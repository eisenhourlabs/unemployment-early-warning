"""
Backtest of the Layer 1 triggers against the signed-off event list (decisions 2026-11-08, stage 3b).

Definitions:
  Episode     A run of months in which a trigger is at least amber (or, for the red view, red), with gaps of
              up to 2 months bridged so flicker doesn't count twice.
  Warning     An episode WARNS an event if it starts in the 12 months before the event's start (or in the
              start month itself) AND is still on within 3 months of the start (LIVE; no credit for a blip
              that switched off long before). Lead = months from the episode's start to the event's start.
              If none started in that window, the lead table says why: "late +k" (first on k months after
              the start), "on since YYYY-MM" (already on, from an episode older than the window), "none",
              or "n/a" (no data yet). The yield curve is also shown with a 24-month window.
  Outcome     Episodes whose 12-month window runs past the last month of data are "too recent to judge" and
              not scored. Otherwise each episode that starts outside an event is a HIT if an event (recession, early signal or 2020)
              starts within the next 12 months while the episode is live (as above), "followed by a scare" if only a scare does, otherwise a
              FALSE ALARM. Episodes that start during an event are not scored.
  Adds        A trigger ADDS WARNING for an event if its amber lead is at least 1 month longer than the best
              amber lead of the baseline triggers (Sahm + the three claims triggers; for a baseline trigger,
              the other three), or it warns when they don't. Judged on the 7 recessions used for fitting and
              the early signal (#7).
  Flag        drop candidate = adds warning in none of the events it can be tested on;
              weak = adds in only one, or (amber) more false alarms than hits. Nothing is dropped here.

Both overall-status rules (new: "overall"; plan: "overall_old") are scored like triggers, and compared side
by side in data/model/status_comparison.csv (months in each color, leads, false alarms, longest amber runs).

Writes data/model/trigger_episodes.csv, trigger_leads.csv, trigger_summary.csv, status_comparison.csv and
prints the tables used in docs/model.md section 4.

Run it (after triggers.py and events.py):
    python src/model/backtest_triggers.py
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "data" / "model"
CONFIG = ROOT / "config" / "triggers.csv"

WINDOW = 12            # months before an event start in which an episode counts as a warning
YIELD_WINDOW = 24      # extra view for the yield curve (known to lead by more than a year)
BRIDGE = 2             # off-months bridged inside an episode
LIVE = 3               # an episode must still be on within this many months before the event start to count
BASELINE = ["sahm", "claims_vs_low", "claims_yoy", "cont_claims_yoy"]
LEVELS = {"amber": ["amber", "red"], "red": ["red"]}
# The two overall-status versions in triggers_monthly.csv, scored like triggers.
STATUS = {"overall": "Overall status (new rule)", "overall_old": "Overall status (plan rule)"}
RUN_WINDOWS = {"2006-08": ("2006-01-01", "2008-12-01"), "2022-25": ("2022-01-01", "2025-12-01")}


def months_between(a, b) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def episodes(on: pd.Series, available: pd.Series) -> list[tuple]:
    """[(start, end)] runs of True in `on`, bridging up to BRIDGE off-months between on-months."""
    runs, start, last_on, gap = [], None, None, 0
    for month, is_on in on.items():
        if is_on:
            if start is None:
                start = month
            last_on, gap = month, 0
        elif start is not None:
            gap += 1
            if gap > BRIDGE or not available[month]:
                runs.append((start, last_on))
                start = None
    if start is not None:
        runs.append((start, last_on))
    return runs


def load():
    trig = pd.read_csv(MODEL / "triggers_monthly.csv", parse_dates=["month"], keep_default_na=False)
    trig = trig.set_index("month")
    ev = pd.read_csv(MODEL / "events.csv", dtype={"start_month": str, "end_month": str})
    ev["start"] = pd.to_datetime(ev.start_month + "-01")
    last = trig.index[-1]
    ev["end"] = [pd.Timestamp(e + "-01") if e != "ongoing" else last for e in ev.end_month]
    ev["group"] = ev.classification.map({"recession": "recession", "early signal": "early signal",
                                         "scare": "scare", "recession (pandemic)": "2020"})
    cfg = pd.read_csv(CONFIG).set_index("trigger_id").sort_values("order")
    return trig, ev, cfg


def in_event(month, ev) -> bool:
    """True if `month` falls inside an event after its start month (the start month itself is not 'inside')."""
    return bool(((ev.start < month) & (month <= ev.end)).any())


def live(episode_end, event_start) -> bool:
    """Was the episode still on at, or within LIVE months before, the event start? (No credit for a
    blip that switched off long before.)"""
    return episode_end >= event_start - pd.DateOffset(months=LIVE)


def lead_for(event, eps, on, available, window):
    """Lead text and number for one trigger-level and one event."""
    S = event.start
    starts = [s for s, e in eps if S - pd.DateOffset(months=window) <= s <= S and live(e, S)]
    if starts:
        k = months_between(min(starts), S)
        return str(k), k
    if not available.get(S, False):
        return "n/a", None
    for s, e in eps:                                   # already on, from an older episode?
        if s < S <= e + pd.DateOffset(months=BRIDGE):
            return f"on since {s:%Y-%m}", None
    after = on[(on.index > S) & (on.index <= S + pd.DateOffset(months=12))]
    if after.any():
        return f"late +{months_between(S, after.idxmax())}", None
    return "none", None


def main() -> None:
    trig, ev, cfg = load()
    trigger_ids = list(cfg.index) + list(STATUS)
    names = {**dict(cfg.name), **STATUS}

    episode_rows, lead_rows = [], []
    for tid in trigger_ids:
        color = trig[f"{tid}_color"] if tid not in STATUS else trig[tid]
        available = color != ""
        basis = trig[f"{tid}_basis"] if tid not in STATUS else pd.Series("mixed", index=trig.index)
        for level, colors in LEVELS.items():
            on = color.isin(colors)
            eps = episodes(on, available)
            # Score each episode.
            for s, e in eps:
                if in_event(s, ev):
                    outcome, ev_no = "during event", None
                else:
                    nxt = ev[(ev.start >= s) & (ev.start <= s + pd.DateOffset(months=WINDOW))
                             & ev.start.apply(lambda S, e=e: live(e, S))]
                    real = nxt[nxt.group != "scare"]
                    if len(real):
                        outcome, ev_no = f"hit ({real.iloc[0].group})", int(real.iloc[0].event)
                    elif len(nxt):
                        outcome, ev_no = "followed by scare", int(nxt.iloc[0].event)
                    elif s + pd.DateOffset(months=WINDOW) > trig.index[-1]:
                        # Its 12-month window isn't over yet: an event could still follow. Not scored.
                        outcome, ev_no = "too recent to judge", None
                    else:
                        outcome, ev_no = "false alarm", None
                episode_rows.append({"trigger": tid, "level": level, "start": f"{s:%Y-%m}", "end": f"{e:%Y-%m}",
                                     "months": months_between(s, e) + 1, "basis_at_start": basis[s],
                                     "outcome": outcome, "event": ev_no})
            # Lead for each event.
            windows = [WINDOW] + ([YIELD_WINDOW] if tid == "yield_curve" else [])
            for w in windows:
                for event in ev.itertuples():
                    text, k = lead_for(event, eps, on, available, w)
                    lead_rows.append({"trigger": tid, "level": level, "window": w, "event": event.event,
                                      "start_month": event.start_month, "group": event.group,
                                      "lead": text, "lead_months": k,
                                      "basis": basis.get(event.start, "") if tid not in STATUS else "mixed"})

    episodes_df = pd.DataFrame(episode_rows)
    leads = pd.DataFrame(lead_rows)

    # "Adds warning" (amber, 12-month window) on the 7 fitting recessions + the early signal.
    amber = leads[(leads.level == "amber") & (leads.window == WINDOW)]
    judged = ev[ev.group.isin(["recession", "early signal"])].event.tolist()
    adds = {}
    for tid in cfg.index:
        others = [b for b in BASELINE if b != tid]
        count, testable, extra = 0, 0, []
        for e in judged:
            row = amber[(amber.trigger == tid) & (amber.event == e)].iloc[0]
            if row.lead == "n/a":
                continue
            testable += 1
            base = amber[(amber.trigger.isin(others)) & (amber.event == e)].lead_months.dropna()
            best = base.max() if len(base) else None
            if pd.notna(row.lead_months) and (best is None or row.lead_months >= best + 1):
                count += 1
                extra.append(f"#{e} +{int(row.lead_months - best) if best is not None else 'only'}")
        adds[tid] = (count, testable, "; ".join(extra))

    # Summary per trigger and level.
    summary = []
    for tid in trigger_ids:
        color = trig[f"{tid}_color"] if tid not in STATUS else trig[tid]
        years = (color != "").sum() / 12
        for level in LEVELS:
            L = leads[(leads.trigger == tid) & (leads.level == level) & (leads.window == WINDOW)]
            E = episodes_df[(episodes_df.trigger == tid) & (episodes_df.level == level)]
            rec = L[L.group == "recession"]
            rec_testable = rec[rec.lead != "n/a"]
            warned = rec_testable.lead_months.dropna()
            row = {
                "trigger": tid, "name": names[tid], "level": level,
                "years_with_data": round(years, 1),
                "recessions_warned": f"{len(warned)} of {len(rec_testable)}",
                "median_lead_months": warned.median() if len(warned) else None,
                "leads_by_recession": ", ".join(f"#{r.event}:{r.lead}" for r in rec.itertuples()),
                "early_signal_7": L[L.group == "early signal"].lead.iloc[0],
                "scares_warned": f"{L[L.group == 'scare'].lead_months.notna().sum()} of "
                                 f"{(L[L.group == 'scare'].lead != 'n/a').sum()}",
                "pandemic_2020": L[L.group == "2020"].lead.iloc[0],
                "episodes": len(E[~E.outcome.isin(["during event", "too recent to judge"])]),
                "too_recent": int((E.outcome == "too recent to judge").sum()),
                "hits": int(E.outcome.str.startswith("hit").sum()),
                "followed_by_scare": int((E.outcome == "followed by scare").sum()),
                "false_alarms": int((E.outcome == "false alarm").sum()),
                "false_alarms_per_decade": round(10 * (E.outcome == "false alarm").sum() / years, 1) if years else None,
            }
            if tid not in STATUS and level == "amber":
                c, t, extra = adds[tid]
                row["adds_warning"] = f"{c} of {t}"
                row["adds_detail"] = extra
                if t == 0:
                    row["flag"] = "untestable"
                elif c == 0:
                    row["flag"] = "drop candidate"
                elif c == 1 or row["false_alarms"] > row["hits"]:
                    row["flag"] = "weak"
                else:
                    row["flag"] = "keep"
            summary.append(row)
    summary = pd.DataFrame(summary)

    # Side-by-side comparison of the two overall-status rules.
    rec_events = ev[ev.group == "recession"]
    comp = []
    for tid, label in STATUS.items():
        status = trig[tid]
        share = status.value_counts()
        row = {"rule": label, "column": tid}
        for c in ["green", "amber", "red"]:
            row[f"months_{c}"] = int(share.get(c, 0))
            row[f"pct_{c}"] = round(100 * share.get(c, 0) / len(status), 1)
        for level in LEVELS:
            L = leads[(leads.trigger == tid) & (leads.level == level) & (leads.window == WINDOW)]
            for r in rec_events.itertuples():
                row[f"{level}_lead_#{r.event}"] = L[L.event == r.event].lead.iloc[0]
            row[f"{level}_lead_#7_early_signal"] = L[L.event == 7].lead.iloc[0]
            row[f"{level}_lead_#13_2020"] = L[L.event == 13].lead.iloc[0]
            E = episodes_df[(episodes_df.trigger == tid) & (episodes_df.level == level)]
            row[f"{level}_hits"] = int(E.outcome.str.startswith("hit").sum())
            row[f"{level}_followed_by_scare"] = int((E.outcome == "followed by scare").sum())
            row[f"{level}_false_alarms"] = int((E.outcome == "false alarm").sum())
            row[f"{level}_false_alarm_starts"] = ", ".join(E[E.outcome == "false alarm"].start)
        # Continuous runs of AMBER months (amber exactly, not red).
        runs, start = [], None
        for m, c in status.items():
            if c == "amber" and start is None:
                start = m
            if c != "amber" and start is not None:
                runs.append((start, prev)); start = None
            prev = m
        if start is not None:
            runs.append((start, prev))
        length = lambda r: months_between(r[0], r[1]) + 1
        longest = max(runs, key=length)
        row["longest_amber_run"] = f"{length(longest)} months ({longest[0]:%Y-%m} to {longest[1]:%Y-%m})"
        for name, (a0, a1) in RUN_WINDOWS.items():
            inside = [r for r in runs if r[1] >= pd.Timestamp(a0) and r[0] <= pd.Timestamp(a1)]
            months_amber = int((status.loc[a0:a1] == "amber").sum())
            if inside:
                big = max(inside, key=length)
                row[f"amber_{name}"] = (f"longest run {length(big)} months ({big[0]:%Y-%m} to {big[1]:%Y-%m}); "
                                        f"{months_amber} amber months in {a0[:4]}-{a1[:4]}")
            else:
                row[f"amber_{name}"] = f"no amber; {months_amber} amber months"
        comp.append(row)
    comparison = pd.DataFrame(comp).set_index("rule").T
    comparison.to_csv(MODEL / "status_comparison.csv")

    episodes_df.to_csv(MODEL / "trigger_episodes.csv", index=False)
    leads.to_csv(MODEL / "trigger_leads.csv", index=False)
    summary.to_csv(MODEL / "trigger_summary.csv", index=False)

    pd.set_option("display.width", 300)
    pd.set_option("display.max_colwidth", 120)
    print(summary.drop(columns=["name"]).to_string(index=False))
    print()
    wide = leads[leads.window == WINDOW].pivot_table(index=["trigger", "level"], columns="event",
                                                     values="lead", aggfunc="first")
    print(wide.reindex(trigger_ids, level=0).to_string())
    print()
    print(comparison.to_string())
    print()
    y24 = leads[(leads.trigger == "yield_curve") & (leads.window == YIELD_WINDOW)]
    print("Yield curve, 24-month window:", ", ".join(f"#{r.event}:{r.level[0]}:{r.lead}" for r in y24.itertuples()))


if __name__ == "__main__":
    main()
