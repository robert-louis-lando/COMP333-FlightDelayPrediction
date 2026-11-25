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

The script downloads the BTS Master Coordinate airport ZIP, 12 monthly flight
ZIPs for January through December 2024, and the NOAA GHCN hourly station-list
CSV/TXT files. BTS files are saved under `data/raw/bts/`; the station inventory
is saved under `data/raw/noaa/stations/`. Existing downloads are kept; use
`python scripts/01_download/download_datasets.py --force` to download them
again. BTS ZIPs are verified and left intact. If TranStats is unavailable
during a forced airport refresh, the downloader reuses the existing airport
ZIP only if it passes ZIP integrity validation and contains `T_MASTER_CORD.csv`.

To download only one dataset, use one of these mutually exclusive options:

```powershell
python scripts/01_download/download_datasets.py --flights-only
python scripts/01_download/download_datasets.py --airports-only
python scripts/01_download/download_datasets.py --stations-only
```

With no dataset option, the downloader gets all three. The pipeline runner
uses this default. Add `--force` with any option to download that selection
again.

## 2. Convert the datasets to Parquet

Install the conversion dependencies once:

```powershell
python -m pip install pandas pyarrow
```

Then run:

```powershell
python scripts/02_convert/convert_to_parquet.py
```

The script reads CSVs in chunks. It reads flight and airport CSVs directly
inside their ZIPs without extracting them, and converts the NOAA station-list
CSV. It writes one Parquet file per flight month, one for airports, and
`ghcnh_stations.parquet` under `data/staging/01_converted/`. Values are
initially stored as text to preserve source values; blank CSV headers are given
a generated name. Existing Parquet files are kept; use `--force` to rebuild.

To convert just one dataset, use one of these mutually exclusive options:

```powershell
python scripts/02_convert/convert_to_parquet.py --flights-only
python scripts/02_convert/convert_to_parquet.py --airports-only
python scripts/02_convert/convert_to_parquet.py --stations-only
```

With no dataset option, the converter handles all three. The pipeline runner
uses this default.

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
previously requested flight columns plus `DepTime`, which stage 11 needs to
match weather to the actual departure hour. It processes batches, preserves
the filtered row count, and leaves the filtered source file unchanged. Use
`--force` to rebuild the output, or `--batch-size 25000` to use smaller read
batches.

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
the six requested airport columns plus `AIRPORT_COUNTRY_NAME` and
`UTC_LOCAL_TIME_VARIATION`, which stage 11 uses to align UTC weather times to
local departure times. It processes batches, preserves the filtered row
count, and leaves the filtered source unchanged. Use `--force` to rebuild the
output, or `--batch-size 25000` to use smaller read batches.

Reduce the NOAA station inventory with:

```powershell
python scripts/05_reduce/reduce_station_columns.py
```

This reads `data/staging/01_converted/ghcnh_stations.parquet` directly and
writes `data/staging/04_reduced/ghcnh_stations_reduced.parquet` with only
`GHCN_ID`, `LATITUDE`, and `LONGITUDE`. The inventory is not combined or
filtered. Use `--force` to rebuild the output.

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

## 10. Find the nearest weather station for each top-ten airport

Run:

```powershell
python scripts/06_analyze/airport_weather_station_distances.py
```

This calculates Haversine distance in kilometers from each of the 10 selected
airports to every station with a valid ID and coordinates. It writes all pairs
to `data/staging/06_analysis/airport_weather_station_distances.parquet` and
the three nearest station candidates for each airport (30 rows) to
`data/staging/06_analysis/airports_closest_weather_station.parquet`, ranked by
distance in `DISTANCE_RANK`. Use
`--force` to rebuild both outputs or `--batch-size 25000` for smaller batches.

## 08. Download observations for the closest weather stations

Run:

```powershell
python scripts/08_download/download_weather_observations.py
```

This reads the 30-row candidate table and tries stations in distance order for
each airport. If NOAA returns 404 for a station, it tries the next candidate;
it stops for that airport after finding an available 2024 GHCNh PSV file.
Station files are downloaded at most once per run and reused across airports.
Files are saved to `data/raw/noaa/observations/`. Existing files are reused;
add `--force` to download them again. The pipeline runs this after creating the
ranked candidate table.

## 09. Convert and combine weather observations

Run:

```powershell
python scripts/09_combine/combine_weather_observations.py
```

This reads every downloaded 2024 GHCNh PSV file, checks that their columns
match, and appends the rows into
`data/staging/07_weather/weather_observations_2024.parquet`. Source values are
kept as text and the original PSV files are left unchanged. Use `--force` to
rebuild the Parquet or `--batch-size 25000` for smaller read batches. The full
pipeline runs this after the step 08 observation download.

The first 50 rows from the first station file are also available as
`data/preview/weather_observations_first_50.csv` for inspection.

## 10. Reduce weather observation columns

Run:

```powershell
python scripts/10_reduce/reduce_weather_observation_columns.py
```

This keeps `STATION`, `DATE`, `temperature`, `wind_speed`, `visibility`,
`dew_point_temperature`, `station_level_pressure`, `wind_gust`,
`precipitation`, `wet_bulb_temperature`, and `relative_humidity` from the
combined weather Parquet. It writes
`data/staging/07_weather/weather_observations_2024_reduced.parquet` and leaves
the combined source unchanged. Use `--force` to rebuild the output or
`--batch-size 25000` for smaller batches.

## 11. Integrate flights with airports and weather

Run:

```powershell
python scripts/11_integrate/integrate_flight_weather.py
```

This uses the latest top-ten flight and airport Parquets, ranked airport
weather-station links, reduced station inventory, and reduced observations.
It matches `DepTime` to the same local date and hour as the station
observation. NOAA observation timestamps are UTC, while BTS `DepTime` is local
HHMM, so the join applies the airport's UTC offset and 2024 U.S. daylight
saving time where applicable. BTS defines `DepTime` as local HHMM in its
[TranStats field definitions](https://www.transtats.bts.gov/Fields.asp?gnoyr_VQ=FGK),
and NOAA documents GHCNh timestamps as UTC in its
[GHCNh documentation](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh_DOCUMENTATION.pdf).
If there are multiple reports in an hour, it keeps the last report for that
station-hour. The flight-to-weather join is a left join: all flights are kept,
and weather observation fields are null when no same-hour report is available.
The output row count is validated against the input flight count. It writes
`data/staging/08_integrated/flights_airports_weather_2024.parquet`.
Use `--force` to rebuild it or `--batch-size 2500` to use smaller flight
batches.

After adding `DepTime` and airport offsets, refresh the affected intermediate
Parquets before running stage 11:

```powershell
python scripts/05_reduce/reduce_flight_columns.py --force
python scripts/05_reduce/reduce_airport_columns.py --force
python scripts/07_subset/keep_top10_origin_airports.py --force
python scripts/11_integrate/integrate_flight_weather.py --force
```

## Flight-delay classification notebook

Open `notebooks/flight_delay_classification.ipynb` from JupyterLab or VS Code.
It trains a scikit-learn multilayer perceptron using every column from the
stage 11 integrated Parquet as a predictor except `DepDel15`, the target, and
uses a random stratified 80/20 train/test split. It undersamples only the training split to 50/50; the test split keeps the original class proportions. The notebook selects a cutoff
by maximizing F1 on a validation subset from the training data, then evaluates
on the untouched test split. Rows without a usable target are excluded from
supervised training.
## Pipeline folder layout

Scripts are grouped by stage under `scripts/01_download/` through
`scripts/11_integrate/`. Parquet outputs are grouped by stage under
`data/staging/01_converted/`, `02_combined/`, `03_filtered/`, `04_reduced/`,
`05_top10/`, `06_analysis/`, `07_weather/`, and `08_integrated/`. Source data remains under
`data/raw/bts/` and `data/raw/noaa/`.
The earlier WeatherDelay-filter output is preserved in
`data/archive/previous_outputs/`; it is not an input to the current pipeline.

