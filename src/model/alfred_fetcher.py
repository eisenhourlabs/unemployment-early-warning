"""
Step 2 of the modeling data: past vintages from ALFRED (FRED's archive of what each series said on
each past date).

What it does, for every row of config/model_series.csv with vintage_source = alfred:
  1. Asks the FRED API for the series' full real-time history (realtime_start=1776-07-04,
     realtime_end=9999-12-31). FRED answers with one row per (observation date, value) and the period
     during which that value was the published one: realtime_start to realtime_end. A value revised in a
     later release gets a new row from the revision date on.
  2. Saves it to data/model/alfred/<SERIES_ID>.csv  (columns: date, value, realtime_start, realtime_end).
  3. Writes data/model/alfred/vintage_coverage.csv: number of vintages, first and last vintage date, and
     the observed first-release lag (days from an observation's date to its first publication), which is
     compared with the release_lag_days in the config.

src/model/realtime.py reads these files to answer "what did series X say on date D?".

Run it:
    python src/model/alfred_fetcher.py             # all ALFRED series in the config
    python src/model/alfred_fetcher.py UNRATE      # only these
"""

import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "fetchers"))
from fred_fetcher import fred_get, load_api_key   # reuse the FRED fetcher's key loading and retries

CONFIG = ROOT / "config" / "model_series.csv"
OUT_DIR = ROOT / "data" / "model" / "alfred"
PAGE = 100_000          # FRED returns at most 100,000 rows per request; longer answers come in pages


def alfred_series() -> pd.DataFrame:
    """Rows of config/model_series.csv that use ALFRED."""
    cfg = pd.read_csv(CONFIG, comment="#")     # lines starting with # are notes
    return cfg[cfg.vintage_source == "alfred"]


def fetch_realtime(series_id: str, key: str) -> pd.DataFrame:
    """Download every vintage of one series as rows of (date, value, realtime_start, realtime_end)."""
    rows, offset = [], 0
    while True:
        answer = fred_get("series/observations", {
            "series_id": series_id,
            "realtime_start": "1776-07-04",   # FRED's documented "earliest possible" date
            "realtime_end": "9999-12-31",     # ... and "latest possible" date
            "limit": PAGE, "offset": offset,
        }, key)
        rows += answer["observations"]
        offset += PAGE
        if offset >= int(answer["count"]):
            break
        time.sleep(0.6)                       # stay well under FRED's request limit
    df = pd.DataFrame(rows)[["date", "value", "realtime_start", "realtime_end"]]
    # FRED writes "." for a missing value (e.g. October 2025, when no unemployment rate was collected).
    df["value"] = pd.to_numeric(df["value"].replace(".", pd.NA), errors="coerce")
    return df.sort_values(["date", "realtime_start"]).reset_index(drop=True)


def coverage(series_id: str, df: pd.DataFrame, lag_config: int) -> dict:
    """Summarize one series' vintages, including how late each observation was first published."""
    vintages = sorted(df.realtime_start.unique())
    # First publication of each observation = its earliest realtime_start.
    first = df.groupby("date").realtime_start.min()
    lag = (pd.to_datetime(first) - pd.to_datetime(first.index)).dt.days
    # Only count observations dated after the first vintage: older ones were archived or added to the
    # history later (e.g. payrolls back to 1939), not released late.
    lag = lag[first.index > vintages[0]]
    return {
        "series_id": series_id,
        "vintages": len(vintages),
        "first_vintage": vintages[0],
        "last_vintage": vintages[-1],
        "first_observation": df.date.min(),
        "rows": len(df),
        "first_release_lag_median_days": int(lag.median()),
        "first_release_lag_max_days": int(lag.max()),
        "release_lag_days_config": lag_config,
        # The config lag is used only before the first vintage; it should cover the usual lag.
        "config_covers_95pct_of_releases": bool((lag <= lag_config).mean() >= 0.95),
    }


def main(only: list[str]) -> None:
    key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = alfred_series()
    if only:
        cfg = cfg[cfg.series_id.isin(only)]
    summary = []
    for row in cfg.itertuples():
        df = fetch_realtime(row.series_id, key)
        df.to_csv(OUT_DIR / f"{row.series_id}.csv", index=False)
        info = coverage(row.series_id, df, row.release_lag_days)
        summary.append(info)
        print(f"{row.series_id:10} {info['vintages']:4} vintages from {info['first_vintage']}, "
              f"{info['rows']:7} rows, first-release lag median {info['first_release_lag_median_days']} "
              f"days (max {info['first_release_lag_max_days']})")
        time.sleep(0.6)

    # Keep the coverage rows of series not fetched this time.
    out = OUT_DIR / "vintage_coverage.csv"
    new = pd.DataFrame(summary)
    if out.exists() and only:
        old = pd.read_csv(out)
        new = pd.concat([old[~old.series_id.isin(new.series_id)], new])
    new.to_csv(out, index=False)
    print(f"Wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main(sys.argv[1:])
