"""Download 2024 NOAA GHCNh observations for stations nearest the top airports."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
STATIONS = ROOT / "data/staging/06_analysis/airports_closest_weather_station.parquet"
OUTPUT_DIR = ROOT / "data/raw/noaa/observations"
NOAA_URL = "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/access/by-year"
YEAR = 2024


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="download the selected station files again")
    args = parser.parse_args()

    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit(
            "This script needs pyarrow. Install it with: python -m pip install pyarrow"
        ) from exc

    if not STATIONS.is_file():
        raise FileNotFoundError(
            f"Missing nearest-station table: {STATIONS.relative_to(ROOT)}. "
            "Run scripts/06_analyze/airport_weather_station_distances.py first."
        )
    table = pq.read_table(STATIONS, columns=["AIRPORT_SEQ_ID", "GHCN_ID", "DISTANCE_RANK"])
    candidates = table.to_pylist()
    if table.num_rows != 30:
        raise ValueError(f"Expected 30 ranked station candidates, found {table.num_rows}")
    by_airport: dict[str, list[dict]] = {}
    for row in candidates:
        if row["AIRPORT_SEQ_ID"] is None or row["GHCN_ID"] is None:
            raise ValueError("Closest-station table contains a missing airport or station ID")
        airport_id = str(row["AIRPORT_SEQ_ID"]).strip()
        row["GHCN_ID"] = str(row["GHCN_ID"]).strip()
        by_airport.setdefault(airport_id, []).append(row)
    if len(by_airport) != 10 or any(
        sorted(row["DISTANCE_RANK"] for row in rows) != [1, 2, 3]
        for rows in by_airport.values()
    ):
        raise ValueError("Expected three ranked candidates for each of 10 airports")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = urllib.request.build_opener()
    client.addheaders = [("User-Agent", "COMP333 weather observation downloader")]
    station_results: dict[str, Path | None] = {}
    airport_station: dict[str, str] = {}

    def fetch_station(station_id: str) -> Path | None:
        if station_id in station_results:
            return station_results[station_id]
        filename = f"GHCNh_{station_id}_{YEAR}.psv"
        output = OUTPUT_DIR / filename
        if output.is_file() and not args.force:
            print(f"Already downloaded: {output.relative_to(ROOT)}")
            station_results[station_id] = output
            return output

        partial = output.with_name(output.name + ".part")
        url = f"{NOAA_URL}/{YEAR}/psv/{filename}"
        try:
            print(f"Downloading: {filename}")
            try:
                with client.open(url, timeout=180) as response:
                    content_type = response.headers.get("Content-Type", "").lower()
                    if "text/html" in content_type:
                        raise ValueError(f"NOAA returned an HTML page for {filename}")
                    expected = response.headers.get("Content-Length")
                    with partial.open("wb") as target:
                        shutil.copyfileobj(response, target)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    print(f"Not available (404): {filename}; trying the next candidate if needed.")
                    station_results[station_id] = None
                    return None
                raise
            if not partial.is_file() or not partial.stat().st_size:
                raise ValueError(f"NOAA returned an empty observation file for {filename}")
            if expected is not None and partial.stat().st_size != int(expected):
                raise ValueError(f"Incomplete NOAA download: {filename}")
            with partial.open("rb") as source:
                first_line = source.readline(4096).decode("utf-8-sig", errors="replace")
            if "|" not in first_line or "STATION" not in first_line.upper():
                raise ValueError(f"Unexpected PSV header in NOAA download: {filename}")
            os.replace(partial, output)
            print(f"Saved: {output.relative_to(ROOT)} ({output.stat().st_size:,} bytes)")
            station_results[station_id] = output
            return output
        finally:
            if partial.exists():
                partial.unlink()

    for airport_id, airport_candidates in by_airport.items():
        for candidate in sorted(airport_candidates, key=lambda row: row["DISTANCE_RANK"]):
            station_id = candidate["GHCN_ID"]
            if fetch_station(station_id) is not None:
                airport_station[airport_id] = station_id
                break

    unresolved = sorted(set(by_airport) - set(airport_station))
    if unresolved:
        raise RuntimeError(
            "No observation file was available among the top three station candidates for "
            f"airport(s): {', '.join(unresolved)}"
        )
    print(f"Weather observations are available for all 10 airports ({YEAR}).")
    for airport_id, station_id in airport_station.items():
        print(f"Airport {airport_id}: using station {station_id}")
    print(f"Fetched or reused {sum(path is not None for path in station_results.values())} unique station files.")


if __name__ == "__main__":
    main()
