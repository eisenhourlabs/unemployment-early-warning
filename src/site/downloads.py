"""
Data & Downloads page: writes every downloadable file into site/data/ and lists them on the page.

What it writes (each file has a permanent address, so Excel's Data > From Web can refresh it):
  site/data/series/<ID>.csv / .xlsx   every public FRED series (national and state)
  site/data/dol/<file>.csv / .xlsx     every DOL file (state files with plain column names)
  site/data/data_dictionary.csv        every column of every DOL file: file, column, definition, units
  site/data/model/<file>.csv / .xlsx   early-warning model outputs (score, trigger, forecast, what-if and nowcast
                                       histories); "model output, not official statistics"
  site/data/bundles/                   dol_weekly_claims.csv / .xlsx, weekly_series.csv, monthly_series.csv,
                                       everything.xlsx (one sheet per frequency + a data dictionary)
Each XLSX has an "About" sheet (source, units, link, citation); DOL files also get a "Columns" sheet
with the description of every column (config/dol_columns.csv and config/derived_columns.csv).

What it never writes: series whose catalog licence is not "public" (e.g. U. Michigan sentiment:
citation-required; Chicago Fed Labor Market Indicators: restricted, local-only) and the state weights themselves.
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
# State files (Phase 4, States page): (file stem, frequency, plain name). Built by src/transforms/state_measures.py.
# Since the Phase 4 review (Gate 3 item 6) the weighted series are downloadable too (they were charted only before).
STATE_FILES = [
    ("state_weekly", "weekly", "State claims: rates, year-on-year and vs.-normal changes, by state and week, from 1995"),
    ("state_monthly", "monthly", "State unemployment rate and Sahm-style gap, exhaustion and duration, by month"),
    ("diffusion_weekly", "weekly", "State claims diffusion index (share of states / covered jobs with claims up 20%+)"),
    ("weighted_weekly", "weekly", "Weighted claims rates and year-on-year changes vs. national (state sums)"),
    ("weighted_monthly", "monthly", "Weighted unemployment rate and Sahm-style gap vs. national"),
]
# Not offered: weighted_contributions_weekly (it would list every weighted state, i.e. their count; decision O1).
STATE_CITATION = ("U.S. Department of Labor, Employment and Training Administration, unemployment insurance data "
                  "(ar539, ETA 5159), https://oui.doleta.gov/unemploy/DataDownloads.asp; state unemployment rates: "
                  "U.S. Bureau of Labor Statistics (LAUS) via FRED, Federal Reserve Bank of St. Louis. Calculated by "
                  "Unemployment Watch: see the Columns sheet.")
# Review WP5: labour flows (Duration page), calculated by src/transforms/labor_flows.py from public BLS and DOL series.
FLOWS_CITATION = ("U.S. Bureau of Labor Statistics, Current Population Survey (UNEMPLOY, UEMPLT5) and JOLTS (JTSJOL); "
                  "U.S. Department of Labor, Employment and Training Administration (CCSA, ICSA); all retrieved from "
                  "FRED, Federal Reserve Bank of St. Louis. Calculated by Unemployment Watch: see the Columns sheet.")
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
    # State files (States page): calculated from DOL state data (and BLS state unemployment rates)
    for stem, freq, name in STATE_FILES:
        entries.append({
            "kind": "DOL", "id": stem, "name": name, "title": name,
            "source": "DOL and BLS (derived)" if stem in ("state_monthly", "weighted_monthly") else "DOL (derived)",
            "source_url": DOL_PAGE, "frequency": freq, "units": "Various (see data dictionary)",
            "sa": "SA (unemployment rate) and NSA" if stem in ("state_monthly", "weighted_monthly") else "NSA",
            "page": "states", "state": "", "updated": last_check,
            "csv": f"data/states/{stem}.csv", "xlsx": f"data/states/{stem}.xlsx",
            "path": PROCESSED / "states" / f"{stem}.csv", "report": "", "citation": STATE_CITATION,
        })
    if (PROCESSED / "labor_flows_monthly.csv").exists():
        entries.append({
            "kind": "DOL", "id": "labor_flows_monthly",
            "name": "Labour flows: job-finding rate, job openings per unemployed, continuing claims per new claim",
            "title": "Labour flows (job-finding rate, openings per unemployed, continuing claims per new claim)",
            "source": "BLS and DOL (derived)", "source_url": "https://fred.stlouisfed.org/series/UNEMPLOY",
            "frequency": "monthly", "units": "Various (see data dictionary)", "sa": "SA", "page": "duration",
            "state": "", "updated": last_check, "csv": "data/derived/labor_flows_monthly.csv",
            "xlsx": "data/derived/labor_flows_monthly.xlsx", "path": PROCESSED / "labor_flows_monthly.csv",
            "report": "", "citation": FLOWS_CITATION,
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


# ===========================================================================
# Early-warning model outputs (Phase 3)
# ===========================================================================
MODEL = ROOT / "data" / "model"
MODEL_NOTE = "Model output, not official statistics. Unemployment Watch early-warning model; method: outlook.html#methodology"


def model_files() -> list[dict]:
    """The model downloads: one entry per file with its table, description and 'as of' rule. A file whose inputs are
    missing is left out (the rest of the page still builds)."""
    out = []

    def add(stem, name, contents, asof_rule, df, columns):
        out.append({"stem": stem, "name": name, "contents": contents, "asof_rule": asof_rule, "df": df,
                    "columns": columns})

    # 1. Score history: monthly out-of-sample scores since 1980, then every live run
    monthly, runs = MODEL / "score_display_monthly.csv", MODEL / "live_history.csv"
    if monthly.exists():
        m = pd.read_csv(monthly)
        m = pd.DataFrame({"date": m.month, "kind": "month (backtest)", "score_3m": m.p3, "score_6m": m.p6,
                          "score_12m": m.p12, "colour": m.colour, "basis": m.basis})
        if runs.exists():
            r = pd.read_csv(runs)
            m = pd.concat([m, pd.DataFrame({"date": r["asof"], "kind": "live run", "score_3m": r.p3, "score_6m": r.p6,
                                            "score_12m": r.p12, "colour": r.colour, "basis": "live"})])
        add("score_history", "Early-warning score history",
            "Month (1980 on) and live run: chance of a claims jump or unemployment rise within 3 / 6 / 12 months, the "
            "colour shown, and the basis (1980-1999 tested with partly revised data, out of sample 2000 on, live)", "each row", m,
            [["date", "Month (tested on history: as of its last day) or live run date"],
             ["kind", "month (backtest) = tested on history, or live run"],
             ["score_3m / score_6m / score_12m", "Probability (0-1) that an event starts within 3 / 6 / 12 months"],
             ["colour", "Colour shown (hysteresis: amber from 0.20 until below 0.15; red from 0.50 until below 0.40)"],
             ["basis", "pseudo out of sample = 1980-1999, tested with partly revised data; out of sample (2000 on); live"]])
    # 2. Trigger history: monthly confirmation-trigger (Layer 1) values and colours since 1967
    trig = MODEL / "triggers_monthly.csv"
    if trig.exists():
        t = pd.read_csv(trig, keep_default_na=False)
        t = t.drop(columns=[c for c in ("overall_old", "n_amber_or_red", "n_panel_amber_or_red") if c in t])
        t = t.rename(columns={"overall": "overall_status"})
        add("trigger_history", "Confirmation-trigger history",
            "Monthly confirmation-trigger values and colours since 1967 (as of each month's last day), the data basis "
            "of each, and the overall status", "each row", t,
            [["<trigger>_value", "The trigger's number (Sahm: points; claims and continuing claims: ratio - 1; temp "
              "help: 6-month change; yield curve: 10y-3m spread, points; factory surveys: index; NFCI: index)"],
             ["<trigger>_color", "green / amber / red (blank before enough data exist)"],
             ["<trigger>_basis", "real-time (as published then), current-vintage (today's claims cut back by the "
              "release lag) or revised (before the first archived vintage)"],
             ["overall_status", "Status rule: red if trigger 1, 2 or 4 is red; amber if one of them is amber/red and "
              "another trigger that counts toward the status (1, 2, 4, 6, 8) is amber/red; else green. Temp help "
              "and factory surveys are shown for context, not counted"]])
    # 3. Forecast archive: every live run's fans
    fans = MODEL / "live_fans_history.csv"
    if fans.exists():
        add("forecast_archive", "Forecast archive",
            "Every live run's forecast ranges: target, horizon, middle value and the 10 / 25 / 75 / 90 percentiles, "
            "and the weight on past-event paths", "run date", pd.read_csv(fans),
            [["asof", "Run date"], ["target", "ur = unemployment rate (%); cc = SA continuing claims rate, 4-week "
                                    "average (% of covered employment)"],
             ["latest_period / level_at_origin", "Latest published period and value the forecast starts from"],
             ["horizon / horizon_months / target_period", "Months (ur) or weeks (cc) ahead, and the period forecast"],
             ["q10 / q25 / median / q75 / q90", "Percentiles of the forecast distribution (80% range: q10-q90)"],
             ["deterioration_weight", "Weight on past-event paths (the matching event probability)"]])
    # 4. Stress paths (what-ifs) from the latest live run
    latest = MODEL / "live_latest.json"
    if latest.exists():
        import json
        live = json.loads(latest.read_text(encoding="utf-8"))
        rows = [{"asof": live["asof"], "target": t, "scenario": sc, "period": pt["period"], "level": pt["level"]}
                for t, st in live["stress"].items() for sc, pts in st["scenarios"].items() for pt in pts]
        add("stress_paths", "What-if paths",
            "If a 2001-type or 2008-type downturn started now: the path from today's level (not forecasts)",
            "run date", pd.DataFrame(rows),
            [["target", "ur = unemployment rate (%); ic = SA initial claims rate, 4-week average (% of covered "
              "employment; the site shows it per 10,000 = x100); cc = SA continuing claims rate, 4-week average (%)"],
             ["scenario", "2001-type (event #9) or 2008-type (event #12): the change after that event's start, "
              "added (ur, points) or applied as a % change (claims rates) to today's level"],
             ["period / level", "Month or week, and the what-if level"]])
    # 5. Nowcast history: the backtest (2000 on) and every live nowcast
    nc = MODEL / "nowcast.csv"
    if nc.exists():
        n = pd.read_csv(nc)
        n = pd.DataFrame({"month": n.month, "kind": "backtest", "released": n.released, "prior_value": n.prior_value,
                          "nowcast": n.nowcast.round(3), "first_release": n.first_release,
                          "error": (n.first_release - n.nowcast).round(3)})
        if runs.exists():
            r = pd.read_csv(runs).dropna(subset=["nowcast"])
            if len(r):
                n = pd.concat([n, pd.DataFrame({"month": r.nowcast_month, "kind": "live (run " + r["asof"] + ")",
                                                "nowcast": r.nowcast.round(3)})])
        add("nowcast_history", "Nowcast history",
            "Every nowcast of the next unemployment-rate release with its first release and error (tested on history from 2000; "
            "live runs once available). Typical range +/-0.2 point (held about 80% of first releases)", "release date",
            n, [["month", "Month the release covers"], ["kind", "backtest (= tested on history) or live"],
                ["released", "Date of the first release"], ["prior_value", "Previous published rate (no-change forecast)"],
                ["nowcast", "Our nowcast (%)"], ["first_release", "Rate as first published (%)"],
                ["error", "first_release - nowcast (points)"]])
    return out


def write_model_files(out, built: datetime) -> list[dict]:
    """Write data/model/<stem>.csv and .xlsx (Data + About sheets) for each model file; returns the page rows."""
    mdir = out / "data" / "model"
    mdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for e in model_files():
        e["df"].to_csv(mdir / f"{e['stem']}.csv", index=False)
        about = [["Unemployment Watch download", e["name"]], ["Note", MODEL_NOTE], ["Contents", e["contents"]],
                 ["File built (UTC)", built.strftime("%Y-%m-%d %H:%M")], ["", ""], ["Column", "Meaning"]] + e["columns"]
        write_xlsx(mdir / f"{e['stem']}.xlsx", [("Data", e["df"]), ("About", about)])
        rows.append({"name": e["name"], "contents": e["contents"], "asof": e["asof_rule"], "rows": len(e["df"]),
                     "csv": f"data/model/{e['stem']}.csv", "xlsx": f"data/model/{e['stem']}.xlsx"})
    return rows


def about_sheet(e: dict, built: datetime) -> list[list]:
    rows = [["Unemployment Watch download", ""],
            ["Series / file", e["id"]], ["Name", e["title"]], ["Source", e["source"]], ["Source link", e["source_url"]],
            ["Frequency", e["frequency"]], ["Units", e["units"]], ["Seasonal adjustment", e["sa"]],
            ["Source last updated", e["updated"]], ["File built (UTC)", built.strftime("%Y-%m-%d %H:%M")],
            ["Permanent link (CSV)", SITE_URL + e["csv"]], ["", ""]]
    if e.get("citation"):
        rows.append(["Citation", e["citation"]])
    elif e["kind"] == "FRED":
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
               "monthly": wide(fred, frames, "monthly"),
               "quarterly": wide(fred, frames, "quarterly")}             # bank lending standards (review WP6)
    sheet_names = {"daily": "Daily", "weekly": "Weekly (Sat)", "weekly_friday": "Weekly (Fri)", "monthly": "Monthly",
                   "quarterly": "Quarterly"}
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
         "ending Friday, monthly, quarterly) plus a data dictionary",
         "csv": "", "xlsx": "data/bundles/everything.xlsx"},
    ]
    rows = [{k: e[k] for k in ("kind", "id", "name", "source", "source_url", "frequency", "units", "sa", "page",
                               "state", "updated", "csv", "xlsx", "latest_date", "latest_value")}
            | {"dictionary": "data/data_dictionary.csv" if e["kind"] == "DOL" else ""}
            | {"page_label": PAGE_LABELS.get(e["page"], e["page"])} for e in dol + fred]
    model = write_model_files(out, built)
    return {"rows": rows, "bundles": bundles, "excluded": excluded(), "model_files": model,
            "n_files": len(fred) * 2 + len(dol) * 2 + 7 + len(model) * 2}
