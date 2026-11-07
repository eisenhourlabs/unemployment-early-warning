"""
DOL state detail files from https://oui.doleta.gov/unemploy/csv/:
  ar539.csv   weekly claims by state
  ar5159.csv  monthly first payments, weeks compensated, exhaustions by state
  ar218.csv   quarterly benefit rights and duration by state

Which files to fetch comes from config/series_catalog.csv (rows with fetcher = dol_csv; DOL_AR539 -> ar539.csv).
Coded column names (c1, c2, ...) are renamed using config/dol_columns.csv. Data from 1995 on.
Saved to data/processed/dol/<report>.csv with the same "latest figures only" rule as the national file.

Run:  python src/fetchers/dol_state.py            # all dol_csv rows in the catalog
      python src/fetchers/dol_state.py ar5159     # just one report
"""

import io
import sys

import pandas as pd

from dol_common import (OUI, START_DATE, catalog_rows, column_names, download, log_fetch,
                        save_latest, update_metadata)

# Columns whose largest revision is written to docs/data_revisions.md, per report.
REVISION_COLUMNS = {
    "ar539": ["ic_state_ui", "cw_state_ui"],
    "ar5159": ["fp_state_ui_total", "wc_state_ui_total", "final_payments_state_ui"],
    "ar218": ["potential_avg_weeks", "actual_avg_weeks"],
}


def fetch_report(report: str) -> tuple[pd.DataFrame, str]:
    """Download one report, rename columns, keep 1995+. Returns (data, date column name)."""
    raw = pd.read_csv(io.BytesIO(download(f"{OUI}/csv/{report}.csv")), low_memory=False)
    names = column_names(report)
    unmapped = [c for c in raw.columns if c not in names]
    if unmapped:
        # DOL added a column we have no name for: keep it under its code and say so.
        print(f"  note: {report} has unmapped columns {unmapped}; add them to config/dol_columns.csv")
    df = raw.rename(columns=names)
    date_col = names["rptdate"]
    df[date_col] = pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d")
    if "reflected_week_ended" in df:
        df["reflected_week_ended"] = pd.to_datetime(df.reflected_week_ended).dt.strftime("%Y-%m-%d")
    df = df[df[date_col] >= START_DATE]
    # One row per state and period; if DOL ever repeats one, keep the last.
    df = df.drop_duplicates(["state", date_col], keep="last").sort_values(["state", date_col])
    return df.reset_index(drop=True), date_col


def main(only=None) -> int:
    reports = [r["series_id"].removeprefix("DOL_").lower() for r in catalog_rows("dol_csv")]
    if only:
        reports = [r for r in reports if r in only]
    failures = 0
    for report in reports:
        series_id = f"DOL_{report.upper()}"
        try:
            df, date_col = fetch_report(report)
            status = save_latest(df, f"{report}.csv", ["state", date_col], date_col,
                                 REVISION_COLUMNS.get(report, []), f"State {report}")
            update_metadata(f"{report}.csv", f"DOL {report} by state", f"{OUI}/csv/{report}.csv", df, date_col)
            print(f"{series_id}: {status}; {df.state.nunique()} areas; latest {df[date_col].max()}")
            log_fetch(series_id, "updated: " + status)
        except Exception as e:
            failures += 1
            print(f"{series_id}: FAILED: {e}")
            log_fetch(series_id, f"FAILED: {e}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
