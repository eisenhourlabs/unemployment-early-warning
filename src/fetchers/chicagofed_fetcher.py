"""
Chicago Fed Labor Market Indicators (catalog row CHI_LMI): all 36 series in the release.

The Chicago Fed's release page loads its numbers from a public data file:
    https://api.data.chicagofed.org/CFLMI/chi-labor-market-indicators.json
It holds monthly series dated by the BLS reference week (e.g. 2026-10-17 for October):
  - flows from 2008: layoffs and other separations rate, hiring rate for unemployed workers,
    flow-consistent unemployment rate
  - real-time unemployment rate forecasts from 2025: percentiles (16/25/50/75/84) for the advance,
    final and revised estimates, layoff and hiring contributions, and probabilities of each change
Released twice a month at 8:30 am ET (advance, then final).

Each series is saved like a FRED series: data/processed/<source_id>.csv (date, value), with a dated
vintage in data/vintages/<source_id>/ whenever it changes (normal vintage rule; forecasts get revised).
Tier 3: a failed download is logged but does not fail the run; the series-health check will flag it.

Run:  python src/fetchers/chicagofed_fetcher.py
"""

import json
import sys
from datetime import datetime, timezone

import pandas as pd
import requests

from fred_fetcher import LOG_FILE, PROCESSED, save

SERIES_ID = "CHI_LMI"
URL = "https://api.data.chicagofed.org/CFLMI/chi-labor-market-indicators.json"
RELEASE_DATE_URL = "https://api.data.chicagofed.org/CFLMI/release-date.txt"
HEADERS = {"User-Agent": "unemployment-early-warning (github.com/eisenhourlabs/unemployment-early-warning)"}


def fetch() -> tuple[dict, str]:
    r = requests.get(URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    try:
        release = requests.get(RELEASE_DATE_URL, headers=HEADERS, timeout=30).text.strip()
    except requests.RequestException:
        release = ""
    return json.loads(r.content), release


def main() -> int:
    run_time = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log_rows, meta_rows = [], []
    try:
        data, release = fetch()
        series = data["series"]
        if len(series) < 3:
            raise ValueError(f"only {len(series)} series in the file")
    except Exception as e:
        print(f"{SERIES_ID}: FAILED: {e}")
        pd.DataFrame([{"run_utc": run_time, "series_id": SERIES_ID, "status": f"FAILED: {e}"}]).to_csv(
            LOG_FILE, mode="a", header=not LOG_FILE.exists(), index=False)
        return 0   # Tier 3: don't fail the run

    print(f"{SERIES_ID}: release {release or '(date unknown)'}, {len(series)} series")
    for s in series:
        sid, m = s["source_id"], s["metadata"]
        df = pd.DataFrame(s["observations"], columns=["date", "value"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.sort_values("date").reset_index(drop=True)
        changed = save(sid, df)
        status = "updated" if changed else "no change"
        log_rows.append({"run_utc": run_time, "series_id": sid, "status": status})
        meta_rows.append({
            "series_id": sid, "title": m.get("title", ""), "units": m.get("units", ""),
            "frequency": {"M": "Monthly"}.get(m.get("frequency"), m.get("frequency", "")),
            "seasonal_adjustment": m.get("season", ""),
            "last_updated": release,
            "first_date": df.date.iloc[0] if len(df) else "", "last_date": df.date.iloc[-1] if len(df) else "",
            "last_value": df.value.dropna().iloc[-1] if df.value.notna().any() else "",
        })
        print(f"  {sid:<42} {status:<10} latest {df.date.iloc[-1]} = {df.value.iloc[-1]}")

    # Merge into the shared metadata file without touching other series' rows.
    meta_path = PROCESSED / "_metadata.csv"
    new_meta = pd.DataFrame(meta_rows)
    if meta_path.exists():
        old = pd.read_csv(meta_path)
        new_meta = pd.concat([old[~old.series_id.isin(new_meta.series_id)], new_meta])
    new_meta.sort_values("series_id").to_csv(meta_path, index=False)

    pd.DataFrame(log_rows).to_csv(LOG_FILE, mode="a", header=not LOG_FILE.exists(), index=False)
    print(f"Done: {len(series)} Chicago Fed series saved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
