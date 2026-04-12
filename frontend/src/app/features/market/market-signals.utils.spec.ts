import { describe, expect, it } from 'vitest';

import { computeTradeSignal, computeTradeSignalFast, computeTradeSignalLoose, computeTradeSignalOpen, computeVelocity, type TradeSignalInputs } from './market-signals.utils';

type Candle = { open: number; high: number; low: number; close: number; volume: number };

function buildCandles(closes: readonly number[], volume = 100): readonly Candle[] {
  return closes.map((close, idx) => {
    const open = idx > 0 ? closes[idx - 1]! : close;
    const high = Math.max(open, close) + 0.6;
    const low = Math.min(open, close) - 0.6;
    return { open, high, low, close, volume };
  });
}

function makeInputs(
  closes: readonly number[],
  overrides: Partial<TradeSignalInputs> = {},
): TradeSignalInputs {
  const candles = buildCandles(closes);
  return {
    closes,
    candles,
    imbalance: 0,
    pressure: 0,
    flowNet: 0,
    flowTotal: 1,
    spreadLatest: 1,
    spreadP90: 2,
    bid: closes[closes.length - 1]! - 1,
    ask: closes[closes.length - 1]! + 1,
    last: closes[closes.length - 1]!,
    ...overrides,
  };
}

describe('computeTradeSignal strict BUY gating', () => {
  it('never emits BUY above dynamic cap and hard cap conditions', () => {
    const closes = [70, 72, 74, 76, 78, 80, 84, 88, 92, 95, 97, 97];
    const signal = computeTradeSignal(
      makeInputs(closes, {
        pressure: 20,
        flowNet: 300,
        flowTotal: 800,
        imbalance: 30,
        last: 97,
        bid: 96,
        ask: 98,
      }),
    );

    expect(signal.direction).not.toBe('BUY');
    expect(signal.buyScore).toBe(0);
    expect(signal.entryNote).toContain('no BUY above cap');
  });

  it('blocks BUY while low-holdoff bars are not complete', () => {
    const closes = [60, 58, 56, 54, 52, 50, 48, 46, 44, 46, 48];
    const signal = computeTradeSignal(
      makeInputs(closes, {
        pressure: 18,
        flowNet: 220,
        flowTotal: 700,
        imbalance: 24,
      }),
    );

    expect(signal.direction).toBe('WAIT');
    expect(signal.entryNote).toContain('Low not established yet');
  });

  it('requires at least 3 of 5 strong confirmations for BUY eligibility', () => {
    const closes = [60, 58, 56, 54, 52, 50, 48, 46, 44, 45, 46, 47, 47, 47, 47];
    const signal = computeTradeSignal(
      makeInputs(closes, {
        pressure: 6,
        flowNet: 40,
        flowTotal: 500,
        imbalance: 8,
      }),
    );

    expect(signal.direction).toBe('WAIT');
    expect(signal.entryNote).toContain('Need stronger reversal evidence');
  });

  it('allows BUY only when low is established and strong confirmation/trend gates pass', () => {
    const closes = [
      95, 92, 89, 86, 83, 80, 77, 74, 71, 68, 65, 62, 59, 56, 53, 50, 47, 44, 41, 38,
      35, 32, 29, 26, 24, 23, 24, 25, 26, 27,
    ];
    const signal = computeTradeSignal(
      makeInputs(closes, {
        pressure: 18,
        flowNet: 420,
        flowTotal: 1000,
        imbalance: 28,
        last: 27,
        bid: 26,
        ask: 28,
      }),
    );

    expect(signal.direction).toBe('BUY');
    expect(signal.buyScore).toBeGreaterThan(60);
    expect(signal.entryNote).toContain('buy YES');
  });

  it('fast profile can trigger BUY in setups where strict remains WAIT', () => {
    const closes = [
      80, 76, 72, 68, 64, 60, 56, 52, 48, 44, 40, 36, 33, 30, 28, 27,
      28, 30, 33, 37,
    ];

    const inputs = makeInputs(closes, {
      pressure: 11,
      flowNet: 260,
      flowTotal: 900,
      imbalance: 16,
      last: 37,
      bid: 36,
      ask: 38,
    });

    const strictSignal = computeTradeSignal(inputs);
    const fastSignal = computeTradeSignalFast(inputs);

    expect(strictSignal.direction).toBe('WAIT');
    expect(fastSignal.direction).toBe('BUY');
    expect(fastSignal.buyScore).toBeGreaterThanOrEqual(strictSignal.buyScore);
  });

  it('loose alias matches fast profile exactly', () => {
    const closes = [
      85, 82, 79, 76, 73, 70, 67, 64, 61, 58, 55, 52, 49, 46, 43, 41, 42, 44, 46,
    ];
    const inputs = makeInputs(closes, {
      pressure: 9,
      flowNet: 170,
      flowTotal: 700,
      imbalance: 12,
      last: 46,
      bid: 45,
      ask: 47,
    });

    const fastSignal = computeTradeSignalFast(inputs);
    const looseSignal = computeTradeSignalLoose(inputs);

    expect(looseSignal).toEqual(fastSignal);
  });

  it('does not treat slowing upward momentum as accelerating down', () => {
    const vel = computeVelocity([30, 31, 33, 36, 38, 39, 40]);
    expect(vel).not.toBeNull();
    expect(vel!.recentROC).toBeGreaterThan(0);
    expect(vel!.accelerating).toBe(true);
    expect(vel!.acceleratingDown).toBe(false);
  });

  it('loosened mode can BUY when quality gates are mixed but reversal is underway', () => {
    const closes = [
      80, 76, 72, 68, 64, 60, 56, 52, 48, 44, 40, 36, 32, 30, 29,
      30, 31, 33, 36, 38, 39, 40,
    ];
    const signal = computeTradeSignalLoose(
      makeInputs(closes, {
        pressure: 9,
        flowNet: 160,
        flowTotal: 700,
        imbalance: 11,
        last: 40,
        bid: 39,
        ask: 41,
      }),
    );

    expect(signal.direction).toBe('BUY');
  });

  it('open mode is at least as permissive as loosened in early reversal setups', () => {
    const closes = [
      74, 70, 66, 62, 58, 54, 50, 46, 42, 38, 35, 33, 32,
      33, 34, 35, 36,
    ];

    const inputs = makeInputs(closes, {
      pressure: 3,
      flowNet: 50,
      flowTotal: 700,
      imbalance: 6,
      last: 36,
      bid: 35,
      ask: 37,
    });

    const loose = computeTradeSignalLoose(inputs);
    const open = computeTradeSignalOpen(inputs);

    expect(open.buyScore).toBeGreaterThanOrEqual(loose.buyScore);
    expect(open.direction === 'BUY' || loose.direction === 'BUY').toBe(true);
  });
});
