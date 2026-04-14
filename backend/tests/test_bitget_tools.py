"""
Unit tests for the Bitget copy trading analysis tools.

Tests the analysis logic and formatting helpers without requiring
live API credentials.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from deerflow.community.bitget.tools import (
    _analyze_copy_history,
    _format_copy_orders,
    _format_positions,
    _ts_to_iso,
)


# ── Timestamp helper ────────────────────────────────────────────────


class TestTsToIso:
    def test_valid_timestamp(self):
        # 2024-01-01 00:00:00 UTC = 1704067200000 ms
        assert _ts_to_iso(1704067200000) == "2024-01-01 00:00:00 UTC"

    def test_string_timestamp(self):
        assert _ts_to_iso("1704067200000") == "2024-01-01 00:00:00 UTC"

    def test_none(self):
        assert _ts_to_iso(None) == "N/A"

    def test_invalid(self):
        assert _ts_to_iso("not_a_number") == "not_a_number"


# ── Position formatting ─────────────────────────────────────────────


class TestFormatPositions:
    def test_empty(self):
        assert _format_positions([]) == []

    def test_basic_position(self):
        positions = [{
            "symbol": "BTCUSDT",
            "holdSide": "short",
            "total": "0.0246",
            "leverage": "50",
            "openPriceAvg": "74684.8",
            "markPrice": "74078",
            "unrealizedPL": "14.9272",
            "margin": "36.74",
            "liquidationPrice": "76200",
            "takeProfitPrice": "",
            "stopLossPrice": "",
            "cTime": "1713092544000",
        }]
        result = _format_positions(positions)
        assert len(result) == 1
        assert result[0]["symbol"] == "BTCUSDT"
        assert result[0]["side"] == "short"
        assert result[0]["leverage"] == "50"
        assert result[0]["entry_price"] == "74684.8"
        assert result[0]["unrealized_pnl"] == "14.9272"


# ── Copy order formatting ───────────────────────────────────────────


class TestFormatCopyOrders:
    def test_empty(self):
        assert _format_copy_orders([]) == []

    def test_basic_order(self):
        orders = [{
            "symbol": "ETHUSDT",
            "posSide": "long",
            "openSize": "0.5",
            "leverage": "20",
            "openPrice": "3200",
            "closePrice": "3350",
            "achievedProfits": "75.0",
            "openTime": "1704067200000",
            "closeTime": "1704153600000",
            "traderId": "TRADER123",
        }]
        result = _format_copy_orders(orders)
        assert len(result) == 1
        assert result[0]["symbol"] == "ETHUSDT"
        assert result[0]["pnl"] == "75.0"
        assert result[0]["trader_id"] == "TRADER123"


# ── History analysis ─────────────────────────────────────────────────


class TestAnalyzeCopyHistory:
    def test_empty_history(self):
        result = _analyze_copy_history([])
        assert result["total_trades"] == 0

    def test_all_winners(self):
        orders = [
            {"achievedProfits": "10.0", "symbol": "BTCUSDT", "posSide": "long", "openTime": "1704067200000", "closeTime": "1704153600000"},
            {"achievedProfits": "20.0", "symbol": "BTCUSDT", "posSide": "short", "openTime": "1704153600000", "closeTime": "1704240000000"},
        ]
        result = _analyze_copy_history(orders)
        assert result["total_trades"] == 2
        assert result["wins"] == 2
        assert result["losses"] == 0
        assert result["win_rate_pct"] == 100.0
        assert result["total_pnl_usdt"] == 30.0
        assert result["profit_factor"] == "inf"
        assert result["estimated_30pct_profit_share_usdt"] == 9.0

    def test_mixed_results(self):
        orders = [
            {"achievedProfits": "50.0", "symbol": "BTCUSDT", "posSide": "long", "openTime": "1704067200000", "closeTime": "1704110400000"},
            {"achievedProfits": "-20.0", "symbol": "ETHUSDT", "posSide": "short", "openTime": "1704110400000", "closeTime": "1704153600000"},
            {"achievedProfits": "30.0", "symbol": "BTCUSDT", "posSide": "long", "openTime": "1704153600000", "closeTime": "1704196800000"},
            {"achievedProfits": "-10.0", "symbol": "SOLUSDT", "posSide": "long", "openTime": "1704196800000", "closeTime": "1704240000000"},
        ]
        result = _analyze_copy_history(orders)
        assert result["total_trades"] == 4
        assert result["wins"] == 2
        assert result["losses"] == 2
        assert result["win_rate_pct"] == 50.0
        assert result["total_pnl_usdt"] == 50.0
        assert result["total_profit_usdt"] == 80.0
        assert result["total_loss_usdt"] == 30.0
        assert result["avg_win_usdt"] == 40.0
        assert result["avg_loss_usdt"] == 15.0
        assert result["profit_factor"] == round(80.0 / 30.0, 4)
        assert result["symbols_traded"] == {"BTCUSDT": 2, "ETHUSDT": 1, "SOLUSDT": 1}
        assert result["side_distribution"] == {"long": 3, "short": 1}
        assert result["estimated_30pct_profit_share_usdt"] == 24.0

    def test_holding_time_calculation(self):
        # 24 hours apart
        orders = [
            {"achievedProfits": "5.0", "symbol": "BTCUSDT", "posSide": "long", "openTime": "1704067200000", "closeTime": "1704153600000"},
        ]
        result = _analyze_copy_history(orders)
        assert result["avg_holding_hours"] == 24.0

    def test_zero_pnl_is_breakeven(self):
        orders = [
            {"achievedProfits": "0", "symbol": "BTCUSDT", "posSide": "long"},
        ]
        result = _analyze_copy_history(orders)
        assert result["wins"] == 0
        assert result["losses"] == 0
        assert result["breakeven"] == 1

    def test_missing_pnl_field(self):
        orders = [{"symbol": "BTCUSDT", "posSide": "long"}]
        result = _analyze_copy_history(orders)
        assert result["total_trades"] == 1
        assert result["total_pnl_usdt"] == 0.0
