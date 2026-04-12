import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
} from '@angular/core';

export type HelpCardKey =
  | 'imbalance'
  | 'microprice'
  | 'spread'
  | 'depth'
  | 'dispersion'
  | 'intraday'
  | 'candle'
  | 'rsi'
  | 'signal';

type RowHelp = { label: string; meaning: string };

type HelpEntry = {
  title: string;
  what: string;
  timing: string;
  howToUse: string;
  rows: readonly RowHelp[];
};

const HELP: Record<HelpCardKey, HelpEntry> = {
  imbalance: {
    title: 'Orderbook Imbalance',
    what:
      'Compares the total resting bid volume on the YES side against resting ask volume ' +
      'across the nearest price levels. A positive number means buyers are sitting in the ' +
      'book more heavily than sellers near the current price; negative means sellers dominate.',
    timing:
      'Microsecond. Every individual order placement, cancellation, or size change in the ' +
      'book recalculates this instantly — it is the fastest-moving number on this screen. ' +
      'You are looking at a snapshot of right now; by the time you read it, it may already be different.',
    howToUse:
      'Do not trade a single snapshot. Watch the direction of change over 5–10 seconds. ' +
      'Persistently positive Top 5 (buyers consistently outnumber sellers at the near levels) ' +
      'is a short-term upward pressure signal. A sudden flip from strongly positive to deeply ' +
      'negative often precedes a price drop. Use it as a filter: enter YES when imbalance is ' +
      'consistently positive and trending higher across consecutive ticks.',
    rows: [
      {
        label: 'Top 5',
        meaning:
          'Imbalance across the 5 price levels nearest to the current price. More sensitive ' +
          'and noisier — reacts to every small order change. Best for very short-term signals.',
      },
      {
        label: 'Top 10',
        meaning:
          'Imbalance across the 10 nearest levels. Smoother than Top 5. When both Top 5 and ' +
          'Top 10 agree in direction, the signal is meaningfully stronger.',
      },
    ],
  },

  microprice: {
    title: 'Microprice / Pressure',
    what:
      'The simple midpoint ((best bid + best ask) / 2) ignores volume. Microprice corrects ' +
      'this by weighting the mid toward whichever side has more resting contracts. If 500 ' +
      'contracts are bidding at 50¢ and only 100 are offered at 51¢, the microprice moves ' +
      'closer to 50¢ — reflecting that buyers have more presence. Pressure is how far the ' +
      'microprice has deviated from the raw mid, as a percentage of the spread.',
    timing:
      'Sub-second. Updates any time a bid or ask quantity changes at any level — even if the ' +
      'price itself does not move. Slightly smoother than raw imbalance but still ticks ' +
      'continuously with order flow. Treat it as a near-real-time signal, not a candle-speed one.',
    howToUse:
      'Microprice above the displayed last price signals that the bid side is heavier — a ' +
      'short-term upward lean. Look for sustained positive pressure (microprice consistently ' +
      'above mid for many consecutive seconds) as a sign that the ask side is being absorbed ' +
      'and the price may tick up. A microprice drifting below mid that keeps widening warns ' +
      'that sellers are building inventory and a downward move may follow.',
    rows: [
      {
        label: 'Microprice',
        meaning:
          'Volume-weighted mid price in cents. Compare to the displayed YES Last ' +
          'price — if microprice > last, the market is leaning bullish in the book.',
      },
      {
        label: 'Pressure',
        meaning:
          'Signed deviation of microprice from the raw mid, as % of the spread. ' +
          'Positive = bid-heavy (upward pressure). Negative = ask-heavy (downward pressure).',
      },
    ],
  },

  spread: {
    title: 'Rolling Spread',
    what:
      'The bid-ask spread is the gap between the best YES ask and the best YES bid. It ' +
      'represents the cost of crossing the market immediately — you pay this simply to ' +
      'get filled at the best available price. This tracks the spread over recent candle periods.',
    timing:
      'Sub-second for Latest; per-candle for Mean and P90. The Latest spread refreshes ' +
      'whenever the top of the book changes. Mean and P90 are rolling statistics computed ' +
      'from candle closes, so they drift gradually rather than jumping every tick. ' +
      'Watch Latest for real-time liquidity cost; use Mean/P90 as a stable reference baseline.',
    howToUse:
      'Only enter when the spread is at or below its mean. If Latest >> Mean, the market is ' +
      'momentarily illiquid — wait it out. P90 is your upper bound: when Latest approaches P90, ' +
      'the market is at its widest typical spread; patience almost always saves you ticks. A ' +
      'consistently low P90 means this is a reliably liquid market, safe for active trading.',
    rows: [
      {
        label: 'Latest',
        meaning:
          'Current ask minus bid in cents. This is the immediate cost to get filled with a market order.',
      },
      {
        label: 'Mean',
        meaning: 'Average spread over recent periods. Your baseline for what "normal" liquidity cost looks like here.',
      },
      {
        label: 'P90',
        meaning:
          '90th percentile of recent spreads. When Latest is near P90, the market ' +
          'is unusually wide — delay entry or use a limit order.',
      },
    ],
  },

  depth: {
    title: 'Depth Concentration',
    what:
      'Measures what fraction of all resting YES bid or NO ask volume is stacked at just the ' +
      'top 1 or top 3 price levels. High concentration means a few large orders dominate the ' +
      'book at specific prices; low concentration means volume is spread thinly across many levels.',
    timing:
      'Sub-second. Concentration ratios recompute whenever any resting order at the top levels ' +
      'is placed, resized, or cancelled. A single large order event can flip the reading ' +
      'immediately. It is fast, but not as continuous as imbalance — meaningful jumps are ' +
      'usually caused by a real participant action rather than ambient noise.',
    howToUse:
      'High YES Top1 — a dominant single-price buyer is defending a level. If price dips to ' +
      'that level and holds, that is a support signal. High NO Top3 — a wall of resting sell ' +
      'orders sits near the current price; it will absorb buying pressure and resist a move up. ' +
      'Low concentration on both sides means the book is thin — price can move quickly in ' +
      'either direction with only modest flow.',
    rows: [
      {
        label: 'YES Top3',
        meaning:
          '% of all YES bid volume sitting at the 3 best bid prices. High = concentrated ' +
          'liquidity at a specific level; a large buyer is defending that zone.',
      },
      {
        label: 'NO Top3',
        meaning:
          '% of all NO (ask) volume at the 3 best ask prices. High = a resistance wall ' +
          'sitting just above the current price.',
      },
      {
        label: 'YES Top1',
        meaning:
          '% of all YES bid volume at the single best bid price. Very high (>60%) signals ' +
          'a dominant block buyer sitting at one specific level.',
      },
    ],
  },

  dispersion: {
    title: 'Event Dispersion',
    what:
      'For events with multiple mutually exclusive outcomes (e.g. a tennis match: Player A vs ' +
      'Player B, or a race with several candidates), this measures how spread out the prices ' +
      'of each outcome are. If all outcomes trade near equal prices, the market sees them as ' +
      'roughly equal probability. If one trades near 90¢ and the others near 5¢, the market ' +
      'is strongly opinionated.',
    timing:
      'Trade-driven — updates only when a trade prints or an order moves a best price. ' +
      'In active events this can be every few seconds; in quiet events it may not change ' +
      'for minutes. The number does not tick on order-book noise, only on actual price changes ' +
      'across the event\'s outcomes.',
    howToUse:
      'Low stdev (outcomes clustered near equal prices) = high uncertainty = prices can swing ' +
      'violently on new information; these are higher-variance trades. High stdev = strong ' +
      'market consensus on a favorite. Fading the heavy favorite is a high-risk contrarian ' +
      'bet; only do it if you have information the market does not. Wide range (>80) means ' +
      'one outcome is near-certain — entering that leg has very little upside for the cost.',
    rows: [
      {
        label: 'Outcomes',
        meaning: 'Number of active legs in this event. More outcomes = more ways the market can move against you.',
      },
      {
        label: 'Stdev',
        meaning:
          'Standard deviation of all outcome prices. Near 0 = close race, very uncertain. ' +
          'High = the market strongly favors one side.',
      },
      {
        label: 'Range',
        meaning:
          'Max price minus min price across all outcomes. A range above 80 means one outcome ' +
          'is a near-certainty in the market\'s view.',
      },
    ],
  },

  intraday: {
    title: 'Intraday Return / Drawdown',
    what:
      'Tracks how the YES price has moved today from its first candlestick to now, and how ' +
      'badly it declined at its worst point intraday. Together these paint a picture of whether ' +
      'today\'s move has been clean and directional or choppy and reversal-prone.',
    timing:
      'Per-candle for Return, Max DD, and Bars. These are computed from closed OHLCV bars, ' +
      'so they advance at the candle resolution you have selected (1-min, 5-min, etc.). ' +
      'They will not flicker every second — expect one update per candle close plus ' +
      'a live-price refresh on the current bar.',
    howToUse:
      'Large return + small max drawdown = clean directional move; trend-continuation entries ' +
      'make sense. Large return + large max drawdown = the price has round-tripped badly; fading ' +
      'extremes or using tighter stops is more appropriate. Few bars = not much data yet today ' +
      '— other indicators here are less reliable. Return near 0 with many bars = flat, ' +
      'low-activity market; spread cost is likely your biggest edge factor, not direction.',
    rows: [
      {
        label: 'Return',
        meaning:
          'Total % change from the first bar today to the most recent price. Green = YES has ' +
          'gained today; red = YES has fallen.',
      },
      {
        label: 'Max DD',
        meaning:
          'The largest peak-to-trough decline today. High drawdown relative to return means ' +
          'the move has been noisy and full of reversals.',
      },
      {
        label: 'Bars',
        meaning:
          'Candles with active trading today. Low count = thin data; treat directional signals ' +
          'with lower confidence.',
      },
    ],
  },

  candle: {
    title: 'Candle Quality',
    what:
      'Characterizes the nature of recent price bars. This tells you whether the chart ' +
      'reflects real directional activity or mostly noise and zero-trade periods — which ' +
      'changes how you should interpret every other signal you see.',
    timing:
      'Per-candle. All three ratios are computed from the full set of closed historical bars ' +
      'and recalculate only when a new candle closes. This is the slowest-updating card on ' +
      'the screen — at 1-minute resolution it updates once per minute at most. ' +
      'Use it for market-character context, not for timing individual entries.',
    howToUse:
      'High flat bar % = the market sits still most of the time; use only limit orders — ' +
      'a market order will cross a wide spread into nothing. High large wick % = the price ' +
      'regularly spikes and reverses within bars; momentum entries are unreliable here, ' +
      'prefer fading extremes with limits. Many open gaps = news-driven jumps are common ' +
      'in this market; if you are trading around a catalyst, expect disorderly opening prices ' +
      'and plan your entry accordingly.',
    rows: [
      {
        label: 'Flat Bars',
        meaning:
          '% of bars where open = close (no net price change). High = market is dormant most ' +
          'periods; low volume liquidity only.',
      },
      {
        label: 'Large Wicks',
        meaning:
          '% of bars with a wick-to-body ratio above 2:1. High = frequent intrabar reversals; ' +
          'price often trades far from where it closes.',
      },
      {
        label: 'Open Gaps',
        meaning:
          'Count of bars that opened more than 1¢ away from the prior close. Marks ' +
          'news-event or resolution-driven price jumps.',
      },
    ],
  },

  rsi: {
    title: 'RSI (14)',
    what:
      'The Relative Strength Index measures the speed and magnitude of recent price ' +
      'changes on a 0–100 scale. It divides average gains over bullish bars by average ' +
      'losses over bearish bars using a 14-candle Wilder smoothing window. ' +
      'Values below 30 signal that the price has fallen sharply relative to recent history; ' +
      'values above 70 signal it has risen sharply.',
    timing:
      'Per-candle close. Updates once when each candle finalizes—same cadence as the EMA. ' +
      'On a 1-min chart it refreshes every minute. Does not react to live order-book ' +
      'changes between closes. Requires at least 15 bars of history to produce a value.',
    howToUse:
      'RSI < 30 (Oversold): the price has fallen hard and fast — potential bounce, ' +
      'look for a green candle at support as a YES entry trigger. ' +
      'RSI > 70 (Overbought): the price has rallied sharply — potential reversal, reduce ' +
      'YES exposure or look for a NO entry at resistance. ' +
      '30–70 is neutral. Most powerful combined with other signals: oversold RSI at ' +
      'support = strong YES setup; overbought RSI at resistance = quality exit.',
    rows: [
      {
        label: 'RSI 14',
        meaning:
          'Current RSI value (0–100). Below 30 = oversold (bullish lean). ' +
          'Above 70 = overbought (bearish lean). Shows — until ≥15 bars are loaded.',
      },
      {
        label: 'Zone',
        meaning:
          'Oversold (<30, green), Neutral (30–70, grey), or Overbought (>70, red). ' +
          'Zone color matches the text-buy / text-sell convention used throughout the workstation.',
      },
    ],
  },

  signal: {
    title: 'Trade Signal',
    what:
      'A composite dip-buy timing score (0–100) derived from six dimensions: ' +
      'RSI exhaustion, EMA distance, Stochastic %K, microprice pressure, tape ' +
      'flow recovery, and orderbook imbalance rebuild. ' +
      'The model is designed to score HIGH only when a downward move is exhausted ' +
      'and reversal evidence is starting to accumulate — not during normal uptrends. ' +
      'A cliff abort gate fires first: if the price is accelerating down with rising volume, ' +
      'it returns SELL/12% immediately regardless of RSI.',
    timing:
      'Near-real-time composite. The cliff gate, pressure, and imbalance components update ' +
      'at sub-second speed with every order-book change. Tape flow updates with each trade. ' +
      'RSI, EMA, and Stochastic update per-candle close. ' +
      'Treat the signal as a persistent lean over 5–10 second windows. ' +
      'It will be quiet (WAIT/SELL) most of the time by design — that is correct behaviour.',
    howToUse:
      'The signal is intentionally selective. Expect it to show SELL or WAIT the vast majority ' +
      'of the time. BUY fires only when: (1) RSI and/or Stochastic are in the oversold zone, ' +
      '(2) price is below EMA, AND (3) at least one live reversal signal (pressure flip, ' +
      'YES tape re-entry, bid accumulation, or hammer wick) confirms the turn. ' +
      'When BUY fires: enter at Ask, set a mental stop below EMA. ' +
      'When SELL fires and you hold YES: consider trimming. ' +
      '"Oversold but no reversal yet" means the price has fallen far enough but sellers ' +
      'are still active — wait for the book/tape flip before entering.',
    rows: [
      {
        label: 'RSI Exhaustion',
        meaning:
          'Max +35, min −15 pts. RSI <20 = extreme oversold = 35 pts. ' +
          'RSI >60 = overbought = penalty (−5 to −15 pts). ' +
          'This is the primary driver — it identifies when sell-side momentum is spent.',
      },
      {
        label: 'EMA Distance',
        meaning:
          'Max +25, min −15 pts. Price stretched below EMA scores higher. ' +
          'Price well above EMA = penalty. Measures mean-reversion potential.',
      },
      {
        label: 'Stochastic %K',
        meaning:
          'Max +15 pts. Price at the low of its recent cycle range = 15 pts. ' +
          'Provides independent confirmation of exhaustion based on price location, ' +
          'not momentum.',
      },
      {
        label: 'Pressure flip',
        meaning:
          'Max +20 pts. Microprice turning positive (buyers at mid) = confirmation ' +
          'that selling is drying up. Heavy negative pressure = 0 pts.',
      },
      {
        label: 'Tape Flow',
        meaning:
          'Max +15 pts. YES buyer re-entry in the last 80 trades = accumulation signal. ' +
          'NO seller dominance = 0 pts.',
      },
      {
        label: 'OB Imbalance',
        meaning:
          'Max +15 pts. Bids rebuilding at low prices = smart-money bottom signal. ' +
          'Ask-heavy = 0 pts (distribution still active).',
      },
    ],
  },
};

@Component({
  selector: 'app-analytics-help-modal',
  standalone: true,
  imports: [],
  templateUrl: './analytics-help-modal.component.html',
  styleUrl: './analytics-help-modal.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AnalyticsHelpModalComponent {
  @Input({ required: true }) cardKey!: HelpCardKey;
  @Output() readonly close = new EventEmitter<void>();

  get entry(): HelpEntry {
    return HELP[this.cardKey];
  }
}
