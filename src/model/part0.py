"""
Stage 3e Part 0: fixes from the stage 3d review (docs/model.md section 6, "Part 0").

    python src/model/part0.py prep     (run after score_followups.py, before forecast.py)
        0.2  coherent probabilities: p12 = max(p12, p6), p3 = min(p3, p6) every month; Brier before/after;
             score_horizons.csv keeps the raw values as p3_raw / p12_raw and the adjusted ones as p3 / p12
        0.3  live "as of" inputs: every score input, the 3/6/12-month probabilities and the latest published
             unemployment rate / claims weeks AS OF THE REFRESH DATE (not the month end) -> data/model/live_asof.csv;
             forecast.py adds this as the live origin, so score, fans and stress paths start from the same values
        0.5  nowcast: actual coverage of the +/-0.2 point range, and the range that covers about 80%

    python src/model/part0.py report   (run after forecast.py for each option)
        0.1  late-cycle bias of the fan medians, the two fixes, and today's fans under each
        0.4  today's median beside the latest FOMC SEP median for the matching quarter
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "model"))
sys.path.insert(0, str(ROOT / "src" / "fetchers"))
import score as S                                   # noqa: E402
from features import features_at                    # noqa: E402

MODEL = ROOT / "data" / "model"
RNG = np.random.default_rng(20261108)


def months_between(a, b):
    return (b.year - a.year) * 12 + b.month - a.month


# ===================================================================================================
def prep(asof: pd.Timestamp) -> None:
    F = pd.read_csv(MODEL / "features_monthly.csv", parse_dates=["month"]).set_index("month")
    S.DATA_END = F.index[-1]
    status = pd.read_csv(MODEL / "triggers_monthly.csv", parse_dates=["month"], keep_default_na=False).set_index("month")["overall"]
    ev = S.load_events()

    # ---- 0.2 coherent probabilities ----
    P = pd.read_csv(MODEL / "score_horizons.csv", parse_dates=["month"]).set_index("month")
    if "p3_raw" not in P:
        P["p3_raw"], P["p12_raw"] = P.p3, P.p12
    P["p3"] = np.minimum(P.p3_raw, P.p6)
    P["p12"] = np.maximum(P.p12_raw, P.p6)
    rows = []
    for h, raw, adj in [(3, "p3_raw", "p3"), (12, "p12_raw", "p12")]:
        S.HORIZON = h
        t = S.target(F.index, ev)
        idx = P.index[(P.index >= "2000-01-01")]
        idx = idx[t.loc[idx, "usable"].values]
        y = t.loc[idx, "y"]
        base = y.expanding().mean().shift().fillna(y.mean())   # not used; skill vs. a fixed base below
        b_raw, b_adj = S.brier(P.loc[idx, raw], y), S.brier(P.loc[idx, adj], y)
        b0 = S.brier(pd.Series(y.mean(), index=idx), y)
        changed_all = int((P[raw] != P[adj]).sum())
        changed_2000 = int((P.loc[P.index >= "2000-01-01", raw] != P.loc[P.index >= "2000-01-01", adj]).sum())
        rows.append({"probability": f"{h}-month", "months_changed_1980on": changed_all,
                     "months_changed_2000on": changed_2000, "brier_raw_2000on": round(b_raw, 4),
                     "brier_adjusted_2000on": round(b_adj, 4),
                     "max_adjustment": round((P[adj] - P[raw]).abs().max(), 3)})
    S.HORIZON = 6
    P.to_csv(MODEL / "score_horizons.csv", date_format="%Y-%m-%d", index_label="month")
    coh = pd.DataFrame(rows)
    coh.to_csv(MODEL / "part0_coherence.csv", index=False)
    print("0.2 coherence:"); print(coh.to_string(index=False))

    # ---- 0.3 live inputs as of the refresh date ----
    x = pd.DataFrame([features_at(asof)], index=[asof]).astype(float)
    live = {"asof": asof.date()}
    live.update({k: x.iloc[0][k] for k in S.FINAL_FEATURES})
    probs = {}
    for h in (3, 6, 12):
        S.HORIZON = h
        t = S.target(F.index, ev)
        known = pd.Timestamp(f"{asof.year}-01-01") - pd.DateOffset(months=h + 1)
        train = t.index[t.usable & (t.index <= known) & (t.index >= S.FIRST_FIT)]
        fit = S.Fitted(F, t, status, train, S.FINAL_FEATURES, nonneg=True)
        probs[h] = fit.logit.predict_proba(fit.z(x[S.FINAL_FEATURES]))[0, 1]
    S.HORIZON = 6
    live["p6"] = probs[6]
    live["p3_raw"], live["p12_raw"] = probs[3], probs[12]
    live["p3"], live["p12"] = min(probs[3], probs[6]), max(probs[12], probs[6])
    from realtime import as_known_on
    ur = as_known_on("UNRATE", asof).dropna()
    live["ur_latest_month"], live["ur_latest"] = ur.index[-1].date(), ur.iloc[-1]
    pd.DataFrame([live]).to_csv(MODEL / "live_asof.csv", index=False)
    print("\n0.3 live inputs:"); print(pd.Series(live).to_string())

    # ---- 0.5 nowcast range coverage ----
    n = pd.read_csv(MODEL / "nowcast.csv", parse_dates=["month"]).set_index("month")
    n = n[~((n.index >= "2020-03-01") & (n.index <= "2020-12-01"))]
    err = (n.first_release - n.nowcast).abs()
    cov = {f"+/-{r}": round((err <= r + 1e-9).mean(), 3) for r in (0.1, 0.15, 0.2, 0.25, 0.3)}
    cov["range_for_80pct"] = round(np.quantile(err, 0.8), 3)
    cov["releases"] = len(err)
    pd.DataFrame([cov]).to_csv(MODEL / "part0_nowcast_range.csv", index=False)
    print("\n0.5 nowcast coverage (2000-on excl. Mar-Dec 2020):", cov)


# ===================================================================================================
def late_cycle_flags(bt: pd.DataFrame, ev: pd.DataFrame) -> pd.Series:
    """Late-cycle origin: the unemployment rate (as known that day) within 0.5 point of its 24-month low, and no
    event start in the previous 24 months. (The same flag is used for the claims-rate fans.)"""
    from realtime import as_known_on
    flags = {}
    for m in sorted(bt.origin.unique()):
        d = pd.Timestamp(m) + pd.offsets.MonthEnd(0) if pd.Timestamp(m).day == 1 else pd.Timestamp(m)
        ur = as_known_on("UNRATE", d).dropna().iloc[-24:]
        recent = ((ev.start <= pd.Timestamp(m)) & (ev.start > pd.Timestamp(m) - pd.DateOffset(months=24))).any()
        flags[m] = bool(ur.iloc[-1] - ur.min() <= 0.5 and not recent)
    return bt.origin.map(flags)


def block_ci(x: np.ndarray, block: int, reps=2000):
    n = len(x)
    if n == 0:
        return (np.nan, np.nan)
    starts = np.arange(max(1, n - block + 1))
    out = [x[np.concatenate([np.arange(s, s + block) for s in RNG.choice(starts, int(np.ceil(n / block)))])[:n]].mean()
           for _ in range(reps)]
    return tuple(np.quantile(out, [0.05, 0.95]))


def bias_table(bt, label):
    rows = []
    for (t, h), g in bt.groupby(["target", "horizon"]):
        g = g.sort_values("origin")
        g = g[g.realized.notna() & ~g.covid_window & (g.origin >= "2000-01-01")]
        quiet = ~(g.in_progress | g.event_starts_within_h)
        for sub, mask in [("late-cycle, all", g.late), ("late-cycle, quiet", g.late & quiet),
                          ("late-cycle 2022-26", g.late & (g.origin >= "2022-01-01"))]:
            e = (g.realized - g.center)[mask].values
            lo, hi = block_ci(e, int(g.horizon_months.iloc[0]))
            rows.append({"option": label, "target": t, "horizon": h, "subset": sub, "origins": len(e),
                         "mean_error": e.mean() if len(e) else np.nan, "ci90_lo": lo, "ci90_hi": hi})
    return pd.DataFrame(rows)


def overall(bt, label):
    import forecast as FC
    rows = []
    for (t, h), g in bt[bt.realized.notna() & ~bt.covid_window & (bt.origin >= "2000-01-01")].groupby(["target", "horizon"]):
        y, c, y0 = g.realized.values, g.center.values, g.level_at_origin.values
        pl = np.mean([FC.pinball(a, b) for a, b in zip(y, g[["q10", "q25", "center", "q75", "q90"]].values)])
        plc = np.mean([FC.pinball(a, b) for a, b in zip(y, g[["clim_q10", "clim_q25", "clim_q50", "clim_q75", "clim_q90"]].values)])
        rows.append({"option": label, "target": t, "horizon": h,
                     "rmse_ratio": np.sqrt(((y - c) ** 2).mean() / ((y - y0) ** 2).mean()),
                     "pinball_skill": 1 - pl / plc,
                     "cover50": ((y >= g.q25) & (y <= g.q75)).mean(), "cover80": ((y >= g.q10) & (y <= g.q90)).mean()})
    return pd.DataFrame(rows)


def blend(bt, lam):
    """Option (a): move the whole fan so its median is (1 - lam) * median + lam * no-change."""
    out = bt.copy()
    shift = lam * (out.level_at_origin - out.center)
    for c in ["q10", "q25", "center", "q75", "q90"]:
        out[c] = out[c] + shift
    return out


def report() -> None:
    ev = pd.read_csv(MODEL / "events.csv", dtype={"start_month": str})
    ev["start"] = pd.to_datetime(ev.start_month + "-01")
    base = pd.read_csv(MODEL / "forecast_backtest.csv", parse_dates=["origin"])
    gap = pd.read_csv(MODEL / "forecast_backtest_gap.csv", parse_dates=["origin"])
    targets = ["ur", "cc"]
    base, gap = base[base.target.isin(targets)].copy(), gap[gap.target.isin(targets)].copy()
    base["late"] = late_cycle_flags(base, ev)
    gap["late"] = base.set_index(["origin", "target", "horizon"]).late.reindex(
        pd.MultiIndex.from_frame(gap[["origin", "target", "horizon"]])).values

    # Option (a): blend weight per target x horizon, chosen on PRE-2000 origins only (minimise RMSE of the median).
    lam = {}
    for (t, h), g in base[(base.origin < "2000-01-01") & base.realized.notna()].groupby(["target", "horizon"]):
        grid = np.round(np.arange(0, 1.01, 0.05), 2)
        rm = [np.sqrt(((g.realized - ((1 - l) * g.center + l * g.level_at_origin)) ** 2).mean()) for l in grid]
        lam[(t, h)] = float(grid[int(np.argmin(rm))])
    blended = pd.concat([blend(g, lam[k]) for k, g in base.groupby(["target", "horizon"])])

    options = {"base (3d)": base, "(a) blend toward no-change": blended, "(b) gap term": gap}
    bias = pd.concat([bias_table(b, k) for k, b in options.items()])
    ov = pd.concat([overall(b, k) for k, b in options.items()])
    bias.to_csv(MODEL / "part0_bias.csv", index=False)
    ov.to_csv(MODEL / "part0_options_overall.csv", index=False)
    pd.set_option("display.width", 250)
    print("Blend weights (pre-2000):", lam)
    print(bias.round(3).to_string(index=False))
    print(ov.round(3).to_string(index=False))

    # Today's fans (live origin) under each option.
    rows = []
    for k, b in options.items():
        cur = b[b.origin == b.origin.max()]
        for r in cur.itertuples():
            rows.append({"option": k, "origin": r.origin.date(), "target": r.target, "horizon": r.horizon,
                         "level": r.level_at_origin, "q10": r.q10, "q25": r.q25, "median": r.center, "q75": r.q75, "q90": r.q90})
    today = pd.DataFrame(rows)
    today.to_csv(MODEL / "part0_today_fans.csv", index=False)
    print(today.round(2).to_string(index=False))


if __name__ == "__main__":
    if sys.argv[1] == "prep":
        prep(pd.Timestamp(sys.argv[2]) if len(sys.argv) > 2 else pd.Timestamp.today().normalize())
    else:
        report()
