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
| 15 | 2024-07 | 2024-09 | unemployment | none | – | 0.9 | +20% | none | **scare** | The mid-2024 Sahm-rule trigger |

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
