"""
Trend-following trading strategy using EMA crossover.

Logic:
- Compute fast EMA (8-period) and slow EMA (21-period) from candle closes
- BUY signal (CALL): fast EMA crosses above slow EMA
- SELL signal (PUT): fast EMA crosses below slow EMA
- Only one position open at a time
- Fixed stake per trade, configurable duration
"""

import logging

logger = logging.getLogger(__name__)


def compute_ema(prices: list[float], period: int) -> list[float]:
    """Compute Exponential Moving Average."""
    if len(prices) < period:
        return []
    multiplier = 2 / (period + 1)
    ema = [sum(prices[:period]) / period]
    for price in prices[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return ema


def get_signal(candles: list[dict], fast_period: int = 8, slow_period: int = 21) -> str | None:
    """
    Analyze candles and return a trading signal.

    Returns:
        "CALL" — bullish crossover (go long / rise)
        "PUT"  — bearish crossover (go short / fall)
        None   — no signal
    """
    closes = [c["close"] for c in candles]

    if len(closes) < slow_period + 2:
        logger.warning(f"Not enough candles ({len(closes)}) for EMA({slow_period})")
        return None

    fast_ema = compute_ema(closes, fast_period)
    slow_ema = compute_ema(closes, slow_period)

    # Align arrays — slow EMA starts later
    offset = slow_period - fast_period
    fast_aligned = fast_ema[offset:]

    if len(fast_aligned) < 2 or len(slow_ema) < 2:
        return None

    prev_fast = fast_aligned[-2]
    curr_fast = fast_aligned[-1]
    prev_slow = slow_ema[-2]
    curr_slow = slow_ema[-1]

    # Bullish crossover: fast crosses above slow
    if prev_fast <= prev_slow and curr_fast > curr_slow:
        logger.info(f"CALL signal: fast EMA ({curr_fast:.2f}) crossed above slow EMA ({curr_slow:.2f})")
        return "CALL"

    # Bearish crossover: fast crosses below slow
    if prev_fast >= prev_slow and curr_fast < curr_slow:
        logger.info(f"PUT signal: fast EMA ({curr_fast:.2f}) crossed below slow EMA ({curr_slow:.2f})")
        return "PUT"

    return None
