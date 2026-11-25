"""Combine the 12 monthly flight Parquet files into one annual Parquet file."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARQUET_DIR = ROOT / "data/staging/parquet"
OUTPUT = PARQUET_DIR / "flights_2024_all.parquet"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild the combined Parquet file")
    parser.add_argument("--batch-size", type=int, default=50_000, help="rows per read batch")
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be greater than zero")

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit(
            "Combining Parquet files needs pyarrow. Install it with: py -m pip install pyarrow"
        ) from exc

    if OUTPUT.is_file() and not args.force:
        print(f"Already combined: {OUTPUT.relative_to(ROOT)} (use --force to rebuild)")
        return

    inputs = [PARQUET_DIR / f"flights_2024_{month:02d}.parquet" for month in range(1, 13)]
    missing = [path for path in inputs if not path.is_file()]
    if missing:
        paths = "\n".join(f"  - {path.relative_to(ROOT)}" for path in missing)
        raise FileNotFoundError(f"Missing monthly Parquet input(s):\n{paths}")

    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    partial = OUTPUT.with_name(OUTPUT.stem + ".part.parquet")
    writer = None
    expected_schema = None
    expected_rows = 0
    try:
        for path in inputs:
            source = pq.ParquetFile(path)
            if expected_schema is None:
                expected_schema = source.schema_arrow
                writer = pq.ParquetWriter(partial, expected_schema, compression="zstd")
            elif not source.schema_arrow.equals(expected_schema, check_metadata=False):
                raise ValueError(f"Parquet schema does not match the other months: {path.name}")

            expected_rows += source.metadata.num_rows
            print(f"Appending {path.name} ({source.metadata.num_rows:,} rows)")
            for batch in source.iter_batches(batch_size=args.batch_size):
                writer.write_batch(batch, row_group_size=args.batch_size)

        writer.close()
        writer = None
        actual_rows = pq.ParquetFile(partial).metadata.num_rows
        if actual_rows != expected_rows:
            raise RuntimeError(f"Row count mismatch: expected {expected_rows:,}, got {actual_rows:,}")
        os.replace(partial, OUTPUT)
        print(f"Saved {OUTPUT.relative_to(ROOT)} ({actual_rows:,} rows)")
    finally:
        if writer is not None:
            writer.close()
        if partial.exists():
            partial.unlink()


if __name__ == "__main__":
    main()
