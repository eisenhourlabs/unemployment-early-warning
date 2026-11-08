"""
Data & Downloads page: writes every downloadable file into site/data/ and lists them on the page.

What it writes (each file has a permanent address, so Excel's Data > From Web can refresh it):
  site/data/series/<ID>.csv / .xlsx   every public FRED series (national and state)
  site/data/dol/<file>.csv / .xlsx     every DOL file (state files with plain column names)
  site/data/data_dictionary.csv        every column of every DOL file: file, column, definition, units
  site/data/bundles/                   dol_weekly_claims.csv / .xlsx, weekly_series.csv, monthly_series.csv,
                                       everything.xlsx (one sheet per frequency + a data dictionary)
Each XLSX has an "About" sheet (source, units, link, citation); DOL files also get a "Columns" sheet
with the description of every column (config/dol_columns.csv and config/derived_columns.csv).

What it never writes: series whose catalog licence is not "public" (e.g. U. Michigan sentiment:
citation-required; Chicago Fed Labor Market Indicators: terms not yet confirmed) and the private state weights.
Called by build_site.py.
"""

import csv
import sys
from datetime import date, datetime

import pandas as pd
from openpyxl import Workbook

from common import DOL, PROCESSED, ROOT, fmt_date, fmt_month

sys.path.insert(0, str(ROOT / "src" / "fetchers"))
from fred_fetcher import series_to_fetch  # noqa: E402  (the same series list the fetcher uses)

PAGE_LABELS = {"overview": "Overview", "job_losses": "Job Losses", "duration": "Duration", "leading": "Leading",
               "states": "States", "all": "All pages"}
SA_SHORT = {"Seasonally Adjusted": "SA", "Not Seasonally Adjusted": "NSA",
            "Seasonally Adjusted Annual Rate": "SAAR", "Smoothed Seasonally Adjusted": "SA (smoothed)"}
STATE_TEMPLATES = {"ICLAIMS": "STATE_ICLAIMS", "CCLAIMS": "STATE_CCLAIMS", "UR": "STATE_UR"}

# One short list of unit labels for the whole page (FRED uses many spellings for the same thing).
UNIT_LABELS = {"%": "Percent", "Rate": "Percent", "Percent": "Percent", "Percentage Points": "Percentage points",
               "Number": "Number", "Persons": "Number", "Level in Thousands": "Thousands",
               "Thousands of Persons": "Thousands", "Thousands of Units": "Thousands", "Hours": "Hours",
               "Weeks": "Weeks", "Index": "Index", "+1 or 0": "0/1 indicator"}


def unit_label(fred_units: str, sa: str) -> str:
    """Standard unit label; seasonally adjusted annual rates say so (e.g. building permits)."""
    label = UNIT_LABELS.get(fred_units, fred_units)
    return label + (", annual rate" if sa == "SAAR" else "")


def column_units(column: str) -> str:
    """Units of a DOL column, from its name (the naming follows config/dol_columns.csv)."""
    c = column.lower()
    if c.endswith(("_ended", "_date")) or c == "date":
        return "Date"
    if c == "state":
        return "State code"
    if c.startswith("source_") or c.endswith("_status"):
        return "Text"
    if c.startswith("amt_"):
        return "Dollars"
    if c.endswith("_sf"):
        return "Seasonal factor (x100)"
    if "iur" in c or "rate" in c or "pct" in c:
        return "Percent"
    if "avg_weeks" in c or "avg_duration" in c:
        return "Weeks"
    if c.startswith(("cw_", "wc_")) or c == "weeks_compensated":
        return "Number of weeks claimed or paid"
    if c == "covered_employment":
        return "Number of jobs"
    return "Number"

# DOL files offered for download: (file stem, catalog row, frequency, report name in config/dol_columns.csv)
DOL_FILES = [
    ("national_weekly", "DOL_NATIONAL_WEEKLY", "weekly", "eta539_national"),
    ("national_weekly_eta539", "DOL_ETA539_NATIONAL", "weekly", "eta539_national"),
    ("seasonal_factors", "DOL_ETA539_NATIONAL", "weekly", "eta539_national"),
    ("claims_rates_weekly", "DOL_CLAIMS_RATES", "weekly", "eta539_national"),
    ("exhaustion_duration_monthly", "DOL_EXHAUSTION_DURATION", "monthly", "ar5159"),
    ("benefit_duration_quarterly", "DOL_AR218", "quarterly", "ar218"),
    ("ar539", "DOL_AR539", "weekly", "ar539"),
    ("ar5159", "DOL_AR5159", "monthly", "ar5159"),
    ("ar218", "DOL_AR218", "quarterly", "ar218"),
]
# Files we calculate from DOL data (the rest are DOL's figures with plain column names)
DOL_DERIVED = {"national_weekly", "claims_rates_weekly", "exhaustion_duration_monthly", "benefit_duration_quarterly"}
DOL_PAGE = "https://oui.doleta.gov/unemploy/DataDownloads.asp"
SITE_URL = "https://eisenhourlabs.github.io/unemployment-early-warning/"   # where GitHub Pages publishes the site
DOL_CLAIMS_PAGE = "https://oui.doleta.gov/unemploy/claims.asp"


# ===========================================================================
# What can be downloaded
# ===========================================================================
def catalog() -> dict[str, dict]:
    with open(ROOT / "config" / "series_catalog.csv", newline="") as f:
        return {r["series_id"]: r for r in csv.DictReader(f)}


def catalog_row_for(sid: str, cat: dict) -> dict:
    """The catalog row a FRED series belongs to (state series use their STATE_ template row)."""
    if sid in cat:
        return cat[sid]
    for suffix, template in STATE_TEMPLATES.items():
        if sid.endswith(suffix) and len(sid) == 2 + len(suffix):
            return cat[template]
    raise KeyError(f"{sid} is not in the catalog")


def excluded() -> list[dict]:
    """Active catalog rows that are never offered for download, with the reason."""
    reasons = {"citation-required": "copyrighted; charted with its required citation but not redistributed",
               "check-terms": "terms of use not yet confirmed",
               "restricted": "licence does not allow redistribution",
               "reference-only": "a published forecast, shown only as a comparison marker on the charts"}
    return [{"name": r["name"], "id": r["series_id"], "reason": reasons.get(r["license"], r["license"])}
            for r in catalog().values() if r["status"] == "active" and r["license"] != "public"]


def fred_entries() -> list[dict]:
    """One entry per downloadable FRED series."""
    cat = catalog()
    meta = pd.read_csv(PROCESSED / "_metadata.csv").set_index("series_id")
    entries = []
    for sid in series_to_fetch():
        row = catalog_row_for(sid, cat)
        if row["license"] != "public":
            continue   # never offered (licence)
        m = meta.loc[sid]
        is_state = row["series_id"].startswith("STATE_")
        entries.append({
            "kind": "FRED", "id": sid, "name": m["title"] if is_state else row["name"],
            "title": m["title"], "source": row["source"], "source_url": f"https://fred.stlouisfed.org/series/{sid}",
            "frequency": row["frequency"],
            "sa": SA_SHORT.get(m["seasonal_adjustment"], m["seasonal_adjustment"]),
            "units": unit_label(m["units"], SA_SHORT.get(m["seasonal_adjustment"], "")),
            "page": row["dashboard_page"], "state": sid[:2] if is_state else "",
            "updated": str(m["last_updated"])[:10], "csv": f"data/series/{sid}.csv", "xlsx": f"data/series/{sid}.xlsx",
            "path": PROCESSED / f"{sid}.csv",
        })
    return entries


def dol_entries() -> list[dict]:
    cat = catalog()
    meta = pd.read_csv(DOL / "_metadata.csv").set_index("file")
    # Calculated files have no row in DOL's metadata; they are rebuilt in the same run as the newest DOL check.
    last_check = str(meta["last_checked_utc"].max())[:10]
    entries = []
    for stem, cat_id, freq, report in DOL_FILES:
        m = meta.loc[f"{stem}.csv"] if f"{stem}.csv" in meta.index else None
        source = str(m["source"]) if m is not None else ""
        entries.append({
            "kind": "DOL", "id": stem, "name": m["description"] if m is not None else cat[cat_id]["name"],
            "title": cat[cat_id]["name"], "source": "DOL (derived)" if stem in DOL_DERIVED else "DOL",
            "source_url": source if source.startswith("http") else DOL_CLAIMS_PAGE,
            "frequency": freq, "units": "Various (see data dictionary)", "sa": "SA and NSA" if stem.startswith(("national", "claims", "seasonal")) else "NSA",
            "page": cat[cat_id]["dashboard_page"], "state": "",
            "updated": str(m["last_checked_utc"])[:10] if m is not None else last_check,
            "csv": f"data/dol/{stem}.csv", "xlsx": f"data/dol/{stem}.xlsx", "path": DOL / f"{stem}.csv", "report": report,
        })
    return entries


# ===========================================================================
# Column descriptions for DOL files
# ===========================================================================
def column_descriptions(stem: str, report: str, columns) -> list[list]:
    """[column, description, units, DOL code, how confirmed / calculated] for each column of a DOL file."""
    derived = pd.read_csv(ROOT / "config" / "derived_columns.csv")
    derived = {(r.file, r.column): r for r in derived.itertuples(index=False)}
    mapping = pd.read_csv(ROOT / "config" / "dol_columns.csv")
    # The merged bundle reuses the descriptions of the two files it is made from.
    files = ["national_weekly", "claims_rates_weekly"] if stem == "dol_weekly_claims" else [stem]
    rows = []
    for col in columns:
        d = next((derived[(f, col)] for f in files if (f, col) in derived), None)
        if d is not None:
            rows.append([col, d.description, column_units(col), "", d.how_calculated])
            continue
        same_report = mapping[(mapping.report == report) & (mapping.name == col)]
        anywhere = mapping[mapping.name == col]
        hit = same_report if len(same_report) else anywhere
        if len(hit):
            r = hit.iloc[0]
            rows.append([col, r.description, column_units(col), f"{r.report} {r.code}", r.basis])
        else:
            rows.append([col, "", column_units(col), "", ""])
    return rows


# ===========================================================================
# Writing files
# ===========================================================================
DATE_COLUMNS = ("date", "week_ended", "reflected_week_ended", "month_ended", "quarter_ended", "month")


def excel_value(v):
    """Turn pandas values into things Excel understands (dates as real dates, blanks as empty cells)."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NA:
        return None
    if isinstance(v, pd.Timestamp):
        return v.date()
    if hasattr(v, "item"):          # numpy numbers -> plain Python numbers
        return v.item()
    return v


def write_xlsx(path, sheets: list[tuple[str, pd.DataFrame | list[list]]]) -> None:
    """Write an Excel file with several sheets. Each sheet is a DataFrame (header + rows) or a list of rows.
    'write_only' mode streams rows to disk, so even the 88,000-row ar539 file stays fast."""
    wb = Workbook(write_only=True)
    for name, content in sheets:
        ws = wb.create_sheet(name)
        if isinstance(content, pd.DataFrame):
            df = content.copy()
            for c in df.columns:
                if c in DATE_COLUMNS:
                    df[c] = pd.to_datetime(df[c], errors="coerce")
            ws.append(list(df.columns))
            for row in df.itertuples(index=False):
                ws.append([excel_value(v) for v in row])
        else:
            for row in content:
                ws.append(row)
    wb.save(path)


def about_sheet(e: dict, built: datetime) -> list[list]:
    rows = [["Unemployment Watch download", ""],
            ["Series / file", e["id"]], ["Name", e["title"]], ["Source", e["source"]], ["Source link", e["source_url"]],
            ["Frequency", e["frequency"]], ["Units", e["units"]], ["Seasonal adjustment", e["sa"]],
            ["Source last updated", e["updated"]], ["File built (UTC)", built.strftime("%Y-%m-%d %H:%M")],
            ["Permanent link (CSV)", SITE_URL + e["csv"]], ["", ""]]
    if e["kind"] == "FRED":
        rows.append(["Citation", f"{e['source']}, {e['title']} [{e['id']}], retrieved from FRED, Federal Reserve "
                                 f"Bank of St. Louis; {e['source_url']}"])
    else:
        rows.append(["Citation", "U.S. Department of Labor, Employment and Training Administration, unemployment "
                                 f"insurance data; {DOL_PAGE}. Derived columns: see the Columns sheet."])
    rows.append(["Note", "Public data only. Not an official forecast. Figures are revised by their publishers."])
    return rows


def write_entry_files(e: dict, out, built: datetime) -> pd.DataFrame:
    """CSV + XLSX for one series or DOL file. Returns the data (for bundles and the page).

    The CSV is the source file's text, unchanged (only a FRED file's 'value' header becomes the series ID),
    so numbers keep exactly the form the publisher used. The XLSX gets real numbers and dates; convert_dtypes()
    keeps whole-number columns whole even when they have blanks (otherwise pandas would show 552 as 552.0).
    """
    text = pd.read_csv(e["path"], dtype=str, keep_default_na=False)
    df = pd.read_csv(e["path"]).convert_dtypes()
    if e["kind"] == "FRED":
        text = text.rename(columns={"value": e["id"]})
        df = df.rename(columns={"value": e["id"]})
        df["date"] = df["date"].astype(str)
    (out / e["csv"]).parent.mkdir(parents=True, exist_ok=True)
    text.to_csv(out / e["csv"], index=False)
    sheets = [("Data", df), ("About", about_sheet(e, built))]
    if e["kind"] == "DOL":
        sheets.insert(1, ("Columns", [["column", "description", "units", "DOL code", "how confirmed / calculated"]]
                          + column_descriptions(e["id"], e["report"], df.columns)))
    write_xlsx(out / e["xlsx"], sheets)
    return df


def latest(e: dict, df: pd.DataFrame) -> tuple[str, str]:
    """('Oct 31, 2026', '189,000') for the page table. DOL files show the date range instead of a value."""
    if e["kind"] == "DOL":
        date_col = next(c for c in df.columns if c in DATE_COLUMNS)
        d = pd.to_datetime(df[date_col])
        return f"{fmt_date(d.min())} to {fmt_date(d.max())}", f"{len(df):,} rows"
    s = df.set_index("date")[e["id"]].dropna()
    when = fmt_month(s.index[-1]) if e["frequency"] == "monthly" else fmt_date(s.index[-1])
    v = s.iloc[-1]
    return when, (f"{v:,.0f}" if abs(v) >= 1000 else f"{v:g}")


def week_end_day(e: dict, frames) -> str:
    """'Saturday' for claims weeks, 'Friday' for the NFCI: the weekday of the series' latest date."""
    return pd.Timestamp(frames[e["id"]]["date"].iloc[-1]).day_name()


def wide(entries, frames, freq, weekday: str | None = None) -> pd.DataFrame:
    """All series of one frequency side by side (one column per series), joined on date.
    Weekly series are grouped by the day their weeks end, so Friday and Saturday weeks don't sit on
    alternating half-empty rows."""
    cols = [frames[e["id"]].set_index("date")[e["id"]] for e in entries if e["frequency"] == freq
            and (weekday is None or week_end_day(e, frames) == weekday)]
    return pd.concat(cols, axis=1).sort_index().rename_axis("date").reset_index() if cols else pd.DataFrame()


def build(out, built: datetime) -> dict:
    """Write every file under out/data/ and return what the Data page needs."""
    fred = fred_entries()
    dol = dol_entries()
    frames = {}
    for e in fred + dol:
        frames[e["id"]] = write_entry_files(e, out, built)
        e["latest_date"], e["latest_value"] = latest(e, frames[e["id"]])

    # Bundles
    bdir = out / "data" / "bundles"
    bdir.mkdir(parents=True, exist_ok=True)
    weekly = frames["national_weekly"].merge(
        frames["claims_rates_weekly"].drop(columns=["source_initial", "source_continued", "covered_employment"]),
        on="week_ended", how="left")
    weekly.to_csv(bdir / "dol_weekly_claims.csv", index=False)
    write_xlsx(bdir / "dol_weekly_claims.xlsx", [
        ("Data", weekly),
        ("Columns", [["column", "description", "units", "DOL code", "how confirmed / calculated"]]
         + column_descriptions("dol_weekly_claims", "eta539_national", weekly.columns)),
        ("About", [["Unemployment Watch bundle", "DOL weekly claims (merged), from 1995"],
                   ["Contents", "national_weekly.csv joined with claims_rates_weekly.csv on week_ended"],
                   ["Source", f"U.S. Department of Labor, ETA 539 ({DOL_CLAIMS_PAGE}); preliminary weeks via FRED"],
                   ["File built (UTC)", built.strftime("%Y-%m-%d %H:%M")]])])
    # Data dictionary: every column of every DOL file (and the merged bundle), one CSV linked from each DOL row
    dictionary_rows = []
    for e in dol:
        for col, desc, units, *_ in column_descriptions(e["id"], e["report"], frames[e["id"]].columns):
            dictionary_rows.append({"file": f"{e['id']}.csv", "column": col, "definition": desc, "units": units})
    for col, desc, units, *_ in column_descriptions("dol_weekly_claims", "eta539_national", weekly.columns):
        dictionary_rows.append({"file": "bundles/dol_weekly_claims.csv", "column": col, "definition": desc, "units": units})
    pd.DataFrame(dictionary_rows).to_csv(out / "data" / "data_dictionary.csv", index=False)

    by_freq = {"daily": wide(fred, frames, "daily"),
               "weekly": wide(fred, frames, "weekly", "Saturday"),          # claims weeks end on Saturday
               "weekly_friday": wide(fred, frames, "weekly", "Friday"),     # NFCI weeks end on Friday
               "monthly": wide(fred, frames, "monthly")}
    sheet_names = {"daily": "Daily", "weekly": "Weekly (Sat)", "weekly_friday": "Weekly (Fri)", "monthly": "Monthly"}
    by_freq["weekly"].to_csv(bdir / "weekly_series.csv", index=False)
    by_freq["weekly_friday"].to_csv(bdir / "weekly_friday_series.csv", index=False)
    by_freq["monthly"].to_csv(bdir / "monthly_series.csv", index=False)
    dictionary = [["series_id", "name", "frequency", "units", "seasonal adjustment", "source", "source link",
                   "sheet", "last updated"]]
    for e in fred:
        key = e["frequency"] if e["frequency"] != "weekly" else (
            "weekly" if week_end_day(e, frames) == "Saturday" else "weekly_friday")
        dictionary.append([e["id"], e["title"], e["frequency"], e["units"], e["sa"], e["source"], e["source_url"],
                           sheet_names[key], e["updated"]])
    write_xlsx(bdir / "everything.xlsx",
               [(sheet_names[k], by_freq[k]) for k in sheet_names if len(by_freq[k])] + [("Dictionary", dictionary)])

    bundles = [
        {"name": "DOL weekly claims (merged), from 1995", "detail": "Every weekly DOL column, the calculated rates "
         "and the source flag (ETA 539 or preliminary news release)", "csv": "data/bundles/dol_weekly_claims.csv",
         "xlsx": "data/bundles/dol_weekly_claims.xlsx"},
        {"name": "All weekly series", "detail": "Side by side, one column each (weeks ending Saturday: claims)",
         "csv": "data/bundles/weekly_series.csv", "xlsx": ""},
        {"name": "Weekly series ending Friday", "detail": "Chicago Fed NFCI and its credit subindex",
         "csv": "data/bundles/weekly_friday_series.csv", "xlsx": ""},
        {"name": "All monthly series", "detail": "Side by side, one column each",
         "csv": "data/bundles/monthly_series.csv", "xlsx": ""},
        {"name": "Everything workbook", "detail": "One sheet per frequency (daily, weekly ending Saturday, weekly "
         "ending Friday, monthly) plus a data dictionary",
         "csv": "", "xlsx": "data/bundles/everything.xlsx"},
    ]
    rows = [{k: e[k] for k in ("kind", "id", "name", "source", "source_url", "frequency", "units", "sa", "page",
                               "state", "updated", "csv", "xlsx", "latest_date", "latest_value")}
            | {"dictionary": "data/data_dictionary.csv" if e["kind"] == "DOL" else ""}
            | {"page_label": PAGE_LABELS.get(e["page"], e["page"])} for e in dol + fred]
    return {"rows": rows, "bundles": bundles, "excluded": excluded(),
            "n_files": len(fred) * 2 + len(dol) * 2 + 7}
