"""
Unit tests for the MT5 trading tools.

Tests the analysis logic and formatting without requiring an MT5 terminal.
The MetaTrader5 package is mocked since it only works on Windows.
"""

import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── Mock MetaTrader5 module (not available on Linux) ────────────────

mock_mt5 = MagicMock()
mock_mt5.ORDER_TYPE_BUY = 0
mock_mt5.ORDER_TYPE_SELL = 1
mock_mt5.ORDER_TYPE_BUY_LIMIT = 2
mock_mt5.ORDER_TYPE_SELL_LIMIT = 3
mock_mt5.ORDER_TYPE_BUY_STOP = 4
mock_mt5.ORDER_TYPE_SELL_STOP = 5
mock_mt5.TRADE_ACTION_DEAL = 1
mock_mt5.TRADE_ACTION_PENDING = 5
mock_mt5.TRADE_ACTION_SLTP = 6
mock_mt5.ORDER_TIME_GTC = 0
mock_mt5.ORDER_FILLING_IOC = 1
sys.modules["MetaTrader5"] = mock_mt5


from deerflow.community.mt5.client import (
    MT5Client,
    _deal_entry_str,
    _deal_type_str,
    _parse_order_result,
    _retcode_str,
)
from deerflow.community.mt5.tools import _analyze_deals


# ── Helper string converters ────────────────────────────────────────


class TestDealTypeStr:
    def test_buy(self):
        assert _deal_type_str(0) == "buy"

    def test_sell(self):
        assert _deal_type_str(1) == "sell"

    def test_balance(self):
        assert _deal_type_str(2) == "balance"

    def test_unknown(self):
        assert _deal_type_str(99) == "unknown(99)"


class TestDealEntryStr:
    def test_in(self):
        assert _deal_entry_str(0) == "in"

    def test_out(self):
        assert _deal_entry_str(1) == "out"

    def test_unknown(self):
        assert _deal_entry_str(99) == "unknown(99)"


class TestRetcodeStr:
    def test_done(self):
        assert _retcode_str(10009) == "DONE"

    def test_no_money(self):
        assert _retcode_str(10019) == "NO_MONEY"

    def test_unknown(self):
        assert _retcode_str(99999) == "UNKNOWN(99999)"


# ── Order result parsing ────────────────────────────────────────────


class TestParseOrderResult:
    def test_success(self):
        result = SimpleNamespace(retcode=10009, deal=12345, order=67890, volume=0.1, price=74500.0, comment="ok")
        parsed = _parse_order_result(result)
        assert parsed["success"] is True
        assert parsed["retcode"] == 10009
        assert parsed["deal"] == 12345

    def test_failure(self):
        result = SimpleNamespace(retcode=10019, deal=0, order=0, volume=0, price=0, comment="no money")
        parsed = _parse_order_result(result)
        assert parsed["success"] is False
        assert parsed["retcode_description"] == "NO_MONEY"

    def test_none_result(self):
        parsed = _parse_order_result(None)
        assert parsed["success"] is False
        assert "None" in parsed["error"]


# ── Deal analysis ───────────────────────────────────────────────────


class TestAnalyzeDeals:
    def test_empty(self):
        result = _analyze_deals([])
        assert result["total_closed_trades"] == 0

    def test_filters_to_exit_deals_only(self):
        deals = [
            {"entry": "in", "type": "buy", "profit": 0, "commission": 0, "swap": 0, "symbol": "BTCUSD"},
            {"entry": "out", "type": "sell", "profit": 50.0, "commission": -1.0, "swap": -0.5, "symbol": "BTCUSD"},
        ]
        result = _analyze_deals(deals)
        assert result["total_closed_trades"] == 1
        assert result["wins"] == 1

    def test_mixed_results(self):
        deals = [
            {"entry": "out", "type": "buy", "profit": 100.0, "commission": -2.0, "swap": -1.0, "symbol": "BTCUSD"},
            {"entry": "out", "type": "sell", "profit": -40.0, "commission": -2.0, "swap": -0.5, "symbol": "EURUSD"},
            {"entry": "out", "type": "buy", "profit": 60.0, "commission": -1.5, "swap": -0.3, "symbol": "BTCUSD"},
            {"entry": "out", "type": "sell", "profit": -20.0, "commission": -1.0, "swap": 0, "symbol": "XAUUSD"},
        ]
        result = _analyze_deals(deals)
        assert result["total_closed_trades"] == 4
        assert result["wins"] == 2
        assert result["losses"] == 2
        assert result["win_rate_pct"] == 50.0
        assert result["gross_pnl"] == 100.0
        assert result["total_profit"] == 160.0
        assert result["total_loss"] == 60.0
        assert result["avg_win"] == 80.0
        assert result["avg_loss"] == 30.0
        assert result["profit_factor"] == round(160.0 / 60.0, 4)
        assert result["symbols_traded"] == {"BTCUSD": 2, "EURUSD": 1, "XAUUSD": 1}
        assert result["side_distribution"] == {"buy": 2, "sell": 2}
        assert result["savings_vs_30pct_copy"] == round(160.0 * 0.30, 2)

    def test_all_losses(self):
        deals = [
            {"entry": "out", "type": "sell", "profit": -50.0, "commission": -1.0, "swap": 0, "symbol": "BTCUSD"},
        ]
        result = _analyze_deals(deals)
        assert result["wins"] == 0
        assert result["losses"] == 1
        assert result["profit_factor"] == 0.0  # total_profit is 0, no winning trades
        assert result["savings_vs_30pct_copy"] == 0

    def test_all_wins(self):
        deals = [
            {"entry": "out", "type": "buy", "profit": 200.0, "commission": -5.0, "swap": -2.0, "symbol": "BTCUSD"},
            {"entry": "out", "type": "sell", "profit": 100.0, "commission": -3.0, "swap": -1.0, "symbol": "EURUSD"},
        ]
        result = _analyze_deals(deals)
        assert result["wins"] == 2
        assert result["losses"] == 0
        assert result["win_rate_pct"] == 100.0
        assert result["profit_factor"] == "inf"
        assert result["net_pnl"] == 300.0 + (-5.0 + -3.0) + (-2.0 + -1.0)
        assert result["savings_vs_30pct_copy"] == round(300.0 * 0.30, 2)

    def test_expectancy(self):
        deals = [
            {"entry": "out", "type": "buy", "profit": 30.0, "commission": 0, "swap": 0, "symbol": "BTCUSD"},
            {"entry": "out", "type": "sell", "profit": -10.0, "commission": 0, "swap": 0, "symbol": "BTCUSD"},
        ]
        result = _analyze_deals(deals)
        assert result["expectancy_per_trade"] == 10.0

    def test_ignores_balance_deals(self):
        deals = [
            {"entry": "in", "type": "balance", "profit": 1000.0, "commission": 0, "swap": 0, "symbol": ""},
            {"entry": "out", "type": "buy", "profit": 50.0, "commission": -1.0, "swap": 0, "symbol": "BTCUSD"},
        ]
        result = _analyze_deals(deals)
        assert result["total_closed_trades"] == 1


# ── MT5Client unit tests (mocked MT5 module) ────────────────────────


class TestMT5ClientAccount:
    def test_get_account_info(self):
        mock_mt5.account_info.return_value = SimpleNamespace(
            login=12345, name="Test", server="Deriv-Demo", balance=10000.0,
            equity=10500.0, margin=200.0, margin_free=10300.0, leverage=500,
            profit=500.0, currency="USD",
        )
        mock_mt5.initialize.return_value = True

        client = MT5Client()
        client._connected = True
        info = client.get_account_info()

        assert info["balance"] == 10000.0
        assert info["equity"] == 10500.0
        assert info["leverage"] == 500

    def test_get_account_info_failure(self):
        mock_mt5.account_info.return_value = None
        mock_mt5.last_error.return_value = (1, "not connected")

        client = MT5Client()
        client._connected = True
        with pytest.raises(ValueError, match="Failed to get account info"):
            client.get_account_info()


class TestMT5ClientPositions:
    def test_get_positions_empty(self):
        mock_mt5.positions_get.return_value = None

        client = MT5Client()
        client._connected = True
        assert client.get_positions() == []

    def test_get_positions(self):
        mock_mt5.positions_get.return_value = [
            SimpleNamespace(
                ticket=111, symbol="BTCUSD", type=1, volume=0.05,
                price_open=74500.0, price_current=74000.0, sl=75000.0, tp=73000.0,
                profit=25.0, swap=-0.5, comment="deerflow", magic=202506, time=1704067200,
            )
        ]

        client = MT5Client()
        client._connected = True
        positions = client.get_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "BTCUSD"
        assert positions[0]["type"] == "sell"
        assert positions[0]["profit"] == 25.0
