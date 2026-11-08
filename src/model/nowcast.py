"""
Stage 3d, B5: nowcast of the next unemployment-rate release from weekly claims.

The household survey measures unemployment in the REFERENCE WEEK (the Sunday-Saturday week containing the 12th).
For each month M, just before its release, the nowcast is:
    previous published rate + a * months since that release + b * change in log SA initial claims
                            + c * change in log SA continuing claims,
both claims changes measured between the reference week of M and the reference week of the previous published
month. a, b, c come from an ordinary regression on all earlier months (from 1968), re-estimated for every release.
Compared with no-change (the previous published rate). The target is the FIRST release of M (ALFRED), which is
what readers see on release day.

Missing releases: October 2025 was never published. The November 2025 release followed September's, so its
change spans two months; the "months since" term and the two-month claims changes handle that.

Writes data/model/nowcast.csv.  Run it:  python src/model/nowcast.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "model"))
from realtime import _alfred, as_known_on    # noqa: E402

MODEL = ROOT / "data" / "model"


def reference_saturday(month: pd.Timestamp) -> pd.Timestamp:
    """Saturday ending the week (Sunday-Saturday) that contains the 12th."""
    d12 = month + pd.Timedelta(days=11)
    return d12 + pd.Timedelta(days=(5 - d12.weekday()) % 7)


def main() -> None:
    a = _alfred("UNRATE")
    first = a.sort_values("realtime_start").groupby("date").first()           # first release of each month
    first = first[first.index >= "1968-01-01"]
    w = pd.read_csv(MODEL / "claims_weekly.csv", parse_dates=["week_ended"]).set_index("week_ended")
    rows = []
    for month, r in first.iterrows():
        m = pd.Timestamp(month)
        released = pd.Timestamp(r.realtime_start)
        prior = as_known_on("UNRATE", released - pd.Timedelta(days=1)).dropna()
        prior = prior[prior.index < m]
        if len(prior) == 0 or pd.isna(r.value):
            continue
        p_month, p_val = prior.index[-1], prior.iloc[-1]
        sat_m, sat_p = reference_saturday(m), reference_saturday(p_month)
        if sat_m not in w.index or sat_p not in w.index:
            continue
        rows.append({"month": m, "released": released, "prior_month": p_month, "prior_value": p_val,
                     "first_release": r.value,
                     "months_since": (m.year - p_month.year) * 12 + m.month - p_month.month,
                     "d_log_initial": np.log(w.ICSA[sat_m] / w.ICSA[sat_p]),
                     "d_log_continuing": np.log(w.CCSA[sat_m] / w.CCSA[sat_p]),
                     "reference_week": sat_m})
    df = pd.DataFrame(rows).set_index("month")
    df["change"] = df.first_release - df.prior_value
    X = ["months_since", "d_log_initial", "d_log_continuing"]
    preds = []
    for m in df.index[df.index >= "2000-01-01"]:
        train = df[(df.released < df.loc[m, "released"]) & (df.index < m)]
        train = train[~((train.index >= "2020-03-01") & (train.index <= "2020-12-01"))]   # 2020 not fitted
        model = LinearRegression(fit_intercept=False).fit(train[X], train.change)
        preds.append((m, df.loc[m, "prior_value"] + model.predict(df.loc[[m], X])[0]))
    df["nowcast"] = pd.Series(dict(preds))
    df["nowcast_rounded"] = df.nowcast.round(1)                     # BLS publishes one decimal
    test = df[df.nowcast.notna()].copy()
    test["err_nowcast"] = test.first_release - test.nowcast
    test["err_no_change"] = test.first_release - test.prior_value
    test.to_csv(MODEL / "nowcast.csv", date_format="%Y-%m-%d", index_label="month")

    covid = (test.index >= "2020-03-01") & (test.index <= "2020-12-01")
    for label, t in [("2000-on excl. Mar-Dec 2020", test[~covid]), ("Mar-Dec 2020", test[covid])]:
        rm, r0 = np.sqrt((t.err_nowcast ** 2).mean()), np.sqrt((t.err_no_change ** 2).mean())
        hit = (t.nowcast_rounded == t.first_release).mean()
        hit0 = (t.prior_value == t.first_release).mean()
        print(f"{label}: {len(t)} releases; RMSE nowcast {rm:.3f} vs no-change {r0:.3f} (ratio {rm / r0:.3f}); "
              f"MAE {t.err_nowcast.abs().mean():.3f} vs {t.err_no_change.abs().mean():.3f}; "
              f"exact to 0.1: {hit:.0%} vs {hit0:.0%}")
    print(test.loc["2025-06-01":, ["released", "prior_month", "prior_value", "months_since", "nowcast", "first_release"]].round(2).to_string())
    nxt = (df.index[-1] + pd.DateOffset(months=1))
    print(f"Next release: {nxt:%B %Y}; reference week ends {reference_saturday(nxt):%Y-%m-%d}; "
          f"initial claims for it are published the following Thursday, continuing claims a week later.")


if __name__ == "__main__":
    main()
