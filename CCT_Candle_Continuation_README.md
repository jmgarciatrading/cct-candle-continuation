# CCT Candle Continuation

`CCT_Candle_Continuation.pine` is a standalone TradingView Pine Script v6
overlay that marks a candle continuation once an order block follows it.
`CCT_Candle_Continuation_Strategy.pine` is the same reading as a strategy.
Add one of the two scripts to a chart.

## Signal rules

A continuation is captured when its candle closes, and the tag waits for the
next order block on the chart timeframe.

- **Buy continuation:** the previous candle is bullish, and the current bullish
  candle closes above the previous candle's high.
- **Sell continuation:** the previous candle is bearish, and the current
  bearish candle closes below the previous candle's low.
- **Bullish order block:** the anchor candle is bearish, and the next candle is
  bullish and closes above the anchor's high. The order block is the anchor.
- **Bearish order block:** the anchor candle is bullish, and the next candle is
  bearish and closes below the anchor's low. The order block is the anchor.

The anchor is the chart candle immediately before the displacement. The tag is
placed on the first chart order block whose anchor opens after the captured
continuation, in the same direction. The continuation candle itself is not that
order block.

A continuation with no later order block produces no tag and no alert. A second
continuation in the same direction leaves the captured candle where it is.
An opposite continuation before the order block replaces the pending one, and
the first continuation produces no tag. After the tag is shown, later order
blocks do not print it again. The next continuation has to be in the opposite
direction.

Doji candles do not qualify as the setup, the continuation, the anchor, or the
displacement. A wick beyond the prior high or low does not qualify. Signals are
evaluated only after the monitored candle closes, so they do not appear
intrabar. The first qualifying continuation can be in either direction.

## Candle timeframe

**Candle timeframe** chooses the candles used for the continuation. The order
block always uses the chart timeframe. **Chart** follows the chart for the
continuation as well.

A higher timeframe uses the last closed candle on that timeframe. The
continuation is captured on the chart bar where that close is confirmed, and
the tag is drawn on the next chart order block. A timeframe lower than the
chart is rejected.

## Signal window

**Signal Window Start** and **Signal Window End** are minutes of the exchange
hour. Both ends are included. The defaults are 0 and 59, so the whole hour can
print. A tag is drawn only when the order-block candle's open minute is inside
that range. A tag outside the range is left off the chart and does not alert.
The order block still completes the continuation, so a later block does not
print it.

## Stop

The stop uses the candle immediately before the signal candle. The signal
candle is the order block that holds the tag. It is not a swing.

- **Buy:** the previous candle's low, when that low is at least **Minimum
  stop** points below the signal candle's low. Otherwise the signal candle's
  low minus that minimum.
- **Sell:** the previous candle's high, when that high is at least **Minimum
  stop** points above the signal candle's high. Otherwise the signal candle's
  high plus that minimum.

**Minimum stop (points)** defaults to 4. A previous candle that is beyond the
signal by less than that is not used. The same distance is required of a
continuation close and of an order-block close. A smaller close does not arm
a setup and does not print a tag.

A short red line marks that price on the candle that owns it, and only when
the tag is drawn. The stop price does not remove a signal that already cleared
that distance.

## Target

**Timeframe Target** chooses the swing used as the take profit. The default is
15M. Off does not use a swing. With **Max Target** above 0, Off draws that
multiple of the stop distance on the signal candle. Max Target at 0 with Off
leaves the target empty. The entry for the distance is the signal candle's
close. The tag is left off when a target is closer to the confirming close
than the stop is. Equal to that distance still prints. With no target, that
check stays off.

- **Buy:** the newest confirmed swing high on that timeframe above the close.
- **Sell:** the newest confirmed swing low on that timeframe below the close.

A wick through the swing does not skip it. **Target Swing Length** is the
number of bars required on each side of the pivot. The default is 2. The
target timeframe must be the chart timeframe or higher.

When a swing timeframe is selected and no swing is beyond the close, the
target is two times the distance from the close to the stop. **Max Target**
caps a farther swing. 3 draws it at 1:3 on the signal candle. A closer swing
stays on its own candle, and the same line is repeated on the signal candle.
0 leaves the swing unchanged. The two-times fallback stays at two times.

**Min RR** does not remove the tag, the stop, or the target. When the target
pays less than that multiple, the label tooltip shows Min RR. 0 leaves that
note off. A green line marks the target. Each line is two candles of the
target timeframe. When Timeframe Target is Off, the line is two chart candles.

## Strategy

The strategy enters at the close of the chart candle that confirms the order
block. The size is 1. The stop and the target are the prices drawn on that
signal. One position is open at a time. An opposite order closes it and opens
the new side.

A continuation close and an order-block close have to clear the prior extreme
by at least **Minimum stop**. A smaller close does not arm a setup and does
not print a tag.

When a target exists, it has to sit at least the stop distance beyond the
fill. The tag, the alert, and the order are skipped when the room is smaller.
Equal to that distance still qualifies. With no target, the stop rule is unchanged.

The order is skipped when the anchor minute is outside the signal window, when
**Min RR** marks the signal, or when the stop is on the wrong side of that
close. With no target, the order keeps the stop and has no
limit. The tag still prints when Min RR skips the order. The room check
removes the tag as well.

**Global Window Start** and **Global Window End** are on the strategy. They
are the exchange clock for the day, as `HH:MM`. The default `00:00` to `23:59`
keeps the whole day. Both ends are included. A start later than the end wraps
past midnight. Text that is not `HH:MM` leaves this window open. The label,
the lines, the alert, and the order need this window and the minute window.
An order block outside either window still completes the continuation. The
indicator does not have these two inputs.

`cct_candle_continuation.py` is the same reading as a Python model. The lab
adapter is `AI/ai-futures-trading-lab/src/ai_futures_trading_lab/strategies/cct.py`.
It places the order only while the position is flat. Pine still reverses on
the opposite signal. The lab fills the market order at the confirming close,
then adds one tick of adverse slippage and the lab commission. A target that
is not beyond the fill after that slippage is dropped by the lab and the stop
remains.

## Signal markers

BUY sits under the bullish order block. SELL sits over the bearish order block.
Both use that anchor candle's time and its low or high, with `xloc.bar_time`
and `yloc.price`. The script sets no price scale of its own, so the tags share
the chart price scale and move with that bar when the scale is zoomed. The
chart holds up to 500 labels; older tags drop off after that.

TradingView keeps the scale choice from the moment an indicator is added.
Remove this indicator from the chart and add it again so the tags leave an old
pane scale.

This is a basic candle-breakout reading of Candle Continuation Theory followed
by one displacement order block. It does not add a trend or session filter.
Use the **CCT Buy** and **CCT Sell** alert conditions to
create TradingView alerts. The alert fires when the order block confirms.
