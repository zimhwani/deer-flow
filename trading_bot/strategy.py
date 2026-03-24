"""
Trading Strategy - Conservative Scalping for Deriv Synthetic Indices

Strategy: RSI Mean-Reversion + Trend Filter
- Uses RSI(14) for entry signals
- Trend filter via EMA(20) to only trade in trend direction
- Targets short-duration contracts (5 minutes) for quick profit capture
- Conservative: only trades high-confidence setups

Suitable for:
- Volatility 10 Index (R_10) - lowest volatility synthetic, good for small accounts
- Volatility 25 Index (R_25) - medium volatility for more opportunities
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
    Analyse candle data and produce a trading signal.

    Strategy logic:
    1. Need at least 30 candles for reliable signals
    2. RSI oversold (<35) + price below lower BB → BUY signal
    3. RSI overbought (>65) + price above upper BB → SELL signal
    4. EMA trend filter: only trade in direction of EMA(20) slope
    5. Reject if RSI is between 40–60 (no clear momentum)
    """
    if len(candles) < 30:
        return TradeSignal(Signal.HOLD, 0.0, "Insufficient data", symbol)

    # Extract close prices
    closes = [float(c["close"]) for c in candles]
    current_price = closes[-1]

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

    # Trend direction from EMA slope
    ema20_prev = calculate_ema(closes[:-1], period=20)
    trend_up = ema20 > ema20_prev if ema20_prev else True
    trend_down = ema20 < ema20_prev if ema20_prev else True

    confidence = 0.0
    reasons = []

    # === BUY Signal (CALL) ===
    if rsi is not None and rsi < 40:
        confidence += 0.35
        reasons.append(f"RSI oversold ({rsi:.1f})")

    if current_price < bb_lower:
        confidence += 0.30
        reasons.append("Price below lower Bollinger Band")
    elif current_price < bb_mid and rsi < 45:
        confidence += 0.15
        reasons.append("Price below BB midline + low RSI")

    if trend_up:
        confidence += 0.20
        reasons.append("EMA trend: bullish")
    elif not trend_down:
        confidence += 0.10

    if ema10 > ema20 and trend_up:
        confidence += 0.15
        reasons.append("EMA10 > EMA20 (momentum up)")

    if confidence >= 0.55:
        return TradeSignal(
            Signal.BUY,
            min(confidence, 0.95),
            " | ".join(reasons),
            symbol,
        )

    # === SELL Signal (PUT) ===
    confidence = 0.0
    reasons = []

    if rsi is not None and rsi > 60:
        confidence += 0.35
        reasons.append(f"RSI overbought ({rsi:.1f})")

    if current_price > bb_upper:
        confidence += 0.30
        reasons.append("Price above upper Bollinger Band")
    elif current_price > bb_mid and rsi > 55:
        confidence += 0.15
        reasons.append("Price above BB midline + high RSI")

    if trend_down:
        confidence += 0.20
        reasons.append("EMA trend: bearish")
    elif not trend_up:
        confidence += 0.10

    if ema10 < ema20 and trend_down:
        confidence += 0.15
        reasons.append("EMA10 < EMA20 (momentum down)")

    if confidence >= 0.55:
        return TradeSignal(
            Signal.SELL,
            min(confidence, 0.95),
            " | ".join(reasons),
            symbol,
        )

    return TradeSignal(Signal.HOLD, 0.0, "No clear signal", symbol)
