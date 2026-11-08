"""
Review charts for the stage 3d forecasts (not part of the website).

  reports/forecast_backtest_<target>.png   per target, one panel per horizon: what happened (line) and the
                                           out-of-sample fan made h periods earlier (median, 50% and 80% bands)
  reports/forecast_coverage.png            share of outcomes inside the 50% and 80% bands, all / event / quiet
  reports/forecast_events.png              fans made 6 and 3 months before events #9, #12, #14, #15 and 2020
  reports/forecast_current.png             today's fans with the 2001-type and 2008-type stress paths

Run after forecast.py:  python src/model/plot_forecast.py
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MODEL, REPORTS = ROOT / "data" / "model", ROOT / "reports"
SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e4e3df"
BLUE, ORANGE, AQUA, VIOLET = "#2a78d6", "#eb6834", "#1baf7a", "#6250d6"
EVENT, SCARE = "#2a78d6", "#eb6834"
UNIT = {"ur": 1.0, "ic": 100.0, "cc": 1.0}           # initial claims rate shown per 10,000 covered workers
YLABEL = {"ur": "Unemployment rate (%)", "ic": "SA initial claims rate\n(4-wk avg, per 10,000)",
          "cc": "SA continuing claims rate\n(4-wk avg, %)"}
TITLE = {"ur": "Unemployment rate", "ic": "SA initial claims rate", "cc": "SA continuing claims rate"}
HUNIT = {"ur": "months", "ic": "weeks", "cc": "weeks"}


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED, labelcolor=INK2, labelsize=8.5)
    ax.grid(axis="y", color=GRID, lw=0.7)
    ax.set_axisbelow(True)


def actual_series():
    ur = pd.read_csv(ROOT / "data" / "processed" / "UNRATE.csv", parse_dates=["date"]).set_index("date")["value"]
    w = pd.read_csv(MODEL / "claims_weekly.csv", parse_dates=["week_ended"]).set_index("week_ended")
    return {"ur": ur, "ic": w.ic_rate_sa.rolling(4).mean() * 100, "cc": w.cc_rate_sa.rolling(4).mean()}


def shade_events(ax, ev, start, end):
    for e in ev.itertuples():
        s = pd.Timestamp(e.start_month + "-01")
        en = pd.Timestamp(e.end_month + "-01") + pd.offsets.MonthBegin(1)
        if en < start or s > end:
            continue
        ax.axvspan(s, en, color=SCARE if e.classification == "scare" else EVENT,
                   alpha=0.22 if e.classification == "scare" else 0.10, lw=0)


def backtests(bt, act, ev):
    for t in ["ur", "ic", "cc"]:
        g = bt[bt.target == t]
        hs = sorted(g.horizon.unique())
        fig, axes = plt.subplots(len(hs), 1, figsize=(14, 10), sharex=True)
        fig.patch.set_facecolor(SURFACE)
        for ax, h in zip(axes, hs):
            x = g[g.horizon == h].sort_values("target_period")
            tp = pd.to_datetime(x.target_period)
            u = UNIT[t]
            shade_events(ax, ev, pd.Timestamp("2000-01-01"), tp.max())
            ax.fill_between(tp, x.q10 * u, x.q90 * u, color=BLUE, alpha=0.15, lw=0, label="80% band")
            ax.fill_between(tp, x.q25 * u, x.q75 * u, color=BLUE, alpha=0.28, lw=0, label="50% band")
            ax.plot(tp, x.center * u, color=BLUE, lw=1.2, label="Forecast median")
            a = act[t][(act[t].index >= tp.min()) & (act[t].index <= tp.max())]
            ax.plot(a.index, a.values, color=INK, lw=1.3, label="What happened")
            ax.axvspan(pd.Timestamp("2020-03-01"), pd.Timestamp("2021-06-01"), facecolor="none", edgecolor=MUTED,
                       hatch="///", lw=0, alpha=0.5)
            top = np.nanpercentile(np.r_[x.q90.values * u, a.values], 99) * 1.05
            ax.set_ylim(min(np.nanmin(x.q10 * u), np.nanmin(a)) * 0.95, top)
            ax.set_title(f"{h} {HUNIT[t]} ahead (made {h} {HUNIT[t]} before each date)", loc="left", fontsize=10, color=INK2)
            ax.set_ylabel(YLABEL[t], color=INK2, fontsize=9)
            style(ax)
        axes[0].legend(loc="upper right", frameon=False, fontsize=8.5, labelcolor=INK2, ncol=4)
        axes[-1].xaxis.set_major_locator(mdates.YearLocator(2))
        axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        fig.suptitle(f"{TITLE[t]}: out-of-sample forecast fans vs. what happened, 2000–2026 (for review)", x=0.06,
                     ha="left", fontsize=13, color=INK)
        fig.text(0.06, 0.935, "Hatched: 2020 (reported separately; y-axis capped, so the 2020 spike runs off the "
                 "chart). Shaded: events (blue = recession / early signal, orange = scare).", fontsize=8.5, color=INK2)
        fig.subplots_adjust(left=0.09, right=0.98, top=0.9, bottom=0.05, hspace=0.25)
        fig.savefig(REPORTS / f"forecast_backtest_{t}.png", dpi=120, facecolor=SURFACE)
        plt.close(fig)


def coverage(evl):
    e = evl[evl.subset.str.startswith("2000")].copy()
    e["label"] = e.target.map(TITLE) + "\n" + e.horizon.astype(str) + " " + e.target.map(HUNIT)
    fig, axes = plt.subplots(1, 2, figsize=(15, 6), sharey=True)
    fig.patch.set_facecolor(SURFACE)
    x = np.arange(len(e))
    for ax, band in zip(axes, ["50", "80"]):
        tgt = int(band) / 100
        ax.axhspan(tgt - 0.10, tgt + 0.10, color=GRID, alpha=0.6, lw=0)
        ax.axhline(tgt, color=MUTED, lw=1, ls="--")
        for i, (col, color, lab) in enumerate([(f"cover{band}", BLUE, "All months"),
                                               (f"cover{band}_event", ORANGE, "Event in progress or starting"),
                                               (f"cover{band}_quiet", AQUA, "Quiet months")]):
            ax.bar(x + (i - 1) * 0.27, e[col], width=0.25, color=color, label=lab)
        ax.set_xticks(x, e.label, fontsize=7.5)
        ax.set_title(f"{band}% bands: share of outcomes inside (target {band}%, grey = ±10 points)", loc="left",
                     fontsize=10, color=INK2)
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        style(ax)
    axes[0].legend(frameon=False, fontsize=8.5, labelcolor=INK2, loc="upper left")
    fig.suptitle("Band coverage, out of sample 2000–2026 excluding 2020 (for review)", x=0.06, ha="left", fontsize=13, color=INK)
    fig.subplots_adjust(left=0.06, right=0.99, top=0.86, bottom=0.14, wspace=0.05)
    fig.savefig(REPORTS / "forecast_coverage.png", dpi=120, facecolor=SURFACE)
    plt.close(fig)


def events(bt, act, ev):
    evs = [9, 12, 14, 15, 13]
    fig, axes = plt.subplots(len(evs), 3, figsize=(15, 16))
    fig.patch.set_facecolor(SURFACE)
    for r, e in enumerate(evs):
        S = pd.Timestamp(ev.loc[ev.event == e, "start_month"].iloc[0] + "-01")
        cls = ev.loc[ev.event == e, "classification"].iloc[0]
        for c, t in enumerate(["ur", "ic", "cc"]):
            ax = axes[r, c]
            u = UNIT[t]
            a = act[t][(act[t].index >= S - pd.DateOffset(months=12)) & (act[t].index <= S + pd.DateOffset(months=15))]
            ax.axvline(S, color=MUTED, lw=1, ls="--")
            ax.plot(a.index, a.values, color=INK, lw=1.4)
            for lead, color, off in [(6, VIOLET, -6), (3, ORANGE, 6)]:
                o = S - pd.DateOffset(months=lead)
                g = bt[(bt.target == t) & (pd.to_datetime(bt.origin) == o)]
                for row in g.itertuples():
                    tp = pd.Timestamp(row.target_period) + pd.Timedelta(days=off)
                    ax.plot([tp, tp], [row.q10 * u, row.q90 * u], color=color, lw=2.2, alpha=0.8)
                    ax.plot([tp, tp], [row.q25 * u, row.q75 * u], color=color, lw=5, alpha=0.9)
                    ax.plot(tp, row.center * u, "o", color=SURFACE, mec=color, ms=4)
            if r == 0:
                ax.set_title(TITLE[t], fontsize=10, color=INK)
            if c == 0:
                ax.set_ylabel(f"#{e} {S:%Y-%m}\n{cls}", color=INK2, fontsize=9)
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
            style(ax)
    fig.suptitle("Fans made 6 months (violet) and 3 months (orange) before each event start (dashed line), for review",
                 x=0.05, ha="left", fontsize=13, color=INK)
    fig.text(0.05, 0.955, "Each bar: 80% band (thin), 50% band (thick), median (dot), at the 3 horizons; black line = what "
             "happened. 2020 (#13) was not used to fit anything.", fontsize=9, color=INK2)
    fig.subplots_adjust(left=0.07, right=0.99, top=0.93, bottom=0.03, hspace=0.35, wspace=0.18)
    fig.savefig(REPORTS / "forecast_events.png", dpi=110, facecolor=SURFACE)
    plt.close(fig)


def current(cur, stress, act, evl):
    gate = evl[evl.subset.str.startswith("2000")].set_index(["target", "horizon"]).gate_pass
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.8))
    fig.patch.set_facecolor(SURFACE)
    for ax, t in zip(axes, ["ur", "ic", "cc"]):
        u = UNIT[t]
        g = cur[cur.target == t].sort_values("horizon")
        L = pd.Timestamp(g.latest_period.iloc[0])
        a = act[t][act[t].index >= L - pd.DateOffset(months=30)]
        ax.plot(a.index, a.values, color=INK, lw=1.4, label="History")
        xs = [L] + list(pd.to_datetime(g.target_period))
        y0 = g.level_at_origin.iloc[0] * u
        for lo, hi, alpha, lab in [("q10", "q90", 0.15, "80% band"), ("q25", "q75", 0.3, "50% band")]:
            ax.fill_between(xs, [y0] + list(g[lo] * u), [y0] + list(g[hi] * u), color=BLUE, alpha=alpha, lw=0, label=lab)
        ax.plot(xs, [y0] + list(g.center * u), color=BLUE, lw=1.8, label="Median")
        for row in g.itertuples():
            if not gate.get((t, row.horizon), True):
                ax.annotate("fails gate:\nnot shown", (pd.Timestamp(row.target_period), row.q90 * u), fontsize=7.5,
                            color=INK2, ha="center", va="bottom")
        s = stress[stress.target == t]
        for sc, color, ls in [("2001-type (#9)", ORANGE, "--"), ("2008-type (#12)", VIOLET, "--")]:
            x = s[s.scenario == sc]
            ax.plot(pd.to_datetime(x.period), x.level * u, color=color, lw=1.4, ls=ls, label=f"What-if: {sc}")
        ax.set_title(TITLE[t], loc="left", fontsize=11, color=INK)
        ax.set_ylabel(YLABEL[t], color=INK2, fontsize=9)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.xaxis.set_major_locator(mdates.YearLocator())
        style(ax)
    axes[0].legend(frameon=False, fontsize=8, labelcolor=INK2, loc="upper left")
    fig.suptitle(f"Forecast fans from {pd.Timestamp(cur.origin.iloc[0]):%B %Y} data, with stress paths (what-ifs, not "
                 "forecasts) — for review", x=0.05, ha="left", fontsize=13, color=INK)
    fig.subplots_adjust(left=0.06, right=0.99, top=0.86, bottom=0.08, wspace=0.28)
    fig.savefig(REPORTS / "forecast_current.png", dpi=120, facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    bt = pd.read_csv(MODEL / "forecast_backtest.csv")
    evl = pd.read_csv(MODEL / "forecast_evaluation.csv")
    ev = pd.read_csv(MODEL / "events.csv", dtype={"start_month": str, "end_month": str})
    act = actual_series()
    backtests(bt, act, ev)
    coverage(evl)
    events(bt, act, ev)
    current(pd.read_csv(MODEL / "forecast_current.csv"), pd.read_csv(MODEL / "stress_paths.csv"), act, evl)
    print("Wrote reports/forecast_*.png")
