"""
Review chart for the Layer 1 triggers: reports/layer1_status.png.

  Top:     unemployment rate with events shaded (blue = recession or early signal, orange = scare)
  Middle:  overall Layer 1 status, month by month: the NEW rule (stage 3b review) above the plan's rule
  Bottom:  one strip per trigger, grouped: panel (counted in the new status), context only, removed. Lighter shades = revised data (before the series' first ALFRED vintage),
           grey = no data yet. Thin outlines across the strips mark each event, numbered as in events.csv.

Each month is colored by what was known on its last day (src/model/triggers.py). Not part of the website.
Run after triggers.py:
    python src/model/plot_triggers.py
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import to_rgb

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "data" / "model"
OUT = ROOT / "reports" / "layer1_status.png"

SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e4e3df"
STATUS = {"green": "#0ca30c", "amber": "#fab219", "red": "#d03b3b", "": "#e4e3df"}   # status palette
EVENT, SCARE, LINE = "#2a78d6", "#eb6834", "#2a78d6"
REVISED_STRENGTH = 0.45          # revised months drawn at 45% strength (blended toward the surface)


def rgb(color: str, strength: float = 1.0):
    c, s = np.array(to_rgb(color)), np.array(to_rgb(SURFACE))
    return s + (c - s) * strength


def main() -> None:
    trig = pd.read_csv(MODEL / "triggers_monthly.csv", parse_dates=["month"], keep_default_na=False)
    trig = trig.set_index("month")
    flags = pd.read_csv(MODEL / "event_flags_monthly.csv", parse_dates=["month"]).set_index("month")
    events = pd.read_csv(MODEL / "events.csv", dtype={"start_month": str, "end_month": str})
    cfg = pd.read_csv(ROOT / "config" / "triggers.csv").sort_values("order")

    months = trig.index
    x0 = mdates.date2num(months[0])
    x1 = mdates.date2num(months[-1] + pd.offsets.MonthBegin(1))

    def span(ev):
        s = pd.Timestamp(ev.start_month + "-01")
        e = pd.Timestamp((ev.end_month if ev.end_month != "ongoing" else f"{months[-1]:%Y-%m}") + "-01")
        return s, e + pd.offsets.MonthBegin(1)

    fig = plt.figure(figsize=(15, 10.5))
    fig.patch.set_facecolor(SURFACE)
    gs = fig.add_gridspec(3, 1, height_ratios=[3.0, 1.0, 4.4], hspace=0.10)
    ax_ur, ax_all, ax_t = (fig.add_subplot(gs[i]) for i in range(3))

    # --- Top: unemployment rate, events shaded ---
    for ev in events.itertuples():
        s, e = span(ev)
        scare = ev.classification == "scare"
        ax_ur.axvspan(s, e, color=SCARE if scare else EVENT, alpha=0.30 if scare else 0.16, lw=0)
        ax_ur.text(s, 1.0, str(ev.event), transform=ax_ur.get_xaxis_transform(), fontsize=8, color=INK2,
                   ha="left", va="bottom")
    ax_ur.plot(flags.index, flags.unrate, color=LINE, lw=1.5)
    ax_ur.set_ylabel("Unemployment rate (%)\n(final data)", color=INK2)
    ax_ur.grid(axis="y", color=GRID, lw=0.8)

    # --- Middle: the two overall-status rules ---
    rows = np.array([[rgb(STATUS[c]) for c in trig.overall], [rgb(STATUS[c]) for c in trig.overall_old]])
    ax_all.imshow(rows, aspect="auto", extent=[x0, x1, 2, 0], interpolation="nearest")
    ax_all.axhline(1, color=SURFACE, lw=2)
    ax_all.set_yticks([0.5, 1.5], ["Overall status: NEW rule", "Overall status: plan rule (old)"])

    # --- Bottom: one strip per trigger ---
    short = {"mfg_surveys": "Manufacturing surveys",
             "claims_vs_low": "Initial claims 4-wk avg vs. 52-wk low",
             "claims_yoy": "Initial claims vs. a year ago",
             "cont_claims_yoy": "Continued claims vs. a year ago",
             "temp_help": "Temp help jobs, 6-month change"}
    # Rows grouped by role: the panel (counted in the new status), then context only, then removed.
    role_order = {"core": 0, "panel": 1, "context": 2, "removed": 3}
    cfg = cfg.assign(r=cfg.layer1_role.map(role_order)).sort_values(["r", "order"])
    suffix = {"panel": "", "core": "", "context": " (context only)", "removed": " (removed)"}
    names = []
    for t, nm, o, role, note in zip(cfg.trigger_id, cfg.name, cfg.order, cfg.layer1_role, cfg.panel_note.fillna("")):
        label = f"{o}. {short.get(t, nm)}{suffix[role]}"
        if role == "panel" and note:
            label += f"\n({note})"
        names.append(label)
    grid = []
    for tid in cfg.trigger_id:
        colors, basis = trig[f"{tid}_color"], trig[f"{tid}_basis"]
        grid.append([rgb(STATUS[c], REVISED_STRENGTH if b == "revised" else 1.0)
                     for c, b in zip(colors, basis)])
    n = len(grid)
    ax_t.imshow(np.array(grid), aspect="auto", extent=[x0, x1, n, 0], interpolation="nearest")
    for i in range(1, n):
        ax_t.axhline(i, color=SURFACE, lw=2)          # 2px surface gap between strips
    ax_t.set_yticks(np.arange(n) + 0.5, names)
    n_panel = int(cfg.layer1_role.isin(["core", "panel"]).sum())
    ax_t.axhline(n_panel, color=INK, lw=1.2)          # line between the panel (counted) and the rest
    for ev in events.itertuples():                    # event outlines across the strips
        s, e = span(ev)
        for ax, top in ((ax_t, n), (ax_all, 2)):
            ax.add_patch(plt.Rectangle((mdates.date2num(s), 0), mdates.date2num(e) - mdates.date2num(s), top,
                                       fill=False, ec=INK, lw=0.9, alpha=0.7))

    # --- Axes styling ---
    for ax in (ax_ur, ax_all, ax_t):
        ax.set_facecolor(SURFACE)
        ax.set_xlim(x0, x1)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=MUTED, labelcolor=INK2, labelsize=9, length=0)
        ax.xaxis.set_major_locator(mdates.YearLocator(5))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax_ur.tick_params(labelbottom=False)
    ax_all.tick_params(labelbottom=False)

    fig.suptitle("Layer 1 triggers and overall status, 1967–2026 (real-time where available; for review)",
                 x=0.06, ha="left", fontsize=14, color=INK, y=0.975)
    fig.text(0.06, 0.945, "Each month uses what was published by its last day. NEW rule: red if trigger 1, 2 or 4 is "
             "red; amber if one of 1, 2, 4 is amber/red AND another panel trigger (1, 2, 4, 6, 8) is amber/red.\n"
             "Plan rule (old): red if any of triggers 1–4 is red; amber if two or more of all eight are amber/red. "
             "Triggers above the black line are the panel; below it, context only or removed (not counted).",
             fontsize=9, color=INK2, va="top")
    handles = [plt.Rectangle((0, 0), 1, 1, color=STATUS["green"]), plt.Rectangle((0, 0), 1, 1, color=STATUS["amber"]),
               plt.Rectangle((0, 0), 1, 1, color=STATUS["red"]),
               plt.Rectangle((0, 0), 1, 1, color=rgb(STATUS["amber"], REVISED_STRENGTH)),
               plt.Rectangle((0, 0), 1, 1, color=STATUS[""]),
               plt.Rectangle((0, 0), 1, 1, fill=False, ec=INK, lw=0.9),
               plt.Rectangle((0, 0), 1, 1, color=EVENT, alpha=0.3), plt.Rectangle((0, 0), 1, 1, color=SCARE, alpha=0.4)]
    labels = ["Green", "Amber", "Red", "Lighter = revised data (not real-time)", "No data",
              "Event (outline)", "Recession event / early signal", "Scare"]
    fig.legend(handles, labels, loc="lower left", bbox_to_anchor=(0.06, 0.015), ncol=8, frameon=False,
               fontsize=8.5, labelcolor=INK2)
    fig.text(0.06, 0.003, "Claims triggers use today's claims figures cut back by their release lag (DOL claims are "
             "kept at current vintage). Sources: BLS, U.S. Department of Labor, U.S. Treasury, Philadelphia Fed, "
             "New York Fed, Chicago Fed, NBER, via FRED/ALFRED.", fontsize=7.5, color=MUTED)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.subplots_adjust(left=0.22, right=0.98, top=0.885, bottom=0.08)
    fig.savefig(OUT, dpi=130, facecolor=SURFACE)
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
