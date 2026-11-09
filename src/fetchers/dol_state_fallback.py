"""
Shutdown fallback (Phase 4 stage 4c): estimate national weekly claims from the state filings when DOL's weekly
release is delayed (e.g. the Oct-Nov 2025 federal government shutdown, when states kept filing to DOL's ETA 539
database but no national release came out).

When it estimates (otherwise it does nothing):
  a week's official figure is OVERDUE (its Thursday release time has passed: 9:30 am ET, after the Thursday wait step
  gives up) and neither FRED (ICSA) nor DOL's national report has that week, but data/processed/dol/ar539.csv has it.

How (pre-registered 2026-11-09, docs/decisions.md):
  NSA estimate = sum over reporting areas of (regular state UI + work-sharing equivalent) + a fill-in for each missing
                 area (the 53 DOL areas: 50 states, DC, PR, VI)
  fill-in      "carry"  : the area's last reported value
               "scaled" : that value x (sum this week / sum in that earlier week, over areas reporting in both)
  SA estimate  = NSA / (DOL's published seasonal factor for the week / 100)
  Continuing claims the same way, dated by the week of unemployment they reflect (one week behind), with the CC factor.
  The method used is FILL_METHOD below, chosen by the pre-registered rule from the validation
  (src/model/fallback_validation.py -> reports/fallback_validation.md).

Output: data/processed/dol/claims_estimates.csv, a separate file never mixed into the official tables.
  One row per estimated week and measure (ic / cc). When the official figure arrives, its value and the estimate's
  error are filled in and the replacement is logged in docs/data_revisions.md; the row stays as a record.
  The site and the live model read estimates only for weeks after the latest official week (active_estimates()).

Run (the refresh workflow runs it after the state measures):
    python src/fetchers/dol_state_fallback.py
Preview on the PC only (never in the cloud; nothing committed): pretend the last N official weeks are missing,
    python src/fetchers/dol_state_fallback.py --simulate-delay 2
  writes data/processed/dol/claims_estimates_preview.csv (git-ignored). Then build the site with the environment
  variable UW_PREVIEW_DELAY=2 to see the labels:  $env:UW_PREVIEW_DELAY=2; python src\\site\\build_site.py
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
DOL = PROCESSED / "dol"
ESTIMATES = DOL / "claims_estimates.csv"
PREVIEW = DOL / "claims_estimates_preview.csv"
REVISIONS = ROOT / "docs" / "data_revisions.md"
EASTERN = ZoneInfo("America/New_York")

FILL_METHOD = "scaled"          # chosen by the pre-registered rule (reports/fallback_validation.md, 2026-11-09)
METHOD_VERSION = "v1"
RELEASE_DELAY = timedelta(days=5, hours=9, minutes=30)   # week ends Saturday 0:00 -> Thursday 9:30 am ET
COLUMNS = ["week_ended", "measure", "estimate_nsa", "seasonal_factor", "estimate_sa", "areas_reported",
           "missing_areas", "method", "made_utc", "official_sa", "error_pct", "replaced_utc"]


# ===========================================================================
# Building blocks (pure functions: tested in tests/test_state_fallback.py)
# ===========================================================================
def area_claims(ar539: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Wide tables (week x area) of initial claims and continued weeks claimed, on DOL's national basis:
    regular state UI + work-sharing equivalent (the national totals include it). Continued weeks are dated by the
    week they reflect. A blank state UI figure stays blank (the area did not report)."""
    a = ar539.copy()
    a["ic"] = a.ic_state_ui + a.ic_stc_workshare_equiv.fillna(0)
    a["cc"] = a.cw_state_ui + a.cw_stc_workshare_equiv.fillna(0)
    # one row per area and week, so a plain pivot keeps blanks as blanks
    ic = a.pivot(index="week_ended", columns="state", values="ic")
    cc = a.dropna(subset=["reflected_week_ended"]).pivot(index="reflected_week_ended", columns="state", values="cc")
    ic.index, cc.index = pd.to_datetime(ic.index), pd.to_datetime(cc.index)
    ic.index.name = cc.index.name = "week_ended"
    return ic.sort_index(), cc.sort_index()


def estimate_nsa(wide: pd.DataFrame, week, missing, method: str = FILL_METHOD) -> tuple[float, list[str]]:
    """NSA estimate for `week`: the reporting areas' sum plus a fill-in for each area in `missing` (and for any
    area with no value that week). Returns (estimate, list of filled-in areas)."""
    week = pd.Timestamp(week)
    row = wide.loc[week].copy()
    row[list(missing)] = np.nan
    filled = []
    total = row.sum(skipna=True)
    reporting = row.dropna().index
    for area in row.index[row.isna()]:
        past = wide.loc[wide.index < week, area].dropna()
        if past.empty:
            continue                      # an area that never reported adds nothing
        s, value = past.index[-1], past.iloc[-1]
        if method == "scaled":
            both = [r for r in reporting if pd.notna(wide.at[s, r])]
            then = wide.loc[s, both].sum()
            value = value * (row[both].sum() / then) if then > 0 else value
        elif method != "carry":
            raise ValueError(f"unknown fill-in method {method}")
        total += value
        filled.append(area)
    return float(total), sorted(filled)


def to_sa(nsa: float, factor: float) -> float:
    """DOL's seasonal adjustment: NSA / (factor / 100)."""
    return nsa / (factor / 100.0)


def overdue(week, now: datetime) -> bool:
    """True once the week's national release time has passed (Thursday 9:30 am ET after the week ends)."""
    due = pd.Timestamp(week).to_pydatetime().replace(tzinfo=EASTERN) + RELEASE_DELAY
    return now.astimezone(EASTERN) >= due


def error_pct(estimate: float, official: float) -> float:
    return (estimate / official - 1.0) * 100.0


# ===========================================================================
# Official figures and the estimates file
# ===========================================================================
def official_sa() -> dict[str, pd.Series]:
    """Latest official SA initial / continuing claims by week: FRED (ICSA / CCSA), else DOL's national report."""
    out = {}
    nat = pd.read_csv(DOL / "national_weekly_eta539.csv", parse_dates=["week_ended"]).set_index("week_ended")
    for measure, fred_id, col in [("ic", "ICSA", "ic_sa"), ("cc", "CCSA", "cc_sa")]:
        f = pd.read_csv(PROCESSED / f"{fred_id}.csv", parse_dates=["date"]).set_index("date")["value"].dropna()
        out[measure] = f.combine_first(nat[col].dropna()).sort_index()
    return out


def preview_delay() -> int:
    """UW_PREVIEW_DELAY (PC preview only): the number of official weeks to pretend are missing; 0 normally."""
    try:
        return max(0, int(os.environ.get("UW_PREVIEW_DELAY", "0")))
    except ValueError:
        return 0


def read_estimates(path: Path = ESTIMATES) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(path, dtype={"missing_areas": str}, parse_dates=["week_ended"])
    df["missing_areas"] = df.missing_areas.fillna("")
    return df


def active_estimates() -> pd.DataFrame:
    """Estimates for weeks AFTER the latest official week, per measure: what the site and the live model show.
    Empty in normal times. With UW_PREVIEW_DELAY set, the preview file is used and the official series are cut
    back by that many weeks (see cut_official)."""
    n = preview_delay()
    est = read_estimates(PREVIEW if n else ESTIMATES)
    if est.empty:
        return est
    off = official_sa()
    keep = []
    for measure, s in off.items():
        last = cut_official(s, n).index.max()
        keep.append(est[(est.measure == measure) & (est.week_ended > last)])
    return pd.concat(keep).sort_values(["measure", "week_ended"]).reset_index(drop=True)


def cut_official(s: pd.Series, n: int | None = None) -> pd.Series:
    """Drop the last n weeks of an official weekly series (PC preview only; n = UW_PREVIEW_DELAY by default)."""
    n = preview_delay() if n is None else n
    return s.iloc[:-n] if n else s


# ===========================================================================
# The run
# ===========================================================================
def estimate_rows(ic_wide, cc_wide, factors, official, now: datetime, delay: int = 0) -> list[dict]:
    """Rows for every overdue week that ar539 has but the official series do not (after cutting `delay` weeks)."""
    rows = []
    for measure, wide, sf_col in [("ic", ic_wide, "ic_sf"), ("cc", cc_wide, "cc_sf")]:
        last_official = cut_official(official[measure], delay).index.max()
        # continued claims of a reflected week are filed (and released) a week later than initial claims
        release_week = (lambda w: w + timedelta(days=7)) if measure == "cc" else (lambda w: w)
        for week in wide.index[wide.index > last_official]:
            if not (delay or overdue(release_week(week), now)):
                continue
            reported = wide.loc[week].notna()
            if reported.sum() == 0 or week not in factors.index or pd.isna(factors.at[week, sf_col]):
                continue
            nsa, filled = estimate_nsa(wide, week, [], FILL_METHOD)
            sf = float(factors.at[week, sf_col])
            rows.append({"week_ended": week, "measure": measure, "estimate_nsa": round(nsa),
                         "seasonal_factor": sf, "estimate_sa": round(to_sa(nsa, sf)),
                         "areas_reported": int(reported.sum()), "missing_areas": " ".join(filled),
                         "method": f"{METHOD_VERSION}-{FILL_METHOD}", "made_utc": now.strftime("%Y-%m-%d %H:%M"),
                         "official_sa": None, "error_pct": None, "replaced_utc": None})
    return rows


def merge(est: pd.DataFrame, new: list[dict]) -> pd.DataFrame:
    """Add new estimates; an open estimate (no official yet) is updated when more areas have reported."""
    est = est.copy()
    for r in new:
        same = (est.week_ended == r["week_ended"]) & (est.measure == r["measure"])
        if not same.any():
            est = pd.concat([est, pd.DataFrame([r])], ignore_index=True)
        else:
            i = est.index[same][0]
            if pd.isna(est.at[i, "official_sa"]) and r["areas_reported"] > est.at[i, "areas_reported"]:
                for k in ("estimate_nsa", "seasonal_factor", "estimate_sa", "areas_reported", "missing_areas",
                          "method", "made_utc"):
                    est.at[i, k] = r[k]
    return est


def fill_officials(est: pd.DataFrame, official, now: datetime) -> tuple[pd.DataFrame, list[str]]:
    """Fill in the official value and the error for estimates whose week is now published. Returns log lines."""
    est = est.copy()
    lines = []
    for i, r in est.iterrows():
        if pd.notna(r.official_sa):
            continue
        s = official[r.measure]
        if r.week_ended in s.index:
            off = float(s[r.week_ended])
            est.at[i, "official_sa"] = round(off)
            est.at[i, "error_pct"] = round(error_pct(r.estimate_sa, off), 2)
            est.at[i, "replaced_utc"] = now.strftime("%Y-%m-%d %H:%M")
            name = "initial claims" if r.measure == "ic" else "continuing claims"
            lines.append(f"- {now:%Y-%m-%d}: estimated SA {name}, week ending {r.week_ended:%Y-%m-%d}, replaced by the "
                         f"official figure: estimate {r.estimate_sa:,.0f} ({int(r.areas_reported)} of 53 areas), "
                         f"official {off:,.0f}, error {est.at[i, 'error_pct']:+.2f}%")
    return est, lines


def log_revisions(lines: list[str]) -> None:
    if not lines:
        return
    with open(REVISIONS, "a", encoding="utf-8") as f:
        f.write("\n### Shutdown-fallback estimates replaced by official figures\n" + "\n".join(lines) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--simulate-delay", type=int, default=0,
                    help="PC preview only: pretend the last N official weeks are missing (writes the preview file)")
    args = ap.parse_args(argv)
    now = datetime.now(EASTERN)
    ar539 = pd.read_csv(DOL / "ar539.csv")
    ic_wide, cc_wide = area_claims(ar539)
    factors = pd.read_csv(DOL / "seasonal_factors.csv", parse_dates=["week_ended"]).set_index("week_ended")
    official = official_sa()

    if args.simulate_delay:
        if os.environ.get("GITHUB_ACTIONS"):
            sys.exit("--simulate-delay is a PC preview and never runs in the cloud")
        rows = estimate_rows(ic_wide, cc_wide, factors, official, now, delay=args.simulate_delay)
        df = pd.DataFrame(rows, columns=COLUMNS)
        df, _ = fill_officials(df, official, now)      # the preview knows the real answer: shows the error
        df.to_csv(PREVIEW, index=False, date_format="%Y-%m-%d")
        print(f"Preview: {len(df)} estimates written to {PREVIEW.relative_to(ROOT)} (git-ignored)")
        print(df[["week_ended", "measure", "estimate_sa", "official_sa", "error_pct", "areas_reported"]].to_string(index=False))
        print(f"Build the site with  $env:UW_PREVIEW_DELAY={args.simulate_delay}  to see the labels.")
        return 0

    est = merge(read_estimates(), estimate_rows(ic_wide, cc_wide, factors, official, now))
    est, lines = fill_officials(est, official, now)
    log_revisions(lines)
    if len(est) or ESTIMATES.exists():
        est[COLUMNS].to_csv(ESTIMATES, index=False, date_format="%Y-%m-%d")
    open_ = est[est.official_sa.isna()] if len(est) else est
    if len(open_):
        print(f"Release delayed: {len(open_)} week(s) estimated from state filings:")
        print(open_[["week_ended", "measure", "estimate_sa", "areas_reported", "missing_areas"]].to_string(index=False))
    else:
        print("No delayed release: official claims are up to date (no estimate needed).")
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
