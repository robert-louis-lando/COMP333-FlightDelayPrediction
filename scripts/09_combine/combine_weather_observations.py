"""Convert and combine the downloaded 2024 NOAA observation PSV files."""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INPUT_DIR = ROOT / "data/raw/noaa/observations"
OUTPUT = ROOT / "data/staging/07_weather/weather_observations_2024.parquet"


def read_header(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        names = next(csv.reader(source, delimiter="|"), [])
    if not names or "STATION" not in names or "DATE" not in names:
        raise ValueError(f"Unexpected NOAA observation header in {path.name}")
    if len(names) != len(set(names)):
        raise ValueError(f"Duplicate column names in {path.name}")
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild the combined Parquet")
    parser.add_argument("--batch-size", type=int, default=50_000, help="rows per read batch")
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be greater than zero")

    try:
        import pandas as pd
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit(
            "Weather Parquet conversion needs pandas and pyarrow. "
            "Install them with: python -m pip install pandas pyarrow"
        ) from exc

    if OUTPUT.is_file() and not args.force:
        print(f"Already combined: {OUTPUT.relative_to(ROOT)} (use --force to rebuild)")
        return
    files = sorted(INPUT_DIR.glob("GHCNh_*_2024.psv"))
    if not files:
        raise FileNotFoundError(
            f"No 2024 NOAA observation PSV files found in {INPUT_DIR.relative_to(ROOT)}. "
            "Run scripts/08_download/download_weather_observations.py first."
        )

    columns = read_header(files[0])
    mismatched = [path.name for path in files[1:] if read_header(path) != columns]
    if mismatched:
        raise ValueError("NOAA observation files have mismatched schemas: " + ", ".join(mismatched))
    schema = pa.schema([pa.field(name, pa.string()) for name in columns])

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    partial = OUTPUT.with_name(OUTPUT.stem + ".part.parquet")
    writer = None
    expected_rows = 0
    try:
        writer = pq.ParquetWriter(partial, schema, compression="zstd")
        for path in files:
            print(f"Converting and appending: {path.name}")
            chunks = pd.read_csv(
                path,
                sep="|",
                dtype="string",
                keep_default_na=False,
                na_filter=False,
                chunksize=args.batch_size,
                encoding="utf-8-sig",
            )
            for chunk in chunks:
                table = pa.Table.from_pandas(chunk, schema=schema, preserve_index=False)
                writer.write_table(table, row_group_size=args.batch_size)
                expected_rows += table.num_rows

        writer.close()
        writer = None
        check = pq.ParquetFile(partial)
        try:
            if check.metadata.num_rows != expected_rows:
                raise RuntimeError(
                    f"Row-count mismatch: expected {expected_rows:,}, "
                    f"got {check.metadata.num_rows:,}"
                )
            if check.schema_arrow.names != columns:
                raise RuntimeError("Combined weather Parquet schema validation failed")
        finally:
            check.close()
        os.replace(partial, OUTPUT)
    finally:
        if writer is not None:
            writer.close()
        if partial.exists():
            partial.unlink()

    print(
        f"Saved {OUTPUT.relative_to(ROOT)} ({expected_rows:,} rows, "
        f"{len(columns)} columns, {len(files)} station files)."
    )


if __name__ == "__main__":
    main()
