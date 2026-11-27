"""Calculate distances from the top ten airports to NOAA weather stations."""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AIRPORTS = ROOT / "data/staging/05_top10/airports_2024_top10_origin.parquet"
STATIONS = ROOT / "data/staging/04_reduced/ghcnh_stations_reduced.parquet"
OUTPUT_DIR = ROOT / "data/staging/06_analysis"
DISTANCES = OUTPUT_DIR / "airport_weather_station_distances.parquet"
CLOSEST = OUTPUT_DIR / "airports_closest_weather_station.parquet"
EARTH_RADIUS_KM = 6371.0088


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild both output Parquets")
    parser.add_argument("--batch-size", type=int, default=50_000, help="station rows per batch")
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be greater than zero")

    try:
        import numpy as np
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit(
            "This script needs numpy and pyarrow. Install them with: python -m pip install numpy pyarrow"
        ) from exc

    for path in (AIRPORTS, STATIONS):
        if not path.is_file():
            raise FileNotFoundError(f"Missing input: {path.relative_to(ROOT)}")
    outputs = (DISTANCES, CLOSEST)
    if all(path.is_file() for path in outputs) and not args.force:
        print("Distance Parquets already exist (use --force to rebuild).")
        return
    if any(path.is_file() for path in outputs) and not args.force:
        raise FileExistsError("Only one distance output exists; use --force to rebuild both.")

    airports = pq.read_table(AIRPORTS, columns=["AIRPORT_SEQ_ID", "LATITUDE", "LONGITUDE"])
    if airports.num_rows != 10:
        raise ValueError(f"Expected 10 top airports, found {airports.num_rows}")
    airport_rows = airports.to_pylist()
    airport_ids = [str(row["AIRPORT_SEQ_ID"]).strip() for row in airport_rows]
    if any(not value or value == "None" for value in airport_ids):
        raise ValueError("Top-ten airport data contains a missing AIRPORT_SEQ_ID")
    airport_lat = np.asarray([float(row["LATITUDE"]) for row in airport_rows])[:, None]
    airport_lon = np.asarray([float(row["LONGITUDE"]) for row in airport_rows])[:, None]
    if not np.isfinite(airport_lat).all() or not np.isfinite(airport_lon).all():
        raise ValueError("Top-ten airports must have valid latitude and longitude")
    airport_lat_rad = np.radians(airport_lat)
    airport_lon_rad = np.radians(airport_lon)

    station_file = pq.ParquetFile(STATIONS)
    for name in ("GHCN_ID", "LATITUDE", "LONGITUDE"):
        if station_file.schema_arrow.get_field_index(name) < 0:
            raise ValueError(f"Station Parquet is missing required column: {name}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    distance_part = DISTANCES.with_name(DISTANCES.stem + ".part.parquet")
    closest_part = CLOSEST.with_name(CLOSEST.stem + ".part.parquet")
    pair_schema = pa.schema([
        ("AIRPORT_SEQ_ID", pa.string()),
        ("GHCN_ID", pa.string()),
        ("HAVERSINE_DISTANCE_KM", pa.float64()),
    ])
    candidate_schema = pa.schema([
        ("AIRPORT_SEQ_ID", pa.string()),
        ("GHCN_ID", pa.string()),
        ("HAVERSINE_DISTANCE_KM", pa.float64()),
        ("DISTANCE_RANK", pa.int8()),
    ])
    writer = None
    top_candidates: list[list[tuple[float, str]]] = [[] for _ in range(10)]
    pair_count = 0
    try:
        writer = pq.ParquetWriter(distance_part, pair_schema, compression="zstd")
        for batch in station_file.iter_batches(
            batch_size=args.batch_size, columns=["GHCN_ID", "LATITUDE", "LONGITUDE"]
        ):
            rows = batch.to_pydict()
            ids, lats, lons = [], [], []
            for station_id, latitude, longitude in zip(
                rows["GHCN_ID"], rows["LATITUDE"], rows["LONGITUDE"]
            ):
                try:
                    lat, lon = float(latitude), float(longitude)
                    station_id = str(station_id).strip()
                    if station_id and station_id != "None" and math.isfinite(lat) and math.isfinite(lon):
                        ids.append(station_id)
                        lats.append(lat)
                        lons.append(lon)
                except (TypeError, ValueError):
                    continue
            if not ids:
                continue

            station_lat = np.radians(np.asarray(lats))[None, :]
            station_lon = np.radians(np.asarray(lons))[None, :]
            delta_lat = station_lat - airport_lat_rad
            delta_lon = station_lon - airport_lon_rad
            hav = (np.sin(delta_lat / 2) ** 2 + np.cos(airport_lat_rad)
                   * np.cos(station_lat) * np.sin(delta_lon / 2) ** 2)
            distances = 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(hav, 0.0, 1.0)))
            for i in range(10):
                count = min(3, len(ids))
                indices = np.argpartition(distances[i], count - 1)[:count]
                combined = top_candidates[i] + [
                    (float(distances[i, j]), ids[int(j)]) for j in indices
                ]
                nearest_by_id = {}
                for distance, station_id in combined:
                    nearest_by_id[station_id] = min(
                        distance, nearest_by_id.get(station_id, math.inf)
                    )
                top_candidates[i] = sorted(
                    (distance, station_id) for station_id, distance in nearest_by_id.items()
                )[:3]

            table = pa.Table.from_arrays(
                [pa.array(np.repeat(airport_ids, len(ids))),
                 pa.array(np.tile(ids, 10)),
                 pa.array(distances.reshape(-1))], schema=pair_schema
            )
            writer.write_table(table, row_group_size=args.batch_size * 10)
            pair_count += table.num_rows

        writer.close()
        writer = None
        if not pair_count or any(len(candidates) < 3 for candidates in top_candidates):
            raise ValueError("At least three valid weather stations are required for every airport")
        candidate_rows = [
            (airport_ids[i], station_id, distance, rank)
            for i, candidates in enumerate(top_candidates)
            for rank, (distance, station_id) in enumerate(candidates, start=1)
        ]
        closest_table = pa.Table.from_arrays(
            [
                pa.array([row[0] for row in candidate_rows]),
                pa.array([row[1] for row in candidate_rows]),
                pa.array([row[2] for row in candidate_rows]),
                pa.array([row[3] for row in candidate_rows], type=pa.int8()),
            ],
            schema=candidate_schema,
        )
        pq.write_table(closest_table, closest_part, compression="zstd")
        check = pq.ParquetFile(distance_part)
        try:
            if check.metadata.num_rows != pair_count:
                raise RuntimeError("Distance table row-count validation failed")
        finally:
            check.close()
        check = pq.ParquetFile(closest_part)
        try:
            if check.metadata.num_rows != 30:
                raise RuntimeError("Three-station candidate table must have exactly 30 rows")
        finally:
            check.close()
        os.replace(distance_part, DISTANCES)
        os.replace(closest_part, CLOSEST)
    finally:
        if writer is not None:
            writer.close()
        for partial in (distance_part, closest_part):
            if partial.exists():
                partial.unlink()

    print(f"Saved {DISTANCES.relative_to(ROOT)} ({pair_count:,} airport-station pairs).")
    print(f"Saved {CLOSEST.relative_to(ROOT)} (30 ranked candidate rows).")


if __name__ == "__main__":
    main()
