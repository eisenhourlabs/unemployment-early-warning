"""
States page (Phase 4 stage 4b; Phase 4 review Gates 2 and 3): how claims and unemployment differ across states.
Called by build_site.py.

What this module makes:
  - chart cards drawn by site.js like on every other page:
      breadth (diffusion index); in the Weighted view: new claims and continuing claims rates, the unemployment rate
      and its gap to the 12-month low, each weighted vs. national (downloadable since the review, Gate 3 item 6)
  - states_payload(): the per-state history behind the map, tiles, table, "rising states" list, top-contributors
    table and state drill-down, written to site/assets/states.json (read by static/states.js). They follow the time
    control's END date.

One basis (review Gate 2): every "vs. a year ago" figure compares the claims RATE (claims per covered job, regular
state UI, 4-week average, not seasonally adjusted) with the same weeks a year earlier, for each state, National (the
sum of the states and DC) and Weighted alike. The unemployment flag is the state Sahm convention: 3-month average of
the state rate minus its lowest 3-month average of the previous 12 months.

Public-wording rules (CLAUDE.md, decision O1): "Weighted", never "footprint" or "employer"; no weights, ranks of weights
or a count of weighted states. The browser check tests this.
"""

import json
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from common import (ACCENT, DOL, GREYS, PROCESSED, ROOT, add_recession_shading, add_zero_line, base_layout, card,
                    dates, fmt_date, plain)

STATES = PROCESSED / "states"
THRESHOLD = 20          # % rise in the 4-week claims rate vs. a year earlier (diffusion; fixed in the Phase 4 brief)
GAP_THRESHOLD = 0.5     # points: state Sahm-style gap (review Gate 2)
NORMAL_THRESHOLD = 20   # % above normal for 3 straight weeks: "rising states" list (review Gate 3)
SHUTDOWN_WEEKS = ("2025-09-27", "2025-11-22")   # weeks the 2025 shutdown touched (no DOL release; backlog after)

INTRO = ("How claims and unemployment differ across states: new claims (how many people are losing jobs) and "
         "continuing claims, exhaustion and duration (how long it lasts). The map, tiles and table show the last week "
         "or month at or before the end of the time setting.")
WEIGHTED_SENTENCE = ("Weighted view: each state counts in proportion to a fixed set of regional weights this site "
                     "uses for its own monitoring.")
BASIS = ("All year-on-year figures on this page compare the same thing: the claims rate (claims per 100 covered jobs, "
         "regular state UI, 4-week average, not seasonally adjusted) with the same weeks a year earlier, for each "
         "state, for National (the sum of the states and DC) and for Weighted.")
NSA_NOTE = ("Year-on-year on unadjusted data: states' seasonal patterns differ and DOL publishes no state seasonal "
            "factors, so each week is compared with the same weeks a year earlier.")
SEVERITY_NOTE = ("Continuing-claims levels are not comparable across states: state benefit limits range from about 12 "
                 "to 26 weeks, so in short-limit states UI claims end before unemployment does, and their continuing "
                 "claims rates look low.")

# The map's measures. kind: "diverging" (a change, colours centred on 0) or "sequential" (a level).
MAP_MEASURES = [
    {"key": "icy", "label": "New claims vs. a year ago", "freq": "w", "kind": "diverging", "decimals": 0,
     "unit": "%", "signed": True,
     "footer": "Initial claims rate (regular state UI, per covered job), 4-week average, % change vs. the same 4 weeks "
               "a year earlier. " + NSA_NOTE},
    {"key": "icn", "label": "New claims vs. normal", "freq": "w", "kind": "diverging", "decimals": 0, "unit": "%",
     "signed": True,
     "footer": "Initial claims rate, 4-week average, vs. 'normal': the median of the same weeks in the prior 3 years "
               "(weeks from March 2020 to June 2021 left out). Less sensitive than the year-ago comparison to one "
               "unusual year."},
    {"key": "cc", "label": "Continuing claims rate", "freq": "w", "kind": "sequential", "decimals": 2, "unit": "%",
     "footer": "Continued weeks claimed (regular state UI) as a % of covered jobs, 4-week average, not seasonally "
               "adjusted; dated by the week of unemployment, so it runs a week behind new claims. " + SEVERITY_NOTE},
    {"key": "ur", "label": "Unemployment rate", "freq": "m", "kind": "sequential", "decimals": 1, "unit": "%",
     "footer": "BLS Local Area Unemployment Statistics via FRED ({ST}UR), seasonally adjusted, monthly."},
    {"key": "gap", "label": "Unemployment vs. 12-month low (Sahm-style)", "freq": "m", "kind": "sequential",
     "decimals": 1, "unit": " pt", "signed": True,
     "footer": "3-month average of the state unemployment rate minus its lowest 3-month average of the previous 12 "
               "months, in percentage points: the Sahm rule applied to a state. No confirmation trigger is attached."},
    {"key": "exh", "label": "Exhaustion rate (12-month)", "freq": "m", "kind": "sequential", "decimals": 1, "unit": "%",
     "footer": "Share of claimants who use up all their state benefits: 12-month average final payments ÷ 12-month "
               "average first payments 6 months earlier (DOL ETA 5159, our calculation)."},
]


# Review WP9 C14: the map's colour scale is fixed for each measure (it used to rescale to the states shown at each
# date, so the same colour meant different values at different dates). Range: the 5th to 95th percentile of every
# state's values over the whole history, leaving out March 2020 to December 2021 (pandemic claims would otherwise
# stretch the scale until today's map is nearly one colour); diverging measures are centred on 0.
RANGE_SKIP = ("2020-03", "2021-12")


def colour_range(values, kind: str) -> tuple[float, float]:
    """(zmin, zmax) for a map measure from all its values (None / NaN ignored)."""
    v = np.array([x for x in values if x is not None and x == x], dtype=float)
    q05, q95 = np.quantile(v, [0.05, 0.95])
    if kind == "diverging":
        lim = max(abs(q05), abs(q95)) or 1.0
        return -round(float(lim), 2), round(float(lim), 2)
    return round(float(q05), 2), round(float(max(q95, q05 + 1e-6)), 2)


def map_ranges(payload: dict) -> list[dict]:
    """MAP_MEASURES with each measure's fixed colour range (zmin, zmax) added; states and DC only."""
    on_map = [i for i, ar in enumerate(payload["areas"]) if ar["map"]]
    out = []
    for m in MAP_MEASURES:
        periods = payload["weeks"] if m["freq"] == "w" else payload["months"]
        keep = [k for k, d in enumerate(periods) if not (RANGE_SKIP[0] <= d[:7] <= RANGE_SKIP[1])]
        arrs = payload[m["freq"]][m["key"]]
        zmin, zmax = colour_range([arrs[i][k] for i in on_map for k in keep], m["kind"])
        out.append({**m, "zmin": zmin, "zmax": zmax})
    return out


def read(name: str, date_col: str) -> pd.DataFrame:
    return pd.read_csv(STATES / name, parse_dates=[date_col])


def areas() -> pd.DataFrame:
    return pd.read_csv(ROOT / "config" / "states.csv", comment="#", dtype=str)


# ===========================================================================
# Charts (site.js draws these like every other chart card)
# ===========================================================================
def diffusion_chart(diff: pd.DataFrame, wtd: pd.DataFrame) -> dict:
    """Breadth: CE-weighted diffusion index (solid); the weighted version (dashed) appears only in the Weighted view."""
    d = diff.dropna(subset=["diffusion_ce_weighted_pct"])
    w = wtd.set_index("week_ended").weighted_diffusion_pct.reindex(d.week_ended)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates(d.week_ended), y=plain(d.diffusion_ce_weighted_pct), mode="lines",
                             name="All states (covered-jobs weighted)", line=dict(color=ACCENT, width=2),
                             meta={"role": "main"}, hovertemplate="%{y:.1f}% of covered jobs<extra>All states</extra>"))
    # meta.view: site.js shows this line only while the page is in that view
    fig.add_trace(go.Scatter(x=dates(d.week_ended), y=plain(w.values), mode="lines", name="Weighted",
                             line=dict(color=ACCENT, width=2, dash="dash"), visible=False,
                             meta={"role": "main", "view": "weighted"},
                             hovertemplate="%{y:.1f}%<extra>Weighted</extra>"))
    add_zero_line(fig)
    add_recession_shading(fig, d.week_ended.iloc[0])
    base_layout(fig, "Percent of covered jobs", "Week ending %b %-d, %Y")
    last = d.iloc[-1]
    footer = (f"Share of covered jobs in the states and DC whose initial claims rate (4-week average) is up "
              f"{THRESHOLD}% or more on the same weeks a year earlier. Each state counts by its covered employment; "
              f"the download also has the simple share of states. The {THRESHOLD}% threshold was fixed before any "
              f"testing; added to the early-warning score it did not improve it (tested 2026). {NSA_NOTE} Source: DOL "
              f"ETA 539 (ar539), our calculation. Weekly from Jan 1996. Grey bands: NBER recessions. "
              f"Last data: {fmt_date(last.week_ended)}.")
    rows = [[x, ce, un] for x, ce, un in zip(dates(d.week_ended), plain(d.diffusion_ce_weighted_pct),
                                              plain(d.diffusion_unweighted_pct))]
    return card("diffusion", f"Breadth: share of jobs in states with new claims up {THRESHOLD}%+",
                "How widespread rising layoffs are: a few states, or many at once.",
                footer, fig, ["week_ended", "diffusion_ce_weighted_pct", "diffusion_unweighted_pct"], rows,
                wide=True, zero=True)


def weighted_chart(id, title, why, footer, df: pd.DataFrame, date_col, nat_col, wtd_col, y_title, hover, zero,
                   monthly=False, start="1996-01-01") -> dict:
    """Weighted vs. national on the same basis (Weighted view only; downloadable since review Gate 3 item 6)."""
    d = df.dropna(subset=[nat_col, wtd_col])
    d = d[d[date_col] >= start].copy()
    # 3 decimals are plenty for a chart, and a 3-decimal value can never print like a 6-decimal weight (the browser
    # check looks for the exact weights anywhere on the page; a 6-decimal gap once matched one by chance)
    d[[nat_col, wtd_col]] = d[[nat_col, wtd_col]].round(3)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates(d[date_col]), y=plain(d[wtd_col]), mode="lines", name="Weighted",
                             line=dict(color=ACCENT, width=2), meta={"role": "main"},
                             hovertemplate=f"{hover}<extra>Weighted</extra>"))
    fig.add_trace(go.Scatter(x=dates(d[date_col]), y=plain(d[nat_col]), mode="lines", name="National",
                             line=dict(color=GREYS[0], width=1.5), meta={"role": "grey0"},
                             hovertemplate=f"{hover}<extra>National</extra>"))
    if zero:
        add_zero_line(fig)
    add_recession_shading(fig, d[date_col].iloc[0])
    base_layout(fig, y_title, "%b %Y" if monthly else "Week ending %b %-d, %Y")
    last = d[date_col].iloc[-1]
    footer += (f" {WEIGHTED_SENTENCE} Grey bands: NBER recessions. Last data: "
               f"{last:%b %Y}." if monthly else f" {WEIGHTED_SENTENCE} Grey bands: NBER recessions. "
               f"Last data: {fmt_date(last)}.")
    rows = [[x, a, b] for x, a, b in zip(dates(d[date_col]), plain(d[wtd_col]), plain(d[nat_col]))]
    return card(id, title, why, footer, fig, [date_col, "weighted", "national"], rows, zero=zero)


def short_limit_note(w: pd.Series) -> str:
    """Review Gate 3 item 5: why the weighted continuing-claims rate runs low, with the numbers (ETA 218)."""
    b = pd.read_csv(DOL / "benefit_duration_quarterly.csv")
    q = b[b.quarter_ended == b[b.state != "US"].groupby("quarter_ended").state.count().idxmax()]   # fullest quarter
    q = q.groupby("state").potential_avg_weeks.last()
    pw = q.reindex(w.index)
    weighted = (pw * w).sum() / w[pw.notna()].sum()
    short = pw[pw < 20].index
    return (f"The weighted rate is held down by short benefit limits in heavily weighted states: new claimants there "
            f"are entitled to {weighted:.1f} weeks on average, against {q.get('US', np.nan):.1f} nationally, and "
            f"{w[short].sum() * 100:.0f}% of the weight sits in states with fewer than 20 entitled weeks (DOL ETA 218).")


# ===========================================================================
# Map / tile / table / drill-down data (site/assets/states.json)
# ===========================================================================
def rounded(values, decimals: int) -> list:
    """Plain list for JSON, rounded to keep the file small; None for blanks."""
    out = []
    for v in values:
        if pd.isna(v):
            out.append(None)
        elif decimals == 0:
            out.append(int(round(float(v))))
        else:
            out.append(round(float(v), decimals))
    return out


def states_payload() -> dict:
    """Everything states.js needs, one array per measure and area, aligned with 'weeks' / 'months' / 'quarters'."""
    a = areas()
    codes = a.state.tolist()
    weekly = read("state_weekly.csv", "week_ended")
    monthly = pd.read_csv(STATES / "state_monthly.csv", dtype={"month": str})
    diff = read("diffusion_weekly.csv", "week_ended")
    wtd = read("weighted_weekly.csv", "week_ended")
    contrib = read("weighted_contributions_weekly.csv", "week_ended")
    ar218 = pd.read_csv(DOL / "benefit_duration_quarterly.csv", dtype={"quarter_ended": str})
    ar218 = ar218[ar218.state.isin(codes)]

    weeks = pd.DatetimeIndex(sorted(weekly.week_ended.unique()))
    months = sorted(monthly.month.unique())
    quarters = sorted(ar218.quarter_ended.unique())

    def per_area(df, key, index, col, decimals):
        wide_ = df.pivot(index=key, columns="state", values=col).reindex(index=index, columns=codes)
        return [rounded(wide_[c].values, decimals) for c in codes]

    w = {"ic": per_area(weekly, "week_ended", weeks, "initial_claims", 0),
         "ic4": per_area(weekly, "week_ended", weeks, "initial_claims_4wk", 0),
         "icy": per_area(weekly, "week_ended", weeks, "ic_yoy_pct", 1),
         "icn": per_area(weekly, "week_ended", weeks, "ic_vs_normal_pct", 1),
         "cc": per_area(weekly, "week_ended", weeks, "cc_rate_4wk", 3),
         "ccy": per_area(weekly, "week_ended", weeks, "cc_rate_yoy_pp", 3)}
    # contributions to the weighted change (weighted states only; other areas stay blank)
    w["wc"] = per_area(contrib, "week_ended", weeks, "contribution_pct", 2)
    m = {"ur": per_area(monthly, "month", months, "unemployment_rate", 1),
         "ur3": per_area(monthly, "month", months, "ur_3m_avg", 2),
         "urlow": per_area(monthly, "month", months, "ur_3m_avg_12m_low", 2),
         "gap": per_area(monthly, "month", months, "ur_gap_pp", 2),
         "exh": per_area(monthly, "month", months, "exhaustion_rate_12m", 1),
         "exhc": per_area(monthly, "month", months, "exhaustion_change_12m_pp", 1),
         "dur": per_area(monthly, "month", months, "avg_duration_12m", 1)}
    q = {"pot": per_area(ar218, "quarter_ended", quarters, "potential_avg_weeks", 1)}

    dd = diff.set_index("week_ended").reindex(weeks)
    ww = wtd.set_index("week_ended").reindex(weeks)
    totals = {
        "nat_icy": rounded(ww.national_ic_yoy_pct, 1), "nat_cc": rounded(ww.national_cc_rate_4wk, 3),
        "nat_ccy": rounded(ww.national_cc_rate_yoy_pp, 3),
        "diff": rounded(dd.diffusion_ce_weighted_pct, 1), "n_up": rounded(dd.areas_up, 0),
        "w_icy": rounded(ww.weighted_ic_yoy_pct, 1), "w_cc": rounded(ww.weighted_cc_rate_4wk, 3),
        "w_ccy": rounded(ww.weighted_cc_rate_yoy_pp, 3), "w_diff": rounded(ww.weighted_diffusion_pct, 1),
    }
    payload = {
        "areas": [{"code": r.state, "name": r.state_name, "map": r.area_type in ("state", "dc")}
                  for r in a.itertuples()],
        "weeks": [d.strftime("%Y-%m-%d") for d in weeks],
        "months": months, "quarters": quarters,
        "w": w, "m": m, "q": q, "t": totals,
        "measures": MAP_MEASURES,
        "threshold": THRESHOLD, "gapThreshold": GAP_THRESHOLD, "normalThreshold": NORMAL_THRESHOLD,
        "shutdownWeeks": list(SHUTDOWN_WEEKS),
    }
    payload["measures"] = map_ranges(payload)
    return payload


def write_payload(out_dir) -> int:
    """Write site/assets/states.json; returns its size in KB."""
    path = out_dir / "states.json"
    path.write_text(json.dumps(states_payload(), separators=(",", ":"), allow_nan=False), encoding="utf-8")
    return round(path.stat().st_size / 1024)


# ===========================================================================
# Page
# ===========================================================================
def build(built: datetime) -> dict:
    import sys
    sys.path.insert(0, str(ROOT / "src" / "transforms"))
    import state_measures as sm
    diff = read("diffusion_weekly.csv", "week_ended")
    wtd = read("weighted_weekly.csv", "week_ended")
    wmon = pd.read_csv(STATES / "weighted_monthly.csv")
    wmon["month"] = pd.to_datetime(wmon.month + "-01")
    breadth = diffusion_chart(diff, wtd)
    cc = weighted_chart("weighted-cc", "Continuing claims rate: weighted vs. national",
                        "Whether unemployment spells are lasting longer where the weights sit.",
                        "Continued weeks claimed (regular state UI) as a % of covered jobs, 4-week average, not "
                        "seasonally adjusted; National = the sum of the states and DC. Source: DOL ETA 539 (ar539), "
                        "our calculation.", wtd, "week_ended", "national_cc_rate_4wk", "weighted_cc_rate_4wk",
                        "Percent of covered jobs", "%{y:.2f}%", zero=False)
    cc["notes"] = [short_limit_note(sm.weights())]
    weighted = [
        weighted_chart("weighted-ic", "New claims vs. a year ago: weighted vs. national",
                       "Whether new job losses are rising faster or slower where the weights sit.",
                       "Initial claims rate (regular state UI, claims per covered job), 4-week average, % change vs. "
                       "the same weeks a year earlier, not seasonally adjusted; National = the sum of the states and "
                       "DC. Source: DOL ETA 539 (ar539), our calculation.",
                       wtd, "week_ended", "national_ic_yoy_pct", "weighted_ic_yoy_pct", "Percent change vs. a year ago",
                       "%{y:+.1f}%", zero=True),
        cc,
        weighted_chart("weighted-ur", "Unemployment rate: weighted vs. national",
                       "Where the weights sit, is unemployment higher or lower than in the country as a whole?",
                       "Weighted average of the state unemployment rates (BLS LAUS via FRED, seasonally adjusted) vs. "
                       "the national rate (UNRATE). Monthly.",
                       wmon, "month", "national_ur", "weighted_ur", "Percent", "%{y:.1f}%", zero=False, monthly=True),
        weighted_chart("weighted-ur-gap", "Unemployment vs. 12-month low (Sahm-style): weighted vs. national",
                       "A rise of 0.5 point or more has marked the start of past recessions nationally.",
                       "3-month average of the unemployment rate minus its lowest 3-month average of the previous 12 "
                       "months, in points (the Sahm rule), for the weighted rate and the national rate. Monthly.",
                       wmon, "month", "national_ur_gap_pp", "weighted_ur_gap_pp", "Percentage points", "%{y:+.2f}",
                       zero=True, monthly=True),
    ]
    return {"intro": INTRO, "weighted_sentence": WEIGHTED_SENTENCE, "basis": BASIS, "severity_note": SEVERITY_NOTE,
            "breadth": breadth, "weighted_charts": weighted, "charts": [breadth] + weighted,
            "measures": MAP_MEASURES, "threshold": THRESHOLD, "gap_threshold": GAP_THRESHOLD,
            "normal_threshold": NORMAL_THRESHOLD}
