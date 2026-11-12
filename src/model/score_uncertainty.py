"""
How sure are we of the early-warning score's tested record? (review WP1, 2026-11)

Reads the out-of-sample score history written by score.py (data/model/score_oos.csv) and the event list
(data/model/events.csv). Writes data/model/score_skill_summary.csv: one row per claims basis.

    revised          column `logit`: the score with today's revised claims
    first_published  column `logit_claims_vintage`: claims as published at the time from 2010
                     (identical to `logit` before 2010)

For each basis, over the scored months (from 2000-01, `usable` = outside events and the 2020 window, outcome known):
  months, event_months     how many months, and how many were followed by an event start within 6 months (y = 1)
  events_in_test           how many distinct events those y = 1 months lead into
  brier, brier_base, skill Brier score of the score, of always quoting the base rate, and the skill
                           1 - brier / brier_base
  skill_p05, skill_p95,    block bootstrap of the skill: whole 2-calendar-year blocks resampled with replacement,
  share_le_0               5,000 draws; 5th / 95th percentiles and the share of draws at or below zero
  auc                      chance that a random y = 1 month scored higher than a random y = 0 month
  n_/hit_ red/amber/green  months in each colour band and the share followed by an event (red >= 50%,
                           amber 20-50%, green < 20%; bands on the probability, without the hysteresis rule)
Plus, from ALL months since 2000-01 on revised claims: the longest run of consecutive months at 20% or more.

Run after score.py:  python src\\model\\score_uncertainty.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "data" / "model"
OUT = MODEL / "score_skill_summary.csv"

BASES = {"revised": "logit", "first_published": "logit_claims_vintage"}
AMBER, RED = 0.20, 0.50
SEED = 20261111            # fixed, so every run gives the same bootstrap percentiles
DRAWS = 5000
BLOCK_YEARS = 2


def skill(p: pd.Series, y: pd.Series, base: pd.Series) -> tuple[float, float, float]:
    """(Brier of p, Brier of the base rate, skill = 1 - Brier / base Brier)."""
    b = float(((p - y) ** 2).mean())
    b0 = float(((base - y) ** 2).mean())
    return b, b0, 1 - b / b0


def bootstrap_skill(df: pd.DataFrame, col: str, seed: int = SEED, draws: int = DRAWS) -> np.ndarray:
    """Skill in each of `draws` block-bootstrap samples. Blocks are consecutive 2-calendar-year groups
    (2000-01, 2002-03, ...; the last may hold one year), so months close in time stay together."""
    rng = np.random.default_rng(seed)
    years = sorted(df.index.year.unique())
    blocks = [years[i:i + BLOCK_YEARS] for i in range(0, len(years), BLOCK_YEARS)]
    parts = [df[df.index.year.isin(b)] for b in blocks]
    out = []
    for _ in range(draws):
        pick = rng.integers(0, len(parts), len(parts))          # as many blocks as exist, with replacement
        s = pd.concat([parts[i] for i in pick])
        b0 = ((s["base"] - s["y"]) ** 2).mean()
        if b0 == 0:                                              # no event in the draw: skill undefined
            continue
        out.append(1 - ((s[col] - s["y"]) ** 2).mean() / b0)
    return np.array(out)


def auc(p: pd.Series, y: pd.Series) -> float:
    """Area under the ROC curve from ranks (ties share their average rank)."""
    r = p.rank()
    n1, n0 = int(y.sum()), int((1 - y).sum())
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def events_behind(months: pd.DatetimeIndex, events: pd.DataFrame) -> int:
    """Distinct events whose start is 1 to 6 months after each given (y = 1) month."""
    found = set()
    for m in months:
        e = events[(events.start > m) & (events.start <= m + pd.DateOffset(months=6))]
        if len(e):
            found.add(int(e.iloc[0].event))
    return len(found)


def longest_run(p: pd.Series, at_least: float) -> tuple[int, str, str]:
    """Longest run of consecutive months with p >= at_least: (length, first month, last month)."""
    best, start, cur, cur_start = 0, None, 0, None
    for month, value in p.items():
        if value >= at_least:
            cur, cur_start = cur + 1, (cur_start if cur else month)
            if cur > best:
                best, start, end = cur, cur_start, month
        else:
            cur = 0
    return (best, start.strftime("%Y-%m"), end.strftime("%Y-%m")) if best else (0, "", "")


def summarise(scored: pd.DataFrame, events: pd.DataFrame, col: str) -> dict:
    p, y = scored[col], scored["y"]
    b, b0, sk = skill(p, y, scored["base"])
    boot = bootstrap_skill(scored, col)
    row = {"months": len(scored), "event_months": int(y.sum()),
           "events_in_test": events_behind(scored.index[y == 1], events),
           "brier": round(b, 5), "brier_base": round(b0, 5), "skill": round(sk, 4),
           "skill_p05": round(float(np.quantile(boot, 0.05)), 4), "skill_p95": round(float(np.quantile(boot, 0.95)), 4),
           "share_le_0": round(float((boot <= 0).mean()), 4), "auc": round(auc(p, y), 4)}
    for name, mask in [("red", p >= RED), ("amber", (p >= AMBER) & (p < RED)), ("green", p < AMBER)]:
        row[f"n_{name}"] = int(mask.sum())
        row[f"hit_{name}"] = round(float(y[mask].mean()), 4) if mask.any() else np.nan
    return row


def main() -> None:
    d = pd.read_csv(MODEL / "score_oos.csv", parse_dates=["month"]).set_index("month").sort_index()
    events = pd.read_csv(MODEL / "events.csv", dtype=str)
    events["start"] = pd.to_datetime(events.start_month + "-01")
    since2000 = d[d.index >= "2000-01-01"]
    scored = since2000[since2000["usable"].astype(bool)]

    run, run_start, run_end = longest_run(since2000["logit"], AMBER)   # all months, revised claims
    rows = []
    for basis, col in BASES.items():
        row = {"basis": basis, **summarise(scored, events, col)}
        row.update({"longest_elevated_run_months": run, "longest_elevated_run_start": run_start,
                    "longest_elevated_run_end": run_end})
        rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    with pd.option_context("display.width", 200, "display.max_columns", 50):
        print(out.T.to_string(header=False))
    print(f"\nWrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
