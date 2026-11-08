"""
Build the Unemployment Watch website (a folder of plain HTML files) from our data files.

What it does, step by step:
  1. Reads the processed data (FRED series, DOL claims rates, the health check, the release calendar).
  2. Works out the headline numbers: the five tiles, the "What changed this week" sentences,
     the freshness line and the stale-data badge.
  3. Draws the charts with Plotly (a charting library: Python describes each chart, and the
     plotly.js script draws it interactively in the reader's browser).
  4. Fills in the HTML templates in src/site/templates/ with Jinja2 (a fill-in-the-blanks tool:
     the template has {{ placeholders }} and Python supplies the values).
  5. Writes everything to the site/ folder, which GitHub Pages publishes. site/ is rebuilt from
     scratch every time and is not stored in Git.

If anything goes wrong, the script stops with an error (exit code 1). In the cloud that means the
publish step is skipped and the previous version of the site stays online.

Run (from the project folder):
    python src/site/build_site.py
Preview:
    python -m http.server 8000 --directory site      then open http://localhost:8000
"""

import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly
import plotly.graph_objects as go
from jinja2 import Environment, FileSystemLoader, select_autoescape

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROCESSED = ROOT / "data" / "processed"
DOL = PROCESSED / "dol"
OUT = ROOT / "site"
REPO_URL = "https://github.com/eisenhourlabs/unemployment-early-warning"
CENTRAL = ZoneInfo("America/Chicago")

# ---------------------------------------------------------------------------
# Look. One accent color for the main series, greys for everything else.
# Red / amber / green are reserved for the Phase 3 risk signal, so they are not used here.
# site.js swaps these for the dark-mode versions when the reader turns dark mode on.
# ---------------------------------------------------------------------------
ACCENT = "#2a78d6"
FAINT = "rgba(42, 120, 214, 0.35)"   # the accent, see-through: weekly values behind the 4-week average
RECESSION_FILL = "rgba(120, 120, 120, 0.16)"

# Page-wide time control. Recession views run from about a year before each NBER recession to about
# two years after it ends (decision log, 2026-11-07).
RANGE_BUTTONS = [("1y", "1Y"), ("2y", "2Y"), ("5y", "5Y"), ("10y", "10Y"), ("20y", "20Y"), ("max", "Max")]
RECESSION_VIEWS = [
    {"key": "2001", "label": "2001", "start": "2000-01-01", "end": "2003-12-31"},
    {"key": "2008-09", "label": "2008–09", "start": "2007-01-01", "end": "2011-12-31"},
    {"key": "2020", "label": "2020", "start": "2019-01-01", "end": "2022-12-31"},
]
DEFAULT_RANGE = "5y"

# How far back a value must last have been matched before a sentence says "the highest since ..."
HIGHEST_SINCE_MIN_WEEKS = 13
# Monthly news (unemployment rate, Sahm) only appears in "What changed" if FRED updated it this recently.
MONTHLY_NEWS_DAYS = 7


# ===========================================================================
# Reading data
# ===========================================================================
def fred(series_id: str) -> pd.Series:
    """A FRED series as a pandas Series indexed by date, with blank values dropped."""
    df = pd.read_csv(PROCESSED / f"{series_id}.csv", parse_dates=["date"])
    return df.set_index("date")["value"].dropna()


def fred_metadata() -> pd.DataFrame:
    return pd.read_csv(PROCESSED / "_metadata.csv").set_index("series_id")


def claims_weekly() -> pd.DataFrame:
    """DOL weekly claims rates (from 1995) joined with the claims levels and their source flags."""
    rates = pd.read_csv(DOL / "claims_rates_weekly.csv", parse_dates=["week_ended"])
    levels = pd.read_csv(DOL / "national_weekly.csv", parse_dates=["week_ended"],
                         usecols=["week_ended", "ic_sa", "ic_sa_4wk", "cc_sa", "cc_sa_4wk"])
    df = rates.merge(levels, on="week_ended", how="left")
    # The initial claims rate is stored as a percent of covered employment. The site shows it
    # per 10,000 covered workers (percent x 100), e.g. 0.123% -> 12.3 per 10,000 (decision 2026-11-07).
    for col in ["ic_rate_sa", "ic_rate_sa_4wk"]:
        df[col + "_per10k"] = df[col] * 100
    return df


def is_preliminary(source) -> bool:
    """True for weeks still coming from the news release (not yet in DOL's official ETA 539 report)."""
    return isinstance(source, str) and source.startswith("news release")


def prelim_label(source) -> str:
    """'news release, advance' -> 'preliminary (advance)'."""
    return "preliminary (" + source.split(",")[1].strip() + ")" if is_preliminary(source) else "official"


# ===========================================================================
# Formatting helpers (one place, so every number on the site looks the same)
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

    Example: 62 means 62% of all weeks since 1995 had a rate at or below this week's.
    Ties count as 'at or below', so a value equal to the historical minimum scores above 0.
    """
    values = values.dropna()
    return int(round(100 * (values <= latest).mean()))


def percentile_text(values: pd.Series, latest: float, since) -> str:
    """'62nd percentile since 1995', or 'Lowest since 1995' / 'Highest since 1995' at the extremes,
    because '0th percentile' reads oddly (it means fewer than 0.5% of observations were at or below)."""
    values = values.dropna()
    if latest <= values.min():
        return f"Lowest since {since} (record low)"
    if latest >= values.max():
        return f"Highest since {since} (record high)"
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


def add_recession_shading(fig: go.Figure, bands: list[dict], first_date) -> None:
    """Grey bands behind the lines for each recession after the chart's first date."""
    for b in bands:
        if b["end"] < pd.Timestamp(first_date):
            continue
        fig.add_vrect(x0=b["start"].strftime("%Y-%m-%d"), x1=b["end"].strftime("%Y-%m-%d"),
                      fillcolor=RECESSION_FILL, line_width=0, layer="below",
                      name="recession")


# ===========================================================================
# Charts
# ===========================================================================
def plain(values) -> list:
    """Plain Python list with None for blanks. Plotly would otherwise pack number columns into a
    binary format that site.js can't read point by point (it needs the numbers to rescale y-axes)."""
    return [None if pd.isna(v) else (float(v) if not isinstance(v, str) else v) for v in values]


def base_layout(fig: go.Figure, y_title: str, hover_format: str) -> None:
    """Settings every time-series chart shares."""
    fig.update_layout(
        margin=dict(l=56, r=16, t=8, b=36),
        height=320,
        hovermode="x unified",               # one tooltip listing every line at the hovered date
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(size=12)),
        paper_bgcolor="#fcfcfb",
        plot_bgcolor="#fcfcfb",
        font=dict(family="system-ui, -apple-system, Segoe UI, Roboto, sans-serif", size=12, color="#52514e"),
        dragmode="zoom",
    )
    fig.update_xaxes(type="date", showgrid=False, hoverformat=hover_format, linecolor="#c8c7c2",
                     ticks="outside", tickcolor="#c8c7c2")
    # The y-axis can't be dragged: site.js rescales it to whatever dates are visible.
    fig.update_yaxes(title_text=y_title, gridcolor="#e8e7e3", zeroline=False, fixedrange=True)


def unemployment_chart(ur: pd.Series, bands: list[dict], forecast: pd.DataFrame | None = None) -> dict:
    """Unemployment rate with recession shading.

    forecast (Phase 3): a DataFrame indexed by date with columns lo90, lo50, median, hi50, hi90 (percent).
    When given, a fan (shaded 90% and 50% intervals plus a dashed median) is drawn after the last actual
    month. Left as None in Phase 2.
    """
    # Put missing months back in as blanks so the line shows a gap (e.g. no October 2025 survey,
    # federal government shutdown) instead of drawing a straight line across it.
    ur = ur.asfreq("MS")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=plain(ur.index.strftime("%Y-%m-%d")), y=plain(ur.values), name="Unemployment rate",
        mode="lines", line=dict(color=ACCENT, width=2), meta={"role": "main"},
        hovertemplate="%{y:.1f}%<extra></extra>"))
    if forecast is not None:
        x = forecast.index.strftime("%Y-%m-%d")
        for lo, hi, label, alpha in [("lo90", "hi90", "90% interval", 0.15), ("lo50", "hi50", "50% interval", 0.30)]:
            fig.add_trace(go.Scatter(x=plain(x), y=plain(forecast[hi]), mode="lines", line=dict(width=0),
                                     showlegend=False, hoverinfo="skip", meta={"role": "fan-edge"}))
            fig.add_trace(go.Scatter(x=plain(x), y=plain(forecast[lo]), mode="lines", line=dict(width=0), fill="tonexty",
                                     fillcolor=f"rgba(42, 120, 214, {alpha})", name=f"Forecast {label}",
                                     meta={"role": "fan", "alpha": alpha},
                                     hovertemplate="%{y:.1f}%<extra></extra>"))
        fig.add_trace(go.Scatter(x=plain(x), y=plain(forecast["median"]), name="Forecast median", mode="lines",
                                 line=dict(color=ACCENT, width=2, dash="dash"), meta={"role": "main"},
                                 hovertemplate="%{y:.1f}%<extra></extra>"))
    add_recession_shading(fig, bands, ur.index[0])
    base_layout(fig, "Percent of labor force", "%b %Y")
    fig.update_layout(showlegend=forecast is not None)

    table = {"columns": ["date", "unemployment_rate_pct"],
             "rows": [[d.strftime("%Y-%m-%d"), None if pd.isna(v) else v] for d, v in ur.items()]}
    return {
        "id": "unemployment-rate",
        "title": "Unemployment rate",
        "why": "The headline measure everyone knows; it lags claims but sets the overall picture.",
        "footer": f"Source: BLS via FRED (UNRATE). Percent of the labor force, seasonally adjusted, monthly. "
                  f"Grey bands: NBER recessions. Gap: no October 2025 survey (government shutdown). "
                  f"Last data: {fmt_month(ur.index[-1])}.",
        "figure": json.loads(fig.to_json()),
        "table": table,
    }


def claims_rate_chart(df: pd.DataFrame, kind: str, bands: list[dict]) -> dict:
    """SA initial ('ic') or continuing ('cc') claims rate: 4-week average bold, weekly faint,
    preliminary (news release) weeks dashed with hollow markers."""
    if kind == "ic":
        weekly_col, avg_col, source_col = "ic_rate_sa_per10k", "ic_rate_sa_4wk_per10k", "source_initial"
        unit, y_title, hover = "per 10,000", "Per 10,000 covered workers", "%{y:.1f}"
    else:
        weekly_col, avg_col, source_col = "cc_rate_sa", "cc_rate_sa_4wk", "source_continued"
        unit, y_title, hover = "%", "Percent of covered workers", "%{y:.1f}%"
    d = df.dropna(subset=[weekly_col])[["week_ended", weekly_col, avg_col, source_col]].copy()
    d["x"] = d.week_ended.dt.strftime("%Y-%m-%d")
    prelim = d[source_col].map(is_preliminary)
    official = d[~prelim]
    # The dashed preliminary segment starts at the last official week so the line stays connected.
    tail = pd.concat([official.tail(1), d[prelim]]) if prelim.any() else d.iloc[0:0]
    tail_labels = ["official"] + [prelim_label(s) for s in d[prelim][source_col]] if prelim.any() else []

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=plain(official.x), y=plain(official[weekly_col]), name="Weekly", mode="lines",
                             line=dict(color=FAINT, width=1), meta={"role": "faint"},
                             hovertemplate=f"{hover}<extra>Weekly</extra>"))
    fig.add_trace(go.Scatter(x=plain(official.x), y=plain(official[avg_col]), name="4-week average", mode="lines",
                             line=dict(color=ACCENT, width=2.5), meta={"role": "main"},
                             hovertemplate=f"{hover}<extra>4-week average</extra>"))
    if len(tail):
        fig.add_trace(go.Scatter(
            x=plain(tail.x), y=plain(tail[weekly_col]), name="Weekly, preliminary", mode="lines+markers",
            legendgroup="prelim", showlegend=False, customdata=tail_labels,
            line=dict(color=FAINT, width=1, dash="dot"),
            marker=dict(size=8, symbol="circle-open", color=FAINT, line=dict(width=1.5)),
            meta={"role": "faint-prelim"},
            hovertemplate=f"{hover} · %{{customdata}}<extra>Weekly</extra>"))
        fig.add_trace(go.Scatter(
            x=plain(tail.x), y=plain(tail[avg_col]), name="Preliminary (news release)",
            mode="lines+markers", legendgroup="prelim", customdata=tail_labels,
            line=dict(color=ACCENT, width=2.5, dash="dash"),
            marker=dict(size=8, symbol="circle-open", color=ACCENT, line=dict(width=2)),
            meta={"role": "main-prelim"},
            hovertemplate=f"{hover} · %{{customdata}}<extra>4-week average</extra>"))
    add_recession_shading(fig, bands, d.week_ended.iloc[0])
    base_layout(fig, y_title, "Week ending %b %-d, %Y")

    last = d.iloc[-1]
    last_note = fmt_date(last.week_ended) + (f", {prelim_label(last[source_col])}" if prelim.iloc[-1] else "")
    if kind == "ic":
        title = "SA initial claims rate"
        why = "New job losses: drives how often IUI claims start (frequency)."
        footer = ("Source: DOL weekly claims (ETA 539 and news release; FRED ICSA for preliminary weeks). "
                  "Seasonally adjusted initial claims per 10,000 covered workers, weekly.")
        names = ["week_ended", "ic_rate_sa_per_10k", "ic_rate_sa_4wk_per_10k", "source"]
    else:
        title = "SA continuing claims rate"
        why = "How long people stay on benefits: drives how long IUI claims last (severity)."
        footer = ("Source: DOL weekly claims (ETA 539 and news release; FRED CCSA for preliminary weeks). "
                  "Seasonally adjusted continued claims as a percent of covered workers, weekly; "
                  "matches DOL's insured unemployment rate.")
        names = ["week_ended", "cc_rate_sa_pct", "cc_rate_sa_4wk_pct", "source"]
    footer += f" Hollow markers: preliminary. Grey bands: NBER recessions. Last data: {last_note}."
    # Download table: one row per week; blank 4-week average for the first 3 weeks of 1995.
    rows = [[x, w, (None if pd.isna(a) else a), s]
            for x, w, a, s in zip(d.x, d[weekly_col], d[avg_col], d[source_col])]
    return {"id": f"{kind}-rate", "title": title, "why": why, "footer": footer,
            "figure": json.loads(fig.to_json()), "table": {"columns": names, "rows": rows}}


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
    prev_date, prev = ur.index[-2], ur.iloc[-2]
    yr_date, yr = value_on_or_before(ur, latest_date - pd.DateOffset(years=1))
    tiles.append({
        "name": "Unemployment rate",
        "value": f"{latest:.1f}%",
        "as_of": fmt_month(latest_date),
        "changes": [f"{fmt_change(latest - prev, 1, ' pt')} vs. {fmt_month(prev_date)}",
                    f"{fmt_change(latest - yr, 1, ' pt')} vs. {fmt_month(yr_date)}"],
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
    gap = 0.50 - s
    tiles.append({
        "name": "Sahm indicator",
        "value": f"{s:.2f}",
        "as_of": fmt_month(s_date),
        "changes": [f"{fmt_change(s - sahm.iloc[-2], 2)} vs. {fmt_month(sahm.index[-2])}",
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

    # Rule 2: 4-week average, with a streak of 3+ weeks
    ic4 = fred("IC4WSA")
    d4 = ic4.iloc[-1] - ic4.iloc[-2]
    n = streak(ic4)
    streak_txt = (f", its {ordinal(abs(n))} straight weekly {'rise' if n > 0 else 'decline'}" if abs(n) >= 3 else "")
    if d4 == 0:
        sentences.append(f"The 4-week average was unchanged at {fmt_claims(ic4.iloc[-1])}.")
    else:
        sentences.append(f"The 4-week average, which smooths out weekly noise, {moved(d4)} {fmt_claims(abs(d4))} "
                         f"to {fmt_claims(ic4.iloc[-1])}{streak_txt}.")

    # Rule 3: SA continuing claims (one week behind initial claims)
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

    # Rule 4: initial claims 4-week average vs. a year ago
    yr_date, yr = value_on_or_before(ic4, ic4.index[-1] - timedelta(days=364))
    pct = 100 * (ic4.iloc[-1] / yr - 1)
    if round(pct, 1) == 0:
        sentences.append(f"The 4-week average is about the same as a year ago ({fmt_claims(yr)}).")
    else:
        sentences.append(f"The 4-week average is {abs(pct):.1f}% {'above' if pct > 0 else 'below'} a year ago "
                         f"({fmt_claims(yr)}).")

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
# Frame: freshness line, stale badge, release calendar
# ===========================================================================
def freshness(claims: pd.DataFrame, built: datetime) -> dict:
    last = claims.dropna(subset=["ic_rate_sa"]).iloc[-1]
    ur = fred("UNRATE")
    claims_txt = f"claims week ending {fmt_date(last.week_ended)}"
    if is_preliminary(last.source_initial):
        claims_txt += f" ({prelim_label(last.source_initial).replace('preliminary ', '').strip('()')})"
    local = built.astimezone(CENTRAL)
    return {
        "claims": claims_txt,
        "unemployment": f"unemployment rate {fmt_month(ur.index[-1])}",
        "updated": f"site updated {fmt_date(local)} {local:%I:%M %p}".replace(" 0", " ") + " CT",
    }


def stale_badge() -> dict | None:
    """Warning badge if the health check lists any stale or missing series."""
    path = PROCESSED / "series_health.csv"
    if not path.exists():
        return {"count": None, "text": "Data health check not available", "list": ""}
    h = pd.read_csv(path, dtype=str).fillna("")
    # h["flags"], not h.flags: pandas DataFrames already have a built-in attribute called .flags
    stale = h[h["flags"].str.contains("stale|no data", regex=True) | (h["status"] == "FAIL")]
    if stale.empty:
        return None
    names = ", ".join(stale.series_id.astype(str).tolist())
    n = len(stale)
    return {"count": n, "text": f"{n} series stale", "list": f"Stale or missing: {names}"}


def release_calendar() -> list[dict]:
    path = PROCESSED / "release_calendar.csv"
    if not path.exists():
        return []
    cal = pd.read_csv(path, dtype=str).fillna("")
    rows = []
    for r in cal.itertuples(index=False):
        next_txt = (f"{pd.Timestamp(r.next_date):%a}, {fmt_date(r.next_date)}" if r.next_date
                    else "date not available")
        rows.append({"release": r.release, "next": next_txt, "time": r.time_et + " ET" if r.next_date else "",
                     "detail": r.detail, "after": fmt_date(r.following_date) if r.following_date else "",
                     "url": r.source_url, "sort": r.next_date or "9999"})
    return sorted(rows, key=lambda x: x["sort"])


# ===========================================================================
# Write the site
# ===========================================================================
def render(page_template: str, out_name: str, context: dict, env: Environment) -> None:
    html = env.get_template(page_template).render(**context)
    (OUT / out_name).write_text(html, encoding="utf-8")


def main() -> None:
    built = datetime.now(timezone.utc)
    claims = claims_weekly()
    bands = recession_bands()

    charts = {
        "unemployment": unemployment_chart(fred("UNRATE"), bands),
        "ic": claims_rate_chart(claims, "ic", bands),
        "cc": claims_rate_chart(claims, "cc", bands),
    }
    for c in charts.values():   # a chart with no data means something upstream broke: stop
        if not c["table"]["rows"]:
            raise RuntimeError(f"Chart {c['id']} has no data")

    # Everything the browser script needs, embedded in the page as JSON.
    page_data = {
        "today": built.astimezone(CENTRAL).strftime("%Y-%m-%d"),
        "defaultRange": DEFAULT_RANGE,
        "recessionViews": RECESSION_VIEWS,
        "charts": [{"id": c["id"], "figure": c["figure"], "table": c["table"], "title": c["title"]}
                   for c in charts.values()],
    }
    context = {
        "page": "overview",
        "title": "Overview",
        "freshness": freshness(claims, built),
        "badge": stale_badge(),
        "range_buttons": RANGE_BUTTONS,
        "recession_views": RECESSION_VIEWS,
        "default_range": DEFAULT_RANGE,
        "tiles": build_tiles(claims),
        "sentences": what_changed(claims, built),
        "charts": charts,
        "calendar": release_calendar(),
        "repo_url": REPO_URL,
        "page_data": json.dumps(page_data, separators=(",", ":"), allow_nan=False),
        "year": built.year,
    }

    # Start from an empty site/ folder so nothing old lingers.
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True)
    for f in (HERE / "static").iterdir():
        shutil.copy(f, OUT / "assets" / f.name)
    # plotly.js ships inside the Python plotly package, so the browser version always matches.
    shutil.copy(Path(plotly.__file__).parent / "package_data" / "plotly.min.js", OUT / "assets" / "plotly.min.js")

    env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=select_autoescape(["html"]))
    render("overview.html", "index.html", context, env)

    size_kb = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file()) / 1024
    print(f"Site built in {OUT} ({size_kb:,.0f} KB): index.html with {len(charts)} charts, "
          f"{len(context['tiles'])} tiles, {len(context['sentences'])} sentences.")


if __name__ == "__main__":
    main()
