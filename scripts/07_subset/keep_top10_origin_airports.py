"""Keep the top ten origin airports and flights originating at those airports."""

from __future__ import annotations

from collections import Counter
import argparse
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FLIGHTS = ROOT / "data/staging/04_reduced/flights_2024_reduced.parquet"
AIRPORTS = ROOT / "data/staging/04_reduced/airports_active_2024_reduced.parquet"
OUTPUT_DIR = ROOT / "data/staging/05_top10"
FLIGHT_OUTPUT = OUTPUT_DIR / "flights_2024_top10_origin_airports.parquet"
AIRPORT_OUTPUT = OUTPUT_DIR / "airports_2024_top10_origin.parquet"
AIRPORT_COLUMNS = (
    "AIRPORT_SEQ_ID",
    "AIRPORT_STATE_NAME",
    "DISPLAY_AIRPORT_NAME",
    "DISPLAY_AIRPORT_CITY_NAME_FULL",
    "LATITUDE",
    "LONGITUDE",
)


def required_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Missing input: {path.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild both top-ten Parquet files")
    parser.add_argument("--batch-size", type=int, default=100_000, help="rows per flight batch")
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be greater than zero")

    try:
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit(
            "This script needs pyarrow. Install it with: python -m pip install pyarrow"
        ) from exc

    required_file(FLIGHTS)
    required_file(AIRPORTS)
    outputs = (FLIGHT_OUTPUT, AIRPORT_OUTPUT)
    if not args.force and all(path.is_file() for path in outputs):
        print("Top-ten Parquet files already exist (use --force to rebuild both).")
        return
    if not args.force and any(path.is_file() for path in outputs):
        raise FileExistsError("Only one top-ten output exists; rerun with --force to rebuild both.")

    airport_table = pq.read_table(AIRPORTS, columns=list(AIRPORT_COLUMNS))
    airport_rows = airport_table.to_pylist()
    airport_by_seq_id = {}
    for row in airport_rows:
        seq_id = str(row["AIRPORT_SEQ_ID"]).strip()
        if not seq_id or seq_id == "None":
            continue
        if seq_id in airport_by_seq_id:
            raise ValueError(f"Duplicate AIRPORT_SEQ_ID in airport Parquet: {seq_id}")
        airport_by_seq_id[seq_id] = row

    flight_source = pq.ParquetFile(FLIGHTS)
    origin_index = flight_source.schema_arrow.get_field_index("OriginAirportSeqID")
    if origin_index < 0:
        raise ValueError("Flight Parquet has no OriginAirportSeqID column")

    origin_counts = Counter()
    for batch in flight_source.iter_batches(
        batch_size=args.batch_size, columns=["OriginAirportSeqID"]
    ):
        origin_counts.update(
            value.strip()
            for value in batch.column(0).to_pylist()
            if value is not None and value.strip()
        )

    matched_counts = {
        seq_id: count for seq_id, count in origin_counts.items() if seq_id in airport_by_seq_id
    }
    top_ten = sorted(
        matched_counts.items(),
        key=lambda item: (
            -item[1],
            str(airport_by_seq_id[item[0]]["DISPLAY_AIRPORT_NAME"] or ""),
            item[0],
        ),
    )[:10]
    if not top_ten:
        raise ValueError("No origin airport sequence IDs matched the airport dataset")

    top_ids = [seq_id for seq_id, _ in top_ten]
    flight_key_type = flight_source.schema_arrow.field("OriginAirportSeqID").type
    flight_key_values = pa.array(top_ids, type=flight_key_type)
    airport_key_index = airport_table.schema.get_field_index("AIRPORT_SEQ_ID")
    airport_key_type = airport_table.schema.field(airport_key_index).type
    airport_key_values = pa.array(top_ids, type=airport_key_type)
    reduced_airports = airport_table.filter(
        pc.is_in(airport_table.column(airport_key_index), value_set=airport_key_values)
    )
    if reduced_airports.num_rows != len(top_ids):
        raise RuntimeError(
            f"Expected {len(top_ids)} top-ten airport rows, found {reduced_airports.num_rows}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    flight_partial = FLIGHT_OUTPUT.with_name(FLIGHT_OUTPUT.stem + ".part.parquet")
    airport_partial = AIRPORT_OUTPUT.with_name(AIRPORT_OUTPUT.stem + ".part.parquet")
    writer = None
    kept_flights = 0
    try:
        writer = pq.ParquetWriter(
            flight_partial, flight_source.schema_arrow, compression="zstd"
        )
        for batch in flight_source.iter_batches(batch_size=args.batch_size):
            keep = pc.is_in(batch.column(origin_index), value_set=flight_key_values)
            selected = pc.filter(batch, keep)
            kept_flights += selected.num_rows
            if selected.num_rows:
                writer.write_batch(selected, row_group_size=args.batch_size)

        writer.close()
        writer = None
        pq.write_table(reduced_airports, airport_partial, compression="zstd")

        flight_check = pq.ParquetFile(flight_partial)
        try:
            actual_flights = flight_check.metadata.num_rows
        finally:
            flight_check.close()
        airport_check = pq.ParquetFile(airport_partial)
        try:
            actual_airports = airport_check.metadata.num_rows
        finally:
            airport_check.close()
        if actual_flights != kept_flights or actual_airports != len(top_ids):
            raise RuntimeError("Top-ten output row-count validation failed")

        os.replace(flight_partial, FLIGHT_OUTPUT)
        os.replace(airport_partial, AIRPORT_OUTPUT)
    finally:
        if writer is not None:
            writer.close()
        for partial in (flight_partial, airport_partial):
            if partial.exists():
                partial.unlink()

    print("Top ten origin airports:")
    for rank, (seq_id, count) in enumerate(top_ten, start=1):
        airport = airport_by_seq_id[seq_id]
        print(
            f"{rank:>2}. {airport['DISPLAY_AIRPORT_NAME']} | "
            f"{airport['DISPLAY_AIRPORT_CITY_NAME_FULL']} | {count:,} flights"
        )
    print(f"Saved {FLIGHT_OUTPUT.relative_to(ROOT)} ({kept_flights:,} flights).")
    print(f"Saved {AIRPORT_OUTPUT.relative_to(ROOT)} ({len(top_ids)} airports).")


if __name__ == "__main__":
    main()
