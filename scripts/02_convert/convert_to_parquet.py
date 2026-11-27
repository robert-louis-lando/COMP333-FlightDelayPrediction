"""Convert BTS ZIPs and the NOAA station CSV to chunk-written Parquet files."""

from __future__ import annotations

import argparse
import csv
import io
import os
from pathlib import Path
import zipfile
from contextlib import contextmanager


ROOT = Path(__file__).resolve().parents[2]
FLIGHT_FILE = "On_Time_Marketing_Carrier_On_Time_Performance_Beginning_January_2018_2024_{}.zip"
CHUNK_SIZE = 50_000


def csv_member(archive: zipfile.ZipFile) -> str:
    """Find the data CSV inside a BTS ZIP (which also contains a readme)."""
    members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
    if len(members) != 1:
        raise ValueError(f"Expected one CSV in ZIP, found {len(members)}")
    return members[0]


def parquet_column_names(open_csv) -> list[str]:
    """Read CSV headers and give any blank or duplicate headers usable names."""
    with open_csv() as text:
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


@contextmanager
def open_zip_csv(zip_path: Path):
    """Open the sole CSV member in a BTS ZIP without extracting it."""
    with zipfile.ZipFile(zip_path) as archive:
        member = csv_member(archive)
        with archive.open(member) as binary, io.TextIOWrapper(
            binary, encoding="utf-8-sig", newline=""
        ) as text:
            yield text


@contextmanager
def open_csv_file(csv_path: Path):
    """Open a plain source CSV as UTF-8 text."""
    with csv_path.open(encoding="utf-8-sig", newline="") as text:
        yield text


def convert_csv(source_label: str, open_csv, parquet_path: Path, force: bool) -> None:
    """Stream a plain or zipped CSV into one Parquet file."""
    if parquet_path.is_file() and not force:
        print(f"Already converted: {parquet_path.relative_to(ROOT)}")
        return
    print(f"Converting: {source_label}")

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
        names = parquet_column_names(open_csv)
        schema = pa.schema([pa.field(name, pa.string()) for name in names])
        with open_csv() as text:
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


def convert_zip(zip_path: Path, parquet_path: Path, force: bool) -> None:
    """Convert one ZIP's CSV into Parquet without extracting it."""
    if not zip_path.is_file():
        raise FileNotFoundError(f"Missing source ZIP: {zip_path.relative_to(ROOT)}")
    convert_csv(zip_path.name, lambda: open_zip_csv(zip_path), parquet_path, force)


def convert_station_inventory(force: bool) -> None:
    """Convert the NOAA station inventory CSV into Parquet."""
    source = ROOT / "data/raw/noaa/stations/ghcnh-station-list.csv"
    if not source.is_file():
        raise FileNotFoundError(f"Missing station inventory CSV: {source.relative_to(ROOT)}")
    convert_csv(
        source.name,
        lambda: open_csv_file(source),
        ROOT / "data/staging/01_converted/ghcnh_stations.parquet",
        force,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild existing Parquet files")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--flights-only", action="store_true", help="convert only flight ZIPs")
    selection.add_argument("--airports-only", action="store_true", help="convert only the airport ZIP")
    selection.add_argument("--stations-only", action="store_true", help="convert only the NOAA station CSV")
    args = parser.parse_args()

    output_dir = ROOT / "data/staging/01_converted"
    convert_all = not (args.flights_only or args.airports_only or args.stations_only)
    if convert_all or args.flights_only:
        print("Converting flight ZIPs one month at a time.")
        for month in range(1, 13):
            month_text = f"{month:02d}"
            zip_path = ROOT / "data/raw/bts/flights" / FLIGHT_FILE.format(month)
            parquet_path = output_dir / f"flights_2024_{month_text}.parquet"
            convert_zip(zip_path, parquet_path, args.force)

    if convert_all or args.airports_only:
        print("Converting the airport ZIP.")
        convert_zip(
            ROOT / "data/raw/bts/airports/T_MASTER_CORD.zip",
            output_dir / "airports.parquet",
            args.force,
        )

    if convert_all or args.stations_only:
        print("Converting the NOAA station inventory CSV.")
        convert_station_inventory(args.force)

    print("Conversion selection complete. Flight months remain separate.")


if __name__ == "__main__":
    main()
