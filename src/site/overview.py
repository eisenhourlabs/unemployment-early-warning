"""
Overview page ("Where are we this week?"): five tiles, "What changed this week", and three charts.
Called by build_site.py.
"""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go

from common import (ACCENT, GREYS, MODEL, WHATIF_FOOTER, add_colour_band, add_fan, add_whatif, asof_line, with_outlook, base_layout, card, claims_weekly, dates, model_csv,
                    model_output, pre_recession_averages, fmt_change, fmt_claims, fmt_date, fmt_month, fred,
                    fred_metadata, is_estimate, is_preliminary, last_time_as_extreme, line_chart, ordinal, percentile_text, plain,
                    prelim_label, signal, streak, value_on_or_before, vs_month, weekly_claims_chart)

# How far back a value must last have been matched before a sentence says "the highest since ..."
HIGHEST_SINCE_MIN_WEEKS = 13
# Monthly news (unemployment rate, Sahm) only appears in "What changed" if FRED updated it this recently.
MONTHLY_NEWS_DAYS = 7


# ===========================================================================
# Charts
# ===========================================================================
def unemployment_chart(live: dict | None = None) -> dict:
    """Unemployment rate with recession shading; with the model output (Phase 3) also:
      - the forecast fan after the last published month: 80% band (light), 50% band (dark), at 3, 6 and 12 months,
        joined by straight lines; the dashed middle line stops at 6 months (review WP3: none at 12 months, where
        confidence is lower);
      - the FOMC median for this year's Q4 and, when published, next year's Q4 (triangles at mid-Q4);
      - the 2001-type and 2008-type what-if paths (dashed, hidden until the reader ticks the toggle).
    The next-release nowcast is shown only in the Outlook forecast table (review WP3).
    All of these carry meta.today: site.js shows them only when the time range includes today."""
    c = line_chart(
        "unemployment-rate", "Unemployment rate",
        "The headline measure everyone knows; it lags claims but sets the overall picture.",
        "Source: BLS via FRED (UNRATE). Percent of the labor force, seasonally adjusted, monthly. "
        "Gap: no October 2025 survey (government shutdown).",
        fred("UNRATE"), "Unemployment rate", "Percent of labor force", "%{y:.1f}%", "unemployment_rate_pct",
        wide=True)
    if live is None:
        return c
    fig = go.Figure(c["figure"])
    ahead = add_fan(fig, live["fans"]["ur"], 1, ".1f", "%",
                    lambda h: f"{fmt_month(h['target_period'])} ({h['horizon']} months"
                              + (", lower confidence)" if h["horizon"] == 12 else ")"), low_conf=12, median_until=6)
    today = {"today": True, "forecast": True}
    fm = live.get("fomc")
    if fm:
        released = f"{pd.Timestamp(fm['released']):%b %Y} projections" if fm.get("released") else "latest projections"
        markers = [(fm["year"], fm["value"], fm["marker_date"])]
        if fm.get("next"):
            markers.append((fm["next"]["year"], fm["next"]["value"], fm["next"]["marker_date"]))
            # the chart runs on past next year's marker
            ahead = max(pd.Timestamp(ahead), pd.Timestamp(fm["next"]["marker_date"]) + pd.Timedelta(days=15)
                        ).strftime("%Y-%m-%d")
        for year, value, when in markers:
            fig.add_trace(go.Scatter(
                x=[when], y=[value], mode="markers", name=f"FOMC median, Q4 {year} ({released})",
                marker=dict(symbol="triangle-up", size=11, color=GREYS[0]),
                hovertemplate=f"FOMC median for Q4 {year}: %{{y:.1f}}% ({released})<extra></extra>",
                meta={"role": "grey0", **today}))
    whatif_ahead = add_whatif(fig, live["stress"]["ur"], 1, ".1f", "%")
    return with_outlook(
        c, fig, ahead, whatif_ahead, ur_notes(live),
        " " + fan_coverage_sentence() + " Since 2022 the middle line has run 0.1–0.3 pt below what happened. The 3, 6 "
        "and 12-month ranges are joined by straight lines; no middle line is drawn at 12 months, where confidence is "
        "lower." + WHATIF_FOOTER
        + " FOMC median: Federal Reserve Board Summary of Economic Projections via FRED (UNRATEMD), shown for "
        "comparison and not offered for download.")


def fan_coverage_sentence() -> str:
    """Review WP3 (F6): coverage as measured in testing, from data/model/forecast_evaluation.csv."""
    ev = pd.read_csv(MODEL / "forecast_evaluation.csv")
    ur = ev[(ev.target == "ur") & (ev.subset == "2000-on excl. 2020")]
    return ("Fan = our forecast range: in testing (2000–2026, excluding 2020) the darker band held about half of "
            f"outcomes and the lighter band {ur.cover80.min() * 100:.0f}–{ur.cover80.max() * 100:.0f}%.")


def ur_notes(live: dict) -> list[str]:
    """Line under the unemployment-rate chart: the FOMC comparison (the nowcast moved to the Outlook table, WP3)."""
    fm = live.get("fomc")
    if not fm:
        return []
    released = f"{pd.Timestamp(fm['released']):%b %Y}" if fm.get("released") else "latest"
    nx = fm.get("next")
    if not nx:
        return [f"▲ FOMC median for Q4 {fm['year']}: {fm['value']:.1f}% ({released} projections); our middle line for "
                f"Q4 averages {fm['our_q4_median']:.2f}%."]
    note = (f"▲ FOMC median: {fm['value']:.1f}% for Q4 {fm['year']} and {nx['value']:.1f}% for Q4 {nx['year']} "
            f"({released} projections). Our middle value is {fm['our_q4_median']:.2f}% for Q4 {fm['year']} and "
            f"{nx['our_12m_median']:.2f}% twelve months out.")
    if abs(nx["gap"]) >= 0.3:
        note += (f" The two differ by {abs(nx['gap']):.1f} point at twelve months. Forecasters' consensus has been the "
                 "better guide to the middle; use our range for the spread of outcomes.")
    return [note]


# ===========================================================================
# Early-warning score panel (Phase 3)
# ===========================================================================
# Review WP2 (2026-11). The template adds the link: "... see <a href="duration.html">Duration</a>."
SCORE_DEFINITION = ("The chance that, within 6 months, new claims jump 25% or more above their low of the past year, "
                    "or unemployment's 3-month average rises 0.5 point above its low. This is a stress alert, not a "
                    "recession forecast: of the 14 such events since 1967 (2020 aside), 8 were tied to a recession "
                    "and 6 were short scares that faded. It covers new job losses (claim frequency); for how long "
                    "people stay unemployed (claim severity), see")


def change_line(s: dict) -> str:
    """The line under the score: how it moved since the previous run (review WP9 C2).

    - First live run: exactly "First live run". The previous point is a tested-on-history score, and a change
      between a live run and a tested-on-history point is not shown.
    - Score shown as a number: moves under 0.5 point read "unchanged", because the display rounds to whole
      percent and a smaller move cannot be seen.
    - Score shown in words (verbal bands): any move of 0.05 point or more is shown, as before.
    """
    if s.get("first_live_run"):
        return "First live run"
    ch, label = s["change_pt"], s.get("compare_label", "vs. last week")
    shown_in_words = s["display"]["6"].get("words", False)
    unchanged_below = 0.05 if shown_in_words else 0.5
    return f"unchanged {label}" if abs(ch) < unchanged_below else f"{'▲' if ch > 0 else '▼'} {abs(ch):.1f} pt {label}"


def score_panel(m: dict) -> dict:
    """Everything the score panel shows. m = common.model_output()."""
    live = m["live"]
    if live is None:
        return {"available": False, "note": m["note"]}
    s = live["score"]
    d6 = s["display"]["6"]
    change = change_line(s)
    if m.get("claims_delayed") and live.get("provisional"):
        change += " · provisional (estimated claims)"     # stage 4c: run on claims estimated from state filings
    elif m.get("claims_delayed"):
        change = "no new claims data"              # the claims report is past due: the score keeps its last value
    return {"available": True, "signal": signal(s["colour"]), "value": d6["text"], "words": d6["words"],
            "tooltip": d6["tooltip"], "change": change, "asof": asof_line(live), "definition": SCORE_DEFINITION,
            "drivers": [{"arrow": "↑" if d["direction"] == "up" else "↓", "text": d["text"]} for d in s["drivers"]],
            "note": m["note"]}


def score_mini_chart(live: dict | None, built: datetime) -> dict | None:
    """The last 2 years of the weekly 6-month score: the out-of-sample backtest dotted (labeled "backtest"), live runs
    solid, amber 20% and red 50% guide lines, and the displayed colour (hysteresis) as a strip underneath."""
    wk = model_csv("score_display_weekly.csv", "date")
    if wk is None or live is None:
        return None
    today = pd.Timestamp(built.astimezone(ZoneInfo("America/Chicago")).date())   # same "today" as the page
    start = today - pd.DateOffset(years=2)
    shown = wk[wk.date >= start - pd.Timedelta(days=7)].copy()
    shown["pct"] = shown.score * 100
    back = shown[shown.basis == "backtest"]
    live_rows = pd.concat([back.tail(1), shown[shown.basis == "live"]])     # joined to the last backtest week
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates(back.date), y=plain(back.pct), name="Tested on history (weekly)",
                             mode="lines", line=dict(color=ACCENT, width=1.8, dash="dot"), meta={"role": "main"},
                             hovertemplate="%{y:.0f}%<extra>Tested on history</extra>"))
    fig.add_trace(go.Scatter(x=dates(live_rows.date), y=plain(live_rows.pct), name="Live", mode="lines+markers",
                             line=dict(color=ACCENT, width=2.5), marker=dict(size=[0] * (len(live_rows) - 1) + [8]),
                             meta={"role": "main"}, hovertemplate="%{y:.1f}%<extra>Live</extra>"))
    x0, x1 = start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    for v in (20, 50):
        fig.add_trace(go.Scatter(x=[x0, x1], y=[v, v], mode="lines", showlegend=False, hoverinfo="skip",
                                 line=dict(color=GREYS[1], width=1.2, dash="dot"), meta={"role": "grey1", "ref": True}))
    add_colour_band(fig, shown.date, shown.colour, today)
    base_layout(fig, "Chance within 6 months (%)", "Week of %b %-d, %Y")
    fig.update_layout(height=230, margin=dict(l=52, r=16, t=8, b=30),
                      meta={"refs": [{"text": "amber from 20%", "value": 20}, {"text": "red from 50%", "value": 50}]})
    c = card("score-history", "Early-warning score, last 2 years (fixed view)", "", "", fig,
             ["date", "score_6m_pct", "basis", "colour"],
             [[d, p, b, col] for d, p, b, col in zip(dates(shown.date), plain(shown.pct.round(2)), shown.basis,
                                                     shown.colour)],
             fixed=[x0, x1], downloadable=False)   # downloads: the full history on the Outlook page
    c["fixed_note"] = "Fixed view: the last 2 years, whatever the time setting."
    return c


# Covered employment grew sharply in 1978 when state and local government workers came under UI coverage,
# so claims rates before and after are not strictly comparable. Both rate charts mark it.
COVERAGE_MARKER = [("1978-01-01", "UI coverage expanded (1978)")]


def ic_rate_chart(claims: pd.DataFrame, wide=False) -> dict:
    rate = claims.dropna(subset=["ic_rate_sa_per10k"]).set_index("week_ended")["ic_rate_sa_per10k"]
    return weekly_claims_chart(
        "ic-rate", "SA initial claims rate",
        "New job losses. For involuntary unemployment insurance (IUI), this is the public guide to how often claims start (frequency).",
        "Source: DOL state UI claims (ETA 539 weekly report and Thursday news release; FRED ICSA for preliminary "
        "weeks). Seasonally adjusted initial claims per 10,000 covered workers, weekly, from 1971.",
        claims, "ic_rate_sa_per10k", "ic_rate_sa_4wk_per10k", "source_initial",
        "Per 10,000 covered workers", "%{y:.1f}",
        ["week_ended", "ic_rate_sa_per_10k", "ic_rate_sa_4wk_per_10k", "source"], wide=wide,
        refs=pre_recession_averages(rate), ref_fmt=".1f", markers=COVERAGE_MARKER)


def cc_rate_chart(claims: pd.DataFrame, wide=False) -> dict:
    rate = claims.dropna(subset=["cc_rate_sa"]).set_index("week_ended")["cc_rate_sa"]
    return weekly_claims_chart(
        "cc-rate", "SA continuing claims rate",
        "How long people stay on state UI benefits. For involuntary unemployment insurance (IUI), this is the public "
        "guide to how long claims last (severity).",
        "Source: DOL state UI claims (ETA 539 weekly report and Thursday news release; FRED CCSA for preliminary "
        "weeks). Seasonally adjusted continuing claims as a percent of covered workers, weekly, from 1971; "
        "matches DOL's insured unemployment rate.",
        claims, "cc_rate_sa", "cc_rate_sa_4wk", "source_continued",
        "Percent of covered workers", "%{y:.1f}%",
        ["week_ended", "cc_rate_sa_pct", "cc_rate_sa_4wk_pct", "source"], wide=wide,
        refs=pre_recession_averages(rate), ref_fmt=".2f", markers=COVERAGE_MARKER)


# ===========================================================================
# Tiles: latest value, changes, percentile on full history
# ===========================================================================
def weekly_tile(name, s: pd.Series, decimals, unit, change_unit, since_label, note="", is_rate=False) -> dict:
    """Tile for a weekly series: change vs. last week and vs. the same week a year ago.

    is_rate: a claims rate. Covered employment jumped in 1978 (UI coverage expansion), so when the percentile
    or "lowest / highest since" text reaches back before 1978 it says so (review WP9 C5)."""
    latest_date, latest = s.index[-1], s.iloc[-1]
    year_date, year_val = value_on_or_before(s, latest_date - timedelta(days=364))
    fmt = (lambda v: fmt_claims(v)) if decimals == 0 else (lambda v: f"{v:.{decimals}f}")
    percentile = percentile_text(s, latest, since_label)
    if is_rate and s.index[0].year < 1978:
        percentile += " (rates before 1978 are not strictly comparable)"
    return {
        "name": name,
        "value": fmt(latest) + unit,
        "as_of": f"Week ending {fmt_date(latest_date)}" + (f" · {note}" if note else ""),
        "changes": [f"{fmt_change(latest - s.iloc[-2], decimals, change_unit)} vs. prior week",
                    f"{fmt_change(latest - year_val, decimals, change_unit)} vs. a year ago"],
        "percentile": percentile,
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

    # 3. SA initial claims rate, 4-week average, per 10,000 covered workers (DOL, from 1971). Review WP9 C5:
    #    the 4-week average, like the rate chart's bold line; changes and percentile on the same series.
    w = claims.dropna(subset=["ic_rate_sa_4wk_per10k"]).set_index("week_ended")
    tiles.append(weekly_tile("New claims rate, 4-week average", w["ic_rate_sa_4wk_per10k"], 1, " per 10k", "",
                             w.index[0].year, prelim_label(w["source_initial"].iloc[-1])
                             if is_preliminary(w["source_initial"].iloc[-1]) else "", is_rate=True))

    # 4. SA continuing claims rate, 4-week average, percent (DOL, from 1971)
    c = claims.dropna(subset=["cc_rate_sa_4wk"]).set_index("week_ended")
    tiles.append(weekly_tile("Continuing claims rate, 4-week average", c["cc_rate_sa_4wk"], 1, "%", " pt",
                             c.index[0].year, prelim_label(c["source_continued"].iloc[-1])
                             if is_preliminary(c["source_continued"].iloc[-1]) else "", is_rate=True))

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


def score_sentence(live: dict | None) -> str | None:
    """'The early-warning score moved from 2% to 3%; its colour is green.' (rule added in Phase 3)"""
    if live is None:
        return None
    s = live["score"]
    a, b = s["previous"]["display"]["text"], s["display"]["6"]["text"]
    colour = signal(s["colour"])["label"].lower()
    if s.get("first_live_run"):
        return f"The early-warning score is {b}, {colour}, in its first live run."    # review WP9 C2
    label = s.get("compare_label", "vs. last week")
    if label != "vs. last week":                   # the previous run was not a week earlier
        return (f"The early-warning score is {b} ({fmt_change(s['change_pt'], 1, ' pt')} {label}); "
                f"its colour is {colour}.")
    if a == b:
        return (f"The early-warning score was little changed at {b} ({fmt_change(s['change_pt'], 1, ' pt')} "
                f"vs. last week); its colour is {colour}.")
    return f"The early-warning score moved from {a} to {b}; its colour is {colour}."


def what_changed(claims: pd.DataFrame, built: datetime, live: dict | None = None) -> list[str]:
    sentences = []
    first = score_sentence(live)
    if first:
        sentences.append(first)
    nw = claims.set_index("week_ended")

    # Rule 1: SA initial claims, latest week (with advance flag and "highest/lowest since")
    ic = fred("ICSA")
    d = ic.iloc[-1] - ic.iloc[-2]
    src = nw["source_initial"].get(ic.index[-1], "")
    tag = (" (estimated from state filings: DOL's release is delayed)" if is_estimate(src)
           else " (advance figure)" if is_preliminary(src) and "advance" in src else "")
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
    ctag = (" (estimated from state filings: DOL's release is delayed)" if is_estimate(csrc)
            else " (advance figure)" if is_preliminary(csrc) and "advance" in csrc else "")
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
    return sentences[:6]


# ===========================================================================
# The page
# ===========================================================================
def build(built: datetime) -> dict:
    """Everything the Overview template needs."""
    claims = claims_weekly()
    m = model_output(built)
    live = m["live"]
    charts = {}
    mini = score_mini_chart(live, built)
    if mini:
        charts["score"] = mini           # first: it is the first chart on the page
    charts.update({"unemployment": unemployment_chart(live), "ic": ic_rate_chart(claims), "cc": cc_rate_chart(claims)})
    return {"tiles": build_tiles(claims), "sentences": what_changed(claims, built, live), "charts": charts,
            "score": score_panel(m)}
