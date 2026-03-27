"""
Trading Strategy - Conservative Scalping for Deriv Synthetic Indices

Strategy: RSI Mean-Reversion + Trend Filter
- Uses RSI(14) for entry signals
- Trend filter via EMA(10/20) to only trade in trend direction
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
    - EMA spread filter: crossover must be meaningful (not noise)
    - Candle body confirmation: last candle must close in signal direction
    - RSI band filter: no BUY when RSI>65 (overbought), no SELL when RSI<35 (oversold)
    - All paths require confidence >= 0.55 to fire

    Mean-reversion path (BB extreme + RSI extreme → self-sufficient at 0.55):
      Best for choppy/ranging markets. Uses 5-minute contracts.

    Trend-following path (EMA crossover + slope + RSI mid-range → 0.55):
      Best for trending markets. Uses 2-minute contracts.
    """
    if len(candles) < 30:
        return TradeSignal(Signal.HOLD, 0.0, "Insufficient data", symbol)

    # Extract OHLC
    closes = [float(c["close"]) for c in candles]
    opens = [float(c.get("open", c["close"])) for c in candles]
    current_price = closes[-1]

    # Last candle body direction (confirms momentum)
    last_candle_bullish = closes[-1] > opens[-1]
    last_candle_bearish = closes[-1] < opens[-1]

    # Calculate indicators
    rsi = calculate_rsi(closes, period=14)
    ema20 = calculate_ema(closes, period=20)
    ema10 = calculate_ema(closes, period=10)
    bb_upper, bb_mid, bb_lower = calculate_bollinger_bands(closes, period=20)

    if any(v is None for v in [rsi, ema20, ema10, bb_upper, bb_lower]):
        return TradeSignal(Signal.HOLD, 0.0, "Indicator calculation failed", symbol)

    logger.debug(
        f"{symbol} | Price: {current_price:.5f} | RSI: {rsi:.1f} | "
        f"EMA10: {ema10:.5f} | EMA20: {ema20:.5f} | "
        f"BB: {bb_lower:.5f}/{bb_mid:.5f}/{bb_upper:.5f}"
    )

    # EMA spread — crossover must be meaningful, not noise
    # Require EMA10/EMA20 separation of at least 0.02% of price
    ema_spread_pct = abs(ema10 - ema20) / ema20 * 100
    ema_spread_sufficient = ema_spread_pct >= 0.02

    # EMA slope (5-candle lookback — on 1-min candles this is 5 minutes)
    ema20_prev = calculate_ema(closes[:-5], period=20) if len(closes) > 25 else None
    trend_up = ema20 > ema20_prev if ema20_prev is not None else False
    trend_down = ema20 < ema20_prev if ema20_prev is not None else False

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

    # Trend-following path — requires meaningful EMA crossover + candle confirmation
    if ema10 > ema20 and ema_spread_sufficient:
        buy_confidence += 0.25
        buy_reasons.append("EMA10 > EMA20")
    if trend_up:
        buy_confidence += 0.20
        buy_reasons.append("EMA trend: bullish")
    # RSI bonus: only when mid-range (not overbought, not oversold)
    if rsi > 35 and rsi < 65 and trend_up and not rsi_falling:
        buy_confidence += 0.10
        buy_reasons.append(f"RSI bullish ({rsi:.1f})")
    # Last candle confirmation bonus
    if last_candle_bullish and (ema10 > ema20 or current_price < bb_lower):
        buy_confidence += 0.05
        buy_reasons.append("Candle confirms up")
    # Pullback in uptrend
    if trend_up and current_price < bb_mid and rsi < 50 and rsi_rising:
        buy_confidence += 0.10
        buy_reasons.append("Pullback in uptrend")

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

    # Trend-following path — requires meaningful EMA crossover + candle confirmation
    if ema10 < ema20 and ema_spread_sufficient:
        sell_confidence += 0.25
        sell_reasons.append("EMA10 < EMA20")
    if trend_down:
        sell_confidence += 0.20
        sell_reasons.append("EMA trend: bearish")
    # RSI bonus: only when mid-range (not oversold, not overbought)
    if rsi > 35 and rsi < 65 and trend_down and not rsi_rising:
        sell_confidence += 0.10
        sell_reasons.append(f"RSI bearish ({rsi:.1f})")
    # Last candle confirmation bonus
    if last_candle_bearish and (ema10 < ema20 or current_price > bb_upper):
        sell_confidence += 0.05
        sell_reasons.append("Candle confirms down")
    # Spike in downtrend
    if trend_down and current_price > bb_mid and rsi > 50 and rsi_falling:
        sell_confidence += 0.10
        sell_reasons.append("Spike in downtrend")

    # Determine contract duration:
    # Mean-reversion (BB extreme) → 5-minute contract (needs time to revert)
    # Trend-following → 2-minute contract (short, fast signal)
    buy_is_mean_reversion = current_price < bb_lower
    sell_is_mean_reversion = current_price > bb_upper

    # Single threshold: 0.55 for all signals
    threshold = 0.55

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
        f"{symbol} HOLD | RSI={rsi:.1f} | BUY={buy_confidence:.2f} ({', '.join(buy_reasons) or 'no conditions'}) | "
        f"SELL={sell_confidence:.2f} ({', '.join(sell_reasons) or 'no conditions'})"
    )
    return TradeSignal(Signal.HOLD, 0.0, "No clear signal", symbol)
