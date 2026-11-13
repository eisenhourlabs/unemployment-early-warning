"""
Outlook page (Phase 3): the early-warning score in full. Score history since 1980, the 3 / 6 / 12-month
probabilities, the confirmation triggers (Layer 1 in docs/model.md), the forecast table, the track record and the methodology.
Called by build_site.py. Everything comes from the model output files (src/model/live.py); if they are missing
the page still builds and says so.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go

from common import (ACCENT, FAINT, GREYS, MODEL, add_colour_band, event_banner, asof_line, base_layout, card, dates, fmt_date,
                    fmt_month, fred, model_csv, model_output, plain, signal)

CENTRAL = ZoneInfo("America/Chicago")
MINUS = "−"

# Plain names of the score inputs, and how to show each one's value (inputs are stored signed so that higher means
# worse; the table shows the natural number).
INPUTS = {
    "claims_low": ("New claims vs. their 52-week low", lambda v: pct(v)),
    "sahm": ("Sahm indicator", lambda v: f"{v:.2f} pt"),
    "temp_help": ("Temporary-help jobs, 6-month change", lambda v: pct(-v)),
    "mfg": ("Regional factory surveys, 3-month average", lambda v: signed(-v, 1)),
    "nfci": ("Financial conditions (NFCI)", lambda v: signed(v, 2)),
    "yield_curve": ("Yield curve, lowest spread of the past 18 months", lambda v: signed(-v, 2) + " pt"),
    "claims_yoy": ("New claims vs. a year ago", lambda v: pct(v)),
    "cont_yoy": ("Continuing claims vs. a year ago", lambda v: pct(v)),
}


def signed(v: float, d: int) -> str:
    r = round(v, d)
    return ("+" if r > 0 else MINUS if r < 0 else "") + f"{abs(r):.{d}f}"


def pct(v: float, d: int = 1) -> str:
    return signed(v * 100, d) + "%"


def lead_text(v) -> str:
    """Months of warning from score_results.csv: 5 -> '5 months', 'on since 2006-05' -> 'on since May 2006'."""
    if pd.isna(v):
        return "—"
    s = str(v)
    if s.startswith("on since"):
        return "on since " + fmt_month(s.split()[-1] + "-01")
    if s == "none":
        return "none"
    n = int(float(s))
    return f"{n} month" + ("" if n == 1 else "s")


# ===========================================================================
# Score history chart
# ===========================================================================
def history_chart(live: dict, built: datetime) -> dict | None:
    m = model_csv("score_display_monthly.csv", "month")
    if m is None:
        return None
    today = pd.Timestamp(built.astimezone(CENTRAL).date())
    m["pct"] = m.p6 * 100
    fig = go.Figure()
    # Events: recession-linked (blue) and scares (orange); 2020 hatched (not used to fit)
    ev = pd.read_csv(MODEL / "events.csv", dtype={"start_month": str, "end_month": str})
    for e in ev.itertuples():
        start = pd.Timestamp(e.start_month + "-01")
        end = today if e.end_month == "ongoing" else pd.Timestamp(e.end_month + "-01") + pd.offsets.MonthBegin(1)
        if end < m.month.iloc[0]:
            continue
        if e.classification == "recession (pandemic)":
            fig.add_trace(go.Scatter(
                x=dates([start, start, end, end, start]), y=[0, 100, 100, 0, 0], mode="lines", fill="toself",
                fillpattern=dict(shape="/", fgcolor=GREYS[1], size=8, solidity=0.15), fillcolor="rgba(0,0,0,0)",
                line=dict(width=0), name="2020 pandemic (not used to fit)", hoverinfo="skip",
                meta={"role": "grey1", "noscale": True}))
        else:
            kind = "scare" if e.classification == "scare" else "recession"
            fig.add_shape(type="rect", xref="x", yref="paper", x0=f"{start:%Y-%m-%d}", x1=f"{end:%Y-%m-%d}",
                          y0=0.1, y1=1, line_width=0, layer="below", name=f"event-{kind}",
                          fillcolor="rgba(42,120,214,0.13)" if kind == "recession" else "rgba(214,120,42,0.16)")
    # Review WP7 (P2): months inside an event (start to end month, inclusive) are drawn as a thin grey line: the
    # score is then no longer a forecast. The blue lines cover only months outside events, with gaps (no bridging).
    inside = pd.Series(False, index=m.index)
    for e in ev.itertuples():
        first = pd.Timestamp(e.start_month + "-01")
        last = today if e.end_month == "ongoing" else pd.Timestamp(e.end_month + "-01")
        inside |= (m.month >= first) & (m.month <= last)
    m["out"] = m.pct.where(~inside)
    m["during"] = m.pct.where(inside)
    pseudo = m[m.basis == "pseudo out of sample"]
    oos = pd.concat([pseudo.tail(1), m[m.basis == "out of sample"]])        # joined at January 2000
    fig.add_trace(go.Scatter(x=dates(pseudo.month), y=plain(pseudo.out), name="1980–1999: tested with partly revised data",
                             mode="lines", line=dict(color=FAINT, width=1.8), meta={"role": "faint"}, connectgaps=False,
                             hovertemplate="%{y:.0f}%<extra>Tested with partly revised data</extra>"))
    fig.add_trace(go.Scatter(x=dates(oos.month), y=plain(oos.out), name="2000 on: out of sample",
                             mode="lines", line=dict(color=ACCENT, width=2), meta={"role": "main"}, connectgaps=False,
                             hovertemplate="%{y:.0f}%<extra>Out of sample</extra>"))
    fig.add_trace(go.Scatter(x=dates(m.month), y=plain(m.during), name="During an event (not a forecast)",
                             mode="lines", line=dict(color=GREYS[0], width=1.2), meta={"role": "grey0"},
                             connectgaps=False, hovertemplate="%{y:.0f}%<extra>During an event</extra>"))
    s = live["score"]
    # Live runs: every archived run (live_history.csv), then this one; the latest gets the large dot
    runs = model_csv("live_history.csv", "asof")
    pts = {} if runs is None else {d.strftime("%Y-%m-%d"): v * 100 for d, v in zip(runs["asof"], runs.p6)}
    pts[live["asof"]] = s["p6"] * 100
    xs = sorted(pts)
    fig.add_trace(go.Scatter(x=xs, y=[pts[d] for d in xs], name="Live runs (weekly)", mode="lines+markers",
                             line=dict(color=ACCENT, width=2), marker=dict(size=[5] * (len(xs) - 1) + [9], color=ACCENT),
                             meta={"role": "main"}, hovertemplate="%{y:.1f}%<extra>Live</extra>"))
    x0 = m.month.iloc[0].strftime("%Y-%m-%d")
    for v in (20, 50):
        fig.add_trace(go.Scatter(x=[x0, today.strftime("%Y-%m-%d")], y=[v, v], mode="lines", showlegend=False,
                                 hoverinfo="skip", line=dict(color=GREYS[1], width=1.2, dash="dot"),
                                 meta={"role": "grey1", "ref": True}))
    band_dates = list(m.month) + [pd.Timestamp(live["asof"])]
    band_cols = list(m.colour) + [s["colour"]]
    add_colour_band(fig, pd.Series(band_dates), pd.Series(band_cols), today)
    base_layout(fig, "Chance within 6 months (%)", "%b %Y")
    fig.update_layout(height=320, meta={"refs": [{"text": "amber from 20%", "value": 20},
                                                 {"text": "red from 50%", "value": 50}]})
    rows = [[d, a, b, c, bas, col] for d, a, b, c, bas, col in
            zip(dates(m.month), plain((m.p3 * 100).round(2)), plain(m.pct.round(2)), plain((m.p12 * 100).round(2)),
                m.basis, m.colour)]
    rows.append([live["asof"], round(s["p3"] * 100, 2), round(s["p6"] * 100, 2), round(s["p12"] * 100, 2), "live",
                 s["colour"]])
    return card("score-history-long", "Early-warning score since 1980",
                "Each month scored by a model fitted only on earlier data (re-fitted every January), so the line shows "
                "what the score would have said at the time, apart from later revisions to the claims figures "
                "(largest in 2022).",
                "Blue line: chance that a new event starts within 6 months, for months when none was under way. "
                "Grey line: readings during an event, when the score is no longer a forecast. Warnings have usually "
                "shown 1 to 3 months before an event started, sometimes not at all (see the event table below). "
                "1980–1999 (light): tested with partly "
                "revised data. 2000 on: out of sample. Dot: this week's live run. Shading: blue = events "
                "linked to a recession, orange = scares; hatched = 2020 (the pandemic was not foreseeable from these "
                "inputs and is not used to fit). Strip under the chart: the colour shown, with its hysteresis rule. "
                "Model output, not official statistics.",
                fig, ["date", "score_3m_pct", "score_6m_pct", "score_12m_pct", "basis", "colour"], rows, wide=True)


# ===========================================================================
# Tables
# ===========================================================================
def trigger_rule(r: dict) -> str:
    a, red = r["amber"], r["red"]
    return {
        "sahm": f"Amber at {a:.2f}, red at {red:.2f} point",
        "claims_vs_low": f"Amber at +{a * 100:.0f}%, red at +{red * 100:.0f}%",
        "cont_claims_yoy": f"Amber at +{a * 100:.0f}%, red at +{red * 100:.0f}%; also the Duration watch",
        "yield_curve": f"Amber while inverted {a:.0f}+ months in a row; red for {red:.0f} months after such an inversion ends",
        "nfci": f"Amber above {a:.0f}, red above {red:.1f}",
        "temp_help": f"Amber below 0, red below {red * 100:.0f}%",
        "mfg_surveys": f"Amber below 0 for 3 months; red if the 3-month average is below {red:.0f}",
    }[r["id"]]


TRIGGER_NAMES = {"sahm": "Sahm indicator", "claims_vs_low": "New claims vs. their 52-week low",
                 "cont_claims_yoy": "Continuing claims vs. a year ago", "yield_curve": "Yield curve (10-year minus 3-month)",
                 "nfci": "Financial conditions (NFCI)", "temp_help": "Temporary-help jobs, 6-month change",
                 "mfg_surveys": "Regional factory surveys (Philadelphia and New York Fed)"}


def trigger_value(r: dict) -> str:
    v = r["value"]
    if v is None:
        return "—"
    return {"sahm": lambda: f"{v:.2f} pt", "claims_vs_low": lambda: pct(v), "cont_claims_yoy": lambda: pct(v),
            "yield_curve": lambda: f"{signed(v, 2)} pt ({fmt_month(r['through'] + '-01')})",
            "nfci": lambda: signed(v, 2), "temp_help": lambda: pct(v), "mfg_surveys": lambda: signed(v, 1)}[r["id"]]()


def last_change(r: dict) -> str:
    ch = r["last_change"]
    if not ch:
        return "no change on record"
    when = fmt_month(ch["when"]) if ch["monthly"] else "this week"
    return f"to {ch['to']} (from {ch['from']}), {when}"


def triggers_table(live: dict) -> dict:
    t = live["triggers"]
    rows = []
    for r in t["rows"]:
        name = TRIGGER_NAMES[r["id"]]
        note = {"yield_curve": "long lead, often 12+ months", "nfci": "real-time history only since 2011*"}.get(r["id"], "")
        rows.append({"n": r["order"], "name": name, "note": note, "rule": trigger_rule(r), "value": trigger_value(r),
                     "signal": signal(r["colour"]), "change": last_change(r), "context": r["role"] == "context"})
    return {"panel": [r for r in rows if not r["context"]], "context": [r for r in rows if r["context"]],
            "overall": signal(t["overall"]), "rule": t["rule"]}


def horizons_table(live: dict) -> list[dict]:
    s = live["score"]
    out = []
    for h in ("3", "6", "12"):
        p, base = s[f"p{h}"], s["base_rates"][h]
        d = s["display"][h]
        comment = ""
        if h == "12":
            ratio = p / base
            comment = ("about normal for a 12-month window" if 0.8 <= ratio <= 1.25 else
                       "below the usual level for a 12-month window" if ratio < 0.8 else
                       "above the usual level for a 12-month window")
        out.append({"label": f"Within {h} months", "value": d["text"], "tooltip": d["tooltip"],
                    "base": f"{base * 100:.1f}%".replace(".0%", "%"), "comment": comment})
    return out


# Review WP3 (F3): the nowcast is shown only here, with what testing showed about it
NOWCAST_NOTE = ("In testing it was within 0.2 point of the first release 9 times in 10, about the same as simply "
                "repeating last month's rate; it helped mainly when unemployment was moving fast (2001, 2008–09).")


def forecast_rows(live: dict) -> list[dict]:
    rows = []
    n = live["nowcast"]
    month = pd.Timestamp(n["month"])
    if n.get("status") == "ready":
        v, r = n["value"], n["range_pt"]
        rows.append({"target": "Unemployment rate", "horizon": f"{month:%b %Y} nowcast (next release)",
                     "median": f"{v:.1f}%", "b50": "—", "b80": f"{v - r:.1f}–{v + r:.1f}% (about 80%)",
                     "bench": NOWCAST_NOTE})
    else:
        rows.append({"target": "Unemployment rate", "horizon": f"{month:%b %Y} nowcast (next release)",
                     "median": f"after {fmt_date(n['available_after'])}", "b50": "—",
                     "b80": f"±{n['range_pt']:.1f} pt once available", "bench": NOWCAST_NOTE})
    f = live["fans"]["ur"]
    fm = live.get("fomc")
    nx = (fm or {}).get("next")
    for h in f["horizons"]:
        label = f"{h['horizon']} months ({fmt_month(h['target_period'])})" + (", lower confidence" if h["horizon"] == 12 else "")
        # Review WP3 (F1): at 12 months the middle value is shown muted (no middle line on the chart there) and the
        # FOMC median for next year's Q4 is the benchmark
        twelve = h["horizon"] == 12
        rows.append({"target": "", "horizon": label, "median": f"{h['median']:.1f}%", "median_muted": twelve,
                     "b50": f"{h['q25']:.1f}–{h['q75']:.1f}%", "b80": f"{h['q10']:.1f}–{h['q90']:.1f}%",
                     "bench": f"FOMC Q4 {nx['year']}: {nx['value']:.1f}%" if twelve and nx else ""})
    if fm:
        rows.append({"target": "", "horizon": f"Q4 {fm['year']} average", "median": f"{fm['our_q4_median']:.2f}%",
                     "b50": "", "b80": "",
                     "bench": f"FOMC median {fm['value']:.1f}% ({pd.Timestamp(fm['released']):%b %Y} projections)"})
    c = live["fans"]["cc"]
    for i, h in enumerate(c["horizons"]):
        rows.append({"target": "Continuing claims rate (4-week average)" if i == 0 else "",
                     "horizon": f"{h['horizon']} weeks (week ending {fmt_date(h['target_period'])})",
                     "median": f"{h['median']:.2f}%", "b50": f"{h['q25']:.2f}–{h['q75']:.2f}%",
                     "b80": f"{h['q10']:.2f}–{h['q90']:.2f}%", "bench": ""})
    return rows


def backtest() -> dict | None:
    """Track record from testing (2000–2026): score summary, fan accuracy and coverage, event by event."""
    try:
        res = pd.read_csv(MODEL / "score_results.csv")
        ev_fc = pd.read_csv(MODEL / "forecast_events.csv")
        fe = pd.read_csv(MODEL / "forecast_evaluation.csv")
        events = pd.read_csv(MODEL / "events.csv", dtype={"start_month": str})
    except OSError:
        return None
    r = res[(res.run == "final") & (res.model == "logit")].iloc[0]
    score = {"months": int(r.months_scored), "skill": f"{r.skill_vs_base:+.2f}", "brier": f"{r.brier:.3f}",
             "base": f"{r.brier_base:.3f}", "amber_real": int(r.amber_real), "amber_false": int(r.amber_false),
             "red_real": int(r.red_real), "red_false": int(r.red_false)}
    shown = {("ur", 3): "Unemployment rate, 3 months", ("ur", 6): "Unemployment rate, 6 months",
             ("ur", 12): "Unemployment rate, 12 months (lower confidence)",
             ("cc", 13): "Continuing claims rate, 13 weeks", ("cc", 26): "Continuing claims rate, 26 weeks"}
    # Review WP3 (F2): 80% coverage before and during events (src/model/forecast_regimes.py)
    try:
        reg = pd.read_csv(MODEL / "forecast_evaluation_regimes.csv")
    except OSError:
        reg = pd.DataFrame(columns=["target", "horizon", "regime", "cover80"])

    def regime_cover(t, h, regime):
        r_ = reg[(reg.target == t) & (reg.horizon == h) & (reg.regime == regime)]
        return f"{r_.cover80.iloc[0] * 100:.0f}%" if len(r_) else "—"

    # Review WP4 Part D: forecasts that fail the gate are no longer shown on the site (common.apply_fan_gate)
    shown = {k: v for k, v in shown.items()
             if bool(fe[(fe.target == k[0]) & (fe.horizon == k[1]) & (fe.subset == "2000-on excl. 2020")]
                     .gate_pass.all())}
    fans = []
    for (t, h), label in shown.items():
        g = fe[(fe.target == t) & (fe.horizon == h) & (fe.subset == "2000-on excl. 2020")]
        if len(g):
            g = g.iloc[0]
            fans.append({"label": label, "ratio": f"{g.rmse_ratio:.2f}", "c50": f"{g.cover50 * 100:.0f}%",
                         "c80": f"{g.cover80 * 100:.0f}%", "c80_before": regime_cover(t, h, "before an event"),
                         "c80_during": regime_cover(t, h, "during an event"), "origins": int(g.origins)})
    keep = ev_fc[ev_fc.apply(lambda x: (x.target, int(x.horizon)) in shown, axis=1)]
    rows = []
    for e in events[events.start_month >= "2000-01"].itertuples():
        g = keep[keep.event == e.event]
        inside = {lead: f"{int(g[(g.months_before_start == lead)].inside_80.sum())} of "
                        f"{int((g.months_before_start == lead).sum())}" if (g.months_before_start == lead).any() else "—"
                  for lead in (6, 3)}
        kind = {"recession (pandemic)": "2020 pandemic (not used to fit)"}.get(e.classification, e.classification)
        # Review WP2: size of each event, peak rise in the unemployment rate (events.csv ur_peak_rise_pt)
        rise = f"+{e.ur_peak_rise_pt:.1f} pt" if pd.notna(e.ur_peak_rise_pt) else "—"
        rows.append({"event": f"#{e.event}", "start": fmt_month(e.start_month + "-01"), "kind": kind, "rise": rise,
                     "amber": lead_text(r.get(f"amber_lead_#{e.event}")), "red": lead_text(r.get(f"red_lead_#{e.event}")),
                     "fan6": inside[6], "fan3": inside[3]})
    ur_h = [str(h) for (t, h) in shown if t == "ur"]
    cc_h = [str(h) for (t, h) in shown if t == "cc"]
    fans_shown = (f"of the {len(shown)} forecasts shown on this site (unemployment rate at {', '.join(ur_h[:-1])} and "
                  f"{ur_h[-1]} months, continuing claims rate at {' and '.join(cc_h)} weeks)")
    return {"score": score, "fans": fans, "events": rows, "evidence": evidence(), "fans_shown": fans_shown,
            "false_ambers": ", ".join(fmt_month(x + "-01") for x in str(r.amber_false_starts).split(", ")),
            "false_reds": ", ".join(fmt_month(x + "-01") for x in str(r.red_false_starts).split(", "))}


def evidence() -> dict | None:
    """Review WP1: the tested record with its uncertainty, from data/model/score_skill_summary.csv
    (written by src/model/score_uncertainty.py). One entry per claims basis ("revised", "first_published"),
    already formatted, plus the longest amber-or-red run and the unemployment rate's range over it."""
    try:
        summary = pd.read_csv(MODEL / "score_skill_summary.csv").set_index("basis")
    except OSError:
        return None
    pc = lambda v: f"{v * 100:.0f}%"                       # hit rates: whole percent
    out = {}
    for basis, r in summary.iterrows():
        out[basis] = {"months": int(r.months), "events": int(r.events_in_test), "skill": signed(r.skill, 2),
                      "p05": signed(r.skill_p05, 2), "p95": signed(r.skill_p95, 2),
                      "base_rate": pc(r.event_months / r.months),
                      "red_n": int(r.n_red), "red_hit": pc(r.hit_red), "amber_n": int(r.n_amber),
                      "amber_hit": pc(r.hit_amber), "green_n": int(r.n_green), "green_hit": pc(r.hit_green)}
    # The longest run of months at amber or red (same on both rows) and the unemployment rate over it
    first = summary.iloc[0]
    start = pd.Timestamp(first.longest_elevated_run_start + "-01")
    end = pd.Timestamp(first.longest_elevated_run_end + "-01")
    ur = fred("UNRATE")
    during = ur[(ur.index >= start) & (ur.index <= end)]
    out["run"] = {"months": int(first.longest_elevated_run_months), "start": f"{start:%B %Y}", "end": f"{end:%B %Y}",
                  "ur_low": f"{during.min():.1f}", "ur_high": f"{during.max():.1f}"}
    return out


# Review WP7 (P3, P6): "Three things to know" and "How to use the colours". The approved wording rounds the tested
# hit rates (data/model/score_skill_summary.csv, claims as revised) to "1 in N". Each phrase is used only while the
# file still supports it; if a re-fit moves a rate outside its range, the plain percentage is shown instead.
HIT_PHRASES = {            # colour: (approved phrase, lowest and highest hit rate it fits)
    "green": ("about 1 time in 15", 1 / 17, 1 / 13.5),
    "amber": ("about 1 time in 4", 0.21, 0.30),
    "red": ("about half the time", 0.42, 0.58),
}


def hit_phrase(colour: str, rate: float) -> str:
    phrase, lo, hi = HIT_PHRASES[colour]
    return phrase if lo <= rate <= hi else f"in {rate * 100:.0f}% of months"


def most_years(start: pd.Timestamp, end: pd.Timestamp) -> str:
    """'2023–2025' for a run from Nov 2022 to Dec 2025: a first or last year counts only if the run covers more
    than half of it (shared with the Overview score chart note)."""
    first = start.year + (start.month > 6)
    last = end.year - (end.month < 7)
    return f"{first}–{last}" if last > first else str(first)


def colour_guide() -> dict | None:
    """The two cards' variable parts, from score_skill_summary.csv (None if the file is missing: cards not shown)."""
    try:
        r = pd.read_csv(MODEL / "score_skill_summary.csv").set_index("basis").loc["revised"]
    except (OSError, KeyError):
        return None
    green, amber, red = (hit_phrase(c, r[f"hit_{c}"]) for c in ("green", "amber", "red"))
    start = pd.Timestamp(r.longest_elevated_run_start + "-01")
    end = pd.Timestamp(r.longest_elevated_run_end + "-01")
    cap = lambda s: s[0].upper() + s[1:]
    return {
        "three": ["It is a stress alert, not a recession forecast: about half of past alerts were short scares.",
                  f"It sorts months well but is not a precise probability: red has been followed by an event {red}, "
                  f"green {green}.",
                  f"It was amber or red for most of {most_years(start, end)} without a recession."],
        "rows": [
            ("Early-warning score green", f"An event followed within 6 months {green}", "Routine weekly check"),
            ("Score amber", cap(amber), "Look at the weekly claims figures each Thursday; re-read the drivers"),
            ("Score red", f"{cap(red)}; about 1 time in 5 an event tied to a recession",
             "Treat as “prepare”: review assumptions that depend on stable unemployment; it is not a forecast "
             "of recession"),
            ("New claims amber or red (Job Losses)", "The thing the score warns about has begun",
             "Expect more new unemployment claims within 1 to 3 months"),
            ("Duration watch amber or red", "Durations have usually lengthened within a year",
             "Expect longer claims, peaking a year or more after layoffs peak"),
            ("Confirmation triggers red", "The event has started",
             "The what-if paths on each chart show how 2001 and 2008 unfolded from today's level"),
        ],
    }


def live_record() -> str:
    """Review WP4 Part C: the live scorecard sentence, from data/model/live_scorecard.csv (src/model/live_scorecard.py)."""
    try:
        card = pd.read_csv(MODEL / "live_scorecard.csv")
    except OSError:
        card = pd.DataFrame(columns=["asof", "colour", "during_event", "outcome_known", "event_started_within_6m"])
    if len(card):
        card["during_event"] = card.during_event.astype(str).eq("True")
        card["outcome_known"] = card.outcome_known.astype(str).eq("True")
    judged = card[card.outcome_known & ~card.during_event] if len(card) else card
    if judged.empty:
        first = (pd.Timestamp(card["asof"].min()) if len(card) else pd.Timestamp("2026-11-08")) + pd.DateOffset(months=6)
        return f"No live reading is old enough to judge yet; the first will be in {first:%B %Y}."
    hit = judged.event_started_within_6m.astype(str).eq("True")
    n = lambda c: int((judged.colour == c).sum())
    k = lambda c: int(((judged.colour == c) & hit).sum())
    return (f"{len(judged)} live readings are old enough to judge: {n('green')} green ({k('green')} followed by an event "
            f"within 6 months), {n('amber')} amber ({k('amber')}), {n('red')} red ({k('red')}).")


def benchmark_sentence() -> str | None:
    """Review WP9 C12: how much of the score's tested skill one input gives (data/model/score_simple_benchmarks.csv,
    written by src/model/score_simple_benchmarks.py; revised claims, 2000-2026). The approved words "about half" and
    "almost none" are used only while the file supports them (claims-only skill 35-65% of the full model's; rule panel
    below +0.05); otherwise the sentence gives the numbers without those words."""
    try:
        b = pd.read_csv(MODEL / "score_simple_benchmarks.csv")
    except OSError:
        return None
    rv = b[b.basis == "revised"].set_index("model").skill
    if not {"claims_only", "full", "rule_panel"} <= set(rv.index):
        return None
    x, y, rule = rv["claims_only"], rv["full"], rv["rule_panel"]
    rule_words = "almost none" if rule < 0.05 else f"a skill of {signed(rule, 2)}"
    if y > 0 and 0.35 <= x / y <= 0.65:      # the approved wording
        return (f"Most of the score's information comes from one input. Tested the same way, new claims against their "
                f"past-year low alone gives about half the full model's skill ({signed(x, 2)} against "
                f"{signed(y, 2)}); the confirmation triggers used as a forecast give {rule_words}.")
    return (f"Tested the same way, new claims against their past-year low alone gives a skill of {signed(x, 2)}, "
            f"against {signed(y, 2)} for the full model; the confirmation triggers used as a forecast give "
            f"{rule_words}.")


def weights_table(live: dict) -> dict:
    s = live["score"]
    rows = []
    for c in sorted(s["contributions"], key=lambda c: -abs(c["contribution"])):
        name, fmt = INPUTS.get(c["input"], (c["input"], lambda v: f"{v:.2f}"))
        rows.append({"name": name, "value": "—" if c["value"] is None else fmt(c["value"]),
                     "weight": f"{c['weight']:.2f}", "contribution": signed(c["contribution"], 2)})
    total = s["intercept"] + sum(c["contribution"] for c in s["contributions"])
    return {"rows": rows, "intercept": signed(s["intercept"], 2), "total": signed(total, 2),
            "p": f"{s['p6'] * 100:.1f}%"}


# ===========================================================================
def build(built: datetime) -> dict:
    m = model_output(built)
    live = m["live"]
    if live is None:
        return {"available": False, "note": m["note"], "charts": []}
    s = live["score"]
    d6 = s["display"]["6"]
    chart = history_chart(live, built)
    first_live = pd.Timestamp(live["asof"]) + pd.DateOffset(months=3)
    return {
        "available": True, "note": m["note"], "asof": asof_line(live), "asof_date": fmt_date(live["asof"]),
        "signal": signal(s["colour"]), "value": d6["text"], "tooltip": d6["tooltip"], "words": d6["words"],
        "charts": [chart] if chart else [],
        "horizons": horizons_table(live),
        "triggers": triggers_table(live),
        "forecasts": forecast_rows(live),
        "backtest": backtest(),
        "weights": weights_table(live),
        "benchmark": benchmark_sentence(),
        "model_year": live["model_year"],
        "first_live": f"{first_live:%B %Y}",
        "thresholds": s["thresholds"],
        "guide": colour_guide(),
        "event": event_banner(live),
        "live_record": live_record(),
    }
