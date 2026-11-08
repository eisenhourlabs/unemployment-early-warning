"""
Full-history copies of FRED series that the model uses at today's values (vintage_source = current in
config/model_series.csv) but that data/processed/ keeps only from 1990 (the website's default history).

Today: GS10 and TB3MS (yield curve before 1982) and T10Y3MM (yield curve from 1982). Market interest rates
are never revised, so today's values are also the values known at the time.

Saves data/model/current/<SERIES_ID>.csv (columns date, value). realtime.py looks here first.
The website's own files (data/processed/) are not touched.

Run it:
    python src/model/current_fetcher.py
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "fetchers"))
from fred_fetcher import fetch_one, load_api_key   # reuse the FRED fetcher's download code

OUT_DIR = ROOT / "data" / "model" / "current"
SERIES = ["GS10", "TB3MS", "T10Y3MM", "ICNSA"]   # ICNSA: weekly NSA initial claims (stage 3d)


def main() -> None:
    key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for sid in SERIES:
        df, info = fetch_one(sid, key, start="1900-01-01")   # "from the beginning"
        df.to_csv(OUT_DIR / f"{sid}.csv", index=False)
        print(f"{sid:8} {info['first_date']} to {info['last_date']}, {len(df)} observations")


if __name__ == "__main__":
    main()
