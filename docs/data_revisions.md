# DOL data revisions

DOL data keeps only the latest figures (no vintages). Each run compares the new download with the stored
history. When past periods change, the stored file is overwritten and one row is added here automatically
(by `src/fetchers/dol_common.py`). New periods are not revisions. A revision never fails the run.

"Largest change" is new minus old, with the period (and state) where it happened. Seasonal factors are x100.

| Run date (UTC) | File | Periods changed | Date range | Largest change |
| --- | --- | --- | --- | --- |
| 2026-11-13 | State ar539 | 3 | 2026-10-17 to 2026-10-31 | cw_state_ui +16 (2026-10-31 HI) |
| 2026-11-18 | State ar5159 | 1 | 2026-10-31 to 2026-10-31 | changes only in other columns |
| 2026-11-19 | State ar539 | 2 | 2026-10-31 to 2026-11-07 | cw_state_ui +19 (2026-11-07 HI) |
| 2026-11-20 | State ar539 | 45 | 2026-01-24 to 2026-11-14 | cw_state_ui -1.43e+05 (2026-11-14 PR) |
| 2026-11-24 | State ar539 | 1 | 2026-10-24 to 2026-10-24 | changes only in other columns |
| 2026-11-24 | State ar218 | 1 | 2026-09-30 to 2026-09-30 | changes only in other columns |
