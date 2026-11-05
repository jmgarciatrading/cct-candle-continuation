from __future__ import annotations

import pathlib
import unittest
from datetime import datetime, timedelta, timezone

from cct_candle_continuation import (
    CHICAGO,
    Bar,
    Candle,
    Model,
    in_global_window,
    in_signal_window,
    order_block,
    signal,
    stop_level,
    strategy_order,
    target_level,
    under_min_rr,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]
PINE = ROOT / "CCT_Candle_Continuation.pine"
STRATEGY = ROOT / "CCT_Candle_Continuation_Strategy.pine"


def shown_tags(
    candles: list[Bar],
    minutes: list[int] | None = None,
    start: int = 0,
    end: int = 59,
) -> list[tuple[int, int]]:
    """Tags on the order-block anchor after a captured continuation.

    Each item is (anchor_index, direction). The continuation is captured and
    produces no tag. The anchor must be strictly after that candle. A second
    continuation in the same direction does not move the capture. An opposite
    continuation replaces it. No order block means no tag. An anchor whose
    minute is outside the inclusive window is not shown, and that order block
    still completes the continuation.
    """
    last = 0
    captured = None
    waiting = False
    tags = []
    for index in range(1, len(candles)):
        direction = order_block(candles[index - 1], candles[index])
        anchor = index - 1
        minute_of_hour = 0 if minutes is None else minutes[anchor]
        if waiting and captured is not None and direction == last and anchor > captured:
            if in_signal_window(minute_of_hour, start, end):
                tags.append((anchor, direction))
            waiting = False
        continuation = signal(candles[index - 1], candles[index], last)
        if continuation:
            last = continuation
            captured = index
            waiting = True
    return tags


def aggregate(chunk: list[Bar]) -> Bar:
    return Bar(
        chunk[0].open,
        max(bar.high for bar in chunk),
        min(bar.low for bar in chunk),
        chunk[-1].close,
    )


def higher_timeframe_chart_tags(chart: list[Bar], group: int) -> list[tuple[int, int]]:
    """Continuation on groups of chart bars. The tag is a later chart order block.

    The continuation is known on the first chart bar of the next group. Its
    captured bar is the open of the continuation group. An order block inside
    that group is too early. The anchor is a chart bar after it.
    """
    if group < 2:
        raise ValueError("group must cover more than one chart bar")
    last = 0
    captured = None
    waiting = False
    tags = []
    for index in range(1, len(chart)):
        direction = order_block(chart[index - 1], chart[index])
        anchor = index - 1
        if waiting and captured is not None and direction == last and anchor > captured:
            tags.append((anchor, direction))
            waiting = False
        if index % group == 0 and index >= 2 * group:
            monitor_index = index // group
            setup = aggregate(chart[(monitor_index - 2) * group:(monitor_index - 1) * group])
            continuation = aggregate(chart[(monitor_index - 1) * group:monitor_index * group])
            captured_direction = signal(setup, continuation, last)
            if captured_direction:
                last = captured_direction
                captured = (monitor_index - 1) * group
                waiting = True
    return tags


class SignalTests(unittest.TestCase):
    def test_buy_on_bullish_close_above_previous_bullish_high(self):
        self.assertEqual(
            signal(Bar(10, 12, 9, 11), Bar(11, 14, 10, 13)),
            1,
        )

    def test_sell_on_bearish_close_below_previous_bearish_low(self):
        self.assertEqual(
            signal(Bar(12, 13, 10, 11), Bar(11, 12, 8, 9)),
            -1,
        )

    def test_wick_break_without_close_through_level_is_rejected(self):
        self.assertEqual(
            signal(Bar(10, 12, 9, 11), Bar(11, 13, 10, 11.5)),
            0,
        )

    def test_continuation_candle_must_match_direction(self):
        self.assertEqual(
            signal(Bar(10, 12, 9, 11), Bar(13, 14, 11, 12)),
            0,
        )

    def test_doji_setup_is_rejected(self):
        self.assertEqual(
            signal(Bar(10, 12, 9, 10), Bar(10, 13, 10, 12)),
            0,
        )

    def test_close_must_clear_the_prior_extreme_by_the_minimum(self):
        previous = Bar(10, 12, 9, 11)
        self.assertEqual(signal(previous, Bar(11, 16, 10, 13), minimum=4), 0)
        self.assertEqual(signal(previous, Bar(11, 18, 10, 16), minimum=4), 1)
        anchor = Bar(16, 16.2, 14, 14.5)
        self.assertEqual(order_block(anchor, Bar(14.5, 18, 14.2, 17), minimum=4), 0)
        self.assertEqual(order_block(anchor, Bar(14.5, 22, 14.2, 20.5), minimum=4), 1)

    def test_unconfirmed_bar_does_not_signal(self):
        self.assertEqual(
            signal(
                Bar(10, 12, 9, 11),
                Bar(11, 14, 10, 13),
                confirmed=False,
            ),
            0,
        )

    def test_repeated_buy_is_suppressed_until_sell(self):
        previous = Bar(10, 12, 9, 11)
        current = Bar(11, 14, 10, 13)
        self.assertEqual(signal(previous, current, last_direction=1), 0)

    def test_opposite_sell_is_allowed_after_buy(self):
        self.assertEqual(
            signal(
                Bar(12, 13, 10, 11),
                Bar(11, 12, 8, 9),
                last_direction=1,
            ),
            -1,
        )

    def test_buy_is_allowed_after_sell(self):
        self.assertEqual(
            signal(
                Bar(10, 12, 9, 11),
                Bar(11, 14, 10, 13),
                last_direction=-1,
            ),
            1,
        )


class OrderBlockPlacementTests(unittest.TestCase):
    def test_buy_tag_is_placed_on_the_following_bullish_order_block(self):
        candles = [
            Bar(10, 12, 9, 11),
            Bar(11, 14, 10, 13),
            Bar(13, 13.4, 11, 11.5),
            Bar(11.5, 14, 11.2, 13.8),
        ]
        self.assertEqual(shown_tags(candles), [(2, 1)])

    def test_sell_tag_is_placed_on_the_following_bearish_order_block(self):
        candles = [
            Bar(12, 13, 10, 11),
            Bar(11, 12, 8, 9),
            Bar(9, 11, 8.5, 10.5),
            Bar(10.5, 10.8, 8, 8.2),
        ]
        self.assertEqual(shown_tags(candles), [(2, -1)])

    def test_continuation_without_an_order_block_produces_no_tag(self):
        candles = [
            Bar(10, 12, 9, 11),
            Bar(11, 14, 10, 13),
            Bar(13, 14, 12.5, 13.5),
            Bar(13.5, 13.6, 13, 13.2),
        ]
        self.assertEqual(shown_tags(candles), [])

    def test_opposite_order_block_does_not_print_the_pending_tag(self):
        candles = [
            Bar(10, 12, 9, 11),
            Bar(11, 14, 10, 13),
            Bar(13, 15, 12, 14),
            Bar(14, 14.2, 10, 11),
        ]
        self.assertEqual(shown_tags(candles), [])

    def test_order_block_on_the_continuation_candle_is_not_the_tag(self):
        candles = [
            Bar(10, 12, 9, 11),
            Bar(11, 14, 10, 13),
            Bar(13, 13.2, 8, 9),
        ]
        self.assertEqual(order_block(candles[1], candles[2]), -1)
        self.assertEqual(shown_tags(candles), [])

    def test_wick_beyond_the_anchor_does_not_qualify(self):
        candles = [
            Bar(10, 12, 9, 11),
            Bar(11, 14, 10, 13),
            Bar(13, 13.4, 11, 11.5),
            Bar(11.5, 15, 11.2, 13.2),
        ]
        self.assertEqual(shown_tags(candles), [])

    def test_doji_anchor_does_not_qualify(self):
        candles = [
            Bar(10, 12, 9, 11),
            Bar(11, 14, 10, 13),
            Bar(13, 13.4, 11, 13),
            Bar(13, 15, 12.5, 14.5),
        ]
        self.assertEqual(shown_tags(candles), [])

    def test_doji_setup_does_not_arm_a_later_order_block(self):
        candles = [
            Bar(10, 12, 9, 10),
            Bar(10, 13, 10, 12),
            Bar(12, 12.2, 10, 10.5),
            Bar(10.5, 14, 10.2, 13),
        ]
        self.assertEqual(shown_tags(candles), [])

    def test_same_direction_continuation_does_not_print_a_second_tag(self):
        candles = [
            Bar(10, 12, 9, 11),
            Bar(11, 14, 10, 13),
            Bar(13, 13.4, 11, 11.5),
            Bar(11.5, 14, 11.2, 13.8),
            Bar(13.8, 15, 13, 14.5),
            Bar(14.5, 14.6, 12, 12.5),
            Bar(12.5, 16, 12.2, 15.5),
        ]
        self.assertEqual(shown_tags(candles), [(2, 1)])

    def test_opposite_continuation_drops_the_pending_tag(self):
        candles = [
            Bar(10, 12, 9, 11),
            Bar(11, 14, 10, 13),
            Bar(13, 13.5, 12, 12.5),
            Bar(12.5, 12.6, 10, 11),
            Bar(11, 13, 10.5, 12.5),
            Bar(12.5, 12.8, 9, 9.5),
        ]
        self.assertEqual(shown_tags(candles), [(4, -1)])

    def test_buy_stop_uses_a_previous_low_at_least_four_points_below(self):
        previous = Bar(11, 14, 6, 13)
        signal_bar = Bar(13, 13.4, 11, 11.5)
        self.assertEqual(stop_level(previous, signal_bar, 1), 6)
        self.assertEqual(stop_level(Bar(11, 14, 7, 13), signal_bar, 1), 7)

    def test_buy_stop_uses_four_points_when_the_previous_low_is_closer(self):
        previous = Bar(11, 14, 10, 13)
        signal_bar = Bar(13, 13.4, 11, 11.5)
        self.assertEqual(stop_level(previous, signal_bar, 1), 7)

    def test_buy_stop_uses_four_points_when_the_signal_low_is_lower(self):
        previous = Bar(11, 14, 10, 13)
        signal_bar = Bar(13, 13.4, 9, 11.5)
        self.assertEqual(stop_level(previous, signal_bar, 1), 5)
        self.assertEqual(stop_level(previous, Bar(13, 13.4, 10, 11.5), 1), 6)

    def test_sell_stop_uses_a_previous_high_at_least_four_points_above(self):
        previous = Bar(9, 15, 8.5, 10.5)
        signal_bar = Bar(10.5, 10.8, 8, 8.2)
        self.assertEqual(stop_level(previous, signal_bar, -1), 15)
        self.assertEqual(stop_level(Bar(9, 14.8, 8.5, 10.5), signal_bar, -1), 14.8)

    def test_sell_stop_uses_four_points_when_the_previous_high_is_closer(self):
        previous = Bar(9, 12, 8.5, 10.5)
        signal_bar = Bar(10.5, 10.8, 8, 8.2)
        self.assertEqual(stop_level(previous, signal_bar, -1), 14.8)

    def test_sell_stop_uses_four_points_when_the_signal_high_is_higher(self):
        previous = Bar(9, 10, 8.5, 9.5)
        signal_bar = Bar(10.5, 12, 8, 8.2)
        self.assertEqual(stop_level(previous, signal_bar, -1), 16)
        self.assertEqual(stop_level(Bar(9, 12, 8.5, 9.5), signal_bar, -1), 16)

    def test_order_block_outside_the_minute_window_does_not_print(self):
        candles = [
            Bar(10, 12, 9, 11),
            Bar(11, 14, 10, 13),
            Bar(13, 13.4, 11, 11.5),
            Bar(11.5, 14, 11.2, 13.8),
        ]
        minutes = [0, 5, 20, 21]
        self.assertEqual(shown_tags(candles, minutes, start=0, end=15), [])
        self.assertEqual(shown_tags(candles, minutes, start=20, end=20), [(2, 1)])
        self.assertEqual(shown_tags(candles, minutes, start=0, end=59), [(2, 1)])

    def test_higher_timeframe_continuation_uses_the_next_chart_order_block(self):
        chart = [
            Bar(10, 11, 9, 10.5),
            Bar(10.5, 12, 10, 11),
            Bar(11, 11.5, 10.2, 11.2),
            Bar(11.2, 12.2, 11, 11.8),
            Bar(11.8, 12.4, 11.2, 11.4),
            Bar(11.4, 14, 11.3, 13.5),
            Bar(13.5, 13.6, 12, 12.2),
            Bar(12.2, 15, 12.1, 14.5),
            Bar(14.5, 14.8, 14.2, 14.6),
        ]
        self.assertEqual(order_block(chart[4], chart[5]), 1)
        self.assertEqual(higher_timeframe_chart_tags(chart, 3), [(6, 1)])
        self.assertEqual(higher_timeframe_chart_tags(chart[:6], 3), [])

    def test_higher_timeframe_without_a_chart_order_block_produces_no_tag(self):
        chart = [
            Bar(10, 11, 9, 10.5),
            Bar(10.5, 12, 10, 11),
            Bar(11, 11.5, 10.2, 11.2),
            Bar(11.2, 12.2, 11, 11.8),
            Bar(11.8, 12, 11.4, 11.9),
            Bar(11.9, 14, 11.6, 13.5),
            Bar(13.5, 13.8, 13.2, 13.6),
            Bar(13.6, 13.7, 13.3, 13.5),
            Bar(13.5, 13.6, 13.2, 13.4),
        ]
        self.assertEqual(higher_timeframe_chart_tags(chart, 3), [])


class SourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PINE.read_text(encoding="utf-8")

    def test_is_v6_overlay_with_confirmed_signals_and_alerts(self):
        self.assertIn("//@version=6", self.source)
        self.assertIn(
            'indicator("CCT Candle Continuation", overlay = true, max_labels_count = 500, max_lines_count = 500)',
            self.source,
        )
        self.assertNotIn("scale = scale.none", self.source)
        self.assertIn("barstate.isconfirmed", self.source)
        self.assertIn("lastSignalDirection := 1", self.source)
        self.assertIn("lastSignalDirection := -1", self.source)
        self.assertIn('alertcondition(showBuy and inSignalWindow and buyRoomOk, title = "CCT Buy"', self.source)
        self.assertIn('alertcondition(showSell and inSignalWindow and sellRoomOk, title = "CCT Sell"', self.source)
        self.assertNotIn("closeThrough", self.source)
        self.assertNotIn("signalExpiry", self.source)
        self.assertNotIn("Expire after", self.source)

    def test_signal_tags_are_anchored_to_the_order_block(self):
        self.assertIn("max_labels_count = 500", self.source)
        self.assertIn("if showSignals and showBuy", self.source)
        self.assertIn("if showSignals and showSell", self.source)
        self.assertIn('label.new(anchorTime, anchorLow, "BUY"', self.source)
        self.assertIn('label.new(anchorTime, anchorHigh, "SELL"', self.source)
        self.assertNotIn('label.new(time, low, "BUY"', self.source)
        self.assertNotIn('label.new(time, high, "SELL"', self.source)
        self.assertEqual(self.source.count("xloc = xloc.bar_time"), 8)
        self.assertIn("low[2] < low[1] and low[1] - low[2] >= minimumStop", self.source)
        self.assertIn("high[2] > high[1] and high[2] - high[1] >= minimumStop", self.source)
        self.assertIn("low[1] - minimumStop", self.source)
        self.assertIn("high[1] + minimumStop", self.source)
        self.assertIn('input.float(4, "Minimum stop (points)"', self.source)
        self.assertEqual(self.source.count("line.new("), 6)
        self.assertEqual(self.source.count("yloc = yloc.price"), 2)
        self.assertNotIn("force_overlay", self.source)
        self.assertNotIn("size.tiny", self.source)
        self.assertIn("style = label.style_label_up", self.source)
        self.assertIn("style = label.style_label_down", self.source)
        self.assertNotIn("label.delete", self.source)
        self.assertNotIn("plotshape(", self.source)
        self.assertNotIn("location.abovebar", self.source)
        self.assertNotIn("location.belowbar", self.source)
        self.assertNotIn("yloc.abovebar", self.source)
        self.assertNotIn("yloc.belowbar", self.source)
        self.assertIn("anchorTime > capturedTime", self.source)
        self.assertIn("waitingForOrderBlock := false", self.source)

    def test_candle_timeframe_reads_the_last_closed_monitor_candle(self):
        self.assertIn('input.timeframe("", "Candle timeframe"', self.source)
        self.assertIn(
            'candleTimeframe == "" ? timeframe.period : candleTimeframe',
            self.source,
        )
        self.assertIn("close[2] > open[2]", self.source)
        self.assertIn("close[2] < open[2]", self.source)
        self.assertIn("close[1] > open[1] and close[1] > high[2]", self.source)
        self.assertIn("close[1] < open[1] and close[1] < low[2]", self.source)
        self.assertIn("close[1] < open[1] and chartBullishDisplacement", self.source)
        self.assertIn("close[1] > open[1] and chartBearishDisplacement", self.source)
        self.assertIn("int anchorTime = time[1]", self.source)
        self.assertIn("int orderBlockDirection = chartBullishOrderBlock ? 1 : chartBearishOrderBlock ? -1 : 0", self.source)
        self.assertNotIn("closedAnchorTime", self.source)
        self.assertNotIn("closedOrderBlock", self.source)
        self.assertIn(
            "bool orderBlockFollows = barstate.isconfirmed and waitingForOrderBlock",
            self.source,
        )
        self.assertIn("lookahead = barmerge.lookahead_on", self.source)
        self.assertIn("timeframe.change(monitorPeriod)", self.source)
        self.assertIn('input.int(0, "Signal Window Start"', self.source)
        self.assertIn('input.int(59, "Signal Window End"', self.source)
        self.assertIn("minute(anchorTime, syminfo.timezone)", self.source)
        self.assertIn("anchorMinute >= signalStart and anchorMinute <= signalEnd", self.source)
        self.assertIn("close - high[1] >= minimumStop", self.source)
        self.assertIn("close[1] - high[2] >= minimumStop", self.source)
        self.assertIn("bool buyRoomOk = na(buyTarget) or buyTarget - close >= close - buyStop", self.source)
        self.assertIn("if showSignals and showBuy and inSignalWindow and buyRoomOk", self.source)
        self.assertIn("if showSignals and showSell and inSignalWindow and sellRoomOk", self.source)
        self.assertIn("alertcondition(showBuy and inSignalWindow and buyRoomOk", self.source)
        self.assertIn("alertcondition(showSell and inSignalWindow and sellRoomOk", self.source)
        self.assertIn(
            'runtime.error("Candle timeframe must be the chart timeframe or higher.")',
            self.source,
        )

    def test_targets_follow_the_obverse_swing_rules(self):
        self.assertIn('input.string("15M", "Timeframe Target"', self.source)
        self.assertIn('input.int(0, "Min RR"', self.source)
        self.assertIn('input.int(0, "Max Target"', self.source)
        self.assertIn('input.int(2, "Target Swing Length"', self.source)
        self.assertIn("signalClose + buyRisk * 2", self.source)
        self.assertIn("signalClose - sellRisk * 2", self.source)
        self.assertIn("signalClose + buyRisk * maxTarget", self.source)
        self.assertIn("signalClose - sellRisk * maxTarget", self.source)
        self.assertIn("buyUnderMinRr", self.source)
        self.assertIn("sellUnderMinRr", self.source)
        self.assertIn('buyTip + "\\nTP "', self.source)
        self.assertIn('buyTip + "\\nMin RR"', self.source)
        self.assertIn("array.get(targetHighs, pivotIndex) >= pivotHigh", self.source)
        self.assertIn("array.get(targetLows, pivotIndex) <= pivotLow", self.source)
        self.assertIn("bullish ? swingPrice > price : swingPrice < price", self.source)
        self.assertIn("not na(buyTargetTime) and buyTargetTime != anchorTime", self.source)
        self.assertIn('bool swingTargetOn = targetChoice != "Off"', self.source)
        self.assertIn("bool targetOn = swingTargetOn or maxTarget > 0", self.source)
        self.assertIn("if swingTargetOn", self.source)
        self.assertIn(
            'runtime.error("Timeframe Target must be the chart timeframe or higher.")',
            self.source,
        )


class TargetTests(unittest.TestCase):
    def test_buy_uses_the_newest_swing_high_above_the_close(self):
        self.assertEqual(target_level(13.5, 9, 1, [(14, 1), (16, 1)]), (16, True))

    def test_sell_uses_the_newest_swing_low_below_the_close(self):
        self.assertEqual(target_level(10, 14, -1, [(8, -1), (6, -1)]), (6, True))

    def test_wrong_side_swing_is_skipped_for_an_older_one(self):
        self.assertEqual(target_level(10, 6, 1, [(12, 1), (8, -1)]), (12, True))

    def test_swing_that_is_not_beyond_the_close_is_skipped(self):
        self.assertEqual(target_level(13.5, 9, 1, [(14, 1), (13, 1)]), (14, True))

    def test_price_equal_to_the_close_is_not_beyond(self):
        self.assertEqual(target_level(13.5, 9, 1, [(13.5, 1)]), (22.5, False))

    def test_no_swing_uses_two_times_risk_on_the_signal_candle(self):
        self.assertEqual(target_level(13.5, 9, 1, []), (22.5, False))
        self.assertEqual(target_level(10, 14, -1, []), (2, False))

    def test_max_target_caps_a_far_swing_onto_the_signal_candle(self):
        self.assertEqual(target_level(13.5, 9, 1, [(30, 1)], max_target=3), (27, False))
        self.assertEqual(target_level(10, 16, -1, [(1, -1)], max_target=1), (4, False))

    def test_closer_swing_is_not_capped(self):
        self.assertEqual(target_level(13.5, 9, 1, [(16, 1)], max_target=1), (16, True))

    def test_max_target_zero_leaves_the_far_swing(self):
        self.assertEqual(target_level(13.5, 9, 1, [(30, 1)], max_target=0), (30, True))

    def test_two_times_fallback_is_not_capped(self):
        self.assertEqual(target_level(13.5, 9, 1, [], max_target=1), (22.5, False))

    def test_min_rr_does_not_change_the_price(self):
        self.assertEqual(target_level(13.5, 9, 1, [(16, 1)], min_rr=50), (16, True))
        self.assertEqual(target_level(13.5, 9, 1, [], min_rr=50), (22.5, False))

    def test_stop_on_the_wrong_side_returns_no_target(self):
        self.assertIsNone(target_level(13.5, 14, 1, [(16, 1)]))
        self.assertIsNone(target_level(10, 9, -1, [(6, -1)]))

    def test_target_off_returns_no_target(self):
        self.assertIsNone(target_level(13.5, 9, 1, [(16, 1)], enabled=False))

    def test_off_with_max_target_uses_that_multiple(self):
        self.assertEqual(target_level(13.5, 9, 1, [(30, 1)], enabled=False, max_target=3), (27, False))
        self.assertEqual(target_level(10, 16, -1, [(1, -1)], enabled=False, max_target=3), (-8, False))
        self.assertEqual(target_level(13.5, 9, 1, [(30, 1)], enabled=False, max_target=3, min_rr=50), (27, False))
        self.assertIsNone(target_level(13.5, 14, 1, enabled=False, max_target=3))
        self.assertIsNone(target_level(10, 9, -1, enabled=False, max_target=3))


class StrategyOrderTests(unittest.TestCase):
    def test_long_enters_when_the_target_pays_the_stop_distance(self):
        self.assertEqual(strategy_order(1, 16, 9, 23), ("long", 9, 23))
        self.assertIsNone(strategy_order(1, 16, 9, 22.5))

    def test_short_enters_when_the_target_is_below_the_fill(self):
        self.assertEqual(strategy_order(-1, 8, 14, 2), ("short", 14, 2))

    def test_missing_target_keeps_the_stop(self):
        self.assertEqual(strategy_order(1, 16, 9, None), ("long", 9, None))
        self.assertEqual(strategy_order(-1, 8, 14, None), ("short", 14, None))

    def test_target_already_reached_skips_the_order(self):
        self.assertIsNone(strategy_order(1, 16, 9, 16))
        self.assertIsNone(strategy_order(1, 16.5, 9, 16))
        self.assertIsNone(strategy_order(-1, 8, 14, 8))
        self.assertIsNone(strategy_order(-1, 7.5, 14, 8))

    def test_min_rr_window_and_a_stop_through_the_fill_skip_the_order(self):
        self.assertIsNone(strategy_order(1, 16, 9, 22.5, under_min_rr=True))
        self.assertIsNone(strategy_order(1, 16, 9, 22.5, shown=False))
        self.assertIsNone(strategy_order(1, 16, 16, 22.5))
        self.assertIsNone(strategy_order(-1, 8, 8, 2))


class StrategySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = STRATEGY.read_text(encoding="utf-8")

    def test_strategy_uses_the_indicator_signal_and_places_one_reversing_order(self):
        self.assertIn("//@version=6", self.source)
        self.assertIn('strategy("CCT Candle Continuation Strategy", shorttitle = "CCT St"', self.source)
        self.assertIn("pyramiding = 0", self.source)
        self.assertIn("process_orders_on_close = true", self.source)
        self.assertIn("default_qty_type = strategy.fixed", self.source)
        self.assertIn("default_qty_value = 1", self.source)
        self.assertNotIn("indicator(", self.source)
        self.assertNotIn("scale = scale.none", self.source)
        self.assertIn("low[2] < low[1] and low[1] - low[2] >= minimumStop", self.source)
        self.assertIn("high[2] > high[1] and high[2] - high[1] >= minimumStop", self.source)
        self.assertIn("signalClose + buyRisk * 2", self.source)
        self.assertIn("signalClose + buyRisk * maxTarget", self.source)
        self.assertIn('bool targetOn = swingTargetOn or maxTarget > 0', self.source)
        self.assertIn("na(buyTarget) or buyTarget - close >= close - buyStop", self.source)
        self.assertIn("na(sellTarget) or close - sellTarget >= sellStop - close", self.source)
        self.assertIn("bool buyRoomOk = na(buyTarget) or buyTarget - close >= close - buyStop", self.source)
        self.assertIn("inPrintWindow and buyRoomOk and not buyUnderMinRr and buyStop < close", self.source)
        self.assertIn("inPrintWindow and sellRoomOk and not sellUnderMinRr and sellStop > close", self.source)
        self.assertIn('strategy.entry("CCT Long", strategy.long', self.source)
        self.assertIn('strategy.entry("CCT Short", strategy.short', self.source)
        self.assertIn('strategy.exit("CCT Long Exit", from_entry = "CCT Long", stop = buyStop, limit = buyTarget)', self.source)
        self.assertIn('strategy.exit("CCT Short Exit", from_entry = "CCT Short", stop = sellStop)', self.source)
        self.assertIn('input.string("00:00", "Global Window Start"', self.source)
        self.assertIn('input.string("23:59", "Global Window End"', self.source)
        self.assertIn("hour(anchorTime, syminfo.timezone)", self.source)
        self.assertIn("bool inPrintWindow = inSignalWindow and inGlobalWindow", self.source)
        self.assertIn("close - high[1] >= minimumStop", self.source)
        self.assertIn("if showSignals and showBuy and inPrintWindow and buyRoomOk", self.source)
        self.assertIn('alertcondition(showBuy and inPrintWindow and buyRoomOk, title = "CCT Buy"', self.source)


def _chicago_ms(moment: datetime) -> int:
    return int(moment.timestamp()) * 1000


def _run_model(candles: list[Bar], minutes: list[int] | None = None, **kwargs) -> list:
    model = Model(target="Off", minimum_stop=kwargs.pop("minimum_stop", 0), **kwargs)
    start = datetime(2026, 8, 17, 14, 0, tzinfo=CHICAGO)
    found = []
    for index, bar in enumerate(candles):
        moment = start + timedelta(minutes=index)
        minute = None if minutes is None else minutes[index]
        setup = model.on_bar(
            Candle(_chicago_ms(moment), bar.open, bar.high, bar.low, bar.close),
            minute,
        )
        if setup is not None:
            found.append(setup)
    return found


class ModelTests(unittest.TestCase):
    def test_chart_tags_match_the_order_block_placement(self):
        books = (
            [
                Bar(10, 12, 9, 11),
                Bar(11, 14, 10, 13),
                Bar(13, 13.4, 11, 11.5),
                Bar(11.5, 14, 11.2, 13.8),
            ],
            [
                Bar(12, 13, 10, 11),
                Bar(11, 12, 8, 9),
                Bar(9, 11, 8.5, 10.5),
                Bar(10.5, 10.8, 8, 8.2),
            ],
            [
                Bar(10, 12, 9, 11),
                Bar(11, 14, 10, 13),
                Bar(13, 13.5, 12, 12.5),
                Bar(12.5, 12.6, 10, 11),
                Bar(11, 13, 10.5, 12.5),
                Bar(12.5, 12.8, 9, 9.5),
            ],
            [
                Bar(10, 12, 9, 11),
                Bar(11, 14, 10, 13),
                Bar(13, 13.4, 11, 11.5),
                Bar(11.5, 14, 11.2, 13.8),
                Bar(13.8, 15, 13, 14.5),
                Bar(14.5, 14.6, 12, 12.5),
                Bar(12.5, 16, 12.2, 15.5),
            ],
        )
        start = datetime(2026, 8, 17, 14, 0, tzinfo=CHICAGO)
        for candles in books:
            shown = []
            for setup in _run_model(candles):
                if setup.shown:
                    anchor = datetime.fromtimestamp(setup.anchor_time / 1000, CHICAGO)
                    shown.append((int((anchor - start).total_seconds() // 60), setup.direction))
            self.assertEqual(shown, shown_tags(candles))

    def test_buy_stop_is_four_points_when_the_previous_low_is_closer(self):
        candles = [
            Bar(10, 12, 9, 11),
            Bar(11, 16, 10, 16),
            Bar(16, 16.4, 11, 11.5),
            Bar(11.5, 21, 11.2, 20.5),
        ]
        setup = _run_model(candles, minimum_stop=4)[0]
        self.assertEqual(setup.stop, 7)
        self.assertIsNone(setup.target)
        self.assertEqual(strategy_order(setup.direction, setup.fill, setup.stop, setup.target), ("long", 7, None))

    def test_minute_window_hides_the_tag_and_completes_the_continuation(self):
        candles = [
            Bar(10, 12, 9, 11),
            Bar(11, 14, 10, 13),
            Bar(13, 13.4, 11, 11.5),
            Bar(11.5, 14, 11.2, 13.8),
            Bar(13.8, 14, 12, 12.25),
            Bar(12.25, 16, 12, 15.5),
        ]
        minutes = [0, 5, 20, 21, 22, 23]
        hidden = _run_model(candles, minutes, signal_minute_end=15)
        self.assertEqual(len(hidden), 1)
        self.assertFalse(hidden[0].in_window)
        self.assertTrue(hidden[0].in_global)

    def test_global_window_hides_the_tag_and_completes_the_continuation(self):
        candles = [
            Bar(10, 12, 9, 11),
            Bar(11, 14, 10, 13),
            Bar(13, 13.4, 11, 11.5),
            Bar(11.5, 14, 11.2, 13.8),
            Bar(13.8, 14, 12, 12.25),
            Bar(12.25, 16, 12, 15.5),
        ]
        hidden = _run_model(candles, global_start="09:30", global_end="10:00")
        self.assertEqual(len(hidden), 1)
        self.assertTrue(hidden[0].in_window)
        self.assertFalse(hidden[0].in_global)
        self.assertIsNone(
            strategy_order(
                hidden[0].direction,
                hidden[0].fill,
                hidden[0].stop,
                hidden[0].target,
                shown=hidden[0].shown,
            )
        )

    def test_global_window_includes_both_ends_and_wraps_past_midnight(self):
        self.assertTrue(in_global_window(9 * 60 + 30, "09:30", "16:00"))
        self.assertTrue(in_global_window(16 * 60, "09:30", "16:00"))
        self.assertFalse(in_global_window(9 * 60 + 29, "09:30", "16:00"))
        self.assertFalse(in_global_window(16 * 60 + 1, "09:30", "16:00"))
        self.assertTrue(in_global_window(22 * 60, "22:00", "02:00"))
        self.assertTrue(in_global_window(2 * 60, "22:00", "02:00"))
        self.assertFalse(in_global_window(12 * 60, "22:00", "02:00"))
        self.assertTrue(in_global_window(8 * 60, "morning", "16:00"))
        self.assertTrue(in_global_window(None, "09:30", "16:00"))

    def test_higher_timeframe_continuation_waits_for_a_later_chart_order_block(self):
        start = datetime(2026, 8, 17, 14, 0, tzinfo=CHICAGO)
        pieces = []
        for minute in range(5):
            pieces.append((minute, 10 if minute == 0 else 10.5, 12 if minute == 4 else 11, 9, 11 if minute == 4 else 10.5))
        for minute in range(5, 10):
            pieces.append((minute, 11 if minute == 5 else 12, 14 if minute == 9 else 13, 10.8, 13.5 if minute == 9 else 12.5))
        pieces.append((10, 13.5, 13.6, 12, 12.2))
        pieces.append((11, 12.2, 15, 12.1, 14.5))
        model = Model(candle="5M", target="Off", minimum_stop=0)
        found = []
        for minute, opened, high, low, closed in pieces:
            moment = start + timedelta(minutes=minute)
            setup = model.on_bar(Candle(_chicago_ms(moment), opened, high, low, closed))
            if setup is not None and setup.shown:
                anchor = datetime.fromtimestamp(setup.anchor_time / 1000, CHICAGO)
                found.append((anchor.hour, anchor.minute, setup.direction))
        self.assertEqual(found, [(14, 10, 1)])

    def test_one_minute_swing_target_matches_the_closed_pivot(self):
        bars = [
            (11, 12, 10, 10.5),
            (10.5, 14, 10.2, 11),
            (11, 12, 10.8, 11.5),
            (12.5, 16, 12.7, 16),
            (15, 15.2, 13, 13.5),
            (13.5, 19.5, 13.2, 19.5),
        ]
        start = datetime(2024, 1, 2, tzinfo=timezone.utc)
        model = Model(target="1M", swing=1, minimum_stop=4)
        setup = None
        for index, (opened, high, low, closed) in enumerate(bars):
            moment = start + timedelta(minutes=index)
            setup = model.on_bar(Candle(_chicago_ms(moment), opened, high, low, closed)) or setup
        self.assertIsNotNone(setup)
        self.assertEqual(setup.direction, 1)
        self.assertEqual(setup.stop, 9)
        self.assertEqual(setup.target, 16)
        self.assertEqual(setup.fill, 19.5)
        self.assertFalse(setup.under_min_rr)
        self.assertIsNone(strategy_order(setup.direction, setup.fill, setup.stop, setup.target))

    def test_off_max_target_ignores_the_swing(self):
        bars = [
            (11, 12, 10, 10.5),
            (10.5, 14, 10.2, 11),
            (11, 12, 10.8, 11.5),
            (12.5, 16, 12.7, 16),
            (15, 15.2, 13, 13.5),
            (13.5, 19.5, 13.2, 19.5),
        ]
        start = datetime(2024, 1, 2, tzinfo=timezone.utc)
        model = Model(target="Off", max_target=3, swing=1, minimum_stop=4)
        setup = None
        for index, (opened, high, low, closed) in enumerate(bars):
            moment = start + timedelta(minutes=index)
            setup = model.on_bar(Candle(_chicago_ms(moment), opened, high, low, closed)) or setup
        self.assertEqual(setup.target, 27)
        self.assertFalse(under_min_rr(13.5, 9, setup.target, 1, 0))
        self.assertTrue(under_min_rr(13.5, 9, setup.target, 1, 50))


if __name__ == "__main__":
    unittest.main()
