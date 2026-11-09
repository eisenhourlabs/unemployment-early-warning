"""
Stage 4e: pre-registered tests of two state-based inputs for the early-warning score (docs/phase4_model_tests.md,
committed before this script was written).

  C1  state claims diffusion: covered-employment-weighted share of states with 4-week average initial claims up 20%+
      on a year earlier (and, as sensitivity only, at 10% and 30%)
  C2  weighted claims: log(1 + weighted 4-week initial claims rate year-on-year change)

Real time: a month's value is the latest week w with w + 12 days <= the month's last day (state release lag, measured
2026-11-09). Both exist from 1996; before that they are missing (0 after standardization, the Phase 3 convention).

Comparisons (Phase 3 machinery in score.py, unchanged; weights >= 0):
  A  same window: baseline (final Phase 3 model) and baseline + candidate both fitted from 1996-01, scored 2000 on
     where both predict (from 2001 in practice), 2020 excluded            -> the primary test
  S1 A with the national claims inputs as first published (FRED vintages, 2010 on), scored 2010 on
  S2 A with the four shock scares not counted as events
  S3 C1 at 10% and 30% (A)
  B  full history: both fitted from 1968 (candidate 0 before 1996), scored 2000 on
Skill = 1 - Brier / Brier(base rate); difference = candidate - baseline on identical months, with a 90% block
bootstrap by episode (blocks cut 12 months before each event start since 2000; 5,000 draws, seed 20261109).

Adoption (pre-registered): A difference >= +0.02 with its 90% interval above 0, AND S1 >= -0.02, AND B >= -0.02;
at most one candidate (the larger A difference).

Output: data/model/state_candidates_features.csv, state_candidates_results.csv, state_candidates_predictions.csv.
Run:  python src/model/state_candidates.py      (~3-6 min)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "model"))
sys.path.insert(0, str(ROOT / "src" / "transforms"))
import score as S             # noqa: E402
import state_measures as sm   # noqa: E402

MODEL = ROOT / "data" / "model"
STATES = ROOT / "data" / "processed" / "states"
LAG_DAYS = 12
STATE_START = "1996-01-01"
SEED = 20261109
N_BOOT = 5000
EPISODE_EVENTS = [9, 10, 11, 12, 14, 15]
CANDIDATES = {"C1": "diffusion_20", "C2": "weighted_claims"}


# ---------------------------------------------------------------------------------------------------
# Monthly, real-time candidate inputs
# ---------------------------------------------------------------------------------------------------
def monthly_real_time(weekly: pd.Series, months: pd.DatetimeIndex) -> pd.Series:
    """For each month (first-of-month index), the latest weekly value published by the month's last day."""
    s = weekly.dropna().copy()
    s.index = s.index + pd.Timedelta(days=LAG_DAYS)          # date each week's figure became available
    month_ends = months + pd.offsets.MonthEnd(0)
    out = s.reindex(s.index.union(month_ends)).ffill().reindex(month_ends)
    # never carry a value forward more than 5 weeks (a gap in the data stays a gap)
    last_avail = pd.Series(s.index, index=s.index).reindex(s.index.union(month_ends)).ffill().reindex(month_ends)
    out[(month_ends - last_avail) > pd.Timedelta(days=35)] = np.nan
    out.index = months
    return out


def candidate_features(months: pd.DatetimeIndex) -> pd.DataFrame:
    diff = pd.read_csv(STATES / "diffusion_weekly.csv", parse_dates=["week_ended"]).set_index("week_ended")
    wtd = pd.read_csv(STATES / "weighted_weekly.csv", parse_dates=["week_ended"]).set_index("week_ended")
    weekly = pd.read_csv(STATES / "state_weekly.csv", parse_dates=["week_ended"])
    w = sm.weights()
    cols = {"diffusion_20": diff.diffusion_ce_weighted_pct,
            "weighted_claims": np.log1p(wtd.weighted_ic_yoy_pct / 100)}
    for th in (10, 30):                                       # sensitivity only (never used to choose)
        d = sm.diffusion(weekly, w, threshold=th).set_index("week_ended")
        cols[f"diffusion_{th}"] = d.diffusion_ce_weighted_pct
    return pd.DataFrame({k: monthly_real_time(v, months) for k, v in cols.items()})


# ---------------------------------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------------------------------
def blocks(months: pd.DatetimeIndex, ev: pd.DataFrame) -> np.ndarray:
    """Episode block of each scored month: cut 12 months before each event start since 2000."""
    cuts = sorted(ev[ev.event.isin(EPISODE_EVENTS)].start - pd.DateOffset(months=12))
    return np.searchsorted(np.array(cuts, dtype="datetime64[ns]"), months.values, side="right")


def compare(base_pred, cand_pred, tgt, ev, start, rng) -> dict:
    idx = base_pred.index.intersection(cand_pred.index)
    idx = idx[(idx >= start) & tgt.loc[idx, "usable"].values]
    y = tgt.loc[idx, "y"].values
    eb = (base_pred.loc[idx, "logit"].values - y) ** 2
    ec = (cand_pred.loc[idx, "logit"].values - y) ** 2
    e0 = (base_pred.loc[idx, "base"].values - y) ** 2           # same training windows -> same base rate
    skill_b, skill_c = 1 - eb.mean() / e0.mean(), 1 - ec.mean() / e0.mean()
    blk = blocks(idx, ev)
    ids = np.unique(blk)
    sums = {k: np.array([v[blk == i].sum() for i in ids]) for k, v in (("b", eb), ("c", ec), ("0", e0))}
    n = np.array([(blk == i).sum() for i in ids])
    boots = []
    for _ in range(N_BOOT):
        pick = rng.integers(0, len(ids), len(ids))
        tot0 = sums["0"][pick].sum()
        boots.append((sums["b"][pick].sum() - sums["c"][pick].sum()) / tot0)
    return {"months": len(idx), "first_month": f"{idx.min():%Y-%m}", "event_months": int(y.sum()),
            "episodes": len(ids), "skill_baseline": skill_b, "skill_candidate": skill_c,
            "difference": skill_c - skill_b, "ci90_low": float(np.quantile(boots, 0.05)),
            "ci90_high": float(np.quantile(boots, 0.95))}


def main() -> None:
    F = pd.read_csv(MODEL / "features_monthly.csv", parse_dates=["month"]).set_index("month")
    S.DATA_END = F.index[-1]
    trig = pd.read_csv(MODEL / "triggers_monthly.csv", parse_dates=["month"], keep_default_na=False)
    status = trig.set_index("month")["overall"]
    ev_all = S.load_events()
    ev_ns = S.load_events(drop=S.SHOCK_SCARES)
    tgt, tgt_ns = S.target(F.index, ev_all), S.target(F.index, ev_ns)

    cand = candidate_features(F.index)
    cand.to_csv(MODEL / "state_candidates_features.csv", date_format="%Y-%m-%d", index_label="month",
                float_format="%.5f")
    F = F.join(cand)
    Fv = F.copy()                                              # national claims as first published (2010 on)
    for a, b in [("claims_low", "claims_low_v"), ("claims_yoy", "claims_yoy_v"), ("cont_yoy", "cont_yoy_v")]:
        Fv[a] = F[b].where(F[b].notna(), F[a])
    print(f"Candidate inputs: {cand.dropna(how='all').index.min():%Y-%m} to {cand.index.max():%Y-%m}")

    rng = np.random.default_rng(SEED)
    base = S.FINAL_FEATURES
    runs = {"A": dict(Fx=F, t=tgt, ev=ev_all, fit_from=STATE_START, start="2000-01-01"),
            "S1 claims as first published": dict(Fx=Fv, t=tgt, ev=ev_all, fit_from=STATE_START, start="2010-01-01"),
            "S2 shock scares not events": dict(Fx=F, t=tgt_ns, ev=ev_ns, fit_from=STATE_START, start="2000-01-01"),
            "B full history": dict(Fx=F, t=tgt, ev=ev_all, fit_from=S.FIRST_FIT, start="2000-01-01")}
    cache, results, preds = {}, [], []

    def oos(run, features):
        key = (run, tuple(features))
        if key not in cache:
            r = runs[run]
            p, c, _ = S.run_oos(r["Fx"], r["t"], status, features, 2000, fit_from=r["fit_from"], nonneg=True)
            cache[key] = (p, c)
        return cache[key]

    plan = [(run, name, col) for run in runs for name, col in CANDIDATES.items()]
    plan += [("A", "C1 at 10% (sensitivity)", "diffusion_10"), ("A", "C1 at 30% (sensitivity)", "diffusion_30")]
    for run, name, col in plan:
        r = runs[run]
        pb, _ = oos(run, base)
        pc, cc = oos(run, base + [col])
        res = compare(pb, pc, r["t"], r["ev"], r["start"], rng)
        weight = float(cc.iloc[-1].get(col, np.nan)) if len(cc) else np.nan
        results.append({"run": run, "candidate": name, "input": col, **res, "latest_weight": weight,
                        "years_weight_positive": int((cc[col] > 1e-9).sum()) if col in cc else 0,
                        "fit_years": len(cc)})
        preds.append(pc[["logit"]].rename(columns={"logit": f"{run} | {name}"}))
        print(f"  {run:30s} {name:26s} skill {res['skill_baseline']:+.3f} -> {res['skill_candidate']:+.3f} "
              f"(diff {res['difference']:+.3f}, 90% {res['ci90_low']:+.3f} to {res['ci90_high']:+.3f}; "
              f"{res['months']} months from {res['first_month']}, {res['episodes']} episodes; latest weight {weight:.3f})")
        if name in CANDIDATES and run == "A":
            preds.append(pb[["logit"]].rename(columns={"logit": f"{run} | baseline"}))

    out = pd.DataFrame(results)
    out.to_csv(MODEL / "state_candidates_results.csv", index=False, float_format="%.4f")
    pd.concat(preds, axis=1).to_csv(MODEL / "state_candidates_predictions.csv", date_format="%Y-%m-%d",
                                    index_label="month", float_format="%.4f")

    # ---- the pre-registered adoption rule ----
    print("\nAdoption rule (pre-registered):")
    passed = {}
    for name in CANDIDATES:
        a = out[(out.run == "A") & (out.candidate == name)].iloc[0]
        s1 = out[(out.run == "S1 claims as first published") & (out.candidate == name)].iloc[0]
        b = out[(out.run == "B full history") & (out.candidate == name)].iloc[0]
        checks = {"A diff >= +0.02": a.difference >= 0.02, "A 90% interval above 0": a.ci90_low > 0,
                  "S1 diff >= -0.02": s1.difference >= -0.02, "B diff >= -0.02": b.difference >= -0.02}
        ok = all(checks.values())
        print(f"  {name}: {'ADOPT' if ok else 'not adopted'}  " + "; ".join(f"{k}: {'yes' if v else 'no'}"
                                                                         for k, v in checks.items()))
        if ok:
            passed[name] = a.difference
    choice = max(passed, key=passed.get) if passed else None
    print(f"Result: {choice + ' adopted (goes into the January 2027 re-fit)' if choice else 'neither candidate adopted; model unchanged'}")


if __name__ == "__main__":
    main()
