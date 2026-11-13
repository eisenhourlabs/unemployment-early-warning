"""
Shared building blocks for the Unemployment Watch site (used by every page module).

  - reading data files (FRED series, DOL claims)
  - number and date formats, so every number on the site looks the same
  - small statistics (percentile, streaks, "highest since")
  - recession shading from NBER dates
  - chart builders: line_chart, weekly_claims_chart, bars_with_average, seasonal_chart

Each chart builder returns a "card": a dict with the chart's title, one-line "why it matters", footer,
the Plotly figure, and the table offered by its Download CSV button.
"""

import json
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
DOL = PROCESSED / "dol"

# ---------------------------------------------------------------------------
# Look. One accent color for the main series, greys for comparisons.
# Red / amber / green are reserved for the Phase 3 risk signal, so they are not used here.
# site.js swaps these for the dark-mode versions when the reader turns dark mode on (by each trace's "role").
# ---------------------------------------------------------------------------
ACCENT = "#2a78d6"
FAINT = "rgba(42, 120, 214, 0.35)"   # the accent, see-through: weekly values behind the 4-week average
GREYS = ["#6d6c67", "#93928c", "#b9b8b2"]   # comparison years: most recent (darkest) to oldest (lightest)
RECESSION_FILL = "rgba(120, 120, 120, 0.16)"
AXIS = "#c8c7c2"
# Phase 3 risk signal: the only place green / amber / red appear. Always shown with a text label and an icon,
# never colour alone. site.js and style.css hold the matching dark-mode versions.
SIGNAL = {"green": "#1f7a3a", "amber": "#b76e00", "red": "#c0392b"}
SIGNAL_ICON = {"green": "●", "amber": "▲", "red": "■"}
SIGNAL_LABEL = {"green": "Green", "amber": "Amber", "red": "Red"}
MODEL = ROOT / "data" / "model"
MODEL_MAX_AGE_DAYS = 9          # a weekly run older than this shows a "not updated" note


# ===========================================================================
# Reading data
# ===========================================================================
def fred(series_id: str) -> pd.Series:
    """A FRED series as a pandas Series indexed by date, with blank values dropped.
    SA claims series run on through any weeks estimated from state filings while DOL's release is delayed."""
    df = pd.read_csv(PROCESSED / f"{series_id}.csv", parse_dates=["date"])
    s = df.set_index("date")["value"].dropna()
    return with_estimates(series_id, s) if series_id in ESTIMATED_FRED else s


# ---------------------------------------------------------------------------
# Shutdown fallback (Phase 4 stage 4c): while DOL's weekly release is delayed, the claims charts and tiles show the
# weeks after the latest official week as estimates from the state filings (src/fetchers/dol_state_fallback.py),
# labelled ESTIMATE_SOURCE and drawn like preliminary weeks (dashed, hollow markers). Nothing changes in normal times.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(ROOT / "src" / "fetchers"))
import dol_state_fallback as fallback  # noqa: E402
sys.path.append(str(ROOT / "src" / "model"))          # appended: site modules keep priority
from fomc_marker import fomc_next  # noqa: E402  (review WP3; pandas only)

ESTIMATE_SOURCE = "estimate (release delayed)"
ESTIMATED_FRED = {"ICSA": ("ic", None), "IC4WSA": ("ic", 4), "CCSA": ("cc", None), "CC4WSA": ("cc", 4)}
_EST = None


def estimates() -> pd.DataFrame:
    """Open estimates (weeks after the latest official week), read once per build."""
    global _EST
    if _EST is None:
        _EST = fallback.active_estimates()
    return _EST


def with_estimates(series_id: str, s: pd.Series) -> pd.Series:
    est = estimates()
    n = fallback.preview_delay()
    if est.empty and not n:
        return s
    measure, window = ESTIMATED_FRED[series_id]
    s = fallback.cut_official(s, n)
    e = est[est.measure == measure].set_index("week_ended").estimate_sa.astype(float).round(-3)   # as DOL publishes
    if window is None:
        return pd.concat([s, e]).sort_index()
    base = fred("ICSA" if measure == "ic" else "CCSA")            # weekly SA, official + estimates
    avg = base.rolling(window).mean()
    return pd.concat([s, avg.reindex(e.index)]).sort_index()


def overlay_claims_table(df: pd.DataFrame) -> pd.DataFrame:
    """claims_weekly() with estimated weeks added: SA levels and rates (on the latest covered employment), 4-week
    averages, and the source label 'estimate (release delayed), N of 53 areas'."""
    est = estimates()
    n = fallback.preview_delay()
    if est.empty and not n:
        return df
    df = df.set_index("week_ended")
    groups = {"ic": (["ic_nsa", "ic_sa", "ic_sa_4wk", "ic_rate_sa", "ic_rate_nsa", "ic_rate_sa_4wk", "ic_rate_nsa_4wk"],
                     "source_initial", "ic_sa"),
              "cc": (["cc_sa", "cc_sa_4wk", "cc_rate_sa", "cc_rate_nsa", "cc_rate_sa_4wk", "cc_rate_nsa_4wk",
                      "iur_sa_published"], "source_continued", "cc_sa")}
    ce = df.covered_employment.dropna().iloc[-1]
    for measure, (cols, src, level) in groups.items():
        official = df[level].dropna()
        cut = official.index.difference(fallback.cut_official(official, n).index)
        df.loc[cut, [c for c in cols if c in df] + [src]] = None           # preview: pretend these are not out yet
        for r in est[est.measure == measure].itertuples():
            df.loc[r.week_ended, level] = round(float(r.estimate_sa), -3)        # as DOL publishes
            df.loc[r.week_ended, f"{measure}_rate_sa"] = r.estimate_sa / ce * 100
            if measure == "ic":
                df.loc[r.week_ended, "ic_nsa"] = round(float(r.estimate_nsa), -3)
            df.loc[r.week_ended, src] = f"{ESTIMATE_SOURCE}, {int(r.areas_reported)} of 53 areas"
        df = df.sort_index()
        for r in est[est.measure == measure].itertuples():
            for col in (level, f"{measure}_rate_sa"):
                last4 = df[col].loc[:r.week_ended].dropna().tail(4)
                if len(last4) == 4:
                    df.loc[r.week_ended, col.replace("_sa", "_sa_4wk") if col == level else col + "_4wk"] = last4.mean()
    df["covered_employment"] = df.covered_employment.ffill()
    for col in ["ic_rate_sa", "ic_rate_sa_4wk"]:
        df[col + "_per10k"] = df[col] * 100
    return df.reset_index()


def fred_metadata() -> pd.DataFrame:
    return pd.read_csv(PROCESSED / "_metadata.csv").set_index("series_id")


def claims_weekly() -> pd.DataFrame:
    """DOL weekly claims rates (from 1971) joined with the claims levels and their source flags."""
    rates = pd.read_csv(DOL / "claims_rates_weekly.csv", parse_dates=["week_ended"])
    levels = pd.read_csv(DOL / "national_weekly.csv", parse_dates=["week_ended"],
                         usecols=["week_ended", "ic_nsa", "ic_sa", "ic_sa_4wk", "cc_sa", "cc_sa_4wk"])
    df = rates.merge(levels, on="week_ended", how="left")
    # The initial claims rate is stored as a percent of covered employment. The site shows it
    # per 10,000 covered workers (percent x 100), e.g. 0.123% -> 12.3 per 10,000 (decision 2026-11-07).
    for col in ["ic_rate_sa", "ic_rate_sa_4wk"]:
        df[col + "_per10k"] = df[col] * 100
    return overlay_claims_table(df)


# Review WP2 (2026-11): wording changes in src/model/live.py, applied here as well so a site rebuilt from a
# live_latest.json written before the change (the "Publish site" run does not re-run live.py) shows the new words.
WORDS_NOTE = ("In testing, readings this high were followed by a claims jump or unemployment rise roughly half the "
              "time.")
OLD_RULE_TAIL, NEW_RULE_TAIL = "another panel trigger is", "another trigger that counts toward the status is"


def reword_live(live: dict) -> None:
    """In place: "More likely than not" -> "High", the verbal-band tooltip sentence, the comparison label and the
    trigger-rule wording."""
    s = live.get("score") or {}
    displays = list((s.get("display") or {}).values()) + [(s.get("previous") or {}).get("display") or {}]
    for d in displays:
        if d.get("text") == "More likely than not":
            d["text"] = "High"
        if d.get("words") and WORDS_NOTE not in d.get("tooltip", ""):
            d["tooltip"] = f"{d.get('tooltip', '')}. {WORDS_NOTE}"
    if s.get("compare_label") == "vs. last week's backtest score":
        s["compare_label"] = "vs. last week's tested-on-history score"
    t = live.get("triggers") or {}
    if "rule" in t:
        t["rule"] = t["rule"].replace(OLD_RULE_TAIL, NEW_RULE_TAIL)


def add_fomc_next(live: dict) -> None:
    """In place (review WP3): a live_latest.json written before fomc.next existed gets it from the same function
    live.py now uses (src/model/fomc_marker.py), on the UNRATEMD file on disk. The next live run writes it itself."""
    fm = live.get("fomc")
    if not fm or "next" in fm or "ur" not in (live.get("fans") or {}):
        return
    try:
        s = pd.read_csv(PROCESSED / "UNRATEMD.csv", parse_dates=["date"]).set_index("date")["value"]
    except (OSError, KeyError, ValueError):
        return
    nxt = fomc_next(s, int(fm["year"]), live["fans"]["ur"])
    if nxt:
        fm["next"] = nxt


def model_output(built) -> dict:
    """The live model result set (data/model/live_latest.json, from src/model/live.py), with a status note.

    Missing or stale output never breaks the build: {"live": None, "note": ...} when the file is missing or
    unreadable; the last good values plus a note when it is older than MODEL_MAX_AGE_DAYS."""
    import json as _json
    path = MODEL / "live_latest.json"
    try:
        live = _json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"live": None, "note": "Early-warning score not available: the model output is missing."}
    reword_live(live)
    add_fomc_next(live)
    from zoneinfo import ZoneInfo
    today = pd.Timestamp(pd.Timestamp(built).tz_convert(ZoneInfo("America/Chicago")).date())
    asof = pd.Timestamp(live["asof"])
    notes = []
    # 1. The last model run failed (data/model/live_status.json, written by live.py --archive): say so at once.
    try:
        status = _json.loads((MODEL / "live_status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        status = {}
    if status.get("ok") is False and status.get("last_attempt", "") > live["asof"]:
        notes.append(f"Score not updated since {fmt_date(asof)}: the model run of {fmt_date(status['last_attempt'])} "
                     "failed. The values shown are from the last good run.")
    elif (today - asof).days > MODEL_MAX_AGE_DAYS:
        notes.append(f"Score not updated since {fmt_date(asof)}: the weekly model run has not completed since then.")
    # 2. A release is past due and its data have not arrived (shutdowns, delays): the score keeps its last value.
    claims_delayed = False
    now_ct = pd.Timestamp(built).tz_convert(ZoneInfo("America/Chicago"))
    thursday = today - pd.Timedelta(days=(today.weekday() - 3) % 7)          # the latest Thursday, today included
    if thursday == today and (now_ct.hour, now_ct.minute) < (7, 30):        # released 8:30 am ET = 7:30 am CT
        thursday -= pd.Timedelta(days=7)
    expected_week = thursday - pd.Timedelta(days=5)                           # its report covers the week to Saturday
    try:   # official weeks only (fred() would include weeks estimated from state filings)
        raw = pd.read_csv(PROCESSED / "ICSA.csv", parse_dates=["date"]).set_index("date")["value"].dropna()
        latest_week = fallback.cut_official(raw).index[-1]
    except OSError:
        latest_week = expected_week
    if latest_week < expected_week:
        claims_delayed = True
        if live.get("provisional"):
            areas = min((e["areas_reported"] for e in live.get("estimated_claims", [])), default=53)
            notes.append(f"Release delayed: the weekly claims report due {fmt_date(thursday)} has not been published. "
                         f"Provisional: the score and forecasts use claims estimated from state filings ({areas} of 53 "
                         "areas reported); official figures will replace them.")
        else:
            notes.append(f"Release delayed: the weekly claims report due {fmt_date(thursday)} has not been published; "
                         "the score keeps its last value.")
    n = live.get("nowcast") or {}
    if n.get("release_date") and today > pd.Timestamp(n["release_date"]):
        try:
            latest_month = fred("UNRATE").index[-1]
        except OSError:
            latest_month = pd.Timestamp(n["month"])
        if latest_month < pd.Timestamp(n["month"]):
            notes.append(f"Release delayed: the {pd.Timestamp(n['month']):%B} jobs report (scheduled "
                         f"{fmt_date(n['release_date'])}) has not been published. Estimate: the unemployment-rate "
                         "nowcast is our estimate, not a published value.")
    return {"live": live, "note": " ".join(notes), "claims_delayed": claims_delayed}


def model_csv(name: str, date_col: str) -> pd.DataFrame | None:
    """A model display file (score_display_weekly.csv etc.), or None if missing."""
    path = MODEL / name
    return pd.read_csv(path, parse_dates=[date_col]) if path.exists() else None


def asof_line(live: dict) -> str:
    """'As of Nov 8, 2026: initial claims through week ending Oct 31, 2026; unemployment rate through Oct 2026'"""
    i = live["inputs"]
    return (f"As of {fmt_date(live['asof'])}: claims through week ending {fmt_date(i['initial_claims_week'])} "
            f"(continuing claims {fmt_date(i['continuing_claims_week'])}); unemployment rate through "
            f"{fmt_month(i['unemployment_month'])}")


# Duration watch (review WP5 / WP7): the band of continuing claims vs. a year ago (trigger 4's value v).
# A falling reading shows green with the word "Falling" (Troy's decision 6).
def duration_watch(v: float) -> dict:
    """{'word': 'Falling' | 'Steady' | 'Rising' | 'Rising fast', 'colour': green / amber / red} for a value v
    (0.10 = continuing claims' 4-week average 10% above the same average 52 weeks earlier)."""
    if v < 0:
        return {"word": "Falling", "colour": "green", "band": "falling"}
    if v < 0.10:
        return {"word": "Steady", "colour": "green", "band": "green"}
    if v < 0.20:
        return {"word": "Rising", "colour": "amber", "band": "amber"}
    return {"word": "Rising fast", "colour": "red", "band": "red"}


def signal(colour: str) -> dict:
    """Label, icon and CSS class for a colour (green / amber / red)."""
    return {"colour": colour, "label": SIGNAL_LABEL.get(colour, "—"), "icon": SIGNAL_ICON.get(colour, "")}


def add_colour_band(fig: go.Figure, dates_: pd.Series, colours: pd.Series, end) -> None:
    """A thin strip under the plot showing the displayed colour over time (one rectangle per run of a colour).
    The y-axis is moved up (domain 0.1-1) so the strip never covers the line."""
    runs, start, prev = [], None, None
    for d, c in zip(dates_, colours):
        if c != prev:
            if prev is not None:
                runs.append((start, d, prev))
            start, prev = d, c
    if prev is not None:
        runs.append((start, pd.Timestamp(end), prev))
    for a, b, c in runs:
        fig.add_shape(type="rect", xref="x", yref="paper", x0=pd.Timestamp(a).strftime("%Y-%m-%d"),
                      x1=pd.Timestamp(b).strftime("%Y-%m-%d"), y0=0, y1=0.055, line_width=0,
                      fillcolor=SIGNAL[c], layer="above", name=f"sig-{c}")
    fig.update_yaxes(domain=[0.1, 1])
    fig.update_xaxes(anchor="free", position=0)   # date labels stay below the strip, not under it


def add_fan(fig: go.Figure, f: dict, mult: float, fmt: str, unit: str, period_label, low_conf: int | None = None,
            labels_below: bool = False, median_until: int | None = None) -> str:
    """Forecast fan from the latest published level (live_latest.json 'fans' entry): 80% band (light), 50% band
    (dark), dashed middle line with a dot at each horizon, joined by straight lines; a short label above each 80%
    band. mult: display scale (e.g. 100 for 'per 10,000'); fmt: number format ('.1f'); unit: '%' or '';
    period_label(h) -> text for the hover, e.g. 'Jan 2027 (3 months)'. labels_below: put the horizon labels under the
    band (where reference-line labels sit at the chart's right edge above it). All traces carry meta.today / meta.forecast,
    so site.js shows them only when the time range includes today. Returns the last forecast date.
    median_until (review WP3): draw the middle line only to this horizon (e.g. 6 months); later horizons show the
    bands only, with their hover on an invisible marker at the 50% band's mid-point."""
    hz = f["horizons"]
    x = [f["latest_period"]] + [h["target_period"] for h in hz]
    col = lambda k: [f["level"] * mult] + [h[k] * mult for h in hz]
    beyond = [h for h in hz if median_until is not None and h["horizon"] > median_until]
    today = {"today": True, "forecast": True}
    for lo, hi, label, alpha in [("q10", "q90", "Forecast: 80% band", 0.14), ("q25", "q75", "Forecast: 50% band", 0.30)]:
        fig.add_trace(go.Scatter(x=x, y=col(hi), mode="lines", line=dict(width=0), showlegend=False,
                                 hoverinfo="skip", meta={"role": "fan-edge", **today}))
        fig.add_trace(go.Scatter(x=x, y=col(lo), mode="lines", line=dict(width=0), fill="tonexty",
                                 fillcolor=f"rgba(42, 120, 214, {alpha})", name=label, hoverinfo="skip",
                                 meta={"role": "fan", "alpha": alpha, **today}))
    lev = f["level"] * mult
    mid = [h for h in hz if h not in beyond]               # horizons that keep a middle value
    fig.add_trace(go.Scatter(
        x=x[:1 + len(mid)], y=col("median")[:1 + len(mid)], name="Forecast: middle line", mode="lines+markers",
        line=dict(color=ACCENT, width=2, dash="dash"), marker=dict(size=[0] + [7] * len(mid), color=ACCENT),
        customdata=[["latest published", lev, lev, lev, lev]]
                   + [[period_label(h), h["q10"] * mult, h["q25"] * mult, h["q75"] * mult, h["q90"] * mult] for h in mid],
        hovertemplate=(f"%{{customdata[0]}}: middle %{{y:{fmt}}}{unit}, 50% band %{{customdata[2]:{fmt}}}–"
                       f"%{{customdata[3]:{fmt}}}{unit}, 80% band %{{customdata[1]:{fmt}}}–%{{customdata[4]:{fmt}}}{unit}"
                       "<extra>Forecast</extra>"),
        meta={"role": "main", **today}))
    if beyond:
        fig.add_trace(go.Scatter(
            x=[h["target_period"] for h in beyond], y=[(h["q25"] + h["q75"]) / 2 * mult for h in beyond],
            mode="markers", marker=dict(size=12, opacity=0), showlegend=False, name="Forecast: range only",
            customdata=[[period_label(h), h["q10"] * mult, h["q25"] * mult, h["q75"] * mult, h["q90"] * mult]
                        for h in beyond],
            hovertemplate=(f"%{{customdata[0]}}: 50% band %{{customdata[2]:{fmt}}}–%{{customdata[3]:{fmt}}}{unit}, "
                           f"80% band %{{customdata[1]:{fmt}}}–%{{customdata[4]:{fmt}}}{unit}<extra>Forecast</extra>"),
            meta={"role": "fan-hover", **today}))
    short = "mo" if f["frequency"] == "M" else "wk"
    side, edge = ("bottom", "q10") if labels_below else ("top", "q90")
    fig.add_trace(go.Scatter(
        x=x[1:], y=[h[edge] * mult for h in hz], mode="text", showlegend=False, hoverinfo="skip",
        text=[f"{h['horizon']} {short}" + (" (lower confidence)" if h["horizon"] == low_conf else "") for h in hz],
        textposition=[f"{side} center"] * (len(hz) - 1) + [f"{side} left"], textfont=dict(size=11),
        meta={"role": "label", **today}))
    return x[-1]


def add_whatif(fig: go.Figure, stress: dict, mult: float, fmt: str, unit: str) -> str:
    """The 2001-type and 2008-type what-if paths from today's level (dashed greys), hidden until the reader ticks
    "Show what-if paths". Returns the last date they reach."""
    last = stress["latest_period"]
    for i, (label, pts) in enumerate(stress["scenarios"].items()):
        kind = label.split(" ")[0]
        fig.add_trace(go.Scatter(
            x=[p["period"] for p in pts], y=[p["level"] * mult for p in pts], mode="lines", visible=False,
            name=f"What-if: a {kind} downturn starting now (not a forecast)",
            line=dict(color=GREYS[i], width=1.8, dash="dashdot" if i else "dash"),
            hovertemplate=f"What-if, {kind}: %{{y:{fmt}}}{unit}<extra></extra>",
            meta={"role": f"grey{i}", "whatif": True, "today": True, "forecast": True}))
        last = max(last, pts[-1]["period"])
    return last


def with_outlook(c: dict, fig: go.Figure, ahead: str | None, whatif_ahead: str | None, notes: list[str],
                 footer: str) -> dict:
    """Put a chart's Phase 3 elements back into its card (figure, x-axis reach, what-if toggle, notes, footer).
    ahead: last forecast date (None for a chart with what-if paths but no fan)."""
    fig.update_layout(showlegend=True)
    c["figure"] = json.loads(fig.to_json())
    if ahead:
        c["ahead"] = (pd.Timestamp(ahead) + pd.Timedelta(days=20)).strftime("%Y-%m-%d")
    if whatif_ahead:
        c["whatif"], c["whatif_ahead"] = True, whatif_ahead
    c["notes"] = notes
    c["footer"] += footer
    return c


WHATIF_FOOTER = (" What-if paths repeat the 2001 and 2008 recessions from today's level; they are not forecasts. "
                 "Forecast elements appear only when the time range includes today.")


def is_preliminary(source) -> bool:
    """True for weeks still coming from the news release (not yet in DOL's official ETA 539 report), and for weeks
    estimated from state filings while the release is delayed (both are drawn dashed with hollow markers)."""
    return isinstance(source, str) and (source.startswith("news release") or is_estimate(source))


def is_estimate(source) -> bool:
    return isinstance(source, str) and source.startswith(ESTIMATE_SOURCE)


def prelim_label(source) -> str:
    """'news release, advance' -> 'preliminary (advance)'; an estimate keeps its own label (with the area count)."""
    if is_estimate(source):
        return source
    return "preliminary (" + source.split(",")[1].strip() + ")" if is_preliminary(source) else "official"


def hollow_note(sources) -> str:
    """Footer sentence for the hollow markers; says so when some weeks are estimates."""
    if any(is_estimate(s) for s in sources):
        return (" Hollow markers: preliminary, or estimated from state filings while DOL's weekly release is delayed "
                "(official figures will replace them).")
    return " Hollow markers: preliminary."


def tail_name(sources) -> str:
    """Legend name for the dashed tail: preliminary weeks, estimated weeks, or both."""
    sources = [s for s in sources if is_preliminary(s)]
    est = any(is_estimate(s) for s in sources)
    news = any(not is_estimate(s) for s in sources)
    return ("Preliminary / estimate (release delayed)" if est and news
            else "Estimate (release delayed)" if est else "Preliminary (news release)")


# ===========================================================================
# Formatting helpers
# ===========================================================================
def fmt_date(d) -> str:
    """Nov 1, 2026"""
    d = pd.Timestamp(d)
    return f"{d:%b} {d.day}, {d.year}"


def fmt_month(d) -> str:
    """Oct 2026"""
    return f"{pd.Timestamp(d):%b %Y}"


def fmt_claims(x) -> str:
    """228000 -> '228,000'"""
    return f"{x:,.0f}"


def ordinal(n: int) -> str:
    """1 -> '1st', 62 -> '62nd', 13 -> '13th'"""
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def fmt_change(delta: float, decimals: int, unit: str = "") -> str:
    """Signed change, or 'unchanged' when it rounds to zero. Uses a real minus sign."""
    rounded = round(delta, decimals)
    if rounded == 0:
        return "unchanged"
    sign = "+" if rounded > 0 else "−"
    return f"{sign}{abs(rounded):,.{decimals}f}{unit}"


# ===========================================================================
# Statistics
# ===========================================================================
def percentile_rank(values: pd.Series, latest: float) -> int:
    """Empirical percentile: the share of all observations (full history) at or below the latest value.

    Example: 62 means 62% of all weeks since 1971 had a rate at or below this week's.
    """
    values = values.dropna()
    return int(round(100 * (values <= latest).mean()))


def percentile_text(values: pd.Series, latest: float, since) -> str:
    """'62nd percentile since 1971', or 'Lowest since 1971 (start of data)' at the extremes, because
    '0th percentile' reads oddly. Never 'record low': the data simply start in that year."""
    values = values.dropna()
    if latest <= values.min():
        return f"Lowest since {since} (start of data)"
    if latest >= values.max():
        return f"Highest since {since} (start of data)"
    pct = percentile_rank(values, latest)
    if pct < 1:
        return f"Below the 1st percentile since {since}"
    if pct > 99:
        return f"Above the 99th percentile since {since}"
    return f"{ordinal(pct)} percentile since {since}"


def value_on_or_before(s: pd.Series, when) -> tuple:
    """(date, value) of the last observation on or before `when` (used for 'a year ago')."""
    earlier = s[s.index <= pd.Timestamp(when)]
    return (earlier.index[-1], earlier.iloc[-1]) if len(earlier) else (None, None)


def vs_month(s: pd.Series, wanted, missing_word: str) -> tuple:
    """Value to compare against for a monthly tile: the wanted month, or the last month before it if the
    wanted month has no value. Returns (value, label), e.g. (4.4, 'Sep 2025 (Oct 2025 not collected)')."""
    wanted = pd.Timestamp(wanted)
    used_date, value = value_on_or_before(s, wanted)
    label = fmt_month(used_date)
    if used_date != wanted:
        label += f" ({fmt_month(wanted)} {missing_word})"
    return value, label


def last_time_as_extreme(s: pd.Series) -> tuple:
    """For a rise: when was a value at least this high last seen? For a fall: at least this low?

    Returns (direction, date) where date is None if it has never been this high/low in the data.
    direction is 'highest' or 'lowest', or (None, None) if the latest value didn't move.
    """
    latest, prior = s.iloc[-1], s.iloc[-2]
    if latest == prior:
        return None, None
    history = s.iloc[:-1]
    if latest > prior:
        matches = history[history >= latest]
        return "highest", (matches.index[-1] if len(matches) else None)
    matches = history[history <= latest]
    return "lowest", (matches.index[-1] if len(matches) else None)


def streak(s: pd.Series) -> int:
    """Number of consecutive moves in the same direction ending at the latest value (+ up, − down)."""
    diffs = s.diff().dropna()
    if diffs.empty or diffs.iloc[-1] == 0:
        return 0
    up = diffs.iloc[-1] > 0
    n = 0
    for d in reversed(diffs.tolist()):
        if (d > 0) == up and d != 0:
            n += 1
        else:
            break
    return n if up else -n


def year_ago_change_pct(s: pd.Series) -> pd.Series:
    """Weekly series: percent change vs. the same week a year earlier (52 weeks = 364 days back)."""
    year_before = s.copy()
    year_before.index = year_before.index + timedelta(days=364)   # move each value forward one year
    return (100 * (s / year_before - 1)).dropna()


# ===========================================================================
# Recession shading (NBER dates from FRED series USREC)
# ===========================================================================
def recession_bands() -> list[dict]:
    """Turn the monthly 0/1 USREC series into a list of {start, end} date ranges."""
    usrec = fred("USREC")
    bands, start = [], None
    for month, flag in usrec.items():
        if flag == 1 and start is None:
            start = month
        if flag == 0 and start is not None:
            bands.append({"start": start, "end": month})   # shade up to the start of the first non-recession month
            start = None
    if start is not None:  # a recession still under way at the end of the data
        bands.append({"start": start, "end": usrec.index[-1] + pd.offsets.MonthBegin(1)})
    return bands


BANDS = None   # filled the first time a chart needs them


def add_recession_shading(fig: go.Figure, first_date) -> None:
    """Grey bands behind the lines for each recession after the chart's first date."""
    global BANDS
    if BANDS is None:
        BANDS = recession_bands()
    for b in BANDS:
        if b["end"] < pd.Timestamp(first_date):
            continue
        fig.add_vrect(x0=b["start"].strftime("%Y-%m-%d"), x1=b["end"].strftime("%Y-%m-%d"),
                      fillcolor=RECESSION_FILL, line_width=0, layer="below", name="recession")


# ===========================================================================
# Chart building blocks
# ===========================================================================
def plain(values) -> list:
    """Plain Python list with None for blanks. Plotly would otherwise pack number columns into a
    binary format that site.js can't read point by point (it needs the numbers to rescale y-axes)."""
    return [None if pd.isna(v) else (float(v) if not isinstance(v, str) else v) for v in values]


def dates(index) -> list:
    return [d.strftime("%Y-%m-%d") for d in index]


def base_layout(fig: go.Figure, y_title: str, hover_format: str, legend: bool = True) -> None:
    """Settings every time-series chart shares."""
    fig.update_layout(
        margin=dict(l=60, r=16, t=8, b=36),
        height=320,
        hovermode="x unified",               # one tooltip listing every line at the hovered date
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(size=12)),
        paper_bgcolor="#fcfcfb",
        plot_bgcolor="#fcfcfb",
        font=dict(family="system-ui, -apple-system, Segoe UI, Roboto, sans-serif", size=12, color="#52514e"),
        dragmode="zoom",
        bargap=0.15,
    )
    fig.update_xaxes(type="date", showgrid=False, hoverformat=hover_format, linecolor=AXIS,
                     ticks="outside", tickcolor=AXIS)
    # The y-axis can't be dragged: site.js rescales it to whatever dates are visible.
    fig.update_yaxes(title_text=y_title, gridcolor="#e8e7e3", zeroline=False, fixedrange=True)


def add_zero_line(fig: go.Figure) -> None:
    fig.add_hline(y=0, line=dict(color=AXIS, width=1), layer="below")


def card(id, title, why, footer, fig, columns, rows, wide=False, fixed=None, zero=False,
         downloadable=True, caveat: str | None = None) -> dict:
    """Everything the page needs for one chart card.

    fixed: [from, to] if the chart ignores the page time control (the seasonal comparison chart).
    zero:  True if the y-axis must always include zero (bar charts, % change charts).
    downloadable: False hides the Download CSV / image buttons (licensed data, e.g. U. Michigan sentiment).
    """
    if not rows:
        raise RuntimeError(f"Chart {id} has no data")   # something upstream broke: stop the build
    return {"id": id, "title": title, "why": why, "footer": footer, "wide": wide, "fixed": fixed, "zero": zero,
            "downloadable": downloadable,
            "figure": json.loads(fig.to_json()), "table": {"columns": columns, "rows": rows},
            # Phase 3 extras (set by the page module when a chart has forecast elements):
            #   ahead        last date the forecast reaches; in today's view the x-axis runs to it
            #   whatif_ahead last date of the what-if paths (x-axis end while the what-if toggle is on)
            #   whatif       True shows the "Show what-if paths" toggle; notes: extra lines under the chart
            "ahead": None, "whatif_ahead": None, "whatif": False, "notes": [], "fixed_note": None,
            # Review WP7 (P3): caveat = one plain sentence shown directly under the chart, in normal text;
            # the footer then folds into a closed "Source and method" box (see _macros.html chart_card)
            "caveat": caveat}


def split_preliminary(d: pd.DataFrame, source_col: str):
    """Split weekly rows into official weeks and the preliminary tail.

    The tail starts with the last official week so the dashed line connects to the solid one.
    Returns (official rows, tail rows, hover labels for the tail).
    """
    prelim = d[source_col].map(is_preliminary)
    official = d[~prelim]
    if not prelim.any():
        return official, d.iloc[0:0], []
    tail = pd.concat([official.tail(1), d[prelim]])
    labels = ["official"] + [prelim_label(s) for s in d[prelim][source_col]]
    return official, tail, labels


def last_data_note(d: pd.DataFrame, date_col: str, source_col: str | None = None, monthly=False) -> str:
    """'Last data: Oct 31, 2026, preliminary (advance).'"""
    last = d.dropna().iloc[-1] if source_col is None else d.iloc[-1]
    when = fmt_month(last[date_col]) if monthly else fmt_date(last[date_col])
    if source_col and is_preliminary(last[source_col]):
        when += f", {prelim_label(last[source_col])}"
    return f" Last data: {when}."


def line_chart(id, title, why, footer, s: pd.Series, name, y_title, hover, csv_col,
               monthly=True, zero_line=False, prelim: pd.Series | None = None, wide=False, freq="MS",
               x_hover: str | None = None, downloadable=True, caveat: str | None = None) -> dict:
    """One series as a line, with recession shading.

    Monthly series get missing months put back as blanks, so a gap (e.g. no October 2025 survey,
    federal government shutdown) shows as a break instead of a straight line across it.
    freq: "MS" for series dated the 1st of the month (FRED), "ME" for month-end dates (DOL).
    x_hover: date format in the tooltip (default: "Oct 2026" monthly, "Week ending Oct 31, 2026" weekly).
    prelim (weekly only): a series of source labels; preliminary weeks are drawn dashed with hollow markers.
    """
    s = s.dropna()
    if monthly:
        s = s.asfreq(freq)
    d = pd.DataFrame({"date": s.index, "value": s.values})
    d["source"] = prelim.reindex(s.index).fillna("ETA 539").values if prelim is not None else "official"
    official, tail, labels = split_preliminary(d, "source")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates(official.date), y=plain(official.value), name=name, mode="lines",
                             line=dict(color=ACCENT, width=2), meta={"role": "main"},
                             hovertemplate=f"{hover}<extra></extra>"))
    if len(tail):
        fig.add_trace(go.Scatter(
            x=dates(tail.date), y=plain(tail.value), name=tail_name(tail.source), mode="lines+markers",
            customdata=labels, line=dict(color=ACCENT, width=2, dash="dash"),
            marker=dict(size=8, symbol="circle-open", color=ACCENT, line=dict(width=2)),
            meta={"role": "main-prelim"}, hovertemplate=f"{hover} · %{{customdata}}<extra></extra>"))
    if zero_line:
        add_zero_line(fig)
    add_recession_shading(fig, d.date.iloc[0])
    base_layout(fig, y_title, x_hover or ("%b %Y" if monthly else "Week ending %b %-d, %Y"), legend=len(tail) > 0)

    footer += (hollow_note(tail.source) if len(tail) else "") + " Grey bands: NBER recessions." + last_data_note(
        d.dropna(subset=["value"]), "date", "source" if prelim is not None else None, monthly)
    columns = ["date", csv_col] + (["source"] if prelim is not None else [])
    rows = [[x, v] + ([src] if prelim is not None else [])
            for x, v, src in zip(dates(d.date), plain(d.value), d.source)]
    return card(id, title, why, footer, fig, columns, rows, wide=wide, zero=zero_line, downloadable=downloadable,
                caveat=caveat)


def pre_recession_averages(s: pd.Series) -> list[tuple[str, float]]:
    """Reference levels for a weekly series: its average over the 12 months before the 2001, 2008-09 and
    2020 recessions, and its 2019 calendar-year average.

    "Before" = the 12 months before the first recession month in FRED's USREC series. USREC marks recessions
    from the month after the NBER peak, so the windows end Mar 2001, Dec 2007 and Feb 2020 (the peak months)."""
    global BANDS
    if BANDS is None:
        BANDS = recession_bands()
    refs = []
    for year, label in [(2001, "Before 2001"), (2008, "Before 2008–09"), (2020, "Before 2020")]:
        start = next(b["start"] for b in BANDS if b["start"].year == year)
        window = s[(s.index >= start - pd.DateOffset(months=12)) & (s.index < start)]
        refs.append((label, float(window.mean())))
    refs.append(("2019 average", float(s[s.index.year == 2019].mean())))
    return refs


def add_reference_lines(fig: go.Figure, refs: list[tuple[str, float]], x0: str, x1: str, fmt: str) -> None:
    """Dotted grey horizontal lines across the whole chart, with one legend entry for all of them.
    meta.ref tells site.js to keep these lines inside the y-axis whatever dates are shown. The labels at the
    right edge are placed by site.js each time the view changes (layout.meta.refs), merging labels that would
    sit closer than about one line of text, so they never overlap at any zoom."""
    for i, (label, v) in enumerate(refs):
        fig.add_trace(go.Scatter(x=[x0, x1], y=[v, v], mode="lines", name="Pre-recession averages (dotted)",
                                 legendgroup="refs", showlegend=(i == 0), hoverinfo="skip",
                                 line=dict(color=GREYS[1], width=1.2, dash="dot"), meta={"role": "grey1", "ref": True}))
    fig.update_layout(meta={"refs": [{"text": f"{label} {format(v, fmt)}", "value": v} for label, v in refs]})


def add_marker(fig: go.Figure, when: str, text: str) -> None:
    """A thin dashed vertical line with a short label (e.g. the 1978 change in UI coverage)."""
    fig.add_shape(type="line", x0=when, x1=when, yref="paper", y0=0, y1=1, line=dict(color=AXIS, width=1, dash="dash"),
                  layer="below")
    fig.add_annotation(x=when, yref="paper", y=1, yanchor="top", xanchor="left", xshift=3, text=text,
                       showarrow=False, font=dict(size=10, color="#52514e"))


def weekly_claims_chart(id, title, why, footer, d: pd.DataFrame, weekly_col, avg_col, source_col,
                        y_title, hover, csv_names, wide=False, refs: list | None = None, ref_fmt=".1f",
                        markers: list | None = None, caveat: str | None = None) -> dict:
    """Weekly claims measure: 4-week average bold, weekly faint, preliminary (news release) weeks
    dashed with hollow markers. d has columns week_ended, weekly_col, avg_col, source_col.
    refs: [(label, value)] reference levels drawn as dotted lines; markers: [(date, label)] vertical lines."""
    d = d.dropna(subset=[weekly_col])[["week_ended", weekly_col, avg_col, source_col]].copy()
    d["x"] = dates(d.week_ended)
    official, tail, labels = split_preliminary(d, source_col)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=plain(official.x), y=plain(official[weekly_col]), name="Weekly", mode="lines",
                             line=dict(color=FAINT, width=1), meta={"role": "faint"},
                             hovertemplate=f"{hover}<extra>Weekly</extra>"))
    fig.add_trace(go.Scatter(x=plain(official.x), y=plain(official[avg_col]), name="4-week average", mode="lines",
                             line=dict(color=ACCENT, width=2.5), meta={"role": "main"},
                             hovertemplate=f"{hover}<extra>4-week average</extra>"))
    if len(tail):
        fig.add_trace(go.Scatter(
            x=plain(tail.x), y=plain(tail[weekly_col]), name="Weekly, " + tail_name(tail[source_col]).split(" (")[0].lower(), mode="lines+markers",
            legendgroup="prelim", showlegend=False, customdata=labels,
            line=dict(color=FAINT, width=1, dash="dot"),
            marker=dict(size=8, symbol="circle-open", color=FAINT, line=dict(width=1.5)),
            meta={"role": "faint-prelim"},
            hovertemplate=f"{hover} · %{{customdata}}<extra>Weekly</extra>"))
        fig.add_trace(go.Scatter(
            x=plain(tail.x), y=plain(tail[avg_col]), name=tail_name(tail[source_col]),
            mode="lines+markers", legendgroup="prelim", customdata=labels,
            line=dict(color=ACCENT, width=2.5, dash="dash"),
            marker=dict(size=8, symbol="circle-open", color=ACCENT, line=dict(width=2)),
            meta={"role": "main-prelim"},
            hovertemplate=f"{hover} · %{{customdata}}<extra>4-week average</extra>"))
    if refs:
        add_reference_lines(fig, refs, d.x.iloc[0], d.x.iloc[-1], ref_fmt)
    for when, text in markers or []:
        add_marker(fig, when, text)
    add_recession_shading(fig, d.week_ended.iloc[0])
    base_layout(fig, y_title, "Week ending %b %-d, %Y")

    footer = ("Plotted: 4-week average (bold), weekly (faint). " + footer
              + hollow_note(d[source_col]) + " Grey bands: NBER recessions."
              + (" Dotted lines: average SA weekly rate over the 12 months up to each NBER peak (Apr 2000–Mar 2001, "
                 "Jan–Dec 2007, Mar 2019–Feb 2020) and over 2019."
                 if refs else "")
              + last_data_note(d, "week_ended", source_col))
    # Download table: one row per week (the 4-week average is blank for the first 3 weeks).
    rows = [[x, w, (None if pd.isna(a) else a), s]
            for x, w, a, s in zip(d.x, d[weekly_col], d[avg_col], d[source_col])]
    return card(id, title, why, footer, fig, csv_names, rows, wide=wide, caveat=caveat)


def lines_chart(id, title, why, footer, lines: list[tuple], y_title, hover, csv_names, zero_line=False,
                freq="MS") -> dict:
    """Two or more series in the same units, e.g. the Philadelphia and New York Fed surveys.
    lines: [(series, name, short label), ...]; the first is drawn in the accent color, the rest in greys.
    Each line is labelled at its end as well as in the legend."""
    fig = go.Figure()
    ends, table = [], {}
    for i, (s, name, label) in enumerate(lines):
        s = s.dropna().asfreq(freq)
        table[name] = s
        style = (dict(color=ACCENT, width=2), "main") if i == 0 else (dict(color=GREYS[i - 1], width=1.5), f"grey{i - 1}")
        fig.add_trace(go.Scatter(x=dates(s.index), y=plain(s.values), name=name, mode="lines", line=style[0],
                                 meta={"role": style[1]}, hovertemplate=f"{hover}<extra>{name}</extra>"))
        last = s.dropna()
        ends.append({"year": label, "x": last.index[-1].strftime("%Y-%m-%d"), "y": last.iloc[-1]})
    if zero_line:
        add_zero_line(fig)
    first = min(t.index[0] for t in table.values())
    add_recession_shading(fig, first)
    base_layout(fig, y_title, "%b %Y")
    fig.update_layout(margin=dict(l=60, r=70, t=8, b=36))
    all_values = pd.concat(table.values())
    add_end_labels(fig, ends, all_values.min(), all_values.max())
    latest = max(t.dropna().index[-1] for t in table.values())
    footer += f" Grey bands: NBER recessions. Last data: {fmt_month(latest)}."
    df = pd.DataFrame(table).dropna(how="all")
    rows = [[d.strftime("%Y-%m-%d")] + plain(r) for d, r in zip(df.index, df.values)]
    return card(id, title, why, footer, fig, csv_names, rows, zero=zero_line)


def line_with_comparison(id, title, why, footer, main: pd.Series, main_name, main_freq,
                         comp: pd.Series, comp_name, comp_freq, y_title, hover, csv_names,
                         extra: pd.Series | None = None) -> dict:
    """A main series (bold accent) with a comparison series (grey) in the same units, e.g. average weeks
    claimed vs. average weeks entitled. The two can have different frequencies (monthly vs. quarterly);
    each keeps its own gaps. extra: an additional column for the CSV only (not drawn)."""
    main = main.dropna().asfreq(main_freq)
    comp = comp.dropna().asfreq(comp_freq)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates(comp.index), y=plain(comp.values), name=comp_name, mode="lines",
                             line=dict(color=GREYS[0], width=1.5), meta={"role": "grey0"}, connectgaps=False,
                             hovertemplate=f"{hover}<extra>{comp_name}</extra>"))
    fig.add_trace(go.Scatter(x=dates(main.index), y=plain(main.values), name=main_name, mode="lines",
                             line=dict(color=ACCENT, width=2.5), meta={"role": "main"},
                             hovertemplate=f"{hover}<extra>{main_name}</extra>"))
    first = min(main.index[0], comp.index[0])
    add_recession_shading(fig, first)
    base_layout(fig, y_title, "%b %Y")
    fig.update_layout(legend_traceorder="reversed")   # main series first in the legend (it is drawn on top)
    short = lambda n: n.split(" (")[0].lower()        # 'Average weeks paid (all claimants)' -> 'average weeks paid'
    footer += (f" Grey bands: NBER recessions. Last data: {short(main_name)} {fmt_month(main.dropna().index[-1])}, "
               f"{short(comp_name)} {fmt_month(comp.dropna().index[-1])}.")
    # CSV: one row per date that appears in either series (quarter ends line up with month ends)
    table = pd.DataFrame({"main": main, "comp": comp})
    if extra is not None:
        table["extra"] = extra
    table = table.dropna(how="all")
    rows = [[d.strftime("%Y-%m-%d")] + plain(r) for d, r in zip(table.index, table.values)]
    return card(id, title, why, footer, fig, csv_names, rows)


def bars_with_average(id, title, why, footer, s: pd.Series, bar_name, avg_name, y_title, hover, csv_names,
                      avg_months=3) -> dict:
    """Monthly values as faint bars with a bold moving-average line (e.g. payroll change)."""
    s = s.asfreq("MS")
    avg = s.rolling(avg_months).mean()
    x = dates(s.index)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=x, y=plain(s.values), name=bar_name, marker=dict(color=FAINT, line=dict(width=0)),
                         meta={"role": "faint"}, hovertemplate=f"{hover}<extra>{bar_name}</extra>"))
    fig.add_trace(go.Scatter(x=x, y=plain(avg.values), name=avg_name, mode="lines",
                             line=dict(color=ACCENT, width=2.5), meta={"role": "main"},
                             hovertemplate=f"{hover}<extra>{avg_name}</extra>"))
    add_zero_line(fig)
    add_recession_shading(fig, s.index[0])
    base_layout(fig, y_title, "%b %Y")
    footer += " Grey bands: NBER recessions." + f" Last data: {fmt_month(s.dropna().index[-1])}."
    rows = [[xi, v, a] for xi, v, a in zip(x, plain(s.values), plain(avg.values))]
    return card(id, title, why, footer, fig, csv_names, rows, zero=True)


def add_end_labels(fig: go.Figure, ends: list[dict], y_min: float, y_max: float,
                   plot_px: int = 270, min_gap_px: int = 16) -> None:
    """Label each line at its end (e.g. '2024'), in text color rather than the line color.

    Lines that end close together (within 3 weeks of each other) get their labels nudged apart
    vertically so they don't overlap: at least min_gap_px pixels, using the chart's full data range to
    convert values to pixels (approximate, since the reader can change the y-axis).
    """
    px_per_unit = plot_px / (y_max - y_min) if y_max > y_min else 1
    ends = sorted(ends, key=lambda e: e["x"])
    groups, group = [], []
    for e in ends:   # group labels whose lines end within 21 days of each other
        if group and (pd.Timestamp(e["x"]) - pd.Timestamp(group[-1]["x"])).days > 21:
            groups.append(group)
            group = []
        group.append(e)
    groups.append(group)
    for group in groups:
        placed = []   # label heights in pixels, bottom to top
        for e in sorted(group, key=lambda e: e["y"]):
            want = e["y"] * px_per_unit
            pos = max(want, placed[-1] + min_gap_px) if placed else want
            placed.append(pos)
            fig.add_annotation(x=e["x"], y=e["y"], text=str(e["year"]), showarrow=False, xanchor="left",
                               xshift=4, yshift=pos - want, font=dict(size=11, color="#52514e"))


def seasonal_chart(id, title, why, footer, d: pd.DataFrame, value_col, source_col, hover, csv_names,
                   prior_years=3) -> dict:
    """This year vs. the prior years, by week of year (fixed view: ignores the page time control).

    Each week is placed by its calendar date in a stand-in year (2000, a leap year so Feb 29 fits),
    so the x-axis runs Jan to Dec and holiday weeks line up across years.
    "This year" = the calendar year of the latest week (decision 2026-11-07).
    """
    d = d.dropna(subset=[value_col]).copy()
    this_year = d.week_ended.dt.year.max()
    years = list(range(this_year - prior_years, this_year + 1))
    d = d[d.week_ended.dt.year.isin(years)]
    d["x"] = [f"2000-{w:%m-%d}" for w in d.week_ended]
    d["week_label"] = [fmt_date(w) for w in d.week_ended]

    fig = go.Figure()
    ends = []   # where each year's line ends, for its direct label
    for i, yr in enumerate(years):
        part = d[d.week_ended.dt.year == yr]
        last = part.iloc[-1]
        if yr == this_year:
            official, tail, labels = split_preliminary(part, source_col)
            fig.add_trace(go.Scatter(
                x=plain(official.x), y=plain(official[value_col]), name=str(yr), mode="lines",
                customdata=official.week_label, line=dict(color=ACCENT, width=2.5), meta={"role": "main"},
                hovertemplate=f"{hover} (week ending %{{customdata}})<extra>{yr}</extra>"))
            if len(tail):
                fig.add_trace(go.Scatter(
                    x=plain(tail.x), y=plain(tail[value_col]), name=f"{yr}, preliminary", mode="lines+markers",
                    customdata=[f"{w} · {lab}" for w, lab in zip(tail.week_label, labels)],
                    line=dict(color=ACCENT, width=2.5, dash="dash"),
                    marker=dict(size=8, symbol="circle-open", color=ACCENT, line=dict(width=2)),
                    meta={"role": "main-prelim"},
                    hovertemplate=f"{hover} (week ending %{{customdata}})<extra>{yr}</extra>"))
        else:
            shade = len(years) - 2 - i     # most recent prior year darkest
            fig.add_trace(go.Scatter(
                x=plain(part.x), y=plain(part[value_col]), name=str(yr), mode="lines",
                customdata=part.week_label, line=dict(color=GREYS[shade], width=1.5),
                meta={"role": f"grey{shade}"},
                hovertemplate=f"{hover} (week ending %{{customdata}})<extra>{yr}</extra>"))
        ends.append({"year": yr, "x": last.x, "y": last[value_col]})
    add_end_labels(fig, ends, d[value_col].min(), d[value_col].max())
    base_layout(fig, "Initial claims (NSA)", "%b %-d")
    fig.update_xaxes(tickformat="%b", dtick="M1", range=["2000-01-01", "2000-12-31"])
    fig.update_layout(margin=dict(l=60, r=40, t=8, b=36))

    footer += hollow_note(d[source_col]) + last_data_note(d, 'week_ended', source_col)
    rows = [[w.strftime("%Y-%m-%d"), int(w.year), v, s]
            for w, v, s in zip(d.week_ended, plain(d[value_col]), d[source_col])]
    return card(id, title, why, footer, fig, csv_names, rows, fixed=["2000-01-01", "2000-12-31"])
