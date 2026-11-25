"""Keep airport records whose active dates overlap at least one day in 2024."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/staging/parquet/airports.parquet"
OUTPUT = ROOT / "data/staging/parquet/airports_active_2024.parquet"
ACTIVE_FROM = date(2024, 1, 1)
ACTIVE_THROUGH = date(2024, 12, 31)
DATE_FORMATS = (
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %H:%M:%S",
    "%Y%m%d",
    "%m/%d/%Y",
    "%Y/%m/%d",
)


def parse_date(value) -> date | None:
    """Parse a source date; blank dates represent an open-ended range."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        for date_format in DATE_FORMATS:
            try:
                return datetime.strptime(text, date_format).date()
            except ValueError:
                pass
    raise ValueError(f"Unrecognized airport date value: {text!r}")


def overlaps_2024(start_value, end_value) -> bool:
    """Return whether an inclusive active range overlaps calendar year 2024."""
    start = parse_date(start_value)
    end = parse_date(end_value)
    # A blank start/end is treated as an open-ended range on that side.
    return (start is None or start <= ACTIVE_THROUGH) and (end is None or end >= ACTIVE_FROM)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild the filtered airport Parquet")
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
            "Airport filtering needs pyarrow. Install it with: py -m pip install pyarrow"
        ) from exc

    if OUTPUT.is_file() and not args.force:
        print(f"Already filtered: {OUTPUT.relative_to(ROOT)} (use --force to rebuild)")
        return
    if not INPUT.is_file():
        raise FileNotFoundError(
            f"Missing airport Parquet: {INPUT.relative_to(ROOT)}. "
            "Run scripts/convert_to_parquet.py first."
        )

    source = pq.ParquetFile(INPUT)
    start_index = source.schema_arrow.get_field_index("AIRPORT_START_DATE")
    end_index = source.schema_arrow.get_field_index("AIRPORT_THRU_DATE")
    if start_index < 0 or end_index < 0:
        raise ValueError("Airport Parquet must contain AIRPORT_START_DATE and AIRPORT_THRU_DATE")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    partial = OUTPUT.with_name(OUTPUT.stem + ".part.parquet")
    writer = None
    kept_rows = 0
    dropped_rows = 0
    try:
        writer = pq.ParquetWriter(partial, source.schema_arrow, compression="zstd")
        for batch in source.iter_batches(batch_size=args.batch_size):
            starts = batch.column(start_index).to_pylist()
            ends = batch.column(end_index).to_pylist()
            keep = pa.array(
                [overlaps_2024(start, end) for start, end in zip(starts, ends)],
                type=pa.bool_(),
            )
            filtered = pc.filter(batch, keep)
            kept_rows += filtered.num_rows
            dropped_rows += batch.num_rows - filtered.num_rows
            if filtered.num_rows:
                writer.write_batch(filtered, row_group_size=args.batch_size)

        writer.close()
        writer = None
        result = pq.ParquetFile(partial)
        try:
            output_rows = result.metadata.num_rows
            if output_rows != kept_rows:
                raise RuntimeError(f"Row count mismatch: expected {kept_rows:,}, got {output_rows:,}")
        finally:
            result.close()
        os.replace(partial, OUTPUT)
        print(f"Saved: {OUTPUT.relative_to(ROOT)}")
        print(f"Kept {kept_rows:,} airport records; dropped {dropped_rows:,} outside the 2024 date range.")
    finally:
        if writer is not None:
            writer.close()
        if partial.exists():
            partial.unlink()


if __name__ == "__main__":
    main()
