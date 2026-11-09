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

## 6. Stage 3d: score follow-ups and forecast fans

Scripts:
- `src/model/score_followups.py` (Part A);
- `src/model/forecast.py` (fans, backtest, stress paths);
- `src/model/nowcast.py`;
- `src/model/benchmarks.py`;
- `src/model/plot_forecast.py`.

Outputs:
- `data/model/score_followups_*.csv`, `score_horizons.csv`, `score_weekly.csv`;
- `forecast_backtest.csv` (one row per origin × target × horizon: center, 10/25/75/90 percentiles, deterioration
  weight, baseline and deterioration components, climatology quantiles, outcome);
- `forecast_evaluation.csv`, `forecast_events.csv`, `forecast_current.csv`, `forecast_paths.csv`, `stress_paths.csv`,
  `nowcast.csv`, `benchmark_summary.csv`.

Charts: `reports/forecast_backtest_{ur,ic,cc}.png`, `forecast_coverage.png`, `forecast_events.png`,
`forecast_current.png`.

### Part A — score follow-ups

#### A1. What drove the score from October 2024 (text for the methodology page)

Months with the score at or above 20%. Contributions are in log-odds (positive pushes the score up). Inputs with zero
weight are left out.

| Month | Score | Sahm | Claims vs. 52-wk low | Temp help | Yield curve | Manufacturing | NFCI | Intercept |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2024-10 | 99% | +1.95 | +2.73 | +2.17 | +0.43 | +0.33 | −0.33 | −2.93 |
| 2024-11 | 91% | +1.67 | +0.70 | +2.80 | +0.42 | +0.18 | −0.47 | −2.93 |
| 2024-12 | 95% | +1.67 | +1.47 | +2.43 | +0.41 | +0.30 | −0.40 | −2.93 |
| 2025-01 | 37% | +1.27 | −0.55 | +1.27 | +0.29 | +0.18 | −0.41 | −2.57 |
| 2025-02 | 58% | +1.17 | +0.38 | +1.33 | +0.29 | +0.14 | −0.44 | −2.57 |
| 2025-03 | 46% | +0.83 | +0.23 | +1.19 | +0.29 | +0.14 | −0.27 | −2.57 |
| 2025-04 | 48% | +0.83 | −0.02 | +1.03 | +0.29 | +0.42 | −0.09 | −2.57 |
| 2025-05 | 41% | +0.83 | +0.33 | +0.53 | +0.29 | +0.58 | −0.35 | −2.57 |
| **2025-06** | **85%** | +0.83 | **+1.56** | +1.15 | +0.29 | +0.64 | −0.20 | −2.57 |
| 2025-07 | 25% | +0.49 | −0.34 | +0.91 | +0.29 | +0.40 | −0.29 | −2.57 |
| 2025-08 | 32% | +0.26 | +0.26 | +0.97 | +0.29 | +0.29 | −0.27 | −2.57 |
| 2025-09 | 54% | +0.36 | +1.06 | +1.18 | +0.29 | +0.14 | −0.29 | −2.57 |
| 2025-10 | 35% | +0.36 | +0.14 | +1.18 | +0.29 | +0.24 | −0.26 | −2.57 |
| 2025-11 | 39% | +0.70 | −0.11 | +1.24 | +0.29 | +0.22 | −0.23 | −2.57 |
| 2025-12 | 56% | +1.37 | −0.24 | +1.34 | +0.29 | +0.34 | −0.29 | −2.57 |
| 2026-02 | 30% | +0.62 | +0.34 | +0.70 | 0 | +0.24 | −0.27 | −2.48 |
| 2026-06 | 25% | +0.16 | +1.03 | +0.38 | 0 | +0.03 | −0.21 | −2.48 |

**Paragraph for the methodology page.** From late 2024 through 2025 the score was often elevated without a new
deterioration event following. Three things drove it.
- **Temporary-help employment** was falling. It was the largest push in most months.
- **The Sahm indicator** stayed in the 0.3–0.5 range after the mid-2024 rise in unemployment.
- **Initial claims** had several short jumps above their 52-week low. The largest came in October 2024, during Hurricanes
  Helene and Milton and the Boeing strike, and in June and September 2025.

The red reading of June 2025 (85%) combined a 13% rise in initial claims above their 52-week low with a 1.6% six-month fall
in temp-help jobs, on top of a Sahm indicator of 0.27 and weak regional factory surveys. Claims eased the next month and the
score fell to 25%.

In each case the inputs moved in the direction that has preceded past downturns, but not far or long enough. The score
is a probability, and a high probability that doesn't materialise is part of how it behaves.

#### A2. A claims input less dependent on seasonal factors

**New inputs** (`features.py`):
- `nsa_yoy` = the NSA initial claims 4-week average vs. the same weeks a year earlier;
- `nsa_low` = that year-ago ratio minus its lowest value in the prior 52 weeks.

Each version of the final model (weights ≥ 0) was scored out of sample on today's data and on claims as first published
(FRED vintages, 2010 on).

| Variant | Skill, today's data 2000– | Skill, today's data 2010– | **Skill, as published 2010–** | As published 2010–, without 2022–23 | Real-time score mid-2022 (mean) |
| --- | --- | --- | --- | --- | --- |
| Final (SA claims) | **+0.180** | +0.197 | −0.234 | +0.141 | 89% |
| + nsa_yoy | +0.166 | +0.191 | −0.200 | +0.125 | 85% |
| + nsa_yoy + nsa_low | +0.147 | +0.167 | −0.213 | +0.216 | 90% |
| NSA (yoy + low) replace the SA initial-claims measures | +0.040 | −0.044 | −0.061 | +0.102 | 58% |
| NSA yoy replaces the SA initial-claims measures | +0.093 | 0.000 | −0.001 | −0.018 | 12% |

**Not adopted:** no variant meets your rule. The ones that improve the as-published skill materially (the two
"replace" variants) lose 0.09–0.14 of today's-data skill, far more than 0.02. The year-on-year NSA measure removes the
2022 false red, because in real time 2022 claims were *below* their pandemic-inflated year-earlier levels. But it
also blunts the warnings that work, so overall skill falls.

#### A3. Calibration above 35%

**Recalibration doesn't help.** A Platt-style adjustment was estimated each January on earlier out-of-sample scores only.
It made the Brier score worse: 0.112 vs. 0.108 (skill +0.15 vs. +0.18). The two reliability tables are in
`score_followups_a3_reliability.csv`.

**Very little evidence sits above 35%:**

| Band | Months | Independent episodes | Average predicted | Observed | 90% interval (block bootstrap by episode) |
| --- | --- | --- | --- | --- | --- |
| 35–50% | 20 | 9 | 41% | 30% | 6% – 62% |
| 50–100% | 27 | 7 | 76% | 56% | 20% – 77% |

With 7–9 episodes per band, observed rates of 30% and 56% are consistent with the predicted 41% and 76%. The evidence is
too thin to justify a correction.

**Recommendation:** keep the raw score. On the site, show percentages up to 35%, then verbal bands: **"elevated"**
for 35–50% and **"more likely than not"** for 50% and above.

#### A4. Colour stability

The colour uses amber 20% and red 50%, judged on the 1968–1999 in-sample scores and then applied after 2000. Weekly =
the score recomputed every Thursday (claims release day) with everything known that day.

| Rule | Monthly changes / yr (pre-2000 / 2000–) | Weekly changes / yr (2000–) | 2000–: amber real / false | 2000–: red real / false | Effect on leads (2000–) |
| --- | --- | --- | --- | --- | --- |
| Plain 20% / 50% | 2.07 / 1.98 | 3.24 | 5 / 4 | 5 / 2 | – |
| Hysteresis: leave amber < 18.75%, red < 47.5% | 1.91 / 1.90 | 3.09 | 5 / 4 | 5 / 2 | none |
| Hysteresis: leave amber < 17.5%, red < 45% | 1.88 / 1.79 | 2.80 | 5 / 4 | 5 / 1 | none |
| Hysteresis: leave amber < 16.25%, red < 42.5% | 1.69 / 1.79 | 2.80 | 5 / 4 | 5 / 1 | none |
| **Hysteresis: leave amber < 15%, red < 40%** | **1.69 / 1.64** | **2.57** | 5 / 4 | 5 / 1 | none |
| 2 of 3 months (weeks) | 1.07 / 0.89 | 2.42 | 5 / 2 | 2 / 0 | about 1 month shorter; red late for 2001 and 2020; scares #10, #11 missed at red |

**Pre-2000 test:**
- Hysteresis changes no warning or false alarm and cuts colour changes by about a fifth.
- The 2-of-3 rule halves false ambers (6 → 3) but loses one red warning (the 1977 scare) and a month of lead everywhere.

**Recommendation:** hysteresis with amber entered at 20% and left below 15%, red entered at 50% and left below 40%.
That gives about 2.6 colour changes a year week to week (vs. 3.2) at no cost in warning.

#### A5. Probabilities for 3 and 12 months

The same final model (eight inputs, weights ≥ 0, same cross-validation), out of sample from 2000:

| Target | Base rate (2000–) | Brier skill |
| --- | --- | --- |
| Event starts within 3 months | 7.5% | +0.22 |
| Event starts within 6 months (headline) | 15.3% | +0.18 |
| Event starts within 12 months | 30.4% | +0.21 |

**Today (October 2026):** 0.5% (3 months), 2.4% (6 months), 37% (12 months).

The 12-month figure has to be read against its base rate. In an average month since 1968 there is roughly a one-in-three
chance that some event, scares included, starts within a year. 37% is close to that. The small push above the base rate
comes from temp help and from the yield curve, whose lowest spread in the past 18 months was just below zero. The 12-month
model weights the yield curve (0.65) much more than the 6-month model (0).

### Part B — forecast fans

#### Method (rules to keep)

**Targets and timing**
- Unemployment rate at 3, 6 and 12 months after the latest published month.
- SA initial and continuing claims rates as **4-week averages** (less noisy than single weeks) at 13, 26 and 52 weeks
  after the latest published week.
- Origins: every month end from 2000. Each origin uses only what was published by then: the unemployment rate as known
  that day (ALFRED), claims rates as we hold them (current vintage; the 2022 caveat applies), the score inputs, and the
  out-of-sample 3/6/12-month probabilities.
- Outcomes: today's figures.

**Baseline**
- A ridge regression of the h-step change on the eight score inputs plus the current level. Unemployment rate in points;
  claims rates as log (percentage) changes.
- Fitted only on **quiet** origins: no event in progress and none starting within the horizon. The deterioration
  component is what covers downturns, so a baseline trained on downturns too would count them twice.
- Re-fitted each January. Penalty chosen by forward-chaining cross-validation (chosen values 10–3,000, inside the grid);
  the cross-validation's out-of-sample residuals supply the noise.

**Deterioration component**
- The path after each past event start, measured from the last pre-event month (week). Used: events from 1968 for the
  unemployment rate, from 1973 for the claims rates. 2020 is never used.
- **Recession paths** (the 7 recessions plus the early signal) and **scare paths** (6) are kept separate and mixed by
  their share of events: 57% recession for the unemployment rate (8 of 14), 54% for the claims rates (7 of 13). At each
  origin only events whose path had already been observed are used.
- The event is assumed to start at a uniformly random point within the horizon.
- Scaling to today's level: unemployment-rate paths are added in points; claims-rate paths are applied as percentage
  changes.

**Spread of paths across events** (change h periods after the last pre-event period):

| Target | Group | h | Min | 25% | Median | 75% | Max |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Unemployment rate (pt) | recession (8) | 3 / 6 / 12 | 0.0 / −0.1 / +0.6 | +0.1 / +0.4 / +1.3 | +0.35 / +0.65 / +1.7 | +0.5 / +1.0 / +2.5 | +0.9 / +1.4 / +2.8 |
| | scare (6) | 3 / 6 / 12 | −0.3 / −0.6 / −1.1 | | −0.1 / −0.2 / −0.4 | | +0.1 / +0.1 / +0.3 |
| Initial claims rate (%) | recession (7) | 13 / 26 / 52 wk | +5 / 0 / +6 | +8 / +12 / +17 | +10 / +17 / +29 | +14 / +22 / +60 | +23 / +30 / +69 |
| | scare (6) | 13 / 26 / 52 wk | −17 / −22 / −18 | | −8 / −10 / −12 | | +8 / −5 / 0 |
| Continuing claims rate (%) | recession (7) | 13 / 26 / 52 wk | +3 / +5 / +14 | +8 / +14 / +36 | +12 / +16 / +47 | +13 / +25 / +57 | +16 / +31 / +71 |
| | scare (6) | 13 / 26 / 52 wk | −6 / −12 / −20 | | −2 / −5 / −6 | | +4 / +3 / +4 |

(Scare paths measured from the pre-event week fall back quickly, because the spike that defines a scare is already over a
few weeks later.)

**Mixture**
- With the horizon-matched probability (3-month for 3 months / 13 weeks, 6-month for 6 / 26, 12-month for 12 / 52;
  raw, since recalibration was not adopted) the change follows a deterioration path; otherwise the baseline.
- **If an event is already in progress at the origin**, the deterioration weight is 1. The path is picked up at the event's
  current age, using past events that lasted at least that long.

**Bands**
- 10/25/50/75/90 percentiles of 4,000 simulated draws (a baseline or deterioration change, plus a resampled baseline
  residual). Center = the median.
- When risk is elevated the upper band stretches toward the deterioration paths, so the fan is asymmetric (see the 12-month
  fans in `forecast_current.png`).

**Benchmarks**
- No-change.
- Climatology: no-change center plus the empirical quantiles of all past h-step changes, re-estimated each January.

#### Results, 2000–2026 excluding 2020 (B8)

RMSE ratio = our median's RMSE / no-change's RMSE (below 1 is better); 90% interval by moving-block bootstrap
(blocks = the horizon). Pinball skill = quantile loss vs. climatology (above 0 is better). Coverage = share of outcomes
inside the band (targets 50% and 80%).

| Target | h | RMSE ratio (90% int.) | Pinball skill | 50% band: all / event / quiet | 80% band: all / event / quiet | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| Unemployment rate | 3 mo | **0.81** (0.75–0.89) | +0.21 | 48 / 46 / 49 | 80 / 77 / 81 | **pass** |
| | 6 mo | **0.76** (0.69–0.85) | +0.26 | 52 / 47 / 54 | 79 / 76 / 80 | **pass** |
| | 12 mo | **0.74** (0.67–0.84) | +0.29 | 53 / 54 / 52 | 78 / 79 / 77 | **pass** (label lower confidence) |
| Initial claims rate | 13 wk | 0.99 (0.93–1.05) | +0.04 | 50 / 44 / 53 | 79 / 79 / 79 | pass on paper; no real gain |
| | 26 wk | 0.94 (0.88–1.01) | +0.05 | 48 / 44 / 50 | 79 / 77 / 80 | pass; gain not significant |
| | 52 wk | 0.94 (0.85–1.02) | +0.03 | 46 / 55 / 39 | 73 / 75 / 71 | pass; gain not significant |
| Continuing claims rate | 13 wk | **0.88** (0.78–0.96) | +0.17 | 52 / 53 / 52 | 77 / 85 / 74 | **pass** |
| | 26 wk | **0.86** (0.77–0.95) | +0.18 | 46 / 45 / 46 | 73 / 79 / 72 | **pass** |
| | 52 wk | 0.87 (0.78–0.98) | +0.15 | 36 / 38 / 34 | **67** / 70 / 65 | **FAIL** (bands too narrow) → dropped |

"Event" = an event in progress or starting within the horizon (79–125 origins depending on h); "quiet" = the rest.

**2020 (reported separately):** every fan failed. The 80% bands covered 0–24% of outcomes and the RMSE ratios were about 1.0.
No indicator anticipated a pandemic, and the paths of past events have nothing like a 25-fold jump in claims.

**What it says:**
- **Unemployment-rate fans work.** They are 19–26% more accurate than no-change, beat climatology at every horizon, and
  their bands hold up in downturn months as well as in quiet ones. That last point is the one that matters.
- **Continuing-claims fans work at 13 and 26 weeks.** At 52 weeks the bands are too narrow, so that horizon fails the gate.
- **Initial-claims fans are well calibrated but barely more accurate than no-change.** Initial claims are close to a random
  walk at these horizons. Their 90% intervals include 1.

#### Event by event (`forecast_events.png`, `forecast_events.csv`)

Outcomes inside the 80% band, out of 9 (3 targets × 3 horizons):

| Event | 6 months before | 3 months before | Notes |
| --- | --- | --- | --- |
| #9 2001 recession | 5 / 9 | 8 / 9 | Six months before, the claims fans were too low; the unemployment fans held |
| #12 2008 recession | 8 / 9 | 6 / 9 | From November 2007: 12-month unemployment fan 4.2–6.3% (median 4.9%), actual 6.5%, just above the band; 12-month claims also above |
| #14 2023 scare | 6 / 9 | 9 / 9 | |
| #15 2024 scare | 9 / 9 | 7 / 9 | |
| #13 2020 (not fitted) | 2 / 9 | 2 / 9 | As expected |

#### Nowcast of the next unemployment-rate release (B5)

- **Method:** previous published rate, plus regression terms for the months since the last release and the changes in log
  initial and continuing claims between survey reference weeks (the week containing the 12th). Re-estimated before every
  release on all earlier months from 1968, excluding 2020. Scored against the first release.
- **2000–2026 excluding March–December 2020, 311 releases:** RMSE 0.155 vs. 0.172 for no-change (ratio 0.90); MAE 0.121 vs.
  0.128. It hits the exact published figure no more often than no-change (25% each).
- **March–December 2020:** RMSE 1.83 vs. 3.45 (ratio 0.53).
- **Missing releases:** October 2025 was never published. The November 2025 release followed September's, and the
  nowcast treated it as a two-month change (4.42%); the first release was 4.6%.
- **Next nowcast:** November 2026, once claims for the week ending 14 November are out (initial on 19 November, continuing
  on 26 November).
- **Chicago Fed real-time unemployment forecast:** the Chicago Fed's legal notice allows reproducing its written materials
  for non-commercial use with credit. Distributing or republishing requires the Bank's written permission, and the Bank
  cannot grant rights to third-party data. The Labor Market Indicators use third-party sources including Indeed and The
  Conference Board, which our rules exclude. **Not usable as a marker without written permission.** Not built.

#### Published forecasts as benchmarks (B6; comparison only)

**FOMC SEP median:** FRED `UNRATEMD`, verified. It is the Q4-average unemployment rate, annual, with one vintage per SEP
release from December 2015 (43 vintages).

**SPF median:** the Philadelphia Fed's `medianLevel.xlsx`, sheet `UNEMP` (quarterly levels for the current quarter and
four ahead). It is a free download marked "all rights reserved", with reuse questions directed to `PHIL.SPF@phil.frb.org`.
The file is read from outside the repository; only summary statistics are saved.

Our fan medians were interpolated to each benchmark's target quarter, within our 12-month reach.
- **"Strict" timing:** our origin is the last month end before publication. We then know one month *less* of the
  unemployment rate, because both benchmarks come out after that month's release.
- **"Matched" timing:** our origin is the end of the publication month, with the same unemployment-rate release.

Mean absolute error, excluding 2020 quarters:

| Benchmark | Horizon | Cases | Ours, strict | Ours, matched | Benchmark | No-change, matched |
| --- | --- | --- | --- | --- | --- | --- |
| SPF median | 1 quarter ahead | 103 | 0.27 | 0.24 | **0.20** | 0.30 |
| | 2 quarters ahead | 102 | 0.40 | 0.35 | **0.31** | 0.48 |
| | 3 quarters ahead | 101 | 0.58 | 0.51 | **0.44** | 0.69 |
| FOMC SEP median | Mar → Q4 | 6 | 0.58 | 0.36 | **0.23** | 0.55 |
| | Jun → Q4 | 7 | 0.19 | 0.18 | 0.15 | **0.11** |
| | Sep → Q4 | 8 | 0.29 | 0.22 | **0.18** | 0.19 |

December SEPs project the *next* year's Q4, which is beyond our 12-month reach; they were not compared.

**Professional consensus is a better point forecast than our fan median** (about 15–20% lower error). Our fans beat
no-change, and their value is the honest band and the tilt toward downturns, not a better central forecast. The FOMC
comparison rests on only 6–8 cases per release month.

#### Stress paths (B7; what-ifs, not forecasts)

"If a 2001-type (#9) or 2008-type (#12) downturn started now", from today's level (`stress_paths.csv`, shown in
`forecast_current.png`):

| Target | Today | 2001-type peak | 2008-type peak |
| --- | --- | --- | --- |
| Unemployment rate | 4.1% | 6.1% after 18 months | 9.1% after 21 months |
| Initial claims rate (4-wk avg, per 10,000) | 12.7 | 20.2 after 51 weeks | 24.5 after 61 weeks |
| Continuing claims rate (4-wk avg) | 1.11% | 1.91% after 82 weeks | 2.59% after 70 weeks |

#### Today's fans (October 2026 data; unemployment rate latest published: September 4.2%)

| Target | Horizon | Median | 50% band | 80% band | Deterioration weight |
| --- | --- | --- | --- | --- | --- |
| Unemployment rate | 3 mo | 4.05% | 3.93–4.19 | 3.80–4.30 | 0.5% |
| | 6 mo | 3.94% | 3.78–4.09 | 3.62–4.23 | 2.4% |
| | 12 mo | 3.80% | 3.55–4.23 | 3.26–4.99 | 37% |
| Initial claims rate (per 10,000) | 13 / 26 / 52 wk | 12.5 / 12.2 / 12.0 | | 11.7–13.4 / 11.3–13.3 / 10.6–15.0 | |
| Continuing claims rate | 13 / 26 wk | 1.07% / 1.04% | | 1.02–1.13 / 0.97–1.14 | |

The 12-month unemployment fan is visibly asymmetric: the median is 3.8% but the 90th percentile is 5.0%, because the
12-month event probability is 37%.

**Bias check:** in quiet months the 12-month median was on average slightly *too high* (outcomes 0.18 point lower); before
events it was too low (0.46 point). So today's downward-leaning median is not a systematic downward bias.

#### Caveats

- After 2000 the evaluation contains two recessions (2001, 2008), five scares and 2020.
- Overlapping horizons make neighbouring errors correlated. The block-bootstrap intervals allow for that, but they are wide.
- Claims rates are today's figures. Section 5.10 shows real-time claims would have produced a false red in 2022, which
  would also have pushed the fans up then.
- Event dates (used for "in progress") are on final data.
- **The "in progress" rule leans on recession paths during short scares.** For a few months after the starts of #10 (2003)
  and #15 (2024) the 12-month unemployment median jumped to about 6–8% (visible in `forecast_backtest_ur.png`), because the
  past events lasting that long are mostly recessions. Coverage passed anyway.
- Benchmarks' information sets differ from ours; both timings are shown.

### Gate (plan)

**Criteria:** band coverage within about 10 points of target, and each horizon shown beats no-change.

| Target × horizon | Gate | For the site (3e) |
| --- | --- | --- |
| Unemployment rate 3 / 6 / 12 months | pass | show; 12 months labeled lower confidence |
| Continuing claims rate 13 / 26 weeks | pass | show |
| Continuing claims rate 52 weeks | **fail** (80% band covers 67%) | drop |
| Initial claims rate 13 / 26 / 52 weeks | pass on the letter of the gate (ratios 0.99 / 0.94 / 0.94) | **your decision**: intervals include 1, so no demonstrated gain over no-change |
| Nowcast | beats no-change (0.90) | your decision |

### Decisions for Troy (stage 3d)

1. **Calibration:** keep the raw score; percentages up to 35%, then "elevated" (35–50%) and "more likely than not"
   (50%+). Recommended.
2. **Colour stability:** hysteresis, with amber entered at 20% and left below 15%, red entered at 50% and left below 40%.
   Recommended: no loss of warning, about 20% fewer colour changes. The alternatives are the 2-of-3 rule (half the
   changes, a month less warning) or none.
3. **NSA claims input:** not adopted (A2 rule not met). Confirm.
4. **Initial-claims fans:** drop all three (no demonstrated gain), or show 26 and 52 weeks with a "small gain" note.
   Recommended: drop the fans and keep the initial-claims rate history plus its stress paths.
5. **"In progress" rule:** keep as decided, or switch the deterioration weight to 1 only once an event has lasted 3+ months
   (scares rarely do), using the probability before that. That would remove the 2003 / 2024 spikes; it is untested, so it
   would need a re-run.
6. **Nowcast on the site:** show it as "next release nowcast" next to no-change? Its gain is modest (RMSE −10%).
7. **Benchmark markers:** FOMC SEP (public, FRED) could be a marker in 3e. SPF needs the Philadelphia Fed's OK first.
   Chicago Fed: not without written permission.

### Stage 3d decisions (final, 2026-11-08)

Troy asked Claude to decide using best judgement; he leaned towards showing the nowcast.

| # | Decision | Reason |
| --- | --- | --- |
| 1 | **Score display:** percentages up to 35%; above that, verbal bands, **"elevated"** (35–50%) and **"more likely than not"** (50%+). Raw score, no recalibration | Recalibration made the Brier score worse. Only 7–9 independent episodes per band above 35%, so the percentages there aren't precise enough to print |
| 2 | **Colour hysteresis:** amber entered at 20%, kept until the score falls below 15%; red entered at 50%, kept until below 40% | Judged on pre-2000 data: the same warnings with about 20% fewer colour changes. After 2000: weekly changes 3.2 → 2.6 a year, false reds 2 → 1 |
| 3 | **NSA claims input: not adopted** | It didn't meet the adoption rule (A2) |
| 4 | **Initial-claims-rate fans: not shown.** The initial-claims-rate history and its stress paths stay | Accuracy vs. no-change 0.98 / 0.93 / 0.93, with every 90% interval including 1: no demonstrated gain, and a fan implies forecasting skill |
| 5 | **"In progress" rule changed:** the deterioration weight goes to 1 only once an event has lasted **3 months** (`IN_PROGRESS_MIN_MONTHS`); before that the usual probability-weighted mixture applies | Tested before adopting: every target and horizon got slightly more accurate (table below), coverage stayed on target, gate results unchanged. The 12-month median spike after the 2003 scare fell from 7.9% to 5.9%. The 2024–25 readings stay high (event #15 did last 3 months, and the score stayed high afterwards) |
| 6 | **Nowcast: shown**, as "next release nowcast" with a typical-error range (±0.2 point, from the RMSE of 0.155) beside the last published rate | It beats no-change (RMSE −10%) and halved the error in 2020's fast-moving months. No reason not to show it, provided the page says that it doesn't hit the exact published decimal more often than no-change does |
| 7 | **Benchmark markers:** FOMC SEP median (FRED `UNRATEMD`, public) may be shown as a marker in 3e. SPF: only after the Philadelphia Fed confirms reuse. Chicago Fed: no | Terms checked 2026-11-08 (see the B5 / B6 notes above) |

**Final forecast evaluation** (2000–2026 excluding 2020, with the 3-month in-progress rule; this replaces the B8 table above):

| Target | h | RMSE ratio | Pinball skill | 50% band: all / event / quiet | 80% band: all / event / quiet | On the site |
| --- | --- | --- | --- | --- | --- | --- |
| Unemployment rate | 3 mo | 0.80 | +0.23 | 50 / 51 / 49 | 81 / 80 / 81 | yes |
| | 6 mo | 0.74 | +0.28 | 53 / 49 / 54 | 79 / 76 / 80 | yes |
| | 12 mo | 0.73 | +0.31 | 52 / 53 / 52 | 77 / 78 / 77 | yes, lower confidence |
| Continuing claims rate | 13 wk | 0.87 | +0.18 | 53 / 54 / 52 | 77 / 85 / 74 | yes |
| | 26 wk | 0.84 | +0.20 | 45 / 43 / 46 | 73 / 76 / 72 | yes |
| | 52 wk | 0.86 | +0.16 | 36 / 37 / 34 | 67 / 66 / 67 | **no** (fails coverage) |
| Initial claims rate | 13 / 26 / 52 wk | 0.98 / 0.93 / 0.93 | +0.05 / +0.06 / +0.05 | all: 50 / 47 / 46 | all: 80 / 78 / 73 | **no** (no demonstrated gain) |

Event by event, the share of outcomes inside the 80% band is unchanged (table above). Today's fans changed by at most 0.03
point. The benchmark comparison was re-run with the new fans: our matched-timing errors fell slightly (SPF one quarter
ahead: ours 0.24 vs. SPF 0.20), and the conclusion stands.

**Stage 3d is complete. Stage 3e (the site) shows:**
- the score, with the display rules in 1 and 2;
- the unemployment-rate fans at 3, 6 and 12 months (12 labeled lower confidence);
- the continuing-claims-rate fans at 13 and 26 weeks;
- the nowcast;
- the 2001-type and 2008-type stress paths for all three targets, labeled what-ifs;
- the FOMC SEP marker;
- the methodology text from A1 and 5.10.

### 6.x Part 0: fixes from the stage 3d review (stage 3e preparation)

Script: `src/model/part0.py` (`prep` before the forecasts, `report` after). `forecast.py` gained three options:
`--from 1985` (fans before 2000, used only to choose a blend weight), `--option gap`, and `--live`.

#### 0.1 Late-cycle bias

**Late-cycle origin:** the unemployment rate, as known that day, is within 0.5 point of its 24-month low, and no event
started in the previous 24 months. The same flag is used for the continuing-claims fans. Error = outcome minus the fan
median (positive = median too low). The 90% intervals come from a moving-block bootstrap (blocks = the horizon).

| Target | h | Late-cycle, all origins | Late-cycle, quiet origins | Late-cycle, 2022–26 only |
| --- | --- | --- | --- | --- |
| Unemployment rate (pt) | 3 mo | −0.01 (−0.05 to +0.02), n=137 | −0.02 (−0.06 to +0.02) | **+0.13** (+0.06 to +0.20), n=17 |
| | 6 mo | −0.03 (−0.11 to +0.04) | −0.05 (−0.14 to +0.01) | **+0.25** (+0.11 to +0.37), n=15 |
| | 12 mo | −0.10 (−0.33 to +0.06) | **−0.26** (−0.47 to −0.15) | **+0.30** (+0.30 to +0.34), n=15 |
| Continuing claims rate (pt) | 13 wk | −0.01 (−0.02 to +0.01) | −0.01 (−0.03 to 0.00) | **+0.05** (+0.03 to +0.10) |
| | 26 wk | −0.02 (−0.05 to +0.02) | −0.04 (−0.08 to −0.01) | **+0.12** (+0.11 to +0.21) |

**What it says:**
- **Across all late-cycle periods since 2000, the median is *not* biased low.** In quiet late-cycle months it was slightly
  too *high* (12 months: 0.26 point).
- **The downward lean is specific to 2022–26.** In those years unemployment drifted up slowly (3.4% → 4.3%) without a
  qualifying event, so the baseline's "quiet times" pull and the low event probabilities kept the median too low:
  by 0.13 / 0.25 / 0.30 point for the unemployment rate.
- That rests on about 15 overlapping origins, roughly one or two independent observations. The narrow intervals
  understate the uncertainty.

**Fixes tested, 2000–2026 excluding 2020** (adopt only if RMSE ratio and pinball skill stay within ~0.02 and coverage
within ~3 points, and the late-cycle bias falls):

| Option | UR 3 / 6 / 12: RMSE ratio | UR pinball skill | UR 80% coverage | CC 13 / 26: RMSE ratio | 2022–26 bias, UR 3 / 6 / 12 | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| Base (3d) | 0.80 / 0.74 / 0.73 | 0.23 / 0.28 / 0.31 | 82 / 79 / 77 | 0.87 / 0.84 | +0.13 / +0.25 / +0.30 | kept |
| (a) Blend toward no-change (weights chosen on 1985–1999 only: UR 0.50 / 0.45 / 0.20, CC 0.70 / 0.70) | 0.87 / 0.82 / 0.76 | 0.18 / 0.22 / 0.27 | 81 / 78 / 76 | 0.94 / 0.94 | +0.05 / +0.14 / +0.26 | **rejected**: accuracy −0.04 to −0.10, CC coverage −8 points |
| (b) Gap term (level minus 36-month average, penalized 25× less) | 0.80 / 0.75 / 0.74 | 0.22 / 0.25 / 0.26 | 82 / 78 / 74 | 0.87 / 0.83 | +0.18 / +0.26 / +0.26 | **rejected**: 12-month pinball −0.05, coverage −3.5 points, bias not reduced |

**Today's fans under each option** (live origin, 8 November 2026; unemployment rate 4.1% for October):

| Option | UR 3 mo: median (80%) | UR 6 mo | UR 12 mo | CC 13 wk | CC 26 wk |
| --- | --- | --- | --- | --- | --- |
| Base (kept) | 3.94 (3.70–4.20) | 3.84 (3.50–4.14) | 3.67 (3.16–4.69) | 1.07 (1.02–1.13) | 1.04 (0.97–1.14) |
| (a) Blend | 4.02 (3.78–4.28) | 3.96 (3.62–4.26) | 3.76 (3.24–4.77) | 1.10 (1.05–1.16) | 1.09 (1.02–1.18) |
| (b) Gap term | 3.94 (3.70–4.21) | 3.84 (3.47–4.14) | 3.69 (3.05–4.73) | 1.07 (1.01–1.12) | 1.02 (0.95–1.11) |

**Decision:** neither fix adopted. The methodology page will say that in 2022–26 the fan's median ran 0.1–0.3 point
below what happened. Users should read the downward lean of today's median with that in mind, and look at the band
rather than the median line.

#### 0.2 Coherent probabilities

Every month: p3 = min(p3, p6), p12 = max(p12, p6). The adjusted values feed the fans. The raw values are kept in
`score_horizons.csv` as `p3_raw` / `p12_raw`.

| Probability | Months changed, 1980– (2000–) | Largest change | Brier 2000–, raw → adjusted |
| --- | --- | --- | --- |
| 3-month | 22 (8) | 0.04 | 0.0546 → 0.0545 |
| 12-month | 119 (66) | 0.32 | 0.1720 → 0.1727 |

The 12-month model occasionally fell below the 6-month one, mainly in fast-moving months. Forcing coherence costs a
little 12-month accuracy (+0.0007 Brier), a fair price for probabilities that never contradict each other on the page.

#### 0.3 Live origin

The live run uses everything published by the **refresh date**, not the last month end. `part0.py prep` writes
`live_asof.csv` (every score input, the three probabilities, the latest unemployment rate), and `forecast.py --live` adds
it as an origin. Score, fans and stress paths therefore start from the same values.

On 8 November 2026:
- unemployment rate **4.1%** (October, released 6 November);
- initial claims week ending 31 October; continuing claims week ending 24 October;
- temp help: October now shows a 1.4% six-month rise.

| | Month-end origin (31 October) | Live origin (8 November) |
| --- | --- | --- |
| Score (6-month) | 2.4% | **1.8%** |
| 3-month / 12-month probability | 0.5% / 37% | 0.4% / 32% |
| UR level the fan starts from | 4.2% (September) | **4.1% (October)** |
| UR fan 3 / 6 / 12 mo, median | 4.04 / 3.94 / 3.80 | 3.94 / 3.84 / 3.67 |
| UR 12-month 80% band | 3.26–4.91 | 3.16–4.69 |
| CC 13 / 26 wk, median | 1.07 / 1.04 | 1.07 / 1.04 |

Nowcast: the next nowcast (November 2026) can only be made once claims for the reference week ending 14 November are
out (initial on 19 November, continuing on 26 November). Until then the page says "next nowcast available after 26
November".

#### 0.4 Today's median vs. the FOMC

The September 2026 SEP median for the Q4 2026 unemployment rate is **4.1%** (FRED `UNRATEMD`, vintage 2026-09-16). Our
live median for Q4 2026 is **4.05%**: October's published 4.1%, and about 4.05% and 4.0% for November and December. The
December 80% range is 3.84–4.17%.

The two are 0.05 point apart, less than one rounding step of the published rate and well inside our range. Ours leans a
little lower for two reasons:
- our baseline is fitted on quiet periods, in which unemployment has tended to edge down;
- today's 3- and 6-month event probabilities are very low.

The FOMC figure also predates the September and October releases. Section 0.1 shows that in 2022–26 our median ran low,
so the FOMC's flat path is a reasonable reminder that the gap may be our downward lean rather than information.

#### 0.5 Small items

- **In-progress rule:** the 3-month in-progress rule (3d decision 5) was chosen *after* seeing the 2000–2026 results. It
  is not a pure out-of-sample choice, and its small accuracy gain should be read that way.
- **Nowcast range:** ±0.2 point contained the first release in **82%** of 311 releases (2000–2026 excluding March–December
  2020). The range covering 80% is ±0.19, so **±0.2 is the right label** for an "about 80%" range.

  | Range | ±0.1 | ±0.15 | ±0.2 | ±0.25 | ±0.3 |
  | --- | --- | --- | --- | --- | --- |
  | Coverage | 49% | 69% | 82% | 90% | 93% |

## 7. Stage 3e: the model on the site

### 7.1 Stage 3e-1: frozen model, live run, Overview and Outlook

**Frozen model** (`src/model/freeze_model.py` → `data/model/frozen/model_<year>.json`). Re-fits exactly what the backtest
fitted in January of the model year, with only what was known on 1 January:
- score: 3, 6 and 12-month final models (standardizing mean / sd, weights ≥ 0, intercept, penalty);
- fans: baselines for the horizons shown (UR 3 / 6 / 12, CC 13 / 26 weeks) with their CV residuals, and every past event
  path (2020 excluded);
- stress paths (#9, #12) for all three targets; nowcast coefficients (all releases before 1 January, 2020 excluded);
- the colour and display rules and the 2000-on base rates (7.5 / 15.3 / 30.4%).

**Live run** (`src/model/live.py [date]`): one result set as of the run date (`data/model/live_latest.json`), plus
`score_display_weekly.csv` (weekly backtest + live, with the hysteresis colour) and `score_display_monthly.csv`
(1980 on). Nothing is re-estimated.

**Checks against stage 3d / Part 0 (as of 8 November 2026):**

| Item | Part 0 (forecast.py --live) | live.py |
| --- | --- | --- |
| Score 3 / 6 / 12 months | 0.37% / 1.77% / 31.9% | identical |
| UR fan baseline 3 / 6 / 12 | 3.957 / 3.843 / 3.596 | identical (4 decimals) |
| UR 3 / 6 / 12 median (80% band) | 3.94 (3.70–4.20) / 3.84 (3.50–4.14) / 3.67 (3.16–4.69) | 3.94 (3.70–4.20) / 3.83 (3.52–4.14) / 3.67 (3.16–4.76) |
| CC 13 / 26 median | 1.07 / 1.04 | 1.07 / 1.05 |
| Our Q4 2026 median vs. FOMC 4.1% | 4.05 | 4.05 |

The fan differences are simulation noise: the UR 12-month 90th percentile ranges 4.68–4.79 across 12 seeds.

**Today (8 November 2026):** 6-month score 2% (1.77%), green, −0.6 pt vs. last week. Drivers: new claims near their
52-week low (down), strong factory surveys (down), temp help growing only 1.4% over six months (up). All Layer 1 triggers
green. Nowcast for November waits for the reference-week claims (after 26 November).

### 7.2 Stage 3e-2: claims pages, Leading, downloads

- **Live-run record.** `live.py` now writes `data/model/live_history.csv` (one row per run date) and
  `live_fans_history.csv` (each run's fans). The weekly history line uses the backtest up to the first live run, then
  the live runs. The score's change is labeled by what it compares with: last week's backtest score for the first live
  run, then the previous live run ("vs. last week" when it is 5-9 days earlier).
- **Driver sentences** exist for every input with a non-zero contribution. Temp help names its usual pace: the
  training mean of the 6-month change, +2.9% (1968-2025).
- **Initial claims rate (Job Losses):** what-if paths (2001-type peak 20.2 per 10,000 after 51 weeks, 2008-type 24.5
  after 61 weeks from 12.7), no fan, and the score driver line ("currently the largest downward pull").
- **Continuing claims rate (Duration):** 13 and 26-week fan (1.07% (1.02-1.13), 1.05% (0.97-1.14)) and what-ifs; the 52-week
  range is not shown (80% bands held 68% of outcomes, 2000-2026 excluding 2020).

### 7.3 Stage 3e-3: automation, archive, alerts, re-fit

- **Weekly live run** (Refresh data workflow): tests → model inputs (claims history, ALFRED vintages for UNRATE, TEMPHELPS,
  the factory surveys and NFCI, Treasury rates, trigger history) → `live.py --archive`. The run proceeds only with a new
  claims week or unemployment month since the last archived run; it writes a create-only archive file, appends to
  `live_history.csv`, writes `live_status.json` and prints a colour-change alert (alerts off).
- **Frozen model only:** nothing is re-estimated between January re-fits.
- **January re-fit** (Re-fit model workflow): the whole chain, `freeze_model.py <year>`, `refit_summary.py` (old vs. new
  weights, today's score and fans under both, backtest skill and coverage, gate, event list), then a pull request.
- **Reproducibility check (test re-fit, 8 November 2026):** re-fitting the 2026 model in the cloud gave identical weights,
  intercepts and penalties and the same score skill (+0.180). Fan coverage moved by at most 1 point (simulation noise:
  the earlier local run also simulated the live origin, which shifts the random-number sequence).

## 8. Stage 4e: state inputs tested (pre-registered)

Pre-registration: `docs/phase4_model_tests.md`, committed before the test code (`src/model/state_candidates.py`, itself
committed before it was run). Results: `data/model/state_candidates_results.csv`.

**Candidates.** C1 = covered-employment-weighted share of states with 4-week average initial claims up 20%+ on a year
earlier; C2 = log of the weighted 4-week initial claims rate vs. a year earlier (today's weights held fixed). Both
real-time with a 12-day state release lag, from 1996. Baseline = the final Phase 3 model (eight trigger measures,
weights >= 0).

**Results** (skill = 1 - Brier / Brier of the base rate; difference on identical months; 90% interval = block bootstrap
by episode):

| Comparison | Months scored | Baseline skill | + C1 | + C2 |
| --- | --- | --- | --- | --- |
| **A. Same window (fit from 1996), scored Dec 2002 on** | 226 (5 episodes) | +0.146 | −0.006 (−0.017 to +0.003) | +0.001 (−0.061 to +0.040) |
| S1. National claims as first published, scored 2010 on | 167 (3) | +0.179 | −0.026 (−0.038 to −0.014) | −0.023 (−0.131 to +0.103) |
| S2. Shock scares not events | 229 (3) | −0.511 | +0.005 (−0.002 to +0.011) | +0.068 (+0.022 to +0.111) |
| B. Full history (fit from 1968), scored 2000 on | 236 (6) | +0.180 | −0.002 (−0.006 to +0.001) | −0.011 (−0.035 to +0.018) |
| C1 at 10% / 30% (A; sensitivity only) | 226 | +0.146 | −0.023 / −0.000 | |

**Adoption rule** (A difference >= +0.02 with its interval above 0; S1 and B differences >= −0.02): **neither candidate
is adopted; the model is unchanged.** C1 fails A and S1; C2 fails A and S1.

What this says:
- **Breadth adds nothing the national claims measures don't already carry.** With weights constrained >= 0, the fitted
  weight on C1 is zero in the latest re-fit of comparisons A, S1 and B (0.07 in S2): once national claims are in, the share of states with
  rising claims gets no weight. The 10% and 30% versions are no better.
- **Weighted claims (C2) is close to the national claims input**, as expected before testing (its prior was "low"). It
  gets weight but changes skill by +0.001 in the primary test, with an interval of roughly ±0.05: indistinguishable
  from noise.
- The one positive result, C2 when the four one-off shock scares are not events (S2, +0.068), comes from a run whose
  baseline skill is strongly negative (only three event cycles in the window). It is not part of the rule and is
  noted, not acted on.
- Scoring starts in December 2002, not 2001 as the pre-registration expected: months while the 2000-02 event was in
  progress are not scored (the pre-registered definition of a usable month). No rule changed.
- Limitations: state data are today's figures (no state vintages), the weights are today's back to 1996, and the
  state-era window holds only five or six event cycles, so the intervals are wide.

**Consequences:** the diffusion row on the Leading page stays "context" with no colour; the States page keeps the
neutral "why it matters" line on the breadth chart (no lead was found); nothing goes into the January 2027 re-fit.
