"""Executable spec for the CCT candle continuation strategy.

The chart is one-minute bars. A continuation is captured and not drawn. The
tag belongs to the next chart order block whose anchor opens after that
capture. The lab adapter imports this module. It does not keep a second copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


CHICAGO = ZoneInfo("America/Chicago")
FRAME_MINUTES = {"1M": 1, "5M": 5, "15M": 15, "1H": 60, "4H": 240}


@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float

    def bar(self) -> Bar:
        return Bar(self.open, self.high, self.low, self.close)


@dataclass(frozen=True)
class Setup:
    """One completed chart order block.

    `in_window` is the minute of the hour. `in_global` is the time of day.
    Both are required before an order. An order block outside either window
    still completes the continuation.
    """

    direction: int
    anchor_time: int
    fill: float
    stop: float
    target: float | None
    under_min_rr: bool
    in_window: bool
    in_global: bool

    @property
    def shown(self) -> bool:
        return self.in_window and self.in_global


def signal(
    previous: Bar,
    current: Bar,
    last_direction: int = 0,
    confirmed: bool = True,
    minimum: float = 0,
) -> int:
    if not confirmed:
        return 0
    bullish_setup = previous.close > previous.open
    bearish_setup = previous.close < previous.open
    bullish_continuation = (
        current.close > current.open
        and current.close > previous.high
        and current.close - previous.high >= minimum
    )
    bearish_continuation = (
        current.close < current.open
        and current.close < previous.low
        and previous.low - current.close >= minimum
    )
    return 1 if last_direction != 1 and bullish_setup and bullish_continuation else (
        -1 if last_direction != -1 and bearish_setup and bearish_continuation else 0
    )


def order_block(previous: Bar, current: Bar, minimum: float = 0) -> int:
    """1 when `previous` is the bullish order-block anchor, -1 when it is bearish.

    The displacement close has to clear the anchor by at least `minimum` points.
    """

    bullish = (
        previous.close < previous.open
        and current.close > current.open
        and current.close > previous.high
        and current.close - previous.high >= minimum
    )
    bearish = (
        previous.close > previous.open
        and current.close < current.open
        and current.close < previous.low
        and previous.low - current.close >= minimum
    )
    return 1 if bullish else -1 if bearish else 0


def stop_level(previous: Bar, signal_bar: Bar, direction: int, minimum: float = 4) -> float:
    """Stop on the prior candle when it is at least `minimum` points beyond.

    Otherwise the stop is `minimum` points beyond the signal candle.
    """

    if direction == 1:
        if previous.low < signal_bar.low and signal_bar.low - previous.low >= minimum:
            return previous.low
        return signal_bar.low - minimum
    if previous.high > signal_bar.high and previous.high - signal_bar.high >= minimum:
        return previous.high
    return signal_bar.high + minimum


def in_signal_window(minute_of_hour: int, start: int = 0, end: int = 59) -> bool:
    return start <= minute_of_hour <= end


def clock_minutes(hhmm: str) -> int | None:
    """Minutes from midnight. None when the text is not HH:MM."""

    parts = hhmm.split(":")
    if len(parts) != 2 or parts[0] == "" or parts[1] == "":
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    if not parts[0].isdigit() or not parts[1].isdigit():
        return None
    return hour * 60 + minute


def in_global_window(clock: int | None, start: str = "00:00", end: str = "23:59") -> bool:
    """True when the exchange clock is inside the global window.

    Both ends are included. A start later than the end wraps past midnight.
    A missing clock, or text that is not HH:MM, leaves the window open.
    """

    if clock is None:
        return True
    start_min = clock_minutes(start)
    end_min = clock_minutes(end)
    if start_min is None or end_min is None:
        return True
    if start_min <= end_min:
        return start_min <= clock <= end_min
    return clock >= start_min or clock <= end_min


def target_level(
    entry: float,
    stop: float,
    direction: int,
    swings: list[tuple[float, int]] | None = None,
    enabled: bool = True,
    max_target: int = 0,
    min_rr: int = 0,
) -> tuple[float, bool] | None:
    """Newest swing beyond the signal close, otherwise two times the risk.

    `swings` is oldest first. Each item is (price, kind), with 1 a high and
    -1 a low. The second result is True when that swing price is kept. A
    capped swing, the two-times fallback, and a fixed Max Target are False,
    so they belong on the signal candle. With swings off, Max Target above 0
    is that fixed multiple and any swing is ignored. `min_rr` does not change
    the price. None means there is no target, or the stop is on the wrong
    side of the close.
    """

    del min_rr
    if not enabled:
        if max_target <= 0:
            return None
        if direction == 1:
            if not stop < entry:
                return None
            risk = entry - stop
            return (entry + risk * max_target, False)
        if not stop > entry:
            return None
        risk = stop - entry
        return (entry - risk * max_target, False)
    history = [] if swings is None else swings
    if direction == 1:
        if not stop < entry:
            return None
        risk = entry - stop
        found = next((price for price, kind in reversed(history) if kind == 1 and price > entry), None)
        on_swing = found is not None
        target = found if on_swing else entry + risk * 2
        reward = target - entry
        if max_target > 0 and on_swing and reward > max_target * risk:
            return (entry + risk * max_target, False)
        return (target, on_swing)
    if not stop > entry:
        return None
    risk = stop - entry
    found = next((price for price, kind in reversed(history) if kind == -1 and price < entry), None)
    on_swing = found is not None
    target = found if on_swing else entry - risk * 2
    reward = entry - target
    if max_target > 0 and on_swing and reward > max_target * risk:
        return (entry - risk * max_target, False)
    return (target, on_swing)


def under_min_rr(
    entry: float,
    stop: float,
    target: float | None,
    direction: int,
    min_rr: int,
) -> bool:
    """True when a computed target pays less than `min_rr` times the risk.

    The distance is measured from the signal close. Equal to the minimum is
    accepted. No target, or a minimum of 0, stays clear.
    """

    if min_rr <= 0 or target is None:
        return False
    if direction == 1:
        risk = entry - stop
        reward = target - entry
    elif direction == -1:
        risk = stop - entry
        reward = entry - target
    else:
        return False
    if risk <= 0:
        return False
    return reward < min_rr * risk


def strategy_order(
    direction: int,
    fill: float,
    stop: float,
    target: float | None,
    under_min_rr: bool = False,
    shown: bool = True,
) -> tuple[str, float, float | None] | None:
    """Market order at the confirming close, or None when that order is skipped.

    The target is omitted when it is None. A target has to leave at least the
    stop distance beyond the fill. Equal to that distance is accepted.
    """

    if not shown or under_min_rr:
        return None
    if direction == 1:
        risk = fill - stop
        if risk <= 0 or (target is not None and target - fill < risk):
            return None
        return ("long", stop, target)
    if direction == -1:
        risk = stop - fill
        if risk <= 0 or (target is not None and fill - target < risk):
            return None
        return ("short", stop, target)
    return None


def frame_minutes(name: str, *, chart_minutes: int) -> int | None:
    """Minutes for a Pine timeframe name. Empty means the chart. Off is absent."""

    if name == "":
        return chart_minutes
    if name == "Off":
        return None
    if name not in FRAME_MINUTES:
        raise ValueError(f"unknown timeframe {name}")
    minutes = FRAME_MINUTES[name]
    if minutes < chart_minutes:
        raise ValueError(f"{name} is lower than the chart")
    return minutes


@dataclass
class _Partial:
    start_ms: int
    open: float
    high: float
    low: float
    close: float
    count: int


def _floor_ms(time_ms: int, minutes: int) -> int:
    moment = datetime.fromtimestamp(time_ms / 1000, CHICAGO).replace(second=0, microsecond=0)
    midnight = moment.replace(hour=0, minute=0)
    elapsed = int((moment - midnight).total_seconds() // 60)
    floored = midnight + timedelta(minutes=(elapsed // minutes) * minutes)
    return int(floored.timestamp()) * 1000


class BucketBuilder:
    """Aggregate chart bars. A full bucket is emitted on the next bucket's first bar."""

    def __init__(self, minutes: int) -> None:
        self.minutes = minutes
        self._partial: _Partial | None = None

    def add(self, candle: Candle) -> Candle | None:
        start_ms = _floor_ms(candle.time, self.minutes)
        emitted = None
        if self._partial is None or self._partial.start_ms != start_ms:
            if self._partial is not None and self._partial.count == self.minutes:
                finished = self._partial
                emitted = Candle(
                    finished.start_ms,
                    finished.open,
                    finished.high,
                    finished.low,
                    finished.close,
                )
            self._partial = _Partial(start_ms, candle.open, candle.high, candle.low, candle.close, 1)
        else:
            partial = self._partial
            partial.high = max(partial.high, candle.high)
            partial.low = min(partial.low, candle.low)
            partial.close = candle.close
            partial.count += 1
        return emitted


@dataclass
class Model:
    """Streaming CCT state for confirmed one-minute bars.

    Higher-timeframe candles are published when the next bucket opens, and
    only when every minute of the bucket was present. A pending chart order
    block is resolved before a new continuation is armed.
    """

    chart_minutes: int = 1
    candle: str = ""
    target: str = "15M"
    minimum_stop: float = 4
    min_rr: int = 0
    max_target: int = 0
    swing: int = 2
    signal_minute_start: int = 0
    signal_minute_end: int = 59
    global_start: str = "00:00"
    global_end: str = "23:59"
    _last: int = field(default=0, init=False)
    _captured: int | None = field(default=None, init=False)
    _waiting: bool = field(default=False, init=False)
    _chart: list[Candle] = field(default_factory=list, init=False)
    _monitor_closed: list[Candle] = field(default_factory=list, init=False)
    _highs: list[float] = field(default_factory=list, init=False)
    _lows: list[float] = field(default_factory=list, init=False)
    _swings: list[tuple[float, int]] = field(default_factory=list, init=False)
    _prev_minute: int | None = field(default=None, init=False)
    _prev_clock: int | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.swing < 1:
            raise ValueError("swing length must be at least 1")
        candle_minutes = frame_minutes(self.candle, chart_minutes=self.chart_minutes)
        target_minutes = frame_minutes(self.target, chart_minutes=self.chart_minutes)
        if candle_minutes is None:
            raise ValueError("candle timeframe cannot be Off")
        self._candle_minutes = candle_minutes
        self._target_minutes = target_minutes
        self._monitor = None if candle_minutes == self.chart_minutes else BucketBuilder(candle_minutes)
        self._target = None if target_minutes is None else BucketBuilder(target_minutes)

    def on_bar(self, candle: Candle, minute: int | None = None) -> Setup | None:
        local = datetime.fromtimestamp(candle.time / 1000, CHICAGO)
        current_clock = local.hour * 60 + local.minute
        current_minute = current_clock % 60 if minute is None else minute
        if self._target is not None:
            closed_target = self._target.add(candle)
            if closed_target is not None:
                self._push_pivot(closed_target)
        htf_direction = 0
        htf_time = None
        if self._monitor is not None:
            closed_monitor = self._monitor.add(candle)
            if closed_monitor is not None:
                self._monitor_closed.append(closed_monitor)
                if len(self._monitor_closed) > 2:
                    self._monitor_closed.pop(0)
                if len(self._monitor_closed) == 2:
                    older, newer = self._monitor_closed
                    htf_direction = signal(older.bar(), newer.bar(), minimum=self.minimum_stop)
                    htf_time = newer.time
        setup = self._resolve(candle)
        self._capture(candle, htf_direction, htf_time)
        self._chart.append(candle)
        if len(self._chart) > 3:
            del self._chart[0]
        self._prev_minute = current_minute
        self._prev_clock = current_clock
        return setup

    def _resolve(self, candle: Candle) -> Setup | None:
        if not self._chart or not self._waiting or self._captured is None:
            return None
        anchor = self._chart[-1]
        direction = order_block(anchor.bar(), candle.bar(), self.minimum_stop)
        if direction != self._last or not anchor.time > self._captured:
            return None
        previous = self._chart[-2].bar() if len(self._chart) >= 2 else None
        signal_bar = anchor.bar()
        if previous is None:
            stop = signal_bar.low - self.minimum_stop if direction == 1 else signal_bar.high + self.minimum_stop
        else:
            stop = stop_level(previous, signal_bar, direction, self.minimum_stop)
        entry = anchor.close
        found = target_level(
            entry,
            stop,
            direction,
            self._swings,
            enabled=self._target is not None,
            max_target=self.max_target,
            min_rr=self.min_rr,
        )
        target = None if found is None else found[0]
        self._waiting = False
        anchor_minute = self._prev_minute
        in_window = anchor_minute is not None and in_signal_window(
            anchor_minute, self.signal_minute_start, self.signal_minute_end
        )
        return Setup(
            direction=direction,
            anchor_time=anchor.time,
            fill=candle.close,
            stop=stop,
            target=target,
            under_min_rr=under_min_rr(entry, stop, target, direction, self.min_rr),
            in_window=in_window,
            in_global=in_global_window(self._prev_clock, self.global_start, self.global_end),
        )

    def _capture(self, candle: Candle, htf_direction: int, htf_time: int | None) -> None:
        if self._monitor is None:
            if not self._chart:
                return
            direction = signal(self._chart[-1].bar(), candle.bar(), self._last, minimum=self.minimum_stop)
            if direction:
                self._last = direction
                self._captured = candle.time
                self._waiting = True
            return
        if htf_direction and htf_direction != self._last and htf_time is not None:
            self._last = htf_direction
            self._captured = htf_time
            self._waiting = True

    def _push_pivot(self, candle: Candle) -> None:
        self._highs.append(candle.high)
        self._lows.append(candle.low)
        window = self.swing * 2 + 1
        if len(self._highs) > window:
            del self._highs[0]
            del self._lows[0]
        if len(self._highs) != window:
            return
        mid = self.swing
        pivot_high = self._highs[mid]
        pivot_low = self._lows[mid]
        is_high = all(self._highs[index] < pivot_high for index in range(window) if index != mid)
        is_low = all(self._lows[index] > pivot_low for index in range(window) if index != mid)
        if is_high:
            self._swings.append((pivot_high, 1))
        if is_low:
            self._swings.append((pivot_low, -1))
        while len(self._swings) > 50:
            del self._swings[0]
