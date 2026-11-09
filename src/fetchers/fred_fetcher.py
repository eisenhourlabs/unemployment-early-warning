"""
FRED fetcher: downloads every active FRED series listed in config/series_catalog.csv.

What it does, step by step:
  1. Reads your FRED API key (from config/.env on your PC, or from a GitHub secret in the cloud).
  2. Reads the series catalog and picks rows where fetcher == "fred" and status == "active".
     Rows whose ID starts with STATE_ (fetcher fred) are expanded to one series per state in config/states.csv:
     the 50 states and DC, 51 x 3 = 153 series (Phase 4; until then only the 44 weighted states).
  3. Downloads each series' history from the FRED API, from 1990 or from the catalog's history_start
     date when one is set (e.g. UNRATE from 1948, for long-run percentiles on the dashboard).
  4. Saves it to data/processed/<SERIES_ID>.csv  (columns: date, value).
  5. If the data changed since last time, also saves a dated copy in data/vintages/<SERIES_ID>/
     so we keep a record of revisions (important for honest backtests).
  6. Writes data/processed/_metadata.csv (title, units, last updated) and data/fetch_log.csv.
  7. Prints a summary of any failed series and exits with code 1 (a red GitHub run) if any
     Tier 1 series failed or more than 10% of all series failed. Otherwise exits with code 0.

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
STATES = ROOT / "config" / "states.csv"   # all 53 DOL areas; FRED has the 50 states + DC
PROCESSED = ROOT / "data" / "processed"
VINTAGES = ROOT / "data" / "vintages"
LOG_FILE = ROOT / "data" / "fetch_log.csv"

FRED_URL = "https://api.stlouisfed.org/fred"
START_DATE = "1990-01-01"   # default history start; enough for 3 recessions of backtesting.
                            # A catalog row's history_start column overrides it for that series.
PAUSE_SECONDS = 0.6         # FRED allows ~120 requests/minute; this keeps us well under

# When should a run count as failed (exit code 1, which turns the GitHub run red)?
CRITICAL_TIER = "1"         # any failure in this tier fails the run
MAX_FAIL_SHARE = 0.10       # ...or more than this share of all series failing


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


def series_to_fetch(only=None) -> dict[str, str]:
    """Build the FRED series list from the catalog, as {series_id: tier}.

    Per-state series inherit the tier of their STATE_ template row.
    """
    with open(STATES) as f:
        lines = [l for l in f if not l.startswith("#")]
        states = [row["state"] for row in csv.DictReader(lines) if row["area_type"] in ("state", "dc")]

    tiers = {}   # dicts keep insertion order, so series are fetched in catalog order
    with open(CATALOG) as f:
        for row in csv.DictReader(f):
            if row["fetcher"] != "fred" or row.get("status", "active") != "active":
                continue
            sid = row["series_id"]
            if sid.startswith("STATE_"):
                # e.g. "State initial claims (e.g. TXICLAIMS)" -> pattern {ST}ICLAIMS
                suffix = {"STATE_ICLAIMS": "ICLAIMS", "STATE_CCLAIMS": "CCLAIMS", "STATE_UR": "UR"}[sid]
                for st in states:
                    tiers[st + suffix] = row["tier"]
            else:
                tiers[sid] = row["tier"]
    if only:
        # Series named on the command line, whether or not they are in the catalog ("?" = unknown tier).
        tiers = {sid: tiers.get(sid, "?") for sid in only}
    return tiers


def history_starts() -> dict[str, str]:
    """Return {series_id: start date} for catalog rows that set history_start (others use START_DATE)."""
    with open(CATALOG) as f:
        return {row["series_id"]: row["history_start"] for row in csv.DictReader(f)
                if row.get("history_start")}


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


def fetch_one(sid: str, key: str, start: str = START_DATE) -> tuple[pd.DataFrame, dict]:
    """Download one series from the start date. Returns (data, metadata)."""
    meta = fred_get("series", {"series_id": sid}, key)["seriess"][0]
    obs = fred_get("series/observations", {"series_id": sid, "observation_start": start}, key)
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
    tiers = series_to_fetch(only)
    ids = list(tiers)
    starts = history_starts()
    print(f"Fetching {len(ids)} FRED series...")
    meta_rows, log_rows = [], []
    run_time = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for i, sid in enumerate(ids, 1):
        try:
            df, info = fetch_one(sid, key, starts.get(sid, START_DATE))
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
    return run_verdict(failed, len(log), tiers)


def run_verdict(failed: pd.DataFrame, total: int, tiers: dict) -> int:
    """Print a failure summary and return the exit code: 1 = run failed, 0 = run OK."""
    if failed.empty:
        return 0

    print("\nFailed series:")
    for _, row in failed.iterrows():
        print(f"  {row.series_id:<22} tier {tiers.get(row.series_id, '?'):<2} {row.status}")

    critical = [sid for sid in failed.series_id if tiers.get(sid) == CRITICAL_TIER]
    share = len(failed) / total
    reasons = []
    if critical:
        reasons.append(f"Tier {CRITICAL_TIER} series failed: {', '.join(critical)}")
    if share > MAX_FAIL_SHARE:
        reasons.append(f"{len(failed)} of {total} series failed ({share:.1%}; limit {MAX_FAIL_SHARE:.0%})")

    if reasons:
        print("\nRUN FAILED: " + "; ".join(reasons))
        return 1
    print(f"\nRun OK: {len(failed)} of {total} failed ({share:.1%}), no Tier {CRITICAL_TIER} failures (limits: any Tier "
          f"{CRITICAL_TIER}, or more than {MAX_FAIL_SHARE:.0%}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
