"""
How the forecast ranges did before and during events (review WP3, 2026-11). Reads only.

The pooled coverage in forecast_evaluation.csv ("around events") mixes two situations that behave very differently:
forecasts made shortly BEFORE an event (the ranges held more outcomes than they should) and forecasts made once an
event was well UNDER WAY (they held fewer, and the middle ran too low). This script splits them.

Reads data/model/forecast_backtest.csv (written by forecast.py) and data/model/events.csv.
Writes data/model/forecast_evaluation_regimes.csv: one row per target x horizon x regime, plus "all".

Origins used: from 2000-01, on the first day of a month, outcome known, outside the 2020 window.
Regime of each origin (event #13, 2020, left out of the event list):
  during an event   in_progress and the event containing the origin has lasted 3+ months (start month = 1)
  before an event   not in an event, and an event starts within the forecast horizon (event_starts_within_h)
  other             everything else
Measures:
  origins
  rmse_ratio   sqrt(sum((realized - center)^2) / sum((realized - level_at_origin)^2)): below 1 beats "no change"
  mean_error   mean(realized - center): positive = the middle ran too low
  cover50      share with q25 <= realized <= q75 (should be about 0.5)
  cover80      share with q10 <= realized <= q90 (should be about 0.8)
  above_q90, below_q10   share above / below the 80% range

Run after forecast.py:  python src\\model\\forecast_regimes.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "data" / "model"
OUT = MODEL / "forecast_evaluation_regimes.csv"
REGIMES = ["during an event", "before an event", "other"]


def load_events() -> pd.DataFrame:
    ev = pd.read_csv(MODEL / "events.csv", dtype=str)
    ev = ev[ev.event != "13"].copy()                           # 2020 is not used to fit or test
    ev["start"] = pd.to_datetime(ev.start_month + "-01")
    ev["end"] = pd.to_datetime(ev.end_month + "-01")
    return ev


def event_age(month: pd.Timestamp, ev: pd.DataFrame) -> int:
    """Months since the start of the event containing `month` (start month = 1); 0 if not in an event."""
    e = ev[(ev.start <= month) & (month <= ev.end)]
    if not len(e):
        return 0
    s = e.iloc[0].start
    return (month.year - s.year) * 12 + month.month - s.month + 1


def add_regime(bt: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    bt = bt.copy()
    bt["age"] = bt.origin.map(lambda m: event_age(m, ev))
    in_progress = bt.in_progress.astype(bool)
    # An origin early in an event (in progress, under 3 months) is "other", not "before", even when a further event
    # starts within the horizon (as in the review's reference split).
    bt["regime"] = np.select([in_progress & (bt.age >= 3), ~in_progress & bt.event_starts_within_h.astype(bool)],
                             ["during an event", "before an event"], "other")
    return bt


def measures(g: pd.DataFrame) -> dict:
    err, err0 = g.realized - g.center, g.realized - g.level_at_origin
    return {"origins": len(g),
            "rmse_ratio": float(np.sqrt((err ** 2).sum() / (err0 ** 2).sum())),
            "mean_error": float(err.mean()),
            "cover50": float(((g.realized >= g.q25) & (g.realized <= g.q75)).mean()),
            "cover80": float(((g.realized >= g.q10) & (g.realized <= g.q90)).mean()),
            "above_q90": float((g.realized > g.q90).mean()),
            "below_q10": float((g.realized < g.q10).mean())}


def evaluate(bt: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    """The table, from a backtest frame (origin parsed as dates) and the event list."""
    bt = bt[(bt.origin >= "2000-01-01") & (bt.origin.dt.day == 1) & bt.realized.notna()
            & ~bt.covid_window.astype(bool)]
    bt = add_regime(bt, ev)
    rows = []
    for (target, horizon), g in bt.groupby(["target", "horizon"], sort=False):
        for regime in REGIMES + ["all"]:
            part = g if regime == "all" else g[g.regime == regime]
            if len(part):
                rows.append({"target": target, "horizon": int(horizon), "regime": regime, **measures(part)})
    return pd.DataFrame(rows)


def main() -> None:
    bt = pd.read_csv(MODEL / "forecast_backtest.csv", parse_dates=["origin"])
    out = evaluate(bt, load_events())
    out.round(4).to_csv(OUT, index=False)
    with pd.option_context("display.width", 160):
        print(out.round(3).to_string(index=False))
    print(f"\nWrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
