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
  claims                  NSA regular state UI only (excludes work-sharing equivalents; decision at the 4a gate)
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
    # Claims = regular state UI only (Troy's decision at the 4a gate, 2026-11-08). DOL's weekly state report, FRED's
    # {ST}ICLAIMS / {ST}CCLAIMS and the national totals also add work-sharing (short-time compensation) equivalents,
    # so our state figures run slightly below those (by the ar539 work-share columns).
    ic = ar539[["state", "week_ended", "covered_employment"]].copy()
    ic["initial_claims"] = ar539.ic_state_ui
    # Continued weeks claimed are dated by the week of unemployment they reflect.
    cc = ar539[["state", "reflected_week_ended", "covered_employment"]].rename(
        columns={"reflected_week_ended": "week_ended", "covered_employment": "ce_cc"})
    cc["continued_weeks"] = ar539.cw_state_ui
    df = ic.merge(cc, on=["state", "week_ended"], how="outer")
    df["week_ended"] = pd.to_datetime(df.week_ended)
    df["covered_employment"] = df.covered_employment.fillna(df.ce_cc)
    df = df.sort_values(["state", "week_ended"]).reset_index(drop=True)

    df["ic_rate"] = df.initial_claims / df.covered_employment * 100
    df["cc_rate"] = df.continued_weeks / df.ce_cc * 100
    df["initial_claims_4wk"] = rolling_4wk(df, "initial_claims")
    df["ic_rate_4wk"] = rolling_4wk(df, "ic_rate")
    df["cc_rate_4wk"] = rolling_4wk(df, "cc_rate")

    # Phase 4 review (Gate 2): every "vs. a year ago" figure is on one basis: the claims RATE (claims per covered job),
    # 4-week average, regular state UI. For a state this differs from the count basis only by the change in covered jobs.
    past_ic = year_earlier(df, "ic_rate_4wk")
    with np.errstate(divide="ignore", invalid="ignore"):
        df["ic_yoy_pct"] = np.where(past_ic > 0, (df.ic_rate_4wk / past_ic - 1) * 100, np.nan)
    df["cc_rate_yoy_pp"] = df.cc_rate_4wk - year_earlier(df, "cc_rate_4wk")
    df["ic_vs_normal_pct"] = vs_normal(df)

    cols = ["state", "week_ended", "initial_claims", "initial_claims_4wk", "covered_employment", "ic_rate",
            "ic_rate_4wk", "ic_yoy_pct", "ic_vs_normal_pct", "continued_weeks", "cc_rate", "cc_rate_4wk",
            "cc_rate_yoy_pp"]
    return df[cols]


NORMAL_YEARS = 3                                              # "normal" = the same weeks of the prior 3 years
PANDEMIC = (pd.Timestamp("2020-03-01"), pd.Timestamp("2021-06-30"))   # excluded from "normal"


def vs_normal(df: pd.DataFrame) -> pd.Series:
    """Phase 4 review, Gate 3 (1): the 4-week average claims rate vs. 'normal' = the median of the same weeks (52, 104
    and 156 weeks earlier) over the prior 3 years, leaving out weeks from Mar 2020 to Jun 2021. In % (+20 = 20% above
    normal). Blank when none of the 3 earlier years is usable."""
    past = []
    for k in range(1, NORMAL_YEARS + 1):
        p = df[["state", "week_ended", "ic_rate_4wk"]].copy()
        bad = p.week_ended.between(*PANDEMIC)
        p.loc[bad, "ic_rate_4wk"] = np.nan
        p["week_ended"] = p.week_ended + pd.Timedelta(weeks=LAG_WEEKS * k)
        past.append(df[["state", "week_ended"]].merge(p, on=["state", "week_ended"], how="left")["ic_rate_4wk"])
    normal = pd.concat(past, axis=1).median(axis=1, skipna=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        return pd.Series(np.where(normal > 0, (df.ic_rate_4wk / normal - 1) * 100, np.nan), index=df.index)


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


def national_weekly(weekly: pd.DataFrame) -> pd.DataFrame:
    """National NSA claims rates (4-week averages) and year-on-year changes, built from the STATE SUMS (50 states + DC,
    regular state UI; Phase 4 review, Gate 2), so National, Weighted and each state are on the same basis. (DOL's
    national table also counts work-sharing and Puerto Rico / Virgin Islands, so it runs slightly higher.)"""
    d = weekly[weekly.state.isin(measure_areas())]
    g = d.groupby("week_ended")
    ic = d.dropna(subset=["initial_claims", "covered_employment"]).groupby("week_ended")
    cc = d.dropna(subset=["continued_weeks", "covered_employment"]).groupby("week_ended")
    n = pd.DataFrame(index=sorted(d.week_ended.unique()))
    n["ic_rate"] = ic.initial_claims.sum() / ic.covered_employment.sum() * 100
    n["cc_rate"] = cc.continued_weeks.sum() / cc.covered_employment.sum() * 100
    for col in ("ic_rate", "cc_rate"):
        n[col + "_4wk"] = n[col].rolling("28D", min_periods=4).mean()
    lag = n.shift(freq=pd.Timedelta(weeks=LAG_WEEKS)).reindex(n.index)
    return pd.DataFrame({
        "national_ic_rate_4wk": n.ic_rate_4wk,
        "national_ic_yoy_pct": (n.ic_rate_4wk / lag.ic_rate_4wk - 1) * 100,
        "national_cc_rate_4wk": n.cc_rate_4wk,
        "national_cc_rate_yoy_pp": n.cc_rate_4wk - lag.cc_rate_4wk,
    })


def weighted_weekly(weekly: pd.DataFrame, diff: pd.DataFrame, w: pd.Series) -> pd.DataFrame:
    d = weekly[weekly.state.isin(measure_areas())]
    out = pd.DataFrame(index=sorted(d.week_ended.unique()))
    out.index.name = "week_ended"
    for col in ["ic_rate_4wk", "cc_rate_4wk"]:
        out[f"weighted_{col}"], out[f"weights_present_{col[:2]}"] = weighted_mean(
            d.pivot(index="week_ended", columns="state", values=col), w)
    lag = out.shift(freq=pd.Timedelta(weeks=LAG_WEEKS)).reindex(out.index)
    # Weighted % change = the sum of the state contributions (Gate 3 item 3), over the states with a rate in both weeks
    out["weighted_ic_yoy_pct"] = contributions(weekly, w).groupby("week_ended").contribution_pct.sum(min_count=1)
    out["weighted_cc_rate_yoy_pp"] = out.weighted_cc_rate_4wk - lag.weighted_cc_rate_4wk
    out["weighted_diffusion_pct"] = diff.set_index("week_ended").diffusion_weighted_pct
    out = out.join(national_weekly(weekly), how="left")
    out = out.dropna(subset=["weighted_ic_rate_4wk", "weighted_cc_rate_4wk"], how="all")
    return out.reset_index()


def contributions(weekly: pd.DataFrame, w: pd.Series) -> pd.DataFrame:
    """Each weighted state's contribution to the weighted year-on-year % change in the 4-week claims rate:
        c_s,t = w_s (r_s,t - r_s,t-52) / sum_j w_j r_j,t-52 x 100      (states with r in both weeks)
    so the contributions add up exactly to the weighted % change. One row per weighted state and week."""
    d = weekly[weekly.state.isin(w[w > 0].index)]
    r = d.pivot(index="week_ended", columns="state", values="ic_rate_4wk")
    r0 = r.shift(freq=pd.Timedelta(weeks=LAG_WEEKS)).reindex(r.index)
    both = r.notna() & r0.notna()
    ww = w.reindex(r.columns).fillna(0.0)
    base = r0.where(both).mul(ww, axis=1).sum(axis=1)
    c = (r - r0).where(both).mul(ww, axis=1).div(base.replace(0, np.nan), axis=0) * 100
    out = c.stack().rename("contribution_pct").reset_index()
    return out[["state", "week_ended", "contribution_pct"]]


# ---------------------------------------------------------------------------
# Monthly state measures
# ---------------------------------------------------------------------------
def gap_to_12m_low(s: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """State Sahm convention (Phase 4 review, Gate 2), the same formula as the national trigger (realtime.sahm):
    3-month average of the rate (2 of 3 months allowed, e.g. Oct 2025 missing), its lowest value over the PREVIOUS 12
    months (at least 11 present), and the gap between them. s is indexed by a full monthly PeriodIndex.
    Returns (3-month average, previous-12-month low of it, gap)."""
    avg3 = s.rolling(3, min_periods=2).mean()
    low = avg3.shift(1).rolling(12, min_periods=11).min()
    return avg3, low, avg3 - low


def read_fred(sid: str) -> pd.Series:
    f = pd.read_csv(PROCESSED / f"{sid}.csv")
    return pd.Series(f.value.values, index=pd.PeriodIndex(f.date.str[:7], freq="M"), name=sid)


def monthly_measures() -> pd.DataFrame:
    frames = []
    for st in measure_areas():
        ur = read_fred(f"{st}UR")
        ur = ur.reindex(pd.period_range(ur.index.min(), ur.index.max(), freq="M"))
        avg3, low, gap = gap_to_12m_low(ur)
        frames.append(pd.DataFrame({"state": st, "month": ur.index, "unemployment_rate": ur.values,
                                    "ur_3m_avg": avg3.values, "ur_3m_avg_12m_low": low.values,
                                    "ur_gap_pp": gap.values}))
    ur = pd.concat(frames)

    ex = pd.read_csv(DOL / "exhaustion_duration_monthly.csv")
    ex = ex[ex.state.isin(areas().state)]
    ex["month"] = pd.PeriodIndex(ex.month_ended.str[:7], freq="M")
    ex = ex[["state", "month", "exhaustion_rate_12m", "avg_duration_12m"]]

    ex = ex.sort_values(["state", "month"])
    prev = ex[["state", "month", "exhaustion_rate_12m"]].copy()
    prev["month"] = prev.month + 12
    ex = ex.merge(prev.rename(columns={"exhaustion_rate_12m": "exh_prev"}), on=["state", "month"], how="left")
    ex["exhaustion_change_12m_pp"] = ex.exhaustion_rate_12m - ex.pop("exh_prev")
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
    (out["weighted_ur_3m_avg"], out["weighted_ur_3m_avg_12m_low"],
     out["weighted_ur_gap_pp"]) = gap_to_12m_low(out.weighted_ur)
    nat = read_fred("UNRATE")
    nat = nat.reindex(pd.period_range(nat.index.min(), nat.index.max(), freq="M"))
    nat_avg, nat_low, nat_gap = gap_to_12m_low(nat)
    out["national_ur"] = nat.reindex(out.index)
    out["national_ur_3m_avg"] = nat_avg.reindex(out.index)
    out["national_ur_3m_avg_12m_low"] = nat_low.reindex(out.index)
    out["national_ur_gap_pp"] = nat_gap.reindex(out.index)
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
    save(contributions(weekly, w), "weighted_contributions_weekly", "week_ended")
    save(weighted_monthly(monthly, w), "weighted_monthly", "month")


if __name__ == "__main__":
    main()
