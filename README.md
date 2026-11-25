# COMP333-FlightDelayPrediction

## 1. Download the source ZIPs

From the project root, run:

```powershell
py scripts/download_datasets.py
```

The script downloads the BTS Master Coordinate airport ZIP and 12 monthly
flight ZIPs for January through December 2024. It saves them under
`data/raw/bts/airports/` and `data/raw/bts/flights/`. Existing downloads are
kept; use `py scripts/download_datasets.py --force` to download them again.
The ZIPs are verified and left intact.

## 2. Convert the ZIPs to Parquet

Install the conversion dependencies once:

```powershell
py -m pip install pandas pyarrow
```

Then run:

```powershell
py scripts/convert_to_parquet.py
```

The script reads each CSV directly inside its ZIP in chunks; it does not extract
the CSVs. It writes one Parquet file per flight month and one for airports under
`data/staging/parquet/`. Flight columns are initially stored as text to preserve
the source values. Blank CSV headers are given a generated name. Existing
Parquet files are kept; use `--force` to rebuild them.

