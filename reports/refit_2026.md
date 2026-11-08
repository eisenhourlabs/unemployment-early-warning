# Re-fit 2026: summary for review

Old model: 2026 (data known by 2026-01-01). New model: 2026 (data known by 2026-01-01), frozen 2026-11-08 22:48 UTC.
Nothing on the site changes until this pull request is merged.

## 1. Score weights (standardized inputs; weights >= 0)

**3-month model**

| Input | Old | New | Change |
| --- | --- | --- | --- |
| sahm | 0.459 | 0.459 | +0.000 |
| claims_low | 1.218 | 1.218 | +0.000 |
| claims_yoy | 0.145 | 0.145 | +0.000 |
| cont_yoy | 0.034 | 0.034 | +0.000 |
| temp_help | 0.407 | 0.407 | +0.000 |
| yield_curve | 0.000 | 0.000 | +0.000 |
| mfg | 0.403 | 0.403 | +0.000 |
| nfci | 0.600 | 0.600 | +0.000 |
| intercept | -3.759 | -3.759 | +0.000 |
| penalty C | 0.3 | 0.3 |  |
| training months | 493 | 493 | 0 |

**6-month model**

| Input | Old | New | Change |
| --- | --- | --- | --- |
| sahm | 0.458 | 0.458 | +0.000 |
| claims_low | 1.066 | 1.066 | +0.000 |
| claims_yoy | 0.000 | 0.000 | +0.000 |
| cont_yoy | 0.000 | 0.000 | +0.000 |
| temp_help | 0.654 | 0.654 | +0.000 |
| yield_curve | 0.000 | 0.000 | +0.000 |
| mfg | 0.408 | 0.408 | +0.000 |
| nfci | 0.995 | 0.995 | +0.000 |
| intercept | -2.483 | -2.483 | +0.000 |
| penalty C | 0.3 | 0.3 |  |
| training months | 490 | 490 | 0 |

**12-month model**

| Input | Old | New | Change |
| --- | --- | --- | --- |
| sahm | 0.145 | 0.145 | +0.000 |
| claims_low | 0.457 | 0.457 | +0.000 |
| claims_yoy | 0.000 | 0.000 | +0.000 |
| cont_yoy | 0.000 | 0.000 | +0.000 |
| temp_help | 0.542 | 0.542 | +0.000 |
| yield_curve | 0.651 | 0.651 | +0.000 |
| mfg | 0.000 | 0.000 | +0.000 |
| nfci | 0.794 | 0.794 | +0.000 |
| intercept | -0.904 | -0.904 | +0.000 |
| penalty C | 0.1 | 0.1 |  |
| training months | 484 | 484 | 0 |

## 2. Today (2026-11-08) under the old and the new model (same inputs, same seed)

|  | Old model | New model |
| --- | --- | --- |
| Score, 3 months | 0.4% | 0.4% |
| Score, 6 months | 1.8% | 1.8% |
| Score, 12 months | 31.9% | 31.9% |
| ur 3: middle (80% range) | 3.94 (3.70-4.20) | 3.94 (3.70-4.20) |
| ur 6: middle (80% range) | 3.83 (3.52-4.14) | 3.83 (3.52-4.14) |
| ur 12: middle (80% range) | 3.67 (3.16-4.76) | 3.67 (3.16-4.76) |
| cc 13: middle (80% range) | 1.07 (1.02-1.13) | 1.07 (1.02-1.13) |
| cc 26: middle (80% range) | 1.05 (0.97-1.14) | 1.05 (0.97-1.14) |

## 3. Backtest (2000 on): old vs. new

**Score**

| Measure | Old | New |
| --- | --- | --- |
| months_scored | 236 | 236 |
| skill_vs_base | 0.180 | 0.180 |
| amber_real | 5 | 5 |
| amber_false | 4 | 4 |
| red_real | 5 | 5 |
| red_false | 2 | 2 |

**Fans shown on the site**

| Target, horizon | Error vs. no change | Inside 50% range | Inside 80% range | Gate (new) |
| --- | --- | --- | --- | --- |
| ur 3 | 0.797 -> 0.797 | 49% -> 50% | 82% -> 81% | pass |
| ur 6 | 0.739 -> 0.740 | 53% -> 53% | 79% -> 79% | pass |
| ur 12 | 0.725 -> 0.726 | 52% -> 52% | 77% -> 77% | pass |
| cc 13 | 0.866 -> 0.866 | 52% -> 53% | 77% -> 77% | pass |
| cc 26 | 0.837 -> 0.841 | 46% -> 45% | 74% -> 73% | pass |

## 4. Gate

Every target and horizon shown on the site still passes.

## 5. Event list

No change to the event list.
