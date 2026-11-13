"""
Review WP8 test T4 (finding M2 part 3): can the same model predict MATERIAL events (unemployment up a point or more)?

Pre-registration: docs/model_tests_material_target.md (committed before this script). Pattern: state_candidates.py.

  target    an event with ur_peak_rise_pt >= 1.0 starts within the next 12 months: events #1, 2, 4, 5, 8, 9, 12 (and #13,
            whose 2020 window is excluded as in the main model) = score.load_events(drop=[3, 6, 7, 10, 11, 14, 15]),
            with score.HORIZON set to 12 (as score_followups.py does for its 12-month score)
  model     score.py unchanged: the 8 trigger measures (FINAL_FEATURES), weights >= 0, the same cross-validation,
            re-fitted each January from 1980 on months whose outcome was known (fitted from 1968)
  metric    Brier skill vs. the training base rate; 90% interval by 2-year block bootstrap (score_uncertainty.py),
            5,000 draws, seed 20261111; windows 1980-2026 (primary) and 2000-2026 (reported)
  bases     claims as first published from 2010 (reported first), then revised claims
Rule (fixed): show a second probability only if, on 1980-2026, skill >= +0.05 AND the bootstrap 5th percentile > 0,
on BOTH bases. Otherwise "not adopted".

Writes data/model/material_target_results.csv and material_target_predictions.csv.
Run:  python src/model/material_target.py      (~3-5 min)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "model"))
import score as S                      # noqa: E402
import score_uncertainty as SU         # noqa: E402  (2-year block bootstrap)

MODEL = ROOT / "data" / "model"
DROP = [3, 6, 7, 10, 11, 14, 15]
KEPT = [1, 2, 4, 5, 8, 9, 12, 13]
HORIZON = 12
FIRST_YEAR = 1980
SEED = 20261111
DRAWS = 5000
WINDOWS = {"1980-2026": "1980-01-01", "2000-2026": "2000-01-01", "2010-2026": "2010-01-01"}
MIN_SKILL = 0.05


def summarise(scored: pd.DataFrame) -> dict:
    """Skill and its bootstrap for the scored months (columns logit, base, y)."""
    b, b0, sk = SU.skill(scored["logit"], scored["y"], scored["base"])
    boot = SU.bootstrap_skill(scored, "logit", seed=SEED, draws=DRAWS)       # fresh generator, same seed
    return {"months": len(scored), "event_months": int(scored.y.sum()), "brier": b, "brier_base": b0, "skill": sk,
            "skill_p05": float(np.quantile(boot, 0.05)), "skill_p95": float(np.quantile(boot, 0.95)),
            "boot_draws_used": len(boot), "auc": SU.auc(scored["logit"], scored["y"])}


def main() -> None:
    F = pd.read_csv(MODEL / "features_monthly.csv", parse_dates=["month"]).set_index("month")
    S.DATA_END = F.index[-1]
    S.HORIZON = HORIZON                                    # score.py's functions read this setting
    trig = pd.read_csv(MODEL / "triggers_monthly.csv", parse_dates=["month"], keep_default_na=False)
    status = trig.set_index("month")["overall"]

    ev_all = S.load_events()
    material = sorted(ev_all[ev_all.ur_peak_rise_pt >= 1.0].event.astype(int))
    print(f"Events with ur_peak_rise_pt >= 1.0: {material}")
    if material != KEPT:
        raise SystemExit(f"Stop: the material events are {material}, not the pre-registered {KEPT}")
    ev = S.load_events(drop=DROP)
    assert sorted(ev.event.astype(int)) == KEPT
    tgt = S.target(F.index, ev)

    Fv = F.copy()                                          # claims as first published from 2010 (score.py's run)
    for a, b in [("claims_low", "claims_low_v"), ("claims_yoy", "claims_yoy_v"), ("cont_yoy", "cont_yoy_v")]:
        Fv[a] = F[b].where(F[b].notna(), F[a])

    rows, preds = [], {}
    for basis, frame in [("first published (2010 on)", Fv), ("revised", F)]:
        p, coefs, _ = S.run_oos(frame, tgt, status, S.FINAL_FEATURES, FIRST_YEAR, nonneg=True)
        j = p.join(tgt)
        preds[basis] = j.logit
        last = coefs.iloc[-1]
        print(f"\n{basis}: latest fit {int(last.year)}: C {last.C}, "
              + ", ".join(f"{f} {last[f]:+.3f}" for f in S.FINAL_FEATURES))
        for window, start in WINDOWS.items():
            scored = j[(j.index >= start) & j.usable.astype(bool)]
            r = {"basis": basis, "window": window, **summarise(scored)}
            rows.append(r)
            print(f"  {window}: {r['months']} months ({r['event_months']} followed by a material event within 12 "
                  f"months), Brier {r['brier']:.4f} vs base {r['brier_base']:.4f}, skill {r['skill']:+.3f}, "
                  f"90% {r['skill_p05']:+.2f} to {r['skill_p95']:+.2f}, AUC {r['auc']:.2f}")
    out = pd.DataFrame(rows)
    checks = {}
    for basis in ("first published (2010 on)", "revised"):
        r = out[(out.basis == basis) & (out.window == "1980-2026")].iloc[0]
        checks[f"{basis}: skill >= +0.05"] = bool(r.skill >= MIN_SKILL)
        checks[f"{basis}: 5th percentile > 0"] = bool(r.skill_p05 > 0)
    adopted = all(checks.values())
    out["rule_adopted"] = adopted
    out.to_csv(MODEL / "material_target_results.csv", index=False, float_format="%.4f")
    pd.DataFrame(preds).join(tgt[["y", "usable"]]).to_csv(MODEL / "material_target_predictions.csv",
                                                          date_format="%Y-%m-%d", index_label="month",
                                                          float_format="%.4f")
    print("\nRule (pre-registered), 1980-2026:")
    for k, v in checks.items():
        print(f"  {k}: {'yes' if v else 'no'}")
    print("Result: " + ("ADOPTED (enters through the January 2027 re-fit, with Troy's approval)" if adopted
                        else "not adopted; nothing is shown"))


if __name__ == "__main__":
    main()
