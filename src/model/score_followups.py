"""
Stage 3d, Part A: follow-ups on the final early-warning score (src/model/score.py, docs/model.md 5.10).

  A1  What drove the score from 2024-10 on: contribution table for every month with score >= 20%.
  A2  A claims input that depends less on seasonal factors (NSA claims vs. the same weeks a year earlier),
      added to or replacing the SA claims measures; scored on today's data and on claims as first published.
  A3  Recalibration (Platt-style: a logistic fit of the outcome on logit(score)), estimated each January on
      EARLIER out-of-sample scores only; Brier and reliability with and without; episodes per band and a
      block-bootstrap interval (resampling whole episodes) for the observed rate in the 35-50% and 50-100% bands.
  A4  Colour stability: month-to-month and week-to-week colour changes; hysteresis and a 2-of-3-months rule,
      judged on pre-2000 data; effect on leads, false ambers / reds and flips after 2000.
  A5  The same final model with 3-month and 12-month targets (out of sample from 2000), for the forecast fans.

Everything uses the final model's settings from score.py (eight trigger measures, weights >= 0, ridge penalty
by time-ordered cross-validation, re-fitted each January on data whose outcome was known).

Writes data/model/score_followups_*.csv and data/model/score_horizons.csv.
Run it (after score.py):
    python src/model/score_followups.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "model"))
import score as S                     # noqa: E402  (the final model's code)
from features import features_at       # noqa: E402

MODEL = ROOT / "data" / "model"
AMBER, RED = 0.20, 0.50                # final thresholds (docs/model.md 5.10)
A1_FROM = "2024-10-01"
RNG = np.random.default_rng(20261108)  # fixed seed so the bootstrap is reproducible


# ---------------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------------
def load():
    F = pd.read_csv(MODEL / "features_monthly.csv", parse_dates=["month"]).set_index("month")
    S.DATA_END = F.index[-1]
    trig = pd.read_csv(MODEL / "triggers_monthly.csv", parse_dates=["month"], keep_default_na=False)
    status = trig.set_index("month")["overall"]
    ev = S.load_events()
    return F, status, ev


def train_index(tgt, year, fit_from=S.FIRST_FIT):
    """Training months for the January re-fit of `year` (outcome known by then), as in score.run_oos."""
    known = pd.Timestamp(f"{year}-01-01") - pd.DateOffset(months=S.HORIZON + 1)
    return tgt.index[tgt.usable & (tgt.index <= known) & (tgt.index >= fit_from)]


def colours(p: pd.Series, amber=AMBER, red=RED) -> pd.Series:
    return pd.Series(np.where(p >= red, "red", np.where(p >= amber, "amber", "green")), index=p.index)


def hysteresis(p: pd.Series, amber_in, amber_out, red_in, red_out) -> pd.Series:
    """Colour with hysteresis: a colour is entered at the 'in' level and kept until the score falls below the
    'out' level (e.g. red from 50%, kept until below 40%)."""
    out, state = [], "green"
    for v in p:
        if pd.isna(v):
            out.append(state)
            continue
        if state == "red" and v < red_out:
            state = "amber" if v >= amber_out else "green"
        elif state == "amber":
            if v >= red_in:
                state = "red"
            elif v < amber_out:
                state = "green"
        elif state == "green":
            state = "red" if v >= red_in else "amber" if v >= amber_in else "green"
        out.append(state)
    return pd.Series(out, index=p.index)


def persistence(p: pd.Series, amber=AMBER, red=RED, k=2, n=3) -> pd.Series:
    """2-of-3 rule: a colour shows only once the score has been at that level in k of the last n periods."""
    raw = colours(p, amber, red)
    level = raw.map({"green": 0, "amber": 1, "red": 2})
    out = []
    for i in range(len(level)):
        window = level.iloc[max(0, i - n + 1): i + 1]
        lvl = 2 if (window >= 2).sum() >= k else 1 if (window >= 1).sum() >= k else 0
        out.append(["green", "amber", "red"][lvl])
    return pd.Series(out, index=p.index)


def flips(col: pd.Series) -> int:
    return int((col != col.shift()).iloc[1:].sum())


def score_on(on: pd.Series, ev: pd.DataFrame, start: str):
    """Episodes of `on` (Layer 1 rules) from `start`: real / false / too recent, and leads per event."""
    eps = S.episodes(on, on.notna())
    real = false = recent = 0
    false_starts = []
    for s, e in eps:
        if s < pd.Timestamp(start) or ((ev.start < s) & (s <= ev.end)).any():
            continue
        nxt = ev[(ev.start >= s) & (ev.start <= s + pd.DateOffset(months=S.WINDOW))]
        nxt = nxt[[S.live(e, x) for x in nxt.start]]
        if len(nxt):
            real += 1
        elif s + pd.DateOffset(months=S.WINDOW) > S.DATA_END:
            recent += 1
        else:
            false += 1
            false_starts.append(f"{s:%Y-%m}")
    leads = {f"lead_#{x.event}": S.lead_for(x, eps, on, on.notna(), S.WINDOW)[0]
             for x in ev[ev.start >= pd.Timestamp(start)].itertuples()}
    return {"real": real, "false": false, "too_recent": recent, "false_starts": ", ".join(false_starts), **leads}


def brier_skill(p, tgt, start, end=None, skip_years=()):
    idx = p.index[(p.index >= start) & ((p.index <= end) if end else True)]
    idx = idx[tgt.loc[idx, "usable"] & ~idx.year.isin(skip_years)]
    y = tgt.loc[idx, "y"]
    base = S.brier(p.loc[idx] * 0 + y.mean(), y)       # not used for skill (see below); kept for reference
    return idx, y


# ---------------------------------------------------------------------------------------------------
def main() -> None:
    F, status, ev = load()
    feats = S.FINAL_FEATURES
    tgt = S.target(F.index, ev)
    pred, coefs, _ = S.run_oos(F, tgt, status, feats, 1980, nonneg=True)

    def skill(p, base, start, end=None, skip=()):
        idx = p.index[(p.index >= start)]
        if end:
            idx = idx[idx <= end]
        idx = idx[tgt.loc[idx, "usable"] & ~idx.year.isin(skip)]
        y = tgt.loc[idx, "y"]
        b, b0 = S.brier(p.loc[idx], y), S.brier(base.loc[idx], y)
        return round(b, 4), round(1 - b / b0, 3), len(idx)

    # ======================= A1: contributions, 2024-10 on, months with score >= 20% =======================
    rows = []
    for year in sorted({m.year for m in pred.index if m >= pd.Timestamp(A1_FROM)}):
        fitted = S.Fitted(F, tgt, status, train_index(tgt, year), feats, nonneg=True)
        months = [m for m in pred.index if m.year == year and m >= pd.Timestamp(A1_FROM) and pred.loc[m, "logit"] >= AMBER]
        for m in months:
            z = fitted.z(F.loc[[m]]).iloc[0]
            row = {"month": f"{m:%Y-%m}", "score": round(pred.loc[m, "logit"], 3),
                   "intercept": round(fitted.logit.intercept_[0], 2)}
            for f, c in zip(feats, fitted.logit.coef_[0]):
                row[f"{f}_value"] = F.loc[m, f]
                row[f"{f}_contrib"] = round(c * z[f], 2)
            rows.append(row)
    a1 = pd.DataFrame(rows)
    a1.to_csv(MODEL / "score_followups_a1_contributions.csv", index=False)

    # ======================= A2: NSA claims input, today's data and as first published =======================
    Fv = F.copy()            # claims measures as first published from 2010 (FRED vintages); current before
    for a in ["claims_low", "claims_yoy", "cont_yoy", "nsa_yoy", "nsa_low"]:
        Fv[a] = F[f"{a}_v"].where(F[f"{a}_v"].notna(), F[a])
    variants = {
        "final (SA claims)": feats,
        "final + nsa_yoy": feats + ["nsa_yoy"],
        "final + nsa_yoy + nsa_low": feats + ["nsa_yoy", "nsa_low"],
        "NSA replaces SA initial-claims measures": [f for f in feats if f not in ("claims_low", "claims_yoy")]
                                                   + ["nsa_yoy", "nsa_low"],
        "NSA yoy replaces SA initial-claims measures": [f for f in feats if f not in ("claims_low", "claims_yoy")]
                                                      + ["nsa_yoy"],
    }
    a2 = []
    for name, fs in variants.items():
        p_today, _, _ = S.run_oos(F, tgt, status, fs, 2000, nonneg=True)
        p_vint, _, _ = S.run_oos(Fv, tgt, status, fs, 2010, nonneg=True)
        b00, s00, n00 = skill(p_today.logit, p_today.base, "2000-01-01")
        b10, s10, n10 = skill(p_today.logit, p_today.base, "2010-01-01")
        bv, sv, nv = skill(p_vint.logit, p_vint.base, "2010-01-01")
        bvx, svx, _ = skill(p_vint.logit, p_vint.base, "2010-01-01", skip=(2022, 2023))
        b10x, s10x, _ = skill(p_today.logit, p_today.base, "2010-01-01", skip=(2022, 2023))
        ep_today = score_on(p_today.logit >= AMBER, ev, "2000-01-01")
        ep_vint = score_on(p_vint.logit >= AMBER, ev, "2010-01-01")
        a2.append({"variant": name, "inputs": " ".join(fs),
                   "skill_today_2000on": s00, "skill_today_2010on": s10, "skill_vintage_2010on": sv,
                   "skill_today_2010on_ex2022_23": s10x, "skill_vintage_2010on_ex2022_23": svx,
                   "brier_today_2000on": b00, "brier_vintage_2010on": bv,
                   "amber_real_false_today_2000on": f"{ep_today['real']} / {ep_today['false']}",
                   "amber_real_false_vintage_2010on": f"{ep_vint['real']} / {ep_vint['false']}",
                   "vintage_score_mid2022_max": round(p_vint.logit.loc["2022-05-01":"2023-01-01"].max(), 2),
                   "vintage_score_mid2022_mean": round(p_vint.logit.loc["2022-05-01":"2023-01-01"].mean(), 2)})
    a2 = pd.DataFrame(a2)
    a2.to_csv(MODEL / "score_followups_a2_nsa_claims.csv", index=False)

    # ======================= A3: recalibration (Platt), expanding window on prior OOS scores =================
    p = pred.logit.clip(1e-4, 1 - 1e-4)
    logit_p = np.log(p / (1 - p))
    cal = pd.Series(np.nan, index=p.index)
    for year in range(1990, F.index[-1].year + 1):          # needs ~10 years of earlier OOS scores
        hist = train_index(tgt, year, fit_from="1980-01-01")
        hist = hist[hist.isin(p.index)]
        m = LogisticRegression(C=1e6, max_iter=5000).fit(logit_p.loc[hist].to_frame(), tgt.loc[hist, "y"])
        rows_y = p.index[p.index.year == year]
        cal.loc[rows_y] = m.predict_proba(logit_p.loc[rows_y].to_frame())[:, 1]
    pc = pred.assign(logit=cal)
    b_raw, s_raw, n = skill(pred.logit, pred.base, "2000-01-01")
    b_cal, s_cal, _ = skill(cal, pred.base, "2000-01-01")
    rel = pd.concat([S.reliability(pred, tgt, "logit", "2000-01-01").assign(version="raw"),
                     S.reliability(pc, tgt, "logit", "2000-01-01").assign(version="recalibrated")])
    # Episodes per band and a block bootstrap (resample whole episodes) for the observed rate.
    use = pred.index[(pred.index >= "2000-01-01") & tgt.loc[pred.index, "usable"].values]
    bands = []
    for lo, hi in [(0.35, 0.50), (0.50, 1.01)]:
        inband = pd.Series(False, index=pred.index)
        inband.loc[use] = (pred.logit.loc[use] >= lo) & (pred.logit.loc[use] < hi)
        eps = S.episodes(inband, pd.Series(True, index=pred.index))
        groups = [[m for m in use if s <= m <= e and inband[m]] for s, e in eps]
        groups = [g for g in groups if g]
        ys = [tgt.loc[g, "y"].values for g in groups]
        observed = np.concatenate(ys).mean()
        boots = []
        for _ in range(5000):
            pick = RNG.integers(0, len(ys), len(ys))
            boots.append(np.concatenate([ys[i] for i in pick]).mean())
        bands.append({"band": f"{lo:.0%}-{min(hi, 1):.0%}", "months": int(sum(len(g) for g in groups)),
                      "episodes": len(groups), "observed_rate": round(observed, 3),
                      "mean_predicted": round(pred.logit.loc[[m for g in groups for m in g]].mean(), 3),
                      "boot_90_low": round(np.quantile(boots, 0.05), 3),
                      "boot_90_high": round(np.quantile(boots, 0.95), 3),
                      "episode_starts": ", ".join(f"{g[0]:%Y-%m}" for g in groups)})
    a3 = {"brier_raw": b_raw, "skill_raw": s_raw, "brier_recalibrated": b_cal, "skill_recalibrated": s_cal,
          "months": n}
    pd.DataFrame([a3]).to_csv(MODEL / "score_followups_a3_recalibration.csv", index=False)
    rel.to_csv(MODEL / "score_followups_a3_reliability.csv", index=False)
    pd.DataFrame(bands).to_csv(MODEL / "score_followups_a3_bands.csv", index=False)

    # ======================= A4: colour stability ====================================================
    pre = tgt.index[tgt.usable & (tgt.index <= "1999-06-01")]
    pre_rows = F.index[(F.index >= S.FIRST_FIT) & (F.index <= "1999-12-01")]
    p_pre = S.Fitted(F, tgt, status, pre, feats, True).predict(F, pre_rows).logit   # pre-2000 in-sample scores
    p_oos = pred.logit[pred.index >= "2000-01-01"]
    rules = {"plain (20% / 50%)": lambda x: colours(x)}
    for gap in (2.5, 5.0, 7.5, 10.0):
        g = gap / 100
        rules[f"hysteresis: leave amber < {AMBER - g / 2:.1%}, red < {RED - g:.0%}"] = \
            (lambda x, g=g: hysteresis(x, AMBER, AMBER - g / 2, RED, RED - g))
    rules["2 of 3 months"] = lambda x: persistence(x)
    a4 = []
    for name, rule in rules.items():
        for label, series, start in [("pre-2000 (in-sample)", p_pre, "1968-02-01"), ("2000-on (out of sample)", p_oos, "2000-01-01")]:
            col = rule(series)
            amber_on = col.isin(["amber", "red"])
            red_on = col == "red"
            ra = score_on(amber_on, ev, start)
            rr = score_on(red_on, ev, start)
            years = len(col) / 12
            a4.append({"rule": name, "period": label, "flips_per_year": round(flips(col) / years, 2),
                       "amber_real": ra["real"], "amber_false": ra["false"], "red_real": rr["real"],
                       "red_false": rr["false"],
                       **{f"amber_{k}": v for k, v in ra.items() if k.startswith("lead")},
                       **{f"red_{k}": v for k, v in rr.items() if k.startswith("lead")}})
    a4 = pd.DataFrame(a4)

    # Weekly approximation (2000 on): the score recomputed every Thursday (claims release day) with all inputs as
    # known that day, using the model fitted that January.
    fits = {y: S.Fitted(F, tgt, status, train_index(tgt, y), feats, nonneg=True) for y in range(2000, F.index[-1].year + 1)}
    weeks = pd.date_range("2000-01-06", S.DATA_END + pd.offsets.MonthEnd(0), freq="W-THU")
    wrows = []
    for d in weeks:
        x = pd.DataFrame([features_at(d)], index=[d])[feats].astype(float)
        wrows.append({"date": d, "score": fits[d.year].logit.predict_proba(fits[d.year].z(x))[0, 1]})
    weekly = pd.DataFrame(wrows).set_index("date")["score"]
    weekly.to_csv(MODEL / "score_weekly.csv", index_label="thursday")
    wk = []
    for name, rule in rules.items():
        if name == "2 of 3 months":
            col = persistence(weekly, k=2, n=3)
            name = "2 of 3 weeks"
        else:
            col = rule(weekly)
        wk.append({"rule": name, "weekly_flips_per_year": round(flips(col) / (len(col) / 52.18), 2),
                   "weeks_amber_or_red": int(col.isin(["amber", "red"]).sum()), "weeks_red": int((col == "red").sum())})
    a4w = pd.DataFrame(wk)
    a4.to_csv(MODEL / "score_followups_a4_stability.csv", index=False)
    a4w.to_csv(MODEL / "score_followups_a4_weekly.csv", index=False)

    # ======================= A5: 3-month and 12-month targets =======================================
    horizons = {6: pred}
    a5 = [{"horizon_months": 6, "brier": skill(pred.logit, pred.base, "2000-01-01")[0],
           "skill": s_raw, "base_rate_2000on": round(tgt.loc[use, "y"].mean(), 3)}]
    for h in (3, 12):
        S.HORIZON = h                                       # score.py's functions read this setting
        t_h = S.target(F.index, ev)
        p_h, _, _ = S.run_oos(F, t_h, status, feats, 2000, nonneg=True)
        idx = p_h.index[t_h.loc[p_h.index, "usable"].values]
        y = t_h.loc[idx, "y"]
        b, b0 = S.brier(p_h.logit.loc[idx], y), S.brier(p_h.base.loc[idx], y)
        a5.append({"horizon_months": h, "brier": round(b, 4), "skill": round(1 - b / b0, 3),
                   "base_rate_2000on": round(y.mean(), 3)})
        horizons[h] = p_h
    S.HORIZON = 6
    out = pd.DataFrame({f"p{h}": horizons[h].logit for h in (3, 6, 12)})
    out.to_csv(MODEL / "score_horizons.csv", date_format="%Y-%m-%d", index_label="month")
    pd.DataFrame(a5).to_csv(MODEL / "score_followups_a5_horizons.csv", index=False)

    # ---- Print ----
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 80)
    pd.set_option("display.max_colwidth", 60)
    print("A1:", len(a1), "months"); print(a1[["month", "score"] + [c for c in a1.columns if c.endswith("_contrib")] + ["intercept"]].to_string(index=False))
    print("\nA2:"); print(a2.drop(columns=["inputs"]).T.to_string())
    print("\nA3:", a3); print(rel.to_string(index=False)); print(pd.DataFrame(bands).to_string(index=False))
    print("\nA4:"); print(a4.T.to_string()); print(a4w.to_string(index=False))
    print("\nA5:"); print(pd.DataFrame(a5).to_string(index=False))


if __name__ == "__main__":
    main()
