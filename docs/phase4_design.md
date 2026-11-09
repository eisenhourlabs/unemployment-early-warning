# Phase 4 Design Brief: States, Alternative Data and Shutdown Backups

Approved by Troy, 2026-11-08. Plan agreed and open items settled in Troy's Claude project the same day
(decisions below).

## Summary

Phase 4 adds:
- a **States** page: a map plus a table of claims and unemployment for all 50 states and DC, with a
  footprint-weighted view and a national comparison, covering both frequency and severity;
- a **shutdown fallback**: national claims estimated from the state filings when the DOL release is delayed,
  clearly labeled, and replaced by official figures when they arrive;
- **alternative layoff signals** as context charts: Revelio RPLS (incl. its layoff-notice series) and WARN notices.
  Challenger is dropped from Phase 4 (O4);
- **pre-registered model tests** of two state-based inputs for the early-warning score. An input is adopted only
  under the Phase 3 rule, and only through the January re-fit pull request.

It also stops publishing the Chicago Fed LMI files (licence).

**Unchanged rules:**
- free public data only;
- no employer name, logo or company data on the site. The weighted view shows no weights, ranks, counts or company
  references on any page, and the word "footprint" stays off public pages. The exact weights are committed to the
  repository (O2);
- licences decide what is charted and what is downloadable;
- the model is frozen between January re-fits;
- every decision and its reason go in `docs/decisions.md`;
- alerts stay off.

## Decisions taken in planning (2026-11-08)

| # | Question | Decision | By |
| --- | --- | --- | --- |
| P1 | Footprint weighting on the public site | Keep it as is: the States page may show a footprint-weighted view. Troy accepts that published weighted figures make the weights recoverable | Troy |
| P2 | Footprint traces already public (rank file, 44-state downloads, decisions.md wording) | Leave as is for now. No history rewrite | Troy |
| P3 | Chicago Fed LMI files in the public repo | Stop committing them (see 4a). No permission request will be sent, so the LMI stays permanently off the public site and out of the model; local fetch only, for Troy's own comparison | Troy |
| P4 | Shutdown fallback | Build it: national claims estimated from state filings, labeled as an estimate | Troy |
| P5 | Alternative sources | RPLS charted once its terms are confirmed (no downloads). WARN via RPLS's layoff-notice series if allowed, else the WARN Firehose free tier, national level. Challenger: dropped from Phase 4 (O4). Google Trends: apply for the API alpha, nothing on the site meanwhile, no scraping | Troy (Claude's recommendation) |
| P6 | What may enter the model | Two pre-registered candidates: a state claims diffusion index and footprint-weighted claims. RPLS, WARN and Trends are display-only (histories too short or inconsistent for a 2001/2008/2020 backtest) | Troy (Claude's recommendation) |
| P7 | Branch-count source | Current counts stay. Refreshing them is a later task | Troy |

## Source status (checked 2026-11-08; re-verify at build)

| Source | What we use | Licence on our site | Model use | To verify at build |
| --- | --- | --- | --- | --- |
| DOL state claims (ar539; FRED `{ST}ICLAIMS`, `{ST}CCLAIMS`) | State NSA initial and continued weeks claimed, covered employment | Public: chart + download | Candidate (4e) | FRED state history start (expected late 1980s; ar539 from 1995). State release lag vs. national |
| DOL state data during a shutdown | In Oct–Nov 2025 DOL posted downloadable state data for most states while the weekly release was suspended. Economists summed it and applied the pre-published seasonal factors | Public | Fallback input (4c) | Which endpoint kept updating in 2025 (ar539.csv or the claims.asp state report). Build a reader for whichever it was |
| DOL seasonal factors | Already in `data/processed/dol/seasonal_factors.csv`, through 2027-04-03 | Public | Fallback (4c) | Next year's factors appear each spring; quality rule should warn when fewer than 8 future weeks remain |
| BLS LAUS state unemployment rates (FRED `{ST}UR`) | Monthly state rates | Public | Display | — |
| Revelio RPLS | Monthly: employment, hiring and attrition rates, layoff-notice (WARN) series, state detail. Next release Thu 3 Dec 2026, 8:30 am ET | Described as free to use and cite. **Terms of Service not yet read** (the page was blocked from Claude's tools) | Display only (history from about 2021) | Terms of Service; download format; history start; whether figures are revised |
| WARN notices | Fallback if RPLS's series can't be used: WARN Firehose free API (25 calls a day, key in secrets) | Raw notices are public records; aggregator terms apply to their output. Chart only | Display only | Firehose terms and history coverage by state |
| Challenger, Gray & Christmas | Not used in Phase 4 (O4) | No public reuse terms found | None | — |
| Google Trends | Nothing in Phase 4 | Website reuse allowed with citation. The official API is a gated alpha. No scraping | None | Troy applies for alpha access |
| Chicago Fed LMI | Local only | Legal notice: republication or distribution needs written permission; third-party inputs (Bloomberg, Conference Board, Indeed/ADP, Google) cannot be licensed by the Bank. No request will be made (P3) | Internal comparison only | — |

## Data definitions (`src/transforms/state_measures.py`, new)

Notation: s = state (50 + DC; PR and VI appear in tables only), t = week ending Saturday.

- **Initial claims rate** IC_s,t / CE_s,t: NSA state UI initial claims over covered employment (ar539). Shown as
  the 4-week average.
- **Frequency change:** log(4-week avg IC_s,t / 4-week avg IC_s for the same weeks a year earlier), shown as a % change.
  Year-on-year on NSA data, because state seasonal factors aren't published; national factors applied to states would be wrong.
- **Continuing claims rate** (severity): NSA continued weeks claimed / CE, 4-week average, and its change vs. a year
  earlier in percentage points.
- **Exhaustion rate and average duration** (severity, monthly): the existing `exhaustion_duration_monthly.csv`.
- **State unemployment rate** (monthly): LAUS, plus its rise above its own 12-month low, a state "Sahm-style"
  gap shown in points. No trigger is attached.
- **Diffusion index** (breadth of new job losses): the share of states whose frequency change is ≥ +20%,
  three ways:
  - unweighted: count share;
  - covered-employment weighted: Σ CE_s·1[·] / Σ CE_s. This is the headline and model candidate C1;
  - footprint-weighted: Σ w_s·1[·].

  The +20% threshold is fixed in this brief, before any testing. 10% and 30% versions are reported in 4e only as
  sensitivity checks, never to choose the threshold.
- **Footprint-weighted aggregates:** Σ w_s·x_s for the initial claims rate, the continuing claims rate and the state
  unemployment rate, with w_s = branch share (Σ w_s = 1; 0 outside the footprint). Each is shown next to the national
  figure on the same basis (NSA year-on-year).
- **Weights in the cloud (O2):** `config/state_weights.csv` gets a `weight` column (branch share, 6 decimals,
  Σ = 1) generated from `internal/state_weights_private.csv`, and is committed, so the cloud build and live runs
  read it directly. The rank column stays. The data-source note stays in `internal/` only. This replaces CLAUDE.md's
  rule "exact weights kept only in internal/".

## Page wireframes

### 1. States (new page, after Duration in the navigation)

```
+----------------------------------------------------------------------------------------------+
| STATES                                         As of: claims through week ending 31 Oct 2026  |
| How claims and unemployment differ across states. Views: [National] [Weighted]                |
| "Weighted view: each state counts in proportion to a fixed set of regional weights this site  |
|  uses for its own monitoring."                                                                |
+----------------------------------------------------------------------------------------------+
| SUMMARY TILES                                                                                 |
|  New claims vs. a year ago      National +3%   | Weighted +5%                                 |
|  Continuing claims rate         National 1.1%  | Weighted 1.2% (+0.1 pt vs. year ago)         |
|  States with claims up 20%+     8% of covered jobs (4 states)   [diffusion, CE-weighted]      |
|  State unemployment above its 12-month low by 0.5 pt+:  6 states                              |
+----------------------------------------------------------------------------------------------+
| MAP  Measure: (•) New claims vs. a year ago  ( ) Continuing claims rate  ( ) Unemployment rate |
|               ( ) Unemployment rate vs. 12-month low  ( ) Exhaustion rate (12-month)           |
|  [US choropleth, 50 states + DC; diverging colours centred on 0 for change measures,          |
|   sequential for levels; tooltip: state, value, rank among states, as-of date]                |
|  Footer: "Year-on-year on unadjusted data: states' seasonal patterns differ, so we compare      |
|  each week with the same weeks a year earlier."                                               |
+----------------------------------------------------------------------------------------------+
| BREADTH: SHARE OF JOBS IN STATES WITH CLAIMS UP 20%+ (weekly, 1996–)                           |
|  [line, recession shading; CE-weighted solid; weighted-view version dashed when that view is on]|
|  "Why it matters: a rise that starts in a few states and spreads tends to come before a        |
|   national rise in claims." (wording to be confirmed by the 4e results; if C1 shows no lead,   |
|   the line says only what the chart measures)                                                 |
+----------------------------------------------------------------------------------------------+
| WEIGHTED VS. NATIONAL (weighted view only)                                                     |
|  Two small charts: initial claims rate yoy, continuing claims rate; national vs. weighted      |
+----------------------------------------------------------------------------------------------+
| STATE TABLE (sortable; 51 rows + PR, VI)                                                       |
|  State | New claims 4-wk | vs. yr ago | Cont. claims rate | vs. yr ago | Unemp. rate | vs. 12-mo |
|        |                 |            |                   |            | (month)     | low       |
|        | Exhaustion 12-mo | Avg weeks paid | Data through                                         |
|  Late or missing state rows say so ("not reported for week ending 31 Oct").                    |
+----------------------------------------------------------------------------------------------+
```

- The map, tiles and table follow the page time control's end date. History charts follow the control as on
  other pages.
- No weights, ranks, a count of weighted states, the word "footprint" or the word "employer" appear on any page.
  The browser check tests for this, extending the Phase 2 check.
- Map: Plotly choropleth with `locationmode="USA-states"`. Bundle the US topojson in `src/site/static/` so the page
  needs no outside fetch.
- Colour is never the only carrier of a value: every tooltip and table cell shows the number.

### 2. Overview and claims pages: shutdown fallback labels

```
| SA initial claims (estimate) 221,000   "Estimate from state filings: the DOL weekly release is  |
|                                         delayed. 49 of 53 areas reported; missing areas carried  |
|                                         forward. Official figures will replace it."              |
```

- Estimated weeks are drawn as hollow markers with a dashed segment, in every chart that shows them. Legend:
  "estimate (release delayed)".
- The freshness line says: "Claims through week ending 31 Oct (official) · 7 Nov – 21 Nov estimated from state filings".
- Unemployment rate during a BLS blackout: the existing nowcast continues, labeled "Estimate: the October jobs report
  has not been published". It is never shown as a published value.

### 3. Job Losses: new context charts (bottom of page)

```
| LAYOFF NOTICES (WARN), monthly                       Source: Revelio Labs RPLS / WARN Firehose |
|  [bars, workers notified per month, from start of series]                                     |
|  Note: "Notices are filed 60+ days before most layoffs and only by larger employers; state     |
|  rules differ. Context only: not used in the early-warning score."                             |
| ALTERNATIVE EMPLOYMENT AND ATTRITION (RPLS), monthly            Source: Revelio Labs (RPLS)    |
|  [RPLS attrition rate vs. JOLTS layoffs and discharges rate, history since RPLS starts]        |
|  Note: "Built from online professional profiles; skews toward white-collar jobs. Useful when   |
|  BLS releases are delayed."                                                                    |
```

### 4. Duration: one new context chart

```
| HIRING RATE (RPLS) vs. JOLTS HIRES RATE, monthly                                               |
|  Note: "Hiring of all workers, not just the unemployed: a rough read on how fast people find  |
|  jobs, not a job-finding rate."                                                                |
```

### 5. Leading Indicators

- Summary table: add the diffusion index (CE-weighted) as a row with no colour ("context"). It gets a colour only if
  4e adopts it into the score.

### 6. Data & Downloads

| Added | Download? |
| --- | --- |
| `data/states/state_weekly` (state rates, year-on-year changes, 1995–) | Yes (CSV, XLSX) |
| `data/states/state_monthly` (state UR, gap to 12-month low, exhaustion, duration) | Yes |
| `data/states/diffusion_weekly` (unweighted and CE-weighted) | Yes |
| Footprint-weighted aggregates and diffusion | No (charted only; consistent with "weights not offered as download") |
| Shutdown estimates (`dol/claims_estimates`, each estimated week with areas reported, method, and the later official value and error) | Yes |
| RPLS, WARN aggregates | No; listed with the reason |
| Chicago Fed LMI | No (unchanged) |

### 7. About

- **Sources:** RPLS and WARN with attribution and licence notes; the Google Trends note ("not used: no
  licensed automated access").
- **Method notes:** state measures (why year-on-year on NSA data), diffusion definition, the weighted view
  (the same sentence as on the States page), and the shutdown estimate method with its tested accuracy from 4c.

## Shutdown fallback (`src/fetchers/dol_state_fallback.py`, new; called by the Thursday run)

1. **Trigger.** The national release is due (release calendar) and `wait_for_claims.py` times out without a new FRED
   week, and the DOL national XML has no new week either, but state data has a new week. Then estimate. Otherwise
   do nothing.
2. **Estimate.**
   - IC_NSA_est = Σ reported areas + Σ missing areas, each carried forward from its last reported week.
   - IC_SA_est = IC_NSA_est / (SF_t / 100), using DOL's published factor for week t.
   - Continuing claims the same way, one week behind, with the CC factor.
   - Claims rates use the latest covered employment.
3. **Storage.** `data/processed/dol/claims_estimates.csv`, a separate file never mixed into the official tables. Rows:
   week, measure, estimate, areas reported (of 53), missing areas, method version, official value (filled in later),
   error.
4. **Replacement.** When official figures arrive, the site switches to them. The estimate's error is filled in and
   logged in `docs/data_revisions.md`.
5. **Model during a delay.** `live.py` runs on the estimates, and its archive record is flagged `provisional: true`.
   The panel says "provisional: based on estimated claims" (O3). When the official week arrives, the next live run
   uses it; the provisional record stays in the archive (create-only) and the site shows the official run.
6. **Validation (4c gate), two parts:**
   - (a) Replay the Oct–Nov 2025 suspension using the state data now on file, dropping the areas that were reported
     missing at the time where known (news reports name AZ, MA, NV, TN, CO and HI in various weeks).
   - (b) Monte Carlo: for every week from 1996 to 2026, drop k = 1–5 areas at random, with probability proportional to
     their claims share, and estimate.

   Report the median and 90th-percentile absolute % error vs. official SA, for initial and continuing claims.
   Pre-registered acceptance (O3): median ≤ 2% and 90th percentile ≤ 5%. A measure that fails is still shown, with its
   tested error range, but does not feed the score.
   - Limitation, stated on the site: the replay uses today's revised state data, so it understates real-time error
     from later state revisions.

## Model tests (stage 4e, pre-registered)

Write `docs/phase4_model_tests.md` **before** running anything. It holds the candidates, data rules, metric and
adoption rule exactly as below, plus the Phase 3 adoption rule quoted verbatim from `docs/model.md` (A2).

| | Candidate | Definition | Prior expectation (stated now) |
| --- | --- | --- | --- |
| C1 | State claims diffusion | CE-weighted share of states with frequency change ≥ +20% | Plausible gain: breadth is information the national total lacks |
| C2 | Footprint-weighted claims | log ratio of the footprint-weighted 4-week IC rate to its level a year earlier | Low: close to the national NSA year-on-year input that failed A2 in Phase 3. Tested because it is the measure closest to our exposure |

- **Data as known at the time.** State claims use the current vintage cut back by their release lag, like national
  claims (plan decision 5). Code measures the state lag from DOL's release pattern; expected about one week more than
  national. Weights: today's weights held fixed for all history. This is a stated limitation, since the footprint has
  changed over time.
- **Same window.** The state data starts in 1995, or in the late 1980s via FRED if available. So the baseline (final
  Phase 3 model) is re-fit on exactly the same window as each candidate model. Comparisons are like for like; skill
  is not compared against the published +0.18.
- **Metric.** Out-of-sample Brier skill, 2000–2026 excluding 2020, expanding-window re-fit each January, weights ≥ 0,
  ridge as in Phase 3. Report:
  - the skill difference with a 90% block-bootstrap interval (by episode);
  - the sensitivity runs Phase 3 used, including claims as first published from 2010;
  - C1 at the 10% and 30% thresholds (reported only).
- **Uncertainty.** There are only about a dozen events since 2000, so a skill gain under roughly 0.05 is unlikely to be
  distinguishable from noise. The bootstrap interval, not this rough figure, is the reported evidence.
- **Adoption.** Phase 3 rule. At most one candidate is adopted. If adopted, it enters through the January 2027
  re-fit pull request, not mid-year.
- C2 reads the committed weights in `config/state_weights.csv` (O2).

## Catalog, automation and checks

- **Catalog rows:**
  - `RPLS`: active after 4d, licence `cite-only`, no download;
  - `WARN`: source = RPLS series or Firehose, `chart-only`;
  - `CHALLENGER`: stays `future`, note "dropped from Phase 4 (O4)";
  - `STATE_DIFFUSION`: derived;
  - `GTRENDS`: stays `future`;
  - `CHI_LMI`: fetcher `local-only`.
- **FRED state series:** extend from 44 to all 50 + DC (153 series). Still under the 10% failure rule; confirm the
  threshold arithmetic.
- **Quality rules:**
  - allowed age for RPLS (45 days);
  - state completeness (a week with fewer than 50 of 53 areas is flagged);
  - seasonal factors running out (under 8 future weeks).
- **Chicago Fed:**
  - add `data/processed/CFLMI*` and `data/vintages/CFLMI*` (or wherever its vintages live) to `.gitignore`;
  - `git rm --cached` them, so the files stay on the PC and leave the current tree (history unchanged, P2);
  - remove the fetcher from the cloud workflow;
  - keep running it locally only;
  - the Chicago Fed release-schedule read in `release_calendar.py` is unaffected.
- **Secrets:** `WARN_FIREHOSE_KEY`, only if that route is used.
- **Tests:**
  - unit tests for the state measures, diffusion, the fallback estimator (synthetic missing areas), and that
    the committed weights sum to 1 and match the private file;
  - the browser check extended to the States page and the estimate labels.

## Build stages

| Stage | Contents | Gate (stop and wait for Troy) |
| --- | --- | --- |
| **4a Cleanup and foundation** | Chicago Fed untracked and taken out of the cloud run; all-51 state fetch; weight column in `config/state_weights.csv`; `state_measures.py` and its tables; catalog rows; quality rules; CLAUDE.md rule updates; decisions.md entries for P1–P7 and O1–O7 | Green cloud run; `git ls-files` shows no CFLMI files; spot-check 3 states' rates against DOL's published state figures |
| **4b States page** | Page, map, tiles, diffusion chart, weighted vs. national, table, downloads, About notes | Local preview + browser check, then Troy's review and merge |
| **4c Shutdown fallback** | Fallback fetcher, estimates file, labels on Overview / Job Losses / Duration, provisional live runs, replay + Monte Carlo report `reports/fallback_validation.md` | Error table against the pre-registered limits; Troy accepts or adjusts |
| **4d Alternative signals** | RPLS terms check by Code (O5), then RPLS, WARN, Job Losses / Duration context charts, About sources | Licence check per item; Troy's review |
| **4e Model tests** | Pre-registration doc first (Troy approves it), then the runs, results in `docs/model.md` section 8 | Results; adoption decision; any change goes to the January re-fit |

Order: 4a → 4b → 4c → 4d → 4e. 4c can go before 4b if a shutdown looks likely.

## Open items (settled by Troy, 2026-11-08)

| # | Item | Decision |
| --- | --- | --- |
| O1 | Public wording for the weighted view | The word "footprint" is dropped from pages. Label "Weighted"; sentence: "Weighted view: each state counts in proportion to a fixed set of regional weights this site uses for its own monitoring." The proposed "the weights are not published" clause is left out, because under O2 they are in the repository |
| O2 | Where the exact weights live | Committed: a `weight` column in `config/state_weights.csv`, generated from the private file. No secret |
| O3 | Score during a DOL delay; fallback acceptance limits | The score and fans run on estimated claims, flagged "provisional". Acceptance: median absolute error ≤ 2% and 90th percentile ≤ 5% |
| O4 | Challenger | Troy won't do the manual monthly entry, so Challenger is dropped from Phase 4 (catalog row stays `future`) |
| O5 | RPLS Terms of Service | Code reads them at the start of 4d and stops at a gate if charting with attribution isn't clearly allowed |
| O6 | Fallback acceptance limits | Settled with O3 |
| O7 | Chicago Fed permission email | Not sent. The LMI stays local-only and is never on the site or in the model (P3) |
