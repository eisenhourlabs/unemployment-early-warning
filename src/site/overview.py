"""
Overview page ("Where are we this week?"): five tiles, "What changed this week", and three charts.
Called by build_site.py.
"""

import json
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go

from common import (ACCENT, claims_weekly, fmt_change, fmt_claims, fmt_date, fmt_month, fred, fred_metadata,
                    is_preliminary, last_time_as_extreme, line_chart, ordinal, percentile_text, plain,
                    prelim_label, streak, value_on_or_before, vs_month, weekly_claims_chart)

# How far back a value must last have been matched before a sentence says "the highest since ..."
HIGHEST_SINCE_MIN_WEEKS = 13
# Monthly news (unemployment rate, Sahm) only appears in "What changed" if FRED updated it this recently.
MONTHLY_NEWS_DAYS = 7


# ===========================================================================
# Charts
# ===========================================================================
def unemployment_chart(forecast: pd.DataFrame | None = None) -> dict:
    """Unemployment rate with recession shading.

    forecast (Phase 3): a DataFrame indexed by date with columns lo90, lo50, median, hi50, hi90 (percent).
    When given, a fan (shaded 90% and 50% intervals plus a dashed median) is drawn after the last actual
    month. Left as None in Phase 2.
    """
    c = line_chart(
        "unemployment-rate", "Unemployment rate",
        "The headline measure everyone knows; it lags claims but sets the overall picture.",
        "Source: BLS via FRED (UNRATE). Percent of the labor force, seasonally adjusted, monthly. "
        "Gap: no October 2025 survey (government shutdown).",
        fred("UNRATE"), "Unemployment rate", "Percent of labor force", "%{y:.1f}%", "unemployment_rate_pct",
        wide=True)
    if forecast is not None:
        fig = go.Figure(c["figure"])
        x = [d.strftime("%Y-%m-%d") for d in forecast.index]
        for lo, hi, label, alpha in [("lo90", "hi90", "90% interval", 0.15), ("lo50", "hi50", "50% interval", 0.30)]:
            fig.add_trace(go.Scatter(x=x, y=plain(forecast[hi]), mode="lines", line=dict(width=0),
                                     showlegend=False, hoverinfo="skip", meta={"role": "fan-edge"}))
            fig.add_trace(go.Scatter(x=x, y=plain(forecast[lo]), mode="lines", line=dict(width=0), fill="tonexty",
                                     fillcolor=f"rgba(42, 120, 214, {alpha})", name=f"Forecast {label}",
                                     meta={"role": "fan", "alpha": alpha}, hovertemplate="%{y:.1f}%<extra></extra>"))
        fig.add_trace(go.Scatter(x=x, y=plain(forecast["median"]), name="Forecast median", mode="lines",
                                 line=dict(color=ACCENT, width=2, dash="dash"), meta={"role": "main"},
                                 hovertemplate="%{y:.1f}%<extra></extra>"))
        fig.update_layout(showlegend=True)
        c["figure"] = json.loads(fig.to_json())
    return c


def ic_rate_chart(claims: pd.DataFrame, wide=False) -> dict:
    return weekly_claims_chart(
        "ic-rate", "SA initial claims rate", "New job losses: drives how often IUI claims start (frequency).",
        "Source: DOL weekly claims (ETA 539 and news release; FRED ICSA for preliminary weeks). "
        "Seasonally adjusted initial claims per 10,000 covered workers, weekly.",
        claims, "ic_rate_sa_per10k", "ic_rate_sa_4wk_per10k", "source_initial",
        "Per 10,000 covered workers", "%{y:.1f}",
        ["week_ended", "ic_rate_sa_per_10k", "ic_rate_sa_4wk_per_10k", "source"], wide=wide)


def cc_rate_chart(claims: pd.DataFrame, wide=False) -> dict:
    return weekly_claims_chart(
        "cc-rate", "SA continuing claims rate",
        "How long people stay on benefits: drives how long IUI claims last (severity).",
        "Source: DOL weekly claims (ETA 539 and news release; FRED CCSA for preliminary weeks). "
        "Seasonally adjusted continued claims as a percent of covered workers, weekly; "
        "matches DOL's insured unemployment rate.",
        claims, "cc_rate_sa", "cc_rate_sa_4wk", "source_continued",
        "Percent of covered workers", "%{y:.1f}%",
        ["week_ended", "cc_rate_sa_pct", "cc_rate_sa_4wk_pct", "source"], wide=wide)


# ===========================================================================
# Tiles: latest value, changes, percentile on full history
# ===========================================================================
def weekly_tile(name, s: pd.Series, decimals, unit, change_unit, since_label, note="") -> dict:
    """Tile for a weekly series: change vs. last week and vs. the same week a year ago."""
    latest_date, latest = s.index[-1], s.iloc[-1]
    year_date, year_val = value_on_or_before(s, latest_date - timedelta(days=364))
    fmt = (lambda v: fmt_claims(v)) if decimals == 0 else (lambda v: f"{v:.{decimals}f}")
    return {
        "name": name,
        "value": fmt(latest) + unit,
        "as_of": f"Week ending {fmt_date(latest_date)}" + (f" · {note}" if note else ""),
        "changes": [f"{fmt_change(latest - s.iloc[-2], decimals, change_unit)} vs. prior week",
                    f"{fmt_change(latest - year_val, decimals, change_unit)} vs. a year ago"],
        "percentile": percentile_text(s, latest, since_label),
    }


def build_tiles(claims: pd.DataFrame) -> list[dict]:
    tiles = []

    # 1. Unemployment rate (monthly, from 1948)
    ur = fred("UNRATE")
    latest_date, latest = ur.index[-1], ur.iloc[-1]
    # A survey month can be missing (no October 2025 survey: government shutdown); the tile says so.
    prev, prev_label = vs_month(ur, latest_date - pd.DateOffset(months=1), "not collected")
    yr, yr_label = vs_month(ur, latest_date - pd.DateOffset(years=1), "not collected")
    tiles.append({
        "name": "Unemployment rate",
        "value": f"{latest:.1f}%",
        "as_of": fmt_month(latest_date),
        "changes": [f"{fmt_change(latest - prev, 1, ' pt')} vs. {prev_label}",
                    f"{fmt_change(latest - yr, 1, ' pt')} vs. {yr_label}"],
        "percentile": percentile_text(ur, latest, ur.index[0].year),
    })

    # 2. SA initial claims, 4-week average (FRED IC4WSA, from 1967)
    ic4 = fred("IC4WSA")
    src = claims.set_index("week_ended")["source_initial"].get(ic4.index[-1], "")
    tiles.append(weekly_tile("SA initial claims, 4-week average", ic4, 0, "", "", ic4.index[0].year,
                             prelim_label(src) if is_preliminary(src) else ""))

    # 3. SA initial claims rate, per 10,000 covered workers (DOL, from 1995)
    w = claims.dropna(subset=["ic_rate_sa_per10k"]).set_index("week_ended")
    tiles.append(weekly_tile("SA initial claims rate", w["ic_rate_sa_per10k"], 1, " per 10k", "",
                             w.index[0].year, prelim_label(w["source_initial"].iloc[-1])
                             if is_preliminary(w["source_initial"].iloc[-1]) else ""))

    # 4. SA continuing claims rate, percent (DOL, from 1995)
    c = claims.dropna(subset=["cc_rate_sa"]).set_index("week_ended")
    tiles.append(weekly_tile("SA continuing claims rate", c["cc_rate_sa"], 1, "%", " pt", c.index[0].year,
                             prelim_label(c["source_continued"].iloc[-1])
                             if is_preliminary(c["source_continued"].iloc[-1]) else ""))

    # 5. Sahm indicator vs. the 0.50 recession threshold (no percentile)
    sahm = fred("SAHMREALTIME")
    s_date, s = sahm.index[-1], sahm.iloc[-1]
    s_prev, s_prev_label = vs_month(sahm, s_date - pd.DateOffset(months=1), "not published")
    gap = 0.50 - s
    tiles.append({
        "name": "Sahm indicator",
        "value": f"{s:.2f}",
        "as_of": fmt_month(s_date),
        "changes": [f"{fmt_change(s - s_prev, 2)} vs. {s_prev_label}",
                    (f"{gap:.2f} points below the threshold" if gap > 0
                     else f"{-gap:.2f} points above the threshold")],
        "percentile": "Recession signal at 0.50 or more",
    })
    return tiles


# ===========================================================================
# "What changed this week": fixed rules, fixed order, at most 5 sentences
# ===========================================================================
def since_clause(s: pd.Series) -> str:
    """', the highest since March 2026' when the latest value hasn't been this high (low) for 13+ weeks."""
    direction, when = last_time_as_extreme(s)
    if direction is None:
        return ""
    if when is None:
        return f", the {direction} since records began in {s.index[0].year}"
    weeks = (s.index[-1] - when).days // 7
    return f", the {direction} since {fmt_month(when)}" if weeks >= HIGHEST_SINCE_MIN_WEEKS else ""


def moved(delta) -> str:
    return "rose" if delta > 0 else "fell" if delta < 0 else "was unchanged"


def what_changed(claims: pd.DataFrame, built: datetime) -> list[str]:
    sentences = []
    nw = claims.set_index("week_ended")

    # Rule 1: SA initial claims, latest week (with advance flag and "highest/lowest since")
    ic = fred("ICSA")
    d = ic.iloc[-1] - ic.iloc[-2]
    src = nw["source_initial"].get(ic.index[-1], "")
    tag = " (advance figure)" if is_preliminary(src) and "advance" in src else ""
    if d == 0:
        sentences.append(f"SA initial claims were unchanged at {fmt_claims(ic.iloc[-1])} in the week ending "
                         f"{fmt_date(ic.index[-1])}{tag}.")
    else:
        sentences.append(f"SA initial claims {moved(d)} {fmt_claims(abs(d))} to {fmt_claims(ic.iloc[-1])} in the week "
                         f"ending {fmt_date(ic.index[-1])}{tag}{since_clause(ic)}.")

    # Rule 2: SA initial claims 4-week average, with a streak of 3+ weeks
    ic4 = fred("IC4WSA")
    d4 = ic4.iloc[-1] - ic4.iloc[-2]
    n = streak(ic4)
    streak_txt = (f", its {ordinal(abs(n))} straight weekly {'rise' if n > 0 else 'decline'}" if abs(n) >= 3 else "")
    if d4 == 0:
        sentences.append(f"The SA initial claims 4-week average was unchanged at {fmt_claims(ic4.iloc[-1])}.")
    else:
        sentences.append(f"The SA initial claims 4-week average, which smooths out weekly noise, {moved(d4)} "
                         f"{fmt_claims(abs(d4))} to {fmt_claims(ic4.iloc[-1])}{streak_txt}.")

    # Rule 3: SA initial claims 4-week average vs. a year ago (52 weeks earlier)
    yr_date, yr = value_on_or_before(ic4, ic4.index[-1] - timedelta(days=364))
    pct = 100 * (ic4.iloc[-1] / yr - 1)
    if round(pct, 1) == 0:
        sentences.append(f"The SA initial claims 4-week average is about the same as a year ago ({fmt_claims(yr)}).")
    else:
        sentences.append(f"The SA initial claims 4-week average is {abs(pct):.1f}% {'above' if pct > 0 else 'below'} "
                         f"a year ago ({fmt_claims(yr)}).")

    # Rule 4: SA continuing claims (one week behind initial claims)
    cc = fred("CCSA")
    dc = cc.iloc[-1] - cc.iloc[-2]
    csrc = nw["source_continued"].get(cc.index[-1], "")
    ctag = " (advance figure)" if is_preliminary(csrc) and "advance" in csrc else ""
    if dc == 0:
        sentences.append(f"SA continuing claims were unchanged at {fmt_claims(cc.iloc[-1])} in the week ending "
                         f"{fmt_date(cc.index[-1])}{ctag}.")
    else:
        sentences.append(f"SA continuing claims {moved(dc)} {fmt_claims(abs(dc))} to {fmt_claims(cc.iloc[-1])} in the "
                         f"week ending {fmt_date(cc.index[-1])}{ctag}{since_clause(cc)}.")

    # Rule 5: unemployment rate and Sahm indicator, only if FRED updated them in the past 7 days
    meta = fred_metadata()
    updated = pd.Timestamp(meta.loc["UNRATE", "last_updated"]).tz_convert("UTC")
    if (pd.Timestamp(built) - updated).days < MONTHLY_NEWS_DAYS:
        ur = fred("UNRATE")
        du = round(ur.iloc[-1] - ur.iloc[-2], 1)
        change = (f"unchanged from {ur.index[-2]:%B}" if du == 0 else
                  f"{'up' if du > 0 else 'down'} {abs(du):.1f} point from {ur.index[-2]:%B}")
        text = f"The unemployment rate was {ur.iloc[-1]:.1f}% in {ur.index[-1]:%B}, {change}"
        sahm = fred("SAHMREALTIME")
        if sahm.index[-1] == ur.index[-1]:
            s = sahm.iloc[-1]
            text += (f"; the Sahm indicator is {s:.2f}, "
                     f"{'below' if s < 0.50 else 'at or above'} the 0.50 recession threshold")
        sentences.append(text + ".")
    return sentences[:5]


# ===========================================================================
# The page
# ===========================================================================
def build(built: datetime) -> dict:
    """Everything the Overview template needs."""
    claims = claims_weekly()
    charts = {"unemployment": unemployment_chart(), "ic": ic_rate_chart(claims), "cc": cc_rate_chart(claims)}
    return {"tiles": build_tiles(claims), "sentences": what_changed(claims, built), "charts": charts}
