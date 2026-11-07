"""
FRED fetcher: downloads every active FRED series listed in config/series_catalog.csv.

What it does, step by step:
  1. Reads your FRED API key (from config/.env on your PC, or from a GitHub secret in the cloud).
  2. Reads the series catalog and picks rows where fetcher == "fred" and status == "active".
     Rows whose ID starts with STATE_ are expanded to one series per state in config/state_weights.csv.
  3. Downloads each series' full history from the FRED API.
  4. Saves it to data/processed/<SERIES_ID>.csv  (columns: date, value).
  5. If the data changed since last time, also saves a dated copy in data/vintages/<SERIES_ID>/
     so we keep a record of revisions (important for honest backtests).
  6. Writes data/processed/_metadata.csv (title, units, last updated) and data/fetch_log.csv.

How to run it (from the project folder):
    python src/fetchers/fred_fetcher.py            # fetch everything
    python src/fetchers/fred_fetcher.py UNRATE ICSA  # fetch only these series
"""

import csv
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Paths. Path(__file__) is this file; .parents[2] climbs up to the project folder.
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "config" / "series_catalog.csv"
STATE_WEIGHTS = ROOT / "config" / "state_weights.csv"
PROCESSED = ROOT / "data" / "processed"
VINTAGES = ROOT / "data" / "vintages"
LOG_FILE = ROOT / "data" / "fetch_log.csv"

FRED_URL = "https://api.stlouisfed.org/fred"
START_DATE = "1990-01-01"   # history start; enough for 3 recessions of backtesting
PAUSE_SECONDS = 0.6         # FRED allows ~120 requests/minute; this keeps us well under


def load_api_key() -> str:
    """Return the FRED key. Cloud runs use an environment variable; your PC uses config/.env."""
    key = os.environ.get("FRED_API_KEY", "").strip()
    env_file = ROOT / "config" / ".env"
    if not key and env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("FRED_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        sys.exit("No FRED_API_KEY found. Put it in config/.env or set it as an environment variable.")
    return key


def series_to_fetch(only=None) -> list[str]:
    """Build the list of FRED series IDs from the catalog."""
    states = []
    with open(STATE_WEIGHTS) as f:
        lines = [l for l in f if not l.startswith("#")]
        states = [row["state"] for row in csv.DictReader(lines)]

    ids = []
    with open(CATALOG) as f:
        for row in csv.DictReader(f):
            if row["fetcher"] != "fred" or row.get("status", "active") != "active":
                continue
            sid = row["series_id"]
            if sid.startswith("STATE_"):
                # e.g. "State initial claims (e.g. TXICLAIMS)" -> pattern {ST}ICLAIMS
                suffix = {"STATE_ICLAIMS": "ICLAIMS", "STATE_CCLAIMS": "CCLAIMS", "STATE_UR": "UR"}[sid]
                ids += [st + suffix for st in states]
            else:
                ids.append(sid)
    if only:
        ids = list(only)   # series named on the command line, whether or not they are in the catalog
    return ids


def fred_get(endpoint: str, params: dict, key: str, tries: int = 3) -> dict:
    """Call one FRED API endpoint and return the JSON. Retries a few times on network hiccups."""
    params = {**params, "api_key": key, "file_type": "json"}
    for attempt in range(1, tries + 1):
        try:
            r = requests.get(f"{FRED_URL}/{endpoint}", params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 400:   # bad series ID: no point retrying
                raise ValueError(r.json().get("error_message", r.text))
        except requests.RequestException as e:
            if attempt == tries:
                raise
        time.sleep(2 * attempt)
    raise RuntimeError(f"FRED returned status {r.status_code} for {params.get('series_id')}")


def fetch_one(sid: str, key: str) -> tuple[pd.DataFrame, dict]:
    """Download one series. Returns (data, metadata)."""
    meta = fred_get("series", {"series_id": sid}, key)["seriess"][0]
    obs = fred_get("series/observations", {"series_id": sid, "observation_start": START_DATE}, key)
    df = pd.DataFrame(obs["observations"])[["date", "value"]]
    # FRED uses "." for missing values (e.g. October 2025, when no unemployment rate was collected).
    df["value"] = pd.to_numeric(df["value"].replace(".", pd.NA), errors="coerce")
    info = {
        "series_id": sid,
        "title": meta["title"],
        "units": meta["units"],
        "frequency": meta["frequency"],
        "seasonal_adjustment": meta["seasonal_adjustment"],
        "last_updated": meta["last_updated"],
        "first_date": df["date"].iloc[0] if len(df) else "",
        "last_date": df["date"].iloc[-1] if len(df) else "",
        "last_value": df["value"].dropna().iloc[-1] if df["value"].notna().any() else "",
    }
    return df, info


def save(sid: str, df: pd.DataFrame) -> bool:
    """Save the latest copy, and a dated vintage only if something changed. Returns True if changed."""
    PROCESSED.mkdir(parents=True, exist_ok=True)
    path = PROCESSED / f"{sid}.csv"
    changed = True
    if path.exists():
        old = pd.read_csv(path, dtype={"date": str})
        changed = not old.equals(df.reset_index(drop=True))
    df.to_csv(path, index=False)
    if changed:
        vdir = VINTAGES / sid
        vdir.mkdir(parents=True, exist_ok=True)
        df.to_csv(vdir / f"{date.today().isoformat()}.csv", index=False)
    return changed


def main(only=None):
    key = load_api_key()
    ids = series_to_fetch(only)
    print(f"Fetching {len(ids)} FRED series...")
    meta_rows, log_rows = [], []
    run_time = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for i, sid in enumerate(ids, 1):
        try:
            df, info = fetch_one(sid, key)
            changed = save(sid, df)
            meta_rows.append(info)
            status = "updated" if changed else "no change"
            print(f"  [{i}/{len(ids)}] {sid:<22} {status:<10} latest {info['last_date']} = {info['last_value']}")
        except Exception as e:   # one bad series should not stop the whole run
            status = f"FAILED: {e}"
            print(f"  [{i}/{len(ids)}] {sid:<22} {status}")
        log_rows.append({"run_utc": run_time, "series_id": sid, "status": status})
        time.sleep(PAUSE_SECONDS)

    # Metadata: merge with any previous file so a partial run doesn't erase other series.
    meta_path = PROCESSED / "_metadata.csv"
    new_meta = pd.DataFrame(meta_rows)
    if meta_path.exists() and len(new_meta):
        old_meta = pd.read_csv(meta_path)
        new_meta = pd.concat([old_meta[~old_meta.series_id.isin(new_meta.series_id)], new_meta])
    if len(new_meta):
        new_meta.sort_values("series_id").to_csv(meta_path, index=False)

    log = pd.DataFrame(log_rows)
    log.to_csv(LOG_FILE, mode="a", header=not LOG_FILE.exists(), index=False)

    failed = log[log.status.str.startswith("FAILED")]
    print(f"Done: {len(log) - len(failed)} ok, {len(failed)} failed.")
    return 1 if len(failed) == len(log) else 0   # exit code 1 only if everything failed


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
