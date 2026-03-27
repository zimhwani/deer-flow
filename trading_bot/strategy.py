"""
Trading Strategy - Conservative Scalping for Deriv Synthetic Indices

Two signal paths:
  1. Mean-reversion: BB extreme + RSI extreme + RSI ALREADY reversing
  2. Trend-following: EMA aligned + macro trend + RSI healthy

Critical rule: never enter mean-reversion against a still-moving RSI.
If RSI is at 84 and still rising, do NOT sell — wait for it to peak and fall.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


class Signal(Enum):
    BUY = "CALL"
    SELL = "PUT"
    HOLD = "HOLD"


@dataclass
class TradeSignal:
    signal: Signal
    confidence: float
    reason: str
    symbol: str
    suggested_duration: int = 2
    suggested_duration_unit: str = "m"


def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
    if len(prices) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        change = prices[-period + i] - prices[-period + i - 1]
        gains.append(change if change >= 0 else 0)
        losses.append(abs(change) if change < 0 else 0)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_ema(prices: List[float], period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def calculate_ema_series(prices: List[float], period: int) -> List[Optional[float]]:
    if len(prices) < period:
        return [None] * len(prices)
    k = 2 / (period + 1)
    result: List[Optional[float]] = [None] * (period - 1)
    ema = sum(prices[:period]) / period
    result.append(ema)
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
        result.append(ema)
    return result


def calculate_sma(prices: List[float], period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def calculate_bollinger_bands(prices: List[float], period: int = 20, std_dev: float = 2.0):
    if len(prices) < period:
        return None, None, None
    sma = calculate_sma(prices, period)
    variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
    std = variance ** 0.5
    return sma + std_dev * std, sma, sma - std_dev * std


def generate_signal(candles: list, symbol: str) -> TradeSignal:
    """
    Two-path strategy with strict entry discipline.

    Mean-reversion path (5-min contracts):
      - Requires price at BB extreme + RSI extreme + RSI ALREADY reversing
      - rsi_falling required for SELL, rsi_rising required for BUY
      - Prevents shorting into still-rising RSI (the key bug this fixes)

    Trend-following path (2-min contracts):
      - Requires macro trend (EMA50 gate) + EMA crossover + 2 of 3 conditions
      - EMA crossover alone (+0.30) is no longer self-sufficient
      - Needs either RSI confirmation OR consecutive candles to reach 0.60
    """
    if len(candles) < 50:
        return TradeSignal(Signal.HOLD, 0.0, "Insufficient data", symbol)

    closes = [float(c["close"]) for c in candles]
    opens  = [float(c.get("open", c["close"])) for c in candles]
    current_price = closes[-1]

    # Indicators
    rsi    = calculate_rsi(closes, period=14)
    ema10_series = calculate_ema_series(closes, period=10)
    ema20_series = calculate_ema_series(closes, period=20)
    ema50  = calculate_ema(closes, period=50)
    bb_upper, bb_mid, bb_lower = calculate_bollinger_bands(closes, period=20)

    ema10 = ema10_series[-1]
    ema20 = ema20_series[-1]

    if any(v is None for v in [rsi, ema10, ema20, ema50, bb_upper, bb_lower]):
        return TradeSignal(Signal.HOLD, 0.0, "Indicator calculation failed", symbol)

    # EMA slope (compare current EMA20 to its value 5 candles ago)
    ema20_5ago = ema20_series[-6] if len(ema20_series) >= 6 and ema20_series[-6] is not None else None
    trend_up   = ema20 > ema20_5ago if ema20_5ago else False
    trend_down = ema20 < ema20_5ago if ema20_5ago else False

    # RSI direction (3-candle lookback)
    rsi_prev    = calculate_rsi(closes[:-3], period=14) if len(closes) > 17 else None
    rsi_rising  = rsi_prev is not None and rsi > rsi_prev
    rsi_falling = rsi_prev is not None and rsi < rsi_prev

    # Consecutive candle direction (2 of last 3 must agree)
    dirs = [1 if closes[i] > opens[i] else (-1 if closes[i] < opens[i] else 0) for i in range(-3, 0)]
    consecutive_bull = sum(1 for d in dirs if d == 1) >= 2
    consecutive_bear = sum(1 for d in dirs if d == -1) >= 2

    # Macro trend gate
    macro_bull = current_price > ema50
    macro_bear = current_price < ema50

    # EMA spread filter
    ema_spread_pct = abs(ema10 - ema20) / ema20 * 100
    ema_spread_ok  = ema_spread_pct >= 0.02

    logger.debug(
        f"{symbol} | Price={current_price:.4f} RSI={rsi:.1f} "
        f"EMA10={ema10:.4f} EMA20={ema20:.4f} EMA50={ema50:.4f} "
        f"BB={bb_lower:.4f}/{bb_mid:.4f}/{bb_upper:.4f} "
        f"macro={'bull' if macro_bull else 'bear'} "
        f"rsi_dir={'up' if rsi_rising else ('dn' if rsi_falling else 'flat')}"
    )

    # ── BUY ──────────────────────────────────────────────────────────
    buy_confidence = 0.0
    buy_reasons = []

    # Path 1 — Mean-reversion BUY
    # Price below lower BB + RSI oversold + RSI has ALREADY started rising
    if current_price < bb_lower and rsi < 35 and rsi_rising:
        buy_confidence += 0.65
        buy_reasons.append(f"BB oversold reversal | RSI={rsi:.1f} rising")

    # Path 2 — Trend-following BUY (only in macro uptrend, RSI must be above floor)
    elif macro_bull and rsi > 28:
        # Anchor: EMA crossover (required to reach threshold)
        if ema10 > ema20 and ema_spread_ok:
            buy_confidence += 0.30
            buy_reasons.append("EMA10 > EMA20")
        # Supporting signals
        if trend_up:
            buy_confidence += 0.15
            buy_reasons.append("EMA slope: up")
        if rsi > 35 and rsi < 60 and rsi_rising:
            buy_confidence += 0.15
            buy_reasons.append(f"RSI rising ({rsi:.1f})")
        if consecutive_bull:
            buy_confidence += 0.15
            buy_reasons.append("3-candle momentum up")

    # ── SELL ─────────────────────────────────────────────────────────
    sell_confidence = 0.0
    sell_reasons = []

    # Path 1 — Mean-reversion SELL
    # Price above upper BB + RSI overbought + RSI has ALREADY started falling
    if current_price > bb_upper and rsi > 65 and rsi_falling:
        sell_confidence += 0.65
        sell_reasons.append(f"BB overbought reversal | RSI={rsi:.1f} falling")

    # Path 2 — Trend-following SELL (only in macro downtrend, RSI must be above floor)
    elif macro_bear and rsi > 45:
        if ema10 < ema20 and ema_spread_ok:
            sell_confidence += 0.30
            sell_reasons.append("EMA10 < EMA20")
        if trend_down:
            sell_confidence += 0.15
            sell_reasons.append("EMA slope: down")
        if rsi > 40 and rsi < 65 and rsi_falling:
            sell_confidence += 0.15
            sell_reasons.append(f"RSI falling ({rsi:.1f})")
        if consecutive_bear:
            sell_confidence += 0.15
            sell_reasons.append("3-candle momentum down")

    # ── Decision ─────────────────────────────────────────────────────
    threshold = 0.60

    buy_mean_rev  = current_price < bb_lower and rsi < 35
    sell_mean_rev = current_price > bb_upper and rsi > 65

    if buy_confidence >= threshold or sell_confidence >= threshold:
        if buy_confidence > sell_confidence and buy_confidence >= threshold:
            duration = 5 if buy_mean_rev else 2
            return TradeSignal(Signal.BUY, min(buy_confidence, 0.95), " | ".join(buy_reasons), symbol, suggested_duration=duration)
        if sell_confidence > buy_confidence and sell_confidence >= threshold:
            duration = 5 if sell_mean_rev else 2
            return TradeSignal(Signal.SELL, min(sell_confidence, 0.95), " | ".join(sell_reasons), symbol, suggested_duration=duration)
        # Tie-break on BB extreme
        if sell_mean_rev:
            return TradeSignal(Signal.SELL, min(sell_confidence, 0.95), " | ".join(sell_reasons), symbol, suggested_duration=5)
        if buy_mean_rev:
            return TradeSignal(Signal.BUY, min(buy_confidence, 0.95), " | ".join(buy_reasons), symbol, suggested_duration=5)

    logger.info(
        f"{symbol} HOLD | RSI={rsi:.1f} | macro={'bull' if macro_bull else 'bear'} | "
        f"BUY={buy_confidence:.2f} ({', '.join(buy_reasons) or 'no conditions'}) | "
        f"SELL={sell_confidence:.2f} ({', '.join(sell_reasons) or 'no conditions'})"
    )
    return TradeSignal(Signal.HOLD, 0.0, "No clear signal", symbol)
