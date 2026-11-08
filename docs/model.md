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

**Overall Layer 1 status** (plan): red if any of triggers 1–4 is red; amber if two or more triggers are amber or red;
otherwise green. From 1967 to 2026 it was green 59% of months, amber 14% and red 27% (the red months are mostly inside events).
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
| **Overall status** | 2 | 4 | 8 | on since 1979-02 | on since 1989-06 | 0 | on since 2006-12 | 4 | 6 |

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
| **Overall status** | 2 | 0 | 0 | 0 | late +1 | 0 | late +3 | 0 | 0 |

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
| **Overall status** | 5 | 2 | none | 1 | 6 | on since 2022-12 |

**Yield curve with a 24-month window** (amber): 1970 0, 1973 4, 1979 8, 1981 on since 1979-02, 1990 **14**, 2000 2,
2008 **16**, early signal 2, 2020 7. The curve warned of every recession within two years. With the 12-month window it only
gets credit for four of the seven, because its lead is often longer than a year.

### 4.4 Summary per trigger

Hits, scares and false alarms count episodes that start outside events. False alarms per decade use the years with data.

| Trigger | Level | Recessions warned (≤ 12 mo) | Median lead | Hits | Followed by scare | False alarms | False alarms / decade | Adds warning (of 8) | Flag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 Sahm | amber | 4 of 7 | 0.5 | 4 | 3 | 4 | 0.7 | 1 (#1 +1) | weak |
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
| **Overall status** | amber | 4 of 7 (the other 3 "on since") | 3 | 6 | 4 | 4 | 0.7 | | |
|  | red | 5 of 7 | 0 | 7 | 2 | 1 | 0.2 | | |

False alarms, by start month (amber unless noted): Sahm 1967-10, 1986-05, 2023-11, 2025-12; claims vs. 52-wk low
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

### 4.6 Candidates to drop (flagged only; nothing has been dropped)

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
