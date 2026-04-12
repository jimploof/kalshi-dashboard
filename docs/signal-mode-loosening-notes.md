# Signal Mode Loosening Notes

## Purpose

This document records exactly where the buy-side signal logic was loosened, why each change was made, and what guardrails remain in place.

The goal was not to weaken the strict profile. The strict profile remains unchanged as the baseline conservative mode. A separate loosened mode was tuned for whipsaw sports conditions where strict mode can under-trigger.

## What stayed unchanged

- Strict mode thresholds and strict gating behavior were preserved.
- Hard cap protection at 95c remains in all modes.
- Dynamic top gate protection remains in all modes.
- Cliff/acceleration penalties remain in all modes.
- BUY still requires confirmation and quality gates; no unconditional BUY path was introduced.

## New user-facing mode control

The Trade Signal panel now has a mode toggle:

- `Strict`: original conservative logic.
- `Loosened`: uses the fast profile path (same backend mode name `fast` for storage compatibility).

The active mode drives:

- main displayed signal badge and split scores,
- primary BUY/SELL entry/exit notes,
- lifecycle paper-position simulation behavior.

Strict and fast transition events are still logged for side-by-side diagnostics.

## Exact loosening changes in the profile

All changes below apply only to the loosened (`fast`) profile.

1. Low establishment holdoff
- `holdoffBars`: `2 -> 1`
- Why: in fast-moving whipsaw markets, waiting two bars after local low often misses the first actionable reversal pulse.

2. Minimum rebound requirement
- Added profile-controlled rebound settings:
  - `minReboundFloor`: strict `0.8`, loosened `0.35`
  - `minReboundVolMultiplier`: strict `1.2`, loosened `0.75`
- Why: the previous global rebound requirement could stay too high during noisy but valid micro-reversals.

3. Dynamic buy cap tolerance
- `dynamicCapBase`: `84 -> 88`
- `dynamicCapMin`: `66 -> 70`
- `dynamicCapVolSlope`: `5 -> 3`
- Why: loosened mode now allows buys in slightly higher price zones when volatility is elevated, while still honoring the hard 95c cap.

4. Strong confirmation burden
- `requiredStrongConfirmations`: `2 -> 1`
- `strongPressureThreshold`: `8 -> 6`
- `strongFlowRatioThreshold`: `0.15 -> 0.10`
- `strongImbalanceThreshold`: `12 -> 10`
- Why: requiring 2 strong confirms in fast mode was still too restrictive and often prevented BUY from crossing decision thresholds.

5. RSI recovery envelope
- `rsiRecoveryMin`: `35 -> 32`
- `rsiRecoveryMax`: `62 -> 68`
- `rsiRecoverySlopeMin`: `1.0 -> 0.4`
- Why: broadens valid early-turn RSI recovery patterns that occur during abrupt sports tape shifts.

6. EMA reclaim / trend follow-through strictness
- `emaReclaimBase`: `0.25 -> 0.15`
- `emaReclaimVolMultiplier`: `0.35 -> 0.20`
- `trendRocBase`: `0.05 -> -0.05`
- `trendRocVolMultiplier`: `0.10 -> 0.02`
- Why: loosened mode now tolerates flatter follow-through and earlier reclaim behavior without requiring as much post-low extension.

7. Decision thresholds
- `buyScoreMin`: `50 -> 44`
- `buyVsSellGapMin`: `6 -> 4`
- Why: observed field behavior showed BUY frequently stuck below 50 and not materially separating from SELL despite valid reversal context.

8. Additive penalty reductions
- Introduced profile-specific additive penalties:
  - `additiveLowPenalty`: `4` (loosened)
  - `additiveStrongPenalty`: `3` (loosened)
  - `additiveTrendPenalty`: `2` (loosened)
- Previous hardcoded additive penalties were effectively much heavier (`12/10/8`) and could suppress loosened BUY scores into the 40s.
- Why: preserve quality penalties while preventing over-suppression.

9. Confirmation expansion in loosened mode
- `hasConfirmation` now allows strong RSI recovery as a valid confirmation only for loosened mode.
- Why: allows BUY to trigger when reversal momentum appears in RSI before book/tape metrics fully flip.

## Fundamental bug fix (critical)

During investigation of repeated missed reversals, we found a semantic bug in velocity gating:

- Previous behavior:
  - `accelerating = recentROC < priorROC`
  - This flagged **any momentum deceleration** as "accelerating", including positive up-moves that were still rising but less steep.
  - BUY gate used `!accelerating`, which incorrectly blocked valid reversals.

- Fix implemented:
  - Added `acceleratingDown = accelerating && recentROC < 0 && priorROC < 0`
  - Cliff/sell acceleration logic now uses `acceleratingDown`.
  - BUY recovery gate now checks `!acceleratingDown` (or non-negative recent ROC).

Why this matters:
- In real game tapes, reversals often transition from steep up to moderate up while still bullish.
- The old logic could keep suppressing BUY entries during that transition.

## Structural loosened-mode gate adjustment

Loosened mode previously still required all strict structural gates:
- lowEstablished
- hasStrongConfirmation
- trendFollowThrough
- velocityRecovering

This effectively made loosened mode strict-like in many practical sequences.

Updated loosened mode behavior:
- Uses a structural quality-vote model (`>=2` of 4 gates) plus safety constraints:
  - not cliffing
  - not in materially negative momentum (`recentROC > -0.35`)
  - has confirmation
  - not above top gate

Strict mode remains unchanged and still requires all strict structural gates.

## Lifecycle outcome finalization

The lifecycle pipeline now emits `OUTCOME_FINALIZED` after exits with a cost-adjusted outcome label.

- Classification basis: `good_buy` if net PnL > 0 else `bad_buy`.
- Net PnL includes a tiered cost model:
  - fee tiers: `micro`, `standard`, `wide` (derived from spread p90),
  - fee cents + slippage cents,
  - total costs and net PnL logged in lifecycle payload.

This provides an explicit post-trade truth signal for future adaptive tuning.

## Refactor notes

When revisiting this tuning later:

- Keep strict untouched unless there is strong evidence of strict false negatives.
- Evaluate loosened mode by stratifying outcomes by:
  - spread regime,
  - volatility bucket,
  - event type,
  - elapsed hold duration.
- Move profile constants into a typed config object per market regime once enough lifecycle outcome data has accumulated.
