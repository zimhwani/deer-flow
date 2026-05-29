"""
Tapi's Trading Bot Dashboard
A lightweight aiohttp web server that exposes real-time bot stats via a browser UI.
Run with:  python dashboard.py   (from the trading_bot directory)
"""

import json
import os

from aiohttp import web

# ── config ───────────────────────────────────────────────────────────────────
_default_data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_symbol = os.environ.get("TRADING_SYMBOL", "R_25")
DATA_DIR = os.environ.get("TRADING_DATA_DIR", os.path.join(_default_data_dir, _symbol))
HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.environ.get("DASHBOARD_PORT", "8080"))
LOG_TAIL_LINES = 150

# ── MT5 bridge storage ────────────────────────────────────────────────────────
_MT5_FILE = os.path.join(_default_data_dir, "mt5_trades.json")
_mt5_trades: list = []


def _load_mt5_trades() -> list:
    try:
        with open(_MT5_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_mt5_trades() -> None:
    os.makedirs(os.path.dirname(_MT5_FILE), exist_ok=True)
    with open(_MT5_FILE, "w") as f:
        json.dump(_mt5_trades, f)


# ── helpers ───────────────────────────────────────────────────────────────────
def _tail(path: str, n: int) -> list:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            buf = bytearray()
            pos = size
            found = 0
            while pos > 0 and found <= n:
                chunk = min(4096, pos)
                pos -= chunk
                f.seek(pos)
                buf = f.read(chunk) + buf
                found = buf.count(b"\n")
            lines = buf.decode("utf-8", errors="replace").splitlines()
            return lines[-n:]
    except FileNotFoundError:
        return []


def _read_state() -> dict:
    path = os.path.join(DATA_DIR, "risk_state.json")
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# ── API handlers ──────────────────────────────────────────────────────────────
async def api_stats(request):
    state = _read_state()
    trades = state.get("trade_log", [])
    open_positions = state.get("open_positions", [])
    wins = [t for t in trades if t.get("profit", 0) > 0]
    losses = [t for t in trades if t.get("profit", 0) <= 0]
    total_profit = sum(t.get("profit", 0) for t in trades)
    win_rate = round(len(wins) / len(trades) * 100, 1) if trades else 0

    equity = []
    running = 0.0
    for t in trades:
        running += t.get("profit", 0)
        equity.append({"time": t.get("closed_at", ""), "equity": round(running, 2)})

    payload = {
        "date": state.get("date", ""),
        "daily_pnl": round(state.get("daily_pnl", 0.0), 2),
        "balance": round(state.get("balance", 0.0), 2),
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "total_profit": round(total_profit, 2),
        "equity_curve": equity,
        "recent_trades": trades[-20:][::-1],
        "open_positions": open_positions,
    }
    return web.json_response(payload)


async def api_log(request):
    lines = _tail(os.path.join(DATA_DIR, "bot.log"), LOG_TAIL_LINES)
    return web.json_response({"lines": lines})


# ── MT5 bridge API ────────────────────────────────────────────────────────────
async def api_mt5_trade(request):
    try:
        data = await request.json()
        trade_type = data.get("type", "")

        if trade_type == "open":
            sym = data.get("symbol", "")
            direction = data.get("direction", "")
            price = float(data.get("price", 0))
            open_time = data.get("time", "")
            # Deduplicate: skip if identical open already recorded
            for t in _mt5_trades:
                if (t.get("type") == "open" and t.get("symbol") == sym and
                        t.get("direction") == direction and
                        t.get("price") == price and t.get("opened_at") == open_time):
                    return web.json_response({"ok": True, "duplicate": True})
            _mt5_trades.append({
                "id": len(_mt5_trades),
                "type": "open",
                "direction": direction,
                "symbol": sym,
                "lots": float(data.get("lots", 0)),
                "price": price,
                "sl": float(data.get("sl", 0)),
                "tp": float(data.get("tp", 0)),
                "reason": data.get("reason", ""),
                "opened_at": open_time,
                "profit": None,
            })
        elif trade_type == "close":
            sym = data.get("symbol", "")
            profit = float(data.get("profit", 0))
            close_time = data.get("time", "")
            # Deduplicate: skip if identical close already recorded
            for t in _mt5_trades:
                if (t.get("type") == "closed" and t.get("symbol") == sym and
                        t.get("profit") == profit and t.get("closed_at") == close_time):
                    return web.json_response({"ok": True, "duplicate": True})
            matched = False
            for t in reversed(_mt5_trades):
                if t.get("symbol") == sym and t.get("type") == "open":
                    t["type"] = "closed"
                    t["profit"] = profit
                    t["closed_at"] = close_time
                    matched = True
                    break
            if not matched:
                _mt5_trades.append({
                    "id": len(_mt5_trades),
                    "type": "closed",
                    "direction": data.get("direction", ""),
                    "symbol": sym,
                    "lots": float(data.get("lots", 0)),
                    "price": float(data.get("price", 0)),
                    "profit": profit,
                    "opened_at": "",
                    "closed_at": close_time,
                })

        _save_mt5_trades()
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_mt5_stats(request):
    closed = [t for t in _mt5_trades if t.get("type") == "closed" and t.get("profit") is not None]
    open_pos = [t for t in _mt5_trades if t.get("type") == "open"]
    wins = [t for t in closed if (t.get("profit") or 0) > 0]
    losses = [t for t in closed if (t.get("profit") or 0) <= 0]
    total_profit = sum(t.get("profit", 0) for t in closed)
    win_rate = round(len(wins) / len(closed) * 100, 1) if closed else 0
    return web.json_response({
        "total_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "total_profit": round(total_profit, 2),
        "open_positions": open_pos,
        "recent_trades": closed[-20:][::-1],
    })


# ── HTML ──────────────────────────────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tapi's Trading Bot</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

  :root {
    --bg: #080c14;
    --surface: #0d1321;
    --surface2: #111827;
    --border: #1e293b;
    --border2: #243044;
    --text: #e2e8f0;
    --muted: #64748b;
    --green: #10b981;
    --green-dim: rgba(16,185,129,0.12);
    --red: #f43f5e;
    --red-dim: rgba(244,63,94,0.12);
    --blue: #6366f1;
    --blue-dim: rgba(99,102,241,0.12);
    --yellow: #f59e0b;
    --yellow-dim: rgba(245,158,11,0.12);
    --cyan: #22d3ee;
    --purple: #a855f7;
    --orange: #f97316;
    --glow-green: 0 0 20px rgba(16,185,129,0.3);
    --glow-red: 0 0 20px rgba(244,63,94,0.3);
    --glow-blue: 0 0 20px rgba(99,102,241,0.25);
    --glow-orange: 0 0 20px rgba(249,115,22,0.25);
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 14px;
    min-height: 100vh;
    background-image:
      radial-gradient(ellipse at 20% 0%, rgba(99,102,241,0.08) 0%, transparent 50%),
      radial-gradient(ellipse at 80% 100%, rgba(16,185,129,0.06) 0%, transparent 50%);
  }

  /* ── Header ── */
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 28px;
    border-bottom: 1px solid var(--border);
    background: rgba(13,19,33,0.8);
    backdrop-filter: blur(12px);
    position: sticky;
    top: 0;
    z-index: 100;
  }

  .header-left { display: flex; align-items: center; gap: 14px; }

  .logo {
    width: 38px; height: 38px;
    background: linear-gradient(135deg, var(--blue), var(--purple));
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px;
    box-shadow: var(--glow-blue);
  }

  .header-title h1 {
    font-size: 17px;
    font-weight: 700;
    background: linear-gradient(90deg, #e2e8f0, #94a3b8);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: -0.3px;
  }

  .header-title p {
    font-size: 11px;
    color: var(--muted);
    margin-top: 1px;
  }

  .header-right { display: flex; align-items: center; gap: 16px; }

  .live-badge {
    display: flex; align-items: center; gap: 6px;
    background: var(--green-dim);
    border: 1px solid rgba(16,185,129,0.25);
    border-radius: 20px;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 500;
    color: var(--green);
    transition: all 0.3s;
  }

  .live-badge.offline {
    background: rgba(100,116,139,0.1);
    border-color: rgba(100,116,139,0.2);
    color: var(--muted);
  }

  .pulse {
    width: 7px; height: 7px;
    border-radius: 50%;
    background: var(--green);
    animation: pulse 2s infinite;
  }

  .pulse.off { background: var(--muted); animation: none; }

  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(0.8); }
  }

  #last-updated { font-size: 11px; color: var(--muted); }

  /* ── Stat Cards ── */
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 14px;
    padding: 24px 28px 0;
  }

  .stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 18px 20px;
    position: relative;
    overflow: hidden;
    transition: border-color 0.3s, transform 0.2s;
  }

  .stat-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--accent, var(--blue)), transparent);
    opacity: 0.6;
  }

  .stat-card:hover { transform: translateY(-2px); border-color: var(--border2); }

  .stat-card .icon {
    font-size: 20px;
    margin-bottom: 12px;
    display: block;
  }

  .stat-card .label {
    font-size: 11px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.8px;
    font-weight: 500;
    margin-bottom: 6px;
  }

  .stat-card .value {
    font-size: 26px;
    font-weight: 800;
    letter-spacing: -0.5px;
    line-height: 1;
  }

  .stat-card .sub {
    font-size: 11px;
    color: var(--muted);
    margin-top: 4px;
  }

  .value.green { color: var(--green); }
  .value.red   { color: var(--red); }
  .value.blue  { color: var(--blue); }
  .value.yellow{ color: var(--yellow); }
  .value.cyan  { color: var(--cyan); }
  .value.white { color: var(--text); }

  /* ── Charts Row ── */
  .charts-row {
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: 14px;
    padding: 14px 28px 0;
  }

  .panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 20px 22px;
  }

  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
  }

  .panel-header h2 {
    font-size: 12px;
    font-weight: 600;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.8px;
  }

  .panel-header .badge {
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 10px;
    background: var(--blue-dim);
    color: var(--blue);
    font-weight: 500;
  }

  .panel-header .badge.orange {
    background: rgba(249,115,22,0.12);
    color: var(--orange);
  }

  .chart-wrap { position: relative; height: 210px; }
  .donut-wrap { position: relative; height: 190px; }

  /* ── Bottom Row ── */
  .bottom-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
    padding: 14px 28px 0;
  }

  /* ── Trades Table ── */
  table { width: 100%; border-collapse: collapse; }

  th {
    font-size: 10px;
    font-weight: 600;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.7px;
    padding: 0 10px 10px;
    text-align: left;
    border-bottom: 1px solid var(--border);
  }

  td {
    padding: 9px 10px;
    font-size: 12.5px;
    border-bottom: 1px solid rgba(30,41,59,0.5);
    font-family: 'JetBrains Mono', monospace;
  }

  tr:last-child td { border-bottom: none; }

  tr:hover td { background: rgba(255,255,255,0.02); }

  .tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.5px;
  }

  .tag.call { background: var(--green-dim); color: var(--green); }
  .tag.put  { background: var(--red-dim);   color: var(--red); }
  .tag.buy  { background: var(--green-dim); color: var(--green); }
  .tag.sell { background: var(--red-dim);   color: var(--red); }

  .profit-win  { color: var(--green); font-weight: 600; }
  .profit-loss { color: var(--red);   font-weight: 600; }

  /* ── Section Divider ── */
  .section-divider {
    margin: 20px 28px 0;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .section-divider .section-label {
    font-size: 11px;
    font-weight: 700;
    color: var(--orange);
    text-transform: uppercase;
    letter-spacing: 1px;
    white-space: nowrap;
    padding: 4px 12px;
    background: rgba(249,115,22,0.1);
    border: 1px solid rgba(249,115,22,0.2);
    border-radius: 20px;
  }
  .section-divider .divider-line {
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg, rgba(249,115,22,0.3), transparent);
  }

  /* ── Log Panel ── */
  .log-panel {
    margin: 14px 28px 28px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 20px 22px;
  }

  #log-box {
    background: #05080f;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 16px;
    height: 200px;
    overflow-y: auto;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11.5px;
    line-height: 1.7;
    scrollbar-width: thin;
    scrollbar-color: var(--border2) transparent;
  }

  #log-box::-webkit-scrollbar { width: 4px; }
  #log-box::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 4px; }

  .log-time { color: #334155; }
  .log-info  { color: #64748b; }
  .log-info .log-msg { color: #94a3b8; }
  .log-warn  { color: var(--yellow); }
  .log-error { color: var(--red); }
  .log-signal-hold  { color: #475569; }
  .log-signal-buy   { color: var(--green); font-weight: 500; }
  .log-signal-sell  { color: var(--red); font-weight: 500; }

  /* ── Ticker ── */
  .ticker-bar {
    background: var(--surface2);
    border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
    padding: 8px 28px;
    font-size: 11px;
    color: var(--muted);
    display: flex;
    gap: 28px;
    overflow: hidden;
  }

  .ticker-item { white-space: nowrap; }
  .ticker-item span { color: var(--text); font-weight: 500; margin-left: 4px; }

  @media (max-width: 1100px) {
    .stats-grid { grid-template-columns: repeat(3, 1fr); }
  }
  @media (max-width: 900px) {
    .stats-grid { grid-template-columns: repeat(3, 1fr); }
    .charts-row, .bottom-row { grid-template-columns: 1fr; }
  }
  @media (max-width: 600px) {
    .stats-grid { grid-template-columns: repeat(2, 1fr); }
    header { padding: 12px 16px; }
    .stats-grid, .charts-row, .bottom-row, .log-panel { padding-left: 16px; padding-right: 16px; }
    .section-divider { margin-left: 16px; margin-right: 16px; }
  }
</style>
</head>
<body>

<header>
  <div class="header-left">
    <div class="logo">📈</div>
    <div class="header-title">
      <h1>Tapi's Trading Bot</h1>
      <p>Deriv · Volatility Indices + MT5 CFD · Real Money</p>
    </div>
  </div>
  <div class="header-right">
    <div class="live-badge offline" id="live-badge">
      <div class="pulse off" id="pulse-dot"></div>
      <span id="live-text">Connecting…</span>
    </div>
    <span id="last-updated"></span>
  </div>
</header>

<div class="ticker-bar">
  <div class="ticker-item">Symbols <span>R_25 · R_50 · R_75 · R_100</span></div>
  <div class="ticker-item">Today <span id="ticker-date">—</span></div>
  <div class="ticker-item">Daily P&L <span id="ticker-pnl">—</span></div>
  <div class="ticker-item">Win Rate <span id="ticker-wr">—</span></div>
  <div class="ticker-item">Trades <span id="ticker-trades">—</span></div>
  <div class="ticker-item">MT5 Trades <span id="ticker-mt5-trades">—</span></div>
</div>

<div class="stats-grid">
  <div class="stat-card" style="--accent: var(--green)">
    <span class="icon">🏦</span>
    <div class="label">Account Balance</div>
    <div class="value white" id="account-balance">—</div>
    <div class="sub">Live balance</div>
  </div>
  <div class="stat-card" style="--accent: var(--green)">
    <span class="icon">💰</span>
    <div class="label">Daily P&L</div>
    <div class="value" id="daily-pnl">—</div>
    <div class="sub">Today's profit/loss</div>
  </div>
  <div class="stat-card" style="--accent: var(--cyan)">
    <span class="icon">📊</span>
    <div class="label">Total Profit</div>
    <div class="value" id="total-profit">—</div>
    <div class="sub">All closed trades</div>
  </div>
  <div class="stat-card" style="--accent: var(--blue)">
    <span class="icon">🎯</span>
    <div class="label">Win Rate</div>
    <div class="value blue" id="win-rate">—</div>
    <div class="sub" id="wl-sub">— wins / — losses</div>
  </div>
  <div class="stat-card" style="--accent: var(--purple)">
    <span class="icon">🔄</span>
    <div class="label">Total Trades</div>
    <div class="value white" id="total-trades">—</div>
    <div class="sub">Closed positions</div>
  </div>
  <div class="stat-card" style="--accent: var(--yellow)">
    <span class="icon">⚡</span>
    <div class="label">Best Trade</div>
    <div class="value green" id="best-trade">—</div>
    <div class="sub">Highest single profit</div>
  </div>
</div>

<div class="charts-row">
  <div class="panel">
    <div class="panel-header">
      <h2>Equity Curve</h2>
      <span class="badge" id="eq-badge">Cumulative P&L</span>
    </div>
    <div class="chart-wrap"><canvas id="equity-chart"></canvas></div>
  </div>
  <div class="panel">
    <div class="panel-header">
      <h2>Win / Loss Split</h2>
      <span class="badge" id="donut-badge">All trades</span>
    </div>
    <div class="donut-wrap"><canvas id="donut-chart"></canvas></div>
  </div>
</div>

<!-- Deriv Open Positions Banner -->
<div id="open-positions-bar" style="display:none; margin: 14px 28px 0; background: rgba(99,102,241,0.08); border: 1px solid rgba(99,102,241,0.25); border-radius: 12px; padding: 12px 20px;">
  <div style="font-size:11px; font-weight:600; color:var(--blue); text-transform:uppercase; letter-spacing:0.8px; margin-bottom:8px;">
    ⚡ Open Positions
  </div>
  <div id="open-positions-list" style="display:flex; flex-wrap:wrap; gap:10px;"></div>
</div>

<div class="bottom-row">
  <div class="panel">
    <div class="panel-header">
      <h2>Recent Trades</h2>
      <span class="badge">Last 15</span>
    </div>
    <table>
      <thead>
        <tr>
          <th>Time</th>
          <th>Symbol</th>
          <th>Direction</th>
          <th>Stake</th>
          <th>Profit</th>
          <th>Result</th>
        </tr>
      </thead>
      <tbody id="trades-body"></tbody>
    </table>
  </div>

  <div class="panel">
    <div class="panel-header">
      <h2>Performance Stats</h2>
    </div>
    <div id="perf-stats" style="display:flex; flex-direction:column; gap:12px; margin-top:4px;">
      <div class="perf-row" id="pr-avg-win"></div>
      <div class="perf-row" id="pr-avg-loss"></div>
      <div class="perf-row" id="pr-profit-factor"></div>
      <div class="perf-row" id="pr-max-dd"></div>
    </div>
  </div>
</div>

<!-- ── MT5 CFD Section ──────────────────────────────────────────────── -->
<div class="section-divider">
  <div class="section-label">🖥️ MetaTrader 5 CFD Bot</div>
  <div class="divider-line"></div>
</div>

<!-- MT5 Open Positions Banner -->
<div id="mt5-open-bar" style="display:none; margin: 14px 28px 0; background: rgba(249,115,22,0.08); border: 1px solid rgba(249,115,22,0.25); border-radius: 12px; padding: 12px 20px;">
  <div style="font-size:11px; font-weight:600; color:var(--orange); text-transform:uppercase; letter-spacing:0.8px; margin-bottom:8px;">
    ⚡ MT5 CFD Open Positions
  </div>
  <div id="mt5-open-list" style="display:flex; flex-wrap:wrap; gap:10px;"></div>
</div>

<div class="bottom-row">
  <div class="panel">
    <div class="panel-header">
      <h2>MT5 CFD Trades</h2>
      <span class="badge orange">Last 15</span>
    </div>
    <table>
      <thead>
        <tr>
          <th>Time</th>
          <th>Symbol</th>
          <th>Direction</th>
          <th>Lots</th>
          <th>Profit</th>
          <th>Result</th>
        </tr>
      </thead>
      <tbody id="mt5-trades-body">
        <tr><td colspan="6" style="text-align:center;color:var(--muted);padding:24px;font-size:12px;">
          Waiting for MT5 EA to connect…
        </td></tr>
      </tbody>
    </table>
  </div>

  <div class="panel">
    <div class="panel-header">
      <h2>MT5 Performance</h2>
    </div>
    <div id="mt5-perf-stats" style="display:flex; flex-direction:column; gap:12px; margin-top:4px;">
      <div class="perf-row" id="mt5-total-trades"></div>
      <div class="perf-row" id="mt5-win-rate"></div>
      <div class="perf-row" id="mt5-total-profit"></div>
      <div class="perf-row" id="mt5-best-trade"></div>
    </div>
  </div>
</div>

<div class="log-panel">
  <div class="panel-header">
    <h2>Live Bot Log</h2>
    <span class="badge">Auto-scroll</span>
  </div>
  <div id="log-box"></div>
</div>

<style>
  .perf-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 14px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    font-size: 13px;
  }
  .perf-row .pr-label { color: var(--muted); font-size: 12px; }
  .perf-row .pr-value { font-weight: 700; font-family: 'JetBrains Mono', monospace; }
</style>

<script>
let equityChart = null;
let donutChart = null;

function num(val, decimals=2) {
  return Math.abs(val).toLocaleString('en-US', {minimumFractionDigits: decimals, maximumFractionDigits: decimals});
}

function fmt(val, decimals=2) {
  const sign = val >= 0 ? '+' : '-';
  return sign + num(val, decimals);
}

function fmtTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch { return iso.slice(11, 19) || iso || '—'; }
}

function colorClass(val) {
  return val > 0 ? 'green' : val < 0 ? 'red' : 'white';
}

function perfRow(id, label, value, color) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = `<span class="pr-label">${label}</span><span class="pr-value" style="color:var(--${color})">${value}</span>`;
}

async function fetchStats() {
  try {
    const r = await fetch('/api/stats');
    const d = await r.json();

    const pnl = d.daily_pnl ?? 0;
    const tp  = d.total_profit ?? 0;
    const wr  = d.win_rate ?? 0;
    const bal = d.balance ?? 0;

    // Cards
    const balEl = document.getElementById('account-balance');
    if (bal > 0) {
      balEl.textContent = '$' + num(bal);
    }

    const pnlEl = document.getElementById('daily-pnl');
    pnlEl.textContent = fmt(pnl) + ' USD';
    pnlEl.className = 'value ' + colorClass(pnl);

    const tpEl = document.getElementById('total-profit');
    tpEl.textContent = fmt(tp) + ' USD';
    tpEl.className = 'value ' + colorClass(tp);

    document.getElementById('win-rate').textContent = wr + '%';
    document.getElementById('win-rate').className = 'value ' + (wr >= 50 ? 'green' : wr >= 40 ? 'yellow' : 'red');
    document.getElementById('total-trades').textContent = d.total_trades ?? 0;
    document.getElementById('wl-sub').textContent = `${d.wins ?? 0} wins / ${d.losses ?? 0} losses`;

    // Best trade
    const trades = d.recent_trades ?? [];
    const allTrades = [...trades].sort((a,b) => (b.profit??0)-(a.profit??0));
    const best = allTrades.length ? (allTrades[0].profit ?? 0) : 0;
    const bestEl = document.getElementById('best-trade');
    bestEl.textContent = best ? fmt(best) + ' USD' : '—';
    bestEl.className = 'value ' + colorClass(best);

    // Ticker
    document.getElementById('ticker-date').textContent = d.date || '—';
    document.getElementById('ticker-pnl').textContent = fmt(pnl) + ' USD';
    document.getElementById('ticker-wr').textContent = wr + '%';
    document.getElementById('ticker-trades').textContent = d.total_trades ?? 0;

    // Equity chart
    const labels = (d.equity_curve ?? []).map(e => fmtTime(e.time));
    const values = (d.equity_curve ?? []).map(e => e.equity);
    const lastVal = values.length ? values[values.length - 1] : 0;
    const lineColor = lastVal >= 0 ? '#10b981' : '#f43f5e';

    if (!equityChart) {
      const ctx = document.getElementById('equity-chart').getContext('2d');
      const grad = ctx.createLinearGradient(0, 0, 0, 210);
      grad.addColorStop(0, lastVal >= 0 ? 'rgba(16,185,129,0.2)' : 'rgba(244,63,94,0.2)');
      grad.addColorStop(1, 'rgba(0,0,0,0)');
      equityChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [{
            label: 'P&L (USD)',
            data: values,
            borderColor: lineColor,
            backgroundColor: grad,
            borderWidth: 2,
            pointRadius: values.length < 20 ? 3 : 0,
            pointHoverRadius: 5,
            fill: true,
            tension: 0.4,
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: ctx => ' ' + fmt(ctx.parsed.y) + ' USD'
              }
            }
          },
          scales: {
            x: { ticks: { color: '#475569', maxTicksLimit: 6, font: { size: 10, family: 'JetBrains Mono' } }, grid: { color: '#0f172a' } },
            y: { ticks: { color: '#475569', font: { size: 10, family: 'JetBrains Mono' }, callback: v => fmt(v) }, grid: { color: '#0f172a' } }
          }
        }
      });
    } else {
      equityChart.data.labels = labels;
      equityChart.data.datasets[0].data = values;
      equityChart.data.datasets[0].borderColor = lineColor;
      equityChart.update('none');
    }

    // Donut chart
    const wins = d.wins ?? 0;
    const losses = d.losses ?? 0;
    if (!donutChart) {
      const ctx2 = document.getElementById('donut-chart').getContext('2d');
      donutChart = new Chart(ctx2, {
        type: 'doughnut',
        data: {
          labels: ['Wins', 'Losses'],
          datasets: [{
            data: [wins || 1, losses || 0],
            backgroundColor: ['#10b981', '#f43f5e'],
            borderColor: '#0d1321',
            borderWidth: 3,
            hoverOffset: 6,
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          cutout: '68%',
          plugins: {
            legend: {
              position: 'bottom',
              labels: { color: '#64748b', font: { size: 11 }, padding: 14, boxWidth: 10, borderRadius: 3 }
            },
            tooltip: {
              callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed}` }
            }
          }
        }
      });
    } else {
      donutChart.data.datasets[0].data = [wins || 1, losses || 0];
      donutChart.update('none');
    }
    document.getElementById('donut-badge').textContent = wins + 'W / ' + losses + 'L';

    // Open positions banner
    const openPos = d.open_positions ?? [];
    const bar = document.getElementById('open-positions-bar');
    const list = document.getElementById('open-positions-list');
    if (openPos.length > 0) {
      bar.style.display = 'block';
      list.innerHTML = openPos.map(p => {
        const dir = p.contract_type === 'CALL' ? 'call' : 'put';
        const dirLabel = p.contract_type === 'CALL' ? '▲ CALL' : '▼ PUT';
        return `<div style="background:var(--surface);border:1px solid var(--border2);border-radius:8px;padding:8px 14px;font-size:12px;font-family:'JetBrains Mono',monospace;">
          <span class="tag ${dir}" style="margin-right:8px;">${dirLabel}</span>
          <span style="color:var(--muted);">Symbol:</span> <span style="color:var(--cyan);margin-right:8px;">${p.symbol||'R_10'}</span>
          <span style="color:var(--muted);">Stake:</span> <span style="color:var(--text);">${(p.stake??0).toFixed(2)}</span>
          <span style="color:var(--muted);margin-left:10px;">Payout:</span> <span style="color:var(--cyan);">${(p.payout??0).toFixed(2)}</span>
          <span style="color:var(--muted);margin-left:10px;">Opened:</span> <span style="color:var(--text);">${fmtTime(p.opened_at)}</span>
        </div>`;
      }).join('');
    } else {
      bar.style.display = 'none';
    }

    // Recent trades table
    const tbody = document.getElementById('trades-body');
    tbody.innerHTML = '';
    (trades).slice(0, 15).forEach(t => {
      const profit = t.profit ?? 0;
      const isWin = profit > 0;
      const dir = t.contract_type === 'CALL' ? 'call' : 'put';
      const dirLabel = t.contract_type === 'CALL' ? '▲ CALL' : '▼ PUT';
      const sym = t.symbol || '—';
      const row = document.createElement('tr');
      row.innerHTML =
        `<td>${fmtTime(t.closed_at)}</td>` +
        `<td style="color:var(--cyan)">${sym}</td>` +
        `<td><span class="tag ${dir}">${dirLabel}</span></td>` +
        `<td>${(t.stake ?? 0).toFixed(2)}</td>` +
        `<td class="${isWin ? 'profit-win' : 'profit-loss'}">${fmt(profit)}</td>` +
        `<td>${isWin ? '✅' : '❌'}</td>`;
      tbody.appendChild(row);
    });

    // Performance stats
    const closedWins  = trades.filter(t => (t.profit ?? 0) > 0);
    const closedLoss  = trades.filter(t => (t.profit ?? 0) <= 0);
    const avgWin  = closedWins.length  ? closedWins.reduce((s,t) => s + t.profit, 0)  / closedWins.length  : 0;
    const avgLoss = closedLoss.length  ? closedLoss.reduce((s,t) => s + t.profit, 0) / closedLoss.length  : 0;
    const grossW  = closedWins.reduce((s,t) => s + t.profit, 0);
    const grossL  = Math.abs(closedLoss.reduce((s,t) => s + t.profit, 0));
    const pf = grossL > 0 ? (grossW / grossL).toFixed(2) : (grossW > 0 ? '∞' : '—');

    let peak = 0, maxDD = 0, running = 0;
    trades.forEach(t => {
      running += t.profit ?? 0;
      if (running > peak) peak = running;
      const dd = peak - running;
      if (dd > maxDD) maxDD = dd;
    });

    perfRow('pr-avg-win',      'Avg Win',          closedWins.length  ? '+' + num(avgWin) + ' USD' : '—',  'green');
    perfRow('pr-avg-loss',     'Avg Loss',         closedLoss.length  ? '-' + num(Math.abs(avgLoss)) + ' USD' : '—',  'red');
    perfRow('pr-profit-factor','Profit Factor',    pf,                                                       'cyan');
    perfRow('pr-max-dd',       'Max Drawdown',     maxDD > 0 ? '-' + num(maxDD) + ' USD' : '—',             'yellow');

    // Live indicator
    document.getElementById('live-badge').className = 'live-badge';
    document.getElementById('pulse-dot').className = 'pulse';
    document.getElementById('live-text').textContent = 'Live';
    document.getElementById('last-updated').textContent =
      'Updated ' + new Date().toLocaleTimeString();

  } catch (e) {
    document.getElementById('live-badge').className = 'live-badge offline';
    document.getElementById('pulse-dot').className = 'pulse off';
    document.getElementById('live-text').textContent = 'Offline';
  }
}

async function fetchMt5Stats() {
  try {
    const r = await fetch('/api/mt5/stats');
    const d = await r.json();

    // Ticker update
    document.getElementById('ticker-mt5-trades').textContent = d.total_trades ?? 0;

    // MT5 open positions banner
    const openPos = d.open_positions ?? [];
    const bar = document.getElementById('mt5-open-bar');
    const list = document.getElementById('mt5-open-list');
    if (openPos.length > 0) {
      bar.style.display = 'block';
      list.innerHTML = openPos.map(p => {
        const cls = p.direction === 'BUY' ? 'buy' : 'sell';
        const lbl = p.direction === 'BUY' ? '▲ BUY' : '▼ SELL';
        return `<div style="background:var(--surface);border:1px solid var(--border2);border-radius:8px;padding:8px 14px;font-size:12px;font-family:'JetBrains Mono',monospace;">
          <span class="tag ${cls}" style="margin-right:8px;">${lbl}</span>
          <span style="color:var(--orange)">${p.symbol||'—'}</span>
          <span style="color:var(--muted);margin-left:10px;">Lots:</span> <span>${(p.lots??0).toFixed(2)}</span>
          <span style="color:var(--muted);margin-left:10px;">Price:</span> <span>${(p.price??0).toFixed(2)}</span>
          <span style="color:var(--muted);margin-left:10px;">Reason:</span> <span style="color:var(--yellow)">${p.reason||'—'}</span>
          <span style="color:var(--muted);margin-left:10px;">Opened:</span> <span>${p.opened_at||'—'}</span>
        </div>`;
      }).join('');
    } else {
      bar.style.display = 'none';
    }

    // MT5 trades table
    const trades = d.recent_trades ?? [];
    const tbody = document.getElementById('mt5-trades-body');
    if (trades.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:24px;font-size:12px;">Waiting for MT5 EA to connect…</td></tr>';
    } else {
      tbody.innerHTML = '';
      trades.slice(0, 15).forEach(t => {
        const profit = t.profit ?? 0;
        const isWin = profit > 0;
        const cls = t.direction === 'BUY' ? 'buy' : 'sell';
        const lbl = t.direction === 'BUY' ? '▲ BUY' : '▼ SELL';
        const row = document.createElement('tr');
        row.innerHTML =
          `<td>${t.closed_at || t.opened_at || '—'}</td>` +
          `<td style="color:var(--orange);font-weight:600">${t.symbol || '—'}</td>` +
          `<td><span class="tag ${cls}">${lbl}</span></td>` +
          `<td>${(t.lots ?? 0).toFixed(2)}</td>` +
          `<td class="${isWin ? 'profit-win' : 'profit-loss'}">${fmt(profit)}</td>` +
          `<td>${isWin ? '✅' : '❌'}</td>`;
        tbody.appendChild(row);
      });
    }

    // MT5 performance stats
    const totalTrades = d.total_trades ?? 0;
    const wins = d.wins ?? 0;
    const losses = d.losses ?? 0;
    const winRate = d.win_rate ?? 0;
    const totalProfit = d.total_profit ?? 0;
    const bestTrade = trades.length ? Math.max(...trades.map(t => t.profit ?? 0)) : 0;

    perfRow('mt5-total-trades', 'Total Trades', totalTrades + ' (' + wins + 'W / ' + losses + 'L)', 'text');
    perfRow('mt5-win-rate', 'Win Rate', winRate + '%', winRate >= 50 ? 'green' : winRate > 0 ? 'yellow' : 'muted');
    perfRow('mt5-total-profit', 'Total Profit', totalProfit !== 0 ? fmt(totalProfit) + ' USD' : '—', totalProfit >= 0 ? 'green' : 'red');
    perfRow('mt5-best-trade', 'Best Trade', bestTrade > 0 ? '+' + num(bestTrade) + ' USD' : '—', 'green');

  } catch (e) {
    // MT5 endpoint unavailable
  }
}

async function fetchLog() {
  try {
    const r = await fetch('/api/log');
    const d = await r.json();
    const box = document.getElementById('log-box');
    const atBottom = box.scrollHeight - box.clientHeight <= box.scrollTop + 8;
    box.innerHTML = (d.lines ?? []).map(line => {
      const safe = line.replace(/</g, '&lt;');
      if (line.includes('[ERROR]') || line.includes('[CRITICAL]'))
        return `<div class="log-error">${safe}</div>`;
      if (line.includes('[WARNING]') || line.includes('[WARN]'))
        return `<div class="log-warn">${safe}</div>`;
      if (line.includes('Signal=BUY') || line.includes('Signal=CALL'))
        return `<div class="log-signal-buy">${safe}</div>`;
      if (line.includes('Signal=SELL') || line.includes('Signal=PUT'))
        return `<div class="log-signal-sell">${safe}</div>`;
      if (line.includes('Signal=HOLD'))
        return `<div class="log-signal-hold">${safe}</div>`;
      return `<div class="log-info">${safe}</div>`;
    }).join('');
    if (atBottom) box.scrollTop = box.scrollHeight;
  } catch {}
}

async function refresh() {
  await Promise.all([fetchStats(), fetchMt5Stats(), fetchLog()]);
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


async def index(request):
    return web.Response(text=HTML, content_type="text/html")


def build_app() -> web.Application:
    global _mt5_trades
    _mt5_trades = _load_mt5_trades()
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/stats", api_stats)
    app.router.add_get("/api/log", api_log)
    app.router.add_post("/api/mt5/trade", api_mt5_trade)
    app.router.add_get("/api/mt5/stats", api_mt5_stats)
    return app


if __name__ == "__main__":
    app = build_app()
    print(f"Dashboard running at http://{HOST}:{PORT}")
    print(f"Reading data from: {os.path.abspath(DATA_DIR)}")
    web.run_app(app, host=HOST, port=PORT, print=None)
