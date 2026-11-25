"""Keep the requested flight columns from the filtered flight Parquet."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "data/staging/03_filtered/flights_2024_weather_delay_rule.parquet"
OUTPUT = ROOT / "data/staging/04_reduced/flights_2024_reduced.parquet"
COLUMNS = (
    "FlightDate",
    "OriginAirportSeqID",
    "OriginCityName",
    "OriginStateName",
    "DestAirportSeqID",
    "DestCityName",
    "DestStateName",
    "DepDel15",
    "WeatherDelay",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild the reduced Parquet file")
    parser.add_argument("--batch-size", type=int, default=50_000, help="rows per read batch")
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be greater than zero")

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit(
            "Column reduction needs pyarrow. Install it with: python -m pip install pyarrow"
        ) from exc

    if OUTPUT.is_file() and not args.force:
        print(f"Already reduced: {OUTPUT.relative_to(ROOT)} (use --force to rebuild)")
        return
    if not INPUT.is_file():
        raise FileNotFoundError(
            f"Missing filtered flight Parquet: {INPUT.relative_to(ROOT)}. "
            "Run scripts/04_filter/filter_flights_weather_delay.py first."
        )

    source = pq.ParquetFile(INPUT)
    missing = [name for name in COLUMNS if source.schema_arrow.get_field_index(name) < 0]
    if missing:
        raise ValueError(f"Missing required flight column(s): {', '.join(missing)}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    partial = OUTPUT.with_name(OUTPUT.stem + ".part.parquet")
    schema = pa.schema([source.schema_arrow.field(name) for name in COLUMNS])
    writer = None
    rows_written = 0
    try:
        writer = pq.ParquetWriter(partial, schema, compression="zstd")
        for batch in source.iter_batches(batch_size=args.batch_size, columns=list(COLUMNS)):
            writer.write_batch(batch, row_group_size=args.batch_size)
            rows_written += batch.num_rows

        writer.close()
        writer = None
        result = pq.ParquetFile(partial)
        try:
            if result.schema_arrow.names != list(COLUMNS):
                raise RuntimeError("Reduced Parquet does not have the requested column names and order")
            if result.metadata.num_rows != rows_written:
                raise RuntimeError(
                    f"Row count mismatch: expected {rows_written:,}, got {result.metadata.num_rows:,}"
                )
        finally:
            result.close()
        os.replace(partial, OUTPUT)
        print(f"Saved: {OUTPUT.relative_to(ROOT)}")
        print(f"Kept {rows_written:,} rows and {len(COLUMNS)} requested columns.")
    finally:
        if writer is not None:
            writer.close()
        if partial.exists():
            partial.unlink()


if __name__ == "__main__":
    main()
