"""Filter flights by delay causes and remove cancelled or diverted flights."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "data/staging/02_combined/flights_2024_all.parquet"
OUTPUT = ROOT / "data/staging/03_filtered/flights_2024_weather_delay_rule.parquet"
DELAY_CAUSE_COLUMNS = (
    "WeatherDelay",
    "CarrierDelay",
    "NASDelay",
    "SecurityDelay",
    "LateAircraftDelay",
)
STATUS_COLUMNS = ("Cancelled", "Diverted")


def numeric_values(batch, index: int, pa, pc):
    """Read blank/null numeric strings as zero for filter comparisons."""
    value = pc.utf8_trim_whitespace(pc.fill_null(batch.column(index), ""))
    value = pc.if_else(pc.equal(value, ""), "0", value)
    return pc.cast(value, pa.float64(), safe=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild the filtered Parquet file")
    parser.add_argument("--batch-size", type=int, default=50_000, help="rows per read batch")
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be greater than zero")

    try:
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit(
            "Filtering Parquet files needs pyarrow. Install it with: python -m pip install pyarrow"
        ) from exc

    if OUTPUT.is_file() and not args.force:
        print(f"Already filtered: {OUTPUT.relative_to(ROOT)} (use --force to rebuild)")
        return
    if not INPUT.is_file():
        raise FileNotFoundError(
            f"Missing combined flight Parquet: {INPUT.relative_to(ROOT)}. "
            "Run scripts/03_combine/combine_flight_parquets.py first."
        )

    source = pq.ParquetFile(INPUT)
    column_indexes = {
        name: source.schema_arrow.get_field_index(name)
        for name in (*DELAY_CAUSE_COLUMNS, *STATUS_COLUMNS)
    }
    missing_columns = [name for name, index in column_indexes.items() if index < 0]
    if missing_columns:
        raise ValueError(f"Missing delay-cause column(s): {', '.join(missing_columns)}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    partial = OUTPUT.with_name(OUTPUT.stem + ".part.parquet")
    writer = None
    kept_rows = 0
    dropped_rows = 0
    try:
        writer = pq.ParquetWriter(partial, source.schema_arrow, compression="zstd")
        for batch in source.iter_batches(batch_size=args.batch_size):
            nonzero = {}
            for name, index in column_indexes.items():
                nonzero[name] = pc.not_equal(numeric_values(batch, index, pa, pc), 0.0)

            any_nonzero_delay = pc.or_(
                pc.or_(nonzero["WeatherDelay"], nonzero["CarrierDelay"]),
                pc.or_(
                    pc.or_(nonzero["NASDelay"], nonzero["SecurityDelay"]),
                    nonzero["LateAircraftDelay"],
                ),
            )
            # Keep rows with nonzero WeatherDelay, plus rows where every cause is
            # zero or blank. This drops other-cause delays without weather delay.
            delay_keep = pc.or_(nonzero["WeatherDelay"], pc.invert(any_nonzero_delay))
            status_keep = pc.and_(
                pc.not_equal(numeric_values(batch, column_indexes["Cancelled"], pa, pc), 1.0),
                pc.not_equal(numeric_values(batch, column_indexes["Diverted"], pa, pc), 1.0),
            )
            keep = pc.and_(delay_keep, status_keep)
            filtered = pc.filter(batch, keep)
            kept_rows += filtered.num_rows
            dropped_rows += batch.num_rows - filtered.num_rows
            if filtered.num_rows:
                writer.write_batch(filtered, row_group_size=args.batch_size)

        writer.close()
        writer = None
        output_rows = pq.ParquetFile(partial).metadata.num_rows
        if output_rows != kept_rows:
            raise RuntimeError(f"Row count mismatch: expected {kept_rows:,}, got {output_rows:,}")
        os.replace(partial, OUTPUT)
        print(f"Saved: {OUTPUT.relative_to(ROOT)}")
        print(
            f"Kept {kept_rows:,} rows; dropped {dropped_rows:,} rows with "
            "a non-weather delay cause without weather delay, or Cancelled/Diverted equal to 1."
        )
    finally:
        if writer is not None:
            writer.close()
        if partial.exists():
            partial.unlink()


if __name__ == "__main__":
    main()
