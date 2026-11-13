"""
Simple-rule benchmarks for the early-warning score (review WP9, item C12).

Question: how much of the score's tested skill comes from its single strongest input? Each model is scored out of
sample exactly as the final score is (src/model/score.py: re-fitted every January from 1980 on what was known then,
ridge logistic with weights >= 0, the same target), and the skill is measured on the months from 2000 on that are
"usable" (no event under way, outside the 2020 window, outcome known):
  claims_only       new claims vs. their 52-week low, alone
  claims_and_sahm   new claims vs. their low + the Sahm indicator
  full              the eight inputs of the final score (FINAL_FEATURES)
each on two claims bases:
  revised           today's revised claims, cut back by their release lag (as in every test)
  first_published   claims as first published (FRED vintages from 2010; the `_v` columns of features_monthly.csv)
plus the confirmation-trigger rule panel used as a forecast (model `layer1`, revised claims), copied from
data/model/score_results.csv.

This script only imports the functions of score.py (its main() is never called), so it writes nothing but
data/model/score_simple_benchmarks.csv (model, basis, months, brier, brier_base, skill).

Run after score.py (January re-fit chain): python src\\model\\score_simple_benchmarks.py   (about 1 minute)
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "model"))
import score as S   # noqa: E402  (functions only)

MODEL = ROOT / "data" / "model"
OUT = MODEL / "score_simple_benchmarks.csv"
SCORED_FROM = "2000-01-01"
MODELS = {"claims_only": ["claims_low"], "claims_and_sahm": ["claims_low", "sahm"], "full": S.FINAL_FEATURES}
VINTAGE_COLUMNS = [("claims_low", "claims_low_v"), ("claims_yoy", "claims_yoy_v"), ("cont_yoy", "cont_yoy_v")]


def first_published(F: pd.DataFrame) -> pd.DataFrame:
    """The claims measures as first published where FRED has vintages (from 2010), else today's figures."""
    Fv = F.copy()
    for a, b in VINTAGE_COLUMNS:
        if b in F.columns:
            Fv[a] = F[b].where(F[b].notna(), F[a])
    return Fv


def skill_row(model: str, basis: str, pred: pd.DataFrame, tgt: pd.DataFrame) -> dict:
    """Brier score of the out-of-sample predictions vs. the long-run base rate, usable months from 2000."""
    j = pred.join(tgt)
    t = j[(j.index >= SCORED_FROM) & j.usable]
    b = S.brier(t.logit, t.y)
    b0 = S.brier(t.base, t.y)
    return {"model": model, "basis": basis, "months": len(t), "brier": round(b, 6), "brier_base": round(b0, 6),
            "skill": round(1 - b / b0, 6)}


def main() -> None:
    F = pd.read_csv(MODEL / "features_monthly.csv", parse_dates=["month"]).set_index("month")
    S.DATA_END = F.index[-1]
    trig = pd.read_csv(MODEL / "triggers_monthly.csv", parse_dates=["month"], keep_default_na=False)
    status = trig.set_index("month")["overall"]
    tgt = S.target(F.index, S.load_events())
    rows = []
    for basis, frame in (("revised", F), ("first_published", first_published(F))):
        for model, features in MODELS.items():
            pred, _, _ = S.run_oos(frame, tgt, status, features, 1980, nonneg=True)
            rows.append(skill_row(model, basis, pred, tgt))
            print(f"  {model:16} {basis:16} months {rows[-1]['months']}  skill {rows[-1]['skill']:+.3f}", flush=True)
    # The rule panel (confirmation triggers) as a forecast, from score.py's own results (revised claims)
    res = pd.read_csv(MODEL / "score_results.csv")
    r = res[(res.run == "final") & (res.model == "layer1")].iloc[0]
    rows.append({"model": "rule_panel", "basis": "revised", "months": int(r.months_scored), "brier": round(r.brier, 6),
                 "brier_base": round(r.brier_base, 6), "skill": round(r.skill_vs_base, 6)})
    print(f"  {'rule_panel':16} {'revised':16} months {rows[-1]['months']}  skill {rows[-1]['skill']:+.3f}")
    pd.DataFrame(rows).to_csv(OUT, index=False)
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
