import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
} from '@angular/core';

export type ChartLegendKey =
  | 'candle-up'
  | 'candle-dn'
  | 'ema'
  | 'bid'
  | 'ask'
  | 'support'
  | 'resistance'
  | 'volume';

type RowHelp = { label: string; meaning: string };

type HelpEntry = {
  title: string;
  what: string;
  timing: string;
  howToUse: string;
  rows: readonly RowHelp[];
};

const HELP: Record<ChartLegendKey, HelpEntry> = {
  'candle-up': {
    title: 'Bullish Candle',
    what:
      'A green (bullish) candlestick means the YES price closed higher than it opened ' +
      'during that candle period. The body spans open to close; the wicks above and below ' +
      'show the highest and lowest prices reached within the period before settling at the close.',
    timing:
      'Per-candle close. The candle finalizes and turns green when the period ends ' +
      '(e.g. every 1 minute on a 1-min chart). The current live candle updates in real time ' +
      'but only locks in its color at the close.',
    howToUse:
      'A sequence of tall-bodied green candles with small wicks signals strong directional ' +
      'buying — the market is consistently closing near its highs. Look for green candles ' +
      'reclaiming key levels (support, EMA) after a pullback as an entry trigger for YES. ' +
      'A single green candle means little on its own; three or more consecutive ones with ' +
      'increasing volume is a high-confidence continuation signal.',
    rows: [
      {
        label: 'Body height',
        meaning:
          'Close minus open in cents. A tall body = conviction. A tiny body = indecision — ' +
          'buyers and sellers ended near-even that period.',
      },
      {
        label: 'Upper wick',
        meaning:
          'Shows how far price pushed above the close before being sold back down. ' +
          'A long upper wick on a green candle warns buyers lost control near the high.',
      },
      {
        label: 'Lower wick',
        meaning:
          'Shows how far price dipped below the open before buyers stepped in. ' +
          'A long lower wick means dip buyers absorbed selling pressure early in the period.',
      },
    ],
  },

  'candle-dn': {
    title: 'Bearish Candle',
    what:
      'A red (bearish) candlestick means the YES price closed lower than it opened during ' +
      'that candle period. Sellers dominated buyers by the time the period closed. Same ' +
      'anatomy as a bullish candle — body spans open to close, wicks span the high and low.',
    timing:
      'Per-candle close. Same as a bullish candle — finalizes at period end. A sequence ' +
      'of red candles on a 1-min chart can develop over several minutes; on a 5-min ' +
      'chart the same move may appear as just one or two candles.',
    howToUse:
      'Consecutive tall-bodied red candles signal sustained selling. A red candle breaking ' +
      'below support or the EMA is a bearish trigger — consider reducing YES exposure or ' +
      'entering NO. A red candle with an extremely long lower wick (hammer shape) is a ' +
      'potential reversal signal; sellers pushed hard but buyers absorbed it all by close.',
    rows: [
      {
        label: 'Body height',
        meaning:
          'Open minus close in cents. A tall red body = aggressive selling. A tiny body ' +
          '= indecision, potential reversal forming.',
      },
      {
        label: 'Upper wick',
        meaning:
          'Rally that was completely sold back. A long upper wick on a red candle ' +
          'confirms sellers aggressively defended any bounce.',
      },
      {
        label: 'Lower wick',
        meaning:
          'Intrabar dip that was partially recovered before close. A long lower wick ' +
          'on a red candle suggests underlying buy interest even inside a down move.',
      },
    ],
  },

  ema: {
    title: 'EMA × 20',
    what:
      'The 20-period Exponential Moving Average. It is the average of the last 20 candle ' +
      'closes, but more recent closes are weighted more heavily than older ones. This makes ' +
      'it react faster to recent price changes than a simple moving average. It acts as a ' +
      'dynamic reference for the trend direction.',
    timing:
      'Per-candle close. The EMA line shifts one data point each time a new candle closes. ' +
      'It does not tick between candle closes — its last plotted position reflects the most ' +
      'recent completed bar, not the live unfinalised price.',
    howToUse:
      'Price above EMA = short-term uptrend; lean YES entries. Price below EMA = short-term ' +
      'downtrend; caution on new YES entries. The EMA slope matters: a steeply rising EMA ' +
      'signals acceleration; a flattening EMA warns momentum is stalling. The most reliable ' +
      'entry signal is price pulling back to touch the EMA and then bouncing with a green ' +
      'candle — this is a trend continuation entry with a defined risk level (stop just ' +
      'below the EMA).',
    rows: [
      {
        label: 'Period',
        meaning:
          '20 bars. Short enough to respond to intraday trend shifts, long enough to ' +
          'filter out single-candle noise.',
      },
      {
        label: 'Slope',
        meaning:
          'Rising = bullish momentum. Falling = bearish momentum. Flat = no clear ' +
          'directional edge — spread cost becomes the dominant factor.',
      },
      {
        label: 'Price vs EMA',
        meaning:
          'Above = market in an uptrend on this timeframe. Below = downtrend. ' +
          'Crossovers (price crossing through EMA) are potential trend-change signals.',
      },
    ],
  },

  bid: {
    title: 'YES Bid',
    what:
      'The best (highest) resting buy order for YES contracts in the live order book. ' +
      'This is the price at which you can sell YES immediately — a market sell order hits ' +
      'this price. It is plotted as a dashed green horizontal line on the live right edge ' +
      'of the chart.',
    timing:
      'Sub-second. Updates whenever the top of the book changes — any order placed, ' +
      'cancelled, or filled at the current best bid moves this line instantly. ' +
      'Treat it as a live feed, not a candle-speed indicator.',
    howToUse:
      'The bid line shows where you can exit a YES position immediately without waiting. ' +
      'If you need to exit fast and the bid is far below the last trade price, slippage will ' +
      'be significant. Watch the bid move up toward the ask as a signal that buying pressure ' +
      'is building. A bid that holds steady while the price chart ticks lower suggests passive ' +
      'buyers are absorbing supply — potential floor for the current move.',
    rows: [
      {
        label: 'Bid price',
        meaning:
          'Cents per YES contract. This is your immediate sale proceeds if you cross the spread.',
      },
      {
        label: 'Bid vs Ask gap',
        meaning:
          'The spread. Tight bid-ask = liquid market, low entry/exit cost. Wide gap = ' +
          'illiquid, crossing costs more ticks.',
      },
    ],
  },

  ask: {
    title: 'YES Ask',
    what:
      'The best (lowest) resting sell order for YES contracts in the live order book. ' +
      'This is the price at which you can buy YES immediately — a market buy order hits ' +
      'this price. It is plotted as a dashed red horizontal line on the live right edge ' +
      'of the chart.',
    timing:
      'Sub-second. Mirrors the bid in update frequency — any change to the best ask ' +
      'price in the book moves this line instantly.',
    howToUse:
      'The ask line shows where you can enter a YES position immediately. If the ask ' +
      'is significantly above recent traded prices, the market has gapped up — chasing ' +
      'the ask here means buying into a momentary spike. A falling ask line (sellers ' +
      'undercutting each other) is a bearish signal; an ask that refuses to fall despite ' +
      'selling pressure below it suggests a supply wall is being absorbed and a push up ' +
      'may follow.',
    rows: [
      {
        label: 'Ask price',
        meaning:
          'Cents per YES contract. This is the immediate cost to acquire an YES position.',
      },
      {
        label: 'Ask vs Bid gap',
        meaning:
          'The spread. Even if the chart price looks favorable, a wide ask premium ' +
          'erodes your edge immediately on entry.',
      },
    ],
  },

  support: {
    title: 'Support',
    what:
      'A horizontal price level where the chart algorithm detected that the price has ' +
      'previously reversed upward — buyers overwhelmed sellers at this level. ' +
      'Support levels are computed from pivot lows in the candle history: a local low ' +
      'where price dipped, held, and bounced back up.',
    timing:
      'Per algorithm run on candle history. Recalculates when new candlestick data is ' +
      'loaded or when the candle history updates. Does not tick with live order-book data. ' +
      'These are medium-frequency lines — they shift slowly as new price history develops.',
    howToUse:
      'When price approaches a support level from above, watch for a slowdown in selling or ' +
      'a green candle bounce at that zone. This is a potential YES entry with a defined stop: ' +
      'place a stop just below the support level so you exit quickly if the level breaks. ' +
      'A support level that breaks convincingly (price closes below it on a full candle) ' +
      'becomes a new resistance — do not re-enter YES until it is reclaimed.',
    rows: [
      {
        label: 'Level price',
        meaning:
          'The detected pivot low in cents. Zone, not a precise line — treat ±1–2¢ around ' +
          'it as the support zone.',
      },
      {
        label: 'Touch count',
        meaning:
          'Levels that have been tested and held multiple times are stronger. A first-touch ' +
          'support has less evidence than one tested three or more times.',
      },
    ],
  },

  resistance: {
    title: 'Resistance',
    what:
      'A horizontal price level where the chart algorithm detected that the price has ' +
      'previously reversed downward — sellers overwhelmed buyers at this level. ' +
      'Computed from pivot highs: a local peak where price rallied, stalled, and fell back.',
    timing:
      'Per algorithm run on candle history. Same update frequency as support lines — ' +
      'recalculates on new historical candle data, not on live order-book ticks.',
    howToUse:
      'When price approaches resistance from below, slow down on adding YES exposure. ' +
      'This is a natural profit-taking zone and a potential NO entry area. If you are long YES ' +
      'and price is approaching resistance, consider taking partial profits rather than ' +
      'holding through the level. A resistance level that is broken convincingly on high ' +
      'volume flips to support — that breakout candle is a high-confidence YES entry with ' +
      'the former resistance now acting as your stop reference.',
    rows: [
      {
        label: 'Level price',
        meaning:
          'The detected pivot high in cents. As with support, treat as a zone rather than ' +
          'an exact line.',
      },
      {
        label: 'Break vs hold',
        meaning:
          'A close above on high volume = breakout, resistance flips to support. ' +
          'A wick above but close below = rejection, resistance confirmed.',
      },
    ],
  },

  volume: {
    title: 'Volume',
    what:
      'The total number of YES contracts traded during each candle period. Displayed as ' +
      'a histogram at the bottom of the chart — green bars for bullish candles, red bars ' +
      'for bearish candles. Volume is separate from price: a price move with high volume ' +
      'is more meaningful than the same move on thin volume.',
    timing:
      'Per-candle. Accumulates within the current live bar and finalizes at close. ' +
      'Slow markets may show many near-zero volume bars in a row — this is normal for ' +
      'low-activity Kalshi markets and is itself useful information.',
    howToUse:
      'Volume confirms or questions every price move. A green candle on rising volume = ' +
      'conviction move up — reliable YES signal. A green candle on falling/thin volume = ' +
      'weak push, likely to fade — be cautious. A sudden volume spike with a large candle ' +
      'in either direction often marks exhaustion of that move rather than its continuation — ' +
      'the biggest candle on the biggest volume is frequently the last one in a trend. ' +
      'Low volume consistently = wide spreads dominate, entries are expensive and exits may ' +
      'be difficult.',
    rows: [
      {
        label: 'Bar height',
        meaning:
          'Contracts traded that period. Taller = more activity. Context matters: compare ' +
          'to nearby bars, not an absolute threshold.',
      },
      {
        label: 'Bar color',
        meaning:
          'Green = that period\'s price close was above its open. Red = close below open. ' +
          'Matches the candle it belongs to.',
      },
      {
        label: 'Volume spike',
        meaning:
          'A bar significantly taller than its neighbors. Often marks a capitulation or ' +
          'acceleration moment — watch for reversal signals on the next candle.',
      },
    ],
  },
};

@Component({
  selector: 'app-chart-legend-help-modal',
  standalone: true,
  imports: [],
  templateUrl: './chart-legend-help-modal.component.html',
  styleUrl: './chart-legend-help-modal.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChartLegendHelpModalComponent {
  @Input({ required: true }) itemKey!: ChartLegendKey;
  @Output() readonly close = new EventEmitter<void>();

  get entry(): HelpEntry {
    return HELP[this.itemKey];
  }
}
