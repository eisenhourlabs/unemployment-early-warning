"""
Leading Indicators page: a summary table, then nine charts.
Review WP6: each indicator in the form that carries information (year-ago or 6-month changes), the table sorted by
how unusual each reading is on the risky side, a "Lead in our tests" column, and two new charts.
Phase 3: the table shows the Layer 1 colours of the two panel triggers measured here (yield curve, NFCI); temp help
and the regional factory surveys are labeled as context (not counted in the overall status).
Called by build_site.py.
"""

import csv
from datetime import datetime, timedelta

import pandas as pd

from common import (PROCESSED, ROOT, fmt_date, fmt_month, fred, fred_metadata, line_chart, lines_chart, model_output,
                    signal, value_on_or_before)

INTRO = ("Indicators often cited as moving before layoffs. In our own tests most gave little or no extra warning "
         "beyond jobless claims; the yield curve and financial conditions gave the longest. Two of them are "
         "confirmation triggers with a colour (the yield curve and financial conditions); temporary help and the "
         "regional surveys are shown for context. The triggers and the early-warning score are on the Outlook page.")

# Layer 1 links (Phase 3): catalog series -> (trigger id, note). Panel triggers get their colour; context rows a label.
SIGNAL_FOR = {"T10Y3M": ("yield_curve", "long lead, often 12+ months; the trigger uses monthly averages"),
              "NFCI": ("nfci", "real-time history only since 2011")}
CONTEXT = {"TEMPHELPS": "temp_help", "GACDFSA066MSFRBPHI": "mfg", "GACDISA066MSFRBNY": "mfg"}


def signal_cell(sid: str, live: dict | None) -> dict | None:
    """What the Signal column shows for a series: a trigger colour, a context label, or nothing."""
    if live is None:
        return None
    if sid in SIGNAL_FOR:
        tid, note = SIGNAL_FOR[sid]
        row = next(r for r in live["triggers"]["rows"] if r["id"] == tid)
        return {"signal": signal(row["colour"]), "note": note}
    if sid in CONTEXT:
        out = {"context": "Shown for context"}
        c = next((c for c in live["score"]["contributions"] if c["input"] == CONTEXT[sid]), None)
        if sid == "TEMPHELPS" and c and c.get("sentence"):
            # Same words as the Overview driver, so the two pages never seem to disagree (3e-1 review)
            effect = "pushes the score up" if c["contribution"] > 0 else "pulls the score down"
            out["detail"] = f"{c['sentence']}; in the early-warning score this {effect}."
        return out
    if sid in DERIVED:
        return {"context": "Context: not part of the early-warning score"}
    return None


# Derived series (not from FRED) that also get a summary-table row: catalog ID -> how to read it.
# The state claims diffusion index lives on the States page; here it is context only, with no colour (Phase 4 4b).
def state_diffusion() -> pd.Series:
    d = pd.read_csv(PROCESSED / "states" / "diffusion_weekly.csv", parse_dates=["week_ended"])
    return d.set_index("week_ended").diffusion_ce_weighted_pct.dropna().round(1)


DERIVED = {"STATE_DIFFUSION": state_diffusion}

# Series shown as a % change vs. a year ago instead of their level (the level trends, or as a level it carried
# no warning in our screen; review WP6: permits as a level AUC 0.38 / 0.28, as a year-ago change 0.73 / 0.74).
YEAR_AGO_CHANGE = {"TEMPHELPS", "PERMIT", "JTSJOL", "LNS12032194"}
# Series shown as the change over 6 months, in percentage points (quits rate: as a level AUC 0.39 / 0.31, as a
# 6-month change 0.72 / 0.74; review WP6).
SIX_MONTH_CHANGE = {"JTSQUR"}
# Consumer sentiment is kept for reference (Troy, review WP6): its row is always last and is not ranked.
REFERENCE_ONLY = {"UMCSENT"}

# Which chart card each summary-table row links to (rows without a chart have no link).
CHART_FOR = {"T10Y3M": "yield-curve", "TEMPHELPS": "temp-help", "AWHMAN": "factory-hours", "PERMIT": "permits",
             "GACDFSA066MSFRBPHI": "regional-surveys", "GACDISA066MSFRBNY": "regional-surveys",
             "UMCSENT": "sentiment", "NFCICREDIT": "financial-conditions", "NFCI": "financial-conditions",
             "LNS12032194": "part-time-economic", "DRTSCILM": "bank-standards",
             "STATE_DIFFUSION": "states.html#card-diffusion"}


def page_series(s: pd.Series, series_id: str) -> pd.Series:
    """The series as the page shows it: % change vs. a year ago for YEAR_AGO_CHANGE, the change over 6 months
    (percentage points) for SIX_MONTH_CHANGE, else as published."""
    if series_id in YEAR_AGO_CHANGE:
        monthly = s.asfreq("MS")
        return (100 * (monthly / monthly.shift(12) - 1)).dropna()
    if series_id in SIX_MONTH_CHANGE:
        monthly = s.asfreq("MS")
        return (monthly - monthly.shift(6)).dropna()
    return s


# Plain-English units for the summary table; any other series falls back to FRED's own units label.
UNITS = {"JTSQUR": "Change over 6 months, percentage points", "AWHMAN": "Hours",
         "DRTSCILM": "Net % of banks tightening",
         "T10Y3M": "Percentage points", "PERMIT": "Thousands of units, annual rate",
         "GACDFSA066MSFRBPHI": "Diffusion index", "GACDISA066MSFRBNY": "Diffusion index",
         "UMCSENT": "Index, 1966 Q1 = 100", "NFCICREDIT": "Index, 0 = average", "NFCI": "Index, 0 = average",
         "STATE_DIFFUSION": "Percent of covered jobs"}


def decimals_for(s: pd.Series, series_id: str) -> int:
    """Decimals the publisher uses (from the last 2 years of values), at most 2: 2.1 -> 1, 0.67 -> 2, 1398 -> 0.
    Calculated changes get 1."""
    if series_id in YEAR_AGO_CHANGE or series_id in SIX_MONTH_CHANGE:
        return 1
    recent = s.tail(500 if len(s) > 2000 else 24)
    for d in (0, 1):
        if ((recent * 10 ** d).round() - recent * 10 ** d).abs().max() < 1e-6:
            return d
    return 2


PERCENTILE_START = 1990   # one start year for every percentile in the table; later starts are flagged


# "Reading vs. history" labels (review WP6, Part B): risk_pct at or above each bound gets the label.
RISK_LABELS = [(80, "High"), (60, "Above normal"), (40, "Normal"), (0, "Low")]
YIELD_LOOKBACK = 18   # months; the yield curve is ranked on its lowest monthly average of the past 18 months


def risk_pct(history: pd.Series, latest: float) -> float:
    """Share (in %) of the history at or below the latest value, where both are already turned so that a higher
    value is riskier. 100 = the riskiest reading in the history; near 0 = the safest."""
    history = history.dropna()
    return 100.0 * float((history <= latest).mean())


def risk_label(pct: float) -> str:
    """'High' (80+), 'Above normal' (60 to under 80), 'Normal' (40 to under 60), 'Low' (under 40)."""
    return next(label for bound, label in RISK_LABELS if pct >= bound)


def ranking_series(s: pd.Series, sid: str, frequency: str) -> pd.Series:
    """The values the reading is ranked against. Weekly and daily series use month-start-labelled monthly values
    (the last reading of each month, so the cell can say "of months"), with the latest reading as the last value.
    The yield curve uses the lowest monthly-average spread of the past 18 months, the form the score uses
    (src/model/features.py), so its row does not drop the moment the curve turns back up."""
    if sid == "T10Y3M":
        monthly_avg = s.resample("MS").mean().dropna()
        return monthly_avg.rolling(YIELD_LOOKBACK).min().dropna()
    if frequency in ("weekly", "daily"):
        monthly = s.resample("MS").last().dropna()
        monthly.iloc[-1] = s.iloc[-1]
        return monthly
    return s


def summary_table(live: dict | None = None) -> list[dict]:
    """One row per active catalog series on the 'leading' page (add a catalog row to add a table row).

    Sorted by how unusual the latest reading is on the risky side (review WP6): risk_pct = share of values since
    PERCENTILE_START that are at or below the latest, after turning the series so that higher = riskier (catalog
    column risk_direction: 'down' = falling is toward risk). Rows without a risk_direction follow; consumer
    sentiment is always last and not ranked. The 3-month change is shown for information only."""
    meta = fred_metadata()
    with open(ROOT / "config" / "series_catalog.csv", newline="") as f:
        rows = [r for r in csv.DictReader(f)
                if r["status"] == "active" and ((r["dashboard_page"] == "leading" and r["fetcher"] == "fred")
                                                or r["series_id"] in DERIVED)]
    table = []
    for r in rows:
        sid = r["series_id"]
        s = DERIVED[sid]() if sid in DERIVED else page_series(fred(sid), sid)
        freq = r["frequency"]
        monthly, quarterly = freq == "monthly", freq == "quarterly"
        latest_date, latest = s.index[-1], s.iloc[-1]
        # Change: vs. 3 months earlier (monthly), about 91 days earlier (daily / weekly) or the prior quarter
        if quarterly:
            before = s.iloc[-2]
        else:
            back = latest_date - (pd.DateOffset(months=3) if monthly else timedelta(days=91))
            _, before = value_on_or_before(s, back)
        dec = decimals_for(s, sid)
        change = round(latest - before, dec)
        if sid in YEAR_AGO_CHANGE:
            units = "% change vs. a year ago"
        else:
            units = UNITS[sid] if sid in UNITS else meta.loc[sid, "units"]
        risky_way = r.get("risk_direction", "")

        # Reading vs. history (Part B): where the latest value sits among all values since 1990
        ranked = ranking_series(s, sid, freq)
        hist = ranked[ranked.index.year >= PERCENTILE_START]
        late_start = hist.index[0] > pd.Timestamp(f"{PERCENTILE_START}-01-31")
        start = fmt_month(hist.index[0]) if late_start else PERCENTILE_START
        word = "quarters" if quarterly else "months"
        pct = None
        if sid in REFERENCE_ONLY:
            reading, group = "Shown for reference: not ranked", 2
        elif risky_way in ("up", "down"):
            sign = 1 if risky_way == "up" else -1
            pct = risk_pct(sign * hist, sign * hist.iloc[-1])
            reading, group = f"Riskier than {pct:.0f}% of {word} since {start} · {risk_label(pct)}", 0
        else:
            reading, group = "—", 1

        if quarterly:
            as_of = f"{fmt_month(latest_date)} survey"
        else:
            as_of = fmt_month(latest_date) if monthly else fmt_date(latest_date)
        change_text = "unchanged" if change == 0 else f"{'+' if change > 0 else '−'}{abs(change):,.{dec}f}"
        table.append({
            "name": r["name"],
            "id": sid,
            "units": units,
            "link": CHART_FOR.get(sid, ""),
            "latest": f"{latest:,.{dec}f}".replace("-", "−"),
            "as_of": as_of,
            "change": change_text + (" vs. prior quarter" if quarterly else ""),
            "arrow": "→" if change == 0 else ("↑" if change > 0 else "↓"),
            "direction": "flat" if change == 0 else ("up" if change > 0 else "down"),
            "reading": reading,
            "risk_pct": pct,
            "late_start": late_start and pct is not None,
            "lead": "none found" if sid in REFERENCE_ONLY else (r.get("tested_lead") or "not tested"),
            "sort": (group, -(pct or 0)),
            "yield_curve": sid == "T10Y3M",
            "signal": signal_cell(sid, live),
        })
    return sorted(table, key=lambda row: row["sort"])


def build(built: datetime) -> dict:
    live = model_output(built)["live"]
    charts = []

    # 1. Yield curve: 10-year minus 3-month Treasury (daily)
    charts.append(line_chart(
        "yield-curve", "Yield curve: 10-year minus 3-month",
        "When short rates rise above long rates (below zero), recessions have often followed within about a year.",
        "Source: U.S. Treasury via FRED (T10Y3M). 10-year minus 3-month Treasury constant-maturity yield, "
        "percentage points, daily.",
        fred("T10Y3M"), "10-year minus 3-month", "Percentage points", "%{y:.2f} pp", "spread_10y_3m_pp",
        monthly=False, zero_line=True, x_hover="%b %-d, %Y"))

    # 2. Temporary help jobs, % change vs. a year ago
    charts.append(line_chart(
        "temp-help", "Temporary help jobs vs. a year ago",
        "Firms usually cut temporary staff before permanent staff.",
        "Source: BLS Current Employment Statistics via FRED (TEMPHELPS). Percent change in temporary help services "
        "employment vs. 12 months earlier, seasonally adjusted, monthly.",
        page_series(fred("TEMPHELPS"), "TEMPHELPS"), "% change vs. a year ago", "% change vs. a year ago",
        "%{y:+.1f}%", "temp_help_pct_change_vs_year_ago", zero_line=True))

    # 3. Average weekly hours, manufacturing
    charts.append(line_chart(
        "factory-hours", "Average weekly hours, manufacturing",
        "Employers usually cut hours before they cut jobs.",
        "Source: BLS Current Employment Statistics via FRED (AWHMAN). Average weekly hours of production and "
        "nonsupervisory employees, manufacturing, seasonally adjusted, monthly.",
        fred("AWHMAN"), "Weekly hours", "Hours", "%{y:.1f} hours", "avg_weekly_hours_manufacturing"))

    # 4. Involuntary part-time work, % change vs. a year ago (review WP6)
    charts.append(line_chart(
        "part-time-economic", "Involuntary part-time work vs. a year ago",
        "Employers cut hours before they cut jobs.",
        "Source: BLS Current Population Survey via FRED (LNS12032194). Percent change in the number working part "
        "time for economic reasons vs. 12 months earlier; seasonally adjusted, monthly.",
        page_series(fred("LNS12032194"), "LNS12032194"), "% change vs. a year ago", "% change vs. a year ago",
        "%{y:+.1f}%", "part_time_economic_pct_change_vs_year_ago", zero_line=True))

    # 5. Building permits, % change vs. a year ago (review WP6: as a level they carried no warning in our screen)
    charts.append(line_chart(
        "permits", "Building permits vs. a year ago",
        "Housing turns early in the cycle; fewer permits mean less construction work ahead.",
        "Source: U.S. Census Bureau via FRED (PERMIT). Percent change in new private housing units authorized by "
        "building permits vs. 12 months earlier; monthly.",
        page_series(fred("PERMIT"), "PERMIT"), "% change vs. a year ago", "% change vs. a year ago", "%{y:+.1f}%",
        "permits_pct_change_vs_year_ago", zero_line=True))

    # 6. Regional manufacturing surveys (Philadelphia and New York Fed), same units
    charts.append(lines_chart(
        "regional-surveys", "Regional manufacturing surveys",
        "Early monthly reads on factory activity; below zero means more firms report declines than gains.",
        "Source: Federal Reserve Banks of Philadelphia and New York via FRED (GACDFSA066MSFRBPHI, GACDISA066MSFRBNY). "
        "Current general activity diffusion indexes, seasonally adjusted, monthly; Empire State starts Jul 2001.",
        [(fred("GACDFSA066MSFRBPHI"), "Philadelphia Fed", "Philly Fed"),
         (fred("GACDISA066MSFRBNY"), "Empire State (New York Fed)", "Empire")],
        "Diffusion index", "%{y:.1f}", ["date", "philadelphia_fed_general_activity", "empire_state_general_activity"],
        zero_line=True))

    # 7. Financial and credit conditions: NFCI and its credit subindex in one chart (weekly; review WP6)
    charts.append(lines_chart(
        "financial-conditions", "Financial and credit conditions (NFCI)",
        "Broad financial conditions and their credit component; above zero means tighter than average. Tighter "
        "credit makes it harder for firms to fund payrolls.",
        "Source: Federal Reserve Bank of Chicago via FRED (NFCI, NFCICREDIT). Zero = average since 1971, positive = "
        "tighter. Weekly, week ending Friday.",
        [(fred("NFCI"), "NFCI", "NFCI"), (fred("NFCICREDIT"), "Credit subindex", "Credit")],
        "Index (0 = average)", "%{y:.2f}", ["date", "nfci", "nfci_credit_subindex"],
        zero_line=True, freq="W-FRI", monthly=False))

    # 8. Banks tightening standards on business loans (Senior Loan Officer Survey, quarterly; review WP6)
    charts.append(line_chart(
        "bank-standards", "Banks tightening standards on business loans",
        "When banks tighten credit to firms, hiring freezes and layoffs have followed two to four quarters later.",
        "Source: Federal Reserve Board, Senior Loan Officer Opinion Survey, via FRED (DRTSCILM). Net percentage of "
        "domestic banks tightening standards for commercial and industrial loans to large and middle-market firms; "
        "quarterly; above zero = more banks tightening than easing.",
        fred("DRTSCILM"), "Net % of banks tightening", "Net % of banks tightening", "%{y:.1f}",
        "net_pct_banks_tightening_ci_loans", zero_line=True, freq="QS", x_hover="%b %Y survey"))

    # 9. Consumer sentiment (licensed: citation required, no downloads). Last on the page, for reference (WP6).
    charts.append(line_chart(
        "sentiment", "Consumer sentiment",
        "Widely quoted. In our checks it has not helped separate risky months from quiet ones, so it is shown for "
        "reference.",
        f"FRED publishes this series with about a one-month delay (latest: {fmt_month(fred('UMCSENT').index[-1])}). "
        # Review WP9 C11: the permission in FRED's series notes is FRED's, not this site's; the FRED citation
        # asks for an access date, which is the build date.
        "Source: Surveys of Consumers, University of Michigan, University of Michigan: Consumer Sentiment © "
        "[UMCSENT], retrieved from FRED, Federal Reserve Bank of St. Louis "
        f"(https://fred.stlouisfed.org/series/UMCSENT/), accessed {fmt_date(built)}. Copyright Surveys of "
        "Consumers, University of Michigan. Shown as a chart with this citation; the data are not offered for "
        "download here. Index, 1966 Q1 = 100, not seasonally adjusted, monthly.",
        fred("UMCSENT"), "Consumer sentiment", "Index (1966 Q1 = 100)", "%{y:.1f}", "consumer_sentiment_index",
        downloadable=False))

    return {"intro": INTRO, "summary": summary_table(live), "charts": charts}
