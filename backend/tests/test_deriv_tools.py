"""
Unit tests for the Deriv trading tools.

Tests the analysis logic without requiring a live Deriv API connection.
"""

import json

import pytest

from deerflow.community.deriv.tools import _analyze_profit_table


class TestAnalyzeProfitTable:
    def test_empty(self):
        result = _analyze_profit_table([])
        assert result["total_trades"] == 0

    def test_all_wins(self):
        trades = [
            {"profit_loss": 20.0, "buy_price": 10.0},
            {"profit_loss": 30.0, "buy_price": 15.0},
        ]
        result = _analyze_profit_table(trades)
        assert result["total_trades"] == 2
        assert result["wins"] == 2
        assert result["losses"] == 0
        assert result["win_rate_pct"] == 100.0
        assert result["total_pnl"] == 50.0
        assert result["profit_factor"] == "inf"
        assert result["total_staked"] == 25.0
        assert result["roi_pct"] == 200.0
        assert result["savings_vs_30pct_copy"] == 15.0

    def test_all_losses(self):
        trades = [
            {"profit_loss": -10.0, "buy_price": 10.0},
            {"profit_loss": -15.0, "buy_price": 15.0},
        ]
        result = _analyze_profit_table(trades)
        assert result["wins"] == 0
        assert result["losses"] == 2
        assert result["total_pnl"] == -25.0
        assert result["profit_factor"] == 0.0
        assert result["savings_vs_30pct_copy"] == 0

    def test_mixed(self):
        trades = [
            {"profit_loss": 50.0, "buy_price": 20.0},
            {"profit_loss": -10.0, "buy_price": 20.0},
            {"profit_loss": 30.0, "buy_price": 15.0},
            {"profit_loss": -5.0, "buy_price": 10.0},
        ]
        result = _analyze_profit_table(trades)
        assert result["total_trades"] == 4
        assert result["wins"] == 2
        assert result["losses"] == 2
        assert result["win_rate_pct"] == 50.0
        assert result["total_pnl"] == 65.0
        assert result["total_profit"] == 80.0
        assert result["total_loss"] == 15.0
        assert result["avg_win"] == 40.0
        assert result["avg_loss"] == 7.5
        assert result["profit_factor"] == round(80.0 / 15.0, 4)
        assert result["total_staked"] == 65.0
        assert result["roi_pct"] == 100.0
        assert result["savings_vs_30pct_copy"] == 24.0

    def test_breakeven_trades(self):
        trades = [
            {"profit_loss": 0, "buy_price": 10.0},
        ]
        result = _analyze_profit_table(trades)
        assert result["wins"] == 0
        assert result["losses"] == 0
        assert result["breakeven"] == 1

    def test_missing_fields(self):
        trades = [{}]
        result = _analyze_profit_table(trades)
        assert result["total_trades"] == 1
        assert result["total_pnl"] == 0.0
        assert result["total_staked"] == 0.0

    def test_roi_calculation(self):
        trades = [
            {"profit_loss": 10.0, "buy_price": 100.0},
        ]
        result = _analyze_profit_table(trades)
        assert result["roi_pct"] == 10.0
