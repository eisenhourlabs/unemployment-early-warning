"""
DOL national weekly claims (ETA 539 report): the official series.

Downloads the National report from https://oui.doleta.gov/unemploy/claims.asp as XML (the same request
the website form sends), keeps every column, and saves:
  data/processed/dol/national_weekly_eta539.csv  weeks with data, from 1971
  data/processed/dol/seasonal_factors.csv        DOL's published seasonal factors, including future weeks
Past weeks that DOL revised are overwritten and logged in docs/data_revisions.md (no vintages).

Run:  python src/fetchers/dol_national.py
"""

import sys
import xml.etree.ElementTree as ET
from datetime import date

import pandas as pd

from dol_common import OUI, NATIONAL_START_DATE, column_names, download, log_fetch, save_latest, update_metadata

SERIES_ID = "DOL_ETA539_NATIONAL"
REPORT_URL = f"{OUI}/wkclaims/report.asp"


def fetch() -> pd.DataFrame:
    """Download the national report as XML and return one row per week."""
    last_year = date.today().year + 1          # the form offers next year too (future seasonal factors)
    form = {"level": "us", "final_yr": last_year, "strtdate": NATIONAL_START_DATE[:4],
            "enddate": last_year, "filetype": "xml"}
    root = ET.fromstring(download(REPORT_URL, data=form))

    names = column_names("eta539_national")    # e.g. "InitialClaims/NSA" -> "ic_nsa"
    rows = []
    for week in root.iter("week"):
        row = {}
        for path, name in names.items():
            text = (week.findtext(path) or "").strip().replace(",", "")
            row[name] = text if path == "weekEnded" else (float(text) if text else None)
        rows.append(row)

    df = pd.DataFrame(rows)
    df["week_ended"] = pd.to_datetime(df.week_ended, format="%m/%d/%Y").dt.strftime("%Y-%m-%d")
    for c in ["ic_nsa", "ic_sa", "cc_nsa", "cc_sa", "covered_employment"]:
        df[c] = df[c].round().astype("Int64")   # whole numbers ("Int64" allows blanks)
    return df[df.week_ended >= NATIONAL_START_DATE].sort_values("week_ended").reset_index(drop=True)


def main() -> int:
    try:
        df = fetch()
    except Exception as e:
        print(f"{SERIES_ID}: FAILED: {e}")
        log_fetch(SERIES_ID, f"FAILED: {e}")
        return 1

    # Weeks with actual data vs. future weeks that only have seasonal factors.
    has_data = df.ic_nsa.notna() | df.cc_nsa.notna()
    weekly = df[has_data]
    factors = df[["week_ended", "ic_sf", "cc_sf"]].dropna(how="all", subset=["ic_sf", "cc_sf"])

    # Sanity checks: a broken download should fail loudly, not overwrite good data.
    latest = pd.Timestamp(weekly.week_ended.max())
    if len(weekly) < 1500 or (pd.Timestamp.today() - latest).days > 60:
        msg = f"FAILED: unexpected content ({len(weekly)} weeks, latest {latest.date()})"
        print(f"{SERIES_ID}: {msg}")
        log_fetch(SERIES_ID, msg)
        return 1

    status = save_latest(weekly, "national_weekly_eta539.csv", ["week_ended"], "week_ended",
                         ["ic_sa", "cc_sa", "ic_sf", "cc_sf"], "National weekly claims (ETA 539)")
    save_latest(factors, "seasonal_factors.csv", ["week_ended"], "week_ended", [], "Seasonal factors")
    update_metadata("national_weekly_eta539.csv", "National weekly claims, ETA 539 (official)",
                    REPORT_URL, weekly, "week_ended")
    update_metadata("seasonal_factors.csv", "Published seasonal factors incl. future weeks",
                    REPORT_URL, factors, "week_ended")

    last_ic = weekly.loc[weekly.ic_nsa.notna(), "week_ended"].max()
    last_cc = weekly.loc[weekly.cc_nsa.notna(), "week_ended"].max()
    print(f"{SERIES_ID}: {status}. Latest initial claims week {last_ic}, continued claims week {last_cc}.")
    log_fetch(SERIES_ID, "updated: " + status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
