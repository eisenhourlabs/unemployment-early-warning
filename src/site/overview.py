"""
Overview page ("Where are we this week?"): five tiles, "What changed this week", and three charts.
Called by build_site.py.
"""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go

from common import (ACCENT, GREYS, MODEL, WHATIF_FOOTER, add_colour_band, add_fan, add_whatif, asof_line, with_outlook, base_layout, card, claims_weekly, dates, duration_watch, model_csv,
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
    # Review WP7 (P3): the caveat a reader should see without opening the footer
    c["caveat"] = ("Read the shaded range, not a single line. The Fed's median is marked for comparison; forecasters' "
                   "consensus has been the better guide to the middle.")
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
# "Where things stand" panel (review WP7, Part A; wording approved by Troy)
# ===========================================================================
# Thresholds of the three confirmation triggers the panel uses (as in config/triggers.csv and live_latest.json).
CLAIMS_AMBER, CLAIMS_RED = 0.15, 0.25          # new claims 4-week average vs. its lowest of the previous 52 weeks
CONT_AMBER, CONT_RED = 0.10, 0.20              # continuing claims 4-week average vs. 52 weeks earlier
SAHM_AMBER = 0.30                              # unemployment's 3-month average above its 12-month low (points)

# Score inputs as the "What to watch" list names them: (name, verb)
WATCH_NAMES = {
    "sahm": ("Unemployment's rise from its low", "is"),
    "claims_low": ("New claims", "are"),
    "claims_yoy": ("New claims", "are"),
    "cont_yoy": ("People on benefits", "are"),
    "temp_help": ("Temporary-help jobs", "are"),
    "yield_curve": ("The yield curve", "is"),
    "mfg": ("Regional factory surveys", "are"),
    "nfci": ("Financial conditions", "are"),
}

MEANING = {
    "freq_red": ("A jump in new claims is under way. Expect more new unemployment claims now, and longer claims from "
                 "six to eighteen months out if it persists."),
    "freq_amber": ("New claims are rising. If this continues, expect more new unemployment claims within one to three "
                   "months. Check the weekly figure each Thursday."),
    "sev_red": ("The number of people on benefits is rising fast. In past downturns claim durations kept lengthening "
                "for one to two years after layoffs peaked."),
    "sev_amber": ("More people are on benefits than a year ago. Claim durations have usually lengthened within a year "
                  "from here."),
    "score_red": ("The early-warning score is high, but claims have not confirmed it. Readings this high were followed "
                  "by a claims jump or unemployment rise roughly half the time."),
    "score_amber": ("Early-warning inputs have turned, but claims themselves have not. About 1 amber month in 4 has been "
                    "followed by a claims jump or unemployment rise within six months. Watch the weekly claims figures."),
    "all_green": "Nothing here points to more claims or longer claims in the months ahead. Routine weekly monitoring.",
}

# Small line under the Duration cell. Bracketed wording (review WP7) until test T2 in WP8 has passed.
DURATION_SMALL = {
    "falling": "From here, durations have almost never lengthened within a year. Would turn amber at about {amber} "
               "million (10% above a year ago).",
    "green": "From here, durations have lengthened within a year occasionally. Amber at about {amber} million.",
    "amber": "From here, long-term unemployment has usually risen sharply within a year. Red at about {red} million.",
    "red": "From here, long-term unemployment has risen sharply within a year in most cases, and durations kept "
           "rising for one to two years after layoffs peaked.",
}
WORST = {"green": 0, "amber": 1, "red": 2}


def round_to(x: float, step: int) -> int:
    return int(round(x / step) * step)


def claims_status(v: float) -> dict:
    """Cell 1: the status word and colour of new claims vs. their low of the past year."""
    if v >= CLAIMS_RED:
        return {"word": "High", "colour": "red"}
    if v >= CLAIMS_AMBER:
        return {"word": "Rising", "colour": "amber"}
    return {"word": "Low" if v < 0.05 else "Normal", "colour": "green"}


def trigger_value(live: dict, tid: str) -> float:
    row = next((r for r in live["triggers"]["rows"] if r["id"] == tid), None)
    return 0.0 if row is None or row.get("value") is None else float(row["value"])


def event_under_way(live: dict) -> tuple[bool, str | None]:
    """Review WP4's provisional 'event under way' flag; an absent key means not under way."""
    e = live.get("event_state") or {}
    return bool(e.get("under_way")), e.get("since")


def stand_numbers(live: dict, claims: pd.DataFrame, ur: pd.Series) -> dict:
    """The levels the panel quotes, from the same data the triggers used (cut at the live run's claims weeks):
    A = initial claims 4-week average, L = its lowest over the previous 52 weeks (current week excluded, as in
    src/model/triggers.py claims_vs_low_of), s = usual weekly move of A, C / C52 = continuing claims 4-week average
    now and 52 weeks earlier, ur3 / ur_low = the unemployment rate's 3-month average and its lowest over the
    previous 12 months."""
    i = live["inputs"]
    ic4 = claims.dropna(subset=["ic_sa_4wk"]).set_index("week_ended")["ic_sa_4wk"]
    ic4 = ic4[ic4.index <= pd.Timestamp(i["initial_claims_week"])]
    cc4 = claims.dropna(subset=["cc_sa_4wk"]).set_index("week_ended")["cc_sa_4wk"]
    cc4 = cc4[cc4.index <= pd.Timestamp(i["continuing_claims_week"])]
    ur = ur[ur.index <= pd.Timestamp(i["unemployment_month"])]
    ur3 = ur.rolling(3).mean().dropna()
    return {"A": float(ic4.iloc[-1]), "L": float(ic4.iloc[-53:-1].min()),
            "s": float(ic4.diff().iloc[-104:].std()),
            "C": float(cc4.iloc[-1]), "C52": float(cc4.get(cc4.index[-1] - pd.Timedelta(weeks=52), float("nan"))),
            "cc_week": cc4.index[-1],
            "ur3": float(ur3.iloc[-1]), "ur_low": float(ur3.iloc[-13:-1].min())}


def watch_list(live: dict, n: dict, v_sahm: float, v_ic: float, v_cc: float) -> tuple[list[dict], str]:
    """'What to watch': at most three items, then the closing small line."""
    items = []
    s = live["score"]
    up = [c for c in s.get("contributions", []) if c.get("contribution", 0) > 0]
    if up:
        top = max(up, key=lambda c: c["contribution"])
        name, verb = WATCH_NAMES.get(top["input"], (top["input"], "is"))
        drv = next((d["text"] for d in s.get("drivers", []) if d["input"] == top["input"]), None)
        sentence = (top.get("sentence") or drv or "").split(" (pushes")[0].rstrip(".")
        if sentence:
            items.append({"bold": name, "text": f" {verb} the main input pushing risk up: "
                                                f"{sentence[0].lower() + sentence[1:]}.", "meter": None})
    usual = max(1000, round_to(n["s"], 1000))
    sahm_amber = n["ur_low"] + SAHM_AMBER
    measures = [
        ("Unemployment rate, 3-month average", max(v_sahm / SAHM_AMBER, 0),
         f"{n['ur3']:.2f}%", f"Amber at {sahm_amber:.2f}%"
         + (f", which would take about three monthly readings near {n['ur_low'] + 0.4:.1f}%" if v_sahm <= 0 else "")
         + "."),
        ("New claims, 4-week average", max(v_ic / CLAIMS_AMBER, 0),
         fmt_claims(round_to(n["A"], 250)),
         f"Amber at about {fmt_claims(round_to((1 + CLAIMS_AMBER) * n['L'], 500))}. "
         f"A normal week moves the average by about {fmt_claims(usual)}."),
        ("People on benefits, 4-week average", max(v_cc / CONT_AMBER, 0),
         f"{n['C'] / 1e6:.2f} million", f"Amber at about {(1 + CONT_AMBER) * n['C52'] / 1e6:.2f} million."),
    ]
    order = sorted(range(3), key=lambda k: -measures[k][1])        # stable: ties keep Sahm, new, continuing
    for k in order:
        if len(items) >= 3:
            break
        name, p, level, after = measures[k]
        filled = min(p, 1)
        items.append({"bold": f"{name}: {level}.", "text": " " + after, "meter": round(filled * 100),
                      "label": f"{round(filled * 100)}% of the way to amber"})
    ps = [m[1] for m in measures]
    closing = ""
    if all(p < 0.5 for p in ps):
        closing = "No measure is more than half-way to a warning level. "
    past = [m[0] for m in measures if m[1] >= 1]
    if past:
        closing = " ".join(f"{name} is past its warning level." for name in past) + " "
    closing += ("Levels are worked out from this week's data and move as the past year's low and the year-ago "
                "figure move.")
    return items, closing


def stand_panel(live: dict | None, claims: pd.DataFrame, ur: pd.Series | None = None) -> dict | None:
    """Everything the 'Where things stand' panel shows (None when there is no model output: no panel)."""
    if live is None:
        return None
    n = stand_numbers(live, claims, fred("UNRATE") if ur is None else ur)
    v_sahm, v_ic, v_cc = (trigger_value(live, t) for t in ("sahm", "claims_vs_low", "cont_claims_yoy"))
    on, since = event_under_way(live)

    # Cell 1: new job losses (frequency)
    st1 = claims_status(v_ic)
    x = round(v_ic * 100)
    a = fmt_claims(round_to(n["A"], 250))
    if st1["word"] == "Low" and x <= 1:
        main1 = f"New claims average {a} a week, at their lowest of the past year."
    else:
        main1 = f"New claims average {a} a week, {x}% above their lowest of the past year."
        if st1["colour"] == "amber":
            main1 += " That is the warning zone."
        elif st1["colour"] == "red":
            main1 += (" A claims jump of this size is what the early-warning score warns about; it is now under way.")
    amber1, red1 = (fmt_claims(round_to((1 + t) * n["L"], 500)) for t in (CLAIMS_AMBER, CLAIMS_RED))
    small1 = {"green": f"Would turn amber at about {amber1} a week (15% above the past year's low) and red at about "
                       f"{red1}.",
              "amber": f"Red at about {red1} a week.", "red": ""}[st1["colour"]]

    # Cell 2: duration (severity)
    dw = duration_watch(v_cc)
    y = round(abs(v_cc) * 100)
    main2 = (f"{n['C'] / 1e6:.2f} million people are on benefits, {y}% {'fewer' if v_cc < 0 else 'more'} than a "
             "year ago.")
    small2 = DURATION_SMALL[dw["band"]].format(amber=f"{(1 + CONT_AMBER) * n['C52'] / 1e6:.2f}",
                                               red=f"{(1 + CONT_RED) * n['C52'] / 1e6:.2f}")

    # Cell 3: next 6 to 12 months (early warning)
    s = live["score"]
    d6 = s["display"]["6"]
    base = round(s["base_rates"]["6"] * 100)
    if on:
        when = f"{pd.Timestamp(since + '-01' if len(str(since)) == 7 else since):%b %Y}" if since else "recently"
        main3 = (f"A deterioration is under way since {when} (provisional). The score now shows the chance of a "
                 "further, new event.")
    else:
        main3 = f"Chance of a claims jump or unemployment rise within 6 months: {d6['text']} (usual: {base}%)."
    small3 = "A stress alert, not a recession forecast."

    cells = [
        {"heading": "New job losses", "sub": "how often claims start", "colour": st1["colour"],
         "badge": st1["word"], "main": main1, "small": small1, "link": ("job-losses.html", "Job Losses →")},
        {"heading": "Duration", "sub": "how long claims last", "colour": dw["colour"], "badge": dw["word"],
         "main": main2, "small": small2, "link": ("duration.html", "Duration →")},
        {"heading": "Next 6 to 12 months", "sub": "early warning", "colour": s["colour"],
         "badge": f"{signal(s['colour'])['label']} · {d6['text']}", "main": main3, "small": small3,
         "link": ("outlook.html", "Outlook →")},
    ]
    for c in cells:
        c["icon"] = signal(c["colour"])["icon"]

    # "What it means": frequency and severity rows first; otherwise the score rows; otherwise all green
    parts = []
    if st1["colour"] == "red" or on:
        parts.append(MEANING["freq_red"])
    elif st1["colour"] == "amber":
        parts.append(MEANING["freq_amber"])
    if dw["colour"] == "red":
        parts.append(MEANING["sev_red"])
    elif dw["colour"] == "amber":
        parts.append(MEANING["sev_amber"])
    if not parts:
        parts.append(MEANING["score_red"] if s["colour"] == "red" else
                     MEANING["score_amber"] if s["colour"] == "amber" else MEANING["all_green"])
    worst = max((c["colour"] for c in cells), key=lambda col: WORST.get(col, 0))

    items, closing = watch_list(live, n, v_sahm, v_ic, v_cc)
    return {"asof": asof_line(live), "cells": cells, "meaning": " ".join(parts), "meaning_colour": worst,
            "watch": items, "closing": closing}


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
    c["stretch_note"] = stretch_note(shown[shown.date >= start])
    return c


def stretch_note(window: pd.DataFrame) -> str | None:
    """Review WP7 Part B: when any week in the plotted window BEFORE the current colour run was amber or red, the
    footer starts with a sentence on the long amber / red stretch without a recession. The years and the
    unemployment range are those of the longest amber-or-red run in data/model/score_skill_summary.csv (review WP1,
    the stretch the Outlook link explains), so the sentence and the Outlook note always agree. None otherwise."""
    if window.empty:
        return None
    col = list(window.colour)
    k = len(col)
    while k > 0 and col[k - 1] == col[-1]:     # drop the current colour run
        k -= 1
    if not any(c in ("amber", "red") for c in col[:k]):
        return None
    try:
        r = pd.read_csv(MODEL / "score_skill_summary.csv").iloc[0]
    except (OSError, IndexError):
        return None
    start = pd.Timestamp(r.longest_elevated_run_start + "-01")
    end = pd.Timestamp(r.longest_elevated_run_end + "-01")
    ur = fred("UNRATE")
    during = ur[(ur.index >= start) & (ur.index <= end)]
    first, last = start.year + (start.month > 6), end.year - (end.month < 7)     # as outlook.most_years
    years = f"{first}–{last}" if last > first else str(first)
    return (f"The score was amber or red for most of {years}: unemployment drifted up from "
            f"{during.min():.1f}% to {during.max():.1f}% and two short scares followed, but no recession.")


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


def build_tiles(claims: pd.DataFrame, live: dict | None = None) -> list[dict]:
    """Five tiles (review WP7, Part E): unemployment rate; new job losses (frequency): new claims 4-week average and
    new claims rate; duration (severity): people on benefits vs. a year ago and the continuing claims rate.
    'group' starts a labelled group of tiles. The Sahm indicator tile was removed (Troy's decision 9)."""
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

    # 2. SA initial claims, 4-week average (FRED IC4WSA, from 1967); last line: vs. the past year's low (trigger 2)
    ic4 = fred("IC4WSA")
    src = claims.set_index("week_ended")["source_initial"].get(ic4.index[-1], "")
    t2 = weekly_tile("New claims, 4-week average", ic4, 0, "", "", ic4.index[0].year,
                     prelim_label(src) if is_preliminary(src) else "")
    if live is not None:
        x = round(trigger_value(live, "claims_vs_low") * 100)
        t2["percentile"] = ("At the past year's low" if x == 0 else
                            f"{abs(x)}% {'above' if x > 0 else 'below'} the past year's low")
    t2["group"] = "New job losses (frequency)"
    tiles.append(t2)

    # 3. SA initial claims rate, 4-week average, per 10,000 covered workers (DOL, from 1971). Review WP9 C5:
    #    the 4-week average, like the rate chart's bold line; changes and percentile on the same series.
    w = claims.dropna(subset=["ic_rate_sa_4wk_per10k"]).set_index("week_ended")
    tiles.append(weekly_tile("New claims rate, 4-week average", w["ic_rate_sa_4wk_per10k"], 1, " per 10k", "",
                             w.index[0].year, prelim_label(w["source_initial"].iloc[-1])
                             if is_preliminary(w["source_initial"].iloc[-1]) else "", is_rate=True))

    # 4. People on benefits vs. a year ago (trigger 4's value) with the Duration watch word and colour
    c4 = claims.dropna(subset=["cc_sa_4wk"]).set_index("week_ended")["cc_sa_4wk"]
    if live is not None:
        v = trigger_value(live, "cont_claims_yoy")
        c4 = c4[c4.index <= pd.Timestamp(live["inputs"]["continuing_claims_week"])]
        dw = duration_watch(v)
        r = round(v * 100)
        tiles.append({"name": "People on benefits vs. a year ago",
                      "value": ("+" if r > 0 else "−" if r < 0 else "") + f"{abs(r)}%",
                      "as_of": f"{c4.iloc[-1] / 1e6:.2f} million, week ending {fmt_date(c4.index[-1])}",
                      "changes": [], "percentile": f"Duration watch: {dw['word']}", "edge": dw["colour"],
                      "group": "Duration (severity)"})

    # 5. SA continuing claims rate, 4-week average, percent (DOL, from 1971)
    c = claims.dropna(subset=["cc_rate_sa_4wk"]).set_index("week_ended")
    t5 = weekly_tile("Continuing claims rate, 4-week average", c["cc_rate_sa_4wk"], 1, "%", " pt",
                     c.index[0].year, prelim_label(c["source_continued"].iloc[-1])
                     if is_preliminary(c["source_continued"].iloc[-1]) else "", is_rate=True)
    if live is None:
        t5["group"] = "Duration (severity)"
    tiles.append(t5)
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
    """'The early-warning score is 2%, green, unchanged.' (review WP7, Part D). A move under 0.5 point reads
    'unchanged' when the score is shown as a whole percent (the same rule as the line under the score, WP9 C2)."""
    if live is None:
        return None
    s = live["score"]
    a, b = s["previous"]["display"]["text"], s["display"]["6"]["text"]
    colour = signal(s["colour"])["label"].lower()
    if s.get("first_live_run"):
        # review WP9 C2 wording, kept only while there are at most 4 live runs
        if s.get("live_runs", 1) <= 4:
            return f"The early-warning score is {b}, {colour}, in its first live run."
        return f"The early-warning score is {b}, {colour}."
    ch = s["change_pt"]
    unchanged_below = 0.05 if s["display"]["6"].get("words") else 0.5
    move = ("unchanged" if abs(ch) < unchanged_below else
            f"{'up' if ch > 0 else 'down'} {abs(ch):.1f} point{'' if round(abs(ch), 1) == 1 else 's'}")
    return f"The early-warning score is {b}, {colour}, {move}."


# Moves larger than usual (review WP7, Part D): |weekly change| > 1.5 standard deviations of the series' weekly
# changes over the previous 104 weeks.
UNUSUAL_SD = 1.5
SCORE_MOVE_PT = 5            # a score move of 5 points or more is listed with the unusual items
TRIGGER_NAMES = {"sahm": "the Sahm indicator", "claims_vs_low": "new claims vs. their low of the past year",
                 "cont_claims_yoy": "continuing claims vs. a year ago"}


def larger_than_usual(s: pd.Series) -> bool:
    """True when the latest weekly change is more than 1.5 standard deviations of the previous 104 changes."""
    d = s.diff().dropna()
    if len(d) < 30:
        return False
    return bool(abs(d.iloc[-1]) > UNUSUAL_SD * d.iloc[-105:-1].std())


def previous_run(live: dict | None) -> dict | None:
    """The archived live run before this one (data/archive/YYYY/*.json), or None."""
    if live is None:
        return None
    key = lambda d: (d.get("asof", ""), d.get("run_at", ""))
    best = None
    for f in sorted((MODEL.parent / "archive").glob("*/*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if key(d) < key(live) and (best is None or key(d) > key(best)):
            best = d
    return best


def colour_changes(live: dict | None, prev: dict | None) -> list[str]:
    """(a) colour changes since the previous live run: score, Duration watch, the Sahm indicator, new claims and
    continuing claims triggers, and the event flag."""
    if live is None:
        return []
    out = []
    s = live["score"]
    was = (s.get("previous") or {}).get("colour")
    if was and was != s["colour"] and not s.get("first_live_run"):
        out.append(f"The early-warning score turned {s['colour']} (from {was}).")
    if prev is None:
        return out
    rows = {r["id"]: r for r in live["triggers"]["rows"]}
    old = {r["id"]: r for r in (prev.get("triggers") or {}).get("rows", [])}
    if "cont_claims_yoy" in rows and old.get("cont_claims_yoy", {}).get("value") is not None:
        now_w = duration_watch(trigger_value(live, "cont_claims_yoy"))["word"]
        then_w = duration_watch(float(old["cont_claims_yoy"]["value"]))["word"]
        if now_w != then_w:
            out.append(f"Duration watch moved to {now_w} (from {then_w}).")
    for tid, name in TRIGGER_NAMES.items():
        if tid in rows and tid in old and rows[tid]["colour"] != old[tid]["colour"]:
            out.append(f"The confirmation trigger for {name} turned {rows[tid]['colour']} "
                       f"(from {old[tid]['colour']}).")
    on_now, _ = event_under_way(live)
    on_then, _ = event_under_way(prev)
    if on_now and not on_then:
        out.append("A deterioration is now flagged as under way (provisional).")
    elif on_then and not on_now:
        out.append("The provisional flag for a deterioration under way has been lifted.")
    return out


def claims_tag(src) -> str:
    src = "" if pd.isna(src) else str(src)
    return (" (estimated from state filings: DOL's release is delayed)" if is_estimate(src)
            else " (advance figure)" if is_preliminary(src) and "advance" in src else "")


def what_changed(claims: pd.DataFrame, built: datetime, live: dict | None = None,
                 prev: dict | None = None, series: dict | None = None, ur_news: bool | None = None) -> list[str]:
    """'What changed this week' (review WP7, Part D), in this order, at most four bullets:
      (a) colour changes since the previous live run; (b) a score move of 5 points or more;
      (c) claims moves larger than usual, in the usual wording plus "(a larger move than usual)";
      (d) one merged line for the ordinary moves; (e) the unemployment rate, only within 7 days of the jobs report.
    If nothing in (a)-(c) applies, the first bullet is "Nothing unusual this week." The score sentence follows the
    unusual items (it is itself item (b) when the score moved 5 points or more).
    prev / series / ur_news: for tests (default: the archive, the FRED files and FRED's update time)."""
    nw = claims.set_index("week_ended")
    get = (lambda k: series[k]) if series else fred
    ic, ic4, cc = get("ICSA"), get("IC4WSA"), get("CCSA")
    if prev is None and series is None:
        prev = previous_run(live)
    unusual = colour_changes(live, prev)
    score_line = score_sentence(live)
    if score_line and live is not None and abs(live["score"]["change_pt"]) >= SCORE_MOVE_PT \
            and not live["score"].get("first_live_run"):
        unusual.append(score_line)
        score_line = None

    # (c) the three weekly claims measures: unusual ones get their own sentence
    d, d4, dc = ic.iloc[-1] - ic.iloc[-2], ic4.iloc[-1] - ic4.iloc[-2], cc.iloc[-1] - cc.iloc[-2]
    tag = claims_tag(nw["source_initial"].get(ic.index[-1], ""))
    ctag = claims_tag(nw["source_continued"].get(cc.index[-1], ""))
    big = {"ic": larger_than_usual(ic), "ic4": larger_than_usual(ic4), "cc": larger_than_usual(cc)}
    larger = " (a larger move than usual)."
    if big["ic"]:
        unusual.append(f"SA initial claims {moved(d)} {fmt_claims(abs(d))} to {fmt_claims(ic.iloc[-1])} in the week "
                       f"ending {fmt_date(ic.index[-1])}{tag}{since_clause(ic)}{larger}")
    if big["ic4"]:
        n = streak(ic4)
        streak_txt = (f", its {ordinal(abs(n))} straight weekly {'rise' if n > 0 else 'decline'}" if abs(n) >= 3 else "")
        unusual.append(f"The SA initial claims 4-week average, which smooths out weekly noise, {moved(d4)} "
                       f"{fmt_claims(abs(d4))} to {fmt_claims(ic4.iloc[-1])}{streak_txt}{larger}")
    if big["cc"]:
        unusual.append(f"SA continuing claims {moved(dc)} {fmt_claims(abs(dc))} to {fmt_claims(cc.iloc[-1])} in the "
                       f"week ending {fmt_date(cc.index[-1])}{ctag}{since_clause(cc)}{larger}")

    out = unusual if unusual else ["Nothing unusual this week."]
    if score_line:
        out.append(score_line)

    # (d) the ordinary moves, merged into one line; an advance / estimated week says so inside the brackets
    updown = lambda x: f"{'up' if x > 0 else 'down'} {fmt_claims(abs(x))}" if x else "unchanged"
    inner = lambda tag_, rest: f" ({tag_.strip(' ()')}; {rest})" if tag_ else f" ({rest})"
    pieces = []
    if not big["ic"] and not big["ic4"]:
        pieces.append(f"new claims {fmt_claims(ic.iloc[-1])}"
                      + inner(tag, f"4-week average {fmt_claims(ic4.iloc[-1])}, {updown(d4)}"))
    elif not big["ic"]:
        pieces.append(f"new claims {fmt_claims(ic.iloc[-1])}" + inner(tag, updown(d)))
    elif not big["ic4"]:
        pieces.append(f"new claims 4-week average {fmt_claims(ic4.iloc[-1])} ({updown(d4)})")
    if not big["cc"]:
        pieces.append(f"people on benefits {fmt_claims(cc.iloc[-1])}" + inner(ctag, updown(dc)))
    if pieces:
        out.append("Weekly claims moved within their normal range: " + "; ".join(pieces) + ".")

    # (e) the unemployment rate, only if the jobs report came out in the past 7 days
    if ur_news is None:
        updated = pd.Timestamp(fred_metadata().loc["UNRATE", "last_updated"]).tz_convert("UTC")
        ur_news = (pd.Timestamp(built) - updated).days < MONTHLY_NEWS_DAYS
    if ur_news:
        ur = get("UNRATE")
        du = round(ur.iloc[-1] - ur.iloc[-2], 1)
        change = "unchanged" if du == 0 else f"{'up' if du > 0 else 'down'} {abs(du):.1f} point"
        out.append(f"The unemployment rate was {ur.iloc[-1]:.1f}% in {ur.index[-1]:%B}, {change}.")
    return out[:4]


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
    tiles = build_tiles(claims, live)
    groups = []                          # tiles in labelled groups (review WP7, Part E)
    for t in tiles:
        if t.get("group") or not groups:
            groups.append({"label": t.get("group", ""), "tiles": []})
        groups[-1]["tiles"].append(t)
    return {"tiles": tiles, "tile_groups": groups, "sentences": what_changed(claims, built, live), "charts": charts,
            "score": score_panel(m), "stand": stand_panel(live, claims)}
