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

## 3. Combine the flight months

After all monthly Parquet files exist, run:

```powershell
py scripts/combine_flight_parquets.py
```

This combines only the 12 flight files, in month order, into
`data/staging/parquet/flights_2024_all.parquet`. It streams batches, checks that
the monthly schemas match, and verifies the final row count. It does not change
the monthly files or the airport Parquet. Use `--force` to rebuild the combined
file, or `--batch-size 25000` to use smaller read batches.

## 4. Keep weather-delay flights and flights with no recorded delay cause

After combining the monthly files, run:

```powershell
py scripts/filter_flights_weather_delay.py
```

This writes `data/staging/parquet/flights_2024_weather_delay_rule.parquet`.
It keeps rows with a nonzero `WeatherDelay`, plus rows where all five delay
cause columns are zero or blank. It drops rows where `WeatherDelay` is zero or
blank and any other delay cause is nonzero. It also removes rows where
`Cancelled` or `Diverted` equals `1`. The combined source file is unchanged.
Use `--force` to rebuild the filtered file, or `--batch-size 25000` to use
smaller read batches.

## 5. Reduce the flight columns

After filtering, run:

```powershell
py scripts/reduce_flight_columns.py
```

This writes `data/staging/parquet/flights_2024_reduced.parquet` with only the
nine requested flight columns. It processes batches, preserves the filtered
row count, and leaves the filtered source file unchanged. Use `--force` to
rebuild the output, or `--batch-size 25000` to use smaller read batches.

## 6. Keep airport records active in 2024

Run:

```powershell
py scripts/filter_airports_active_2024.py
```

This writes `data/staging/parquet/airports_active_2024.parquet`. A record is
kept when its inclusive start/end dates overlap 2024 by at least one day. A
blank start or end date is treated as an open range on that side. The source
airport Parquet is unchanged. Use `--force` to rebuild the output.


## 7. Reduce the airport columns

After filtering airports to records active in 2024, run:

```powershell
py scripts/reduce_airport_columns.py
```

This writes `data/staging/parquet/airports_active_2024_reduced.parquet` with
only the six requested airport columns. It processes batches, preserves the
filtered row count, and leaves the filtered source unchanged. Use `--force` to
rebuild the output, or `--batch-size 25000` to use smaller read batches.

