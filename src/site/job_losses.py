"""
Job Losses page (frequency: how many people are losing jobs). Seven charts, in the design's order.
Called by build_site.py.
"""

import pandas as pd

from common import (bars_with_average, claims_weekly, fred, line_chart, seasonal_chart, weekly_claims_chart,
                    year_ago_change_pct)
from overview import ic_rate_chart

INTRO = ("New job losses drive how often IUI claims start (claim frequency). Initial claims are the fastest "
         "signal, published every Thursday; payrolls, JOLTS and the household survey confirm it monthly.")


def initial_claims_sources(claims: pd.DataFrame) -> pd.Series:
    """Source label for each week (ETA 539 or news release), indexed by week. Weeks before our DOL data
    (1995) come from FRED, which republishes DOL's official figures, so they count as ETA 539."""
    return claims.set_index("week_ended")["source_initial"]


def build() -> dict:
    claims = claims_weekly()
    sources = initial_claims_sources(claims)
    charts = []

    # 1. SA initial claims rate (same chart as the Overview), full width
    charts.append(ic_rate_chart(claims, wide=True))

    # 2. SA initial claims level: 4-week average bold, weekly faint (FRED, from 1967)
    level = pd.DataFrame({"ic_sa": fred("ICSA"), "ic_sa_4wk": fred("IC4WSA")})
    level.index.name = "week_ended"
    level = level.reset_index()
    level["source"] = level.week_ended.map(sources).fillna("ETA 539")
    charts.append(weekly_claims_chart(
        "ic-level", "SA initial claims",
        "Week-to-week detail on new claims; the 4-week average smooths holiday and weather noise.",
        "Source: DOL weekly claims via FRED (ICSA, IC4WSA). Seasonally adjusted, number of claims, weekly.",
        level, "ic_sa", "ic_sa_4wk", "source", "Initial claims (SA)", "%{y:,.0f}",
        ["week_ended", "ic_sa", "ic_sa_4wk", "source"]))

    # 3. NSA initial claims: this year vs. the prior 3 years, by week of year (fixed view)
    charts.append(seasonal_chart(
        "ic-nsa-seasonal", "NSA initial claims: this year vs. the prior 3 years",
        "Raw claims follow a strong seasonal pattern; comparing years checks the seasonal adjustment.",
        "Source: DOL weekly claims (ETA 539 and news release). Not seasonally adjusted, number of claims, "
        "weekly, by week-ending date. Fixed view: ignores the page time control.",
        claims[["week_ended", "ic_nsa", "source_initial"]], "ic_nsa", "source_initial", "%{y:,.0f}",
        ["week_ended", "year", "ic_nsa", "source"]))

    # 4. Initial claims 4-week average, % change vs. a year ago
    yoy = year_ago_change_pct(fred("IC4WSA"))
    charts.append(line_chart(
        "ic-yoy", "Initial claims vs. a year ago",
        "Turns the claims level into a trend: above zero means claims are running higher than a year ago.",
        "Source: DOL weekly claims via FRED (IC4WSA). Percent change in the SA 4-week average vs. the same week "
        "52 weeks earlier, weekly.",
        yoy, "% change vs. a year ago", "% change vs. a year ago", "%{y:+.1f}%", "ic_sa_4wk_pct_change_vs_year_ago",
        monthly=False, zero_line=True, prelim=sources))

    # 5. Payroll change: monthly bars with 3-month average (thousands of jobs)
    payroll_change = fred("PAYEMS").diff().dropna()
    charts.append(bars_with_average(
        "payrolls", "Payroll change",
        "Net jobs added or lost each month: the broadest monthly measure of hiring minus job losses.",
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
        "Fresh inflow into unemployment from the household survey, whether or not people file a claim.",
        "Source: BLS Current Population Survey via FRED (UEMPLT5). Number unemployed less than 5 weeks, "
        "thousands, seasonally adjusted, monthly. Gap: no October 2025 survey (government shutdown).",
        fred("UEMPLT5"), "Unemployed < 5 weeks", "Thousands of people", "%{y:,.0f}k", "unemployed_lt5wk_thousands"))

    return {"intro": INTRO, "charts": charts}
