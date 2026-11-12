"""
Job Losses page (frequency: how many people are losing jobs). Eight charts, in the design's order
(the eighth, ADP vs. BLS private payrolls, is the Phase 4 stage 4d context chart).
Called by build_site.py.
"""

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go

from common import (WHATIF_FOOTER, add_whatif, bars_with_average, claims_weekly, fred, line_chart, lines_chart,
                    model_output,
                    ordinal, seasonal_chart, weekly_claims_chart, with_outlook, year_ago_change_pct)
from overview import ic_rate_chart

INTRO = ("How many people are losing jobs. State UI initial claims are the fastest signal, published every "
         "Thursday; payrolls, JOLTS and the household survey confirm it monthly. Claims are applications under "
         "state rules: a guide to direction and timing.")


def initial_claims_sources(claims: pd.DataFrame) -> pd.Series:
    """Source label for each week (ETA 539 or news release), indexed by week. Weeks before our DOL data
    (1971) come from FRED, which republishes DOL's official figures, so they count as ETA 539."""
    return claims.set_index("week_ended")["source_initial"]


def score_driver_line(live: dict) -> str | None:
    """Where new claims stand in the early-warning score, e.g. 'currently the largest downward pull'."""
    parts = [c for c in live["score"]["contributions"] if abs(c["contribution"]) > 1e-9]
    parts.sort(key=lambda c: -abs(c["contribution"]))
    pos = next((i for i, c in enumerate(parts) if c["input"] == "claims_low"), None)
    if pos is None:
        return None
    c = parts[pos]
    which = "the largest" if pos == 0 else f"the {ordinal(pos + 1)}-largest"
    return (f"In the early-warning score, new claims (vs. their 52-week low) are currently {which} "
            f"{'upward push' if c['contribution'] > 0 else 'downward pull'}.")


def ic_outlook(c: dict, live: dict) -> dict:
    """Phase 3 on the initial-claims-rate chart: what-if paths (no fan) and the notes the design asks for."""
    fig = go.Figure(c["figure"])
    whatif_ahead = add_whatif(fig, live["stress"]["ic"], 100, ".1f", " per 10k")   # stored in %, shown per 10,000
    notes = [n for n in [score_driver_line(live)] if n]
    notes.append("We don't show a forecast range for initial claims: in testing it was no more accurate than assuming "
                 "no change. The early-warning score (Overview, Outlook) is our forward view of new claims.")
    return with_outlook(c, fig, None, whatif_ahead, notes,
                        WHATIF_FOOTER.replace("from today's level", "from the latest 4-week average"))


def build(built: datetime) -> dict:
    claims = claims_weekly()
    sources = initial_claims_sources(claims)
    live = model_output(built)["live"]
    charts = []

    # 1. SA initial claims rate (same chart as the Overview), full width; Phase 3: what-if paths and notes
    ic = ic_rate_chart(claims, wide=True)
    charts.append(ic_outlook(ic, live) if live else ic)

    # 2. SA initial claims level: 4-week average bold, weekly faint (FRED, from 1967)
    level = pd.DataFrame({"ic_sa": fred("ICSA"), "ic_sa_4wk": fred("IC4WSA")})
    level.index.name = "week_ended"
    level = level.reset_index()
    level["source"] = level.week_ended.map(sources).fillna("ETA 539")
    charts.append(weekly_claims_chart(
        "ic-level", "SA initial claims",
        "Week-to-week detail on new claims; the 4-week average smooths holiday and weather noise.",
        "Source: DOL state UI claims via FRED (ICSA, IC4WSA). Seasonally adjusted, number of claims, weekly.",
        level, "ic_sa", "ic_sa_4wk", "source", "Initial claims (SA)", "%{y:,.0f}",
        ["week_ended", "ic_sa", "ic_sa_4wk", "source"]))

    # 3. NSA initial claims: this year vs. the prior 3 years, by week of year (fixed view)
    charts.append(seasonal_chart(
        "ic-nsa-seasonal", "NSA initial claims: this year vs. the prior 3 years",
        "Raw claims follow a strong seasonal pattern; comparing years checks the seasonal adjustment.",
        "Source: DOL state UI claims (ETA 539 weekly report and Thursday news release). Not seasonally adjusted, "
        "number of claims, "
        "weekly, by week-ending date. Fixed view: ignores the page time control.",
        claims[["week_ended", "ic_nsa", "source_initial"]], "ic_nsa", "source_initial", "%{y:,.0f}",
        ["week_ended", "year", "ic_nsa", "source"]))

    # 4. Initial claims 4-week average, % change vs. a year ago
    yoy = year_ago_change_pct(fred("IC4WSA"))
    charts.append(line_chart(
        "ic-yoy", "Initial claims vs. a year ago",
        "Turns the claims level into a trend: above zero means claims are running higher than a year ago.",
        "Source: DOL state UI claims via FRED (IC4WSA). Percent change in the SA 4-week average vs. the same week "
        "52 weeks earlier, weekly.",
        yoy, "% change vs. a year ago", "% change vs. a year ago", "%{y:+.1f}%", "ic_sa_4wk_pct_change_vs_year_ago",
        monthly=False, zero_line=True, prelim=sources))

    # 5. Payroll change: monthly bars with 3-month average (thousands of jobs)
    payroll_change = fred("PAYEMS").diff().dropna()
    charts.append(bars_with_average(
        "payrolls", "Payroll change",
        "Net jobs added or lost each month: the broadest monthly measure of hiring minus job losses. Payroll "
        "change is net (hiring minus separations), so layoffs can rise while payrolls still grow.",
        "Source: BLS Current Employment Statistics via FRED (PAYEMS). Monthly change in total nonfarm "
        "payrolls, thousands of jobs, seasonally adjusted.",
        payroll_change, "Monthly change", "3-month average", "Thousands of jobs", "%{y:+,.0f}k",
        ["month", "payroll_change_thousands", "payroll_change_3m_avg_thousands"]))

    # 6. JOLTS layoffs and discharges rate
    charts.append(line_chart(
        "jolts-layoffs", "JOLTS layoffs and discharges rate",
        "Layoffs reported by employers, including those that never lead to an unemployment claim.",
        "Source: BLS Job Openings and Labor Turnover Survey via FRED (JTSLDR). Layoffs and discharges as a "
        "percent of total employment, seasonally adjusted, monthly; JOLTS starts Dec 2000.",
        fred("JTSLDR"), "Layoffs and discharges rate", "Percent of employment", "%{y:.1f}%",
        "layoffs_discharges_rate_pct"))

    # 7. Newly unemployed (less than 5 weeks)
    charts.append(line_chart(
        "newly-unemployed", "Newly unemployed (less than 5 weeks)",
        "A proxy for fresh inflow into unemployment, from the household survey, whether or not people file a claim.",
        "Source: BLS Current Population Survey via FRED (UEMPLT5). Number unemployed less than 5 weeks, "
        "thousands, seasonally adjusted, monthly. Gap: no October 2025 survey (government shutdown).",
        fred("UEMPLT5"), "Unemployed < 5 weeks", "Thousands of people", "%{y:,.0f}k", "unemployed_lt5wk_thousands"))

    # 8. Alternative employment read (Phase 4 stage 4d): ADP private payrolls vs. BLS private payrolls, monthly change.
    # Planned as Revelio RPLS; its Terms of Service do not allow it, so ADP (public via FRED) takes its place.
    adp = fred("ADPMNUSNERSA").diff() / 1000          # ADP is in persons; thousands like BLS
    bls = fred("USPRIV").diff()                       # BLS private nonfarm payrolls, thousands
    gap = (adp - bls).dropna()
    gap = gap[(gap.index >= "2010-02-01") & ((gap.index < "2020-03-01") | (gap.index > "2021-12-01"))].abs()
    charts.append(lines_chart(
        "adp-vs-bls", "Private payrolls: ADP vs. BLS",
        "A second, independent read on private jobs; useful when the BLS jobs report is delayed (as in the October "
        "2025 shutdown).",
        "Sources: ADP National Employment Report via FRED (ADPMNUSNERSA) and BLS Current Employment Statistics via "
        "FRED (USPRIV). Monthly change in private nonfarm payrolls, thousands of jobs, seasonally adjusted, from 2010. "
        "ADP is built from payroll records of ADP clients and published two days before the BLS report. Outside "
        f"2020-21 the two differ by about {gap.median():,.0f}k jobs in a typical month and by 100k or more in "
        f"{(gap >= 100).mean() * 10:.0f} months out of 10. Context only: not used in the early-warning score.",
        [(adp[adp.index >= "2010-02-01"], "ADP private payrolls", "ADP"),
         (bls[bls.index >= "2010-02-01"], "BLS private payrolls", "BLS")],
        "Thousands of jobs", "%{y:+,.0f}k",
        ["month", "adp_private_change_thousands", "bls_private_change_thousands"], zero_line=True))

    return {"intro": INTRO, "charts": charts}
