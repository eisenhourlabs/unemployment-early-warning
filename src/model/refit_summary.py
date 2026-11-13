"""
Stage 3e-3: summary of a January re-fit, for the pull request the "Re-fit model" workflow opens.

It compares the OLD frozen model and backtest files (copied aside before the re-fit) with the NEW ones and writes
reports/refit_<year>.md:
  1. old vs. new score weights (3 / 6 / 12 months) and penalties;
  2. today's score and fans under the old and the new model (same inputs, same seed);
  3. change in backtest skill (score) and in accuracy and coverage (fans shown on the site);
  4. any target x horizon shown on the site that now FAILS the gate (bands within 10 points of 50% / 80%, and more
     accurate than no change);
  5. changes to the event list (a new event needs Troy's classification before the model is used).
  6. whether docs/model_card.md still matches the new files (tests/test_model_card.py; review X5).
Nothing here changes the site: the live run uses the newest frozen model on main, so only merging the pull request
does that.

Run it (the workflow does):
    python src/model/refit_summary.py <year> <folder with the old files>
The old folder holds model_old.json, score_results.csv, forecast_evaluation.csv and events.csv as they were before.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "model"))
import live as LV                                   # noqa: E402
from features import features_at                    # noqa: E402

MODEL = ROOT / "data" / "model"
SHOWN = [("ur", 3), ("ur", 6), ("ur", 12), ("cc", 13), ("cc", 26)]


def table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def today_under(fz: dict, asof: pd.Timestamp, x: dict) -> dict:
    p = {h: LV.probability(fz, x, h)[0] for h in (3, 6, 12)}
    probs = {"p6": p[6], "p3": min(p[3], p[6]), "p12": max(p[12], p[6])}
    rng = np.random.default_rng(LV.SEED)
    fans = {name: LV.fan(fz, name, x, probs, asof, rng) for name in fz["forecast"]["targets"]}
    return {"probs": probs, "fans": fans}


def main(year: int, old_dir: Path) -> None:
    old = json.loads((old_dir / "model_old.json").read_text(encoding="utf-8"))
    new = json.loads((MODEL / "frozen" / f"model_{year}.json").read_text(encoding="utf-8"))
    lines = [f"# Re-fit {year}: summary for review",
             "",
             f"Old model: {old['model_year']} (data known by {old['data_known_by']}). New model: {new['model_year']} "
             f"(data known by {new['data_known_by']}), frozen {new['frozen_at']}.",
             "Nothing on the site changes until this pull request is merged.", ""]

    # 1. weights
    lines += ["## 1. Score weights (standardized inputs; weights >= 0)", ""]
    feats = new["score"]["features"]
    for h in ("3", "6", "12"):
        o, n = old["score"]["horizons"][h], new["score"]["horizons"][h]
        rows = [[f, f"{o['weights'][f]:.3f}", f"{n['weights'][f]:.3f}", f"{n['weights'][f] - o['weights'][f]:+.3f}"]
                for f in feats]
        rows.append(["intercept", f"{o['intercept']:.3f}", f"{n['intercept']:.3f}", f"{n['intercept'] - o['intercept']:+.3f}"])
        rows.append(["penalty C", o["C"], n["C"], ""])
        rows.append(["training months", o["train_months"], n["train_months"], n["train_months"] - o["train_months"]])
        lines += [f"**{h}-month model**", "", table(["Input", "Old", "New", "Change"], rows), ""]

    # 2. today's score and fans under each model
    asof = pd.Timestamp.today().normalize()
    x = features_at(asof)
    t_old, t_new = today_under(old, asof, x), today_under(new, asof, x)
    lines += [f"## 2. Today ({asof:%Y-%m-%d}) under the old and the new model (same inputs, same seed)", ""]
    rows = [[f"Score, {h} months", f"{t_old['probs'][f'p{h}']:.1%}", f"{t_new['probs'][f'p{h}']:.1%}"] for h in (3, 6, 12)]
    for name in t_new["fans"]:
        for ho, hn in zip(t_old["fans"][name]["horizons"], t_new["fans"][name]["horizons"]):
            rows.append([f"{name} {hn['horizon']}: middle (80% range)",
                         f"{ho['median']:.2f} ({ho['q10']:.2f}-{ho['q90']:.2f})",
                         f"{hn['median']:.2f} ({hn['q10']:.2f}-{hn['q90']:.2f})"])
    lines += [table(["", "Old model", "New model"], rows), ""]

    # 3. backtest changes
    lines += ["## 3. Backtest (2000 on): old vs. new", ""]
    so, sn = pd.read_csv(old_dir / "score_results.csv"), pd.read_csv(MODEL / "score_results.csv")
    pick = lambda d: d[(d.run == "final") & (d.model == "logit")].iloc[0]
    a, b = pick(so), pick(sn)
    rows = [[k, a[k], b[k]] for k in ("months_scored", "skill_vs_base", "amber_real", "amber_false", "red_real", "red_false")]
    rows = [[r[0], f"{r[1]:.3f}" if isinstance(r[1], float) else r[1], f"{r[2]:.3f}" if isinstance(r[2], float) else r[2]]
            for r in rows]
    lines += ["**Score**", "", table(["Measure", "Old", "New"], rows), ""]
    fo, fn = pd.read_csv(old_dir / "forecast_evaluation.csv"), pd.read_csv(MODEL / "forecast_evaluation.csv")
    sel = lambda d, t, h: d[(d.target == t) & (d.horizon == h) & (d.subset == "2000-on excl. 2020")].iloc[0]
    rows, failing = [], []
    for t, h in SHOWN:
        o, n = sel(fo, t, h), sel(fn, t, h)
        ok = abs(n.cover50 - 0.5) <= 0.10 and abs(n.cover80 - 0.8) <= 0.10 and n.rmse_ratio < 1
        if not ok:
            failing.append(f"{t} {h}")
        rows.append([f"{t} {h}", f"{o.rmse_ratio:.3f} -> {n.rmse_ratio:.3f}", f"{o.cover50:.0%} -> {n.cover50:.0%}",
                     f"{o.cover80:.0%} -> {n.cover80:.0%}", "pass" if ok else "**FAIL**"])
    lines += ["**Fans shown on the site**", "",
              table(["Target, horizon", "Error vs. no change", "Inside 50% range", "Inside 80% range", "Gate (new)"], rows), ""]

    # 4. gate
    lines += ["## 4. Gate", "",
              ("**Failing now: " + ", ".join(failing) + ".** These should be hidden on the site before merging."
               if failing else "Every target and horizon shown on the site still passes."), ""]

    # 5. events
    eo = pd.read_csv(old_dir / "events.csv", dtype=str)
    en = pd.read_csv(MODEL / "events.csv", dtype=str)
    cols = ["event", "start_month", "end_month", "classification"]
    m = eo[cols].merge(en[cols], on="event", how="outer", suffixes=("_old", "_new"), indicator=True)
    changed = m[(m._merge != "both") | (m.start_month_old != m.start_month_new) | (m.end_month_old != m.end_month_new)
                | (m.classification_old != m.classification_new)]
    lines += ["## 5. Event list", ""]
    if changed.empty:
        lines += ["No change to the event list.", ""]
    else:
        lines += ["**The event list changed. A new event needs Troy's classification (config/event_notes.csv) before "
                  "this re-fit is used.**", "",
                  table(["Event", "Old start / end / type", "New start / end / type"],
                        [[r.event, f"{r.start_month_old} / {r.end_month_old} / {r.classification_old}",
                          f"{r.start_month_new} / {r.end_month_new} / {r.classification_new}"]
                         for r in changed.itertuples()]), ""]
    lines += ["## 6. Model card", ""] + model_card_check()
    out = ROOT / "reports" / f"refit_{year}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nWrote {out.relative_to(ROOT)}")


def model_card_check() -> list[str]:
    """Run tests/test_model_card.py against the new files. A mismatch must be fixed in this pull request: the weekday
    refresh runs the unit tests before its model step, so a stale card would stop the live updates after the merge."""
    import io
    import unittest
    sys.path.insert(0, str(ROOT / "tests"))
    import test_model_card
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(
        unittest.defaultTestLoader.loadTestsFromModule(test_model_card))
    problems = [str(err).strip().splitlines()[-1] for _, err in result.failures + result.errors]
    if not problems:
        return ["docs/model_card.md matches the new files.", ""]
    return (["**docs/model_card.md no longer matches the new files. Update the card (numbers, version line and its "
             "\"What changed\" table) in this pull request before merging, or the weekday refresh will fail its "
             "unit tests and skip the model step.**", ""] + [f"- {x}" for x in problems] + [""])


if __name__ == "__main__":
    main(int(sys.argv[1]), Path(sys.argv[2]))
