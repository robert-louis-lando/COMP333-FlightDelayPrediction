# Pipeline data sources

Raw downloads and generated datasets are not checked into Git. To recreate them, install `pandas` and `pyarrow`, then run `python scripts/run_pipeline.py` from the repository root. The downloader reuses files that are already present.

## Initial downloads

[`scripts/01_download/download_datasets.py`](../scripts/01_download/download_datasets.py) fetches these public sources:

| Publisher | Dataset and source | Local destination |
| --- | --- | --- |
| U.S. Bureau of Transportation Statistics (BTS), TranStats | **Marketing Carrier On-Time Performance (Beginning January 2018)** — 12 monthly flight ZIPs for January–December **2024**, from the [TranStats PREZIP archive](https://www.transtats.bts.gov/PREZIP/). See the [January 2024 ZIP](https://www.transtats.bts.gov/PREZIP/On_Time_Marketing_Carrier_On_Time_Performance_Beginning_January_2018_2024_1.zip) for an example. | `data/raw/bts/flights/` |
| BTS, TranStats | **Master Coordinate** airport table — downloaded as a ZIP by submitting the [TranStats download form](https://www.transtats.bts.gov/DL_SelectFields.aspx?QO_fu146_anzr=N8vn6v10+f722146+gnoyr5&gnoyr_VQ=FLL) with all fields, geographies, years, and periods selected. Airport records active in 2024 are selected later in the pipeline. | `data/raw/bts/airports/T_MASTER_CORD.zip` |
| NOAA National Centers for Environmental Information (NCEI) | **Global Historical Climatology Network hourly (GHCNh) station inventory** — [CSV station list](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-station-list.csv) and [TXT station list](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-station-list.txt). The pipeline converts the CSV and retains the TXT as downloaded. | `data/raw/noaa/stations/` |

The flight ZIP filenames follow `On_Time_Marketing_Carrier_On_Time_Performance_Beginning_January_2018_2024_{month}.zip`, where `{month}` is `1` through `12` without zero padding.

## Weather observations downloaded later

[`scripts/08_download/download_weather_observations.py`](../scripts/08_download/download_weather_observations.py) fetches the hourly observations after the pipeline ranks weather stations for each of the ten origin airports. These files come from NOAA NCEI's [GHCNh 2024 PSV archive](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/access/by-year/2024/psv/): `GHCNh_{station_id}_2024.psv`, saved in `data/raw/noaa/observations/`. If a station's 2024 file is unavailable (HTTP 404), the downloader tries the next ranked candidate.

See the [NOAA GHCNh documentation](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh_DOCUMENTATION.pdf) for observation fields and units. Derived Parquets under `data/staging/` are generated locally and are not a separate source.
