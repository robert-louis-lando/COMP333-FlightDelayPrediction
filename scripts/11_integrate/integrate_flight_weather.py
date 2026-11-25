"""Join the latest flight, airport, station-link, station, and weather Parquets."""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FLIGHTS = ROOT / "data/staging/05_top10/flights_2024_top10_origin_airports.parquet"
AIRPORTS = ROOT / "data/staging/05_top10/airports_2024_top10_origin.parquet"
LINKS = ROOT / "data/staging/06_analysis/airports_closest_weather_station.parquet"
STATIONS = ROOT / "data/staging/04_reduced/ghcnh_stations_reduced.parquet"
OBSERVATIONS = ROOT / "data/staging/07_weather/weather_observations_2024_reduced.parquet"
OUTPUT = ROOT / "data/staging/08_integrated/flights_airports_weather_2024.parquet"
WEATHER_COLUMNS = (
    "STATION",
    "DATE",
    "temperature",
    "wind_speed",
    "visibility",
    "dew_point_temperature",
    "station_level_pressure",
    "wind_gust",
    "precipitation",
    "wet_bulb_temperature",
    "relative_humidity",
)
AIRPORT_OUTPUT_COLUMNS = (
    "AirportCountryName",
    "AirportStateName",
    "AirportName",
    "AirportCityName",
    "AirportLatitude",
    "AirportLongitude",
    "AirportUTCOffset",
)
LINK_OUTPUT_COLUMNS = (
    "WeatherStationID",
    "AirportWeatherStationDistanceKm",
    "WeatherStationPriority",
)
STATION_OUTPUT_COLUMNS = ("WeatherStationLatitude", "WeatherStationLongitude")
OBSERVATION_LOCAL_TIME_COLUMN = "WeatherObservationLocalDateTime"


def nth_sunday(year: int, month: int, occurrence: int) -> int:
    first_day = datetime(year, month, 1)
    first_sunday = 1 + (6 - first_day.weekday()) % 7
    return first_sunday + (occurrence - 1) * 7


def parse_utc_offset(value: str) -> int:
    text = str(value).strip()
    if len(text) != 5 or text[0] not in "+-" or not text[1:].isdigit():
        raise ValueError(f"Unrecognized airport UTC offset: {value!r}")
    hours, minutes = int(text[1:3]), int(text[3:5])
    if hours > 14 or minutes > 59:
        raise ValueError(f"Invalid airport UTC offset: {value!r}")
    sign = -1 if text[0] == "-" else 1
    return sign * (hours * 60 + minutes)


def observes_us_daylight_time(country: str, state: str) -> bool:
    no_dst = {
        "arizona", "hawaii", "puerto rico", "guam", "american samoa",
        "u.s. virgin islands", "us virgin islands", "northern mariana islands",
    }
    return country.strip().casefold() == "united states" and state.strip().casefold() not in no_dst


def normalize(series, pd):
    return series.astype("string").str.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild the integrated Parquet")
    parser.add_argument("--batch-size", type=int, default=5_000, help="flight rows per join batch")
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be greater than zero")

    try:
        import pandas as pd
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit(
            "Flight/weather integration needs pandas and pyarrow. "
            "Install them with: python -m pip install pandas pyarrow"
        ) from exc

    if OUTPUT.is_file() and not args.force:
        print(f"Already integrated: {OUTPUT.relative_to(ROOT)} (use --force to rebuild)")
        return
    input_paths = (FLIGHTS, AIRPORTS, LINKS, STATIONS, OBSERVATIONS)
    missing = [path for path in input_paths if not path.is_file()]
    if missing:
        files = "\n".join(f"  - {path.relative_to(ROOT)}" for path in missing)
        raise FileNotFoundError(f"Missing latest pipeline input(s):\n{files}")

    flight_source = pq.ParquetFile(FLIGHTS)
    flight_columns = flight_source.schema_arrow.names
    required_flight_columns = ("FlightDate", "DepTime", "OriginAirportSeqID")
    absent = [name for name in required_flight_columns if name not in flight_columns]
    if absent:
        raise ValueError(
            f"Flight Parquet is missing join column(s): {', '.join(absent)}. "
            "Rebuild it with scripts/05_reduce/reduce_flight_columns.py --force "
            "and scripts/07_subset/keep_top10_origin_airports.py --force."
        )

    airport_source = pq.ParquetFile(AIRPORTS)
    airport_schema = airport_source.schema_arrow
    airport_source.close()
    required_airport_columns = (
        "AIRPORT_SEQ_ID",
        "AIRPORT_COUNTRY_NAME",
        "AIRPORT_STATE_NAME",
        "DISPLAY_AIRPORT_NAME",
        "DISPLAY_AIRPORT_CITY_NAME_FULL",
        "LATITUDE",
        "LONGITUDE",
        "UTC_LOCAL_TIME_VARIATION",
    )
    missing_airport_columns = [
        name for name in required_airport_columns if airport_schema.get_field_index(name) < 0
    ]
    if missing_airport_columns:
        raise ValueError(
            "Top-ten airport Parquet is missing required column(s): "
            f"{', '.join(missing_airport_columns)}. Rebuild it with "
            "scripts/05_reduce/reduce_airport_columns.py --force and "
            "scripts/07_subset/keep_top10_origin_airports.py --force."
        )

    airport_table = pq.read_table(
        AIRPORTS,
        columns=[
            "AIRPORT_SEQ_ID",
            "AIRPORT_COUNTRY_NAME",
            "AIRPORT_STATE_NAME",
            "DISPLAY_AIRPORT_NAME",
            "DISPLAY_AIRPORT_CITY_NAME_FULL",
            "LATITUDE",
            "LONGITUDE",
            "UTC_LOCAL_TIME_VARIATION",
        ],
    )
    airport_data = airport_table.to_pandas()
    airport_data["OriginAirportSeqID"] = normalize(airport_data["AIRPORT_SEQ_ID"], pd)
    airport_data = airport_data.rename(
        columns={
            "AIRPORT_COUNTRY_NAME": "AirportCountryName",
            "AIRPORT_STATE_NAME": "AirportStateName",
            "DISPLAY_AIRPORT_NAME": "AirportName",
            "DISPLAY_AIRPORT_CITY_NAME_FULL": "AirportCityName",
            "LATITUDE": "AirportLatitude",
            "LONGITUDE": "AirportLongitude",
            "UTC_LOCAL_TIME_VARIATION": "AirportUTCOffset",
        }
    ).drop(columns=["AIRPORT_SEQ_ID"])
    if airport_data["OriginAirportSeqID"].duplicated().any():
        raise ValueError("Top-ten airport Parquet contains duplicate AIRPORT_SEQ_ID values")

    observations_table = pq.read_table(OBSERVATIONS, columns=list(WEATHER_COLUMNS))
    weather = observations_table.to_pandas()
    weather["STATION"] = normalize(weather["STATION"], pd)
    weather["_UTCDateTime"] = pd.to_datetime(
        weather["DATE"], errors="coerce", utc=True
    ).dt.tz_localize(None)
    weather = weather[weather["_UTCDateTime"].notna()]
    available_stations = set(weather["STATION"].dropna().tolist())
    if not available_stations:
        raise ValueError("Reduced weather observations contain no station IDs")

    link_data = pq.read_table(
        LINKS,
        columns=["AIRPORT_SEQ_ID", "GHCN_ID", "HAVERSINE_DISTANCE_KM", "DISTANCE_RANK"],
    ).to_pandas()
    link_data["AIRPORT_SEQ_ID"] = normalize(link_data["AIRPORT_SEQ_ID"], pd)
    link_data["GHCN_ID"] = normalize(link_data["GHCN_ID"], pd)
    link_data["DISTANCE_RANK"] = pd.to_numeric(link_data["DISTANCE_RANK"], errors="raise")
    selected_links = []
    for airport_id, group in link_data.groupby("AIRPORT_SEQ_ID", sort=False):
        group = group.sort_values("DISTANCE_RANK")
        available = group[group["GHCN_ID"].isin(available_stations)]
        if available.empty:
            raise ValueError(
                f"No downloaded candidate weather station has observations for airport {airport_id}"
            )
        selected_links.append(available.iloc[0])
    selected_link_data = pd.DataFrame(selected_links).rename(
        columns={
            "AIRPORT_SEQ_ID": "OriginAirportSeqID",
            "GHCN_ID": "WeatherStationID",
            "HAVERSINE_DISTANCE_KM": "AirportWeatherStationDistanceKm",
            "DISTANCE_RANK": "WeatherStationPriority",
        }
    )[["OriginAirportSeqID", *LINK_OUTPUT_COLUMNS]]
    airport_weather_links = selected_link_data.merge(
        airport_data[
            [
                "OriginAirportSeqID",
                "AirportCountryName",
                "AirportStateName",
                "AirportUTCOffset",
            ]
        ],
        on="OriginAirportSeqID",
        how="left",
        validate="one_to_one",
    )
    if selected_link_data["OriginAirportSeqID"].nunique() != 10:
        raise ValueError("Expected a selected weather station for each of the 10 airports")

    local_weather_frames = []
    for mapping in airport_weather_links.to_dict("records"):
        station_observations = weather[weather["STATION"] == mapping["WeatherStationID"]].copy()
        if station_observations.empty:
            continue
        offset_minutes = parse_utc_offset(mapping["AirportUTCOffset"])
        local_time = station_observations["_UTCDateTime"] + pd.to_timedelta(
            offset_minutes, unit="m"
        )
        if observes_us_daylight_time(
            str(mapping["AirportCountryName"] or ""),
            str(mapping["AirportStateName"] or ""),
        ):
            year = 2024
            dst_start_local = pd.Timestamp(
                datetime(year, 3, nth_sunday(year, 3, 2), 2)
            )
            dst_end_local = pd.Timestamp(
                datetime(year, 11, nth_sunday(year, 11, 1), 2)
            )
            dst_start_utc = dst_start_local - pd.Timedelta(minutes=offset_minutes)
            dst_end_utc = dst_end_local - pd.Timedelta(minutes=offset_minutes + 60)
            daylight = station_observations["_UTCDateTime"].ge(dst_start_utc) & (
                station_observations["_UTCDateTime"] < dst_end_utc
            )
            local_time = local_time + pd.to_timedelta(daylight.astype("int8") * 60, unit="m")

        station_observations["_AirportJoinKey"] = mapping["OriginAirportSeqID"]
        station_observations["_LocalDate"] = local_time.dt.strftime("%Y-%m-%d")
        station_observations["_LocalHour"] = local_time.dt.hour.astype("int8")
        station_observations[OBSERVATION_LOCAL_TIME_COLUMN] = local_time.dt.strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        local_weather_frames.append(station_observations)
    if not local_weather_frames:
        raise ValueError("No selected-station observations could be converted to airport local time")
    weather_by_airport = pd.concat(local_weather_frames, ignore_index=True)
    weather_by_airport = weather_by_airport.sort_values(
        ["_AirportJoinKey", "STATION", "_LocalDate", "_LocalHour", "_UTCDateTime"],
        kind="mergesort",
    ).drop_duplicates(
        subset=["_AirportJoinKey", "STATION", "_LocalDate", "_LocalHour"], keep="last"
    )

    station_data = pq.read_table(
        STATIONS, columns=["GHCN_ID", "LATITUDE", "LONGITUDE"]
    ).to_pandas()
    station_data["WeatherStationID"] = normalize(station_data["GHCN_ID"], pd)
    station_data = station_data.rename(
        columns={"LATITUDE": "WeatherStationLatitude", "LONGITUDE": "WeatherStationLongitude"}
    )[["WeatherStationID", *STATION_OUTPUT_COLUMNS]]
    station_data = station_data[station_data["WeatherStationID"].isin(available_stations)]
    if station_data["WeatherStationID"].duplicated().any():
        raise ValueError("Reduced weather-station inventory contains duplicate GHCN_ID values")
    missing_station_metadata = set(selected_link_data["WeatherStationID"]) - set(
        station_data["WeatherStationID"]
    )
    if missing_station_metadata:
        raise ValueError(
            "Selected station(s) are missing from the reduced station inventory: "
            + ", ".join(sorted(missing_station_metadata))
        )

    if airport_data["OriginAirportSeqID"].nunique() != 10:
        raise ValueError("Expected 10 rows in the top-ten airport Parquet")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    partial = OUTPUT.with_name(OUTPUT.stem + ".part.parquet")
    output_columns = [
        *flight_columns,
        *AIRPORT_OUTPUT_COLUMNS,
        *LINK_OUTPUT_COLUMNS,
        *STATION_OUTPUT_COLUMNS,
        *WEATHER_COLUMNS,
        OBSERVATION_LOCAL_TIME_COLUMN,
    ]
    string_columns = (
        *flight_columns,
        *AIRPORT_OUTPUT_COLUMNS,
        "WeatherStationID",
        *STATION_OUTPUT_COLUMNS,
        *WEATHER_COLUMNS,
        OBSERVATION_LOCAL_TIME_COLUMN,
    )
    output_schema = pa.schema(
        [pa.field(name, pa.string()) for name in string_columns]
        + [
            pa.field("AirportWeatherStationDistanceKm", pa.float64()),
            pa.field("WeatherStationPriority", pa.int64()),
        ]
    )
    output_schema = pa.schema([output_schema.field(name) for name in output_columns])
    writer = None
    input_rows = 0
    output_rows = 0
    try:
        for batch in flight_source.iter_batches(batch_size=args.batch_size):
            flights = batch.to_pandas()
            flights["OriginAirportSeqID"] = normalize(flights["OriginAirportSeqID"], pd)
            departure_hhmm = pd.to_numeric(flights["DepTime"], errors="coerce")
            departure_hhmm = departure_hhmm.where(departure_hhmm.mod(1).eq(0))
            valid_time = (
                (departure_hhmm.between(0, 2359) & (departure_hhmm.mod(100) < 60))
                | departure_hhmm.eq(2400)
            ).fillna(False)
            departure_hour = (departure_hhmm // 100).where(departure_hhmm.ne(2400), 0)
            flight_date = pd.to_datetime(flights["FlightDate"], errors="coerce")
            midnight_rollover_days = departure_hhmm.eq(2400).fillna(False).astype("int8")
            flight_date = flight_date + pd.to_timedelta(midnight_rollover_days, unit="D")
            flights["_FlightDate"] = flight_date.dt.strftime("%Y-%m-%d")
            flights["_FlightHour"] = departure_hour.where(valid_time).astype("Int64")
            joined = flights.merge(
                airport_data, on="OriginAirportSeqID", how="left", validate="many_to_one"
            ).merge(
                selected_link_data,
                on="OriginAirportSeqID",
                how="left",
                validate="many_to_one",
            ).merge(
                station_data, on="WeatherStationID", how="left", validate="many_to_one"
            ).merge(
                weather_by_airport,
                left_on=[
                    "OriginAirportSeqID", "WeatherStationID", "_FlightDate", "_FlightHour"
                ],
                right_on=[
                    "_AirportJoinKey", "STATION", "_LocalDate", "_LocalHour"
                ],
                how="left",
                sort=False,
            )
            if joined["AirportName"].isna().any() or joined["WeatherStationLatitude"].isna().any():
                raise ValueError("A flight airport or selected station failed to join")
            joined = joined[output_columns]
            table = pa.Table.from_pandas(joined, schema=output_schema, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(partial, output_schema, compression="zstd")
            if table.num_rows:
                writer.write_table(table, row_group_size=args.batch_size)
            input_rows += batch.num_rows
            output_rows += table.num_rows

        if writer is None:
            writer = pq.ParquetWriter(partial, output_schema, compression="zstd")
        writer.close()
        writer = None
        check = pq.ParquetFile(partial)
        try:
            if check.metadata.num_rows != output_rows:
                raise RuntimeError("Integrated Parquet row-count validation failed")
            if output_rows != input_rows:
                raise RuntimeError(
                    f"Left-join row count mismatch: expected {input_rows:,} flight rows, "
                    f"got {output_rows:,}"
                )
            if check.schema_arrow.names != output_columns:
                raise RuntimeError("Integrated Parquet schema validation failed")
        finally:
            check.close()
        os.replace(partial, OUTPUT)
    finally:
        if writer is not None:
            writer.close()
        if partial.exists():
            partial.unlink()
        flight_source.close()

    print(
        f"Saved {OUTPUT.relative_to(ROOT)} ({output_rows:,} joined rows from "
        f"{input_rows:,} flights; unmatched weather observations are null)."
    )


if __name__ == "__main__":
    main()
