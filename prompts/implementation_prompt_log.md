# Implementation Prompt Log GPT-6-luna medium

### Reorganize scripts and Parquets by pipeline order

**Prompt:**

> Please reorganize the scripts and Parquet files according to the order in which they should run in the pipeline.

**What the LLM produced:** Grouped scripts under numbered stage folders from
`scripts/01_download/` through `scripts/07_subset/`. Moved Parquets into stage
folders under `data/staging/01_converted/` through `05_top10/`, updated script
paths and README commands, and archived the previous WeatherDelay-filter
output under `data/archive/previous_outputs/`.

**Human validation:** Verified the destination folders and individual file moves, reviewed script paths, and searched the scripts and README for outdated flat paths and staging references.

**Human judgment and reason:** Grouped related operations by
dependency stage, kept the airport and flight branches together at filtering
and reduction stages, and preserved the obsolete result in an archive rather
than deleting it. Trying to keep a clean structure and logic file organization so we can easily add to the pipeline.

### Add a runner for the complete pipeline

**Prompt:**

> Please add a way to run the entire pipeline sequentially.

**What the LLM produced:** Added `scripts/run_pipeline.py` to execute the nine
pipeline scripts in dependency order, and documented the setup and command in
the README.

**Human validation:** Reviewed the step order and script paths against the README and pipeline dependencies. Ran the pipeline and validated the numbers at each step to match what they were before.

**Human judgment and reason:** Instead of running each of the step with a command, allow the whole pipeline to be ran sequentially from one script. It also keeps the pipeline order execution.

## Stage 1: Download source datasets

### Make the download steps reproducible

**Prompt:**

> Please create clear, minimal, organized scripts for each download step so I can reproduce the downloads.

**What the LLM produced:** Added `scripts/download_datasets.py` and documented
its command in `README.md`. At this point it downloaded only the selected BTS
airport and flight ZIPs.

**Human validation:** Read the script and README after editing. Run it and verify the output.

**Human judgment and reason:** Kept the downloader self-contained,
standard-library-only, and limited to source ZIP downloads so it would not
silently load or integrate data.

### Download all 12 months

**Prompt:**

> Please update the flight download to include all 12 months.

**What the LLM produced:** Changed the download loop and README to cover
January-December 2024.

**Human validation:** Inspected the updated month range and instructions.
**Human judgment and reason:** At first, it only downloaded the first 6 months of 2024. So I wanted the full 2024 year of flights.

### Inspect ZIP contents and recommend an efficient workflow

**Prompt:**

> What do the ZIP files contain, and what is the most efficient way to use them for later integration and cleaning?

**What the LLM produced:** Inspected the downloaded ZIPs. The airport archive
contains `T_MASTER_CORD.csv` with 32 columns. Each flight ZIP contains a large
monthly CSV and `readme.html`; the flight CSV has 120 headers, including a
blank trailing header and `Operating_Airline ` with a trailing space. The
12 flight CSV members total about 3.75 GB uncompressed. Recommended retaining
the ZIPs as raw inputs and processing in chunks into Parquet.

**Human validation:** Looked into parquet and realized it is much more efficient than a csv or sqlite.

**Human judgment and reason:** Chose parquet/chunked processing
for integration because the expanded source is large. It is way faster than csv, which was attempted earlier.

### Add NOAA weather-station inventory downloads

**Prompt:**

> Please add weather-station downloads to the existing download script. Use the old repository to find the endpoint.

**What the LLM produced:** Extended
`scripts/01_download/download_datasets.py` to download the NOAA GHCN hourly
station inventory CSV and TXT companion under `data/raw/noaa/stations/`.
Updated the README and pipeline runner label.

**Human validation:** Confirmed the station-list endpoint against the old repository download definitions and reviewed the download. Compared with the count that we had got beforehand around 38k-40k rows.

**Human judgment and reason:** Had to download the weather station data.

### Add individual dataset download options

**Prompt:**

> Please add options to download each dataset individually. When run without an option, the pipeline should download all datasets.

**What the LLM produced:** Added mutually exclusive `--flights-only`,
`--airports-only`, and `--stations-only` flags to
`scripts/01_download/download_datasets.py`. With no dataset flag it still
downloads all three selections, as used by the pipeline runner. Updated the
README with examples.

**Human validation:** Checked, tested and ran the script individually and matched with the bulk download.
**Human judgment and reason:** Used explicit `*-only` flags to avoid
ambiguity and kept the default as all datasets so the full pipeline remains
one-command. Makes it easier to download a specific dataset rather than always downloading all of them. Flights dataset takes a couple minutes.

## Stage 2: Convert source files to Parquet

### Separate ZIP downloads from Parquet conversion

**Prompt:**

> Split the workflow into a script that downloads the ZIP files and a separate script that converts them to Parquet. Remove the CSV-combination scripts.

**What the LLM produced:** Removed Excel export from
`scripts/download_datasets.py`; added `scripts/convert_to_parquet.py` to read
each ZIP's CSV in chunks and write a separate Parquet per flight month plus an
airport Parquet. Updated the README.

**Human validation:** Reviewed the implementation and its documented behavior.

**Human judgment and reason:** Want to keep all the scripts seperate in case we want to modify or extend them. Decided to go with parquet because it is much faster to process than csv and much more convenient.

### Add dataset selection to Parquet conversion

**Prompt:**

> Add similar dataset-selection options to the conversion step, and include conversion of the weather-station data to Parquet.

**What the LLM produced:** Added mutually exclusive `--flights-only`,
`--airports-only`, and `--stations-only` flags to
`scripts/02_convert/convert_to_parquet.py`. The converter now writes
`data/staging/01_converted/ghcnh_stations.parquet` from the downloaded NOAA
station CSV. With no selection flag it converts all datasets. Updated the
README and pipeline runner label.

**Human validation:** Reviewed the selection branches, station source/output paths,

**Human judgment and reason:** Reused the chunked CSV-to-Parquet
conversion path for both ZIP members and the plain station CSV, keeping values
as text and avoiding an extracted intermediate file.

## Stage 3: Combine monthly flight Parquets

### Combine monthly flight Parquets

**Prompt:**

> Write a preprocessing script that combines the 12 monthly flight Parquet files into one Parquet file. This applies only to the flight data.

**What the LLM produced:** Added `scripts/combine_flight_parquets.py`. It appends
the 12 monthly flight Parquets in order into
`flights_2024_all.parquet`; the airport Parquet remains separate. Updated the
README.

**Human validation:** Reviewed input paths, batch iteration, matching schemas, and the output row-count check.

**Human judgment and reason:** Wanted to work with one file rather than 12 seperate files containing flights.

## Stage 4: Filter flights

### Filter rows missing WeatherDelay

**Prompt:**

> Write a script for the flight data that removes every row without a value in the `WeatherDelay` column.

**What the LLM produced:** Added `scripts/filter_flights_weather_delay.py` to
write a filtered flight Parquet from the combined flight Parquet.

**Human validation:** Reviewed the implementation and its documented behavior against the request.

**Human judgment and reason:** The reason behind this data reduction is that we are focused on Flights that are either not delayed or are delayed by weather. We aren't interested in flight being delayed for another reason other than weather, therefore all these rows are dropped.

### Revise the WeatherDelay filter rule

**Prompt:**

> Update the script to remove rows where `WeatherDelay` is zero and any of the other four delay types is nonzero. Keep rows when all delay values are zero or missing.

**What the LLM produced:** Changed the filter to retain rows with nonzero
`WeatherDelay` or rows where all five delay-cause fields are zero/blank; it
drops rows with a non-weather cause but no nonzero weather delay. The output
was renamed to `flights_2024_weather_delay_rule.parquet`; README updated.

**Human validation:** Reviewed the implementation and its documented behavior against the request.

**Human judgment and reason:** Interpreted blank as zero for the
delay-rule comparison, retained numeric zero only when no other delay cause is
nonzero.

### Exclude cancelled and diverted rows

**Prompt:**

> Also remove rows where either the `Cancelled` or `Diverted` column has a value of 1.

**What the LLM produced:** Added `Cancelled == 1` and `Diverted == 1` exclusions
to the existing filter and updated the README.

**Human validation:** Confirmed the existing output file and reviewed the updated filter and README command.

**Human judgment and reason:** Exclude flights that were cancelled and diverted since this would contamination the dataset, making long delays, but they are in fact not delays.

### Preview 50 flight rows with all columns

**Prompt:**

> Show me a preview of 50 flight rows with all columns so I can inspect the data.

**What the LLM produced:** Created
`data/preview/january_2024_first_50_flights.csv` containing the first 50 data
rows from the January 2024 ZIP and all 120 original columns.

**Human validation:** The extraction command reported 50 rows, 120 columns, and a 21,817-byte CSV preview. The preview was read directly from the ZIP using the standard CSV reader.

**Human judgment and reason:** Chose CSV as a compact, easy-to-open
preview artifact because printing all 120 columns inline would be unwieldy. Simply, to better visualize the rows and columns with some sample data from the dataset.

## Stage 5: Reduce flight columns

### Reduce the filtered flight data to selected columns

**Prompt:**

> Create a flight-data reduction script that reads the Parquet produced by the flight-filtering script and keeps only these columns: `FlightDate`, `OriginAirportSeqID`, `OriginCityName`, `OriginStateName`, `DestAirportSeqID`, `DestCityName`, `DestStateName`, `DepDel15`, and `WeatherDelay`.

**What the LLM produced:** Added `scripts/reduce_flight_columns.py` to read the
filtered flight Parquet and write
`data/staging/parquet/flights_2024_reduced.parquet` with the nine requested
columns. Added the step to the README.

**Human validation:** Reviewed the input and output paths, selected column names and order, and batch-written schema and row-count checks.

**Human judgment and reason:** Perfoming data reduction and only keeping columns that are deemed relevant for the model and potentially data visualization.

## Stage 6: Filter airports active in 2024

### Keep airport records active during 2024

**Prompt:**

> Write a script that filters the airport Parquet using `AIRPORT_START_DATE` and `AIRPORT_THRU_DATE`. Keep records whose active date range overlaps 2024 by at least one day.

**What the LLM produced:** Added
`scripts/filter_airports_active_2024.py` to filter airport Parquet records by
date-range overlap and write `airports_active_2024.parquet`. Added the command
and behavior to the README.

**Human validation:** Inspected the airport source headers and confirmed the Parquet
file exists. Reviewed the inclusive overlap condition and output validation

**Human judgment and reason:** We only care about flights in 2024. Therefore, we only care about airports which were in service during 2024, if not then dropped.

## Stage 7: Reduce airport and station columns

### Reduce the filtered airport data to selected columns

**Prompt:**

> Reduce the filtered airport Parquet by keeping only these columns: `AIRPORT_SEQ_ID`, `AIRPORT_STATE_NAME`, `DISPLAY_AIRPORT_NAME`, `DISPLAY_AIRPORT_CITY_NAME_FULL`, `LATITUDE`, and `LONGITUDE`.

**What the LLM produced:** Added `scripts/reduce_airport_columns.py` to read the
2024-active airport Parquet and write
`data/staging/parquet/airports_active_2024_reduced.parquet` with the six
requested columns. Added the command to the README.

**Human validation:** Confirmed no output file with that name existed and reviewed
the input path, requested columns/order, and output row-count/schema checks.

**Human judgment and reason:** Lots of uncessary columns in the airport dataset therefore, reduced them to the relevant ones for the model training and the potential data visualization.

### Reduce the station inventory to ID and coordinates

**Prompt:**

> The weather-station inventory does not need a combine or filter step. Create a reduction script that keeps only `GHCN_ID`, `LATITUDE`, and `LONGITUDE`.

**What the LLM produced:** Added
`scripts/05_reduce/reduce_station_columns.py` to select `GHCN_ID`, `LATITUDE`,
and `LONGITUDE` from the converted station inventory and write
`data/staging/04_reduced/ghcnh_stations_reduced.parquet`. Added the reducer to
the pipeline runner and README.

**Human validation:** Reviewed the input path, requested column names/order

**Human judgment and reason:** Reduced the columns to what is relevant and all we need is coordinates for location and id to know which weather observation is tied to the station.

## Stage 8: Analyze top origin airports

### Join origin flights to airports and print the top ten

**Prompt:**

> Write a script that joins flights to airports using the airport sequence ID for the flight origin. Print the 10 airports with the most originating flights and each airport's flight count.

**What the LLM produced:** Added `scripts/top_origin_airports.py`. It counts
origin sequence IDs from the reduced flight Parquet in batches, matches those
counts to the reduced airport Parquet by sequence ID, and prints the ten
highest airport counts. Updated the README with the run command.

**Human validation:** Checked if the script makes sense, also that the top ten airports make sense.

**Human judgment and reason:** This is in the goal of cutting down the number of flights to only those of the top 10 airports.

## Stage 9: Select top-ten origin airports and flights

### Keep only the top ten origin airports and their flights

**Prompt:**

> Create a follow-up script that keeps only the top 10 airports and the flights originating from those airports.

**What the LLM produced:** Added `scripts/keep_top10_origin_airports.py`. It
recomputes the top ten from the reduced inputs, writes a flight Parquet for
departures from those airport sequence IDs, and writes a second Parquet with
only the matching airport records. Updated the README.

**Human validation:** Reviewed that both outputs use the same top-ten sequence IDs,
that flight rows are filtered by origin only, and that output row counts are

**Human judgment and reason:** There is too much data, therefore we decided to cut down by taking the 10 most popular( most flights) airports to simply reduce processing time.(there is too many flights so we cut down to have 1.9million flights)

## Stage 10: Calculate airport-to-station distances

### Calculate airport-to-weather-station distances

**Prompt:**

> Add a script to the analysis stage that calculates Haversine distances between the 10 selected airports and the weather stations. Write a Parquet linking table with the airport sequence ID, weather-station ID, and distance. Also write a second Parquet containing only the closest station for each airport, with 10 rows total.

**What the LLM produced:** Added `scripts/06_analyze/airport_weather_station_distances.py`. It writes an all-pairs Haversine distance table and a second 10-row table with the closest station per airport. Added the distance step to the pipeline runner and documented both outputs in the README.

**Human validation:** Reviewed the implementation and its documented behavior.

**Human judgment and reason:** The reason behind this decision is that we needed to match our 10 airports to a weather station. We decided to use the haversine algorithm to calculate the distance between airport and weather station. Make a linking table which would contain airport + closest weather station and its distance.

## Stage 11: Download weather observations

### Download weather observations for the closest stations

**Prompt:**

> Add a pipeline step to download weather observations for the 10 closest weather stations.

**What the LLM produced:** Added `scripts/08_download/download_weather_observations.py` to read the closest-station Parquet and download each unique station's 2024 NOAA GHCNh PSV observations. Added the downloader to the full pipeline and documented its command, output folder, and `--force` option in the README. The next prompt updated this to ranked fallback candidates.

**Human validation:** Reviewed the implementation and its documented behavior.

**Human judgment and reason:** Need to download the weather observation data based on the "selected" weather station from our linking table.

### Keep three ranked stations per airport and fall back on 404

**Prompt:**

> Update the airport-to-station linking Parquet to keep the three closest stations for each airport, for 30 rows total. During downloads, if a station returns a 404, try the next station by distance priority. Download each station's observation file only once, even if it is linked to multiple airports.

**What the LLM produced:** Updated the candidate Parquet to contain three stations per airport (30 rows), ranked by distance with `DISTANCE_RANK`. Updated the step 08 downloader to try ranks in order, skip 404 stations, and reuse successful downloads so each station file is fetched at most once per run.

**Human validation:** Reviewed the implementation and its documented behavior.

**Human judgment and reason:** A station may be nearest to multiple airports, so the downloader shares one successfully fetched local station file among them. Each airport uses its first available candidate.

## Stage 12: Combine weather observations

### Convert and combine weather observations

**Prompt:**

> Add a pipeline step that converts and combines the weather observations into a single Parquet file.

**What the LLM produced:** Added `scripts/09_combine/combine_weather_observations.py` to convert the downloaded 2024 station PSV files and append their rows into `data/staging/07_weather/weather_observations_2024.parquet`. Added this as the next step in the pipeline and documented its command and output.

**Human validation:** Reviewed the implementation and its documented behavior.

**Human judgment and reason:** Converting for convenience and also did it for all the other datasets.

## Stage 13: Reduce weather observation columns

### Reduce weather observation columns

**Prompt:**

> Add a pipeline step to reduce the weather-observation Parquet. Keep only these columns: `STATION`, `DATE`, `temperature`, `wind_speed`, `visibility`, `dew_point_temperature`, `station_level_pressure`, `wind_gust`, `precipitation`, `wet_bulb_temperature`, and `relative_humidity`.

**What the LLM produced:** Added `scripts/10_reduce/reduce_weather_observation_columns.py` to write `data/staging/07_weather/weather_observations_2024_reduced.parquet` with only the 11 requested columns. Added the reducer as the final pipeline step and documented its command and output in README.

**Human validation:** Reviewed the implementation and its documented behavior.

**Human judgment and reason:** Reducing the weather observation table to only the relevant columns for model training.

## Stage 14: Integrate flights, airports, and weather

### Integrate flights, airports, station links, stations, and observations

**Prompt:**

> Create a pipeline script that integrates the latest Parquet outputs for flights, airports, the airport-to-weather-station linking table, the 10 weather stations, and weather observations.

**What the LLM produced:** Added `scripts/11_integrate/integrate_flight_weather.py` to join the latest top-ten flights and airports, ranked airport-station links, reduced station inventory, and reduced observations into `data/staging/08_integrated/flights_airports_weather_2024.parquet`. Added it to the pipeline and documented its inputs and output.

**Human validation:** Reviewed the implementation and its documented behavior.

**Human judgment and reason:** Want to "integrate" which really means just join all the tables into one big table so we can then train on the data.

### Keep flights without same-hour weather matches

**Prompt:**

> Keep flights without a matching weather observation by using a left join. Leave the weather columns null when no observation matches.

**What the LLM produced:** Changed the flight-to-weather join in stage 11 to a left join and stopped filtering out flights with missing or invalid departure join keys. Weather observation fields remain null when there is no same-hour match. Added a check that integrated row count equals the flight input row count and updated the README.

**Human validation:** Reviewed the implementation and its documented behavior.

**Human judgment and reason:** Preserve all flight rows as requested while retaining null weather values when the selected station has no observation for that flight's local departure hour.

## Stage 15: Classify flight delays

### Correct target and use stratified random train/test split

**Prompt:**

> Use scikit-learn's `train_test_split` with `test_size=0.2`, `random_state=42`, and `stratify=y` instead of splitting by month. This should preserve the proportions of delayed and non-delayed flights while keeping the split random. Train directly on the integrated Parquet without additional data cleaning or preprocessing.

**What the LLM produced:** Revised `notebooks/flight_delay_classification.ipynb` to require `DepDel15`, load features only from the stage 11 integrated Parquet, and use the requested scikit-learn stratified 80/20 random split with `random_state=42`. Removed month-based splitting, date-derived features, imputation, categorical encoding, and the earlier preprocessing pipeline. The numeric `HistGradientBoostingClassifier` handles missing feature values as-is. Updated the README description.

**Human validation:** Reviewed the implementation and its documented behavior.

**Human judgment and reason:** It was splitting the dataset into train(first 10months) and test (last 2 months), this could skew the distributions and isn't random at all.

### Use a neural network classifier

**Prompt:**

> Use a neural network classifier instead.

**What the LLM produced:** Replaced the gradient-boosting classifier with scikit-learn's `MLPClassifier` neural network. Kept all integrated columns except `DepDel15` as predictors, the `DepDel15` target, stratified random 80/20 split, and the evaluation metrics. Added a training-only preprocessing pipeline for numeric imputation/scaling and categorical imputation/one-hot encoding. Cleared prior notebook outputs.

**Human validation:** Reviewed the implementation and its documented behavior

**Human judgment and reason:** Tested with a HistGradientBoostingClassifier, but the result were really lacking. So decided to try a neural network.

### Tune the classification threshold

**Prompt:**

> Add threshold tuning to the classifier.

**What the LLM produced:** Updated the notebook to reserve a stratified validation subset from the training data, select the probability threshold that maximizes validation F1, refit the neural network on the full training split, and evaluate the selected threshold on the untouched test split. Updated the README and cleared notebook outputs.

**Human validation:** Reviewed the implementation and its documented behavior.

**Human judgment and reason:** Maximizing F1 balances precision and recall as a starting point for the user's concern about missed delayed flights. The test split remains out of threshold selection to keep evaluation independent.

### Balance the training split while preserving test proportions

**Prompt:**

> Keep the original class proportions in the test set, and balance the training set to 50% delayed and 50% non-delayed flights.

**What the LLM produced:** Added random undersampling after the stratified train/test split to make `X_train` and `y_train` 50/50 delayed and non-delayed. Left `X_test` and `y_test` unchanged, so test proportions remain the original stratified proportions. Updated the README and cleared notebook outputs.

**Human validation:** Reviewed the implementation and its documented behavior.

**Human judgment and reason:** Used undersampling to make training 50/50 without synthesizing or duplicating examples. This discards some non-delayed training rows but preserves the full, naturally distributed test split for evaluation.
