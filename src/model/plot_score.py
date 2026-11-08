"""
Review charts for the early-warning score (stage 3c). Not part of the website.

  reports/score_history.png      out-of-sample score since 2000 (re-fitted each January on earlier data only),
                                 events shaded, amber and red lines, the 2020 window marked; thin lines show
                                 two comparison runs (the model before the review; claims as published at the time)
  reports/score_reliability.png  calibration: in each band of predicted probability, the share of months
                                 that were really followed by an event start within 6 months

Run after score.py:
    python src/model/plot_score.py
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "data" / "model"
REPORTS = ROOT / "reports"

SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e4e3df"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"     # categorical slots 1-3
AMBER, RED = "#fab219", "#d03b3b"                        # status colors (threshold lines only)
EVENT, SCARE = "#2a78d6", "#eb6834"


def style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelcolor=INK2, labelsize=9)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def history():
    s = pd.read_csv(MODEL / "score_oos.csv", parse_dates=["month"]).set_index("month")
    s = s[s.index >= "2000-01-01"]
    ev = pd.read_csv(MODEL / "events.csv", dtype={"start_month": str, "end_month": str})
    theta = s.theta_amber.iloc[0]

    fig, ax = plt.subplots(figsize=(15, 6.2))
    fig.patch.set_facecolor(SURFACE)
    x = s.index + pd.Timedelta(days=14)                     # plot each month at its middle
    for e in ev.itertuples():
        start = pd.Timestamp(e.start_month + "-01")
        if start < pd.Timestamp("1999-01-01"):
            continue
        end = pd.Timestamp(e.end_month + "-01") + pd.offsets.MonthBegin(1)
        scare = e.classification == "scare"
        ax.axvspan(start, end, color=SCARE if scare else EVENT, alpha=0.28 if scare else 0.14, lw=0)
        ax.text(start, 1.01, f"#{e.event}", transform=ax.get_xaxis_transform(), fontsize=8, color=INK2)
    ax.axvspan(pd.Timestamp("2019-09-01"), pd.Timestamp("2021-04-01"), facecolor="none", edgecolor=MUTED,
               hatch="///", lw=0, alpha=0.5)
    ax.text(pd.Timestamp("2019-09-15"), 0.93, "2020: excluded\nfrom fitting", fontsize=8, color=INK2,
            transform=ax.get_xaxis_transform(), va="top")

    ax.plot(x, s.logit_claims_vintage, color=MUTED, lw=1.0, ls=":", label="Sensitivity: claims as published at the time (2010 on)")
    ax.plot(x, s.logit_previous_main, color=ORANGE, lw=1.1, label="Before review: unconstrained, without JOLTS")
    ax.plot(x, s.logit, color=BLUE, lw=2.0, label="Score (final model, out of sample)")
    ax.axhline(theta, color=AMBER, lw=1.4, ls="--")
    ax.axhline(0.5, color=RED, lw=1.4, ls="--")
    ax.text(s.index[-1], theta, f" Amber {theta:.0%}", color=INK2, fontsize=9, va="center", ha="left")
    ax.text(s.index[-1], 0.5, " Red 50%", color=INK2, fontsize=9, va="center", ha="left")

    style(ax)
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_ylabel("Probability an event starts within 6 months", color=INK2)
    ax.set_xlim(pd.Timestamp("2000-01-01"), s.index[-1] + pd.offsets.MonthBegin(1))
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.08), ncol=3, frameon=False, fontsize=9, labelcolor=INK2)
    fig.suptitle("Early-warning score, out of sample since 2000 (for review)", x=0.06, ha="left", fontsize=14,
                 color=INK, y=0.98)
    fig.text(0.06, 0.915, "Re-fitted every January on earlier data only; each month uses what was published by its "
             "last day. Shaded: events (blue = recession / early signal, orange = scare).", fontsize=9, color=INK2)
    fig.subplots_adjust(left=0.07, right=0.93, top=0.86, bottom=0.17)
    fig.savefig(REPORTS / "score_history.png", dpi=130, facecolor=SURFACE)


def calibration():
    r = pd.read_csv(MODEL / "score_reliability.csv")
    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    fig.patch.set_facecolor(SURFACE)
    ax.plot([0, 1], [0, 1], color=MUTED, lw=1, ls="--", label="Perfect calibration")
    names = {"logit": ("Final model", BLUE), "logit_previous": ("Before review", ORANGE),
             "equal": ("Equal-weight index", AQUA)}
    for model, (label, color) in names.items():
        d = r[(r.model == model) & (r.months > 0)]
        ax.plot(d.mean_predicted, d.observed_rate, color=color, lw=2, marker="o", ms=7, label=label)
        if model == "logit":
            for row in d.itertuples():
                ax.annotate(f"{row.months}", (row.mean_predicted, row.observed_rate), textcoords="offset points",
                            xytext=(6, -12), fontsize=8, color=INK2)
    style(ax)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_xlabel("Average predicted probability in the band", color=INK2)
    ax.set_ylabel("Share of months followed by an event start", color=INK2)
    ax.legend(loc="upper left", frameon=False, fontsize=9, labelcolor=INK2)
    fig.suptitle("Calibration of the out-of-sample score, 2000–2026", x=0.1, ha="left", fontsize=13, color=INK)
    fig.text(0.1, 0.905, "Bands 0–5, 5–10, 10–20, 20–35, 35–50, 50–100%; numbers = months in each band "
             "(final model)", fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.12, right=0.95, top=0.87, bottom=0.1)
    fig.savefig(REPORTS / "score_reliability.png", dpi=130, facecolor=SURFACE)


if __name__ == "__main__":
    REPORTS.mkdir(exist_ok=True)
    history()
    calibration()
    print("Wrote reports/score_history.png and reports/score_reliability.png")
