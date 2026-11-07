"""
Merged national weekly claims table: official ETA 539 weeks + preliminary weeks from the news release.

DOL's weekly news release (www.dol.gov/ui/data.pdf) blocks automated downloads, so the preliminary
weeks come from FRED, which republishes the release's figures on release morning (decision 2026-11-07):
  initial claims   ICNSA, ICSA, IC4WSA
  continued claims CCNSA, CCSA, CC4WSA, IURSA, IURNSA
Seasonal factors for those weeks come from DOL's published factors; covered employment is carried
forward from the latest ETA 539 week (DOL updates it quarterly).

Program detail (federal employees, veterans, EB, state additional benefits, workshare) is the sum of
the state rows in ar539.csv, for every week.

Rules (part 2 of the DOL pipeline):
  - Only weeks the ETA 539 report doesn't have yet are filled; official values are never overwritten.
  - source_initial / source_continued say where each week's figures came from:
      "ETA 539", "news release, advance" (newest week) or "news release, revised" (earlier weeks).
  - The table is rebuilt from scratch on every run, so release values disappear as soon as ETA 539
    has the week. No history of release figures is kept.

Run AFTER fred_fetcher.py, dol_national.py and dol_state.py:
    python src/fetchers/dol_recent_weeks.py
Output: data/processed/dol/national_weekly.csv
"""

import sys

import pandas as pd

from dol_common import DOL_DIR, FRED_DIR, log_fetch, update_metadata

SERIES_ID = "DOL_NATIONAL_WEEKLY"
IC_FROM_FRED = {"ic_nsa": "ICNSA", "ic_sa": "ICSA", "ic_sa_4wk": "IC4WSA"}
CC_FROM_FRED = {"cc_nsa": "CCNSA", "cc_sa": "CCSA", "cc_sa_4wk": "CC4WSA", "iur_sa": "IURSA", "iur_nsa": "IURNSA"}

# News-release "all programs" components, from ar539 state sums.
IC_PROGRAMS = {"ic_ucfe": "ic_ucfe", "ic_ucx": "ic_ucx"}
CW_PROGRAMS = {"cw_regular_state": "cw_state_ui", "cw_ucfe": "cw_ucfe", "cw_ucx": "cw_ucx",
               "cw_eb": "cw_eb_total", "cw_state_additional": "cw_state_additional_total",
               "cw_stc_workshare": "cw_stc_workshare"}


def fred(series_id: str) -> pd.Series:
    return pd.read_csv(FRED_DIR / f"{series_id}.csv").set_index("date")["value"]


def preliminary(fields: dict, after: str, source_col: str) -> pd.DataFrame:
    """FRED values for weeks after the last official week, labelled advance / revised."""
    first = fred(next(iter(fields.values())))
    weeks = sorted(w for w in first.dropna().index if w > after)
    out = pd.DataFrame(index=pd.Index(weeks, name="week_ended"))
    for col, fid in fields.items():
        out[col] = fred(fid).reindex(weeks)
    out[source_col] = "news release, revised"
    if weeks:
        out.loc[weeks[-1], source_col] = "news release, advance"
    return out


def state_sums(ar: pd.DataFrame, date_col: str, columns: dict) -> pd.DataFrame:
    """National totals from state rows, only for weeks where every area reported."""
    g = ar.groupby(date_col)
    complete = g.state.count() >= g.state.count().max()
    sums = g[list(columns.values())].sum()[complete]
    return sums.rename(columns={v: k for k, v in columns.items()}).rename_axis("week_ended")


def main() -> int:
    official = pd.read_csv(DOL_DIR / "national_weekly_eta539.csv").set_index("week_ended")
    factors = pd.read_csv(DOL_DIR / "seasonal_factors.csv").set_index("week_ended")
    ar = pd.read_csv(DOL_DIR / "ar539.csv", low_memory=False)

    merged = official.copy()
    merged["source_initial"] = merged.ic_nsa.notna().map({True: "ETA 539", False: pd.NA})
    merged["source_continued"] = merged.cc_nsa.notna().map({True: "ETA 539", False: pd.NA})

    last_ic = merged.index[merged.ic_nsa.notna()].max()
    last_cc = merged.index[merged.cc_nsa.notna()].max()
    pre_ic = preliminary(IC_FROM_FRED, last_ic, "source_initial")
    pre_cc = preliminary(CC_FROM_FRED, last_cc, "source_continued")
    pre_ic["ic_sf"] = factors.ic_sf.reindex(pre_ic.index)
    pre_cc["cc_sf"] = factors.cc_sf.reindex(pre_cc.index)

    # combine_first fills only blanks, so official ETA 539 values always win.
    merged = merged.combine_first(pre_ic).combine_first(pre_cc).sort_index()
    merged["covered_employment"] = merged.covered_employment.ffill()

    programs = state_sums(ar, "week_ended", IC_PROGRAMS).join(
        state_sums(ar, "reflected_week_ended", CW_PROGRAMS), how="outer")
    programs["cw_all_programs"] = programs[list(CW_PROGRAMS)].sum(axis=1, min_count=len(CW_PROGRAMS))
    merged = merged.join(programs, how="left")

    order = ["source_initial", "source_continued", "ic_nsa", "ic_sf", "ic_sa", "ic_sa_4wk",
             "cc_nsa", "cc_sf", "cc_sa", "cc_sa_4wk", "iur_nsa", "iur_sa", "covered_employment",
             *IC_PROGRAMS, *CW_PROGRAMS, "cw_all_programs"]
    merged = merged[order].reset_index()
    for c in ["ic_nsa", "ic_sa", "cc_nsa", "cc_sa", "covered_employment", *IC_PROGRAMS, *CW_PROGRAMS,
              "cw_all_programs"]:
        merged[c] = merged[c].round().astype("Int64")

    merged.to_csv(DOL_DIR / "national_weekly.csv", index=False)
    update_metadata("national_weekly.csv", "Merged national weekly claims (ETA 539 + preliminary weeks)",
                    "ETA 539 national report; FRED (news release figures); ar539 state sums",
                    merged, "week_ended")

    status = (f"{len(merged)} weeks; official through IC {last_ic} / CC {last_cc}; "
              f"preliminary IC weeks {list(pre_ic.index)}, CC weeks {list(pre_cc.index)}")
    print(f"{SERIES_ID}: {status}")
    log_fetch(SERIES_ID, "updated: " + status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
