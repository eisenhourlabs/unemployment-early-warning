"""
Stage 3c: the early-warning score (Phase 3 plan, Layer 2), fitted and tested out of sample.

TARGET  For each month t (judged at its last day): y = 1 if an event (data/model/events.csv) STARTS in months
        t+1 .. t+6, else 0. Scares and the early signal count as events (Troy's ruling 2026-11-08).
        Not used for fitting or for the Brier score: months while an event is in progress (start month included;
        the score predicts starts) and the 2020 window 2019-09 .. 2021-03 (event #13; reported separately).

INPUTS  data/model/features_monthly.csv (features.py): candidate indicators, signed so higher = worse, each
        month seeing only what was published by then. Each is standardized with the TRAINING window's mean and
        standard deviation, capped at +/-4, and set to 0 ("average, no information") before the series exists.

MODELS  (a) logit     penalized (L2 / ridge) logistic regression; penalty chosen by time-ordered cross-validation
                      inside the training data (forward-chaining blocks, 6-month gap before each validation block)
        (b) equal     equal-weight index: average of the standardized inputs, turned into a probability by a
                      one-variable logistic fit (so it can be scored like the others)
        (c) layer1    the Layer 1 overall status (new rule) turned into historical event rates per color, shrunk
                      toward the base rate
        (d) base      the constant base rate of the training data

TEST    Expanding window: re-fit every January using only months whose 6-month outcome was already known
        (t <= December of the year before minus 6 months), then score that year's 12 months. Runs from 1980
        (1980-1999 = "pseudo out of sample", reported only) and from 2000 (the real test).

AMBER   Threshold chosen on pre-2000 data only (Troy's decision): from a model fitted on 1968-1999, in sample, the
        threshold whose episodes give about one false amber per real warning (a real warning = an episode
        followed by any event within 12 months while still on; Layer 1's episode rules). Red = 50%.

Writes data/model/score_*.csv and prints a summary. Charts: plot_score.py. Write-up: docs/model.md section 5.

Run it (after features.py and triggers.py):
    python src/model/score.py
"""

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from scipy.optimize import minimize
from scipy.special import expit
from sklearn.metrics import log_loss

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "model"))
from backtest_triggers import episodes, lead_for, live, months_between, WINDOW   # noqa: E402  (Layer 1 rules)

warnings.filterwarnings("ignore", category=UserWarning)   # sklearn chatter on tiny folds
MODEL = ROOT / "data" / "model"

HORIZON = 6                                    # months ahead the score looks
EXCLUDE_2020 = ("2019-09-01", "2021-03-01")    # 6 months before event #13 through its end
SHOCK_SCARES = [3, 6, 11, 14]                  # one-off shocks: winter 1977, 1984 week, Katrina, Minnesota/Ohio
MAIN = ["sahm", "claims_low", "claims_yoy", "cont_yoy", "temp_help", "yield_curve", "mfg", "nfci"]
JOLTS = ["jolts_layoffs", "jolts_hires"]
C_GRID = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0]   # smaller C = stronger penalty
CV_BLOCKS = 5
CLIP = 4.0
FIRST_FIT = "1968-02-01"                       # claims measures need a year of history
RED = 0.50
THETA_GRID = np.round(np.arange(0.05, 0.505, 0.01), 2)
LAYER1_SHRINK = 10                             # Layer 1 baseline: pseudo-months pulling each color to the base rate
MODELS = ["logit", "equal", "layer1", "base"]
DATA_END = None                                # last month of data; set in main() ("too recent to judge" uses it)


# ---------------------------------------------------------------------------------------------------
# Events, target and which months can be used
# ---------------------------------------------------------------------------------------------------
def load_events(drop: list[int] = ()) -> pd.DataFrame:
    ev = pd.read_csv(MODEL / "events.csv", dtype={"start_month": str, "end_month": str})
    ev = ev[~ev.event.isin(drop)].copy()
    ev["start"] = pd.to_datetime(ev.start_month + "-01")
    ev["end"] = [pd.Timestamp(e + "-01") if e != "ongoing" else pd.Timestamp("2100-01-01") for e in ev.end_month]
    return ev


def target(months: pd.DatetimeIndex, ev: pd.DataFrame) -> pd.DataFrame:
    """y, in_event and usable flags for every month."""
    df = pd.DataFrame(index=months)
    df["y"] = [int(((ev.start > t) & (ev.start <= t + pd.DateOffset(months=HORIZON))).any()) for t in months]
    df["in_event"] = [bool(((ev.start <= t) & (t <= ev.end)).any()) for t in months]
    df["in_2020"] = (months >= EXCLUDE_2020[0]) & (months <= EXCLUDE_2020[1])
    # The outcome of month t is only known once months t+1..t+6 have happened; the last 6 months can't be scored.
    df["outcome_known"] = months + pd.DateOffset(months=HORIZON) <= months[-1]
    df["usable"] = ~df.in_event & ~df.in_2020 & (months >= FIRST_FIT) & df.outcome_known
    return df


# ---------------------------------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------------------------------
def standardize(train: pd.DataFrame, rows: pd.DataFrame):
    """z-scores of `rows` using the mean / sd of `train`; capped at +/-CLIP; missing -> 0."""
    mean, sd = train.mean(), train.std().replace(0, np.nan)
    z = ((rows - mean) / sd).clip(-CLIP, CLIP).fillna(0.0)
    return z, mean, sd


class NonNegLogit:
    """Ridge logistic regression with every coefficient constrained to be >= 0 (sensitivity run).
    Same objective as scikit-learn's: C * sum(log-loss) + 0.5 * sum(coef^2), intercept not penalized.
    Since every input is signed so that higher = worse, a negative weight would mean "worse lowers the risk",
    which can happen when inputs move together; this run rules it out."""

    def __init__(self, C):
        self.C = C

    def fit(self, z, y):
        X, yv = np.asarray(z, float), np.asarray(y, float)

        def objective(w):
            eta = w[0] + X @ w[1:]
            p = expit(eta)
            value = self.C * np.sum(np.logaddexp(0, eta) - yv * eta) + 0.5 * w[1:] @ w[1:]
            g = self.C * (p - yv)
            return value, np.concatenate([[g.sum()], X.T @ g + w[1:]])

        bounds = [(None, None)] + [(0, None)] * X.shape[1]
        w = minimize(objective, np.zeros(X.shape[1] + 1), jac=True, method="L-BFGS-B", bounds=bounds).x
        self.intercept_, self.coef_ = np.array([w[0]]), np.array([w[1:]])
        return self

    def predict_proba(self, z):
        p = expit(self.intercept_[0] + np.asarray(z, float) @ self.coef_[0])
        return np.column_stack([1 - p, p])


def make_logit(C, nonneg=False):
    return NonNegLogit(C) if nonneg else LogisticRegression(C=C, max_iter=5000)


def choose_c(X: pd.DataFrame, y: pd.Series, nonneg: bool = False) -> float:
    """Penalty by time-ordered cross-validation: split the training months into CV_BLOCKS blocks in time order;
    for each block after the first, fit on all earlier blocks (dropping the last HORIZON months, whose targets
    overlap the block) and measure log-loss on the block. Smallest average loss wins; ties go to more penalty."""
    idx = X.index
    blocks = np.array_split(np.arange(len(idx)), CV_BLOCKS)
    scores = {c: [] for c in C_GRID}
    for k in range(1, CV_BLOCKS):
        val = idx[blocks[k]]
        fit = idx[np.concatenate(blocks[:k])]
        fit = fit[fit < val[0] - pd.DateOffset(months=HORIZON)]
        if y[fit].nunique() < 2:
            continue
        z_fit, mean, sd = standardize(X.loc[fit], X.loc[fit])
        z_val = ((X.loc[val] - mean) / sd).clip(-CLIP, CLIP).fillna(0.0)
        for c in C_GRID:
            m = make_logit(c, nonneg).fit(z_fit, y[fit])
            scores[c].append(log_loss(y[val], m.predict_proba(z_val)[:, 1], labels=[0, 1]))
    avg = {c: np.mean(v) for c, v in scores.items() if v}
    if not avg:
        return C_GRID[0]
    best = min(avg.values())
    return min(c for c, v in avg.items() if v <= best + 1e-9)


class Fitted:
    """All four models fitted on one training set; .predict(rows) gives their probabilities."""

    def __init__(self, F, tgt, status, train_idx, features, nonneg=False):
        self.features = features
        X, y = F.loc[train_idx, features], tgt.loc[train_idx, "y"]
        self.base = y.mean()
        z, self.mean, self.sd = standardize(X, X)
        self.C = choose_c(X, y, nonneg)
        self.logit = make_logit(self.C, nonneg).fit(z, y)
        idx = z.mean(axis=1).to_frame("index")
        self.equal = LogisticRegression(C=1e6, max_iter=5000).fit(idx, y)
        rates = {}
        for color in ["green", "amber", "red"]:
            sel = status.loc[train_idx] == color
            rates[color] = (y[sel].sum() + LAYER1_SHRINK * self.base) / (sel.sum() + LAYER1_SHRINK)
        self.layer1 = rates
        self.status = status

    def z(self, rows):
        return ((rows[self.features] - self.mean) / self.sd).clip(-CLIP, CLIP).fillna(0.0)

    def predict(self, F, rows) -> pd.DataFrame:
        z = self.z(F.loc[rows])
        out = pd.DataFrame(index=rows)
        out["logit"] = self.logit.predict_proba(z)[:, 1]
        out["equal"] = self.equal.predict_proba(z.mean(axis=1).to_frame("index"))[:, 1]
        out["layer1"] = self.status.loc[rows].map(self.layer1).fillna(self.base).values
        out["base"] = self.base
        return out

    def coefficients(self) -> dict:
        return {"C": self.C, "intercept": self.logit.intercept_[0],
                **dict(zip(self.features, self.logit.coef_[0]))}


# ---------------------------------------------------------------------------------------------------
# Out-of-sample loop
# ---------------------------------------------------------------------------------------------------
def run_oos(F, tgt, status, features, first_year, fit_from=FIRST_FIT, nonneg=False):
    """Re-fit each January from first_year; predict that year's months. Returns (predictions, coefficients)."""
    preds, coefs = [], []
    last = F.index[-1]
    for year in range(first_year, last.year + 1):
        refit = pd.Timestamp(f"{year}-01-01")
        known = refit - pd.DateOffset(months=HORIZON + 1)            # outcome of month t known by t + 6 months
        train = tgt.index[tgt.usable & (tgt.index <= known) & (tgt.index >= fit_from)]
        if tgt.loc[train, "y"].nunique() < 2:
            continue
        fitted = Fitted(F, tgt, status, train, features, nonneg)
        rows = F.index[(F.index.year == year)]
        p = fitted.predict(F, rows)
        p["fit_year"] = year
        preds.append(p)
        coefs.append({"year": year, "train_months": len(train), "train_events": int(tgt.loc[train, "y"].sum()),
                      **fitted.coefficients()})
    return pd.concat(preds), pd.DataFrame(coefs), fitted


# ---------------------------------------------------------------------------------------------------
# Thresholds, episodes and scoring
# ---------------------------------------------------------------------------------------------------
def score_episodes(p: pd.Series, theta: float, ev: pd.DataFrame):
    """Episodes of p >= theta (Layer 1 rules) and their outcomes: 'real' if any event starts within 12 months
    while the episode is live, 'during' if it starts inside an event, else 'false'."""
    on = p >= theta
    eps = episodes(on, p.notna())
    rows = []
    for s, e in eps:
        if ((ev.start < s) & (s <= ev.end)).any():
            outcome = "during event"
        else:
            nxt = ev[(ev.start >= s) & (ev.start <= s + pd.DateOffset(months=WINDOW))]
            nxt = nxt[[live(e, S) for S in nxt.start]]
            if len(nxt):
                outcome = f"real (#{int(nxt.iloc[0].event)})"
            elif s + pd.DateOffset(months=WINDOW) > DATA_END:
                outcome = "too recent to judge"      # its 12-month window isn't over yet
            else:
                outcome = "false"
        rows.append({"start": s, "end": e, "outcome": outcome})
    return pd.DataFrame(rows, columns=["start", "end", "outcome"]), eps, on


def pick_theta(p: pd.Series, ev: pd.DataFrame):
    """Threshold giving about one false amber per real warning (ties -> the lower threshold, which warns earlier)."""
    best, table = None, []
    for th in THETA_GRID:
        eps, _, _ = score_episodes(p, th, ev)
        real = eps.outcome.str.startswith("real").sum()
        false = (eps.outcome == "false").sum()
        table.append({"theta": th, "real": real, "false": false})
        if real:
            gap = abs(false / real - 1)
            if best is None or gap < best[0] - 1e-12:
                best = (gap, th)
    return (best[1] if best else None), pd.DataFrame(table)


def brier(p, y):
    return float(np.mean((p - y) ** 2))


def evaluate(pred: pd.DataFrame, tgt: pd.DataFrame, ev: pd.DataFrame, theta: float, col: str, start: str,
             skip_years=()):
    """Brier and skill on usable months from `start` (optionally leaving out some years from the Brier score);
    leads and false ambers for events from `start`."""
    sc = pred.index[(pred.index >= start)]
    use = sc[tgt.loc[sc, "usable"]]
    use = use[~use.year.isin(skip_years)]
    y = tgt.loc[use, "y"]
    out = {"months_scored": len(use), "event_months": int(y.sum()),
           "brier": brier(pred.loc[use, col], y), "brier_base": brier(pred.loc[use, "base"], y)}
    out["skill_vs_base"] = 1 - out["brier"] / out["brier_base"]
    p = pred.loc[sc, col]
    for name, th in (("amber", theta), ("red", RED)):
        if th is None:
            continue
        eps, raw, on = score_episodes(p, th, ev)
        later = eps[eps.start >= pd.Timestamp(start)]
        out[f"{name}_real"] = int(later.outcome.str.startswith("real").sum())
        out[f"{name}_false"] = int((later.outcome == "false").sum())
        out[f"{name}_too_recent"] = int((later.outcome == "too recent to judge").sum())
        out[f"{name}_false_starts"] = ", ".join(f"{s:%Y-%m}" for s in later[later.outcome == "false"].start)
        for event in ev[ev.start >= pd.Timestamp(start)].itertuples():
            out[f"{name}_lead_#{event.event}"] = lead_for(event, raw, on, p.notna(), WINDOW)[0]
    return out


def reliability(pred, tgt, col, start):
    sc = pred.index[(pred.index >= start)]
    use = sc[tgt.loc[sc, "usable"]]
    bins = [0, 0.05, 0.10, 0.20, 0.35, 0.50, 1.0]
    d = pd.DataFrame({"p": pred.loc[use, col], "y": tgt.loc[use, "y"]})
    d["bin"] = pd.cut(d.p, bins, include_lowest=True)
    r = d.groupby("bin", observed=False).agg(months=("y", "size"), mean_predicted=("p", "mean"),
                                             observed_rate=("y", "mean")).reset_index()
    r["model"] = col
    return r


# ---------------------------------------------------------------------------------------------------
def main() -> None:
    global DATA_END
    F = pd.read_csv(MODEL / "features_monthly.csv", parse_dates=["month"]).set_index("month")
    DATA_END = F.index[-1]
    trig = pd.read_csv(MODEL / "triggers_monthly.csv", parse_dates=["month"], keep_default_na=False)
    status = trig.set_index("month")["overall"]                 # Layer 1 overall status, new rule
    ev_all = load_events()
    tgt = target(F.index, ev_all)

    # ---- Main model: pseudo-OOS 1980-99 + OOS 2000-on, all four models ----
    pred, coefs, latest_fit = run_oos(F, tgt, status, MAIN, 1980)

    # ---- Amber threshold from pre-2000 data only: model fitted on 1968-1999, in-sample predictions ----
    pre = tgt.index[tgt.usable & (tgt.index <= "1999-06-01")]
    pre_fit = Fitted(F, tgt, status, pre, MAIN)
    pre_rows = F.index[(F.index >= FIRST_FIT) & (F.index <= "1999-12-01")]
    pre_pred = pre_fit.predict(F, pre_rows)
    thetas, theta_tables = {}, []
    for col in ["logit", "equal", "layer1"]:
        th, table = pick_theta(pre_pred[col], ev_all)
        thetas[col] = th
        theta_tables.append(table.assign(model=col, basis="in-sample 1968-1999"))
    th_pseudo, table = pick_theta(pred.loc[pred.index <= "1999-12-01", "logit"], ev_all)
    theta_tables.append(table.assign(model="logit", basis="pseudo-OOS 1980-1999"))
    theta = thetas["logit"]

    # ---- Evaluate 2000-on (and pseudo 1980-99 for reference) ----
    results = []
    for col in MODELS[:-1]:
        results.append({"run": "main", "model": col, "theta": thetas[col],
                        **evaluate(pred, tgt, ev_all, thetas[col], col, "2000-01-01")})
    pseudo = {"run": "main (pseudo-OOS 1980-1999)", "model": "logit", "theta": theta,
              **evaluate(pred[pred.index <= "1999-12-01"], tgt, ev_all, theta, "logit", "1980-01-01")}
    results.append(pseudo)
    rel = pd.concat([reliability(pred, tgt, c, "2000-01-01") for c in ["logit", "equal", "layer1"]])

    # ---- Sensitivity runs (logit), side by side with the main run ----
    sens = [{"run": "main", "theta": theta, **evaluate(pred, tgt, ev_all, theta, "logit", "2000-01-01"),
             "C_latest": coefs.iloc[-1].C}]
    variant_preds = {"main": pred.logit}

    #  (1) four one-off shock scares NOT counted as events
    ev_ns = load_events(drop=SHOCK_SCARES)
    tgt_ns = target(F.index, ev_ns)
    p_ns, c_ns, _ = run_oos(F, tgt_ns, status, MAIN, 1980)
    pre_ns = Fitted(F, tgt_ns, status, tgt_ns.index[tgt_ns.usable & (tgt_ns.index <= "1999-06-01")], MAIN)
    th_ns, _ = pick_theta(pre_ns.predict(F, pre_rows).logit, ev_ns)
    sens.append({"run": "shock scares #3, #6, #11, #14 not events", "theta": th_ns,
                 **evaluate(p_ns, tgt_ns, ev_ns, th_ns, "logit", "2000-01-01"), "C_latest": c_ns.iloc[-1].C})
    variant_preds["no_shock_scares"] = p_ns.logit

    #  (2a) without temp help
    feats = [f for f in MAIN if f != "temp_help"]
    p_nt, c_nt, _ = run_oos(F, tgt, status, feats, 1980)
    th_nt, _ = pick_theta(Fitted(F, tgt, status, pre, feats).predict(F, pre_rows).logit, ev_all)
    sens.append({"run": "without temp help", "theta": th_nt,
                 **evaluate(p_nt, tgt, ev_all, th_nt, "logit", "2000-01-01"), "C_latest": c_nt.iloc[-1].C})
    variant_preds["no_temp_help"] = p_nt.logit

    #  (2b) with JOLTS: fitted on 2001 on (JOLTS starts Dec 2000), tested from 2008; compared with the same
    #       2001-on fit without JOLTS. Indicative only (one recession, 2008, in the test). No pre-2000 data,
    #       so the main amber threshold is used.
    p_j, c_j, _ = run_oos(F, tgt, status, MAIN + JOLTS, 2008, fit_from="2001-01-01")
    p_j0, c_j0, _ = run_oos(F, tgt, status, MAIN, 2008, fit_from="2001-01-01")
    sens.append({"run": "2001-on fit WITHOUT JOLTS (comparison for the next row), tested 2008-on", "theta": theta,
                 **evaluate(p_j0, tgt, ev_all, theta, "logit", "2008-01-01"), "C_latest": c_j0.iloc[-1].C})
    sens.append({"run": "2001-on fit WITH JOLTS, tested 2008-on (indicative)", "theta": theta,
                 **evaluate(p_j, tgt, ev_all, theta, "logit", "2008-01-01"), "C_latest": c_j.iloc[-1].C})
    variant_preds["jolts_2001fit"] = p_j.logit
    variant_preds["no_jolts_2001fit"] = p_j0.logit

    #  (3) claims revisions: claims measures from FRED's vintages from 2010 (as published), else current
    Fv = F.copy()
    for a, b in [("claims_low", "claims_low_v"), ("claims_yoy", "claims_yoy_v"), ("cont_yoy", "cont_yoy_v")]:
        Fv[a] = F[b].where(F[b].notna(), F[a])
    p_v, c_v, _ = run_oos(Fv, tgt, status, MAIN, 1980)
    main_2010 = evaluate(pred, tgt, ev_all, theta, "logit", "2010-01-01")
    vint_2010 = evaluate(p_v, tgt, ev_all, theta, "logit", "2010-01-01")
    sens.append({"run": "main, scored 2010-on (current-vintage claims)", "theta": theta, **main_2010, "C_latest": coefs.iloc[-1].C})
    sens.append({"run": "claims as published at the time (FRED vintages), scored 2010-on", "theta": theta, **vint_2010,
                 "C_latest": c_v.iloc[-1].C})
    variant_preds["claims_vintage"] = p_v.logit
    sens.append({"run": "main, scored 2010-on WITHOUT 2022-2023", "theta": theta, "C_latest": coefs.iloc[-1].C,
                 **evaluate(pred, tgt, ev_all, theta, "logit", "2010-01-01", skip_years=(2022, 2023))})
    sens.append({"run": "claims vintages, scored 2010-on WITHOUT 2022-2023", "theta": theta, "C_latest": c_v.iloc[-1].C,
                 **evaluate(p_v, tgt, ev_all, theta, "logit", "2010-01-01", skip_years=(2022, 2023))})

    #  (4) extra: coefficients constrained >= 0 (not in Troy's list; added because continued claims gets a
    #      negative weight in the main fit, which makes the contributions hard to read)
    p_nn, c_nn, nn_fit = run_oos(F, tgt, status, MAIN, 1980, nonneg=True)
    th_nn, _ = pick_theta(Fitted(F, tgt, status, pre, MAIN, nonneg=True).predict(F, pre_rows).logit, ev_all)
    sens.append({"run": "coefficients constrained >= 0", "theta": th_nn,
                 **evaluate(p_nn, tgt, ev_all, th_nn, "logit", "2000-01-01"), "C_latest": c_nn.iloc[-1].C})
    variant_preds["nonneg"] = p_nn.logit
    c_nn.to_csv(MODEL / "score_coefficients_nonneg.csv", index=False)
    rel = pd.concat([rel, reliability(p_nn.rename(columns={"logit": "logit_nonneg"}), tgt, "logit_nonneg",
                                      "2000-01-01")])
    diff = (p_v.logit - pred.logit)[pred.index >= "2010-01-01"]

    # ---- Contributions to the latest score (the model re-fitted in January of the latest year) ----
    last = F.index[-1]
    z = latest_fit.z(F.loc[[last]]).iloc[0]
    coef = pd.Series(latest_fit.logit.coef_[0], index=MAIN)
    contrib = pd.DataFrame({"raw_value": F.loc[last, MAIN], "z": z, "coefficient": coef,
                            "contribution_log_odds": coef * z})
    contrib.loc["intercept", "contribution_log_odds"] = latest_fit.logit.intercept_[0]
    contrib.loc["total (log-odds)", "contribution_log_odds"] = contrib.contribution_log_odds.sum()
    contrib.loc["probability", "contribution_log_odds"] = pred.loc[last, "logit"]
    z_nn = nn_fit.z(F.loc[[last]]).iloc[0]
    coef_nn = pd.Series(nn_fit.logit.coef_[0], index=MAIN)
    contrib["coefficient_nonneg"] = coef_nn
    contrib["contribution_nonneg"] = coef_nn * z_nn
    contrib.loc["intercept", "contribution_nonneg"] = nn_fit.logit.intercept_[0]
    contrib.loc["total (log-odds)", "contribution_nonneg"] = contrib.contribution_nonneg.iloc[:len(MAIN) + 1].sum()
    contrib.loc["probability", "contribution_nonneg"] = p_nn.loc[last, "logit"]

    # ---- Save ----
    out = pred.join(tgt)
    for k, v in variant_preds.items():
        out[f"logit_{k}"] = v
    out["theta_amber"], out["red"] = theta, RED
    out.to_csv(MODEL / "score_oos.csv", date_format="%Y-%m-%d", index_label="month")
    pre_pred.join(tgt).to_csv(MODEL / "score_pre2000_insample.csv", date_format="%Y-%m-%d", index_label="month")
    coefs.to_csv(MODEL / "score_coefficients.csv", index=False)
    pd.DataFrame(results).to_csv(MODEL / "score_results.csv", index=False)
    pd.DataFrame(sens).to_csv(MODEL / "score_sensitivity.csv", index=False)
    rel.to_csv(MODEL / "score_reliability.csv", index=False)
    pd.concat(theta_tables).to_csv(MODEL / "score_thresholds.csv", index=False)
    contrib.to_csv(MODEL / "score_contributions.csv", index_label="indicator")

    # ---- Print ----
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 60)
    print(f"Amber threshold (pre-2000, in-sample fit): logit {thetas['logit']}, equal {thetas['equal']}, "
          f"layer1 {thetas['layer1']}; pseudo-OOS 1980-99 logit: {th_pseudo}")
    print(pd.DataFrame(results).set_index(["run", "model"]).T.to_string())
    print()
    print(pd.DataFrame(sens).set_index("run").T.to_string())
    print()
    print(f"Claims vintages vs current, 2010-on: mean |score difference| {diff.abs().mean():.3f}, "
          f"max {diff.abs().max():.3f} ({diff.abs().idxmax():%Y-%m})")
    print()
    print(rel.to_string(index=False))
    print()
    print(coefs.round(3).to_string(index=False))
    print()
    print(f"Latest month {last:%Y-%m}:")
    print(contrib.round(3).to_string())


if __name__ == "__main__":
    main()
