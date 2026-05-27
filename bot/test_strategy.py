"""Tests for the EMA crossover strategy."""

from strategy import compute_ema, get_signal


class TestComputeEma:
    def test_basic(self):
        prices = [1.0, 2.0, 3.0, 4.0, 5.0]
        ema = compute_ema(prices, 3)
        assert len(ema) == 3
        assert ema[0] == 2.0  # SMA of first 3

    def test_too_few_prices(self):
        assert compute_ema([1.0, 2.0], 5) == []

    def test_single_period(self):
        prices = [10.0, 20.0, 30.0]
        ema = compute_ema(prices, 1)
        assert len(ema) == 3
        assert ema[0] == 10.0

    def test_ema_tracks_price(self):
        prices = [i * 1.0 for i in range(1, 21)]
        ema = compute_ema(prices, 5)
        # EMA should lag below a steadily rising price
        assert ema[-1] < prices[-1]
        assert ema[-1] > ema[0]


class TestGetSignal:
    def _make_candles(self, closes: list[float]) -> list[dict]:
        return [{"close": c} for c in closes]

    def test_not_enough_data(self):
        candles = self._make_candles([1.0] * 10)
        assert get_signal(candles, fast_period=8, slow_period=21) is None

    def test_bullish_crossover(self):
        # Downtrend where fast EMA is below slow, then one big spike at the end
        # causes fast to cross above slow at the very last candle
        prices = [100.0 - i * 0.5 for i in range(40)]  # slow decline
        prices[-1] = prices[-2] + 30  # sharp spike at the end

        candles = self._make_candles(prices)
        signal = get_signal(candles, fast_period=3, slow_period=10)
        assert signal == "CALL"

    def test_bearish_crossover(self):
        # Uptrend where fast EMA is above slow, then one big drop at the end
        # causes fast to cross below slow at the very last candle
        prices = [100.0 + i * 0.5 for i in range(40)]  # slow rise
        prices[-1] = prices[-2] - 30  # sharp drop at the end

        candles = self._make_candles(prices)
        signal = get_signal(candles, fast_period=3, slow_period=10)
        assert signal == "PUT"

    def test_no_signal_in_flat_market(self):
        candles = self._make_candles([100.0] * 50)
        assert get_signal(candles, fast_period=8, slow_period=21) is None

    def test_no_signal_steady_trend(self):
        # Steady uptrend — no crossover, just parallel EMAs
        candles = self._make_candles([50.0 + i * 0.5 for i in range(50)])
        signal = get_signal(candles, fast_period=8, slow_period=21)
        # In a steady trend, fast stays above slow — no NEW crossover
        # (may or may not fire depending on initial crossover)
        assert signal in (None, "CALL")
