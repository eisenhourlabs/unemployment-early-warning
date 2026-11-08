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
                         usecols=["week_ended", "ic_nsa", "ic_sa", "ic_sa_4wk", "cc_sa", "cc_sa_4wk"])
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

    Example: 62 means 62% of all weeks since 1995 had a rate at or below this week's.
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


def card(id, title, why, footer, fig, columns, rows, wide=False, fixed=None, zero=False) -> dict:
    """Everything the page needs for one chart card.

    fixed: [from, to] if the chart ignores the page time control (the seasonal comparison chart).
    zero:  True if the y-axis must always include zero (bar charts, % change charts).
    """
    if not rows:
        raise RuntimeError(f"Chart {id} has no data")   # something upstream broke: stop the build
    return {"id": id, "title": title, "why": why, "footer": footer, "wide": wide, "fixed": fixed, "zero": zero,
            "figure": json.loads(fig.to_json()), "table": {"columns": columns, "rows": rows}}


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
               monthly=True, zero_line=False, prelim: pd.Series | None = None, wide=False, freq="MS") -> dict:
    """One series as a line, with recession shading.

    Monthly series get missing months put back as blanks, so a gap (e.g. no October 2025 survey,
    federal government shutdown) shows as a break instead of a straight line across it.
    freq: "MS" for series dated the 1st of the month (FRED), "ME" for month-end dates (DOL).
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
            x=dates(tail.date), y=plain(tail.value), name="Preliminary (news release)", mode="lines+markers",
            customdata=labels, line=dict(color=ACCENT, width=2, dash="dash"),
            marker=dict(size=8, symbol="circle-open", color=ACCENT, line=dict(width=2)),
            meta={"role": "main-prelim"}, hovertemplate=f"{hover} · %{{customdata}}<extra></extra>"))
    if zero_line:
        add_zero_line(fig)
    add_recession_shading(fig, d.date.iloc[0])
    base_layout(fig, y_title, "%b %Y" if monthly else "Week ending %b %-d, %Y", legend=len(tail) > 0)

    footer += " Grey bands: NBER recessions." + last_data_note(
        d.dropna(subset=["value"]), "date", "source" if prelim is not None else None, monthly)
    columns = ["date", csv_col] + (["source"] if prelim is not None else [])
    rows = [[x, v] + ([src] if prelim is not None else [])
            for x, v, src in zip(dates(d.date), plain(d.value), d.source)]
    return card(id, title, why, footer, fig, columns, rows, wide=wide, zero=zero_line)


def weekly_claims_chart(id, title, why, footer, d: pd.DataFrame, weekly_col, avg_col, source_col,
                        y_title, hover, csv_names, wide=False) -> dict:
    """Weekly claims measure: 4-week average bold, weekly faint, preliminary (news release) weeks
    dashed with hollow markers. d has columns week_ended, weekly_col, avg_col, source_col."""
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
            x=plain(tail.x), y=plain(tail[weekly_col]), name="Weekly, preliminary", mode="lines+markers",
            legendgroup="prelim", showlegend=False, customdata=labels,
            line=dict(color=FAINT, width=1, dash="dot"),
            marker=dict(size=8, symbol="circle-open", color=FAINT, line=dict(width=1.5)),
            meta={"role": "faint-prelim"},
            hovertemplate=f"{hover} · %{{customdata}}<extra>Weekly</extra>"))
        fig.add_trace(go.Scatter(
            x=plain(tail.x), y=plain(tail[avg_col]), name="Preliminary (news release)",
            mode="lines+markers", legendgroup="prelim", customdata=labels,
            line=dict(color=ACCENT, width=2.5, dash="dash"),
            marker=dict(size=8, symbol="circle-open", color=ACCENT, line=dict(width=2)),
            meta={"role": "main-prelim"},
            hovertemplate=f"{hover} · %{{customdata}}<extra>4-week average</extra>"))
    add_recession_shading(fig, d.week_ended.iloc[0])
    base_layout(fig, y_title, "Week ending %b %-d, %Y")

    footer += (" Hollow markers: preliminary. Grey bands: NBER recessions."
               + last_data_note(d, "week_ended", source_col))
    # Download table: one row per week (the 4-week average is blank for the first 3 weeks).
    rows = [[x, w, (None if pd.isna(a) else a), s]
            for x, w, a, s in zip(d.x, d[weekly_col], d[avg_col], d[source_col])]
    return card(id, title, why, footer, fig, csv_names, rows, wide=wide)


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

    footer += f" Hollow markers: preliminary.{last_data_note(d, 'week_ended', source_col)}"
    rows = [[w.strftime("%Y-%m-%d"), int(w.year), v, s]
            for w, v, s in zip(d.week_ended, plain(d[value_col]), d[source_col])]
    return card(id, title, why, footer, fig, csv_names, rows, fixed=["2000-01-01", "2000-12-31"])
