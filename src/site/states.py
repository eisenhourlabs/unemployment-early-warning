"""
States page (Phase 4 stage 4b): how claims and unemployment differ across states.
Called by build_site.py.

What this module makes:
  - three chart cards drawn by site.js like on every other page:
      1. breadth: the diffusion index (share of covered jobs in states with new claims up 20%+ vs. a year earlier)
      2. and 3. weighted vs. national (shown only in the "Weighted" view; charted, never offered for download)
  - states_payload(): the per-state history behind the map, the four tiles and the state table, written to
    site/assets/states.json. The map, tiles and table follow the time control's END date (the last week or month at
    or before it), so the browser needs every week, not just the latest one. states.js reads this file.

Public-wording rules (CLAUDE.md, decision O1): the page says "Weighted", never "footprint" or "employer", and shows
no weights, ranks of weights or a count of weighted states. The map and table are the same in both views, so the page
never marks which states carry weight. The browser check tests this.

All inputs come from src/transforms/state_measures.py (data/processed/states/).
"""

import json
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go

from common import (ACCENT, GREYS, PROCESSED, ROOT, add_recession_shading, add_zero_line, base_layout, card,
                    dates, fmt_date, plain)

STATES = PROCESSED / "states"
THRESHOLD = 20          # % rise in 4-week average initial claims vs. a year earlier (fixed in the Phase 4 brief)
GAP_THRESHOLD = 0.5     # points above the state's own 12-month low (tile 4)

INTRO = ("How claims and unemployment differ across states: new claims (how many people are losing jobs) and "
         "continuing claims, exhaustion and duration (how long it lasts). The map, tiles and table show the last week "
         "or month at or before the end of the time setting.")
WEIGHTED_SENTENCE = ("Weighted view: each state counts in proportion to a fixed set of regional weights this site "
                     "uses for its own monitoring.")
NSA_NOTE = ("Year-on-year on unadjusted data: states' seasonal patterns differ and DOL publishes no state seasonal "
            "factors, so each week is compared with the same weeks a year earlier.")
NO_DOWNLOAD = "Not offered for download (the weighted figures are charted only)."

# The map's measures. kind: "diverging" (change, colours centred on 0) or "sequential" (a level).
# freq "w" reads the weekly arrays, "m" the monthly ones. decimals / unit format the tooltip and table.
MAP_MEASURES = [
    {"key": "icy", "label": "New claims vs. a year ago", "freq": "w", "kind": "diverging", "decimals": 0,
     "unit": "%", "signed": True,
     "footer": "State UI initial claims (regular state programs), 4-week average, % change vs. the same 4 weeks a year "
               "earlier. " + NSA_NOTE},
    {"key": "cc", "label": "Continuing claims rate", "freq": "w", "kind": "sequential", "decimals": 2, "unit": "%",
     "footer": "Continued weeks claimed (regular state UI) as a % of covered jobs, 4-week average, not seasonally "
               "adjusted; dated by the week of unemployment, so it runs a week behind new claims."},
    {"key": "ur", "label": "Unemployment rate", "freq": "m", "kind": "sequential", "decimals": 1, "unit": "%",
     "footer": "BLS Local Area Unemployment Statistics via FRED ({ST}UR), seasonally adjusted, monthly."},
    {"key": "gap", "label": "Unemployment rate vs. 12-month low", "freq": "m", "kind": "sequential", "decimals": 1,
     "unit": " pt", "signed": True,
     "footer": "State unemployment rate minus its lowest value over the last 12 months (this month included), in "
               "percentage points: a state version of the Sahm-style gap. No warning trigger is attached."},
    {"key": "exh", "label": "Exhaustion rate (12-month)", "freq": "m", "kind": "sequential", "decimals": 1, "unit": "%",
     "footer": "Share of claimants who use up all their state benefits: 12-month average final payments ÷ 12-month "
               "average first payments 6 months earlier (DOL ETA 5159, our calculation)."},
]


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
    footer = (f"Share of covered jobs in the states and DC whose state UI initial claims (4-week average) are up "
              f"{THRESHOLD}% or more on the same weeks a year earlier. Each state counts by its covered employment; "
              f"the download also has the simple share of states. The {THRESHOLD}% threshold was fixed before any "
              f"testing. {NSA_NOTE} Source: DOL ETA 539 (ar539), our calculation. Weekly from Jan 1996. "
              f"Grey bands: NBER recessions. Last data: {fmt_date(last.week_ended)}.")
    rows = [[x, ce, un] for x, ce, un in zip(dates(d.week_ended), plain(d.diffusion_ce_weighted_pct),
                                              plain(d.diffusion_unweighted_pct))]
    c = card("diffusion", f"Breadth: share of jobs in states with new claims up {THRESHOLD}%+",
             "How widespread rising layoffs are: a few states, or many at once.",
             footer, fig, ["week_ended", "diffusion_ce_weighted_pct", "diffusion_unweighted_pct"], rows,
             wide=True, zero=True)
    c["notes"] = []
    return c


def weighted_chart(id, title, why, footer, wtd: pd.DataFrame, nat_col, wtd_col, y_title, hover, zero) -> dict:
    """Weighted vs. national on the same basis. Charted only: never offered for download (decision O1 / brief)."""
    d = wtd.dropna(subset=[nat_col, wtd_col])
    d = d[d.week_ended >= "1996-01-01"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates(d.week_ended), y=plain(d[wtd_col]), mode="lines", name="Weighted",
                             line=dict(color=ACCENT, width=2), meta={"role": "main"},
                             hovertemplate=f"{hover}<extra>Weighted</extra>"))
    fig.add_trace(go.Scatter(x=dates(d.week_ended), y=plain(d[nat_col]), mode="lines", name="National",
                             line=dict(color=GREYS[0], width=1.5), meta={"role": "grey0"},
                             hovertemplate=f"{hover}<extra>National</extra>"))
    if zero:
        add_zero_line(fig)
    add_recession_shading(fig, d.week_ended.iloc[0])
    base_layout(fig, y_title, "Week ending %b %-d, %Y")
    footer += (f" {WEIGHTED_SENTENCE} National: all states on the same basis. Grey bands: NBER recessions. "
               f"Last data: {fmt_date(d.week_ended.iloc[-1])}.")
    rows = [[x, a, b] for x, a, b in zip(dates(d.week_ended), plain(d[wtd_col]), plain(d[nat_col]))]
    c = card(id, title, why, footer, fig, ["week_ended", "weighted", "national"], rows, zero=zero,
             downloadable=False)
    c["no_download_note"] = NO_DOWNLOAD
    return c


# ===========================================================================
# Map / tile / table data (site/assets/states.json)
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
    """Everything states.js needs, one array per measure and area, aligned with the 'weeks' / 'months' lists."""
    a = areas()
    codes = a.state.tolist()
    weekly = read("state_weekly.csv", "week_ended")
    monthly = pd.read_csv(STATES / "state_monthly.csv", dtype={"month": str})
    diff = read("diffusion_weekly.csv", "week_ended")
    wtd = read("weighted_weekly.csv", "week_ended")

    weeks = pd.DatetimeIndex(sorted(weekly.week_ended.unique()))
    months = sorted(monthly.month.unique())

    def per_area(df, key, index, col, decimals):
        wide_ = df.pivot(index=key, columns="state", values=col).reindex(index=index, columns=codes)
        return [rounded(wide_[c].values, decimals) for c in codes]

    w = {"ic": per_area(weekly, "week_ended", weeks, "initial_claims", 0),
         "ic4": per_area(weekly, "week_ended", weeks, "initial_claims_4wk", 0),
         "icy": per_area(weekly, "week_ended", weeks, "ic_yoy_pct", 1),
         "cc": per_area(weekly, "week_ended", weeks, "cc_rate_4wk", 3),
         "ccy": per_area(weekly, "week_ended", weeks, "cc_rate_yoy_pp", 3)}
    m = {"ur": per_area(monthly, "month", months, "unemployment_rate", 1),
         "gap": per_area(monthly, "month", months, "ur_above_12m_low_pp", 1),
         "exh": per_area(monthly, "month", months, "exhaustion_rate_12m", 1),
         "dur": per_area(monthly, "month", months, "avg_duration_12m", 1)}

    dd = diff.set_index("week_ended").reindex(weeks)
    ww = wtd.set_index("week_ended").reindex(weeks)
    totals = {
        # national comparison (all states, NSA, same basis) and the diffusion index (download files)
        "nat_icy": rounded(ww.national_ic_yoy_pct, 1), "nat_cc": rounded(ww.national_cc_rate_4wk, 3),
        "nat_ccy": rounded(ww.national_cc_rate_yoy_pp, 3),
        "diff": rounded(dd.diffusion_ce_weighted_pct, 1), "n_up": rounded(dd.areas_up, 0),
        # the Weighted view (charted only, never a download)
        "w_icy": rounded(ww.weighted_ic_yoy_pct, 1), "w_cc": rounded(ww.weighted_cc_rate_4wk, 3),
        "w_ccy": rounded(ww.weighted_cc_rate_yoy_pp, 3), "w_diff": rounded(ww.weighted_diffusion_pct, 1),
    }
    return {
        "areas": [{"code": r.state, "name": r.state_name, "map": r.area_type in ("state", "dc")}
                  for r in a.itertuples()],
        "weeks": [d.strftime("%Y-%m-%d") for d in weeks],
        "months": months,
        "w": w, "m": m, "t": totals,
        "measures": MAP_MEASURES,
        "threshold": THRESHOLD, "gapThreshold": GAP_THRESHOLD,
    }


def write_payload(out_dir) -> int:
    """Write site/assets/states.json; returns its size in KB."""
    path = out_dir / "states.json"
    path.write_text(json.dumps(states_payload(), separators=(",", ":"), allow_nan=False), encoding="utf-8")
    return round(path.stat().st_size / 1024)


# ===========================================================================
# Page
# ===========================================================================
def build(built: datetime) -> dict:
    diff = read("diffusion_weekly.csv", "week_ended")
    wtd = read("weighted_weekly.csv", "week_ended")
    breadth = diffusion_chart(diff, wtd)
    weighted = [
        weighted_chart("weighted-ic", "New claims vs. a year ago: weighted vs. national",
                       "Whether new job losses are rising faster or slower where the weights sit.",
                       "State UI initial claims rate (claims ÷ covered jobs), 4-week average, % change vs. the same "
                       "weeks a year earlier, not seasonally adjusted. Source: DOL ETA 539 (ar539), our calculation.",
                       wtd, "national_ic_yoy_pct", "weighted_ic_yoy_pct", "Percent change vs. a year ago",
                       "%{y:+.1f}%", zero=True),
        weighted_chart("weighted-cc", "Continuing claims rate: weighted vs. national",
                       "Whether unemployment spells are lasting longer where the weights sit.",
                       "Continued weeks claimed (regular state UI) as a % of covered jobs, 4-week average, not "
                       "seasonally adjusted. Source: DOL ETA 539 (ar539), our calculation.",
                       wtd, "national_cc_rate_4wk", "weighted_cc_rate_4wk", "Percent of covered jobs",
                       "%{y:.2f}%", zero=False),
    ]
    return {"intro": INTRO, "weighted_sentence": WEIGHTED_SENTENCE, "nsa_note": NSA_NOTE,
            "breadth": breadth, "weighted_charts": weighted, "charts": [breadth] + weighted,
            "measures": MAP_MEASURES, "threshold": THRESHOLD, "gap_threshold": GAP_THRESHOLD}
