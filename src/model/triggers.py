"""
Layer 1 triggers (Phase 3 plan), computed for every month since 1967 with the data known at the time.

For each month, the "as of" date is the month's LAST DAY: each trigger uses only what had been published
by then (src/model/realtime.py, as_known_on). Thresholds come from config/triggers.csv.

Each trigger gets three columns in data/model/triggers_monthly.csv:
  <id>_value   the trigger's number (e.g. 0.37 for a Sahm indicator of 0.37 point; 0.18 for +18%)
  <id>_color   green / amber / red, or blank when there isn't enough data yet
  <id>_basis   real-time        = the values published at the time (ALFRED, or never revised)
               current-vintage  = today's values cut back by the release lag (DOL claims: our rule)
               revised          = before the series' first ALFRED vintage: earliest archived values

Overall Layer 1 status (plan): red if any of the first four triggers is red; amber if two or more triggers
are amber or red; otherwise green.

Run it (after build_claims_history.py, alfred_fetcher.py and current_fetcher.py):
    python src/model/triggers.py
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "model"))
from realtime import as_known_on, sahm, _current   # noqa: E402  (our own module, same folder)

CONFIG = ROOT / "config" / "triggers.csv"
OUT = ROOT / "data" / "model" / "triggers_monthly.csv"
FIRST_MONTH = "1967-01-01"
YEAR = pd.Timedelta(days=364)      # "a year ago" for weekly data = 52 weeks earlier (same weekday)


def basis(series: pd.Series) -> str:
    """Translate realtime.py's notes into the basis label."""
    if series.attrs.get("source") == "current":
        return "current-vintage"
    return "real-time" if series.attrs.get("real_time") else "revised"


def grade_up(value, amber, red) -> str:
    """Color for a trigger where HIGHER is worse (amber/red are 'at least' thresholds)."""
    if pd.isna(value):
        return ""
    return "red" if value >= red else "amber" if value >= amber else "green"


# ---------------------------------------------------------------------------------------------------
# One function per trigger. Each takes the as-of date and returns (value, color, basis).
# ---------------------------------------------------------------------------------------------------
def t_sahm(d, cfg):
    ur = as_known_on("UNRATE", d)
    ur = ur.asfreq("MS")                         # one row per month; a missing month stays blank
    if len(ur) < 15:
        return None, "", ""
    v = round(sahm(ur), 2)
    return v, grade_up(v, cfg.amber, cfg.red), basis(ur)


def t_claims_vs_low(d, cfg):
    ic4 = as_known_on("IC4WSA", d).dropna()
    if len(ic4) < 53:
        return None, "", ""
    v = ic4.iloc[-1] / ic4.iloc[-53:-1].min() - 1   # latest vs. lowest of the previous 52 weeks
    return round(v, 4), grade_up(round(v, 6), cfg.amber, cfg.red), basis(ic4)


def t_claims_yoy(d, cfg):
    ic4 = as_known_on("IC4WSA", d).dropna()
    then = ic4.get(ic4.index[-1] - YEAR) if len(ic4) else None
    if then is None or pd.isna(then):
        return None, "", ""
    v = ic4.iloc[-1] / then - 1
    return round(v, 4), grade_up(round(v, 6), cfg.amber, cfg.red), basis(ic4)


def t_cont_claims_yoy(d, cfg):
    cc = as_known_on("CCSA", d).dropna()
    cc4 = cc.rolling(4).mean()                    # 4-week average, like the initial-claims triggers
    then = cc4.get(cc4.index[-1] - YEAR) if len(cc4) else None
    if then is None or pd.isna(then):
        return None, "", ""
    v = cc4.iloc[-1] / then - 1
    return round(v, 4), grade_up(round(v, 6), cfg.amber, cfg.red), basis(cc)


def t_temp_help(d, cfg):
    th = as_known_on("TEMPHELPS", d).dropna()
    if len(th) < 7:
        return None, "", ""
    then = th.get(th.index[-1] - pd.DateOffset(months=6))
    if then is None or pd.isna(then):
        return None, "", ""
    v = th.iloc[-1] / then - 1
    # LOWER is worse here: red below -3%, amber below 0.
    color = "red" if v < cfg.red else "amber" if v < cfg.amber else "green"
    return round(v, 4), color, basis(th)


def yield_spread() -> pd.Series:
    """Monthly 10-year minus 3-month spread: GS10 - TB3MS before 1982, the official T10Y3MM from 1982."""
    early = (_current("GS10") - _current("TB3MS")).dropna()
    late = _current("T10Y3MM").dropna()
    return pd.concat([early[early.index < late.index[0]], late]).rename("spread")


def yield_colors(spread: pd.Series, need: int, red_months: int) -> pd.Series:
    """Walk the spread month by month. Amber while inverted (below 0) for `need`+ months in a row;
    red for `red_months` months after such an inversion ends (the re-steepening); otherwise green.
    Market rates are never revised, so this can be done once on the full series."""
    colors, run, months_since_end = [], 0, None
    for v in spread:
        if v < 0:
            run += 1
        else:
            if run >= need:                       # a qualifying inversion just ended
                months_since_end = 0
            run = 0
        if months_since_end is not None and v >= 0:
            months_since_end += 1
        if run >= need:
            colors.append("amber")
        elif months_since_end is not None and 1 <= months_since_end <= red_months:
            colors.append("red")
        else:
            colors.append("green")
    return pd.Series(colors, index=spread.index)


def t_mfg(d, cfg):
    philly = as_known_on("GACDFSA066MSFRBPHI", d)
    empire = as_known_on("GACDISA066MSFRBNY", d)
    both = pd.concat([philly, empire], axis=1).mean(axis=1).dropna()   # Philly alone before Jul 2001
    if len(both) < 3:
        return None, "", ""
    last3 = both.iloc[-3:]
    color = "red" if last3.mean() < cfg.red else "amber" if (last3 < cfg.amber).all() else "green"
    real = philly.attrs["real_time"] and (empire.attrs["real_time"] or len(empire) == 0)
    return round(both.iloc[-1], 1), color, "real-time" if real else "revised"


def t_nfci(d, cfg):
    nf = as_known_on("NFCI", d).dropna()
    if len(nf) == 0:
        return None, "", ""
    v = round(float(nf.iloc[-1]), 2)             # as published (2 decimals)
    color = "red" if v > cfg.red else "amber" if v > cfg.amber else "green"   # "above" thresholds
    return v, color, basis(nf)


def main() -> None:
    cfg = pd.read_csv(CONFIG).set_index("trigger_id")
    funcs = {"sahm": t_sahm, "claims_vs_low": t_claims_vs_low, "claims_yoy": t_claims_yoy,
             "cont_claims_yoy": t_cont_claims_yoy, "temp_help": t_temp_help, "mfg_surveys": t_mfg,
             "nfci": t_nfci}
    spread = yield_spread()
    ycol = yield_colors(spread, int(cfg.loc["yield_curve", "amber"]), int(cfg.loc["yield_curve", "red"]))

    # Months to evaluate: January 1967 to the last complete month.
    last = (pd.Timestamp.today().normalize() - pd.offsets.MonthBegin(1)) - pd.DateOffset(months=1)
    months = pd.date_range(FIRST_MONTH, last, freq="MS")
    rows = []
    for m in months:
        d = m + pd.offsets.MonthEnd(0)            # as-of date = last day of the month
        row = {"month": m}
        for tid in cfg.sort_values("order").index:
            if tid == "yield_curve":
                v, c, b = (round(spread[m], 2), ycol[m], "real-time") if m in spread.index else (None, "", "")
            else:
                v, c, b = funcs[tid](d, cfg.loc[tid])
            row[f"{tid}_value"], row[f"{tid}_color"], row[f"{tid}_basis"] = v, c, b
        rows.append(row)
    df = pd.DataFrame(rows).set_index("month")

    # Overall Layer 1 status.
    first_four = ["sahm", "claims_vs_low", "claims_yoy", "cont_claims_yoy"]
    colors = df[[f"{t}_color" for t in cfg.index]]
    df["n_amber_or_red"] = colors.isin(["amber", "red"]).sum(axis=1)
    any_red_top4 = (df[[f"{t}_color" for t in first_four]] == "red").any(axis=1)
    df["overall"] = "green"
    df.loc[df.n_amber_or_red >= 2, "overall"] = "amber"
    df.loc[any_red_top4, "overall"] = "red"

    df.to_csv(OUT, date_format="%Y-%m-%d")
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(df)} months, {months[0]:%Y-%m} to {months[-1]:%Y-%m}")

    # Coverage summary: first month with a color, and months on each basis.
    for tid in cfg.sort_values("order").index:
        col = df[f"{tid}_color"]
        first = col[col != ""].index.min()
        counts = df[f"{tid}_basis"].value_counts().to_dict()
        counts.pop("", None)
        print(f"  {tid:16} from {first:%Y-%m}  {counts}")
    print("  overall:", df.overall.value_counts().to_dict())

    # Yield-curve splice check: how different are the two definitions where both exist (1982 on)?
    gs = (_current("GS10") - _current("TB3MS")).dropna()
    both = pd.concat([gs.rename("gs10_tb3ms"), _current("T10Y3MM").rename("t10y3mm")], axis=1).dropna()
    diff = both.t10y3mm - both.gs10_tb3ms
    same_sign = ((both.t10y3mm < 0) == (both.gs10_tb3ms < 0)).mean()
    print(f"  yield splice check 1982-: T10Y3MM - (GS10 - TB3MS) mean {diff.mean():+.2f} pt, "
          f"mean absolute {diff.abs().mean():.2f}, max {diff.abs().max():.2f}; same sign {same_sign:.1%} of months")


if __name__ == "__main__":
    main()
