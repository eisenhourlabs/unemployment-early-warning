"""
Shared helpers for the Department of Labor (DOL) scripts.

DOL data follows a "latest figures only" rule (see CLAUDE.md): no vintages. Each run downloads the
full history, compares it with what we already have, overwrites the stored file, and writes one line
to docs/data_revisions.md if any past period changed. A revision never fails the run.
"""

import csv
import io
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
DOL_DIR = ROOT / "data" / "processed" / "dol"
FRED_DIR = ROOT / "data" / "processed"
CATALOG = ROOT / "config" / "series_catalog.csv"
COLUMNS = ROOT / "config" / "dol_columns.csv"
FETCH_LOG = ROOT / "data" / "fetch_log.csv"
METADATA = DOL_DIR / "_metadata.csv"
REVISIONS = ROOT / "docs" / "data_revisions.md"

START_DATE = "1995-01-01"   # DOL state files start here (decision 2026-11-07)
# The national weekly report (ETA 539) starts earlier: covered employment, the denominator of the claims rates,
# is published from 1971 (decision 2026-11-07, Phase 2 review). Coverage expanded in 1978 (state and local
# government workers), so rates before and after 1978 are not strictly comparable; the charts mark it.
NATIONAL_START_DATE = "1971-01-01"
OUI = "https://oui.doleta.gov/unemploy"
HEADERS = {"User-Agent": "unemployment-early-warning (github.com/eisenhourlabs/unemployment-early-warning)"}


def download(url: str, data: dict | None = None, tries: int = 3) -> bytes:
    """GET (or POST, if `data` is given) a URL and return the body. Retries on network errors."""
    for attempt in range(1, tries + 1):
        try:
            if data is None:
                r = requests.get(url, headers=HEADERS, timeout=120)
            else:
                r = requests.post(url, data=data, headers=HEADERS, timeout=120)
            r.raise_for_status()
            return r.content
        except requests.RequestException:
            if attempt == tries:
                raise
            time.sleep(5 * attempt)


def column_names(report: str) -> dict[str, str]:
    """Return {DOL code: plain name} for one report, from config/dol_columns.csv."""
    with open(COLUMNS, encoding="utf-8") as f:
        return {r["code"]: r["name"] for r in csv.DictReader(f) if r["report"] == report}


def catalog_rows(fetcher: str) -> list[dict]:
    """Active catalog rows for one fetcher type (e.g. 'dol_csv')."""
    with open(CATALOG, encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["fetcher"] == fetcher and r["status"] == "active"]


def save_latest(df: pd.DataFrame, filename: str, keys: list[str], date_col: str,
                report_cols: list[str], label: str) -> str:
    """Compare `df` with the stored file, log any revision, then overwrite. Returns a status message.

    keys        columns that identify a row (e.g. ["week_ended"] or ["state", "week_ended"])
    date_col    the date column used for the revision date range
    report_cols columns whose largest change is written to the revisions log
    """
    DOL_DIR.mkdir(parents=True, exist_ok=True)
    path = DOL_DIR / filename
    # Round-trip the new data through CSV text so old and new are read the same way (same types).
    new = pd.read_csv(io.StringIO(df.to_csv(index=False)))
    status = f"{len(new)} rows"

    if path.exists():
        old = pd.read_csv(path)
        changed = compare(old, new, keys, date_col, report_cols)
        if changed:
            log_revision(label, changed)
            status += f"; REVISED {changed['n']} past periods ({changed['first']} to {changed['last']})"
        added = len(new.merge(old[keys], on=keys, how="left", indicator=True).query("_merge == 'left_only'"))
        status += f"; {added} new periods" if added else "; no new periods"

    df.to_csv(path, index=False)
    return status


def compare(old: pd.DataFrame, new: pd.DataFrame, keys, date_col, report_cols) -> dict | None:
    """Find rows present in both files whose values differ. Returns a summary dict, or None."""
    values = [c for c in new.columns if c in old.columns and c not in keys]
    both = old.merge(new, on=keys, suffixes=("_old", "_new"))
    if both.empty or not values:
        return None

    diff_any = pd.Series(False, index=both.index)
    for c in values:
        a, b = both[f"{c}_old"], both[f"{c}_new"]
        if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
            same = (a - b).abs().le(1e-9) | (a.isna() & b.isna())
        else:
            same = (a.astype(str) == b.astype(str)) | (a.isna() & b.isna())
        diff_any |= ~same
    rows = both[diff_any]
    if rows.empty:
        return None

    summary = {"n": len(rows), "first": rows[date_col].min(), "last": rows[date_col].max(), "largest": {}}
    for c in report_cols:
        if f"{c}_old" in rows and pd.api.types.is_numeric_dtype(rows[f"{c}_new"]):
            change = rows[f"{c}_new"] - rows[f"{c}_old"]
            if change.abs().max() > 0:
                i = change.abs().idxmax()
                where = rows.loc[i, date_col] + (f" {rows.loc[i, 'state']}" if "state" in rows else "")
                summary["largest"][c] = f"{change[i]:+,.4g} ({where})"
    return summary


def log_revision(label: str, s: dict) -> None:
    """Append one row to docs/data_revisions.md."""
    largest = "; ".join(f"{c} {v}" for c, v in s["largest"].items()) or "changes only in other columns"
    today = datetime.now(timezone.utc).date().isoformat()
    with open(REVISIONS, "a", encoding="utf-8") as f:
        f.write(f"| {today} | {label} | {s['n']:,} | {s['first']} to {s['last']} | {largest} |\n")


def log_fetch(series_id: str, status: str) -> None:
    """Append to data/fetch_log.csv (same columns as the FRED fetcher)."""
    run_time = datetime.now(timezone.utc).isoformat(timespec="seconds")
    row = pd.DataFrame([{"run_utc": run_time, "series_id": series_id, "status": status}])
    row.to_csv(FETCH_LOG, mode="a", header=not FETCH_LOG.exists(), index=False)


def update_metadata(filename: str, description: str, source: str, df: pd.DataFrame, date_col: str) -> None:
    """Keep data/processed/dol/_metadata.csv: one row per output file."""
    row = {
        "file": filename,
        "description": description,
        "source": source,
        "first_date": df[date_col].min(),
        "last_date": df[date_col].max(),
        "rows": len(df),
        "last_checked_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    meta = pd.read_csv(METADATA) if METADATA.exists() else pd.DataFrame(columns=row.keys())
    meta = pd.concat([meta[meta.file != filename], pd.DataFrame([row])]).sort_values("file")
    meta.to_csv(METADATA, index=False)
