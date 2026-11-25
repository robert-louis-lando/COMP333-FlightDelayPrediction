"""Convert the BTS ZIP datasets to separate, chunk-written Parquet files."""

from __future__ import annotations

import argparse
import csv
import io
import os
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[2]
FLIGHT_FILE = "On_Time_Marketing_Carrier_On_Time_Performance_Beginning_January_2018_2024_{}.zip"
CHUNK_SIZE = 50_000


def csv_member(archive: zipfile.ZipFile) -> str:
    """Find the data CSV inside a BTS ZIP (which also contains a readme)."""
    members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
    if len(members) != 1:
        raise ValueError(f"Expected one CSV in ZIP, found {len(members)}")
    return members[0]


def parquet_column_names(zip_path: Path, member: str) -> list[str]:
    """Read CSV headers and give any blank or duplicate headers usable names."""
    with zipfile.ZipFile(zip_path) as archive:
        with archive.open(member) as binary, io.TextIOWrapper(
            binary, encoding="utf-8-sig", newline=""
        ) as text:
            original_names = next(csv.reader(text))

    names = []
    used = set()
    for index, original in enumerate(original_names, start=1):
        base = original or f"unnamed_column_{index}"
        name = base
        suffix = 2
        while name in used:
            name = f"{base}_{suffix}"
            suffix += 1
        names.append(name)
        used.add(name)
    return names


def convert_zip(zip_path: Path, parquet_path: Path, force: bool) -> None:
    """Stream one ZIP's CSV into Parquet without extracting the CSV."""
    if parquet_path.is_file() and not force:
        print(f"Already converted: {parquet_path.relative_to(ROOT)}")
        return
    if not zip_path.is_file():
        raise FileNotFoundError(f"Missing source ZIP: {zip_path.relative_to(ROOT)}")
    print(f"Converting: {zip_path.name}")

    try:
        import pandas as pd
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit(
            "Parquet conversion needs pandas and pyarrow. Install them with: "
            "python -m pip install pandas pyarrow"
        ) from exc

    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = parquet_path.with_name(parquet_path.stem + ".part.parquet")
    writer = None
    try:
        with zipfile.ZipFile(zip_path) as archive:
            member = csv_member(archive)
        names = parquet_column_names(zip_path, member)
        schema = pa.schema([pa.field(name, pa.string()) for name in names])
        with zipfile.ZipFile(zip_path) as archive:
            with archive.open(member) as binary, io.TextIOWrapper(
                binary, encoding="utf-8-sig", newline=""
            ) as text:
                chunks = pd.read_csv(
                    text,
                    header=0,
                    names=names,
                    dtype="string",
                    keep_default_na=False,
                    na_filter=False,
                    chunksize=CHUNK_SIZE,
                )
                writer = pq.ParquetWriter(partial_path, schema, compression="zstd")
                for chunk in chunks:
                    table = pa.Table.from_pandas(chunk, schema=schema, preserve_index=False)
                    writer.write_table(table, row_group_size=CHUNK_SIZE)

        writer.close()
        writer = None
        os.replace(partial_path, parquet_path)
        print(f"Saved: {parquet_path.relative_to(ROOT)}")
    finally:
        if writer is not None:
            writer.close()
        if partial_path.exists():
            partial_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild existing Parquet files")
    args = parser.parse_args()

    output_dir = ROOT / "data/staging/01_converted"
    print("Converting flight ZIPs one month at a time.")
    for month in range(1, 13):
        month_text = f"{month:02d}"
        zip_path = ROOT / "data/raw/bts/flights" / FLIGHT_FILE.format(month)
        parquet_path = output_dir / f"flights_2024_{month_text}.parquet"
        convert_zip(zip_path, parquet_path, args.force)

    print("Converting the airport ZIP.")
    convert_zip(
        ROOT / "data/raw/bts/airports/T_MASTER_CORD.zip",
        output_dir / "airports.parquet",
        args.force,
    )
    print("Done. Each month remains a separate Parquet file; no months were combined.")


if __name__ == "__main__":
    main()
