"""
Leading Indicators page (simple version): a summary table, then eight charts.
No signal colors yet: Phase 3 adds them once thresholds are backtested.
Called by build_site.py.
"""

import csv
from datetime import timedelta

import pandas as pd

from common import (ROOT, fmt_date, fmt_month, fred, fred_metadata, line_chart, lines_chart, percentile_text,
                    value_on_or_before)

INTRO = ("Indicators that have tended to move before layoffs: the yield curve, temporary help jobs, factory "
         "hours, housing permits, regional surveys, consumer sentiment and financial conditions. Shown as-is "
         "for now; Phase 3 adds green / amber / red signals once thresholds are backtested.")

# Series shown as a % change vs. a year ago instead of their level (the level just trends up over time).
YEAR_AGO_CHANGE = {"TEMPHELPS"}

# Which chart card each summary-table row links to (rows without a chart have no link).
CHART_FOR = {"T10Y3M": "yield-curve", "TEMPHELPS": "temp-help", "AWHMAN": "factory-hours", "PERMIT": "permits",
             "GACDFSA066MSFRBPHI": "regional-surveys", "GACDISA066MSFRBNY": "regional-surveys",
             "UMCSENT": "sentiment", "NFCICREDIT": "credit-conditions", "NFCI": "financial-conditions"}


def page_series(s: pd.Series, series_id: str) -> pd.Series:
    """The series as the page shows it: % change vs. a year ago for YEAR_AGO_CHANGE, else as published."""
    if series_id in YEAR_AGO_CHANGE:
        monthly = s.asfreq("MS")
        return (100 * (monthly / monthly.shift(12) - 1)).dropna()
    return s


# Plain-English units for the summary table; any other series falls back to FRED's own units label.
UNITS = {"JTSQUR": "Percent of employment", "JTSJOL": "Thousands of openings", "AWHMAN": "Hours",
         "T10Y3M": "Percentage points", "PERMIT": "Thousands of units, annual rate",
         "GACDFSA066MSFRBPHI": "Diffusion index", "GACDISA066MSFRBNY": "Diffusion index",
         "UMCSENT": "Index, 1966 Q1 = 100", "NFCICREDIT": "Index, 0 = average", "NFCI": "Index, 0 = average"}


def decimals_for(s: pd.Series, series_id: str) -> int:
    """Decimals the publisher uses (from the last 2 years of values), at most 2: 2.1 -> 1, 0.67 -> 2, 1398 -> 0.
    Calculated % changes get 1."""
    if series_id in YEAR_AGO_CHANGE:
        return 1
    recent = s.tail(500 if len(s) > 2000 else 24)
    for d in (0, 1):
        if ((recent * 10 ** d).round() - recent * 10 ** d).abs().max() < 1e-6:
            return d
    return 2


def summary_table() -> list[dict]:
    """One row per active catalog series on the 'leading' page (add a catalog row to add a table row)."""
    meta = fred_metadata()
    with open(ROOT / "config" / "series_catalog.csv", newline="") as f:
        rows = [r for r in csv.DictReader(f)
                if r["dashboard_page"] == "leading" and r["status"] == "active" and r["fetcher"] == "fred"]
    table = []
    for r in rows:
        sid = r["series_id"]
        s = page_series(fred(sid), sid)
        monthly = r["frequency"] == "monthly"
        latest_date, latest = s.index[-1], s.iloc[-1]
        # 3-month change: vs. 3 months earlier (monthly) or about 91 days earlier (daily / weekly)
        back = latest_date - (pd.DateOffset(months=3) if monthly else timedelta(days=91))
        _, before = value_on_or_before(s, back)
        dec = decimals_for(s, sid)
        change = round(latest - before, dec)
        units = "% change vs. a year ago" if sid in YEAR_AGO_CHANGE else UNITS.get(sid, meta.loc[sid, "units"])
        table.append({
            "name": r["name"],
            "units": units,
            "link": CHART_FOR.get(sid, ""),
            "latest": f"{latest:,.{dec}f}".replace("-", "−"),
            "as_of": fmt_month(latest_date) if monthly else fmt_date(latest_date),
            "change": "unchanged" if change == 0 else f"{'+' if change > 0 else '−'}{abs(change):,.{dec}f}",
            "arrow": "→" if change == 0 else ("↑" if change > 0 else "↓"),
            "direction": "flat" if change == 0 else ("up" if change > 0 else "down"),
            "percentile": percentile_text(s, latest, s.index[0].year),
            "lead": r["typical_lead"],
        })
    return table


def build() -> dict:
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

    # 4. Building permits
    charts.append(line_chart(
        "permits", "Building permits",
        "Housing turns early in the cycle; fewer permits mean less construction work ahead.",
        "Source: U.S. Census Bureau via FRED (PERMIT). New private housing units authorized by building permits, "
        "thousands of units at a seasonally adjusted annual rate, monthly.",
        fred("PERMIT"), "Building permits", "Thousands of units (annual rate)", "%{y:,.0f}k",
        "permits_thousands_saar"))

    # 5. Regional manufacturing surveys (Philadelphia and New York Fed), same units
    charts.append(lines_chart(
        "regional-surveys", "Regional manufacturing surveys",
        "Early monthly reads on factory activity; below zero means more firms report declines than gains.",
        "Source: Federal Reserve Banks of Philadelphia and New York via FRED (GACDFSA066MSFRBPHI, GACDISA066MSFRBNY). "
        "Current general activity diffusion indexes, seasonally adjusted, monthly; Empire State starts Jul 2001.",
        [(fred("GACDFSA066MSFRBPHI"), "Philadelphia Fed", "Philly Fed"),
         (fred("GACDISA066MSFRBNY"), "Empire State (New York Fed)", "Empire")],
        "Diffusion index", "%{y:.1f}", ["date", "philadelphia_fed_general_activity", "empire_state_general_activity"],
        zero_line=True))

    # 6. Consumer sentiment (licensed: citation required, no downloads)
    charts.append(line_chart(
        "sentiment", "Consumer sentiment",
        "Worried consumers spend less, and their worries often include their own jobs.",
        "Source: Surveys of Consumers, University of Michigan: Consumer Sentiment © [UMCSENT], retrieved from FRED, "
        "Federal Reserve Bank of St. Louis (https://fred.stlouisfed.org/series/UMCSENT/). Copyright Surveys of "
        "Consumers, University of Michigan; reprinted with permission. Index, 1966 Q1 = 100, not seasonally "
        "adjusted, monthly.",
        fred("UMCSENT"), "Consumer sentiment", "Index (1966 Q1 = 100)", "%{y:.1f}", "consumer_sentiment_index",
        downloadable=False))

    # 7. Credit conditions: Chicago Fed NFCI credit subindex (weekly)
    charts.append(line_chart(
        "credit-conditions", "Credit conditions (NFCI credit subindex)",
        "Tighter credit makes it harder for firms to fund payrolls; above zero means tighter than average.",
        "Source: Federal Reserve Bank of Chicago via FRED (NFCICREDIT). Credit subindex of the National Financial "
        "Conditions Index; zero = average since 1971, positive = tighter. Weekly, week ending Friday.",
        fred("NFCICREDIT"), "NFCI credit subindex", "Index (0 = average)", "%{y:.2f}", "nfci_credit_subindex",
        monthly=False, zero_line=True))

    # 8. Financial conditions: Chicago Fed NFCI (weekly)
    charts.append(line_chart(
        "financial-conditions", "Financial conditions (NFCI)",
        "Broad credit, risk and leverage conditions; above zero means tighter than average.",
        "Source: Federal Reserve Bank of Chicago via FRED (NFCI). National Financial Conditions Index; zero = "
        "average since 1971, positive = tighter. Weekly, week ending Friday.",
        fred("NFCI"), "NFCI", "Index (0 = average)", "%{y:.2f}", "nfci", monthly=False, zero_line=True))

    return {"intro": INTRO, "summary": summary_table(), "charts": charts}
