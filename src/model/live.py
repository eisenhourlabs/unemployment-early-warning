"""
Stage 3e: the LIVE run. One "as of" result set from the frozen model and everything published by the run date.

Every number below starts from the same inputs (docs/phase3e_design.md, "One 'as of' set per run"):
  score      3 / 6 / 12-month probabilities of a new deterioration event (coherent: 3 <= 6 <= 12), the three
             largest drivers of the 6-month score in plain English, and the colour. The colour comes from the
             stored HISTORY with the hysteresis rule (previous colour + new score = new colour), never from today's
             value alone.
  triggers   the Layer 1 panel (1 Sahm, 2 claims vs. 52-week low, 4 continued claims, 6 yield curve, 8 NFCI) and the
             overall status (new rule), plus temp help (5) and manufacturing (7) as context; each with its last
             colour change
  fans       unemployment rate 3 / 6 / 12 months, continuing claims rate 13 / 26 weeks (the horizons that passed
             the gate), from the frozen baselines and event paths (docs/model.md section 6)
  stress     2001-type and 2008-type what-if paths for all three targets, from today's levels
  nowcast    the next unemployment-rate release, once claims for its reference week are out
  fomc       the latest FOMC median for this year's Q4 (FRED UNRATEMD), beside our Q4 median

Nothing is re-estimated: the coefficients, residuals and event paths come from data/model/frozen/model_<year>.json
(freeze_model.py). The fans are simulations (4,000 draws, fixed seed), so a re-run on the same day gives the same
numbers.

Writes:
  data/model/live_latest.json          the result set the site reads
  data/model/live_history.csv          one row per live run (score, colour, inputs, nowcast); re-running a date
                                       replaces its row. "Change vs. last week" compares only live with live
  data/model/live_fans_history.csv     every live run's fans (the forecast archive download)
  data/model/score_display_weekly.csv  weekly 6-month score since 2000 with its colour (Overview history line):
                                       the weekly out-of-sample backtest ("backtest"), then this run ("live")
  data/model/score_display_monthly.csv monthly 3 / 6 / 12-month scores since 1980 with the colour (Outlook history):
                                       1980-1999 "pseudo out of sample", 2000 on "out of sample"

  data/archive/YYYY/<date>_ic<week>_ur<month>.json   (--archive only) the permanent record of each live run, opened
                                       create-only: the run FAILS rather than overwrite an existing file
  data/model/live_status.json          (--archive only) the last attempt: new run, skipped (no new inputs) or failed

The "Refresh data" workflow runs it with --archive after every refresh; it does real work only when there is a new
claims week or unemployment month (Thursday claims, jobs report). On the PC, run it without --archive to preview.
    python src/model/live.py                         (preview, today)
    python src/model/live.py 2026-11-08              (preview, a given date)
    python src/model/live.py --archive               (what the workflow runs)
    python src/model/live.py --record-failure "why"  (the workflow, when the model's inputs could not be refreshed)
"""

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "model"))
import triggers as TR                               # noqa: E402  (Layer 1 trigger rules)
from features import features_at, YIELD_LAG         # noqa: E402
from nowcast import reference_saturday              # noqa: E402
from realtime import as_known_on                    # noqa: E402

MODEL = ROOT / "data" / "model"
PROCESSED = ROOT / "data" / "processed"
FROZEN = MODEL / "frozen"
OUT = MODEL / "live_latest.json"
WEEKLY_OUT = MODEL / "score_display_weekly.csv"
MONTHLY_OUT = MODEL / "score_display_monthly.csv"
RUNS = MODEL / "live_history.csv"                   # one row per live run (re-running a date replaces its row)
FANS_HISTORY = MODEL / "live_fans_history.csv"     # every live run's fans (the forecast archive download)
STATUS = MODEL / "live_status.json"                 # the last attempt: ok / skipped / failed
ARCHIVE = ROOT / "data" / "archive"                 # permanent, create-only: one file per live run
SEED = 20261108                                     # fixed seed: same inputs give the same fans
PANEL = ["sahm", "claims_vs_low", "cont_claims_yoy", "yield_curve", "nfci"]
CONTEXT = ["temp_help", "mfg_surveys"]


# ===================================================================================================
# Small helpers
# ===================================================================================================
def load_frozen(asof: pd.Timestamp) -> dict:
    """The newest frozen model whose year is not after the run date's year."""
    files = sorted(FROZEN.glob("model_*.json"))
    usable = [f for f in files if int(f.stem.split("_")[1]) <= asof.year]
    if not usable:
        sys.exit(f"No frozen model in {FROZEN.relative_to(ROOT)} for {asof.year}: run python src/model/freeze_model.py")
    return json.loads(usable[-1].read_text(encoding="utf-8"))


def num(v) -> float:
    """None / missing -> NaN, otherwise a float."""
    return float("nan") if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def score_display(p: float, disp: dict) -> dict:
    """How the site shows a probability: a whole percent up to 35%, words above (number in the tooltip only).
    Rounding: whole percent ('1.8' -> '2%'), '<1%' below 0.5%."""
    pct = math.floor(p * 100 + 0.5)
    number = "<1%" if p < disp["below_text_under"] else f"{pct}%"
    if p >= disp["more_likely_from"]:
        return {"text": "More likely than not", "number": number, "words": True, "tooltip": f"about {pct}% in testing terms"}
    if p >= disp["words_from"]:
        return {"text": "Elevated", "number": number, "words": True, "tooltip": f"about {pct}% in testing terms"}
    return {"text": number, "number": number, "words": False, "tooltip": f"{p * 100:.1f}%"}


def hysteresis(values: pd.Series, c: dict) -> pd.Series:
    """Colour with hysteresis (docs/model.md 6, A4): amber is entered at 20% and kept until the score falls below
    15%; red is entered at 50% and kept until it falls below 40%. Same rule as score_followups.hysteresis."""
    out, state = [], "green"
    for v in values:
        if pd.isna(v):
            out.append(state)
            continue
        if state == "red" and v < c["red_out"]:
            state = "amber" if v >= c["amber_out"] else "green"
        elif state == "amber":
            if v >= c["red_in"]:
                state = "red"
            elif v < c["amber_out"]:
                state = "green"
        elif state == "green":
            state = "red" if v >= c["red_in"] else "amber" if v >= c["amber_in"] else "green"
        out.append(state)
    return pd.Series(out, index=values.index)


# ===================================================================================================
# Score
# ===================================================================================================
def probability(fz: dict, x: dict, h: int) -> tuple[float, list[dict]]:
    """Probability for horizon h from the frozen weights; returns (p, contributions in log-odds)."""
    m, clip = fz["score"]["horizons"][str(h)], fz["score"]["clip"]
    eta, parts = m["intercept"], []
    for f in fz["score"]["features"]:
        v, mean, sd, w = num(x.get(f)), m["mean"][f], m["sd"][f], m["weights"][f]
        z = 0.0 if math.isnan(v) or not sd else max(-clip, min(clip, (v - mean) / sd))   # missing -> average
        parts.append({"input": f, "value": None if math.isnan(v) else v, "z": z, "weight": w, "contribution": w * z,
                      "mean": mean})
        eta += w * z
    return float(expit(eta)), parts


def driver_sentence(f: str, v: float, up: bool, mean: float | None = None) -> str:
    """Fixed plain-English templates (design brief, Overview). Inputs are signed so higher = worse; the template is
    chosen by the direction of the contribution, and checked against the raw value so it never says something false.
    mean: the input's training average (temp help: the usual 6-month change is minus this)."""
    if f == "claims_low":
        text = (f"New claims have risen {v * 100:.0f}% above their low of the past year" if up and v > 0
                else "New claims are close to their low of the past year" if up
                else "New claims are near their lowest level of the past year")
    elif f == "sahm":
        text = (f"Unemployment's 3-month average is {v:.2f} pt above its low of the past year" if up
                else "Unemployment is close to its low of the past year")
    elif f == "temp_help":
        change = -v                                  # the input is MINUS the 6-month change
        if up:
            usual = f"less than its usual {-mean * 100:.1f}%" if mean is not None and mean < 0 else "less than usual"
            text = (f"Temporary-help jobs fell {abs(change) * 100:.1f}% over six months" if change < 0
                    else f"Temporary-help jobs grew only {change * 100:.1f}% over six months, {usual}")
        else:
            text = ("Temporary-help jobs grew over six months" if change >= 0
                    else f"Temporary-help jobs fell only {abs(change) * 100:.1f}% over six months, less than usual")
    elif f == "mfg":
        text = "Regional factory surveys are weak" if up else "Regional factory surveys are strong"
    elif f == "nfci":
        if up:
            text = ("Financial conditions are tighter than average" if v > 0
                    else "Financial conditions are less loose than usual")
        else:
            text = ("Financial conditions are looser than average" if v < 0
                    else "Financial conditions are only slightly tighter than average")
    elif f == "yield_curve":
        if up:
            text = ("The yield curve was inverted within the past 18 months" if v > 0
                    else "The yield curve has been flatter than usual over the past 18 months")
        else:
            text = "The yield curve has not been inverted recently"
    elif f == "claims_yoy":
        text = f"New claims are {abs(v) * 100:.0f}% {'above' if v > 0 else 'below'} a year ago"
    elif f == "cont_yoy":
        text = f"Continuing claims are {abs(v) * 100:.0f}% {'above' if v > 0 else 'below'} a year ago"
    else:
        text = f"{f} {'pushes up' if up else 'pulls down'}"
    return text


def driver_text(p: dict) -> str:
    """A contribution as a sentence ending '(pushes the score up)' or '(pulls the score down)'."""
    up = p["contribution"] > 0
    return (driver_sentence(p["input"], p["value"], up, p.get("mean"))
            + (" (pushes the score up)" if up else " (pulls the score down)"))


def drivers(parts: list[dict], n=3) -> list[dict]:
    """The n largest contributions by absolute size; inputs with zero weight (or no data) are never listed."""
    live = [p for p in parts if p["weight"] > 0 and p["value"] is not None and abs(p["contribution"]) > 1e-9]
    live.sort(key=lambda p: -abs(p["contribution"]))
    return [{"input": p["input"], "direction": "up" if p["contribution"] > 0 else "down",
             "contribution": p["contribution"], "text": driver_text(p)}
            for p in live[:n]]


def weekly_history(fz: dict, asof: pd.Timestamp, p6_now: float, runs: pd.DataFrame) -> pd.DataFrame:
    """Weekly 6-month scores: the out-of-sample backtest (score_weekly.csv, every Thursday from 2000 with that
    year's model), topped up with the frozen model for Thursdays after it up to a week before the first live run
    (or this run), then every earlier live run (live_history.csv) and this run. Colour = hysteresis over the whole
    sequence."""
    earlier = runs[runs.index < asof]
    first_live = earlier.index[0] if len(earlier) else asof
    wk = pd.read_csv(MODEL / "score_weekly.csv", parse_dates=["thursday"]).set_index("thursday")["score"]
    fill = pd.date_range(wk.index[-1] + pd.Timedelta(days=7), first_live - pd.Timedelta(days=7), freq="W-THU")
    extra = {d: probability(fz, features_at(d), 6)[0] for d in fill}
    df = pd.DataFrame({"score": pd.concat([wk, pd.Series(extra, dtype=float)])})
    df["basis"] = "backtest"
    df = df[df.index < first_live]
    for d, r in earlier.iterrows():
        df.loc[d] = [r.p6, "live"]
    df.loc[asof] = [p6_now, "live"]
    df["colour"] = hysteresis(df.score, fz["colour"])
    df.index.name = "date"
    return df


def monthly_history(fz: dict) -> pd.DataFrame:
    """Monthly scores since 1980 (out of sample: each year scored by a model fitted that January)."""
    oos = pd.read_csv(MODEL / "score_oos.csv", parse_dates=["month"]).set_index("month")
    hz = pd.read_csv(MODEL / "score_horizons.csv", parse_dates=["month"]).set_index("month")
    df = pd.DataFrame({"p3": hz.p3, "p6": oos.logit, "p12": hz.p12}).dropna(subset=["p6"])
    df["basis"] = np.where(df.index < "2000-01-01", "pseudo out of sample", "out of sample")
    df["colour"] = hysteresis(df.p6, fz["colour"])
    df.index.name = "month"
    return df


# ===================================================================================================
# Layer 1 triggers
# ===================================================================================================
def triggers_now(asof: pd.Timestamp) -> dict:
    cfg = pd.read_csv(TR.CONFIG).set_index("trigger_id")
    funcs = {"sahm": TR.t_sahm, "claims_vs_low": TR.t_claims_vs_low, "cont_claims_yoy": TR.t_cont_claims_yoy,
             "temp_help": TR.t_temp_help, "mfg_surveys": TR.t_mfg, "nfci": TR.t_nfci}
    spread = TR.yield_spread()
    ycol = TR.yield_colors(spread, int(cfg.loc["yield_curve", "amber"]), int(cfg.loc["yield_curve", "red"]))
    known = spread[spread.index + YIELD_LAG <= asof]                 # same rule as the score input
    hist = pd.read_csv(MODEL / "triggers_monthly.csv", parse_dates=["month"], keep_default_na=False).set_index("month")
    rows = []
    for tid in PANEL + CONTEXT:
        c = cfg.loc[tid]
        if tid == "yield_curve":
            m = known.index[-1]
            value, colour, basis, through = round(float(known.iloc[-1]), 2), ycol[m], "real-time", f"{m:%Y-%m}"
        else:
            value, colour, basis = funcs[tid](asof, c)
            through = ""
        # Last colour change: monthly history (as of each month end) followed by today's colour.
        seq = [(m, col) for m, col in hist[f"{tid}_color"].items() if col] + [(asof, colour)]
        change = None
        for i in range(len(seq) - 1, 0, -1):
            if seq[i][1] != seq[i - 1][1]:
                change = {"when": f"{seq[i][0]:%Y-%m-%d}", "monthly": seq[i][0] != asof,
                          "to": seq[i][1], "from": seq[i - 1][1]}
                break
        rows.append({"id": tid, "order": int(c.order), "role": c.layer1_role, "name": c["name"],
                     "note": c.panel_note if isinstance(c.panel_note, str) else "", "value": value, "colour": colour,
                     "basis": basis, "through": through, "last_change": change, "amber": c.amber, "red": c.red})
    on = lambda ids, levels=("amber", "red"): sum(r["colour"] in levels for r in rows if r["id"] in ids)
    core = list(cfg[cfg.layer1_role == "core"].index)
    overall = ("red" if on(core, ("red",)) else
               "amber" if on(core) >= 1 and on(PANEL) >= 2 else "green")
    return {"rows": rows, "overall": overall,
            "rule": "Red if trigger 1, 2 or 4 is red; amber if one of 1, 2, 4 is amber or red and another panel "
                    "trigger is amber or red; otherwise green."}


# ===================================================================================================
# Fans and stress paths
# ===================================================================================================
def target_level(name: str, asof: pd.Timestamp, lag_days) -> tuple[pd.Timestamp, float, pd.Series]:
    """(latest period, level, series) of a fan target as published on the run date. Claims rates are 4-week
    averages of today's figures cut back by their release lag (the backtest's rule)."""
    if name == "ur":
        s = as_known_on("UNRATE", asof).dropna()
    else:
        w = pd.read_csv(MODEL / "claims_weekly.csv", parse_dates=["week_ended"]).set_index("week_ended")
        col = "ic_rate_sa" if name == "ic" else "cc_rate_sa"
        s = w[col].rolling(4).mean().dropna()
        s = s[s.index + pd.Timedelta(days=lag_days) <= asof]
    return s.index[-1], float(s.iloc[-1]), s


def step(freq: str, t: pd.Timestamp, k: int) -> pd.Timestamp:
    return t + pd.DateOffset(months=k) if freq == "M" else t + pd.Timedelta(weeks=k)


def apply(scale: str, level: float, change):
    return level + change if scale == "points" else level * np.exp(change)


def event_in_progress(asof: pd.Timestamp):
    """The event under way on the run date (events.csv, 2020 excluded), or None. A new event only appears here once
    Troy has classified it and events.csv says so."""
    ev = pd.read_csv(MODEL / "events.csv", dtype={"start_month": str, "end_month": str})
    ev = ev[ev.classification != "recession (pandemic)"]
    m = pd.Timestamp(f"{asof:%Y-%m}-01")
    for e in ev.itertuples():
        start = pd.Timestamp(e.start_month + "-01")
        end = pd.Timestamp("2100-01-01") if e.end_month == "ongoing" else pd.Timestamp(e.end_month + "-01")
        if start <= m <= end:
            return start
    return None


def fan(fz: dict, name: str, x: dict, probs: dict, asof: pd.Timestamp, rng) -> dict:
    """One target's fan at every shown horizon (the stage 3d mixture, with the frozen pieces)."""
    fc = fz["forecast"]
    t = fc["targets"][name]
    freq, scale = t["frequency"], t["scale"]
    L, y0, series = target_level(name, asof, t["release_lag_days"])
    D, Q = fc["draws"], fc["quantiles"]
    paths = [dict(p, start=pd.Timestamp(p["start"] + "-01"), base=pd.Timestamp(p["base"]),
                  path=np.array([np.nan if v is None else v for v in p["path"]])) for p in t["paths"]]
    cur_start = event_in_progress(asof)
    age_now = 0 if cur_start is None else (asof.year - cur_start.year) * 12 + asof.month - cur_start.month + 1
    out = []
    for h_key, hz in t["horizons"].items():
        h, hm = int(h_key), hz["horizon_months"]
        level_feature = np.log(y0) if scale == "log" else y0
        xrow = np.array([level_feature if c == "level" else num(x.get(c)) for c in hz["columns"]])
        mean, sd = np.array(hz["mean"], float), np.array(hz["sd"], float)
        z = np.clip((xrow - mean) / np.where(sd == 0, np.nan, sd), -fc["clip"], fc["clip"])
        z = np.where(np.isnan(z), 0.0, z)
        base_pred = hz["intercept"] + float(z @ np.array(hz["weights"]))
        resid = np.array(hz["residuals"])
        if cur_start is not None and age_now >= fc["in_progress_min_months"]:
            # An event has lasted 3+ months: follow past events from the same age (weight 1).
            age_m = age_now - 1
            if freq == "M":
                base_period = cur_start - pd.DateOffset(months=1)
                k_l = (L.year - base_period.year) * 12 + L.month - base_period.month
            else:
                k_l = int((L - series.index[series.index < cur_start][-1]).days // 7)
            ok = lambda p: len(p["path"]) > k_l + h and not np.isnan(p["path"][k_l + h])
            cands = [p for p in paths if p["start"] < cur_start and p["length_months"] >= age_m + 1 and ok(p)
                     and step(freq, p["base"], k_l + h) <= L]
            if not cands:
                cands = [p for p in paths if p["start"] < cur_start and p["group"] == "recession" and ok(p)]
            det = np.array([p["path"][k_l + h] - p["path"][k_l] for p in cands]) if cands else np.zeros(1)
            det_draw, is_det, w, share = det[rng.integers(0, len(det), D)], np.ones(D, bool), 1.0, None
        else:
            usable = [p for p in paths if step(freq, p["base"], h) <= L]
            rec = [p["path"][:h + 1] for p in usable if p["group"] == "recession"]
            scr = [p["path"][:h + 1] for p in usable if p["group"] == "scare"]
            share = len(rec) / (len(rec) + len(scr))
            w = probs[{3: "p3", 6: "p6", 12: "p12"}[hm]]
            is_det = rng.random(D) < w
            grp_rec = rng.random(D) < share
            j = rng.integers(1, h + 1, D)                       # the event starts j periods after the origin
            det_draw = np.empty(D)
            for i in range(D):
                pool = rec if grp_rec[i] else scr
                det_draw[i] = pool[rng.integers(0, len(pool))][h - j[i] + 1]
        change = np.where(is_det, det_draw, base_pred) + resid[rng.integers(0, len(resid), D)]
        q = np.quantile(apply(scale, y0, change), Q)
        out.append({"horizon": h, "horizon_months": hm, "target_period": f"{step(freq, L, h):%Y-%m-%d}",
                    "q10": q[0], "q25": q[1], "median": q[2], "q75": q[3], "q90": q[4],
                    "deterioration_weight": w, "recession_share": share,
                    "baseline_median": float(apply(scale, y0, base_pred))})
    return {"label": t["label"], "frequency": freq, "latest_period": f"{L:%Y-%m-%d}", "level": y0, "horizons": out}


def stress_paths(fz: dict, asof: pd.Timestamp) -> dict:
    """What-ifs: 'if a 2001-type or 2008-type downturn started now', from today's level (not forecasts)."""
    lags = {"ur": None, "ic": 5, "cc": 12}
    out = {}
    for name, scenarios in fz["stress"].items():
        freq = "M" if name == "ur" else "W"
        scale = "points" if name == "ur" else "log"
        L, y0, _ = target_level(name, asof, lags[name])
        out[name] = {"latest_period": f"{L:%Y-%m-%d}", "level": y0, "scenarios": {
            label: [{"period": f"{step(freq, L, k):%Y-%m-%d}", "level": float(apply(scale, y0, v))}
                    for k, v in enumerate(path) if v is not None]
            for label, path in scenarios.items()}}
    return out


# ===================================================================================================
# Nowcast and FOMC marker
# ===================================================================================================
def next_release_month(p_month: pd.Timestamp) -> tuple[pd.Timestamp, str | None]:
    """The month the next jobs report covers: the month before its scheduled release (release calendar), or the
    month after the latest published one if the calendar is missing."""
    cal_path = PROCESSED / "release_calendar.csv"
    if cal_path.exists():
        cal = pd.read_csv(cal_path, dtype=str).fillna("")
        row = cal[cal.release.str.startswith("Jobs report")]
        if len(row) and row.next_date.iloc[0]:
            rel = pd.Timestamp(row.next_date.iloc[0])
            month = pd.Timestamp(f"{rel:%Y-%m}-01") - pd.DateOffset(months=1)
            if month > p_month:
                return month, f"{rel:%Y-%m-%d}"
    return p_month + pd.DateOffset(months=1), None


def nowcast(fz: dict, asof: pd.Timestamp) -> dict:
    nc = fz["nowcast"]
    ur = as_known_on("UNRATE", asof).dropna()
    p_month, p_val = ur.index[-1], float(ur.iloc[-1])
    month, release = next_release_month(p_month)
    months_since = (month.year - p_month.year) * 12 + month.month - p_month.month
    sat_m, sat_p = reference_saturday(month), reference_saturday(p_month)
    w = pd.read_csv(MODEL / "claims_weekly.csv", parse_dates=["week_ended"]).set_index("week_ended")
    have_ic = sat_m in w.index and pd.notna(w.ICSA.get(sat_m)) and sat_m + pd.Timedelta(days=nc["initial_claims_lag_days"]) <= asof
    have_cc = sat_m in w.index and pd.notna(w.CCSA.get(sat_m)) and sat_m + pd.Timedelta(days=nc["continuing_claims_lag_days"]) <= asof
    out = {"month": f"{month:%Y-%m-%d}", "release_date": release, "prior_month": f"{p_month:%Y-%m-%d}",
           "prior_value": p_val, "months_since": months_since, "reference_week": f"{sat_m:%Y-%m-%d}",
           "available_after": f"{sat_m + pd.Timedelta(days=nc['continuing_claims_lag_days']):%Y-%m-%d}",
           "range_pt": fz["display"]["nowcast_range_pt"]}
    if months_since > 1:
        skipped = [p_month + pd.DateOffset(months=k) for k in range(1, months_since)]
        out["bridges"] = [f"{m:%Y-%m-%d}" for m in skipped]
    if have_ic and have_cc:
        xv = {"months_since": months_since, "d_log_initial": np.log(w.ICSA[sat_m] / w.ICSA[sat_p]),
              "d_log_continuing": np.log(w.CCSA[sat_m] / w.CCSA[sat_p])}
        out["value"] = p_val + sum(c * xv[k] for k, c in zip(nc["columns"], nc["weights"]))
        out["status"] = "ready"
    else:
        out["status"] = "waiting for reference-week claims"
    return out


def fomc(asof: pd.Timestamp, ur_fan: dict) -> dict | None:
    """Latest FOMC SEP median for this year's Q4 average (FRED UNRATEMD), and our own Q4 median for comparison
    (published months as they are, later months from the fan medians, joined in straight lines)."""
    path = PROCESSED / "UNRATEMD.csv"
    if not path.exists():
        return None
    s = pd.read_csv(path, parse_dates=["date"]).set_index("date")["value"].dropna()
    year = asof.year
    if pd.Timestamp(f"{year}-01-01") not in s.index:
        return None
    meta = pd.read_csv(PROCESSED / "_metadata.csv").set_index("series_id")
    released = pd.Timestamp(meta.loc["UNRATEMD", "last_updated"][:10]) if "UNRATEMD" in meta.index else None
    L = pd.Timestamp(ur_fan["latest_period"])
    ks = [0] + [h["horizon"] for h in ur_fan["horizons"]]
    meds = [ur_fan["level"]] + [h["median"] for h in ur_fan["horizons"]]
    ur = as_known_on("UNRATE", asof).dropna()
    q4 = []
    for mth in (10, 11, 12):
        m = pd.Timestamp(f"{year}-{mth:02d}-01")
        k = (m.year - L.year) * 12 + m.month - L.month
        q4.append(float(ur[m]) if k <= 0 and m in ur.index else float(np.interp(k, ks, meds)))
    return {"year": year, "value": float(s[pd.Timestamp(f"{year}-01-01")]), "series": "UNRATEMD",
            "released": f"{released:%Y-%m-%d}" if released is not None else None,
            "our_q4_median": float(np.mean(q4)), "marker_date": f"{year}-11-15"}


# ===================================================================================================
# Archive (stage 3e-3): one permanent file per live run, never overwritten
# ===================================================================================================
def archive_name(asof: pd.Timestamp, inputs: dict) -> str:
    """data/archive/YYYY/YYYY-MM-DD_ic<claims week>_ur<YYYY-MM>.json: run date plus the inputs it used."""
    return f"{asof:%Y}/{asof:%Y-%m-%d}_ic{inputs['initial_claims_week']}_ur{inputs['unemployment_month'][:7]}.json"


def write_archive(archive_dir: Path, name: str, payload: dict) -> Path:
    """Write a NEW archive file. Opened in create-only mode ("x"): if the file already exists this raises
    FileExistsError, so the run fails instead of overwriting a past result (tests/test_live_archive.py)."""
    path = archive_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, allow_nan=False, default=float)
    return path


def latest_archived_inputs(archive_dir: Path) -> tuple[str | None, str | None, str | None]:
    """(file name, claims week, unemployment month) of the newest archived run, or Nones if there is none."""
    files = sorted(archive_dir.glob("*/*.json"))
    if not files:
        return None, None, None
    i = json.loads(files[-1].read_text(encoding="utf-8"))["inputs"]
    return files[-1].name, i["initial_claims_week"], i["unemployment_month"]


def current_inputs(asof: pd.Timestamp) -> dict:
    """The newest initial-claims week and unemployment-rate month published by the run date."""
    ic4 = as_known_on("IC4WSA", asof).dropna()
    cc = as_known_on("CCSA", asof).dropna()
    ur = as_known_on("UNRATE", asof).dropna()
    return {"initial_claims_week": f"{ic4.index[-1]:%Y-%m-%d}", "continuing_claims_week": f"{cc.index[-1]:%Y-%m-%d}",
            "unemployment_month": f"{ur.index[-1]:%Y-%m-%d}", "unemployment_rate": float(ur.iloc[-1])}


def has_new_inputs(now: dict, archived: tuple) -> bool:
    """A live run is made only when there is a new claims week or a new unemployment month since the last archived
    run (design brief, step 1): in practice once each Thursday and once after each jobs report."""
    _, week, month = archived
    return week is None or now["initial_claims_week"] > week or now["unemployment_month"] > month


def write_status(status: dict) -> None:
    """data/model/live_status.json: the last attempt, so the site can say 'model run failed' straight away."""
    STATUS.write_text(json.dumps(status, indent=1), encoding="utf-8")


# ===================================================================================================
# Alerts (built, off unless ALERTS_ENABLED=true): colour change under the hysteresis rule
# ===================================================================================================
SITE_URL = "https://eisenhourlabs.github.io/unemployment-early-warning"


def colour_alert(result: dict) -> tuple[str, str] | None:
    """(subject, body) when the displayed colour differs from the previous week's, else None (design brief text)."""
    s = result["score"]
    new, old = s["colour"], s["previous"]["colour"]
    if new == old:
        return None
    t = s["thresholds"]
    rule = {"green": f"It stays green until it reaches {t['amber_in']:.0%} (amber).",
            "amber": f"It entered amber at {t['amber_in']:.0%}; it stays amber until it falls below {t['amber_out']:.0%} "
                     f"or rises to {t['red_in']:.0%} (red).",
            "red": f"It entered red at {t['red_in']:.0%}; it stays red until it falls below {t['red_out']:.0%}."}[new]
    week = pd.Timestamp(result["inputs"]["initial_claims_week"])
    drivers_txt = "; ".join(d["text"][0].lower() + d["text"][1:].replace(" the score", "") for d in s["drivers"])
    body = (f"The 6-month early-warning score is {s['display']['6']['number']} "
            f"(last week {s['previous']['display']['number']}), as of claims for the week ending "
            f"{week.day} {week:%b %Y}.\n{rule}\nMain drivers: {drivers_txt}.\nDetails: {SITE_URL}/outlook.html")
    return f"Unemployment Watch: early-warning colour changed to {new.upper()}", body


# ===================================================================================================
def run(asof: pd.Timestamp, archive: bool) -> dict | None:
    fz = load_frozen(asof)
    print(f"Live run as of {asof:%Y-%m-%d} with the {fz['model_year']} frozen model"
          + (" (archive mode)" if archive else " (preview: no archive, run record unchanged)"))
    disp = fz["display"]
    now = current_inputs(asof)
    if archive:
        last = latest_archived_inputs(ARCHIVE)
        if not has_new_inputs(now, last):
            print(f"  No new claims week or unemployment month since the archived run {last[0]} "
                  f"(claims week {now['initial_claims_week']}, unemployment {now['unemployment_month'][:7]}): "
                  "nothing to do; the site keeps the last run.")
            write_status({"last_attempt": f"{asof:%Y-%m-%d}", "ok": True, "result": "skipped: no new inputs",
                          "last_run": last[0]})
            return None

    # ---- score ----
    x = features_at(asof)
    raw = {h: probability(fz, x, h) for h in (3, 6, 12)}
    p6 = raw[6][0]
    probs = {"p3_raw": raw[3][0], "p12_raw": raw[12][0], "p6": p6,
             "p3": min(raw[3][0], p6), "p12": max(raw[12][0], p6)}        # coherent: 3 <= 6 <= 12
    runs = (pd.read_csv(RUNS, parse_dates=["asof"]).set_index("asof") if RUNS.exists()
            else pd.DataFrame(columns=["p3", "p6", "p12", "colour"], index=pd.DatetimeIndex([], name="asof")))
    weekly = weekly_history(fz, asof, p6, runs)
    weekly.to_csv(WEEKLY_OUT, date_format="%Y-%m-%d")
    monthly = monthly_history(fz)
    monthly.to_csv(MONTHLY_OUT, date_format="%Y-%m-%d")
    prev = weekly.iloc[-2]
    colour = weekly.colour.iloc[-1]
    # What "change" compares with (3e-1 review): a live run is compared only with an earlier live run. Until there is
    # one, the comparison is with last week's backtest score and says so.
    if prev.basis == "live":
        days = (asof - prev.name).days
        compare = "vs. last week" if 5 <= days <= 9 else f"vs. the run of {prev.name:%b} {prev.name.day}"
    else:
        compare = "vs. last week's backtest score"
    for c in raw[6][1]:
        c["sentence"] = (None if c["value"] is None or abs(c["contribution"]) < 1e-9 else   # zero weight: no direction
                         driver_sentence(c["input"], c["value"], c["contribution"] > 0, c.get("mean")))

    inputs = {**now, "values": {k: (None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v))
                                for k, v in x.items() if k in fz["score"]["features"]}}
    rng = np.random.default_rng(SEED)
    fans = {name: fan(fz, name, x, probs, asof, rng) for name in fz["forecast"]["targets"]}
    result = {
        "asof": f"{asof:%Y-%m-%d}",
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "model_year": fz["model_year"],
        "inputs": inputs,
        "score": {
            **probs, "colour": colour,
            "display": {h: score_display(probs[k], disp) for h, k in (("3", "p3"), ("6", "p6"), ("12", "p12"))},
            "base_rates": fz["base_rates"],
            "previous": {"date": f"{prev.name:%Y-%m-%d}", "p6": float(prev.score), "colour": prev.colour,
                         "basis": prev.basis, "display": score_display(float(prev.score), disp)},
            "first_live_run": prev.basis != "live", "compare_label": compare,
            "live_runs": int((weekly.basis == "live").sum()),
            "change_pt": (p6 - float(prev.score)) * 100,
            "thresholds": fz["colour"],
            "drivers": drivers(raw[6][1]),
            "contributions": raw[6][1],
            "intercept": fz["score"]["horizons"]["6"]["intercept"],
        },
        "triggers": triggers_now(asof),
        "fans": fans,
        "stress": stress_paths(fz, asof),
        "nowcast": nowcast(fz, asof),
        "fomc": fomc(asof, fans["ur"]),
    }
    if archive:
        # Archive FIRST: if this run's file already exists, stop here before touching anything else.
        path = write_archive(ARCHIVE, archive_name(asof, inputs), result)
        print(f"  archived {path.relative_to(ROOT)}")
    OUT.write_text(json.dumps(result, indent=1, allow_nan=False, default=float), encoding="utf-8")

    # ---- the run record (archive mode only; re-running the same date replaces its rows) ----
    if archive:
        n = result["nowcast"]
        runs.loc[asof, ["p3", "p6", "p12", "colour", "model_year", "initial_claims_week", "unemployment_month",
                        "nowcast_month", "nowcast", "run_at"]] = [
            probs["p3"], probs["p6"], probs["p12"], colour, fz["model_year"], inputs["initial_claims_week"],
            inputs["unemployment_month"], n["month"], n.get("value"), result["run_at"]]
        runs.sort_index().to_csv(RUNS, date_format="%Y-%m-%d", index_label="asof")
        rows = [{"asof": result["asof"], "target": name, "label": f["label"], "latest_period": f["latest_period"],
                 "level_at_origin": f["level"], **{k: h[k] for k in ("horizon", "horizon_months", "target_period", "q10",
                                                                     "q25", "median", "q75", "q90",
                                                                     "deterioration_weight")}}
                for name, f in fans.items() for h in f["horizons"]]
        hist = pd.read_csv(FANS_HISTORY) if FANS_HISTORY.exists() else pd.DataFrame(columns=list(rows[0]))
        hist = pd.concat([hist[hist["asof"] != result["asof"]], pd.DataFrame(rows)])   # hist["asof"]: .asof is a method
        hist.sort_values(["asof", "target", "horizon"]).to_csv(FANS_HISTORY, index=False)
        write_status({"last_attempt": f"{asof:%Y-%m-%d}", "ok": True, "result": "new live run",
                      "last_run": path.name})
        alert = colour_alert(result)
        if alert:
            sys.path.insert(0, str(ROOT / "src" / "alerts"))
            from alerts import send_alert      # prints the message instead of sending while ALERTS_ENABLED is off
            send_alert(*alert)
        else:
            print(f"  colour unchanged ({colour}): no alert")

    # ---- print a summary ----
    s = result["score"]
    print(f"  inputs: initial claims week {inputs['initial_claims_week']}, continuing {inputs['continuing_claims_week']}, "
          f"unemployment {inputs['unemployment_month'][:7]} = {inputs['unemployment_rate']}%")
    print(f"  score: 3m {s['p3']:.2%}  6m {s['p6']:.2%}  12m {s['p12']:.2%}  colour {colour}  "
          f"({s['change_pt']:+.1f} pt {s['compare_label']}: {s['previous']['p6']:.2%} on {s['previous']['date']}; "
          f"live run number {s['live_runs']})")
    for d in s["drivers"]:
        print(f"    {d['text']}")
    t = result["triggers"]
    print(f"  Layer 1 overall {t['overall']}: " + ", ".join(f"{r['id']} {r['colour']}" for r in t["rows"]))
    for name, f in fans.items():
        print(f"  fan {name} from {f['level']:.3f} ({f['latest_period']}): " + "; ".join(
            f"{h['horizon']}: {h['median']:.2f} ({h['q10']:.2f}-{h['q90']:.2f})" for h in f["horizons"]))
    n = result["nowcast"]
    print(f"  nowcast {n['month'][:7]}: " + (f"{n['value']:.2f}" if "value" in n else f"{n['status']} (after {n['available_after']})"))
    if result["fomc"]:
        print(f"  FOMC Q4 {result['fomc']['year']}: {result['fomc']['value']} ({result['fomc']['released']}); "
              f"ours {result['fomc']['our_q4_median']:.2f}")
    print(f"Wrote {OUT.relative_to(ROOT)}, {WEEKLY_OUT.relative_to(ROOT)}, {MONTHLY_OUT.relative_to(ROOT)}"
          + (f", {RUNS.relative_to(ROOT)}, {FANS_HISTORY.relative_to(ROOT)}" if archive else ""))
    return result


def main() -> None:
    """python src/model/live.py [YYYY-MM-DD] [--archive]
    --archive (the workflow): only if there is a new claims week or unemployment month; writes the permanent archive
    file (create-only), the run record and the status, and prints a colour-change alert. Without it: a preview that
    refreshes the site's files but leaves the archive and run record alone."""
    if "--record-failure" in sys.argv:
        # The workflow could not refresh the model's inputs: don't run on stale data, just record the failure so
        # the site says "model run failed" and keeps the last good values.
        reason = sys.argv[sys.argv.index("--record-failure") + 1] if len(sys.argv) > sys.argv.index("--record-failure") + 1 else ""
        write_status({"last_attempt": f"{pd.Timestamp.today():%Y-%m-%d}", "ok": False, "result": f"failed: {reason}"})
        print(f"Recorded a failed model step ({reason}); the site keeps the last good run.")
        return
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    archive = "--archive" in sys.argv
    asof = pd.Timestamp(args[0]) if args else pd.Timestamp.today().normalize()
    try:
        run(asof, archive)
    except Exception as e:
        if archive:
            write_status({"last_attempt": f"{asof:%Y-%m-%d}", "ok": False,
                          "result": f"failed: {type(e).__name__}: {str(e)[:200]}"})
        raise


if __name__ == "__main__":
    main()
