/**
 * market-signals.utils.ts
 *
 * Pure client-side signal computation functions.
 * All inputs are derived from already-loaded candlestick history and live
 * order-book/WS signals — no network requests are made here.
 */

// ── RSI ───────────────────────────────────────────────────────────────────────

/** Wilder's RSI(period). Returns null if insufficient bars. */
export function computeRSI(closes: readonly number[], period = 14): number | null {
  if (closes.length < period + 1) return null;

  let avgGain = 0;
  let avgLoss = 0;

  for (let i = 1; i <= period; i++) {
    const delta = closes[i]! - closes[i - 1]!;
    if (delta > 0) avgGain += delta;
    else avgLoss += Math.abs(delta);
  }
  avgGain /= period;
  avgLoss /= period;

  for (let i = period + 1; i < closes.length; i++) {
    const delta = closes[i]! - closes[i - 1]!;
    avgGain = (avgGain * (period - 1) + Math.max(0, delta)) / period;
    avgLoss = (avgLoss * (period - 1) + Math.max(0, -delta)) / period;
  }

  if (avgLoss === 0) return 100;
  const rs = avgGain / avgLoss;
  return Number((100 - 100 / (1 + rs)).toFixed(2));
}

// ── EMA ───────────────────────────────────────────────────────────────────────

/** Exponential Moving Average — returns final EMA value or null if insufficient bars. */
export function computeEMAValue(closes: readonly number[], period: number): number | null {
  if (closes.length < period) return null;
  const k = 2 / (period + 1);
  let ema = closes.slice(0, period).reduce((a, b) => a + b, 0) / period;
  for (let i = period; i < closes.length; i++) {
    ema = closes[i]! * k + ema * (1 - k);
  }
  return Number(ema.toFixed(2));
}

// ── VWAP ──────────────────────────────────────────────────────────────────────

type OHLCVBar = { open: number; high: number; low: number; close: number; volume: number };

/**
 * Volume-Weighted Average Price over the supplied candle window.
 * Note: resets are not applied (uses the full loaded history, not a calendar day).
 */
export function computeVWAP(candles: readonly OHLCVBar[]): number | null {
  if (!candles.length) return null;
  let num = 0;
  let den = 0;
  for (const bar of candles) {
    const typical = (bar.high + bar.low + bar.close) / 3;
    if (bar.volume > 0) {
      num += typical * bar.volume;
      den += bar.volume;
    }
  }
  return den === 0 ? null : Number((num / den).toFixed(2));
}

// ── Velocity & Acceleration ───────────────────────────────────────────────────

export interface VelocityResult {
  recentROC: number;     // avg ¢ change per bar, last 3 bars
  priorROC: number;      // avg ¢ change per bar, prior 3 bars
  accelerating: boolean; // true if momentum is decreasing vs prior window
  acceleratingDown: boolean; // true only when the downward move is speeding up
}

/**
 * Rate-of-change over two consecutive 3-bar windows.
 * recentROC < priorROC (both negative) = fall is accelerating = cliff fingerprint.
 */
export function computeVelocity(closes: readonly number[]): VelocityResult | null {
  if (closes.length < 7) return null;
  const n = closes.length;
  const recentROC = (closes[n - 1]! - closes[n - 4]!) / 3;
  const priorROC  = (closes[n - 4]! - closes[n - 7]!) / 3;
  const accelerating = recentROC < priorROC;
  const acceleratingDown = accelerating && recentROC < 0 && priorROC < 0;
  return { recentROC, priorROC, accelerating, acceleratingDown };
}

// ── Lower-wick exhaustion ─────────────────────────────────────────────────────

/**
 * Lower wick as a fraction of the bar range on the most recent candle.
 * > 0.35 = meaningful price rejection. > 0.5 = strong hammer / reversal candle.
 * Returns null if the bar range is too tight (<0.5¢) to be meaningful.
 */
export function recentLowerWickRatio(candles: readonly OHLCVBar[]): number | null {
  if (!candles.length) return null;
  const bar = candles[candles.length - 1]!;
  const range = bar.high - bar.low;
  if (range < 0.5) return null;
  const lowerWick = Math.min(bar.open, bar.close) - bar.low;
  return Number((lowerWick / range).toFixed(3));
}

// ── Volume divergence ─────────────────────────────────────────────────────────

export interface VolumeDivergenceResult {
  priceDirection:    'down' | 'flat' | 'up';
  volumeDirection:   'rising' | 'flat' | 'falling';
  bearishExhaustion: boolean; // price down + volume falling = sellers drying up
  cliffConfirmed:    boolean; // price down + volume rising  = continuation down
}

/**
 * Compares 3-bar price direction to 3-bar volume trend.
 * bearishExhaustion → potential reversal up (dip setup signal).
 * cliffConfirmed    → falling knife, avoid buying.
 */
export function computeVolumeDivergence(candles: readonly OHLCVBar[]): VolumeDivergenceResult | null {
  if (candles.length < 6) return null;
  const n = candles.length;
  const recentClose = (candles[n - 1]!.close + candles[n - 2]!.close + candles[n - 3]!.close) / 3;
  const priorClose  = (candles[n - 4]!.close + candles[n - 5]!.close + candles[n - 6]!.close) / 3;
  const recentVol   = (candles[n - 1]!.volume + candles[n - 2]!.volume + candles[n - 3]!.volume) / 3;
  const priorVol    = (candles[n - 4]!.volume + candles[n - 5]!.volume + candles[n - 6]!.volume) / 3;

  const priceDirection: 'down' | 'flat' | 'up' =
    recentClose < priorClose - 0.5 ? 'down' :
    recentClose > priorClose + 0.5 ? 'up' : 'flat';

  const volumeDirection: 'rising' | 'flat' | 'falling' =
    priorVol > 0
      ? recentVol / priorVol > 1.15 ? 'rising' :
        recentVol / priorVol < 0.85 ? 'falling' : 'flat'
      : 'flat';

  return {
    priceDirection,
    volumeDirection,
    bearishExhaustion: priceDirection === 'down' && volumeDirection === 'falling',
    cliffConfirmed:    priceDirection === 'down' && volumeDirection === 'rising',
  };
}

// ── Stochastic %K ─────────────────────────────────────────────────────────────

/**
 * Stochastic %K (fast, no smoothing) over `period` bars.
 * Below 20 = oversold. Above 80 = overbought.
 * Complements RSI: RSI is momentum-based, Stochastic is price-location-in-range.
 */
export function computeStochastic(candles: readonly OHLCVBar[], period = 14): number | null {
  if (candles.length < period) return null;
  const window = candles.slice(-period);
  const highestHigh = Math.max(...window.map(b => b.high));
  const lowestLow   = Math.min(...window.map(b => b.low));
  if (highestHigh === lowestLow) return 50;
  const close = candles[candles.length - 1]!.close;
  return Number(((close - lowestLow) / (highestHigh - lowestLow) * 100).toFixed(2));
}

// ── Buy-side structure helpers ───────────────────────────────────────────────

/** Realized volatility as std-dev of per-bar close deltas (in cents). */
function computeRealizedVolatility(closes: readonly number[], lookback = 20): number | null {
  if (closes.length < lookback + 1) return null;
  const slice = closes.slice(-(lookback + 1));
  const deltas: number[] = [];
  for (let i = 1; i < slice.length; i++) {
    deltas.push(slice[i]! - slice[i - 1]!);
  }
  if (!deltas.length) return null;
  const mean = deltas.reduce((a, b) => a + b, 0) / deltas.length;
  const variance = deltas.reduce((acc, d) => acc + (d - mean) ** 2, 0) / deltas.length;
  return Math.sqrt(variance);
}

interface LowEstablishmentResult {
  lowPrice: number;
  lowIndex: number;
  barsSinceLow: number;
  reboundCents: number;
  established: boolean;
}

/**
 * A dip is considered "established" only after:
 * 1) local low is printed,
 * 2) no lower low appears for `holdoffBars`,
 * 3) price has rebounded by at least `minRebound` cents.
 */
function analyzeLowEstablishment(
  candles: readonly OHLCVBar[],
  holdoffBars: number,
  minRebound: number,
): LowEstablishmentResult | null {
  if (candles.length < holdoffBars + 2) return null;

  const n = candles.length;
  const windowSize = Math.min(24, n);
  const start = n - windowSize;
  const window = candles.slice(start);

  let minLow = Number.POSITIVE_INFINITY;
  let minOffset = 0;
  for (let i = 0; i < window.length; i++) {
    const low = window[i]!.low;
    if (low < minLow) {
      minLow = low;
      minOffset = i;
    }
  }

  const lowIndex = start + minOffset;
  const barsSinceLow = n - 1 - lowIndex;
  const lastClose = candles[n - 1]!.close;
  const reboundCents = lastClose - minLow;

  const afterLow = candles.slice(lowIndex + 1);
  const madeLowerLowAfter = afterLow.some(bar => bar.low < minLow - 0.01);

  return {
    lowPrice: minLow,
    lowIndex,
    barsSinceLow,
    reboundCents,
    established:
      barsSinceLow >= holdoffBars &&
      !madeLowerLowAfter &&
      reboundCents >= minRebound,
  };
}

// ── Trade Signal ──────────────────────────────────────────────────────────────

export type TradeDirection = 'BUY' | 'SELL' | 'WAIT';

export interface TradeSignalInputs {
  closes: readonly number[];
  candles: readonly OHLCVBar[];
  imbalance: number | null;      // imbalanceTop5 (−100 → +100)
  pressure: number | null;       // impliedPressurePct (−100 → +100)
  flowNet: number;               // aggressorFlow.net (signed contracts)
  flowTotal: number;             // yesVolume + noVolume
  spreadLatest: number | null;
  spreadP90: number | null;
  bid: number | null;            // cents
  ask: number | null;            // cents
  last: number | null;           // cents
}

export interface TradeSignalResult {
  direction: TradeDirection;
  confidence: number;            // dominant side score (for badge label)
  buyScore: number;              // 0–100 independent BUY strength
  sellScore: number;             // 0–100 independent SELL strength
  entryNote: string;
  stopNote: string;
  targetNote: string;
  reasons: readonly string[];
  tradeable: boolean;
}

type SignalProfileName = 'strict' | 'fast' | 'open';

interface SignalProfile {
  name: SignalProfileName;
  holdoffBars: number;
  minReboundFloor: number;
  minReboundVolMultiplier: number;
  dynamicCapBase: number;
  dynamicCapMin: number;
  dynamicCapVolSlope: number;
  hardCap: number;
  requiredStrongConfirmations: number;
  strongPressureThreshold: number;
  strongFlowRatioThreshold: number;
  strongImbalanceThreshold: number;
  rsiRecoveryMin: number;
  rsiRecoveryMax: number;
  rsiRecoverySlopeMin: number;
  emaReclaimBase: number;
  emaReclaimVolMultiplier: number;
  trendRocBase: number;
  trendRocVolMultiplier: number;
  trendNeedsThreeBars: boolean;
  buyScoreMin: number;
  buyVsSellGapMin: number;
  buyPenaltyMode: 'multiplicative' | 'additive';
  additiveLowPenalty: number;
  additiveStrongPenalty: number;
  additiveTrendPenalty: number;
}

const STRICT_PROFILE: SignalProfile = {
  name: 'strict',
  holdoffBars: 4,
  minReboundFloor: 0.8,
  minReboundVolMultiplier: 1.2,
  dynamicCapBase: 80,
  dynamicCapMin: 62,
  dynamicCapVolSlope: 7,
  hardCap: 95,
  requiredStrongConfirmations: 3,
  strongPressureThreshold: 12,
  strongFlowRatioThreshold: 0.25,
  strongImbalanceThreshold: 20,
  rsiRecoveryMin: 38,
  rsiRecoveryMax: 55,
  rsiRecoverySlopeMin: 2,
  emaReclaimBase: 0.35,
  emaReclaimVolMultiplier: 0.5,
  trendRocBase: 0.12,
  trendRocVolMultiplier: 0.15,
  trendNeedsThreeBars: true,
  buyScoreMin: 60,
  buyVsSellGapMin: 12,
  buyPenaltyMode: 'multiplicative',
  additiveLowPenalty: 12,
  additiveStrongPenalty: 10,
  additiveTrendPenalty: 8,
};

const FAST_PROFILE: SignalProfile = {
  name: 'fast',
  holdoffBars: 1,
  minReboundFloor: 0.35,
  minReboundVolMultiplier: 0.75,
  dynamicCapBase: 88,
  dynamicCapMin: 70,
  dynamicCapVolSlope: 3,
  hardCap: 95,
  requiredStrongConfirmations: 1,
  strongPressureThreshold: 6,
  strongFlowRatioThreshold: 0.1,
  strongImbalanceThreshold: 10,
  rsiRecoveryMin: 32,
  rsiRecoveryMax: 68,
  rsiRecoverySlopeMin: 0.4,
  emaReclaimBase: 0.15,
  emaReclaimVolMultiplier: 0.2,
  trendRocBase: -0.05,
  trendRocVolMultiplier: 0.02,
  trendNeedsThreeBars: false,
  buyScoreMin: 44,
  buyVsSellGapMin: 4,
  buyPenaltyMode: 'additive',
  additiveLowPenalty: 4,
  additiveStrongPenalty: 3,
  additiveTrendPenalty: 2,
};

const OPEN_PROFILE: SignalProfile = {
  // OPEN mode exists to reduce false negatives in high-whipsaw game markets.
  // It is intentionally looser than FAST, but still bounded by cliff and top-cap safeguards.
  name: 'open',
  holdoffBars: 1,
  minReboundFloor: 0.2,
  minReboundVolMultiplier: 0.6,
  dynamicCapBase: 90,
  dynamicCapMin: 72,
  dynamicCapVolSlope: 2,
  hardCap: 95,
  requiredStrongConfirmations: 1,
  strongPressureThreshold: 4,
  strongFlowRatioThreshold: 0.06,
  strongImbalanceThreshold: 8,
  rsiRecoveryMin: 30,
  rsiRecoveryMax: 72,
  rsiRecoverySlopeMin: 0.2,
  emaReclaimBase: 0.1,
  emaReclaimVolMultiplier: 0.12,
  trendRocBase: -0.12,
  trendRocVolMultiplier: -0.03,
  trendNeedsThreeBars: false,
  buyScoreMin: 38,
  buyVsSellGapMin: 2,
  buyPenaltyMode: 'additive',
  additiveLowPenalty: 2,
  additiveStrongPenalty: 1,
  additiveTrendPenalty: 1,
};

/**
 * Split-scoring timing signal.
 *
 * buyScore  (0–100): exhaustion / reversal evidence.
 *   High = oversold + book/tape reversal forming.
 * sellScore (0–100): extension / deterioration evidence.
 *   High = overbought or active cliff.
 *
 * Mutual exclusion is structural: the same RSI value scores only one side;
 * the same EMA distance scores only one direction; cliff actively penalises BUY.
 * Both scores are near-zero when the market is in a neutral, undecided state.
 *
 *   BUY raw max  = 106  (RSI 35 + EMA 20 + Stoch 12 + Wick 8 + Exhaust 8 + Pressure 15 + Flow 12 + Imbalance 12)
 *   SELL raw max = 129  (RSI 35 + EMA 20 + Cliff 35 + Pressure 15 + Flow 12 + Imbalance 12)
 *
 *   buyScore  = clamp(buyRaw  / 106 × 100, 0, 100)
 *   sellScore = clamp(sellRaw / 129 × 100, 0, 100)
 *
 *   BUY  — buyScore  > 55 AND buyScore  > sellScore + 10 AND hasConfirmation
 *   SELL — sellScore > 55 AND sellScore > buyScore  + 10
 *   WAIT — everything else
 */
function computeTradeSignalWithProfile(
  inputs: TradeSignalInputs,
  profile: SignalProfile,
): TradeSignalResult {
  const { closes, candles, imbalance, pressure, flowNet, flowTotal,
          spreadLatest, spreadP90, bid, ask, last } = inputs;

  const rsi       = computeRSI(closes, 14);
  const ema20     = computeEMAValue(closes, 20);
  const velocity  = computeVelocity(closes);
  const volDiv    = computeVolumeDivergence(candles);
  const stoch     = computeStochastic(candles, 14);
  const lowerWick = recentLowerWickRatio(candles);
  const prevRsi   = closes.length > 15 ? computeRSI(closes.slice(0, -1), 14) : null;
  const price     = last ?? (bid !== null && ask !== null ? (bid + ask) / 2 : null);
  const tradeable = spreadLatest === null || spreadP90 === null || spreadLatest <= spreadP90;

  // Strict-confirmed BUY architecture configuration.
  // Bias is deliberately conservative: fewer entries, higher quality.
  const holdoffBars = profile.holdoffBars;
  const volatility = computeRealizedVolatility(closes, 20);
  const minRebound = Math.max(profile.minReboundFloor, (volatility ?? 0.8) * profile.minReboundVolMultiplier);
  const lowEstablishment = analyzeLowEstablishment(candles, holdoffBars, minRebound);

  // Volatility-aware buy cap with absolute hard cap at 95c.
  // Higher vol -> lower cap to avoid chasing noisy late moves.
  const dynamicBuyCap = Math.min(
    profile.hardCap,
    Math.max(profile.dynamicCapMin, profile.dynamicCapBase - (volatility ?? 1) * profile.dynamicCapVolSlope),
  );

  const isCliff =
    velocity !== null &&
    velocity.acceleratingDown &&
    velocity.recentROC < -1 &&
    (volDiv?.cliffConfirmed ?? false);

  // Dynamic top gate (volatility-aware), with absolute 95c hard ceiling.
  const priceAboveTopGate    = price !== null && price >= dynamicBuyCap;
  const hardCapReached       = price !== null && price >= profile.hardCap;
  const priceBelowBottomGate = price !== null && price <= 25;

  const reasons: string[] = [];
  let buyRaw  = 0;
  let sellRaw = 0;

  // ── 1. RSI ────────────────────────────────────────────────────────────────
  // Oversold scores BUY only; overbought scores SELL only.
  // The same RSI value cannot drive both sides high simultaneously.
  if (rsi !== null) {
    if (rsi < 25) {
      buyRaw += 35;
      reasons.push(`RSI ${rsi.toFixed(1)} — extreme oversold`);
    } else if (rsi < 35) {
      buyRaw += 25;
      reasons.push(`RSI ${rsi.toFixed(1)} — oversold zone`);
    } else if (rsi < 45) {
      buyRaw += 12;
      reasons.push(`RSI ${rsi.toFixed(1)} — approaching oversold`);
    } else if (rsi > 75) {
      sellRaw += 35;
      reasons.push(`RSI ${rsi.toFixed(1)} — extreme overbought`);
    } else if (rsi > 65) {
      sellRaw += 25;
      reasons.push(`RSI ${rsi.toFixed(1)} — overbought zone`);
    } else if (rsi > 55) {
      sellRaw += 12;
    }
  }

  // ── 2. EMA distance ───────────────────────────────────────────────────────
  // Below EMA scores BUY; above EMA scores SELL.
  if (ema20 !== null && price !== null) {
    const dist = ema20 - price; // positive = price BELOW EMA
    if (dist > 5) {
      buyRaw += 20;
      reasons.push(`Price ${dist.toFixed(1)}¢ below EMA — deeply stretched`);
    } else if (dist > 2) {
      buyRaw += 13;
      reasons.push(`Price ${dist.toFixed(1)}¢ below EMA — pullback zone`);
    } else if (dist > 0) {
      buyRaw += 5;
    } else if (dist < -5) {
      sellRaw += 20;
      reasons.push(`Price ${(-dist).toFixed(1)}¢ above EMA — overextended`);
    } else if (dist < -2) {
      sellRaw += 13;
      reasons.push(`Price ${(-dist).toFixed(1)}¢ above EMA`);
    } else if (dist < 0) {
      sellRaw += 5;
    }
  }

  // ── 2b. Binary terminus ─────────────────────────────────────────────────
  // Near the ceiling the probability is already priced in and YES buyers
  // have terrible R/R. Score SELL explicitly so the split bar reflects reality.
  // Near the floor, YES is historically cheap — small BUY boost.
  if (price !== null) {
    if (hardCapReached) {
      sellRaw += 35;
      reasons.push(`Price ${price.toFixed(0)}¢ — hard cap reached, BUY disabled`);
    } else if (price >= 90) {
      sellRaw += 25;
      reasons.push(`Price ${price.toFixed(0)}¢ — near binary ceiling, R/R favours exit`);
    } else if (price >= 80) {
      sellRaw += 12;
      reasons.push(`Price ${price.toFixed(0)}¢ — elevated, limited upside for YES buyers`);
    } else if (price <= 10) {
      buyRaw += 12;
    } else if (price <= 20) {
      buyRaw += 6;
    }
  }

  // ── 3. Stochastic (BUY only) ──────────────────────────────────────────────
  if (stoch !== null) {
    if (stoch < 20) {
      buyRaw += 12;
      reasons.push(`Stochastic ${stoch.toFixed(0)} — price at cycle low`);
    } else if (stoch < 35) {
      buyRaw += 6;
    }
  }

  // ── 4. Cliff / velocity (SELL only, BUY penalty) ──────────────────────────
  if (isCliff) {
    sellRaw += 35;
    buyRaw  -= 25; // active cliff = hard penalty on BUY side
    reasons.push(`Cliff: ${velocity!.recentROC.toFixed(2)}¢/bar — accelerating fall`);
    reasons.push('Volume rising on down-move — sellers in control');
  } else if (velocity !== null && velocity.acceleratingDown && velocity.recentROC < -0.5) {
    sellRaw += 15;
    reasons.push(`Velocity accelerating (${velocity.recentROC.toFixed(2)}¢/bar)`);
  }

  // ── 4b. Hammer / lower wick (BUY only) ────────────────────────────────────
  const wickConfirms = lowerWick !== null && lowerWick > 0.35;
  if (!isCliff && wickConfirms) {
    if (lowerWick! > 0.55) {
      buyRaw += 8;
      reasons.push(`Strong hammer (${(lowerWick! * 100).toFixed(0)}% wick) — rejection at low`);
    } else {
      buyRaw += 5;
      reasons.push(`Lower wick (${(lowerWick! * 100).toFixed(0)}% of range)`);
    }
  }

  // ── 4c. Bearish exhaustion (BUY only) ─────────────────────────────────────
  const exhaustionConfirms = volDiv?.bearishExhaustion ?? false;
  if (exhaustionConfirms) {
    buyRaw += 8;
    reasons.push('Volume falling on down-move — selling pressure drying up');
  }

  // ── 5. Pressure ───────────────────────────────────────────────────────────
  let pressureConfirms = false;
  let strongPressure = false;
  if (pressure !== null) {
    if (pressure > 10) {
      buyRaw += 15;
      // Positive pressure at high prices is momentum continuation, not reversal
      pressureConfirms = !priceAboveTopGate;
      strongPressure = pressure > profile.strongPressureThreshold && !priceAboveTopGate;
      reasons.push(`Pressure +${pressure.toFixed(0)}% — buyers at mid`);
    } else if (pressure > 2) {
      buyRaw += 8;
      pressureConfirms = !priceAboveTopGate;
    } else if (pressure < -10) {
      sellRaw += 15;
      reasons.push(`Pressure ${pressure.toFixed(0)}% — sellers dominant`);
    } else if (pressure < -2) {
      sellRaw += 8;
    }
  }

  // ── 6. Tape flow ──────────────────────────────────────────────────────────
  let flowConfirms = false;
  let strongFlow = false;
  if (flowTotal > 0) {
    const ratio = flowNet / flowTotal;
    if (ratio > 0.2) {
      buyRaw += 12;
      // YES tape buying at top = chasing momentum, not accumulation at a low
      flowConfirms = !priceAboveTopGate;
      strongFlow = ratio > profile.strongFlowRatioThreshold && !priceAboveTopGate;
      reasons.push(`Tape: YES net +${flowNet} (last 80)`);
    } else if (ratio > 0.05) {
      buyRaw += 6;
      flowConfirms = !priceAboveTopGate;
    } else if (ratio < -0.2) {
      sellRaw += 12;
      reasons.push(`Tape: NO net ${flowNet} (last 80)`);
    } else if (ratio < -0.05) {
      sellRaw += 6;
    }
  }

  // ── 7. Book imbalance ─────────────────────────────────────────────────────
  let imbalanceConfirms = false;
  let strongImbalance = false;
  if (imbalance !== null) {
    if (imbalance > 15) {
      buyRaw += 12;
      // Bid-heavy book at high prices = buyers chasing the top, not accumulating a low
      imbalanceConfirms = !priceAboveTopGate;
      strongImbalance = imbalance > profile.strongImbalanceThreshold && !priceAboveTopGate;
      reasons.push(`Book ${imbalance.toFixed(0)}% bid-heavy`);
    } else if (imbalance > 0) {
      buyRaw += 6;
      imbalanceConfirms = !priceAboveTopGate;
    } else if (imbalance < -15) {
      sellRaw += 12;
      reasons.push(`Book ${(-imbalance).toFixed(0)}% ask-heavy`);
    } else if (imbalance < 0) {
      sellRaw += 6;
    }
  }

  // ── Strict BUY confirmation framework ─────────────────────────────────────
  // 3-of-5 strong confirmations are required before BUY can trigger.
  const lowEstablished = (lowEstablishment?.established ?? false) && !isCliff;
  const barsUntilEstablished =
    lowEstablishment === null
      ? holdoffBars
      : Math.max(0, holdoffBars - lowEstablishment.barsSinceLow);

  const strongRsiRecovery =
    rsi !== null &&
    prevRsi !== null &&
    rsi >= profile.rsiRecoveryMin &&
    rsi <= profile.rsiRecoveryMax &&
    rsi - prevRsi >= profile.rsiRecoverySlopeMin;

  const strongEmaReclaim =
    ema20 !== null &&
    price !== null &&
    price > ema20 + Math.max(profile.emaReclaimBase, (volatility ?? 0.7) * profile.emaReclaimVolMultiplier);

  const strongSignals = [strongRsiRecovery, strongEmaReclaim, strongPressure, strongFlow, strongImbalance];
  const strongConfirmationCount = strongSignals.filter(Boolean).length;
  const hasStrongConfirmation = strongConfirmationCount >= profile.requiredStrongConfirmations;

  // Trend follow-through: require positive momentum after low is established.
  const trendFollowThrough =
    (profile.trendNeedsThreeBars
      ? closes.length >= 3 &&
        closes[closes.length - 1]! > closes[closes.length - 2]! &&
        closes[closes.length - 2]! >= closes[closes.length - 3]!
      : closes.length >= 2 && closes[closes.length - 1]! > closes[closes.length - 2]!) &&
    (velocity === null || velocity.recentROC > Math.max(profile.trendRocBase, (volatility ?? 0.8) * profile.trendRocVolMultiplier));

  // If strict prerequisites are not met, dampen BUY score to avoid false optimism.
  if (profile.buyPenaltyMode === 'multiplicative') {
    let buyQualityMultiplier = 1;
    if (!lowEstablished) buyQualityMultiplier *= 0.5;
    if (!hasStrongConfirmation) buyQualityMultiplier *= 0.6;
    if (!trendFollowThrough) buyQualityMultiplier *= 0.7;
    buyRaw *= buyQualityMultiplier;
  } else {
    if (!lowEstablished) buyRaw -= profile.additiveLowPenalty;
    if (!hasStrongConfirmation) buyRaw -= profile.additiveStrongPenalty;
    if (!trendFollowThrough) buyRaw -= profile.additiveTrendPenalty;
  }

  // ── Hard binary R/R gate ──────────────────────────────────────────────────
  // After all indicator scoring, zero out the structurally-unwinnable side.
  // This overrides any accumulated raw points — no indicator combo should
  // produce a BUY signal above the dynamic cap or a SELL signal at 25¢ and below.
  if (priceAboveTopGate)    buyRaw  = 0;
  if (priceBelowBottomGate) sellRaw = 0;

  // ── Normalize to 0–100 ────────────────────────────────────────────────────
  const buyScore  = Math.round(Math.max(0, Math.min(100, buyRaw  / 106 * 100)));
  const sellScore = Math.round(Math.max(0, Math.min(100, sellRaw / 129 * 100)));

  // ── Direction gate ────────────────────────────────────────────────────────
  const hasConfirmation =
    pressureConfirms || flowConfirms || imbalanceConfirms ||
    wickConfirms || exhaustionConfirms ||
    ((profile.name === 'fast' || profile.name === 'open') && strongRsiRecovery);

  // For BUY: the downturn must be at least decelerating before entry.
  // Don't call a bottom while price is still in active momentum down.
  // An accelerating fall (even below cliff threshold) blocks BUY from firing.
  const velocityRecovering = velocity === null || !velocity.acceleratingDown || velocity.recentROC >= 0;

  const fastStructuralQualityVotes = [
    lowEstablished,
    hasStrongConfirmation,
    trendFollowThrough,
    velocityRecovering,
  ].filter(Boolean).length;

  const strictBuyEligible =
    hasConfirmation &&
    velocityRecovering &&
    lowEstablished &&
    hasStrongConfirmation &&
    trendFollowThrough &&
    !priceAboveTopGate;

  const fastBuyEligible =
    hasConfirmation &&
    !isCliff &&
    (velocity === null || velocity.recentROC > -0.35) &&
    fastStructuralQualityVotes >= 2 &&
    !priceAboveTopGate;

  // OPEN mode uses a wider entry net to intentionally capture early reversals
  // that strict/fast can miss in sports whipsaw. Guardrails remain in place:
  //  - no BUY during confirmed cliffing
  //  - no BUY above dynamic top gate
  //  - minimum structural quality and non-catastrophic momentum
  const openBuyEligible =
    (hasConfirmation || strongRsiRecovery) &&
    !isCliff &&
    (velocity === null || velocity.recentROC > -0.6) &&
    fastStructuralQualityVotes >= 1 &&
    !priceAboveTopGate;

  const direction: TradeDirection =
    buyScore  > profile.buyScoreMin &&
    buyScore  > sellScore + profile.buyVsSellGapMin &&
    (
      profile.name === 'strict'
        ? strictBuyEligible
        : profile.name === 'fast'
          ? fastBuyEligible
          : openBuyEligible
    ) ? 'BUY'  :
    sellScore > 55 && sellScore > buyScore + 10 ? 'SELL' :
                                                 'WAIT';

  const confidence =
    direction === 'BUY'  ? buyScore  :
    direction === 'SELL' ? sellScore :
    Math.max(buyScore, sellScore);

  // ── Entry / stop / target notes ───────────────────────────────────────────
  let entryNote: string;
  let stopNote: string;
  let targetNote: string;

  if (direction === 'BUY') {
    entryNote  = ask !== null ? `Ask at ${ask}¢ (buy YES)` : 'At Ask (buy YES)';
    stopNote   = lowEstablishment !== null ? `Below established low ${lowEstablishment.lowPrice.toFixed(1)}¢` :
                 ema20 !== null ? `Below EMA ~${ema20.toFixed(1)}¢` : 'Below EMA — see chart';
    targetNote = 'Next resistance — see chart';
  } else if (direction === 'SELL') {
    entryNote  = bid !== null ? `Bid ${bid}¢ — consider exiting YES` : 'Near Bid — consider exit';
    stopNote   = '—';
    targetNote = ema20 !== null ? `EMA ~${ema20.toFixed(1)}¢` : 'See chart';
  } else if (priceAboveTopGate) {
    const upside = price !== null ? (100 - price).toFixed(0) : '?';
    const cost   = price !== null ? price.toFixed(0) : '?';
    entryNote  = `At ${cost}¢ — no BUY above cap ${dynamicBuyCap.toFixed(1)}¢: risking ${cost}¢ to make ${upside}¢`;
    stopNote   = '—';
    targetNote = '—';
  } else if (!lowEstablished) {
    entryNote  = `Low not established yet — holdoff ${barsUntilEstablished} more bar${barsUntilEstablished === 1 ? '' : 's'}`;
    stopNote   = '—';
    targetNote = '—';
  } else if (!hasStrongConfirmation) {
    entryNote  = `Need stronger reversal evidence (${strongConfirmationCount}/5 strong confirmations, need ${profile.requiredStrongConfirmations})`;
    stopNote   = '—';
    targetNote = '—';
  } else if (!trendFollowThrough) {
    entryNote  = 'Reversal seen, but trend not confirmed yet — wait for follow-through bars';
    stopNote   = '—';
    targetNote = '—';
  } else if (priceBelowBottomGate) {
    entryNote  = `At ${price!.toFixed(0)}¢ — no SELL setup at this level`;
    stopNote   = '—';
    targetNote = '—';
  } else if (buyScore > 45 && !hasConfirmation) {
    entryNote  = 'Oversold but no reversal signal yet — wait for book/tape flip';
    stopNote   = '—';
    targetNote = '—';
  } else if (!velocityRecovering) {
    entryNote  = 'Downtrend still accelerating — wait for momentum to stall before entry';
    stopNote   = '—';
    targetNote = '—';
  } else {
    entryNote  = 'No setup — await RSI < 40, price below EMA + reversal signal';
    stopNote   = '—';
    targetNote = '—';
  }

  if (!lowEstablished) {
    reasons.push(`Low holdoff active: ${barsUntilEstablished} bar${barsUntilEstablished === 1 ? '' : 's'} remaining`);
  }
  if (!hasStrongConfirmation) {
    reasons.push(`Strong confirmations: ${strongConfirmationCount}/5 (need ${profile.requiredStrongConfirmations})`);
  }
  if (!trendFollowThrough) {
    reasons.push('Trend follow-through not confirmed yet');
  }
  if ((profile.name === 'fast' || profile.name === 'open') && direction !== 'BUY') {
    reasons.push(`Fast structural quality: ${fastStructuralQualityVotes}/4 (need >=2)`);
  }
  if (priceAboveTopGate) {
    reasons.push(`BUY capped above ${dynamicBuyCap.toFixed(1)}¢ in current volatility regime`);
  }

  return {
    direction,
    confidence,
    buyScore,
    sellScore,
    entryNote,
    stopNote,
    targetNote,
    reasons: reasons.slice(0, 6),
    tradeable,
  };
}

export function computeTradeSignal(inputs: TradeSignalInputs): TradeSignalResult {
  return computeTradeSignalWithProfile(inputs, STRICT_PROFILE);
}

export function computeTradeSignalFast(inputs: TradeSignalInputs): TradeSignalResult {
  return computeTradeSignalWithProfile(inputs, FAST_PROFILE);
}

export function computeTradeSignalOpen(inputs: TradeSignalInputs): TradeSignalResult {
  return computeTradeSignalWithProfile(inputs, OPEN_PROFILE);
}

// Alias that exposes intent in the UI while preserving strict/fast API mode names.
export function computeTradeSignalLoose(inputs: TradeSignalInputs): TradeSignalResult {
  return computeTradeSignalFast(inputs);
}
