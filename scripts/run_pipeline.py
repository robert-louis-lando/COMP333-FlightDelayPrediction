"""Run the complete flight and airport data pipeline in dependency order."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
STEPS = (
    ("Download BTS ZIPs and NOAA station inventory", "scripts/01_download/download_datasets.py", True),
    ("Convert flight, airport, and station data to Parquet", "scripts/02_convert/convert_to_parquet.py", True),
    ("Combine monthly flight Parquets", "scripts/03_combine/combine_flight_parquets.py", True),
    ("Filter flights", "scripts/04_filter/filter_flights_weather_delay.py", True),
    ("Filter airport dates", "scripts/04_filter/filter_airports_active_2024.py", True),
    ("Reduce flight columns", "scripts/05_reduce/reduce_flight_columns.py", True),
    ("Reduce airport columns", "scripts/05_reduce/reduce_airport_columns.py", True),
    ("Reduce station columns", "scripts/05_reduce/reduce_station_columns.py", True),
    ("Print top ten origin airports", "scripts/06_analyze/top_origin_airports.py", False),
    ("Create top-ten airport/flight subsets", "scripts/07_subset/keep_top10_origin_airports.py", True),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="redownload ZIPs and rebuild all outputs",
    )
    args = parser.parse_args()

    for number, (label, relative_script, accepts_force) in enumerate(STEPS, start=1):
        script = ROOT / relative_script
        if not script.is_file():
            raise FileNotFoundError(f"Pipeline script not found: {relative_script}")

        command = [sys.executable, str(script)]
        if args.force and accepts_force:
            command.append("--force")
        print(f"\n[{number}/{len(STEPS)}] {label}", flush=True)
        subprocess.run(command, cwd=ROOT, check=True)

    print("\nPipeline completed successfully.")


if __name__ == "__main__":
    main()
