"""
Stage 3d, Part B: forecast fans (plan Layer 3) and their out-of-sample backtest.

TARGETS     ur   unemployment rate (monthly, %), horizons 3 / 6 / 12 months after the latest published month
            ic   SA initial claims rate, 4-week average (% of covered employment), 13 / 26 / 52 weeks after the
                 latest published week
            cc   SA continuing claims rate, 4-week average (%), 13 / 26 / 52 weeks
ORIGINS     every month end from 2000 (the backtest) and from 1968 / 1971 (training only). At each origin only what
            was published by then is used: the unemployment rate as known that day (ALFRED), claims rates as we hold
            them (current vintage, cut back by the release lag), the score inputs (features_monthly.csv) and the
            out-of-sample event probabilities for 3 / 6 / 12 months (score_horizons.csv).

MIXTURE     With probability P (the event probability for the matching horizon: 3-month P for 3 months / 13 weeks,
            6-month for 6 / 26, 12-month for 12 / 52) the change follows a DETERIORATION path; otherwise the BASELINE.
  baseline       ridge regression of the h-step change (unemployment rate: points; claims rates: log change) on the
                 eight score inputs plus the current level, fitted only on QUIET origins (no event in progress and
                 none starting within the horizon), re-fitted each January; penalty by forward-chaining
                 cross-validation, whose out-of-sample residuals supply the noise.
  deterioration  the path after past event starts, measured from the last pre-event month (week), recession paths
                 (recessions + the early signal) and scare paths kept separate and mixed by their share of events;
                 the event is assumed to start at a uniformly random time within the horizon. 2020 is never used.
                 Unemployment-rate paths are added in points; claims-rate paths are applied as log (percentage) changes.
  in progress    if an event is already in progress at the origin AND has lasted IN_PROGRESS_MIN_MONTHS (3) months,
                 the deterioration weight is 1 and the path is picked up at the event's current age, using past
                 events that lasted at least that long. Younger events use the normal mixture.
BANDS       10 / 25 / 50 / 75 / 90 percentiles of 4,000 simulated draws (baseline or deterioration, plus a resampled
            baseline residual). Center = the median.
BENCHMARKS  no-change; climatology (no-change center plus the empirical quantiles of all past h-step changes).

Writes data/model/forecast_backtest.csv (one row per origin x target x horizon), forecast_evaluation.csv,
forecast_events.csv, forecast_current.csv, forecast_paths.csv (event paths), stress_paths.csv.
Run it (after score_followups.py):
    python src/model/forecast.py
"""

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "model"))
from realtime import as_known_on    # noqa: E402
import realtime_events as rte       # noqa: E402  (review WP4: real-time event dating, shared with live.py)

MODEL = ROOT / "data" / "model"
FEATURES = ["sahm", "claims_low", "claims_yoy", "cont_yoy", "temp_help", "yield_curve", "mfg", "nfci"]
QUANTILES = [0.10, 0.25, 0.50, 0.75, 0.90]
ALPHAS = [0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1000.0, 3000.0]   # ridge penalty grid (larger = more shrinkage)
CV_BLOCKS = 5
DRAWS = 4000
CLIP = 4.0
BACKTEST_FROM = "2000-01-01"       # first origin scored (evaluation always uses 2000 on); "--from 1985" for Part 0
# Command-line options (Part 0, stage 3e):
#   --from YEAR   also produce fans from YEAR (pre-2000 fans are used only to choose the blend weight in part0.py)
#   --option gap  add a lightly penalized gap term (level minus its 36-month average); outputs get a "_gap" suffix
#   --live        add the live origin from data/model/live_asof.csv (inputs as of the refresh date)
ARGS = sys.argv[1:]
if "--from" in ARGS:
    BACKTEST_FROM = f"{ARGS[ARGS.index('--from') + 1]}-01-01"
OPTION = ARGS[ARGS.index("--option") + 1] if "--option" in ARGS else "base"
SUFFIX = "" if OPTION == "base" else f"_{OPTION}"
LIVE = "--live" in ARGS
GAP_SCALE = 5.0    # the gap column is multiplied by 5 after standardizing: ridge then penalizes it 25 times less
# An event in progress takes the deterioration weight to 1 only once it has lasted this many months; before that the
# usual probability-weighted mixture applies (stage 3d review: avoids leaning on recession paths during short scares,
# which rarely last 3 months).
IN_PROGRESS_MIN_MONTHS = 3
COVID = (pd.Timestamp("2020-03-01"), pd.Timestamp("2021-03-01"))   # 2020: reported separately, never fitted
RNG = np.random.default_rng(20261108)

TARGETS = {
    # name: (frequency, horizons, scale, release lag in days, first training origin)
    "ur": ("M", [3, 6, 12], "points", None, "1968-03-01"),
    "ic": ("W", [13, 26, 52], "log", 5, "1971-03-01"),
    "cc": ("W", [13, 26, 52], "log", 12, "1971-03-01"),
}
LABEL = {"ur": "Unemployment rate", "ic": "SA initial claims rate (4-wk avg)", "cc": "SA continuing claims rate (4-wk avg)"}


def months_for(freq, h):
    """Horizon in months (weekly horizons rounded up: 13 weeks -> 3 months)."""
    return h if freq == "M" else math.ceil(h / 4.345)


# ---------------------------------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------------------------------
def load():
    F = pd.read_csv(MODEL / "features_monthly.csv", parse_dates=["month"]).set_index("month")[FEATURES]
    P = pd.read_csv(MODEL / "score_horizons.csv", parse_dates=["month"]).set_index("month")
    ev = pd.read_csv(MODEL / "events.csv", dtype={"start_month": str, "end_month": str})
    ev["start"] = pd.to_datetime(ev.start_month + "-01")
    ev["end"] = [pd.Timestamp(e + "-01") for e in ev.end_month]
    ev["group"] = ev.classification.map({"recession": "recession", "early signal": "recession", "scare": "scare",
                                         "recession (pandemic)": "2020"})
    ur_final = pd.read_csv(ROOT / "data" / "processed" / "UNRATE.csv", parse_dates=["date"]).set_index("date")["value"]
    w = pd.read_csv(MODEL / "claims_weekly.csv", parse_dates=["week_ended"]).set_index("week_ended")
    weekly = {"ic": w.ic_rate_sa.rolling(4).mean().dropna(), "cc": w.cc_rate_sa.rolling(4).mean().dropna()}
    return F, P, ev, ur_final, weekly


class Series:
    """Access to one target: its level as known at a date, its final value at a date, and steps."""

    def __init__(self, name, ur_final, weekly):
        self.name = name
        self.freq, self.horizons, self.scale, self.lag, self.first = TARGETS[name]
        self.final = ur_final if name == "ur" else weekly[name]
        self._vintage_cache = {}

    def known(self, d):
        """(latest period, its value, the whole series) as published on date d."""
        if self.name == "ur":
            if d not in self._vintage_cache:
                s = as_known_on("UNRATE", d).dropna()
                self._vintage_cache[d] = s
            s = self._vintage_cache[d]
        else:
            s = self.final[self.final.index + pd.Timedelta(days=self.lag) <= d]
        return s.index[-1], s.iloc[-1], s

    def step(self, t, k):
        return t + pd.DateOffset(months=k) if self.freq == "M" else t + pd.Timedelta(weeks=k)

    def change(self, a, b):
        """Change from level a to level b on this target's scale (points, or log change)."""
        return b - a if self.scale == "points" else np.log(b / a)

    def apply(self, level, change):
        return level + change if self.scale == "points" else level * np.exp(change)


# ---------------------------------------------------------------------------------------------------
# Deterioration paths
# ---------------------------------------------------------------------------------------------------
def event_paths(ser: Series, ev: pd.DataFrame, max_k: int):
    """For each event: its path of changes from the last pre-event month (week), k = 0..max_k, on final data."""
    out = {}
    for e in ev.itertuples():
        if ser.freq == "M":
            base = e.start - pd.DateOffset(months=1)
            idx = [base + pd.DateOffset(months=k) for k in range(max_k + 1)]
        else:
            before = ser.final.index[ser.final.index < e.start]
            if len(before) == 0:
                continue
            base = before[-1]
            idx = [base + pd.Timedelta(weeks=k) for k in range(max_k + 1)]
        if base not in ser.final.index or pd.isna(ser.final.get(base)):
            continue
        vals = ser.final.reindex(idx)
        out[e.event] = {"base": base, "group": e.group, "length_months": (e.end.year - e.start.year) * 12
                        + e.end.month - e.start.month + 1, "start": e.start,
                        "path": np.array([ser.change(vals.iloc[0], v) if pd.notna(v) else np.nan for v in vals])}
    return out


# ---------------------------------------------------------------------------------------------------
# Baseline regression
# ---------------------------------------------------------------------------------------------------
def standardize(train, rows):
    mean, sd = train.mean(), train.std().replace(0, np.nan)
    z = ((rows - mean) / sd).clip(-CLIP, CLIP).fillna(0.0)
    if "gap" in z:
        z["gap"] = z["gap"] * GAP_SCALE           # lightly penalized (option "gap")
    return z


def fit_baseline(X: pd.DataFrame, y: pd.Series, gap_months: int):
    """Ridge with the penalty chosen by forward-chaining CV; returns (model, mean, sd, CV residuals)."""
    idx = X.index
    blocks = np.array_split(np.arange(len(idx)), CV_BLOCKS)
    best = None
    for a in ALPHAS:
        res = []
        for k in range(1, CV_BLOCKS):
            val = idx[blocks[k]]
            fit = idx[np.concatenate(blocks[:k])]
            fit = fit[fit < val[0] - pd.DateOffset(months=gap_months)]
            if len(fit) < 30:
                continue
            m = Ridge(alpha=a).fit(standardize(X.loc[fit], X.loc[fit]), y[fit])
            res.append(y[val].values - m.predict(standardize(X.loc[fit], X.loc[val])))
        if not res:
            continue
        r = np.concatenate(res)
        if best is None or np.mean(r ** 2) < best[1]:
            best = (a, np.mean(r ** 2), r)
    if best is None:
        # Too few training origins for the CV folds (only the earliest pre-2000 re-fits): a fixed, fairly strong
        # penalty, with in-sample residuals (slightly too narrow) as the noise.
        alpha = 100.0
        model = Ridge(alpha=alpha).fit(standardize(X, X), y)
        return model, X, y.values - model.predict(standardize(X, X)), alpha
    alpha, _, resid = best
    model = Ridge(alpha=alpha).fit(standardize(X, X), y)
    return model, X, resid, alpha


# ---------------------------------------------------------------------------------------------------
# Review WP4 (F4): whether an event is in progress at a forecast origin, and since when, comes from the real-time
# event state (src/model/realtime_events.py, the same rule as the live flag), on months up to the origin. The
# training-set filter (quiet origins, the 2020 window) and the event-path library keep using events.csv: at a re-fit
# the past is known.
RT_STATE = None


def realtime_in_progress(m: pd.Timestamp):
    """(in progress?, provisional start or None) at origin m (state at the end of m's month, or the latest before)."""
    global RT_STATE
    if RT_STATE is None:
        RT_STATE = rte.state_by_month(rte.month_end_on())
    s = RT_STATE[RT_STATE.index <= pd.Timestamp(f"{m:%Y-%m}-01")]
    if s.empty or not s.under_way.iloc[-1]:
        return False, None
    return True, s.start.iloc[-1]


def main() -> None:
    F, P, ev, ur_final, weekly = load()
    live_asof = None
    if LIVE:
        lv = pd.read_csv(MODEL / "live_asof.csv").iloc[0]
        live_asof = pd.Timestamp(lv["asof"])      # lv["asof"], not lv.asof (a pandas method)
        F.loc[live_asof] = lv[FEATURES].astype(float).values
        P.loc[live_asof, ["p3", "p6", "p12"]] = [lv.p3, lv.p6, lv.p12]
    library_ev = ev[ev.group != "2020"]
    last_month = F.index[F.index.day == 1][-1]          # last month-end origin (the live row is not a month start)
    origins_all = list(pd.date_range("1968-03-01", last_month, freq="MS")) + ([live_asof] if LIVE else [])
    rows, evals_raw = [], []
    paths_out = []

    for name in TARGETS:
        ser = Series(name, ur_final, weekly)
        max_k = 60 if ser.freq == "M" else 260         # long enough for an event in progress plus the horizon
        paths = event_paths(ser, library_ev, max_k)
        for e, info in paths.items():
            for k, v in enumerate(info["path"]):
                if not np.isnan(v):
                    paths_out.append({"target": name, "event": e, "group": info["group"], "k": k, "change": v})

        # Per-origin facts: latest published period and level, features, regime.
        facts = {}
        for m in origins_all:
            if m < pd.Timestamp(ser.first):
                continue
            d = m + pd.offsets.MonthEnd(0)
            if m == live_asof:
                d = live_asof                          # the live origin uses the refresh date itself
            L, y0, s_known = ser.known(d)
            # gap = level minus its 36-month average (claims: in logs, over 156 weeks)
            gap = (y0 - s_known.iloc[-36:].mean()) if ser.freq == "M" else (np.log(y0) - np.log(s_known.iloc[-156:]).mean())
            facts[m] = (d, L, y0, gap)

        for h in ser.horizons:
            hm = months_for(ser.freq, h)
            # Training table: every origin with its h-step change (final data for the claims rates; for the
            # unemployment rate the change is re-read at each re-fit from the vintage known then, see below).
            def regime(m):
                in_prog = ((ev.start <= m) & (m <= ev.end) & (ev.group != "2020")).any()
                starts = ((ev.start > m) & (ev.start <= m + pd.DateOffset(months=hm))).any()
                covid = (m <= COVID[1]) and (m + pd.DateOffset(months=hm) >= COVID[0] - pd.DateOffset(months=1))
                return in_prog, starts, covid

            for year in range(pd.Timestamp(BACKTEST_FROM).year, last_month.year + 1):
                refit = pd.Timestamp(f"{year}-01-01")
                # Values as known at the re-fit date (unemployment rate: that day's vintage).
                _, _, known_series = ser.known(refit - pd.Timedelta(days=1))
                Xtr, ytr, clim = [], [], []
                for m, (d, L, y0, gap) in facts.items():
                    if d >= refit:
                        break
                    T = ser.step(L, h)
                    if T not in known_series.index:
                        continue
                    in_prog, starts, covid = regime(m)
                    if covid:
                        continue
                    dy = ser.change(y0, known_series[T])
                    clim.append(dy)                                   # climatology: all regimes
                    if not in_prog and not starts:                    # baseline: quiet origins only
                        extra = {"level": ser.change(1, y0) if ser.scale == "log" else y0}
                        if OPTION == "gap":
                            extra["gap"] = gap
                        Xtr.append(pd.concat([F.loc[m], pd.Series(extra)]).rename(m))
                        ytr.append(dy)
                Xtr = pd.DataFrame(Xtr)
                ytr = pd.Series(ytr, index=Xtr.index)
                model, Xref, resid, alpha = fit_baseline(Xtr, ytr, hm)
                clim_q = np.quantile(clim, QUANTILES)

                # Forecasts for the origins of this year.
                for m in [x for x in facts if x.year == year and x >= pd.Timestamp(BACKTEST_FROM)]:
                    d, L, y0, gap = facts[m]
                    T = ser.step(L, h)
                    extra = {"level": ser.change(1, y0) if ser.scale == "log" else y0}
                    if OPTION == "gap":
                        extra["gap"] = gap
                    x = pd.concat([F.loc[m], pd.Series(extra)]).to_frame().T
                    base_pred = float(model.predict(standardize(Xref, x))[0])
                    _, starts, covid = regime(m)
                    # Review WP4: in progress and its start from the real-time event state, not from events.csv
                    in_prog, cur_start = realtime_in_progress(m)
                    # Event paths known by this origin (path observed far enough).
                    age_now = 0
                    if in_prog:
                        age_now = (m.year - cur_start.year) * 12 + m.month - cur_start.month + 1   # months, incl. start
                    if in_prog and age_now >= IN_PROGRESS_MIN_MONTHS:
                        cur = pd.Series({"start": cur_start})
                        age_m = (m.year - cur.start.year) * 12 + m.month - cur.start.month
                        k_l = (L - (cur.start - pd.DateOffset(months=1))).days // 30 if ser.freq == "M" else None
                        if ser.freq == "M":
                            base_period = cur.start - pd.DateOffset(months=1)
                            k_l = (L.year - base_period.year) * 12 + L.month - base_period.month
                        else:
                            before = ser.final.index[ser.final.index < cur.start]
                            k_l = int((L - before[-1]).days // 7)
                        cands = [p for e, p in paths.items() if p["start"] < cur.start and p["length_months"] >= age_m + 1
                                 and len(p["path"]) > k_l + h and not np.isnan(p["path"][k_l + h])
                                 and ser.step(p["base"], k_l + h) <= L]
                        if not cands:      # no past event lasted this long: use the recessions observed this far
                            cands = [p for e, p in paths.items() if p["start"] < cur.start and p["group"] == "recession"
                                     and len(p["path"]) > k_l + h and not np.isnan(p["path"][k_l + h])]
                        det = np.array([p["path"][k_l + h] - p["path"][k_l] for p in cands]) if cands else np.zeros(1)
                        det_draw = det[RNG.integers(0, len(det), DRAWS)]
                        w, share = 1.0, np.nan
                        is_det = np.ones(DRAWS, bool)
                    else:
                        usable = [p for p in paths.values() if ser.step(p["base"], h) <= L]
                        rec = [p["path"][:h + 1] for p in usable if p["group"] == "recession"]
                        scr = [p["path"][:h + 1] for p in usable if p["group"] == "scare"]
                        share = len(rec) / (len(rec) + len(scr))
                        w = float(P.loc[m, f"p{hm}"]) if f"p{hm}" in P.columns else float(P.loc[m, "p6"])
                        is_det = RNG.random(DRAWS) < w
                        grp_rec = RNG.random(DRAWS) < share
                        j = RNG.integers(1, h + 1, DRAWS)              # event starts j periods after the origin
                        det_draw = np.empty(DRAWS)
                        for i in range(DRAWS):
                            pool = rec if grp_rec[i] else scr
                            path = pool[RNG.integers(0, len(pool))]
                            det_draw[i] = path[h - j[i] + 1]
                    noise = resid[RNG.integers(0, len(resid), DRAWS)]
                    change = np.where(is_det, det_draw, base_pred) + noise
                    levels = ser.apply(y0, change)
                    q = np.quantile(levels, QUANTILES)
                    realized = ser.final.get(T)
                    rows.append({
                        "origin": m, "target": name, "horizon": h, "horizon_months": hm, "latest_period": L,
                        "target_period": T, "level_at_origin": y0, "center": q[2], "mean": levels.mean(),
                        "q10": q[0], "q25": q[1], "q75": q[3], "q90": q[4], "deterioration_weight": w,
                        "recession_share": share, "baseline_center": ser.apply(y0, base_pred),
                        "deterioration_center": ser.apply(y0, np.median(det_draw)), "in_progress": in_prog,
                        "event_starts_within_h": starts, "covid_window": covid, "ridge_alpha": alpha,
                        "clim_q10": ser.apply(y0, clim_q[0]), "clim_q25": ser.apply(y0, clim_q[1]),
                        "clim_q50": ser.apply(y0, clim_q[2]), "clim_q75": ser.apply(y0, clim_q[3]),
                        "clim_q90": ser.apply(y0, clim_q[4]), "realized": realized})
        print(f"{name}: done")

    bt = pd.DataFrame(rows)
    bt.to_csv(MODEL / f"forecast_backtest{SUFFIX}.csv", index=False, date_format="%Y-%m-%d")
    evaluate(bt)
    if SUFFIX:
        return                                  # option runs: backtest + evaluation only
    pd.DataFrame(paths_out).to_csv(MODEL / "forecast_paths.csv", index=False)
    events_table(bt, ev)
    current_and_stress(bt, ev, ur_final, weekly)


# ---------------------------------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------------------------------
def pinball(y, qs, levels=QUANTILES):
    return np.mean([max(q * (y - f), (q - 1) * (y - f)) for q, f in zip(levels, qs)])


def block_boot(values: np.ndarray, block: int, stat, reps=2000):
    """Moving-block bootstrap (blocks of consecutive origins) for a statistic of the per-origin values."""
    n = len(values)
    starts = np.arange(max(1, n - block + 1))
    out = []
    for _ in range(reps):
        pick = RNG.choice(starts, int(np.ceil(n / block)))
        idx = np.concatenate([np.arange(s, s + block) for s in pick])[:n]
        out.append(stat(values[idx]))
    return np.quantile(out, [0.05, 0.95])


def evaluate(bt: pd.DataFrame):
    rows = []
    scored = bt[bt.realized.notna() & (pd.to_datetime(bt.origin) >= pd.Timestamp("2000-01-01"))]   # evaluation: 2000 on
    for (t, h), g in scored.groupby(["target", "horizon"], sort=False):
        hm = g.horizon_months.iloc[0]
        for subset, gg in [("2000-on excl. 2020", g[~g.covid_window]), ("2020 window", g[g.covid_window])]:
            if len(gg) == 0:
                continue
            y, c, y0 = gg.realized.values, gg.center.values, gg.level_at_origin.values
            e_m, e_0 = (y - c) ** 2, (y - y0) ** 2
            pl = np.array([pinball(a, b) for a, b in zip(y, gg[["q10", "q25", "center", "q75", "q90"]].values)])
            plc = np.array([pinball(a, b) for a, b in zip(y, gg[["clim_q10", "clim_q25", "clim_q50", "clim_q75", "clim_q90"]].values)])
            in50 = ((y >= gg.q25) & (y <= gg.q75)).values
            in80 = ((y >= gg.q10) & (y <= gg.q90)).values
            ev_mask = (gg.in_progress | gg.event_starts_within_h).values
            r = {"target": t, "horizon": h, "subset": subset, "origins": len(gg),
                 "rmse": np.sqrt(e_m.mean()), "rmse_no_change": np.sqrt(e_0.mean()),
                 "rmse_ratio": np.sqrt(e_m.mean() / e_0.mean()),
                 "mae_ratio": np.abs(y - c).mean() / np.abs(y - y0).mean(),
                 "pinball": pl.mean(), "pinball_climatology": plc.mean(), "pinball_skill": 1 - pl.mean() / plc.mean(),
                 "cover50": in50.mean(), "cover80": in80.mean(),
                 "cover50_event": in50[ev_mask].mean() if ev_mask.any() else np.nan,
                 "cover80_event": in80[ev_mask].mean() if ev_mask.any() else np.nan,
                 "cover50_quiet": in50[~ev_mask].mean(), "cover80_quiet": in80[~ev_mask].mean(),
                 "event_origins": int(ev_mask.sum())}
            if subset.startswith("2000"):
                ratio = lambda idx: np.sqrt(e_m[idx].mean() / e_0[idx].mean())
                lo, hi = block_boot(np.arange(len(gg)), hm, ratio)
                r["rmse_ratio_90lo"], r["rmse_ratio_90hi"] = lo, hi
                c80lo, c80hi = block_boot(in80.astype(float), hm, np.mean)
                r["cover80_90lo"], r["cover80_90hi"] = c80lo, c80hi
                r["gate_pass"] = bool(abs(r["cover50"] - 0.5) <= 0.10 and abs(r["cover80"] - 0.8) <= 0.10 and r["rmse_ratio"] < 1)
            rows.append(r)
    out = pd.DataFrame(rows)
    out.to_csv(MODEL / f"forecast_evaluation{SUFFIX}.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    print(out.round(3).to_string(index=False))


def events_table(bt, ev):
    rows = []
    for e in [9, 12, 13, 14, 15]:
        S = ev.loc[ev.event == e, "start"].iloc[0]
        for lead in (6, 3):
            m = S - pd.DateOffset(months=lead)
            g = bt[bt.origin == m]
            for r in g.itertuples():
                rows.append({"event": e, "origin": f"{m:%Y-%m}", "months_before_start": lead, "target": r.target,
                             "horizon": r.horizon, "level_at_origin": r.level_at_origin, "q10": r.q10, "center": r.center,
                             "q90": r.q90, "realized": r.realized, "deterioration_weight": r.deterioration_weight,
                             "inside_80": (r.q10 <= r.realized <= r.q90) if pd.notna(r.realized) else None})
    out = pd.DataFrame(rows)
    out.to_csv(MODEL / "forecast_events.csv", index=False)


def current_and_stress(bt, ev, ur_final, weekly):
    cur = bt[bt.origin == bt.origin.max()]
    cur.to_csv(MODEL / "forecast_current.csv", index=False, date_format="%Y-%m-%d")
    rows = []
    for name in TARGETS:
        ser = Series(name, ur_final, weekly)
        L, y0 = ser.final.dropna().index[-1], ser.final.dropna().iloc[-1]       # today's level
        max_k = 24 if ser.freq == "M" else 104
        paths = event_paths(ser, ev[ev.event.isin([9, 12])], max_k)
        for e, info in paths.items():
            label = "2001-type (#9)" if e == 9 else "2008-type (#12)"
            for k, v in enumerate(info["path"]):
                if not np.isnan(v):
                    rows.append({"target": name, "scenario": label, "k": k, "period": ser.step(L, k),
                                 "level": ser.apply(y0, v), "start_level": y0})
    pd.DataFrame(rows).to_csv(MODEL / "stress_paths.csv", index=False, date_format="%Y-%m-%d")


if __name__ == "__main__":
    main()
