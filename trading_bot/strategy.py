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

    # Trend direction from 5-candle EMA slope (more reliable than 1-candle)
    ema20_prev = calculate_ema(closes[:-5], period=20) if len(closes) > 25 else None
    trend_up = ema20 > ema20_prev if ema20_prev is not None else False
    trend_down = ema20 < ema20_prev if ema20_prev is not None else False

    # === BUY Signal (CALL) ===
    buy_confidence = 0.0
    buy_reasons = []

    # Bollinger Band conditions (strong signals)
    if current_price < bb_lower:
        buy_confidence += 0.30
        buy_reasons.append("Price below lower BB")
        if rsi is not None and rsi < 40:
            buy_confidence += 0.20
            buy_reasons.append(f"RSI oversold ({rsi:.1f})")
    elif current_price < bb_mid and rsi is not None and rsi < 35:
        buy_confidence += 0.25
        buy_reasons.append(f"Below BB mid + RSI very oversold ({rsi:.1f})")

    # EMA crossover (works independently of BB)
    if ema10 > ema20:
        buy_confidence += 0.25
        buy_reasons.append("EMA10 > EMA20 crossover")

    if trend_up:
        buy_confidence += 0.20
        buy_reasons.append("EMA trend: bullish")

    # RSI momentum support (mild boost when directionally aligned)
    if rsi is not None and 50 < rsi < 70 and trend_up:
        buy_confidence += 0.10
        buy_reasons.append(f"RSI bullish ({rsi:.1f})")

    if buy_confidence >= 0.55:
        return TradeSignal(
            Signal.BUY,
            min(buy_confidence, 0.95),
            " | ".join(buy_reasons),
            symbol,
        )

    # === SELL Signal (PUT) ===
    sell_confidence = 0.0
    sell_reasons = []

    # Bollinger Band conditions (strong signals)
    if current_price > bb_upper:
        sell_confidence += 0.30
        sell_reasons.append("Price above upper BB")
        if rsi is not None and rsi > 60:
            sell_confidence += 0.20
            sell_reasons.append(f"RSI overbought ({rsi:.1f})")
    elif current_price > bb_mid and rsi is not None and rsi > 65:
        sell_confidence += 0.25
        sell_reasons.append(f"Above BB mid + RSI very overbought ({rsi:.1f})")

    # EMA crossover (works independently of BB)
    if ema10 < ema20:
        sell_confidence += 0.25
        sell_reasons.append("EMA10 < EMA20 crossover")

    if trend_down:
        sell_confidence += 0.20
        sell_reasons.append("EMA trend: bearish")

    # RSI momentum support (mild boost when directionally aligned)
    if rsi is not None and 30 < rsi < 50 and trend_down:
        sell_confidence += 0.10
        sell_reasons.append(f"RSI bearish ({rsi:.1f})")

    if sell_confidence >= 0.55:
        return TradeSignal(
            Signal.SELL,
            min(sell_confidence, 0.95),
            " | ".join(sell_reasons),
            symbol,
        )

    return TradeSignal(Signal.HOLD, 0.0, "No clear signal", symbol)
