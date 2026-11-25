# COMP333-FlightDelayPrediction

## Run the full pipeline

Install the dependencies in your virtual environment once:

```powershell
python -m pip install pandas pyarrow
```

With the environment active, run from the project root:

```powershell
python scripts/run_pipeline.py
```

The runner executes the numbered steps below in order and stops if a step
fails. Existing downloads and outputs are reused. Add `--force` to redownload
the ZIPs and rebuild all derived Parquets.

## 1. Download the source ZIPs

From the project root, run:

```powershell
python scripts/01_download/download_datasets.py
```

The script downloads the BTS Master Coordinate airport ZIP and 12 monthly
flight ZIPs for January through December 2024. It saves them under
`data/raw/bts/airports/` and `data/raw/bts/flights/`. Existing downloads are
kept; use `python scripts/01_download/download_datasets.py --force` to download them again.
The ZIPs are verified and left intact.

## 2. Convert the ZIPs to Parquet

Install the conversion dependencies once:

```powershell
python -m pip install pandas pyarrow
```

Then run:

```powershell
python scripts/02_convert/convert_to_parquet.py
```

The script reads each CSV directly inside its ZIP in chunks; it does not extract
the CSVs. It writes one Parquet file per flight month and one for airports under
`data/staging/01_converted/`. Flight columns are initially stored as text to preserve
the source values. Blank CSV headers are given a generated name. Existing
Parquet files are kept; use `--force` to rebuild them.

## 3. Combine the flight months

After all monthly Parquet files exist, run:

```powershell
python scripts/03_combine/combine_flight_parquets.py
```

This combines only the 12 flight files, in month order, into
`data/staging/02_combined/flights_2024_all.parquet`. It reads monthly files from
`data/staging/01_converted/`, streams batches, checks that
the monthly schemas match, and verifies the final row count. It does not change
the monthly files or the airport Parquet. Use `--force` to rebuild the combined
file, or `--batch-size 25000` to use smaller read batches.

## 4. Keep weather-delay flights and flights with no recorded delay cause

After combining the monthly files, run:

```powershell
python scripts/04_filter/filter_flights_weather_delay.py
```

This writes `data/staging/03_filtered/flights_2024_weather_delay_rule.parquet`.
It keeps rows with a nonzero `WeatherDelay`, plus rows where all five delay
cause columns are zero or blank. It drops rows where `WeatherDelay` is zero or
blank and any other delay cause is nonzero. It also removes rows where
`Cancelled` or `Diverted` equals `1`. The combined source file is unchanged.
Use `--force` to rebuild the filtered file, or `--batch-size 25000` to use
smaller read batches.

## 5. Reduce the flight columns

After filtering, run:

```powershell
python scripts/05_reduce/reduce_flight_columns.py
```

This writes `data/staging/04_reduced/flights_2024_reduced.parquet` with only the
nine requested flight columns. It processes batches, preserves the filtered
row count, and leaves the filtered source file unchanged. Use `--force` to
rebuild the output, or `--batch-size 25000` to use smaller read batches.

## 6. Keep airport records active in 2024

Run:

```powershell
python scripts/04_filter/filter_airports_active_2024.py
```

This writes `data/staging/03_filtered/airports_active_2024.parquet`. A record is
kept when its inclusive start/end dates overlap 2024 by at least one day. A
blank start or end date is treated as an open range on that side. The source
airport Parquet is unchanged. Use `--force` to rebuild the output.


## 7. Reduce the airport columns

After filtering airports to records active in 2024, run:

```powershell
python scripts/05_reduce/reduce_airport_columns.py
```

This writes `data/staging/04_reduced/airports_active_2024_reduced.parquet` with
only the six requested airport columns. It processes batches, preserves the
filtered row count, and leaves the filtered source unchanged. Use `--force` to
rebuild the output, or `--batch-size 25000` to use smaller read batches.

## 8. Count flights by origin airport

After reducing both datasets, run:

```powershell
python scripts/06_analyze/top_origin_airports.py
```

The script joins `OriginAirportSeqID` to `AIRPORT_SEQ_ID`, counts matched
flight rows by origin, and prints the top ten airport names, cities, states,
and counts. Counts use the filtered and column-reduced flights.

## 9. Keep only the top ten origin airports and their departures

Run:

```powershell
python scripts/07_subset/keep_top10_origin_airports.py
```

The script recomputes the top ten using the same reduced inputs. It writes
`data/staging/05_top10/flights_2024_top10_origin_airports.parquet` containing
flights whose origin is one of those airports, and
`data/staging/05_top10/airports_2024_top10_origin.parquet` containing the
matching airport records. Destination airports are not used for this filter.
Use `--force` to rebuild both outputs.

## Pipeline folder layout

Scripts are grouped in run order under `scripts/01_download/` through
`scripts/07_subset/`. Parquet outputs are grouped by stage under
`data/staging/01_converted/`, `02_combined/`, `03_filtered/`, `04_reduced/`,
and `05_top10/`. The original ZIP downloads remain under `data/raw/bts/`.
The earlier WeatherDelay-filter output is preserved in
`data/archive/previous_outputs/`; it is not an input to the current pipeline.
