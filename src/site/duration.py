"""
Duration page (severity: how long unemployment lasts). The Duration watch card (review WP5) and ten charts.
Called by build_site.py.
"""

import json
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go

from common import (DOL, MODEL, PROCESSED, WHATIF_FOOTER, add_fan, add_marker, add_whatif, claims_weekly,
                    duration_watch, fmt_date, fred, line_chart, line_with_comparison, model_output, signal,
                    weekly_claims_chart, with_outlook)
from overview import cc_rate_chart

INTRO = ("How long unemployment lasts. State UI continuing claims show it weekly; exhaustion and benefit duration "
         "come monthly and quarterly from DOL's state UI reports; the household survey and JOLTS hiring add the "
         "wider picture. Continuing claims count people on benefits; they rise with more new claims as well as "
         "with longer spells.")


def us_rows(filename: str, date_col: str) -> pd.DataFrame:
    """US rows of a DOL by-state file, indexed by date."""
    df = pd.read_csv(DOL / filename, parse_dates=[date_col])
    return df[df.state == "US"].set_index(date_col)


def ar218_not_reported() -> str:
    """Review Gate 2: name the states holding back the latest ETA 218 quarter (e.g. Alabama, 2026 Q3), so a blank US
    value reads as 'not reported', not as missing data."""
    b = pd.read_csv(DOL / "benefit_duration_quarterly.csv", parse_dates=["quarter_ended"])
    states = b[b.state != "US"]
    latest = states.quarter_ended.max()
    if (b[(b.state == "US") & (b.quarter_ended == latest)].potential_avg_weeks.notna()).any():
        return ""
    names = pd.read_csv(DOL.parents[2] / "config" / "states.csv", comment="#", dtype=str).set_index("state").state_name
    missing = sorted(set(names.index) - set(states[states.quarter_ended == latest].state))
    q = f"Q{(latest.month - 1) // 3 + 1} {latest.year}"
    return (f" {q} is not shown yet: not reported by {', '.join(names.get(s, s) for s in missing)}."
            if missing else "")


def cc_outlook(c: dict, live: dict) -> dict:
    """Phase 3 on the continuing-claims-rate chart: the 13 and 26-week fan, what-if paths, and why 52 weeks is not
    shown (its 80% band held too few outcomes in testing)."""
    fig = go.Figure(c["figure"])
    ahead = add_fan(fig, live["fans"]["cc"], 1, ".2f", "%",
                    lambda h: f"week ending {fmt_date(h['target_period'])} ({h['horizon']} weeks)", labels_below=True)
    whatif_ahead = add_whatif(fig, live["stress"]["cc"], 1, ".2f", "%")
    ev = pd.read_csv(MODEL / "forecast_evaluation.csv")
    row = ev[(ev.target == "cc") & (ev.horizon == 52) & (ev.subset == "2000-on excl. 2020")]
    held = f" (80% bands held only {row.cover80.iloc[0] * 100:.0f}% of outcomes)" if len(row) else ""
    notes = [f"52-week ranges are not shown: in testing they were too narrow{held}."]
    # Review WP3 (F6): coverage as measured in testing, at the two horizons shown
    shown = ev[(ev.target == "cc") & ev.horizon.isin([13, 26]) & (ev.subset == "2000-on excl. 2020")]
    span = lambda col: f"{shown[col].min() * 100:.0f}–{shown[col].max() * 100:.0f}%"
    return with_outlook(c, fig, ahead, whatif_ahead, notes,
                        " Fan = our forecast range for the 4-week average at 13 and 26 weeks: in testing (2000–2026, "
                        f"excluding 2020) the darker band held {span('cover50')} of outcomes and the lighter band "
                        f"{span('cover80')}; when it missed, outcomes were more often below the range than above it."
                        + WHATIF_FOOTER)


# ===========================================================================
# Duration watch (review WP5, Part C): an early read on claim severity from continuing claims vs. a year ago
# ===========================================================================
# The spec's wording in square brackets (no percentages) until WP8 test T2 has passed; then the table shows too.
T2_PASSED = False
WATCH_HEADLINE = {
    "falling": "Continuing claims are {x}% below a year ago. In the past, durations have almost never lengthened in "
               "the following year from here.",
    "green": "Continuing claims are {x}% above a year ago. Durations have occasionally lengthened within a year from "
             "here.",
    "amber": "Continuing claims are {x}% above a year ago. Long-term unemployment has usually risen sharply within a "
             "year from here.",
    "red": "Continuing claims are {x}% above a year ago. Long-term unemployment has risen sharply within a year in "
           "most cases from here, and benefit durations have lengthened for one to two years after layoffs peaked.",
}
WATCH_WHY = ("For involuntary unemployment insurance, this is the early read on claim severity: the official duration "
             "measures below move 6 to 18 months later.")
WATCH_FOOTER = ("Rule: 4-week average of SA continuing claims vs. the same weeks a year earlier; amber from +10%, red "
                "from +20% (the same thresholds as confirmation trigger 4 on the Outlook page). \u2018Risen sharply\u2019 = "
                "share of unemployed out of work 27+ weeks up 3 points or more within 12 months; 1968–2026 excluding "
                "2019–21; today's revised data. Continuing claims rise when more people start claiming as well as "
                "when people stay on benefits longer, so this is an early read on duration, not a direct measure of "
                "it. Not a forecast.")
BAND_LABELS = {"falling": "Falling (below a year ago)", "green": "Steady (0 to +10%)", "amber": "Rising (+10% to +20%)",
               "red": "Rising fast (+20% or more)"}


def watch_card(live: dict | None) -> dict | None:
    """The Duration watch card from trigger 4's live value (None without model output)."""
    if live is None:
        return None
    row = next((r for r in live["triggers"]["rows"] if r["id"] == "cont_claims_yoy"), None)
    if row is None or row.get("value") is None:
        return None
    v = float(row["value"])
    dw = duration_watch(v)
    out = {"signal": {**signal(dw["colour"]), "label": dw["word"]},
           "headline": WATCH_HEADLINE[dw["band"]].format(x=round(abs(v) * 100)),
           "why": WATCH_WHY, "footer": WATCH_FOOTER, "table": None,
           "asof": f"Continuing claims through the week ending {fmt_date(live['inputs']['continuing_claims_week'])}"}
    if T2_PASSED:      # the backtest table, once the real-time check (WP8 T2) has passed
        sw = pd.read_csv(MODEL / "severity_watch.csv")
        pick = lambda o, b: sw[(sw.outcome == o) & (sw.band == b)].iloc[0]
        out["table"] = [{"band": BAND_LABELS[b], "months": int(pick("lt_share_up", b).months),
                         "lt": f"{pick('lt_share_up', b).share_followed * 100:.0f}%",
                         "median": f"{pick('median_up', b).share_followed * 100:.0f}%", "current": b == dw["band"]}
                        for b in ("falling", "green", "amber", "red")]
    return out


def flows() -> pd.DataFrame | None:
    """data/processed/labor_flows_monthly.csv (src/transforms/labor_flows.py), or None if not built."""
    path = PROCESSED / "labor_flows_monthly.csv"
    return pd.read_csv(path, parse_dates=["month"]).set_index("month") if path.exists() else None


def build(built: datetime) -> dict:
    claims = claims_weekly()
    live = model_output(built)["live"]
    charts = []

    # 1. SA continuing claims rate (same chart as the Overview), with how closely it matches DOL's IUR
    rate = cc_rate_chart(claims, wide=True)
    both = claims.dropna(subset=["cc_rate_sa", "iur_sa_published"])
    max_diff = (both.cc_rate_sa - both.iur_sa_published).abs().max()
    rate["footer"] += (f" Check: within {max_diff:.2f} pp of DOL's published insured unemployment rate in every "
                       f"week since {both.week_ended.dt.year.min()} (DOL rounds to 0.1).")
    charts.append(cc_outlook(rate, live) if live else rate)
    if live:   # review WP7 (P3): the caveat a reader should see without opening the footer
        charts[-1]["caveat"] = ("The range has been about right overall and a little too narrow since 2021. It is a "
                                "range for the next 3 to 6 months, not a view on a downturn.")

    # 2. SA continuing claims level: 4-week average bold, weekly faint (FRED, from 1967)
    sources = claims.set_index("week_ended")["source_continued"]
    level = pd.DataFrame({"cc_sa": fred("CCSA"), "cc_sa_4wk": fred("CC4WSA")})
    level.index.name = "week_ended"
    level = level.reset_index()
    level["source"] = level.week_ended.map(sources).fillna("ETA 539")
    charts.append(weekly_claims_chart(
        "cc-level", "SA continuing claims",
        "Number of people still claiming state UI benefits; continuing claims run a week behind initial claims.",
        "Source: DOL state UI claims via FRED (CCSA, CC4WSA). Seasonally adjusted, number of people claiming, weekly.",
        level, "cc_sa", "cc_sa_4wk", "source", "Continuing claims (SA)", "%{y:,.0f}",
        ["week_ended", "cc_sa", "cc_sa_4wk", "source"]))

    # 2b. Continuing claims per new claim (review WP5: stock-flow ratio)
    fl = flows()
    if fl is not None:
        charts.append(line_chart(
            "claims-stock-flow", "Continuing claims per new claim",
            "How many weeks\u2019 worth of new claims are still on the rolls. It rises when people stay on benefits "
            "longer, months before the exhaustion rate does.",
            "Our calculation from DOL claims via FRED (CCSA, ICSA): 4-week average continuing claims ÷ average weekly "
            "initial claims of the prior 26 weeks. Monthly (last week of each month).",
            fl["cc_per_new_claim"], "Continuing claims per new claim", "Weeks of new claims", "%{y:.1f}",
            "cc_per_new_claim"))

    # 3. Exhaustion rate, 12-month (our calculation from DOL's monthly ETA 5159 report)
    monthly = us_rows("exhaustion_duration_monthly.csv", "month_ended")
    charts.append(line_chart(
        "exhaustion-rate", "Exhaustion rate (12-month)",
        "Share of claimants who use up all their state benefits. It does not show whether they then found work.",
        "DOL standard definition · NSA, 12-month average. Source: DOL ETA 5159 (state UI claims and payments), our calculation: 12-month average final payments ÷ "
        "12-month average first payments 6 months earlier. Percent, US. US = sum of all states (can differ "
        "slightly from DOL's published US figure: 0.08 pp in 2026 Q2). Monthly, dated at month end.",
        monthly["exhaustion_rate_12m"], "Exhaustion rate", "Percent of claimants", "%{y:.1f}%",
        "exhaustion_rate_12m_pct", freq="ME"))

    # 4. Average benefit duration: all claimants (monthly) vs. weeks entitled (quarterly ETA 218)
    quarterly = us_rows("benefit_duration_quarterly.csv", "quarter_ended")
    unreported = ar218_not_reported()
    charts.append(line_with_comparison(
        "benefit-duration", "Average benefit duration",
        "Weeks of state UI benefits paid per claimant, against weeks entitled. It covers people receiving state "
        "benefits, not all unemployed people. For involuntary unemployment "
        "insurance (IUI), the closest public match to benefit months.",
        "DOL standard definition · NSA, 12-month average. Source: DOL ETA 5159 and ETA 218, our calculation. Bold: 12-month weeks compensated ÷ 12-month first "
        "payments, all claimants, monthly. Grey: average potential (entitled) duration of new claimants, "
        "quarterly. Weeks, US; quarters with a state missing are left blank." + unreported,
        monthly["avg_duration_12m"], "Average weeks paid (all claimants)", "ME",
        quarterly["potential_avg_weeks"], "Average weeks entitled (ETA 218)", "QE",
        "Weeks", "%{y:.1f} weeks",
        ["date", "avg_weeks_paid_all_claimants_12m", "avg_potential_weeks_eta218", "avg_weeks_exhaustees_eta218"],
        extra=quarterly["actual_avg_weeks"]))

    # 5. Median weeks unemployed (household survey)
    charts.append(line_chart(
        "median-weeks", "Median weeks unemployed",
        "How long a typical unemployed person has been looking, whether or not they claim benefits.",
        "Source: BLS Current Population Survey via FRED (UEMPMED). Median duration of unemployment, weeks, "
        "seasonally adjusted, monthly; starts Jul 1967. Gap: no October 2025 survey (government shutdown).",
        fred("UEMPMED"), "Median weeks unemployed", "Weeks", "%{y:.1f} weeks", "median_weeks_unemployed"))

    # 6. Share unemployed 27 weeks or more (household survey)
    charts.append(line_chart(
        "long-term-share", "Share unemployed 27 weeks or more",
        "Long-term unemployment: the tail that turns into the longest claims.",
        "Source: BLS Current Population Survey via FRED (LNS13025703). Unemployed 27 weeks or more as a percent "
        "of all unemployed, seasonally adjusted, monthly. Gap: no October 2025 survey (government shutdown).",
        fred("LNS13025703"), "Share unemployed 27+ weeks", "Percent of unemployed", "%{y:.1f}%",
        "share_unemployed_27wk_plus_pct"))

    # 6b. Job-finding rate and 6c. job openings per unemployed (review WP5, I2)
    if fl is not None:
        jf = line_chart(
            "job-finding", "Job-finding rate",
            "Share of the unemployed who leave unemployment within a month. When it falls, claims last longer; it is "
            "the most direct public measure of how fast people get back to work.",
            "Source: BLS Current Population Survey via FRED (UNEMPLOY, UEMPLT5), our calculation: 1 − (unemployed next "
            "month − newly unemployed next month) ÷ unemployed this month; 3-month average, percent. Leaving "
            "unemployment includes leaving the labour force. Vertical line at January 1994: survey redesign; levels "
            "before and after are not strictly comparable. Gap: no October 2025 survey.",
            fl["job_finding_rate_3m"], "Job-finding rate, 3-month average", "Percent of unemployed", "%{y:.1f}%",
            "job_finding_rate_3m_pct")
        fig = go.Figure(jf["figure"])
        add_marker(fig, "1994-01-01", "Survey redesign (1994)")
        jf["figure"] = json.loads(fig.to_json())
        charts.append(jf)
        charts.append(line_chart(
            "vacancies-per-unemployed", "Job openings per unemployed person",
            "Fewer openings per job seeker means longer searches.",
            "Source: BLS JOLTS and Current Population Survey via FRED (JTSJOL, UNEMPLOY), our calculation; from Dec 2000.",
            fl["vacancies_per_unemployed"].loc["2000-12-01":], "Job openings per unemployed person",
            "Openings per unemployed", "%{y:.2f}", "openings_per_unemployed"))

    # 7. JOLTS hires rate
    charts.append(line_chart(
        "jolts-hires", "JOLTS hires rate",
        "Hiring as a share of all jobs; see the job-finding rate above for the unemployed specifically.",
        "Source: BLS Job Openings and Labor Turnover Survey via FRED (JTSHIR). Hires as a percent of total "
        "employment, seasonally adjusted, monthly; JOLTS starts Dec 2000.",
        fred("JTSHIR"), "Hires rate", "Percent of employment", "%{y:.1f}%", "hires_rate_pct"))

    return {"intro": INTRO, "charts": charts, "watch": watch_card(live)}
