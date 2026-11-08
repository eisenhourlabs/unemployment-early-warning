"""
Stage 3e: write the FROZEN model, the fixed set of numbers the live run (live.py) uses until the next January re-fit.

"Frozen" means nothing is re-estimated between re-fits: every weekly live run plugs that week's inputs into the same
coefficients, residuals and event paths. This file re-fits exactly what the backtest fitted in January of the model
year (docs/model.md sections 5.10 and 6), using only what was known on 1 January of that year:

  score      the final early-warning model (ridge logistic, eight trigger measures, weights >= 0) for 3, 6 and 12
             months: the standardizing mean / sd of each input, the weights, the intercept and the penalty
  colour     the hysteresis rule (amber in 20% / out below 15%, red in 50% / out below 40%) and the display rules
  forecast   the fan baselines (ridge on the score inputs + level, quiet origins only) for the targets shown on the
             site: unemployment rate 3 / 6 / 12 months, continuing claims rate 13 / 26 weeks. Each with its weights,
             mean / sd, penalty and the cross-validation residuals that supply the noise. Initial-claims fans and the
             52-week continuing-claims fan are not shown (stage 3d decisions), so they are not frozen.
             Plus the deterioration paths of every past event (2020 excluded) for the mixture.
  stress     the 2001-type (#9) and 2008-type (#12) paths for all three targets (what-ifs, not forecasts)
  nowcast    the coefficients of the next-release nowcast, fitted on every release before 1 January

Writes data/model/frozen/model_<year>.json. Run it once a year after the January re-fit (stage 3e-3 automates
that in a pull request), or now for the current year:
    python src/model/freeze_model.py            (model year = this year)
    python src/model/freeze_model.py 2026
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "model"))
import score as S                                  # noqa: E402  (the early-warning score)
import forecast as FC                              # noqa: E402  (the forecast fans)
import nowcast as NC                               # noqa: E402

MODEL = ROOT / "data" / "model"
FROZEN = MODEL / "frozen"

# What the site shows (docs/model.md section 6, stage 3d decisions)
FAN_TARGETS = {"ur": [3, 6, 12], "cc": [13, 26]}
STRESS_EVENTS = {9: "2001-type", 12: "2008-type"}
COLOUR = {"amber_in": 0.20, "amber_out": 0.15, "red_in": 0.50, "red_out": 0.40}
DISPLAY = {"words_from": 0.35, "more_likely_from": 0.50, "below_text_under": 0.005, "nowcast_range_pt": 0.2}
# Long-run (2000-on) base rates of an event starting within 3 / 6 / 12 months (docs/model.md 6, A5)
BASE_RATES = {"3": 0.075, "6": 0.153, "12": 0.304}


def clean(values) -> list:
    """List of floats with None for blanks (JSON has no NaN)."""
    return [None if pd.isna(v) else round(float(v), 10) for v in values]


# ---------------------------------------------------------------------------------------------------
def freeze_score(year: int) -> dict:
    F = pd.read_csv(MODEL / "features_monthly.csv", parse_dates=["month"]).set_index("month")
    S.DATA_END = F.index[-1]
    status = pd.read_csv(MODEL / "triggers_monthly.csv", parse_dates=["month"], keep_default_na=False).set_index("month")["overall"]
    ev = S.load_events()
    out = {}
    for h in (3, 6, 12):
        S.HORIZON = h
        t = S.target(F.index, ev)
        known = pd.Timestamp(f"{year}-01-01") - pd.DateOffset(months=h + 1)   # outcomes known by 1 January
        train = t.index[t.usable & (t.index <= known) & (t.index >= S.FIRST_FIT)]
        fit = S.Fitted(F, t, status, train, S.FINAL_FEATURES, nonneg=S.FINAL_NONNEG)
        out[str(h)] = {
            "train_months": int(len(train)), "train_first": f"{train[0]:%Y-%m}", "train_last": f"{train[-1]:%Y-%m}",
            "train_events": int(t.loc[train, "y"].sum()), "C": fit.C,
            "intercept": float(fit.logit.intercept_[0]),
            "weights": dict(zip(S.FINAL_FEATURES, clean(fit.logit.coef_[0]))),
            "mean": dict(zip(S.FINAL_FEATURES, clean(fit.mean[S.FINAL_FEATURES]))),
            "sd": dict(zip(S.FINAL_FEATURES, clean(fit.sd[S.FINAL_FEATURES]))),
        }
        print(f"  score {h:>2}-month: {len(train)} training months, C = {fit.C}, weights "
              + ", ".join(f"{k} {v:.2f}" for k, v in zip(S.FINAL_FEATURES, fit.logit.coef_[0]) if v > 0))
    S.HORIZON = 6
    return {"features": S.FINAL_FEATURES, "clip": S.CLIP, "horizons": out}


# ---------------------------------------------------------------------------------------------------
def freeze_forecast(year: int) -> tuple[dict, dict]:
    F, P, ev, ur_final, weekly = FC.load()
    library_ev = ev[ev.group != "2020"]
    refit = pd.Timestamp(f"{year}-01-01")
    origins = pd.date_range("1968-03-01", refit - pd.DateOffset(months=1), freq="MS")
    targets, stress = {}, {}
    for name in ["ur", "ic", "cc"]:
        ser = FC.Series(name, ur_final, weekly)
        # Stress paths (all three targets; the site shows initial-claims what-ifs, not fans)
        st_paths = FC.event_paths(ser, ev[ev.event.isin(STRESS_EVENTS)], 24 if ser.freq == "M" else 104)
        stress[name] = {f"{STRESS_EVENTS[e]} (#{e})": clean(info["path"]) for e, info in st_paths.items()}
        if name not in FAN_TARGETS:
            continue
        max_k = 60 if ser.freq == "M" else 260
        paths = FC.event_paths(ser, library_ev, max_k)
        facts = {}
        for m in origins:
            if m < pd.Timestamp(ser.first):
                continue
            d = m + pd.offsets.MonthEnd(0)
            L, y0, _ = ser.known(d)
            facts[m] = (d, L, y0)
        _, _, known_series = ser.known(refit - pd.Timedelta(days=1))       # values as known at the re-fit
        horizons = {}
        for h in FAN_TARGETS[name]:
            hm = FC.months_for(ser.freq, h)
            Xtr, ytr = [], []
            for m, (d, L, y0) in facts.items():
                if d >= refit:
                    break
                T = ser.step(L, h)
                if T not in known_series.index:
                    continue
                in_prog = ((ev.start <= m) & (m <= ev.end) & (ev.group != "2020")).any()
                starts = ((ev.start > m) & (ev.start <= m + pd.DateOffset(months=hm))).any()
                covid = (m <= FC.COVID[1]) and (m + pd.DateOffset(months=hm) >= FC.COVID[0] - pd.DateOffset(months=1))
                if covid or in_prog or starts:
                    continue                                       # baseline: quiet origins only
                level = ser.change(1, y0) if ser.scale == "log" else y0
                Xtr.append(pd.concat([F.loc[m], pd.Series({"level": level})]).rename(m))
                ytr.append(ser.change(y0, known_series[T]))
            Xtr = pd.DataFrame(Xtr)
            ytr = pd.Series(ytr, index=Xtr.index)
            model, Xref, resid, alpha = FC.fit_baseline(Xtr, ytr, hm)
            cols = list(Xref.columns)
            horizons[str(h)] = {
                "horizon_months": hm, "train_origins": int(len(Xtr)), "alpha": alpha,
                "columns": cols, "intercept": float(model.intercept_), "weights": clean(model.coef_),
                "mean": clean(Xref.mean()), "sd": clean(Xref.std()), "residuals": clean(resid),
            }
            print(f"  fan {name} {h:>2}: {len(Xtr)} quiet origins, ridge alpha {alpha}, {len(resid)} residuals")
        targets[name] = {
            "label": FC.LABEL[name], "frequency": ser.freq, "scale": ser.scale, "release_lag_days": ser.lag,
            "horizons": horizons,
            "paths": [{"event": int(e), "group": info["group"], "start": f"{info['start']:%Y-%m}",
                       "base": f"{info['base']:%Y-%m-%d}", "length_months": int(info["length_months"]),
                       "path": clean(info["path"])} for e, info in paths.items()],
        }
    fc = {"draws": FC.DRAWS, "quantiles": FC.QUANTILES, "clip": FC.CLIP,
          "in_progress_min_months": FC.IN_PROGRESS_MIN_MONTHS, "targets": targets}
    return fc, stress


# ---------------------------------------------------------------------------------------------------
def freeze_nowcast(year: int) -> dict:
    df = NC.release_table()
    train = df[(df.released < pd.Timestamp(f"{year}-01-01"))]
    train = train[~((train.index >= "2020-03-01") & (train.index <= "2020-12-01"))]   # 2020 not fitted
    model = LinearRegression(fit_intercept=False).fit(train[NC.X], train.change)
    print(f"  nowcast: {len(train)} releases, coefficients "
          + ", ".join(f"{k} {v:+.3f}" for k, v in zip(NC.X, model.coef_)))
    return {"columns": NC.X, "weights": clean(model.coef_), "train_releases": int(len(train)),
            "train_last": f"{train.index[-1]:%Y-%m}", "initial_claims_lag_days": 5, "continuing_claims_lag_days": 12}


# ---------------------------------------------------------------------------------------------------
def main() -> None:
    year = int(sys.argv[1]) if len(sys.argv) > 1 else datetime.now().year
    FROZEN.mkdir(parents=True, exist_ok=True)
    print(f"Freezing the model for {year} (everything known on {year}-01-01)")
    score = freeze_score(year)
    fc, stress = freeze_forecast(year)
    model = {
        "model_year": year,
        "data_known_by": f"{year}-01-01",
        "frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "description": "Unemployment Watch early-warning model, frozen at the January re-fit (docs/model.md 5.10, 6; "
                       "docs/phase3e_design.md). Model output, not official statistics.",
        "colour": COLOUR, "display": DISPLAY, "base_rates": BASE_RATES,
        "score": score, "forecast": fc, "stress": stress, "nowcast": freeze_nowcast(year),
    }
    path = FROZEN / f"model_{year}.json"
    path.write_text(json.dumps(model, indent=1, allow_nan=False), encoding="utf-8")
    print(f"Wrote {path.relative_to(ROOT)} ({path.stat().st_size / 1024:,.0f} KB)")


if __name__ == "__main__":
    main()
