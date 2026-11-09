"""
Data-quality checks and series-health summary. Runs at the end of the refresh workflow.

For every active series (FRED and Chicago Fed from the catalog; DOL columns from
config/quality_dol_columns.csv) it checks:
  stale    days since the latest observation > allowed age (config/quality_rules.csv, max_age_days)
  gaps     missing or blank periods between first and last date, except known gaps in the rules file
           (daily series are skipped: holidays are normal gaps)
  outlier  robust z-score of the latest period-to-period change against the trailing 3 years of changes:
           z = (latest change - median) / (1.4826 x MAD); flagged when |z| > 6 (report only)
  fetch    the latest result for the series in data/fetch_log.csv
For DOL state files it also reports how many areas reported in the latest period; staleness there uses
the latest period in which every area reported, and a min_areas rule flags a latest period with too few areas.
It also warns when DOL's published seasonal factors are running out (min_future_weeks rule).

Status per series: FAIL = a Tier 1 series is stale or missing (the only thing that fails the run);
WARN = any other flag; OK = no flags. Output: data/processed/series_health.csv (plus a printed summary).

Run:  python src/checks/data_quality.py
"""

import csv
import sys
from datetime import date
from fnmatch import fnmatch
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "fetchers"))
from fred_fetcher import series_to_fetch  # noqa: E402  (list of active FRED series with tiers)

PROCESSED = ROOT / "data" / "processed"
DOL_DIR = PROCESSED / "dol"
CATALOG = ROOT / "config" / "series_catalog.csv"
RULES = ROOT / "config" / "quality_rules.csv"
DOL_COLUMNS = ROOT / "config" / "quality_dol_columns.csv"
FETCH_LOG = ROOT / "data" / "fetch_log.csv"
OUTPUT = PROCESSED / "series_health.csv"
TODAY = pd.Timestamp(date.today())


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
def load_rules() -> list[dict]:
    with open(RULES, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def max_age(rules, series_id: str, freq: str) -> int:
    """First matching specific rule wins; otherwise the default for the frequency."""
    for r in rules:
        if r["rule"] == "max_age_days" and not r["target"].startswith("default:") and fnmatch(series_id, r["target"]):
            return int(r["value"])
    return int(next(r["value"] for r in rules if r["rule"] == "max_age_days" and r["target"] == f"default:{freq}"))


def rule_value(rules, name: str, series_id: str) -> float | None:
    """Value of the first rule `name` whose target matches the series (None if no rule applies)."""
    r = next((r for r in rules if r["rule"] == name and fnmatch(series_id, r["target"])), None)
    return float(r["value"]) if r else None


def setting(rules, name: str) -> float:
    return float(next(r["value"] for r in rules if r["rule"] == name))


def known_gaps(rules, series_id: str) -> set[str]:
    return {r["value"] for r in rules if r["rule"] == "known_gap" and fnmatch(series_id, r["target"])}


def norm_freq(text: str) -> str:
    t = str(text).lower()
    for f in ("daily", "weekly", "quarterly", "monthly"):
        if f in t:
            return f
    return "monthly"


# ---------------------------------------------------------------------------
# Inventory: which series to check
# ---------------------------------------------------------------------------
def catalog() -> dict[str, dict]:
    with open(CATALOG, encoding="utf-8") as f:
        return {r["series_id"]: r for r in csv.DictReader(f)}


def inventory() -> list[dict]:
    cat = catalog()
    meta = pd.read_csv(PROCESSED / "_metadata.csv").set_index("series_id") if (PROCESSED / "_metadata.csv").exists() else pd.DataFrame()
    items = []

    for sid, tier in series_to_fetch().items():
        freq = norm_freq(meta.frequency.get(sid, "")) if "frequency" in meta else "monthly"
        items.append({"series_id": sid, "source": "FRED", "tier": tier, "frequency": freq,
                      "path": PROCESSED / f"{sid}.csv", "column": "value", "date_col": "date", "fetch_id": sid})

    if cat.get("CHI_LMI", {}).get("status") == "active":
        for p in sorted(PROCESSED.glob("CFLMI*.csv")):
            items.append({"series_id": p.stem, "source": "Chicago Fed", "tier": cat["CHI_LMI"]["tier"],
                          "frequency": "monthly", "path": p, "column": "value", "date_col": "date", "fetch_id": p.stem})

    with open(DOL_COLUMNS, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            row = cat.get(r["catalog_id"], {})
            if row.get("status") != "active":
                continue
            items.append({"series_id": f"DOL:{r['file']}:{r['column']}", "source": "DOL", "tier": row["tier"],
                          "frequency": r["frequency"], "path": DOL_DIR / r["file"], "column": r["column"],
                          "date_col": r["date_col"], "fetch_id": r["catalog_id"],
                          "by_state": r["by_state"] == "yes", "filter_state": r["filter_state"]})
    return items


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def to_period(dates: pd.Series, freq: str) -> pd.Series:
    return pd.to_datetime(dates).dt.to_period({"weekly": "W-SAT", "monthly": "M", "quarterly": "Q"}[freq])


def find_gaps(df: pd.DataFrame, freq: str, known: set[str]) -> list[str]:
    """Periods between first and last date that are missing or blank (minus known gaps)."""
    if freq == "daily" or df.empty:
        return []
    # Only look between the first and last real values (warm-up blanks and a not-yet-published latest
    # field, e.g. continued claims for the advance week, are not gaps).
    valid = df.date[df.value.notna()]
    if valid.empty:
        return []
    df = df[(df.date >= valid.min()) & (df.date <= valid.max())]
    if freq == "weekly":
        expected = pd.date_range(df.date.min(), df.date.max(), freq="7D").strftime("%Y-%m-%d")
        present = set(df.date[df.value.notna()])
        missing = [d for d in expected if d not in present]
    else:
        per = to_period(df.date, freq)
        have = set(per[df.value.notna().values])
        expected = pd.period_range(per.min(), per.max(), freq=per.dt.freq)
        missing = [str(p) for p in expected if p not in have]
    known_p = {str(to_period(pd.Series([k]), freq).iloc[0]) for k in known} if freq != "weekly" else known
    return [m for m in missing if m not in known_p]


def outlier_z(df: pd.DataFrame, years: float) -> float | None:
    """Robust z-score of the latest change against the trailing window of changes (None if not computable)."""
    s = df.dropna(subset=["value"]).set_index(pd.to_datetime(df.dropna(subset=["value"]).date)).value
    changes = s.diff().dropna().round(9)   # remove floating-point noise (e.g. 0.1 - 0.2 != -0.1 exactly)
    if len(changes) < 13:
        return None
    latest, past = changes.iloc[-1], changes.iloc[:-1]
    past = past[past.index > changes.index[-1] - pd.DateOffset(years=int(years))]
    if len(past) < 12:
        return None
    med = past.median()
    scale = 1.4826 * (past - med).abs().median()        # MAD, scaled to a standard deviation
    if scale == 0:
        # Most past changes are exactly zero (e.g. rates published to 1 decimal): fall back to the
        # mean absolute deviation from the median, scaled by sqrt(pi/2) = 1.2533 (decision 2026-11-07).
        scale = 1.2533 * (past - med).abs().mean()
    if scale == 0:
        return None
    return float((latest - med) / scale)


def last_fetch_status(log: pd.DataFrame, fetch_id: str) -> str:
    rows = log[log.series_id == fetch_id]
    if rows.empty:
        return "n/a"
    s = str(rows.status.iloc[-1])
    return "FAILED" if s.startswith("FAILED") else "ok"


def check(item: dict, rules, log) -> dict:
    sid, freq, tier = item["series_id"], item["frequency"], str(item["tier"])
    out = {"series_id": sid, "source": item["source"], "tier": tier, "frequency": freq,
           "first_date": "", "last_date": "", "age_days": "", "max_age_days": max_age(rules, sid, freq),
           "gaps": "", "gap_examples": "", "latest_change_z": "", "areas_latest": "",
           "last_fetch": last_fetch_status(log, item["fetch_id"]), "flags": "", "status": "OK"}
    flags = []

    skip = next((r for r in rules if r["rule"] == "skip" and fnmatch(sid, r["target"])), None)
    if skip:
        out["status"], out["flags"] = "SKIP", f"not checked: {skip['reason']}"
        return out

    if not item["path"].exists():
        flags.append("no data file")
    else:
        raw = pd.read_csv(item["path"], low_memory=False)
        if item.get("filter_state"):
            raw = raw[raw.state == item["filter_state"]]
        df = raw[[item["date_col"], item["column"]]].rename(columns={item["date_col"]: "date", item["column"]: "value"})

        if item.get("by_state"):
            # One value per period = number of areas reporting; staleness uses the latest complete period.
            counts = raw.groupby(item["date_col"]).state.count()
            full = counts.max()
            out["areas_latest"] = f"{counts.iloc[-1]}/{full} ({counts.index[-1]})"
            min_areas = rule_value(rules, "min_areas", sid)
            if min_areas is not None and counts.iloc[-1] < min_areas:
                flags.append(f"incomplete: {counts.iloc[-1]} of {full} areas in {counts.index[-1]} "
                             f"(limit {min_areas:.0f})")
            complete = counts[counts >= full]
            df = pd.DataFrame({"date": complete.index, "value": 1.0})
            gaps = find_gaps(pd.DataFrame({"date": counts.index, "value": 1.0}), freq, set())
        else:
            df = df.sort_values("date").reset_index(drop=True)
            gaps = find_gaps(df, freq, known_gaps(rules, sid))
            z = outlier_z(df, setting(rules, "outlier_window_years"))
            if z is not None:
                out["latest_change_z"] = round(z, 2)
                if abs(z) > setting(rules, "outlier_z"):
                    flags.append(f"outlier: latest change z = {z:+.1f}")

        valid = df.dropna(subset=["value"])
        if valid.empty:
            flags.append("no data")
        else:
            out["first_date"], out["last_date"] = valid.date.min(), valid.date.max()
            age = (TODAY - pd.Timestamp(out["last_date"])).days
            out["age_days"] = age
            if age > out["max_age_days"]:
                flags.append(f"stale: {age} days old (limit {out['max_age_days']})")
        out["gaps"] = len(gaps)
        out["gap_examples"] = " ".join(gaps[:5])
        if gaps:
            flags.append(f"{len(gaps)} unexpected gap(s)")

    if out["last_fetch"] == "FAILED":
        flags.append("last fetch FAILED")

    critical = any(f.startswith(("stale", "no data")) for f in flags) and tier == "1"
    out["status"] = "FAIL" if critical else ("WARN" if flags else "OK")
    out["flags"] = "; ".join(flags)
    return out


def seasonal_factor_check(rules) -> dict:
    """Warn when fewer than min_future_weeks of DOL's published seasonal factors lie after today."""
    sid = "DOL:seasonal_factors.csv"
    limit = rule_value(rules, "min_future_weeks", sid)
    out = {"series_id": sid, "source": "DOL", "tier": "1", "frequency": "weekly", "first_date": "", "last_date": "",
           "age_days": "", "max_age_days": "", "gaps": "", "gap_examples": "", "latest_change_z": "",
           "areas_latest": "", "last_fetch": "n/a", "flags": "", "status": "OK"}
    path = DOL_DIR / "seasonal_factors.csv"
    if not path.exists():
        out.update(status="WARN", flags="no data file")
        return out
    sf = pd.read_csv(path).dropna(subset=["ic_sf", "cc_sf"])
    out["first_date"], out["last_date"] = sf.week_ended.min(), sf.week_ended.max()
    future = int((pd.to_datetime(sf.week_ended) > TODAY).sum())
    out["areas_latest"] = f"{future} future weeks"
    if limit is not None and future < limit:
        out.update(status="WARN", flags=f"seasonal factors running out: {future} future weeks left (limit {limit:.0f})")
    return out


def main() -> int:
    rules = load_rules()
    log = pd.read_csv(FETCH_LOG) if FETCH_LOG.exists() else pd.DataFrame(columns=["series_id", "status"])
    results = pd.DataFrame([check(item, rules, log) for item in inventory()] + [seasonal_factor_check(rules)])
    results.to_csv(OUTPUT, index=False)

    counts = results.status.value_counts().to_dict()
    print(f"Series health: {len(results)} series checked: "
          f"{counts.get('OK', 0)} OK, {counts.get('WARN', 0)} WARN, {counts.get('FAIL', 0)} FAIL, "
          f"{counts.get('SKIP', 0)} skipped "
          f"(written to {OUTPUT.relative_to(ROOT)})")
    for status in ("FAIL", "WARN"):
        rows = results[results.status == status]
        if len(rows):
            print(f"\n{status}:")
            for _, r in rows.iterrows():
                print(f"  {r['series_id']:<48} tier {r['tier']}  {r['flags']}")   # r["flags"]: r.flags is a pandas attribute
    if counts.get("FAIL", 0):
        print("\nDATA QUALITY FAILED: a Tier 1 series is stale or missing (see above).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
