"""
Review chart for the event list: reports/events.png.

  Top:     unemployment rate (monthly), events shaded
  Middle:  SA initial claims 4-week average (weekly, log scale so 2020 doesn't flatten the rest), events shaded
  Bottom:  timeline strip: NBER recessions (grey) and events (blue = linked to a recession, orange = scare),
           each event labeled with its number from data/model/events.csv (1-month events drawn ~3 months
           wide in the strip so they can be seen)

This chart is for checking the event list here; it is not part of the website.
Needs matplotlib (in requirements-dev.txt). Run after events.py:
    python src/model/plot_events.py
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")                 # draw to a file, no window
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "data" / "model"
OUT = ROOT / "reports" / "events.png"

# Colors (reference palette from the dataviz guidance; light mode).
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e4e3df"
LINE = "#2a78d6"          # the data lines
EVENT = "#2a78d6"         # recession-linked events
SCARE = "#eb6834"         # scares (no NBER recession within 6 months)
NBER = "#9a9893"
MIN_STRIP_DAYS = 90       # in the timeline strip, short events are drawn at least ~3 months wide


def month_span(start: str, end: str):
    """From the first day of the start month to the last day of the end month."""
    s = pd.Timestamp(start + "-01")
    e = pd.Timestamp(end + "-01") + pd.offsets.MonthEnd(0)
    return s, e


def main() -> None:
    flags = pd.read_csv(MODEL / "event_flags_monthly.csv", parse_dates=["month"]).set_index("month")
    weekly = pd.read_csv(MODEL / "claims_weekly.csv", parse_dates=["week_ended"]).set_index("week_ended")
    events = pd.read_csv(MODEL / "events.csv", dtype={"start_month": str, "end_month": str})
    last = flags.index[-1].strftime("%Y-%m")

    # NBER recession months -> (first month, last month) spans.
    rec = flags.usrec.fillna(0)
    starts = rec[(rec == 1) & (rec.shift(1, fill_value=0) == 0)].index
    ends = rec[(rec == 1) & (rec.shift(-1, fill_value=0) == 0)].index
    recessions = [(s, e + pd.offsets.MonthEnd(0)) for s, e in zip(starts, ends)]

    fig, (ax_ur, ax_ic, ax_tl) = plt.subplots(
        3, 1, figsize=(15, 9), sharex=True, gridspec_kw={"height_ratios": [4, 4, 1.1], "hspace": 0.12})
    fig.patch.set_facecolor("#fcfcfb")

    # Event shading on both data panels.
    for ev in events.itertuples():
        s, e = month_span(ev.start_month, ev.end_month if ev.end_month != "ongoing" else last)
        color = SCARE if ev.classification == "scare" else EVENT
        for ax in (ax_ur, ax_ic):
            ax.axvspan(s, e, color=color, alpha=0.30 if ev.classification == "scare" else 0.16, lw=0)

    # Data lines.
    ax_ur.plot(flags.index, flags.unrate, color=LINE, lw=1.6)
    ax_ur.set_ylabel("Unemployment rate (%)", color=INK2)
    ax_ic.plot(weekly.index, weekly.IC4WSA / 1000, color=LINE, lw=1.4)
    ax_ic.set_yscale("log")
    ax_ic.set_ylabel("SA initial claims,\n4-week average (thousands, log scale)", color=INK2)
    ax_ic.yaxis.set_major_locator(mticker.FixedLocator([150, 200, 300, 400, 600, 1000, 2000, 5000]))
    ax_ic.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax_ic.yaxis.set_minor_locator(mticker.NullLocator())

    # Timeline strip: NBER recessions on the top row, events below with their numbers.
    for s, e in recessions:
        ax_tl.axvspan(s, e, ymin=0.55, ymax=0.95, color=NBER, lw=0)
    for ev in events.itertuples():
        s, e = month_span(ev.start_month, ev.end_month if ev.end_month != "ongoing" else last)
        color = SCARE if ev.classification == "scare" else EVENT
        e = max(e, s + pd.Timedelta(days=MIN_STRIP_DAYS))   # keep 1-month events visible in the strip
        ax_tl.axvspan(s, e, ymin=0.08, ymax=0.48, color=color, lw=0)
        ax_tl.text(s, 0.28, f" {ev.event}", va="center", ha="right", fontsize=8.5, color=INK2,
                   transform=ax_tl.get_xaxis_transform())
    ax_tl.set_yticks([0.75, 0.28], ["NBER recession", "Event"])
    ax_tl.set_ylim(0, 1)
    ax_tl.tick_params(axis="y", length=0, colors=INK2)

    # Recessive axes and grid.
    for ax in (ax_ur, ax_ic, ax_tl):
        ax.set_facecolor("#fcfcfb")
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.spines["left"].set_color(GRID)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=MUTED, labelcolor=INK2, labelsize=9)
    for ax in (ax_ur, ax_ic):
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
    ax_tl.spines["left"].set_visible(False)
    ax_tl.xaxis.set_major_locator(matplotlib.dates.YearLocator(5))
    ax_tl.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%Y"))
    ax_tl.set_xlim(pd.Timestamp("1967-01-01"), flags.index[-1] + pd.offsets.MonthEnd(0))

    # Title and legend.
    fig.suptitle("Labor-market deterioration events since 1967 (for review)", x=0.06, ha="left",
                 fontsize=14, color=INK, y=0.965)
    fig.text(0.06, 0.925, "Event = unemployment rate 3-month average ≥ 0.5 pt above its prior 12-month low, "
             "or SA initial claims 4-week average ≥ 25% above its prior 52-week low; ends after 6 quiet "
             "months. Final (latest) data.", fontsize=9, color=INK2)
    handles = [plt.Rectangle((0, 0), 1, 1, color=EVENT, alpha=0.35),
               plt.Rectangle((0, 0), 1, 1, color=SCARE, alpha=0.35),
               plt.Rectangle((0, 0), 1, 1, color=NBER)]
    ax_ur.legend(handles, ["Recession event (incl. early signal)", "Scare",
                           "NBER recession (timeline strip)"],
                 loc="upper left", frameon=False, fontsize=9, labelcolor=INK2, ncol=3)
    fig.text(0.06, 0.02, "Sources: BLS (UNRATE), U.S. Department of Labor (IC4WSA), NBER (USREC), via FRED.",
             fontsize=8, color=MUTED)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=130, facecolor=fig.get_facecolor())
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
