"""
State measures for the States page and the stage 4e model tests (Phase 4 brief, "Data definitions").

Inputs (all already on file after the DOL and FRED steps):
  data/processed/dol/ar539.csv                      state weekly claims and covered employment (DOL, 53 areas, 1995-)
  data/processed/dol/exhaustion_duration_monthly.csv  12-month exhaustion rate and average duration by state
  data/processed/{ST}UR.csv                          state unemployment rates (BLS LAUS via FRED, SA), UNRATE (national)
  data/processed/dol/claims_rates_weekly.csv         national NSA claims rates (the comparison line)
  config/states.csv                                  the 53 areas (50 states + DC are "measure areas"; PR, VI tables only)
  config/state_weights.csv                           the committed weights (decision O2)

Definitions (s = area, t = week ending Saturday; every rate is per 100 covered jobs):
  claims                  NSA regular state UI plus work-sharing equivalents, as DOL publishes state claims
  initial claims rate     IC_s,t / CE_s,t, shown as its 4-week average
  frequency change        4-week average IC_s,t / 4-week average IC_s,t-52 - 1, in % (year-on-year on unadjusted
                          data: states' seasonal patterns differ and DOL publishes no state seasonal factors)
  continuing claims rate  continued weeks claimed / CE, 4-week average, and its change vs. 52 weeks earlier in points.
                          Dated by the week of unemployment (ar539 "reflected week"), as FRED and the national table do
  diffusion index         share of the 50 states + DC whose frequency change is >= +20%, three ways: unweighted,
                          covered-employment weighted (the headline; model candidate C1) and weighted by the weights.
                          The 20% threshold is fixed in the brief, before any testing
  weighted aggregates     sum of w_s x_s (weights sum to 1) for the initial claims rate, continuing claims rate and
                          unemployment rate, next to the national figure on the same basis
  unemployment rate gap   state UR minus its lowest value over the last 12 months (this month included), in points
                          (a "Sahm-style" gap; no trigger is attached)
When an area has no value for a period, shares and weighted sums use the areas that do (the weights or
covered jobs are re-scaled to sum to 1); the "areas" / "weights_present" columns show how many were in.

Outputs (data/processed/states/):
  state_weekly.csv     one row per area and week          (download, stage 4b)
  state_monthly.csv    one row per area and month         (download, stage 4b)
  diffusion_weekly.csv unweighted and CE-weighted index   (download, stage 4b)
  weighted_weekly.csv, weighted_monthly.csv   weighted figures vs. national (charted only, never a download)

Run:  python src/transforms/state_measures.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
DOL = PROCESSED / "dol"
OUT = PROCESSED / "states"
DIFFUSION_THRESHOLD = 20.0      # % year-on-year rise in 4-week average initial claims (fixed in the brief)
LAG_WEEKS = 52                  # "the same weeks a year earlier"
COUNT_COLUMNS = {"initial_claims", "covered_employment", "continued_weeks", "areas_reported", "areas_up"}


# ---------------------------------------------------------------------------
# Reference lists
# ---------------------------------------------------------------------------
def areas() -> pd.DataFrame:
    return pd.read_csv(ROOT / "config" / "states.csv", comment="#", dtype=str)


def measure_areas() -> list[str]:
    """The 50 states and DC (territories appear in the tables only)."""
    a = areas()
    return a.state[a.area_type.isin(["state", "dc"])].tolist()


def weights() -> pd.Series:
    """Committed weights, indexed by state; 0 for states not listed."""
    w = pd.read_csv(ROOT / "config" / "state_weights.csv", comment="#").set_index("state").weight
    return w.reindex(measure_areas()).fillna(0.0)


# ---------------------------------------------------------------------------
# Weekly state measures
# ---------------------------------------------------------------------------
def rolling_4wk(df: pd.DataFrame, col: str) -> pd.Series:
    """4-week average per area; needs all 4 weeks (a 28-day window by date, so a missing week leaves a gap)."""
    out = (df.set_index("week_ended").groupby("state")[col]
           .rolling("28D", min_periods=4).mean().reset_index())
    return df[["state", "week_ended"]].merge(out, on=["state", "week_ended"], how="left")[col]


def year_earlier(df: pd.DataFrame, col: str) -> pd.Series:
    """The value of `col` for the same area 52 weeks earlier (blank if that week is missing)."""
    past = df[["state", "week_ended", col]].copy()
    past["week_ended"] = past.week_ended + pd.Timedelta(weeks=LAG_WEEKS)
    return df[["state", "week_ended"]].merge(past, on=["state", "week_ended"], how="left")[col]


def weekly_measures(ar539: pd.DataFrame) -> pd.DataFrame:
    """One row per area and week: claims, rates, 4-week averages and year-on-year changes."""
    # Claims = regular state UI + work-sharing (short-time compensation) equivalents. That is how DOL publishes
    # state claims (its weekly state report and FRED's {ST}ICLAIMS / {ST}CCLAIMS), and the national ETA 539 totals
    # are the sum of the states on this basis (decision 2026-11-08, stage 4a).
    ic = ar539[["state", "week_ended", "covered_employment"]].copy()
    ic["initial_claims"] = ar539.ic_state_ui + ar539.ic_stc_workshare_equiv
    # Continued weeks claimed are dated by the week of unemployment they reflect.
    cc = ar539[["state", "reflected_week_ended", "covered_employment"]].rename(
        columns={"reflected_week_ended": "week_ended", "covered_employment": "ce_cc"})
    cc["continued_weeks"] = ar539.cw_state_ui + ar539.cw_stc_workshare_equiv
    df = ic.merge(cc, on=["state", "week_ended"], how="outer")
    df["week_ended"] = pd.to_datetime(df.week_ended)
    df["covered_employment"] = df.covered_employment.fillna(df.ce_cc)
    df = df.sort_values(["state", "week_ended"]).reset_index(drop=True)

    df["ic_rate"] = df.initial_claims / df.covered_employment * 100
    df["cc_rate"] = df.continued_weeks / df.ce_cc * 100
    df["initial_claims_4wk"] = rolling_4wk(df, "initial_claims")
    df["ic_rate_4wk"] = rolling_4wk(df, "ic_rate")
    df["cc_rate_4wk"] = rolling_4wk(df, "cc_rate")

    past_ic = year_earlier(df, "initial_claims_4wk")
    with np.errstate(divide="ignore", invalid="ignore"):
        df["ic_yoy_pct"] = np.where(past_ic > 0, (df.initial_claims_4wk / past_ic - 1) * 100, np.nan)
    df["cc_rate_yoy_pp"] = df.cc_rate_4wk - year_earlier(df, "cc_rate_4wk")

    cols = ["state", "week_ended", "initial_claims", "initial_claims_4wk", "covered_employment", "ic_rate",
            "ic_rate_4wk", "ic_yoy_pct", "continued_weeks", "cc_rate", "cc_rate_4wk", "cc_rate_yoy_pp"]
    return df[cols]


# ---------------------------------------------------------------------------
# Cross-state summaries
# ---------------------------------------------------------------------------
def weighted_mean(values: pd.DataFrame, w: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Row-wise sum of w_s x_s over areas with a value, re-scaled so the present weights sum to 1.

    values: one column per area. Returns (weighted mean, share of the total weight present).
    """
    w = w.reindex(values.columns).fillna(0.0)
    present = values.notna().mul(w, axis=1).sum(axis=1)
    total = values.fillna(0.0).mul(w, axis=1).sum(axis=1)
    return (total / present.replace(0, np.nan)), present / w.sum()


def diffusion(weekly: pd.DataFrame, w: pd.Series, threshold: float = DIFFUSION_THRESHOLD) -> pd.DataFrame:
    """Weekly share of areas (50 states + DC) with initial claims up `threshold`% or more vs. a year earlier."""
    d = weekly[weekly.state.isin(measure_areas())]
    yoy = d.pivot(index="week_ended", columns="state", values="ic_yoy_pct")
    ce = d.pivot(index="week_ended", columns="state", values="covered_employment").where(yoy.notna())
    up = (yoy >= threshold).astype(float).where(yoy.notna())

    out = pd.DataFrame(index=yoy.index)
    out["areas_reported"] = yoy.notna().sum(axis=1)
    out["areas_up"] = (up == 1).sum(axis=1)
    out["diffusion_unweighted_pct"] = out.areas_up / out.areas_reported.replace(0, np.nan) * 100
    out["diffusion_ce_weighted_pct"] = (up * ce).sum(axis=1) / ce.sum(axis=1).replace(0, np.nan) * 100
    wd, wp = weighted_mean(up, w)
    out["diffusion_weighted_pct"] = wd * 100
    out["weights_present"] = wp
    out = out[out.areas_reported > 0]
    return out.reset_index()


def national_weekly() -> pd.DataFrame:
    """National NSA claims rates (4-week averages) and their year-on-year changes, from the national table."""
    n = pd.read_csv(DOL / "claims_rates_weekly.csv", parse_dates=["week_ended"])
    n = n[["week_ended", "ic_rate_nsa_4wk", "cc_rate_nsa_4wk"]].set_index("week_ended")
    lag = n.shift(freq=pd.Timedelta(weeks=LAG_WEEKS)).reindex(n.index)
    return pd.DataFrame({
        "national_ic_rate_4wk": n.ic_rate_nsa_4wk,
        "national_ic_yoy_pct": (n.ic_rate_nsa_4wk / lag.ic_rate_nsa_4wk - 1) * 100,
        "national_cc_rate_4wk": n.cc_rate_nsa_4wk,
        "national_cc_rate_yoy_pp": n.cc_rate_nsa_4wk - lag.cc_rate_nsa_4wk,
    })


def weighted_weekly(weekly: pd.DataFrame, diff: pd.DataFrame, w: pd.Series) -> pd.DataFrame:
    d = weekly[weekly.state.isin(measure_areas())]
    out = pd.DataFrame(index=sorted(d.week_ended.unique()))
    out.index.name = "week_ended"
    for col in ["ic_rate_4wk", "cc_rate_4wk"]:
        out[f"weighted_{col}"], out[f"weights_present_{col[:2]}"] = weighted_mean(
            d.pivot(index="week_ended", columns="state", values=col), w)
    lag = out.shift(freq=pd.Timedelta(weeks=LAG_WEEKS)).reindex(out.index)
    out["weighted_ic_yoy_pct"] = (out.weighted_ic_rate_4wk / lag.weighted_ic_rate_4wk - 1) * 100
    out["weighted_cc_rate_yoy_pp"] = out.weighted_cc_rate_4wk - lag.weighted_cc_rate_4wk
    out["weighted_diffusion_pct"] = diff.set_index("week_ended").diffusion_weighted_pct
    out = out.join(national_weekly(), how="left")
    out = out.dropna(subset=["weighted_ic_rate_4wk", "weighted_cc_rate_4wk"], how="all")
    return out.reset_index()


# ---------------------------------------------------------------------------
# Monthly state measures
# ---------------------------------------------------------------------------
def gap_to_12m_low(s: pd.Series) -> tuple[pd.Series, pd.Series]:
    """(12-month low including this month, value minus that low). s is indexed by a full monthly PeriodIndex;
    a missing month (e.g. Oct 2025, shutdown) is skipped, and at least 11 of the 12 months must be present."""
    low = s.rolling(12, min_periods=11).min()
    return low, s - low


def read_fred(sid: str) -> pd.Series:
    f = pd.read_csv(PROCESSED / f"{sid}.csv")
    return pd.Series(f.value.values, index=pd.PeriodIndex(f.date.str[:7], freq="M"), name=sid)


def monthly_measures() -> pd.DataFrame:
    frames = []
    for st in measure_areas():
        ur = read_fred(f"{st}UR")
        ur = ur.reindex(pd.period_range(ur.index.min(), ur.index.max(), freq="M"))
        low, gap = gap_to_12m_low(ur)
        frames.append(pd.DataFrame({"state": st, "month": ur.index, "unemployment_rate": ur.values,
                                    "ur_12m_low": low.values, "ur_above_12m_low_pp": gap.values}))
    ur = pd.concat(frames)

    ex = pd.read_csv(DOL / "exhaustion_duration_monthly.csv")
    ex = ex[ex.state.isin(areas().state)]
    ex["month"] = pd.PeriodIndex(ex.month_ended.str[:7], freq="M")
    ex = ex[["state", "month", "exhaustion_rate_12m", "avg_duration_12m"]]

    out = ur.merge(ex, on=["state", "month"], how="outer").sort_values(["state", "month"])
    out["month"] = out.month.astype(str)
    return out.reset_index(drop=True)


def weighted_monthly(monthly: pd.DataFrame, w: pd.Series) -> pd.DataFrame:
    m = monthly[monthly.state.isin(measure_areas())].copy()
    m["month"] = pd.PeriodIndex(m.month, freq="M")
    piv = m.pivot(index="month", columns="state", values="unemployment_rate").dropna(how="all")
    piv = piv.reindex(pd.period_range(piv.index.min(), piv.index.max(), freq="M"))
    out = pd.DataFrame(index=piv.index)
    out["weighted_ur"], out["weights_present"] = weighted_mean(piv, w)
    out.loc[piv.isna().all(axis=1), ["weighted_ur", "weights_present"]] = np.nan   # e.g. Oct 2025: no data at all
    out["weighted_ur_12m_low"], out["weighted_ur_above_12m_low_pp"] = gap_to_12m_low(out.weighted_ur)
    nat = read_fred("UNRATE")
    nat = nat.reindex(pd.period_range(nat.index.min(), nat.index.max(), freq="M"))
    nat_low, nat_gap = gap_to_12m_low(nat)
    out["national_ur"] = nat.reindex(out.index)
    out["national_ur_12m_low"] = nat_low.reindex(out.index)
    out["national_ur_above_12m_low_pp"] = nat_gap.reindex(out.index)
    out.index = out.index.astype(str)
    out.index.name = "month"
    return out.reset_index()


# ---------------------------------------------------------------------------
def save(df: pd.DataFrame, name: str, date_col: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = df.copy()
    if pd.api.types.is_datetime64_any_dtype(df[date_col]):
        df[date_col] = df[date_col].dt.strftime("%Y-%m-%d")
    # Counts stay whole numbers (Int64 allows blanks); everything else is rounded to 6 decimals.
    for c in COUNT_COLUMNS & set(df.columns):
        df[c] = df[c].round().astype("Int64")
    num = [c for c in df.select_dtypes("number").columns if c not in COUNT_COLUMNS]
    df[num] = df[num].round(6)
    df.to_csv(OUT / f"{name}.csv", index=False)
    first, last = df[date_col].min(), df[date_col].max()
    print(f"  {name + '.csv':<22} {len(df):>7} rows  {first} to {last}")


def main():
    ar539 = pd.read_csv(DOL / "ar539.csv")
    w = weights()
    print("State measures (data/processed/states/):")
    weekly = weekly_measures(ar539)
    diff = diffusion(weekly, w)
    monthly = monthly_measures()
    save(weekly, "state_weekly", "week_ended")
    save(diff.drop(columns=["diffusion_weighted_pct", "weights_present"]), "diffusion_weekly", "week_ended")
    save(monthly, "state_monthly", "month")
    save(weighted_weekly(weekly, diff, w), "weighted_weekly", "week_ended")
    save(weighted_monthly(monthly, w), "weighted_monthly", "month")


if __name__ == "__main__":
    main()
