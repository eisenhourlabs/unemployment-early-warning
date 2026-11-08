"""
Overview page ("Where are we this week?"): five tiles, "What changed this week", and three charts.
Called by build_site.py.
"""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go

from common import (ACCENT, GREYS, add_colour_band, asof_line, base_layout, card, claims_weekly, dates, model_csv,
                    model_output, pre_recession_averages, fmt_change, fmt_claims, fmt_date, fmt_month, fred,
                    fred_metadata, is_preliminary, last_time_as_extreme, line_chart, ordinal, percentile_text, plain,
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
      - the forecast fan after the last published month: 80% band (light), 50% band (dark), middle line (dashed),
        at 3, 6 and 12 months, joined by straight lines; 12 months labeled lower confidence;
      - the next-release nowcast (diamond with a +/-0.2 bar) once the reference-week claims are out;
      - the FOMC median for this year's Q4 (triangle at mid-Q4);
      - the 2001-type and 2008-type what-if paths (dashed, hidden until the reader ticks the toggle).
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
    f = live["fans"]["ur"]
    hz = f["horizons"]
    x = [f["latest_period"]] + [h["target_period"] for h in hz]
    col = lambda k: [f["level"]] + [h[k] for h in hz]
    today = {"today": True, "forecast": True}
    for lo, hi, label, alpha in [("q10", "q90", "Forecast: 80% band", 0.14), ("q25", "q75", "Forecast: 50% band", 0.30)]:
        fig.add_trace(go.Scatter(x=x, y=col(hi), mode="lines", line=dict(width=0), showlegend=False,
                                 hoverinfo="skip", meta={"role": "fan-edge", **today}))
        fig.add_trace(go.Scatter(x=x, y=col(lo), mode="lines", line=dict(width=0), fill="tonexty",
                                 fillcolor=f"rgba(42, 120, 214, {alpha})", name=label, hoverinfo="skip",
                                 meta={"role": "fan", "alpha": alpha, **today}))
    labels = [f"{fmt_month(h['target_period'])} ({h['horizon']} months"
              + (", lower confidence)" if h["horizon"] == 12 else ")") for h in hz]
    fig.add_trace(go.Scatter(
        x=x, y=col("median"), name="Forecast: middle line", mode="lines+markers",
        line=dict(color=ACCENT, width=2, dash="dash"), marker=dict(size=[0] + [7] * len(hz), color=ACCENT),
        customdata=[["latest published", f["level"], f["level"], f["level"], f["level"]]]
                   + [[lab, h["q10"], h["q25"], h["q75"], h["q90"]] for lab, h in zip(labels, hz)],
        hovertemplate="%{customdata[0]}: middle %{y:.1f}%, 50% band %{customdata[2]:.1f}–%{customdata[3]:.1f}%, "
                      "80% band %{customdata[1]:.1f}–%{customdata[4]:.1f}%<extra>Forecast</extra>",
        meta={"role": "main", **today}))
    # Horizon labels just above each 80% band
    fig.add_trace(go.Scatter(
        x=x[1:], y=[h["q90"] for h in hz], mode="text", showlegend=False, hoverinfo="skip",
        text=[f"{h['horizon']} mo" + (" (lower confidence)" if h["horizon"] == 12 else "") for h in hz],
        textposition=["top center"] * (len(hz) - 1) + ["top left"], textfont=dict(size=11),
        meta={"role": "label", **today}))
    fm = live.get("fomc")
    if fm:
        released = f"{pd.Timestamp(fm['released']):%b %Y} projections" if fm.get("released") else "latest projections"
        fig.add_trace(go.Scatter(
            x=[fm["marker_date"]], y=[fm["value"]], mode="markers", name=f"FOMC median, Q4 {fm['year']} ({released})",
            marker=dict(symbol="triangle-up", size=11, color=GREYS[0]),
            hovertemplate=f"FOMC median for Q4 {fm['year']}: %{{y:.1f}}% ({released})<extra></extra>",
            meta={"role": "grey0", **today}))
    n = live["nowcast"]
    if n.get("status") == "ready":
        fig.add_trace(go.Scatter(
            x=[n["month"]], y=[n["value"]], mode="markers", name=f"Nowcast, {fmt_month(n['month'])} release",
            marker=dict(symbol="diamond", size=10, color=ACCENT),
            error_y=dict(type="constant", value=n["range_pt"], thickness=1.5, width=6, color=ACCENT),
            hovertemplate=f"Nowcast for {fmt_month(n['month'])}: %{{y:.1f}}% (±{n['range_pt']:.1f})<extra></extra>",
            meta={"role": "main", **today}))
    stress = live["stress"]["ur"]
    for i, (label, pts) in enumerate(stress["scenarios"].items()):
        kind = label.split(" ")[0]
        fig.add_trace(go.Scatter(
            x=[p["period"] for p in pts], y=[p["level"] for p in pts], mode="lines", visible=False,
            name=f"What-if: a {kind} downturn starting now (not a forecast)",
            line=dict(color=GREYS[i], width=1.8, dash="dashdot" if i else "dash"),
            hovertemplate=f"What-if, {kind}: %{{y:.1f}}%<extra></extra>",
            meta={"role": f"grey{i}", "whatif": True, "today": True, "forecast": True}))
    fig.update_layout(showlegend=True)
    c["figure"] = json.loads(fig.to_json())
    c["ahead"] = (pd.Timestamp(x[-1]) + pd.Timedelta(days=20)).strftime("%Y-%m-%d")
    c["whatif_ahead"] = max(p["period"] for pts in stress["scenarios"].values() for p in pts)
    c["whatif"] = True
    c["notes"] = ur_notes(live)
    c["footer"] += (" Fan = our forecast range: 50% and 80% of outcomes in testing (2000–2026, excluding 2020) fell "
                    "inside the bands. Since 2022 the middle line has run 0.1–0.3 pt below what happened. The 3, 6 and "
                    "12-month ranges are joined by straight lines; 12 months is lower confidence. What-if paths repeat "
                    "the 2001 and 2008 recessions from today's level; they are not forecasts. Forecast elements appear "
                    "only when the time range includes today. FOMC median: Federal Reserve Board Summary of Economic "
                    "Projections via FRED (UNRATEMD), shown for comparison and not offered for download.")
    return c


def ur_notes(live: dict) -> list[str]:
    """Lines under the unemployment-rate chart: the nowcast status and the FOMC comparison."""
    n, notes = live["nowcast"], []
    month = pd.Timestamp(n["month"])
    published = f", published {fmt_date(n['release_date'])}" if n.get("release_date") else ""
    if n.get("status") == "ready":
        notes.append(f"◆ Next-release nowcast for {month:%B %Y}{published}: {n['value']:.1f}% (±{n['range_pt']:.1f} "
                     "point, a range that held about 80% of first releases since 2000). It hits the exact published "
                     "figure no more often than assuming no change does.")
    else:
        notes.append(f"◆ Next-release nowcast ({month:%B %Y}{published}): available after "
                     f"{fmt_date(n['available_after'])} (needs claims for the survey reference week).")
    if n.get("bridges"):
        missed = ", ".join(f"{pd.Timestamp(b):%B}" for b in n["bridges"])
        notes.append(f"The nowcast for {month:%B} covers {n['months_since']} months ({missed} was not collected).")
    fm = live.get("fomc")
    if fm:
        notes.append(f"▲ FOMC median for Q4 {fm['year']}: {fm['value']:.1f}% "
                     f"({pd.Timestamp(fm['released']):%b %Y} projections); our middle line for Q4 averages "
                     f"{fm['our_q4_median']:.2f}%.")
    return notes


# ===========================================================================
# Early-warning score panel (Phase 3)
# ===========================================================================
SCORE_DEFINITION = ("The chance that a new deterioration starts within 6 months: initial claims (4-week average) jump "
                    "25% or more above their low of the past year, or unemployment's 3-month average rises 0.5 point "
                    "above its low. Past alerts include short scares as well as recessions.")


def score_panel(m: dict) -> dict:
    """Everything the score panel shows. m = common.model_output()."""
    live = m["live"]
    if live is None:
        return {"available": False, "note": m["note"]}
    s = live["score"]
    d6 = s["display"]["6"]
    ch = s["change_pt"]
    change = ("unchanged vs. last week" if abs(ch) < 0.05 else
              f"{'▲' if ch > 0 else '▼'} {abs(ch):.1f} pt vs. last week")
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
    fig.add_trace(go.Scatter(x=dates(back.date), y=plain(back.pct), name="Backtest (weekly, out of sample)",
                             mode="lines", line=dict(color=ACCENT, width=1.8, dash="dot"), meta={"role": "main"},
                             hovertemplate="%{y:.0f}%<extra>Backtest</extra>"))
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
    c = card("score-history", "Early-warning score, last 2 years", "", "", fig,
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
        "New job losses. For involuntary unemployment insurance (IUI), this drives how often claims start (frequency).",
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
        "How long people stay on state UI benefits. For involuntary unemployment insurance (IUI), this drives how "
        "long claims last (severity).",
        "Source: DOL state UI claims (ETA 539 weekly report and Thursday news release; FRED CCSA for preliminary "
        "weeks). Seasonally adjusted continued claims as a percent of covered workers, weekly, from 1971; "
        "matches DOL's insured unemployment rate.",
        claims, "cc_rate_sa", "cc_rate_sa_4wk", "source_continued",
        "Percent of covered workers", "%{y:.1f}%",
        ["week_ended", "cc_rate_sa_pct", "cc_rate_sa_4wk_pct", "source"], wide=wide,
        refs=pre_recession_averages(rate), ref_fmt=".2f", markers=COVERAGE_MARKER)


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

    # 3. SA initial claims rate, per 10,000 covered workers (DOL, from 1971)
    w = claims.dropna(subset=["ic_rate_sa_per10k"]).set_index("week_ended")
    tiles.append(weekly_tile("SA initial claims rate", w["ic_rate_sa_per10k"], 1, " per 10k", "",
                             w.index[0].year, prelim_label(w["source_initial"].iloc[-1])
                             if is_preliminary(w["source_initial"].iloc[-1]) else ""))

    # 4. SA continuing claims rate, percent (DOL, from 1971)
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


def score_sentence(live: dict | None) -> str | None:
    """'The early-warning score moved from 2% to 3%; its colour is green.' (rule added in Phase 3)"""
    if live is None:
        return None
    s = live["score"]
    a, b = s["previous"]["display"]["text"], s["display"]["6"]["text"]
    colour = signal(s["colour"])["label"].lower()
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
