# Phase 3 model: method and results

This document grows with each Phase 3 stage (plan: `docs/phase3_plan.md`). Stage 3a covers the data
foundation and the event definition. Every number below is produced by the scripts in `src/model/`. Re-run them
to reproduce it.

## 1. Data

### Claims history (`src/model/build_claims_history.py` → `data/model/claims_weekly.csv`)

| Column | Source | From |
| --- | --- | --- |
| ICSA, CCSA (SA initial / continuing claims) | FRED | week ending 1967-01-07 |
| IC4WSA (SA initial claims, 4-week average) | FRED | 1967-01-28 |
| covered_employment, ic_rate_sa, cc_rate_sa | DOL national weekly report (ETA 539) | 1971-01-02 |
| pre_1978_coverage | flag: before the 1978 UI coverage expansion | – |

**Covered employment before 1995 / 1971.** The claims rates already go back to 1971, not 1995: the national ETA
539 report gives covered employment from the week ending 1971-01-02 (Phase 2 review change). Before that, DOL
does not publish it in the weekly claims data. A request to DOL's weekly claims report for 1967–1972 returns
claims from 1967 but a blank covered employment and insured unemployment rate for every week before 1971-01-02.
We did not construct a 1967–70 denominator (for example by interpolating annual figures), because the event's claims
leg uses claim levels, which go back to 1967. Rates before 1978 are not strictly comparable with later ones
(state and local government coverage added about 14% to covered employment in 1978–79).

### Real-time data (`src/model/alfred_fetcher.py`, `src/model/realtime.py`)

Revised monthly series are downloaded from ALFRED, FRED's archive of past vintages. Each row of
`data/model/alfred/<ID>.csv` is a value plus the period during which it was the published one (realtime_start to
realtime_end). `as_known_on(series_id, D)` returns the series exactly as it was published on date D. A month
not yet released by D is simply absent, so publication lags are respected without any assumptions.

| Series | Vintages | First vintage | Real-time for | First-release lag (median) |
| --- | --- | --- | --- | --- |
| UNRATE | 801 | 1960-03-15 | all events since 1967 | 34 days after the 1st of the month |
| PAYEMS | 861 | 1955-05-06 | all events | 35 days |
| AWHMAN | 780 | 1961-11-03 | all events | 34 days |
| PERMIT | 625 | 1999-08-17 | 2001 onward | 47 days |
| JTSLDR, JTSHIR | 195 | 2010-08-11 | **after 2008 only** | 68 days |
| TEMPHELPS | 190 | 2011-01-07 | **after 2008 only** | 34 days |

**Before a series' first vintage** (TEMPHELPS before 2011, JOLTS before 2010, PERMIT before 1999) there is no
real-time record. `as_known_on` then uses the earliest vintage, keeps only observations old enough to have been
published (`release_lag_days` in `config/model_series.csv`, set at the 95th percentile of ALFRED's actual first
releases; only the 2025 shutdown delays were longer), and marks the result `real_time = False`. **The 2001 and
2008 backtests therefore see revised values for temporary help and JOLTS.** Results that rely on them will say so.

**DOL claims stay current-vintage.** Initial and continuing claims (and their rates) use today's figures, cut
back by their release lag (initial claims 5 days after the week ends, continuing claims 12 days). This is our rule
(plan decision 5): their revisions are mostly re-estimated seasonal factors. FRED's archive of claims vintages
starts only in 2009. It will be used once, in a later stage, to measure and state how much the revisions matter.
It will not be used to drive the backtest.

**Check.** We rebuilt the real-time Sahm indicator from the UNRATE vintages and compared it with FRED's own
real-time series (SAHMREALTIME), 1960-04 to 2026-10 (798 months). 97.7% of months are identical to 0.01 point,
98.7% are within 0.05, and the largest difference is 0.20 (December 1981). The differences cluster in December and
January, when BLS revises five years of seasonal factors, so the two calculations pick slightly different
vintages around those releases. Run `python src/model/realtime.py` to repeat it.

## 2. The event definition (`src/model/events.py`)

Measured on **final (latest) data**, monthly, from January 1967.

- **Unemployment leg:** the unemployment rate's 3-month average is ≥ 0.5 point above the lowest 3-month
  average of the prior 12 months (months t−12 to t−1; the Sahm-rule shape). October 2025, which was not collected,
  is skipped: a 3-month average that includes it averages the other two months.
- **Claims leg:** the SA initial claims 4-week average (IC4WSA) is ≥ 25% above its lowest value of the prior 52
  weeks (not counting the current week). A month counts as "on" if any week ending in it is on. The leg can be
  tested from January 1968, once 52 weeks of history exist.
- **Start:** the first month either leg is on.
- **End:** once both legs have been off for **6 months in a row**. The end month is the last month a leg was on.
- **Minimum gap:** a new event cannot start until the previous one has ended. So two events are always at least
  7 months apart (6 quiet months, then a new trigger), and one downturn is not counted twice.
- **Peak rises:** the unemployment-rate peak is the highest monthly rate from the start to 12 months after the end
  (stopping 6 months before the next event starts), minus the lowest rate of the 12 months before the start. The
  claims peak is the highest IC4WSA in the same window, as a % above its lowest value in the 52 weeks before the start.
- **NBER link:** an event is linked to a recession if any NBER recession month (USREC) falls within the event or
  within 6 months either side. Otherwise it is a **scare**. "Start vs. NBER peak" is in months: negative means the
  event started before the peak.

## 3. Event list (signed off by Troy, 2026-11-08)

Full detail in `data/model/events.csv`. Chart: `reports/events.png` (events shaded, NBER recessions marked).

| # | Start | End | First leg | Other leg | Start vs. NBER peak | UR rise (pt) | Claims rise | NBER recession | Classification | Note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1970-01 | 1971-10 | claims | UR +2 mo | +1 | 2.7 | +92% | 1969-12 to 1970-11 | recession | GM strike (Sep–Nov 1970) inside the event |
| 2 | 1973-12 | 1976-01 | claims | UR +7 mo | +1 | 4.4 | +154% | 1973-11 to 1975-03 | recession | Oil embargo |
| 3 | 1977-02 | 1977-02 | claims | none | – | 0.2 | +36% | none | **scare** | Severe winter, natural-gas shortages closed plants |
| 4 | 1979-10 | 1981-04 | claims | UR +4 mo | −3 | 2.2 | +97% | 1980-01 to 1980-07 | recession | **Start overridden** from the rule's April 1979 (a one-month spike: Teamsters trucking strike, auto layoffs) |
| 5 | 1981-11 | 1983-06 | both | same month | +4 | 3.6 | +67% | 1981-07 to 1982-11 | recession | Deepest pre-2008 rise |
| 6 | 1984-11 | 1984-11 | claims | none | – | 0.2 | +25% | none | **scare** | One week at +25.1%; cause not identified |
| 7 | 1989-10 | 1990-02 | claims | none | −9 | 0.4 | +27% | 1990-07 to 1991-03 | **early signal** | Of the 1990–91 recession; then 7 quiet months before event 8 |
| 8 | 1990-10 | 1992-10 | both | same month | +3 | 2.6 | +49% | 1990-07 to 1991-03 | recession | Slow recovery |
| 9 | 2000-11 | 2002-11 | claims | UR +7 mo | −4 | 2.2 | +84% | 2001-03 to 2001-11 | recession | Claims led the NBER peak by 4 months |
| 10 | 2003-07 | 2003-08 | unemployment | none | – | 0.5 | +10% | none | **scare** | Late tail of the 2001 "jobless recovery" |
| 11 | 2005-10 | 2005-10 | claims | none | – | 0.1 | +27% | none | **scare** | Hurricanes Katrina and Rita |
| 12 | 2008-02 | 2010-05 | unemployment | claims +5 mo | +2 | 5.6 | +118% | 2007-12 to 2009-06 | recession | UR leg first; claims followed Jul 2008 |
| 13 | 2020-03 | 2021-03 | claims | UR +1 mo | +1 | 11.3 | +2,524% | 2020-02 to 2020-04 | recession (pandemic) | Pandemic. **Excluded from fitting** (decision 4) |
| 14 | 2023-06 | 2023-07 | claims | none | – | 0.5 | +27% | none | **scare** | Minnesota summer benefits for school workers; Ohio fraud |
| 15 | 2024-07 | 2024-09 | unemployment | none | – | 0.9 | +20% | none | **scare** | The mid-2024 Sahm-rule trigger. The unemployment rate rose 0.9 point and stayed elevated, which matters for claims even though it wasn't a recession |

"UR rise" is the peak minus the prior 12-month low. For #15 the peak is 4.4% in September 2025, inside the 12-month
search window after the event.

**What it says.** Every NBER recession since 1969 has an event. Starts range from 4 months before the NBER
peak to 4 months after (median: 1 month after); the early signal (#7) came 9 months before the 1990 peak. NBER announces its dates many months later, so the event still
beats the official call. The claims leg came first in 5 of the 8 recessions (1970, 1973, 1979, 2000, 2020). The
unemployment leg came first in 2008, and both legs came together in 1981 and 1990. There are **6 scares** (#3, 6, 10, 11, 14, 15): 6 false starts against 8 recession events
in 57 years. Four of the scares are single-shock claims spikes (weather, a hurricane, a law change and fraud,
and one unexplained week).

### Troy's rulings (2026-11-08)

Recorded in `config/event_notes.csv` (columns start_override and classification), applied by `events.py`.

1. **Scares count as events** for fitting the score (option A): all 6 stay in, so the score learns that some
   spikes fade. Only 2020 is excluded from fitting (decision 4).
2. **Event #4 starts in October 1979,** not at the rule's April 1979 strike spike. `events.csv` keeps the
   rule's start in `rule_start_month`; this is the only override.
3. **Event #7 (Oct 1989 – Feb 1990) is an early signal** of the 1990–91 recession, not a scare.
4. **Event #10 (mid-2003) is a scare.**

Result: 15 events, of which 8 are recessions (2020 is excluded from fitting), 1 is an early signal and 6 are scares.

### Sensitivity to the quiet period

| Quiet months | Events | What changes vs. 6 |
| --- | --- | --- |
| 3 | 16 | 1979 splits in two (April 1979 spike; new event from October 1979) |
| **6 (chosen)** | **15** | – |
| 12 | 11 | Merges 1979 with 1981–82, 1989 with 1990–91, 2000 with 2003, and 2023 with 2024. The 1981–82 and 1990–91 recessions would no longer start their own events, so 12 is too long |

The list is otherwise the same under all three, so the 6-month choice changes only the 1979 split.

## 4. Layer 1 triggers: backtest (stage 3b)

Scripts: `src/model/triggers.py` (monthly values and colors), `src/model/backtest_triggers.py` (leads, false alarms,
"adds warning"), `src/model/plot_triggers.py` (chart). Thresholds: `config/triggers.csv`. Outputs:
`data/model/triggers_monthly.csv`, `trigger_episodes.csv`, `trigger_leads.csv`, `trigger_summary.csv`;
chart `reports/layer1_status.png`.

### 4.1 How the triggers are computed

Each month is judged on **what had been published by its last day** (`as_known_on`). For example, the end-of-August 2024
Sahm value (0.53) uses the July unemployment rate released on August 2, and matches FRED's real-time Sahm series for July.

| # | Trigger | Amber | Red | Data and basis |
| --- | --- | --- | --- | --- |
| 1 | Sahm indicator | ≥ 0.30 pt | ≥ 0.50 pt | UNRATE vintages: **real-time** from 1967 |
| 2 | SA initial claims 4-wk avg vs. 52-week low | +15% | +25% | IC4WSA from Feb 1968, current-vintage (our rule), 5-day release lag |
| 3 | SA initial claims 4-wk avg vs. a year ago | +10% | +20% | as above |
| 4 | SA continued claims (4-wk avg) vs. a year ago | +10% | +20% | CCSA from Feb 1968, current-vintage, 12-day lag |
| 5 | Temp help jobs, 6-month change | < 0 | < −3% | TEMPHELPS from Aug 1990; real-time from 2011, **revised** before |
| 6 | Yield curve (10y − 3m, monthly average) | inverted 3+ months in a row | the 12 months after such an inversion ends | GS10 − TB3MS before 1982, T10Y3M from 1982; never revised, so **real-time** |
| 7 | Manufacturing surveys (Philly + Empire average) | below 0 for 3 months in a row | 3-month average below −15 | Philly from 1968, Empire added from Jul 2001; real-time from 2014–15, **revised** before |
| 8 | Financial conditions (NFCI) | above 0 | above 0.5 | NFCI first releases from 2011 (real-time); before that, the history as published in May 2011, from 1973 (**revised**) |

**Overall Layer 1 status.** Sections 4.1–4.6 use the plan's rule: red if any of triggers 1–4 is red; amber if two or
more triggers are amber or red; otherwise green. From 1967 to 2026 it was green 59% of months, amber 14% and red 27%
(the red months are mostly inside events). After review, Troy replaced it with a new rule and a smaller panel;
**see 4.8 for the new rule and the side-by-side comparison.**
**October 2026: all eight triggers green; overall green.**

**Yield-curve splice check.** For 1982–2026, where both exist, the official 10y − 3m spread averages 0.12 point below
GS10 − TB3MS (largest gap 0.80), and the two agree on whether the curve is inverted in 97.6% of months.

**NFCI is kept as first releases only.** The index is re-estimated every week, so its full vintage history would be
about 2 million rows. The trigger only needs the latest value known at each date, and that is the week's first
release. One example of why real-time matters: in late March 2020 the first-release NFCI was −0.17 (green). Today's
revised history shows that week as tighter.

### 4.2 How warning and false alarms are measured

- **Episode:** a run of months in which a trigger is at least amber (or, separately, red), with gaps of up to 2 months
  bridged so flicker doesn't count twice.
- **Warning:** an episode warns an event if it starts in the 12 months before the event's start (or in the start
  month) **and is still on within 3 months of the start**. Lead = months from the episode's start to the event's start.
  Otherwise the table says *late +k* (first on k months after the start), *on since YYYY-MM* (already on from an
  episode that began more than 12 months earlier), *none*, or *n/a* (no data yet).
- **Outcome of each episode** that starts outside an event: **hit** if a recession, the early signal or 2020 starts within
  12 months while the episode is live; **followed by a scare** if only a scare does; otherwise a **false alarm**.
- **Adds warning:** a trigger adds warning for an event if its amber lead is at least 1 month longer than the best
  amber lead among the baseline triggers (1–4; for a baseline trigger, the other three), or it warns when they don't.
  This is judged on the 7 recessions used for fitting plus the early signal (#7).
- **Too recent to judge:** an episode whose 12-month window runs past the last month of data is not scored (added in
  stage 3c; it moved Sahm's and the new rule's December 2025 amber from "false alarm" to "too recent").
- **Flags (nothing dropped):** *drop candidate* = adds warning in none of the events it can be tested on; *weak* = adds in
  only one, or (amber) has more false alarms than hits.

**One change from the plan we agreed:** the "still on within 3 months of the start" condition. Without it, a one-month
blip a year before an event counted as a 12-month warning. For example, initial claims vs. a year ago were amber for one
month in February 2007, then quiet for a year, yet that counted as a 12-month warning of the 2008 event. The condition
changed 37 of 300 lead cells.

### 4.3 Months of warning

Months before the event's start (0 = same month); 12-month window. \* = this trigger relied on revised (not real-time) data there.

**Amber:**

| Trigger | 1970 #1 | 1973 #2 | 1979 #4 | 1981 #5 | 1990 #8 | 2000 #9 | 2008 #12 | Early signal #7 | 2020 #13 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 Sahm | 3 | late +3 | late +5 | 0 | 0 | late +5 | 1 | late +12 | late +1 |
| 2 Claims vs. 52-wk low | 1 | 0 | 6 | 1 | 2 | 3 | late +1 | 4 | 3 |
| 3 Claims vs. year ago | 1 | 0 | 6 | 1 | 2 | 0 | late +1 | 0 | 0 |
| 4 Continued claims vs. year ago | 2 | late +1 | late +1 | late +1 | 12 | late +2 | 1 | 0 | late +1 |
| 5 Temp help | n/a | n/a | n/a | n/a | 1\* | 0\* | on since 2006-12\* | n/a | late +1 |
| 6 Yield curve | 0 | 4 | 8 | on since 1979-02 | on since 1989-08 | 2 | on since 2006-10 | 2 | 7 |
| 7 Manufacturing surveys | 0\* | late +3 | 4\* | late +1 | on since 1989-07 | late +3 | late +1 | 3\* | late +1 |
| 8 NFCI | n/a | 10\* | on since 1978-04\* | on since 1978-04\* | 1\* | late +1 | 6\* | on since 1987-04\* | none |
| **Overall status (plan rule)** | 2 | 4 | 8 | on since 1979-02 | on since 1989-06 | 0 | on since 2006-12 | 4 | 6 |

**Red:**

| Trigger | 1970 #1 | 1973 #2 | 1979 #4 | 1981 #5 | 1990 #8 | 2000 #9 | 2008 #12 | Early signal #7 | 2020 #13 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 Sahm | 2 | late +4 | late +7 | late +1 | late +2 | late +8 | late +3 | none | late +2 |
| 2 Claims vs. 52-wk low | 0 | 0 | 0 | late +1 | late +1 | 0 | late +5 | 0 | 0 |
| 3 Claims vs. year ago | 0 | late +1 | 0 | 0 | late +1 | late +1 | late +3 | 0 | 0 |
| 4 Continued claims vs. year ago | 0 | late +2 | late +6 | late +4 | late +1 | late +4 | late +3 | none | late +1 |
| 5 Temp help | n/a | n/a | n/a | n/a | late +6 | late +3 | late +3 | n/a | late +2 |
| 6 Yield curve | late +1 | late +7 | late +7 | 2 | on since 1989-09 | late +3 | 8 | 1 | 5 |
| 7 Manufacturing surveys | late +2 | late +10 | 1 | late +1 | 1 | late +3 | late +9 | late +5 | late +1 |
| 8 NFCI | n/a | 9 | 4 | on since 1979-06 | none | none | late +1 | none | none |
| **Overall status (plan rule)** | 2 | 0 | 0 | 0 | late +1 | 0 | late +3 | 0 | 0 |

**Scares, amber** (did the trigger "warn" of a spike that faded?):

| Trigger | 1977 #3 | 1984 #6 | 2003 #10 | 2005 #11 | 2023 #14 | 2024 #15 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 Sahm | 5 | none | 0 | none | late +5 | 3 |
| 2 Claims vs. 52-wk low | 0 | 2 | none | 1 | 3 | 1 |
| 3 Claims vs. year ago | 0 | late +3 | none | 1 | 0 | late +3 |
| 4 Continued claims vs. year ago | none | none | none | none | 2 | none |
| 5 Temp help | n/a | n/a | 8\* | none | 6 | on since 2022-12 |
| 6 Yield curve | none | none | none | late +12 | 5 | on since 2023-01 |
| 7 Manufacturing surveys | none | none | none | none | 11 | late +10 |
| 8 NFCI | none | 7\* | none | none | none | none |
| **Overall status (plan rule)** | 5 | 2 | none | 1 | 6 | on since 2022-12 |

**Yield curve with a 24-month window** (amber): 1970 0, 1973 4, 1979 8, 1981 on since 1979-02, 1990 **14**, 2000 2,
2008 **16**, early signal 2, 2020 7. The curve warned of every recession within two years. With the 12-month window it only
gets credit for four of the seven, because its lead is often longer than a year.

### 4.4 Summary per trigger

Hits, scares and false alarms count episodes that start outside events. False alarms per decade use the years with data.

| Trigger | Level | Recessions warned (≤ 12 mo) | Median lead | Hits | Followed by scare | False alarms | False alarms / decade | Adds warning (of 8) | Flag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 Sahm | amber | 4 of 7 | 0.5 | 4 | 3 | 3 | 0.5 | 1 (#1 +1) | weak |
|  | red | 1 of 7 | 2 | 1 | 1 | 0 | 0.0 | | |
| 2 Claims vs. 52-wk low | amber | 6 of 7 | 1.5 | 8 | 5 | 8 | 1.4 | 2 (#7 +4, #9 +3) | keep |
|  | red | 4 of 7 | 0 | 6 | 2 | 1 | 0.2 | | |
| 3 Claims vs. year ago | amber | 6 of 7 | 1 | 8 | 3 | 5 | 0.9 | 0 | **drop candidate** |
|  | red | 3 of 7 | 0 | 5 | 1 | 1 | 0.2 | | |
| 4 Continued claims vs. year ago | amber | 3 of 7 | 2 | 3 | 1 | 0 | 0.0 | 1 (#8 +10) | weak |
|  | red | 1 of 7 | 0 | 1 | 1 | 0 | 0.0 | | |
| 5 Temp help | amber | 2 of 3 | 0.5 | 2 | 1 | 5 | 1.4 | 0 (of 3) | **drop candidate** |
|  | red | 0 of 3 | – | 0 | 2 | 5 | 1.4 | | |
| 6 Yield curve | amber | 4 of 7 | 3 | 6 | 1 | 2 | 0.3 | 2 (#2 +4, #4 +2) | keep |
|  | red | 2 of 7 | 5 | 4 | 0 | 2 | 0.3 | | |
| 7 Manufacturing surveys | amber | 2 of 7 | 2 | 3 | 1 | 4 | 0.7 | 0 | **drop candidate** |
|  | red | 2 of 7 | 1 | 2 | 1 | 2 | 0.3 | | |
| 8 NFCI | amber | 3 of 6 | 6 | 3 | 1 | 3 | 0.6 | 2 of 7 (#2 +10\*, #12 +5\*) | keep (revised data only) |
|  | red | 2 of 6 | 6.5 | 2 | 0 | 5 | 0.9 | | |
| **Overall status (plan rule; new rule in 4.8)** | amber | 4 of 7 (the other 3 "on since") | 3 | 6 | 4 | 4 | 0.7 | | |
|  | red | 5 of 7 | 0 | 7 | 2 | 1 | 0.2 | | |

False alarms, by start month (amber unless noted): Sahm 1967-10, 1986-05, 2023-11 (2025-12 is too recent to judge); claims vs. 52-wk low
1969-07, 1972-07, 1973-08, 1976-09, 1995-07, 1995-11, 2006-05, 2017-09 (all 1–2 months long); claims vs. year ago 1985-02,
1994-02, 1995-09, 2007-02, 2024-10; temp help 1995-07, 2006-12, 2016-05, 2019-06, 2021-08; yield curve 1967-01, 2006-10;
manufacturing 1995-06, 2012-08, 2015-10, 2025-05; NFCI 1978-04, 1987-04, 1998-10. Overall amber: 1967-10, 1985-02, 1995-07,
2006-12. Overall red: 1979-04 (the trucking-strike spike; event #4's start was moved past it).

### 4.5 What it says

1. **Every recession found the overall status already amber or red at its start.** In three of them (1981, 1990, 2008)
   it had been amber for more than 12 months. Under our scoring that long run counts as a false alarm: the 2006-12
   episode began 16 months before the 2008 event. Measured within 12 months, overall amber gave a median of 3 months'
   warning. Overall red came at or before the start in 5 of 7 recessions (in the start month in four, 2 months
   early in 1970) and 1–3 months late in 1990 and 2008.
2. **The claims triggers give the earliest dependable warning, but it is short.** Trigger 2 at amber warned of 6 of the 7
   recessions with a median lead of 1.5 months, and of the early signal by 4 months. Its 8 false alarms are all one- or
   two-month blips. Red on trigger 2 *is* the event's claims leg, so its red "lead" is 0 by construction.
3. **The Sahm indicator mostly comes late in real time** (amber late in 3 of 7, red late in 6 of 7). It adds warning only once.
   Its role on the dashboard is as the well-known confirmation, not as an early warning.
4. **The yield curve gives the longest warning,** but often more than 12 months ahead. It is also behind the long
   amber runs in 2006–08 and 2022–25. The 2022–24 inversion was followed only by scares (#14, #15).
5. **NFCI, the manufacturing surveys and temp help** add little, and **all of their warnings before 2011–15 rest on revised
   data**, so even the help NFCI appears to give (1973, 2008) has never been seen in real time. In 2020, NFCI's first
   releases stayed green.
6. **Against the plan's goal** of about one false amber per real one: overall amber had 6 hits, 4 false alarms and 4
   episodes followed by scares. That is close to the target if scares count as half-right, which is a fair reading given
   your decision that scares count as events.

### 4.6 Candidates to drop (flagged in stage 3b; Troy's decision is in 4.8)

| Trigger | Flag | Why | Points in its favor |
| --- | --- | --- | --- |
| 3 Claims vs. year ago | drop candidate | Never earlier than triggers 1, 2 and 4 | Catches slow grinds by design; often ties trigger 2 |
| 5 Temp help | drop candidate | No added warning in 3 testable recessions (all on revised data); 5 false alarms in 36 years, 3 of them real-time since 2016 | Only 3 recessions to test; plan lists it as a score candidate |
| 7 Manufacturing surveys | drop candidate | No added warning in 8; mostly late | Real-time only since 2014–15 |
| 1 Sahm | weak | Adds warning once (1970, +1 month) | The best-known rule; part of the event definition |
| 4 Continued claims vs. year ago | weak | Adds once (1990, +10); usually late | The severity (duration) side, which matters for IUI claim severity rather than frequency |

**Read these flags with care: they are fragile.** With 8 events to judge, one event moves a trigger between "keep",
"weak" and "drop candidate". Before the 3-month "still on" condition was added, Sahm and continued claims were drop
candidates, and claims vs. year ago, the yield curve and NFCI each changed by one event. Stage 3c will test the same
indicators out of sample in the score, which is the better test of whether they help.

### 4.7 Caveats

- Seven recessions (one more, 2020, shown separately) is a small sample. Every count above should be read with that in mind.
- Claims triggers use today's claims figures (our rule). Seasonal-factor revisions could move a borderline month. The
  effect will be measured with FRED's 2009+ claims vintages in stage 3c.
- Events are dated on final data and triggers on real-time data. A trigger can be "late +1" partly because the
  last week of the event's start month was published the following month (for example 1990-10, trigger 2 red).
- The 12-month window favors fast indicators. The 24-month view for the yield curve shows what a longer window would credit.

### 4.8 Stage 3b review: new panel and overall rule (Troy, 2026-11-08)

**Panel** (`config/triggers.csv`, column `layer1_role`):

| Role | Triggers | In the overall status? |
| --- | --- | --- |
| Core | 1 Sahm, 2 initial claims vs. 52-week low, 4 continued claims vs. a year ago | Yes |
| Panel | 6 yield curve ("long lead, often 12+ months"), 8 NFCI ("real-time only since 2011") | Yes, but only alongside a core trigger |
| Context | 5 temp help, 7 manufacturing surveys | No: shown on the Leading page as context (site change in stage 3e) |
| Removed | 3 initial claims vs. a year ago | No |

All eight are still computed and stay candidates for the stage 3c score.

**New overall rule:** red if trigger 1, 2 or 4 is red. Amber if at least one of triggers 1, 2 or 4 is amber or red AND at
least one other panel trigger (1, 2, 4, 6 or 8) is amber or red; in other words, two or more panel triggers on, with a
core one among them. Otherwise green. The yield curve and NFCI can no longer turn the status amber on their own, or
together without a core trigger.

**New rule vs. the plan's rule** (both computed every month; `data/model/status_comparison.csv`):

| | New rule | Plan rule (old) |
| --- | --- | --- |
| Months green / amber / red | 469 / 55 / 194 (65% / 8% / 27%) | 424 / 97 / 197 (59% / 14% / 27%) |
| Amber lead, 1970 #1 | 2 | 2 |
| Amber lead, 1973 #2 | 0 | 4 |
| Amber lead, 1979 #4 | 6 | 8 |
| Amber lead, 1981 #5 | 1 | on since 1979-02 |
| Amber lead, 1990 #8 | on since 1989-06 (the early signal's run) | on since 1989-06 |
| Amber lead, 2000 #9 | 0 | 0 |
| Amber lead, 2008 #12 | 1 | on since 2006-12 |
| Amber lead, early signal #7 / 2020 #13 | 4 / 3 | 4 / 6 |
| Red lead, recessions #1, #2, #4, #5, #8, #9, #12 | 2, 0, 0, late +1, late +1, 0, late +3 | 2, 0, 0, 0, late +1, 0, late +3 |
| Red lead, early signal #7 / 2020 #13 | 0 / 0 | 0 / 0 |
| Amber episodes: hits / followed by scare / false alarms | 8 / 3 / 2 (+1 too recent to judge) | 6 / 4 / 4 |
| Amber false alarms (start month) | 1967-10, 1973-08 (2025-12 too recent to judge) | 1967-10, 1985-02, 1995-07, 2006-12 |
| Red episodes: hits / followed by scare / false alarms | 6 / 2 / 1 | 7 / 2 / 1 |
| Red false alarm | 1979-04 (strike spike) | 1979-04 (strike spike) |
| Longest continuous amber run | 9 months (1990-02 to 1990-10) | 17 months (2024-11 to 2026-03) |
| Amber in 2006–08 | 4 amber months; longest run 4 (2008-01 to 2008-04) | 16 amber months; longest run 12 (2007-05 to 2008-04) |
| Amber in 2022–25 | 13 amber months; longest run 4 (2024-04 to 2024-07) | 27 amber months; longest run 17 (2024-11 to 2026-03) |

**What changed:**

1. **The long amber runs are gone.** In 2006–08 and 2022–25 the plan rule was amber mostly because the yield curve and temp
   help (and, in 2025–26, the yield curve's red re-steepening) were on together. Under the new rule those months are green
   unless a core trigger joins in. Amber time falls from 14% to 8% of months. The longest run is now 9 months, in 1990,
   leading into the 1990–91 recession.
2. **Warning is mostly kept.** Overall amber was on at or before the start of every recession under both rules. The new
   rule gives shorter measured leads where the plan rule's amber was driven by the yield curve (1973: 0 vs. 4; 1979: 6 vs. 8;
   2020: 3 vs. 6). In 1981 and 2008 the new rule's amber is a fresh 1-month warning instead of a run that began more than a
   year earlier.
3. **False alarms:** amber 2 vs. 4. The new rule's two are 1967-10 (Sahm + yield curve) and 1973-08 (a one-month claims blip
   with the yield curve inverted and NFCI red on revised data; the 1973 event followed 4 months later, after the blip had ended).
   A third amber episode, **2025-12 to 2026-02**, is too recent to judge: its 12-month window runs to December 2026. Sahm was
   amber at 0.30–0.43 (from November 2025's first print of 4.6%, not an artifact of the uncollected October; see the check in
   `docs/decisions.md`) while the yield curve was red from re-steepening after the 2022–24 inversion. Red false alarms are
   unchanged (1 each).
4. **Red is slightly later in 1981** (late +1 vs. 0), because trigger 3 (now removed) went red in the event's start month.
5. **Today (October 2026):** green under both rules.

**Caveat:** the new rule was chosen after looking at these same 7 recessions, so its record here is in-sample. Stage 3c's
out-of-sample test of the score is the fairer comparison.

## 5. The early-warning score (stage 3c)

Scripts: `src/model/features.py` (inputs), `src/model/score.py` (fit, out-of-sample test, sensitivity runs),
`src/model/plot_score.py` (charts). Outputs: `data/model/features_monthly.csv`, `score_oos.csv` (every month's
out-of-sample score, all models and runs), `score_results.csv`, `score_sensitivity.csv`, `score_reliability.csv`,
`score_thresholds.csv`, `score_coefficients.csv` (each yearly re-fit), `score_coefficients_nonneg.csv`,
`score_contributions.csv`; charts `reports/score_history.png` and `reports/score_reliability.png`.

**Note:** sections 5.2–5.7 and 5.9 describe the model **before** Troy's review (unconstrained weights). The
**final model and its results are in 5.10.**

### 5.1 Set-up

- **Target.** For each month t, judged at its last day, y = 1 if an event in `events.csv` starts in months t+1 to t+6.
  Scares and the early signal count as events (ruling of 2026-11-08).
- **Not used for fitting or for the Brier score:**
  - months while an event is in progress (start month included), because the score predicts starts;
  - the 2020 window, 2019-09 to 2021-03 (event #13), which is reported separately;
  - the last 6 months of data, whose outcome isn't known yet.
- **Inputs** (`features.py`): the eight trigger measures as continuous values, each signed so that higher = worse,
  each month seeing only what was published by its last day:
  - Sahm indicator; initial claims vs. 52-week low; initial claims vs. a year ago; continued claims vs. a year ago;
  - minus temp help's 6-month change;
  - minus the **lowest** 10y − 3m spread of the past 18 months ("recently inverted, and how deeply");
  - minus the 3-month average of the manufacturing surveys;
  - NFCI.

  Each is standardized with the training window's mean and standard deviation, capped at ±4, and set to 0 ("average, no
  information") before the series exists (temp help before 1990, NFCI before 1973).
- **Models:**
  - (a) **ridge logistic regression** (L2 penalty), with the penalty chosen by forward-chaining cross-validation inside
    each training window (5 time-ordered blocks, 6-month gap);
  - (b) **equal-weight index**: the average of the standardized inputs, turned into a probability by a one-variable
    logistic fit;
  - (c) **Layer 1 baseline**: the event rate per color of the overall status (new rule) in the training data, shrunk
    toward the base rate;
  - (d) **base rate**.
- **Out-of-sample test.** Re-fit every January using only months whose 6-month outcome was already known, then score that
  year. **2000–2026 is the test.** 1980–1999 is also run, as a "pseudo out-of-sample" check.
- **Amber threshold.** Chosen on pre-2000 data only: a model fitted on 1968–1999 gives in-sample scores, and the
  threshold is the one whose episodes come closest to one false amber per real warning. Episodes and outcomes follow
  Layer 1's rules: 12-month window, still on within 3 months of the start, too-recent episodes not scored. **Red = 50%.**
- **Sample.** By the 2026 re-fit: 490 usable months, 84 of them with y = 1, from 14 events (2020 excluded).
  Neighbouring months share the same 6-month windows, so the effective number of independent outcomes is far smaller.

### 5.2 Results, 2000–2026 (out of sample; before review)

236 scored months, 36 with y = 1.

| Model | Brier | Skill vs. base rate | Amber threshold | Amber: real / false | Red (50%): real / false |
| --- | --- | --- | --- | --- | --- |
| **(a) Ridge logistic (main)** | **0.114** | **+0.14** | 19% | 5 / 6 (+1 too recent) | 5 / 2 |
| (b) Equal-weight index | 0.115 | +0.12 | 15% | 3 / 8 | 4 / 1 |
| (c) Layer 1 baseline | 0.130 | +0.01 | 35% | 4 / 1 (+1 too recent) | 4 / 1 |
| (d) Base rate | 0.132 | 0 | – | – | – |
| Ridge logistic, pseudo out of sample 1980–1999 | 0.085 | +0.36 | 19% | 2 / 4 | 4 / 1 |

Brier = average squared error of the probability (lower is better). Skill = 1 − Brier / Brier of the base rate.

**Plan gate: passed.** Out of sample, the logistic score beats the Layer 1 baseline (+0.14 vs. +0.01) and the
equal-weight index (+0.12), so the fallback isn't needed. The margin over the equal-weight index is small.

### 5.3 Thresholds

- **Amber: 19%.** This came from the 1968–1999 fit at about one false amber per real warning, almost exactly the plan's
  starting 20%. The pseudo-out-of-sample 1980–1999 scores would have given 35%, but that rests on only 4 events.
- **After 2000, amber at 19%** gave 5 real warnings and 6 false ambers, plus one episode too recent to judge. That is 1.2
  false per real, close to your target.
- **Red: keep 50%.** After 2000 it gave 5 real warnings and 2 false reds. Months scored above 50% were followed by an event
  52% of the time (table in 5.5), which matches "more likely than not". Nothing argues for moving it.

### 5.4 Event by event since 2000

Main model; months of warning before the event's start (Layer 1 rules).

| Event | Type | Amber (19%) | Red (50%) |
| --- | --- | --- | --- |
| #9 2000-11 | recession | 5 | 3 |
| #10 2003-07 | scare | 3 | none |
| #11 2005-10 | scare (Katrina) | 1 | 1 |
| #12 2008-02 | recession | on since 2006-05 (21 months) | 4 |
| #13 2020-03 | pandemic, excluded from fitting | 4 | 0 |
| #14 2023-06 | scare | 10 | 3 |
| #15 2024-07 | scare | on since 2022-08 | on since 2023-03 |

- **False ambers:** 2006-05, 2011-08, 2012-11, 2017-09 (the Harvey / Irma hurricane claims), 2019-02, 2019-06.
  The 2026-06 episode is too recent to judge. **False reds:** 2006-11, 2017-09.
- **2020:** the score was 49% in December 2019 (the claims bump), back to 7% by February, and 96% at the end of March.
  The December reading was not a forecast of the pandemic.
- **What the episode counts hide:** after #15 ended (September 2024), the score was at or above 50% in 8 months and above
  amber in 17 months between October 2024 and October 2026 (peak 85% in June 2025), and no event has started. These months
  count against the Brier score, but they don't show up as false alarms, because they bridge into the long run that began
  in 2022–23. **Today (October 2026): 2.4% (green).**

### 5.5 Calibration (`reports/score_reliability.png`)

| Predicted band | Months | Average predicted | Share followed by an event start |
| --- | --- | --- | --- |
| 0–5% | 85 | 2.6% | 2.4% |
| 5–10% | 53 | 7.2% | 7.5% |
| 10–20% | 36 | 15.2% | 19.4% |
| 20–35% | 21 | 27.9% | 23.8% |
| 35–50% | 12 | 41.7% | 25.0% |
| 50–100% | 29 | 70.3% | 51.7% |

Well calibrated below 35%. **Above 35% it is overconfident:** 70% predicted against 52% observed. A score of 80% should be read
as "more likely than not", not as 4 in 5. The constrained version (5.6) is similar (76% predicted vs. 56% observed).

### 5.6 Sensitivity runs

| Run (logistic) | Months scored | Brier | Base-rate Brier | Skill | Amber thr. | Amber real / false | Red real / false |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Main**, 2000– | 236 | 0.114 | 0.132 | **+0.14** | 19% | 5 / 6 | 5 / 2 |
| Shock scares #3, #6, #11, #14 **not** events, 2000– | 239 | 0.114 | 0.093 | **−0.23** | 8% | 1 / 7 | 3 / 2 |
| Without temp help, 2000– | 236 | 0.112 | 0.132 | +0.15 | 21% | 5 / 4 | 6 / 2 |
| Fit from 2001, without JOLTS, tested 2008– | 168 | 0.0752 | 0.091 | +0.17 | 19% | 3 / 3 | 1 / 1 |
| Fit from 2001, **with JOLTS**, tested 2008– (indicative) | 168 | 0.0752 | 0.091 | +0.17 | 19% | 3 / 3 | 1 / 1 |
| Main, scored 2010– (today's claims figures) | 167 | 0.068 | 0.083 | +0.18 | 19% | 2 / 5 | 2 / 1 |
| **Claims as published at the time** (FRED vintages), 2010– | 167 | 0.095 | 0.083 | **−0.15** | 19% | 1 / 9 | 2 / 0 |
| Main, 2010– without 2022–23 | 145 | 0.053 | 0.063 | +0.16 | 19% | 2 / 5 | 2 / 1 |
| Claims vintages, 2010– without 2022–23 | 145 | 0.054 | 0.063 | +0.13 | 19% | 1 / 9 | 2 / 0 |
| **Coefficients constrained ≥ 0** (extra run, see below) | 236 | **0.108** | 0.132 | **+0.18** | 20% | 5 / 4 | 5 / 2 |

What they say:

1. **Shock scares.** With the four one-off shocks not counted as events, the score is *worse* than a constant base rate
   after 2000 (−0.23). Since 2000 the only recessions available to the test are 2001 and 2008 (2020 is excluded). Much of
   the score's measurable skill comes from anticipating claims-led scares, which it does because claims are its strongest
   input. Counting scares as events (your ruling) is what makes the score useful here. The flip side: it is as much a
   "claims-jump" detector as a recession detector, which suits IUI claim frequency.
2. **Temp help.** Dropping it improves the score slightly (+0.15 vs. +0.14; 4 false ambers instead of 6). The difference
   is within noise. Its weight changed sign over the years (from −0.50 to +0.85), and before 2011 it rests on revised data.
   Today it is the largest upward contribution (see 5.7).
3. **JOLTS adds nothing.** With a 2001-onward fit the penalty sets its weight to about zero, and the Brier is identical to
   four decimals. That is a test on one recession (2008), so it is indicative only.
4. **Claims revisions matter, mostly in 2022.** With claims as published at the time, the score goes from +0.18 to
   −0.15 for 2010 onward. Almost all of that is mid-2022: initial claims as first published rose 36–46% above their
   March 2022 low, while today's revised figures show 2–6%. The real-time score would have sat at 71–97% from June 2022 to
   January 2023, a false red that today's numbers hide. The Layer 1 claims trigger would also have been red.
   - Average absolute score difference: 0.06; largest 0.76 (July 2022).
   - Without 2022–23 the gap is small (+0.16 vs. +0.13), but the vintage run has more false ambers (9 vs. 5), so smaller
     revisions add noise too.
   - **Our backtest is optimistic about real-time performance, especially around unusual seasonal patterns.**
5. **Coefficients constrained ≥ 0.** This run is not in your list; I added it because of what the main fit does.
   - **Problem with the main fit:** continued claims gets a negative weight in every re-fit since 1985 (−0.08 to −0.51).
     It moves with the stronger initial-claims measures, and its rises mostly happen inside events, which are excluded.
     That makes the contributions misleading ("continued claims rising lowers the risk").
   - **What the constraint does:** requiring every weight to be zero or positive, as the inputs are signed, sets continued
     claims, initial claims vs. a year ago and the yield curve to 0 today.
   - **Result:** a better score (+0.18 vs. +0.14), fewer false ambers (4 vs. 6) and the same warnings, except #14's amber
     at 7 months instead of 10 and 2020's red at 3 months instead of 0.

### 5.7 What drives the latest score (October 2026)

Main model as re-fitted in January 2026 (C = 0.3). Contribution = weight × standardized value, in log-odds. Positive
pushes the score up.

| Input | Value | Standardized | Weight | Contribution | Weight (≥ 0) | Contribution (≥ 0) |
| --- | --- | --- | --- | --- | --- | --- |
| Sahm indicator | 0.00 | −0.15 | 0.48 | −0.07 | 0.46 | −0.07 |
| Initial claims vs. 52-wk low | −0.5% | −1.03 | 1.06 | **−1.10** | 1.07 | **−1.10** |
| Initial claims vs. a year ago | −13.1% | −0.34 | 0.09 | −0.03 | 0 | 0 |
| Continued claims vs. a year ago | −11.9% | −0.12 | −0.20 | +0.02 | 0 | 0 |
| Temp help, 6-month change (sign flipped) | +0.3% (rise) | +0.80 | 0.68 | **+0.54** | 0.65 | **+0.52** |
| Yield curve, lowest spread in 18 months (sign flipped) | −0.04 pt | +0.76 | 0.02 | +0.01 | 0 | 0 |
| Manufacturing surveys, 3-month average | +26.6 | −1.03 | 0.44 | −0.46 | 0.41 | −0.42 |
| NFCI | −0.49 | −0.16 | 0.99 | −0.16 | 1.00 | −0.16 |
| Intercept | | | | −2.49 | | −2.48 |
| **Score** | | | | **2.4%** | | **2.4%** |

**Reading it:** claims sitting at their 52-week low and strong factory surveys hold the score down. Temp help is the main upward
pressure: it rose only 0.3% over six months, well below its usual growth, so its standardized value is +0.8.

**Weights across the 27 re-fits since 2000** (main): initial claims vs. 52-week low 0.61–1.47 (always the largest), NFCI
0.45–1.00, Sahm 0.28–0.71, manufacturing 0.22–0.51, yield curve 0.02–0.46 (falling towards zero after the 2022–24 inversion
was followed only by scares), temp help −0.50 to +0.85, initial claims vs. a year ago 0.08–0.27, continued claims −0.51 to −0.08.

### 5.8 Caveats

- After 2000 the test contains two recessions (2001, 2008), five scares and 2020. Every number above rests on that.
- Claims are today's figures (our rule). 5.6 shows that real-time claims would have produced a long false red in 2022.
- Temp help, the manufacturing surveys and NFCI are revised data before 2011–15 (see section 4).
- The new Layer 1 rule used in the baseline (c) was chosen after looking at all years, so (c) is if anything flattered.
- Calibration is optimistic above 35%.
- Event starts are dated on final data; inputs are real-time.

### 5.9 Decisions for Troy (stage 3c; answered in 5.10)

1. **Constrain coefficients to ≥ 0?** Recommended: yes. It's more explainable and scored better out of sample. Its amber
   threshold is 20%.
2. **Temp help in the score?** Keep (the gain from dropping it is within noise) or drop (slightly better; sign-unstable;
   revised data before 2011).
3. **JOLTS:** leave out (no gain).
4. **Claims revisions:** state the 2022 effect on the site's methodology page. Or, in addition, test a claims input that is
   less sensitive to seasonal factors, for example the non-seasonally-adjusted 4-week average vs. the same weeks a year
   earlier, as a stage 3d / 3e follow-up.
5. **Thresholds:** amber 19% (20% with the constraint), red 50%.

### 5.10 Final model after Troy's review (2026-11-08)

**Decisions:**
1. Weights constrained to zero or positive.
2. Temp help kept.
3. JOLTS tested in the full fit and left out (see below).
4. The claims-revision effect is stated, not modeled (see the note at the end of this section).
5. Amber at the pre-2000 threshold for this model, **20%**; red **50%**.

**Final model:** ridge logistic regression on the eight trigger measures, weights ≥ 0, penalty by time-ordered
cross-validation, re-fitted each January. `src/model/score.py`: `FINAL_FEATURES`, `FINAL_NONNEG`.

**JOLTS.** You first chose to keep JOLTS in. With JOLTS added (set to 0 before December 2000), the out-of-sample skill
fell from +0.18 to +0.16, with 6 false ambers instead of 4 and 3 false reds instead of 2. You then chose the version
without JOLTS. In the 2001-onward fit tested from 2008, JOLTS changes nothing (Brier 0.0757 both ways).

**Out of sample, 2000–2026** (236 scored months, 36 with y = 1):

| Model | Brier | Skill vs. base rate | Amber | Amber: real / false | Red: real / false |
| --- | --- | --- | --- | --- | --- |
| **Final (weights ≥ 0)** | **0.108** | **+0.18** | 20% | 5 / 4 (+1 too recent) | 5 / 2 |
| Before review (unconstrained) | 0.114 | +0.14 | 19% | 5 / 6 (+1 too recent) | 5 / 2 |
| Equal-weight index | 0.115 | +0.12 | 15% | 3 / 8 | 4 / 1 |
| Layer 1 status as rates | 0.130 | +0.01 | 35% | 4 / 1 (+1 too recent) | 4 / 1 |
| Base rate | 0.132 | 0 | – | – | – |
| Final, pseudo out of sample 1980–1999 | 0.084 | +0.37 | 20% | 2 / 4 | 4 / 2 |

**Amber: 20%.** About one false amber per real warning on the 1968–1999 fit. After 2000: 5 real warnings, 4 false ambers
(0.8 per real), plus one too recent to judge. **Red: 50%.** After 2000: 5 real, 2 false. Months scored above 50% were followed
by an event 56% of the time.

**Event by event since 2000** (months of warning before the start):

| Event | Type | Amber (20%) | Red (50%) |
| --- | --- | --- | --- |
| #9 2000-11 | recession | 5 | 3 |
| #10 2003-07 | scare | 3 | none |
| #11 2005-10 | scare (Katrina) | 1 | 1 |
| #12 2008-02 | recession | on since 2006-05 | 4 |
| #13 2020-03 | pandemic (not fitted) | 4 | 3 |
| #14 2023-06 | scare | 7 | 3 |
| #15 2024-07 | scare | on since 2022-11 | on since 2023-03 |

- **False ambers:** 2006-05, 2011-08, 2017-09 (hurricane claims), 2019-06. The 2026-06 episode is too recent to judge.
  **False reds:** 2017-09, 2025-06.
- **2020:** the score was 51% in December 2019 (the claims bump), 5% in February, and 97% at the end of March. The December
  reading was not a forecast of the pandemic.
- **After #15 ended (September 2024):** 7 months at or above 50% and 17 at or above 20%, with no new event so far. That
  counts against the Brier score, but it doesn't show up as false alarms, because those months bridge into the long run
  that began in 2022.

**Calibration** (final model):

| Predicted band | Months | Average predicted | Observed |
| --- | --- | --- | --- |
| 0–5% | 112 | 2.2% | 1.8% |
| 5–10% | 33 | 7.1% | 12.1% |
| 10–20% | 28 | 14.3% | 17.9% |
| 20–35% | 16 | 26.2% | 25.0% |
| 35–50% | 20 | 41.5% | 30.0% |
| 50–100% | 27 | 76.3% | 55.6% |

Reasonable below 35%. **Overconfident above it:** read anything over 50% as "more likely than not".

**Sensitivity runs for the final model:**

| Run | Months | Brier | Base | Skill | Amber real / false | Red real / false |
| --- | --- | --- | --- | --- | --- | --- |
| **Final**, 2000– | 236 | 0.108 | 0.132 | **+0.18** | 5 / 4 | 5 / 2 |
| With JOLTS (0 before 2001) | 236 | 0.111 | 0.132 | +0.16 | 5 / 6 | 5 / 3 |
| Without temp help | 236 | 0.108 | 0.132 | +0.18 | 5 / 4 | 6 / 2 |
| Shock scares #3, #6, #11, #14 not events | 239 | 0.112 | 0.093 | −0.20 | 1 / 7 | 3 / 2 |
| Final, scored 2010– | 167 | 0.066 | 0.083 | +0.20 | 2 / 3 | 2 / 2 |
| **Claims as published at the time**, 2010– | 167 | 0.102 | 0.083 | **−0.23** | 1 / 7 | 1 / 1 |
| Final, 2010– without 2022–23 | 145 | 0.050 | 0.063 | +0.21 | 2 / 3 | 2 / 2 |
| Claims vintages, 2010– without 2022–23 | 145 | 0.054 | 0.063 | +0.14 | 1 / 7 | 1 / 1 |

**Weights across the 27 re-fits since 2000:**
- initial claims vs. 52-week low 1.07–1.44, always the largest;
- NFCI 0.67–1.16; Sahm 0.42–0.78; manufacturing 0.19–0.41;
- temp help 0–1.06 (0.65 today);
- yield curve 0–0.42 (0 today, after the 2022–24 inversion was followed only by scares);
- initial claims vs. a year ago and continued claims 0 throughout. They add nothing beyond the claims-vs-low measure.

**What drives the latest score (October 2026): 2.4%, green.**

| Input | Value | Standardized | Weight | Contribution (log-odds) |
| --- | --- | --- | --- | --- |
| Initial claims vs. 52-week low | −0.5% | −1.03 | 1.07 | **−1.10** |
| Temp help, 6-month change | +0.3% (below its usual growth) | +0.80 | 0.65 | **+0.52** |
| Manufacturing surveys, 3-month average | +26.6 | −1.03 | 0.41 | −0.42 |
| NFCI | −0.49 | −0.16 | 1.00 | −0.16 |
| Sahm indicator | 0.00 | −0.15 | 0.46 | −0.07 |
| Initial claims vs. a year ago, continued claims, yield curve | – | – | 0 | 0 |
| Intercept | | | | −2.48 |
| **Total** | | | | **−3.71 → 2.4%** |

**Claims-revision effect (to be stated on the site's methodology page in stage 3e).** The score is tested on today's
claims figures. With claims as they were first published, its 2010–2026 skill falls from +0.20 to −0.23. Almost all of
that is 2022: first-published claims rose 36–46% above their March 2022 low, against 2–6% after DOL's 2023 seasonal-factor
revision. In real time the score would have been 77–99% from June 2022 to January 2023, a false red that today's figures
hide. Outside 2022–23 the effect is smaller (+0.21 vs. +0.14), but real-time claims still add false ambers (7 vs. 3).
