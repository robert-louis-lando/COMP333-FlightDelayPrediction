"""Print the ten airports with the most flights originating there."""

from __future__ import annotations

from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FLIGHTS = ROOT / "data/staging/04_reduced/flights_2024_reduced.parquet"
AIRPORTS = ROOT / "data/staging/04_reduced/airports_active_2024_reduced.parquet"


def required_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Missing input: {path.relative_to(ROOT)}")


def main() -> None:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit(
            "This script needs pyarrow. Install it with: python -m pip install pyarrow"
        ) from exc

    required_file(FLIGHTS)
    required_file(AIRPORTS)

    airport_table = pq.read_table(
        AIRPORTS,
        columns=[
            "AIRPORT_SEQ_ID",
            "DISPLAY_AIRPORT_NAME",
            "DISPLAY_AIRPORT_CITY_NAME_FULL",
            "AIRPORT_STATE_NAME",
        ],
    )
    airport_rows = airport_table.to_pylist()
    airport_by_seq_id = {}
    for row in airport_rows:
        seq_id = str(row["AIRPORT_SEQ_ID"]).strip()
        if not seq_id or seq_id == "None":
            continue
        if seq_id in airport_by_seq_id:
            raise ValueError(f"Duplicate AIRPORT_SEQ_ID in airport Parquet: {seq_id}")
        airport_by_seq_id[seq_id] = row

    flight_file = pq.ParquetFile(FLIGHTS)
    origin_index = flight_file.schema_arrow.get_field_index("OriginAirportSeqID")
    if origin_index < 0:
        raise ValueError("Flight Parquet has no OriginAirportSeqID column")

    counts = Counter()
    for batch in flight_file.iter_batches(batch_size=100_000, columns=["OriginAirportSeqID"]):
        counts.update(
            value.strip()
            for value in batch.column(0).to_pylist()
            if value is not None and value.strip()
        )

    joined_counts = {
        seq_id: count for seq_id, count in counts.items() if seq_id in airport_by_seq_id
    }
    unmatched = sum(count for seq_id, count in counts.items() if seq_id not in airport_by_seq_id)
    top_ten = sorted(
        joined_counts.items(),
        key=lambda item: (-item[1], str(airport_by_seq_id[item[0]]["DISPLAY_AIRPORT_NAME"] or "")),
    )[:10]

    print("Top 10 origin airports by flight count")
    print(f"{'Rank':>4}  {'Airport':<40} {'City':<34} {'State':<22} {'Flight count':>12}")
    print("-" * 120)
    for rank, (seq_id, count) in enumerate(top_ten, start=1):
        airport = airport_by_seq_id[seq_id]
        name = airport["DISPLAY_AIRPORT_NAME"] or ""
        city = airport["DISPLAY_AIRPORT_CITY_NAME_FULL"] or ""
        state = airport["AIRPORT_STATE_NAME"] or ""
        print(f"{rank:>4}  {name[:40]:<40} {city[:34]:<34} {state[:22]:<22} {count:>12,}")

    print(f"\nUnmatched origin flights (no airport sequence ID match): {unmatched:,}")
    print("Counts use the filtered and column-reduced flight dataset.")


if __name__ == "__main__":
    main()
