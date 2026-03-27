"""
Trading Strategy - Conservative Scalping for Deriv Synthetic Indices

Strategy: RSI Mean-Reversion + Trend Filter
- Uses RSI(14) for entry signals
- Trend filter via EMA(10/20/50) to only trade in trend direction
- 1-minute candles for fast signal alignment with 2-minute contracts
- Conservative: only trades high-confidence setups

Suitable for:
- Volatility 50 Index (R_50)
- Volatility 25 Index (R_25)
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


class Signal(Enum):
    BUY = "CALL"     # Price expected to go UP
    SELL = "PUT"     # Price expected to go DOWN
    HOLD = "HOLD"    # No trade


@dataclass
class TradeSignal:
    signal: Signal
    confidence: float       # 0.0 to 1.0
    reason: str
    symbol: str
    suggested_duration: int = 5
    suggested_duration_unit: str = "m"


def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
    """Calculate Relative Strength Index."""
    if len(prices) < period + 1:
        return None

    gains = []
    losses = []
    for i in range(1, period + 1):
        change = prices[-period + i] - prices[-period + i - 1]
        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_ema(prices: List[float], period: int) -> Optional[float]:
    """Calculate Exponential Moving Average."""
    if len(prices) < period:
        return None

    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period  # Start with SMA
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def calculate_ema_series(prices: List[float], period: int) -> List[Optional[float]]:
    """Calculate EMA for every candle in the series. Returns list of same length as prices."""
    if len(prices) < period:
        return [None] * len(prices)

    k = 2 / (period + 1)
    result = [None] * (period - 1)
    ema = sum(prices[:period]) / period
    result.append(ema)
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
        result.append(ema)
    return result


def calculate_sma(prices: List[float], period: int) -> Optional[float]:
    """Calculate Simple Moving Average."""
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def calculate_bollinger_bands(prices: List[float], period: int = 20, std_dev: float = 2.0):
    """Calculate Bollinger Bands. Returns (upper, middle, lower)."""
    if len(prices) < period:
        return None, None, None

    sma = calculate_sma(prices, period)
    variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
    std = variance ** 0.5

    return sma + std_dev * std, sma, sma - std_dev * std


def generate_signal(candles: list, symbol: str) -> TradeSignal:
    """
    Two-path strategy: mean-reversion (BB-led) and trend-following (EMA-led).
    Uses 1-minute candles for tight alignment with 2-minute contracts.

    Signal quality filters:
    - EMA50 macro trend gate: only trade in direction of major trend
    - EMA spread filter: crossover must be ≥0.05% of price (not noise)
    - Consecutive candle confirmation: 2 of last 3 candles must close in direction
    - RSI band filter: no BUY when RSI>65 (overbought), no SELL when RSI<35 (oversold)
    - All paths require confidence >= 0.60 to fire

    Mean-reversion path (BB extreme + RSI extreme → self-sufficient at 0.60):
      Best for choppy/ranging markets. Uses 5-minute contracts.

    Trend-following path (EMA crossover + macro trend gate + RSI mid-range → 0.60):
      Best for trending markets. Uses 2-minute contracts.
    """
    if len(candles) < 50:
        return TradeSignal(Signal.HOLD, 0.0, "Insufficient data", symbol)

    # Extract OHLC
    closes = [float(c["close"]) for c in candles]
    opens = [float(c.get("open", c["close"])) for c in candles]
    current_price = closes[-1]

    # Consecutive candle direction (last 3 candles)
    candle_dirs = [1 if closes[i] > opens[i] else (-1 if closes[i] < opens[i] else 0)
                   for i in range(-3, 0)]
    bullish_candles = sum(1 for d in candle_dirs if d == 1)
    bearish_candles = sum(1 for d in candle_dirs if d == -1)
    # 2 of last 3 candles must confirm direction
    consecutive_bull = bullish_candles >= 2
    consecutive_bear = bearish_candles >= 2

    # Calculate indicators
    rsi = calculate_rsi(closes, period=14)
    ema10_series = calculate_ema_series(closes, period=10)
    ema20_series = calculate_ema_series(closes, period=20)
    ema50 = calculate_ema(closes, period=50)
    bb_upper, bb_mid, bb_lower = calculate_bollinger_bands(closes, period=20)

    ema10 = ema10_series[-1]
    ema20 = ema20_series[-1]

    if any(v is None for v in [rsi, ema20, ema10, ema50, bb_upper, bb_lower]):
        return TradeSignal(Signal.HOLD, 0.0, "Indicator calculation failed", symbol)

    logger.debug(
        f"{symbol} | Price: {current_price:.5f} | RSI: {rsi:.1f} | "
        f"EMA10: {ema10:.5f} | EMA20: {ema20:.5f} | EMA50: {ema50:.5f} | "
        f"BB: {bb_lower:.5f}/{bb_mid:.5f}/{bb_upper:.5f}"
    )

    # EMA50 macro trend gate — only trade with the major trend
    macro_bull = current_price > ema50  # major uptrend
    macro_bear = current_price < ema50  # major downtrend

    # EMA spread — crossover must be meaningful, not noise (≥0.02% of price)
    ema_spread_pct = abs(ema10 - ema20) / ema20 * 100
    ema_spread_sufficient = ema_spread_pct >= 0.02

    # EMA slope using proper series comparison (5-candle lookback)
    ema20_5ago = ema20_series[-6] if len(ema20_series) >= 6 and ema20_series[-6] is not None else None
    trend_up = ema20 > ema20_5ago if ema20_5ago is not None else False
    trend_down = ema20 < ema20_5ago if ema20_5ago is not None else False

    # RSI momentum direction (3-candle lookback)
    rsi_prev = calculate_rsi(closes[:-3], period=14) if len(closes) > 17 else None
    rsi_falling = rsi_prev is not None and rsi < rsi_prev
    rsi_rising  = rsi_prev is not None and rsi > rsi_prev

    # === BUY confidence ===
    buy_confidence = 0.0
    buy_reasons = []

    # Mean-reversion path — price below BB lower + RSI oversold
    if current_price < bb_lower:
        buy_confidence += 0.30
        buy_reasons.append("Price below lower BB")
        if rsi < 40:
            buy_confidence += 0.25
            buy_reasons.append(f"RSI oversold ({rsi:.1f})")
        if rsi < 30:
            buy_confidence += 0.10
            buy_reasons.append(f"RSI strongly oversold ({rsi:.1f})")
    elif current_price < bb_mid and rsi < 35 and rsi_rising:
        buy_confidence += 0.25
        buy_reasons.append(f"Below BB mid + RSI very oversold ({rsi:.1f})")

    # Trend-following path — requires macro bull trend + meaningful EMA crossover
    if macro_bull:
        if ema10 > ema20 and ema_spread_sufficient:
            buy_confidence += 0.25
            buy_reasons.append("EMA10 > EMA20")
        if trend_up:
            buy_confidence += 0.15
            buy_reasons.append("EMA trend: bullish")
        # RSI bonus: only when mid-range (not overbought, not oversold)
        if rsi > 40 and rsi < 60 and trend_up and not rsi_falling:
            buy_confidence += 0.10
            buy_reasons.append(f"RSI bullish ({rsi:.1f})")
        # Consecutive candle confirmation
        if consecutive_bull and (ema10 > ema20 or current_price < bb_lower):
            buy_confidence += 0.10
            buy_reasons.append("3-candle momentum up")
        # Pullback in uptrend
        if trend_up and current_price < bb_mid and rsi < 50 and rsi_rising:
            buy_confidence += 0.10
            buy_reasons.append("Pullback in uptrend")
    else:
        # Allow mean-reversion BUY even in macro downtrend (BB extreme)
        if current_price < bb_lower and rsi < 35:
            # already scored above — no additional penalty
            pass

    # === SELL confidence ===
    sell_confidence = 0.0
    sell_reasons = []

    # Mean-reversion path — price above BB upper + RSI overbought
    if current_price > bb_upper:
        sell_confidence += 0.30
        sell_reasons.append("Price above upper BB")
        if rsi > 60:
            sell_confidence += 0.25
            sell_reasons.append(f"RSI overbought ({rsi:.1f})")
        if rsi > 70:
            sell_confidence += 0.10
            sell_reasons.append(f"RSI strongly overbought ({rsi:.1f})")
    elif current_price > bb_mid and rsi > 65 and rsi_falling:
        sell_confidence += 0.25
        sell_reasons.append(f"Above BB mid + RSI very overbought ({rsi:.1f})")

    # Trend-following path — requires macro bear trend + meaningful EMA crossover
    if macro_bear:
        if ema10 < ema20 and ema_spread_sufficient:
            sell_confidence += 0.25
            sell_reasons.append("EMA10 < EMA20")
        if trend_down:
            sell_confidence += 0.15
            sell_reasons.append("EMA trend: bearish")
        # RSI bonus: only when mid-range (not oversold, not overbought)
        if rsi > 40 and rsi < 60 and trend_down and not rsi_rising:
            sell_confidence += 0.10
            sell_reasons.append(f"RSI bearish ({rsi:.1f})")
        # Consecutive candle confirmation
        if consecutive_bear and (ema10 < ema20 or current_price > bb_upper):
            sell_confidence += 0.10
            sell_reasons.append("3-candle momentum down")
        # Spike in downtrend
        if trend_down and current_price > bb_mid and rsi > 50 and rsi_falling:
            sell_confidence += 0.10
            sell_reasons.append("Spike in downtrend")
    else:
        # Allow mean-reversion SELL even in macro uptrend (BB extreme)
        if current_price > bb_upper and rsi > 65:
            pass

    # Determine contract duration:
    # Mean-reversion (BB extreme) → 5-minute contract (needs time to revert)
    # Trend-following → 2-minute contract (short, fast signal)
    buy_is_mean_reversion = current_price < bb_lower
    sell_is_mean_reversion = current_price > bb_upper

    # Threshold: 0.60 for all signals
    threshold = 0.60

    if buy_confidence >= threshold or sell_confidence >= threshold:
        if buy_confidence > sell_confidence and buy_confidence >= threshold:
            duration = 5 if buy_is_mean_reversion else 2
            return TradeSignal(Signal.BUY, min(buy_confidence, 0.95), " | ".join(buy_reasons), symbol, suggested_duration=duration)
        if sell_confidence > buy_confidence and sell_confidence >= threshold:
            duration = 5 if sell_is_mean_reversion else 2
            return TradeSignal(Signal.SELL, min(sell_confidence, 0.95), " | ".join(sell_reasons), symbol, suggested_duration=duration)
        # Equal confidence — BB extreme takes priority
        if current_price > bb_upper:
            return TradeSignal(Signal.SELL, min(sell_confidence, 0.95), " | ".join(sell_reasons), symbol, suggested_duration=5)
        if current_price < bb_lower:
            return TradeSignal(Signal.BUY, min(buy_confidence, 0.95), " | ".join(buy_reasons), symbol, suggested_duration=5)

    logger.info(
        f"{symbol} HOLD | RSI={rsi:.1f} | macro={'bull' if macro_bull else 'bear'} | "
        f"BUY={buy_confidence:.2f} ({', '.join(buy_reasons) or 'no conditions'}) | "
        f"SELL={sell_confidence:.2f} ({', '.join(sell_reasons) or 'no conditions'})"
    )
    return TradeSignal(Signal.HOLD, 0.0, "No clear signal", symbol)
