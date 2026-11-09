"""
Validation of the shutdown fallback (Phase 4 stage 4c gate). Pre-registered 2026-11-09 in docs/decisions.md,
before this script was run.

Two tests, both against DOL's official SA figures (national ETA 539 report), for initial claims (ic) and continuing
claims (cc), and for both fill-in methods ("carry" and "scaled", src/fetchers/dol_state_fallback.py):
  (a) Replay of the Oct-Nov 2025 shutdown (no national release for weeks ending Sep 27 - Nov 8, 2025): each week's
      estimate made without the areas reported missing at the time. Documented lists (Reuters): week ending Oct 11
      AZ, MA, NV, TN; Oct 18 TN, MA, CO. Other weeks: the union AZ, MA, NV, TN, CO, HI ("assumed"). Continuing claims
      filed in a week reflect the week before, so the filing week's missing list applies to the reflected week.
  (b) Monte Carlo: every week from 1996 to the latest, for k = 1..5, drop k areas at random with probability
      proportional to their share of that week's claims (one draw per week and k, the same draws for both methods,
      fixed seed). Headline = all weeks and k pooled; also shown by k and excluding Mar-Dec 2020.
Acceptance (O3): median absolute % error <= 2% and 90th percentile <= 5%.
Selection rule: "scaled" is used only if it beats "carry" on BOTH the median and the 90th percentile in (b), per
measure; otherwise "carry".

Limitation: this uses today's (revised) state data, so it understates real-time error from later state revisions.

Output: reports/fallback_validation.md, data/model/fallback_validation_mc.csv (every Monte Carlo draw).
Run:  python src/model/fallback_validation.py      (~2-4 min)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "fetchers"))
import dol_state_fallback as fb  # noqa: E402

DOL = ROOT / "data" / "processed" / "dol"
OUT_MD = ROOT / "reports" / "fallback_validation.md"
OUT_CSV = ROOT / "data" / "model" / "fallback_validation_mc.csv"
SEED = 2026
METHODS = ["carry", "scaled"]
LIMIT_MEDIAN, LIMIT_P90 = 2.0, 5.0

SHUTDOWN_WEEKS = ["2025-09-27", "2025-10-04", "2025-10-11", "2025-10-18", "2025-10-25", "2025-11-01", "2025-11-08"]
DOCUMENTED = {"2025-10-11": ["AZ", "MA", "NV", "TN"], "2025-10-18": ["TN", "MA", "CO"]}
UNION = ["AZ", "MA", "NV", "TN", "CO", "HI"]
# What economists estimated at the time (Reuters, quoted in the report as context, not used in any test)
AT_THE_TIME = {"2025-10-11": "about 217,000 (JPMorgan, Goldman Sachs)",
               "2025-10-18": "227,000-232,000 (Goldman Sachs 227k, JPMorgan 229k, Citi / Nationwide 232k)"}


def inputs():
    ic_wide, cc_wide = fb.area_claims(pd.read_csv(DOL / "ar539.csv"))
    nat = pd.read_csv(DOL / "national_weekly_eta539.csv", parse_dates=["week_ended"]).set_index("week_ended")
    return {"ic": (ic_wide, nat.ic_sf, nat.ic_sa), "cc": (cc_wide, nat.cc_sf, nat.cc_sa)}


def estimate_sa(wide, sf, week, missing, method) -> float:
    nsa, _ = fb.estimate_nsa(wide, week, missing, method)
    return fb.to_sa(nsa, sf[week])


# ---------------------------------------------------------------------------
# (a) Replay of the 2025 shutdown
# ---------------------------------------------------------------------------
def replay(data) -> pd.DataFrame:
    rows = []
    for w in SHUTDOWN_WEEKS:
        filing = pd.Timestamp(w)
        missing = DOCUMENTED.get(w, UNION)
        basis = "documented" if w in DOCUMENTED else "assumed"
        for measure in ("ic", "cc"):
            wide, sf, off = data[measure]
            week = filing if measure == "ic" else filing - pd.Timedelta(days=7)
            r = {"filing_week": w, "measure": measure, "week": f"{week:%Y-%m-%d}", "missing": " ".join(missing),
                 "basis": basis, "official_sa": off[week]}
            for m in METHODS:
                est = estimate_sa(wide, sf, week, missing, m)
                r[f"est_{m}"] = est
                r[f"err_{m}"] = fb.error_pct(est, off[week])
            rows.append(r)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# (b) Monte Carlo
# ---------------------------------------------------------------------------
def monte_carlo(data) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    rows = []
    for measure in ("ic", "cc"):
        wide, sf, off = data[measure]
        weeks = [w for w in wide.index if w >= pd.Timestamp("1996-01-06") and w in off.index and pd.notna(off[w])
                 and pd.notna(sf.get(w))]
        for w in weeks:
            row = wide.loc[w].dropna()
            row = row[row > 0]
            p = (row / row.sum()).values
            for k in range(1, 6):
                drop = list(rng.choice(row.index.values, size=k, replace=False, p=p))
                r = {"measure": measure, "week": w, "k": k, "dropped": " ".join(drop),
                     "share_dropped": float(row[drop].sum() / row.sum()), "official_sa": off[w]}
                for m in METHODS:
                    r[f"err_{m}"] = fb.error_pct(estimate_sa(wide, sf, w, drop, m), off[w])
                rows.append(r)
        print(f"  {measure}: {len(weeks)} weeks x 5 draws")
    return pd.DataFrame(rows)


def summary(errors: pd.Series) -> dict:
    a = errors.abs()
    return {"n": len(a), "median": a.median(), "p90": a.quantile(0.9), "max": a.max()}


def verdict(s: dict) -> str:
    ok = s["median"] <= LIMIT_MEDIAN and s["p90"] <= LIMIT_P90
    return "PASS" if ok else "FAIL"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def report(rp: pd.DataFrame, mc: pd.DataFrame) -> str:
    name = {"ic": "Initial claims", "cc": "Continuing claims"}
    L = ["# Shutdown fallback: validation (Phase 4 stage 4c)", "",
         "Pre-registered 2026-11-09 in docs/decisions.md before any run. Estimates vs. DOL's official SA figures.",
         f"Acceptance: median absolute error <= {LIMIT_MEDIAN:.0f}% and 90th percentile <= {LIMIT_P90:.0f}%. "
         "Selection rule: \"scaled\" only if it beats \"carry\" on both the median and the 90th percentile in (b).", "",
         "## (b) Monte Carlo, 1996 to date: k = 1-5 areas dropped (probability proportional to claims share)", "",
         "| Measure | Method | Draws | Median abs. error | 90th pct | Max | Verdict |", "| --- | --- | --- | --- | --- | --- | --- |"]
    chosen = {}
    for measure in ("ic", "cc"):
        d = mc[mc.measure == measure]
        s = {m: summary(d[f"err_{m}"]) for m in METHODS}
        for m in METHODS:
            L.append(f"| {name[measure]} | {m} | {s[m]['n']:,} | {s[m]['median']:.2f}% | {s[m]['p90']:.2f}% | "
                     f"{s[m]['max']:.1f}% | {verdict(s[m])} |")
        better = s["scaled"]["median"] < s["carry"]["median"] and s["scaled"]["p90"] < s["carry"]["p90"]
        chosen[measure] = "scaled" if better else "carry"
    L += ["", "**Selected by the rule:** " + "; ".join(f"{name[m]}: {chosen[m]}" for m in chosen), ""]

    L += ["### By number of areas missing (k), selected method", "",
          "| Measure | k | Median | 90th pct | Max | Avg. share of claims missing |", "| --- | --- | --- | --- | --- | --- |"]
    for measure in ("ic", "cc"):
        for k in range(1, 6):
            d = mc[(mc.measure == measure) & (mc.k == k)]
            s = summary(d[f"err_{chosen[measure]}"])
            L.append(f"| {name[measure]} | {k} | {s['median']:.2f}% | {s['p90']:.2f}% | {s['max']:.1f}% | "
                     f"{d.share_dropped.mean() * 100:.1f}% |")
    L += ["", "### Excluding March-December 2020 (pandemic surge; information only, not the acceptance basis)", "",
          "| Measure | Method | Median | 90th pct |", "| --- | --- | --- | --- |"]
    calm = mc[~mc.week.between("2020-03-01", "2020-12-31")]
    for measure in ("ic", "cc"):
        for m in METHODS:
            s = summary(calm[calm.measure == measure][f"err_{m}"])
            L.append(f"| {name[measure]} | {m} | {s['median']:.2f}% | {s['p90']:.2f}% |")
    L += ["", "### Largest errors (selected method)", "",
          "| Measure | Week | k | Dropped | Error |", "| --- | --- | --- | --- | --- |"]
    for measure in ("ic", "cc"):
        d = mc[mc.measure == measure].copy()
        d["e"] = d[f"err_{chosen[measure]}"]
        for r in d.reindex(d.e.abs().sort_values(ascending=False).index).head(5).itertuples():
            L.append(f"| {name[measure]} | {r.week:%Y-%m-%d} | {r.k} | {r.dropped} | {r.e:+.1f}% |")

    L += ["", "## (a) Replay: Oct-Nov 2025 shutdown (no national release for these weeks)", "",
          "| Filing week | Measure | Week | Missing areas | Basis | Official SA | Carry | Scaled |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rp.itertuples():
        L.append(f"| {r.filing_week} | {name[r.measure]} | {r.week} | {r.missing} | {r.basis} | {r.official_sa:,.0f} | "
                 f"{r.est_carry:,.0f} ({r.err_carry:+.2f}%) | {r.est_scaled:,.0f} ({r.err_scaled:+.2f}%) |")
    L += ["", "| Measure | Method | Median abs. error | 90th pct | Max | Verdict |", "| --- | --- | --- | --- | --- | --- |"]
    for measure in ("ic", "cc"):
        for m in METHODS:
            s = summary(rp[rp.measure == measure][f"err_{m}"])
            L.append(f"| {name[measure]} | {m} | {s['median']:.2f}% | {s['p90']:.2f}% | {s['max']:.2f}% | {verdict(s)} |")
    L += ["", "Context (not a test): what economists estimated at the time, from the same state data then available:"]
    for w, txt in AT_THE_TIME.items():
        off = rp[(rp.filing_week == w) & (rp.measure == "ic")].official_sa.iloc[0]
        L.append(f"- Week ending {w}: {txt}; official SA today {off:,.0f}.")
    L += ["", "## Limitations", "",
          "- Today's state data are revised: real-time errors from later state revisions are not captured, so these "
          "errors understate what a live estimate would show.",
          "- The official SA figures compared with are DOL's current published values (DOL revises SA claims each spring).",
          "- Only two shutdown weeks have a documented list of missing areas (Reuters); the others assume the union of "
          "the areas named missing at some point.",
          "- One draw per week and k (fixed seed 2026): the pooled statistics rest on about 8,000 draws per measure.", ""]
    return "\n".join(L), chosen


def main() -> None:
    data = inputs()
    print("Replay of the 2025 shutdown ...")
    rp = replay(data)
    print("Monte Carlo (1996 to date) ...")
    mc = monte_carlo(data)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    mc.to_csv(OUT_CSV, index=False, float_format="%.4f", date_format="%Y-%m-%d")
    text, chosen = report(rp, mc)
    OUT_MD.write_text(text, encoding="utf-8")
    print(f"Wrote {OUT_MD.relative_to(ROOT)} and {OUT_CSV.relative_to(ROOT)}; selected: {chosen}")


if __name__ == "__main__":
    main()
