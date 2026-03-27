"""
Tapi's Trading Bot Dashboard - Real Account
A lightweight aiohttp web server that exposes real-time bot stats via a browser UI.
Run with:  python real_dashboard.py   (from the trading_bot directory)
"""

import json
import os

from aiohttp import web

# ── config ───────────────────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SYMBOL = os.environ.get("TRADING_SYMBOL", "R_25")
DATA_DIR = os.environ.get("TRADING_DATA_DIR", os.path.join(_SCRIPT_DIR, "data", SYMBOL))
HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.environ.get("DASHBOARD_PORT", "8081"))
LOG_TAIL_LINES = 150
STARTING_BALANCE = float(os.environ.get("TRADING_STARTING_BALANCE", "100"))
DAILY_PROFIT_TARGET_PCT = float(os.environ.get("TRADING_DAILY_TARGET_PCT", "15.0"))
MAX_DAILY_LOSS_PCT = float(os.environ.get("TRADING_MAX_DAILY_LOSS_PCT", "15.0"))


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

    calls = [t for t in trades if t.get("contract_type") == "CALL"]
    puts  = [t for t in trades if t.get("contract_type") == "PUT"]
    call_wins = len([t for t in calls if t.get("profit", 0) > 0])
    put_wins  = len([t for t in puts  if t.get("profit", 0) > 0])

    recent_20 = trades[-20:] if len(trades) >= 5 else []
    rolling_win_rate = (
        round(len([t for t in recent_20 if t.get("profit", 0) > 0]) / len(recent_20) * 100, 1)
        if recent_20 else None
    )
    profit_target = round(STARTING_BALANCE * DAILY_PROFIT_TARGET_PCT / 100, 2)
    loss_limit = round(state.get("balance", STARTING_BALANCE) * MAX_DAILY_LOSS_PCT / 100, 2)

    consecutive_losses = 0
    for t in reversed(trades):
        if t.get("profit", 0) < 0:
            consecutive_losses += 1
        else:
            break

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
        "call_count": len(calls),
        "put_count": len(puts),
        "call_wins": call_wins,
        "put_wins": put_wins,
        "consecutive_losses": consecutive_losses,
        "equity_curve": equity,
        "recent_trades": trades[-20:][::-1],
        "open_positions": open_positions,
        "rolling_win_rate": rolling_win_rate,
        "profit_target": profit_target,
        "loss_limit": loss_limit,
        "symbol": SYMBOL,
    }
    return web.json_response(payload)


async def api_log(request):
    lines = _tail(os.path.join(DATA_DIR, "bot.log"), LOG_TAIL_LINES)
    return web.json_response({"lines": lines})


# ── HTML ──────────────────────────────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tapi's Trading Bot · Real</title>
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
    --blue: #f59e0b;
    --blue-dim: rgba(245,158,11,0.12);
    --yellow: #f59e0b;
    --yellow-dim: rgba(245,158,11,0.12);
    --cyan: #22d3ee;
    --purple: #fb923c;
    --glow-green: 0 0 20px rgba(16,185,129,0.3);
    --glow-red: 0 0 20px rgba(244,63,94,0.3);
    --glow-blue: 0 0 20px rgba(245,158,11,0.25);
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
    background: linear-gradient(135deg, #f59e0b, #fb923c);
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

  .profit-win  { color: var(--green); font-weight: 600; }
  .profit-loss { color: var(--red);   font-weight: 600; }

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
  .log-signal-score { color: #374151; }
  .log-signal-score .score-val { color: #6b7280; }
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
  }
</style>
</head>
<body>

<header>
  <div class="header-left">
    <div class="logo">📈</div>
    <div class="header-title">
      <h1>Tapi's Trading Bot · Real</h1>
      <p id="header-subtitle">Deriv · R_25 · Live Account</p>
    </div>
  </div>
  <div class="header-right">
    <div style="background:rgba(245,158,11,0.15);border:1px solid rgba(245,158,11,0.4);border-radius:20px;padding:5px 12px;font-size:11px;font-weight:700;color:#f59e0b;letter-spacing:1px;">REAL MONEY</div>
    <div class="live-badge offline" id="live-badge">
      <div class="pulse off" id="pulse-dot"></div>
      <span id="live-text">Connecting…</span>
    </div>
    <span id="last-updated"></span>
  </div>
</header>

<div class="ticker-bar">
  <div class="ticker-item">Symbol <span id="ticker-symbol">—</span></div>
  <div class="ticker-item">Today <span id="ticker-date">—</span></div>
  <div class="ticker-item">Daily P&L <span id="ticker-pnl">—</span></div>
  <div class="ticker-item">Win Rate <span id="ticker-wr">—</span></div>
  <div class="ticker-item">Trades <span id="ticker-trades">—</span></div>
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
    <div class="sub" id="pnl-sub">Today's profit/loss</div>
    <div style="margin-top:8px;">
      <div style="height:4px;background:var(--border);border-radius:2px;overflow:hidden;">
        <div id="profit-bar" style="height:100%;width:0%;background:var(--green);border-radius:2px;transition:width 0.5s;"></div>
      </div>
      <div style="font-size:10px;color:var(--muted);margin-top:3px;" id="profit-bar-label">Target: —</div>
    </div>
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
  <div class="stat-card" style="--accent: var(--red)">
    <span class="icon">🔥</span>
    <div class="label">Loss Streak</div>
    <div class="value green" id="consec-losses">—</div>
    <div class="sub" id="consec-losses-sub">Cooldown status</div>
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
      <h2>CALL / PUT Performance</h2>
      <span class="badge" id="dir-badge">Direction split</span>
    </div>
    <div class="chart-wrap"><canvas id="dir-chart"></canvas></div>
  </div>
</div>

<!-- Open positions banner -->
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
      <div class="perf-row" id="pr-rolling-wr"></div>
      <div class="perf-row" id="pr-avg-win"></div>
      <div class="perf-row" id="pr-avg-loss"></div>
      <div class="perf-row" id="pr-profit-factor"></div>
      <div class="perf-row" id="pr-max-dd"></div>
      <div class="perf-row" id="pr-call-wr"></div>
      <div class="perf-row" id="pr-put-wr"></div>
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
let dirChart = null;

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
  } catch { return iso.slice(11, 19) || '—'; }
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

    // Consecutive losses card
    const trades = d.recent_trades ?? [];
    const cl = d.consecutive_losses ?? 0;
    const clEl = document.getElementById('consec-losses');
    const clSub = document.getElementById('consec-losses-sub');
    clEl.textContent = cl;
    if (cl === 0) {
      clEl.className = 'value green';
      clSub.textContent = 'Streak clear';
    } else if (cl === 1) {
      clEl.className = 'value yellow';
      clSub.textContent = '1 loss in a row';
    } else {
      clEl.className = 'value red';
      clSub.textContent = 'Cooldown active · ' + cl + ' cycles';
    }

    // Symbol
    const sym = d.symbol ?? 'R_?';
    const symEl = document.getElementById('ticker-symbol');
    if (symEl) symEl.textContent = sym;
    const subEl = document.getElementById('header-subtitle');
    if (subEl) subEl.textContent = 'Deriv · ' + sym + ' · Live Account';

    // Profit target progress bar
    const profitTarget = d.profit_target ?? 15;
    const profitBar = document.getElementById('profit-bar');
    const profitBarLabel = document.getElementById('profit-bar-label');
    if (profitBar && profitBarLabel) {
      const pct = Math.min(100, Math.max(0, pnl > 0 ? (pnl / profitTarget) * 100 : 0));
      profitBar.style.width = pct + '%';
      profitBar.style.background = pct >= 100 ? 'var(--red)' : pct >= 75 ? 'var(--yellow)' : 'var(--green)';
      profitBarLabel.textContent = 'Target: +' + profitTarget.toFixed(2) + ' USD (' + Math.round(pct) + '%)';
    }

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

    // CALL / PUT performance chart
    const callCount = d.call_count ?? 0;
    const putCount  = d.put_count  ?? 0;
    const callWins  = d.call_wins  ?? 0;
    const putWins   = d.put_wins   ?? 0;
    const callLosses = callCount - callWins;
    const putLosses  = putCount  - putWins;
    if (!dirChart) {
      const ctx2 = document.getElementById('dir-chart').getContext('2d');
      dirChart = new Chart(ctx2, {
        type: 'bar',
        data: {
          labels: ['CALL ▲', 'PUT ▼'],
          datasets: [
            {
              label: 'Wins',
              data: [callWins, putWins],
              backgroundColor: 'rgba(16,185,129,0.7)',
              borderColor: '#10b981',
              borderWidth: 1,
              borderRadius: 4,
            },
            {
              label: 'Losses',
              data: [callLosses, putLosses],
              backgroundColor: 'rgba(244,63,94,0.7)',
              borderColor: '#f43f5e',
              borderWidth: 1,
              borderRadius: 4,
            }
          ]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { position: 'bottom', labels: { color: '#64748b', font: { size: 11 }, padding: 14, boxWidth: 10 } },
            tooltip: { callbacks: { label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.y}` } }
          },
          scales: {
            x: { ticks: { color: '#475569', font: { size: 12 } }, grid: { display: false } },
            y: { ticks: { color: '#475569', font: { size: 10, family: 'JetBrains Mono' }, stepSize: 1 }, grid: { color: '#0f172a' } }
          }
        }
      });
    } else {
      dirChart.data.datasets[0].data = [callWins, putWins];
      dirChart.data.datasets[1].data = [callLosses, putLosses];
      dirChart.update('none');
    }
    document.getElementById('dir-badge').textContent = callCount + ' CALL / ' + putCount + ' PUT';

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
      const row = document.createElement('tr');
      row.innerHTML =
        `<td>${fmtTime(t.closed_at)}</td>` +
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

    // Max drawdown from equity curve
    let peak = 0, maxDD = 0, running = 0;
    trades.forEach(t => {
      running += t.profit ?? 0;
      if (running > peak) peak = running;
      const dd = peak - running;
      if (dd > maxDD) maxDD = dd;
    });

    const rwr = d.rolling_win_rate;
    perfRow('pr-rolling-wr', 'Rolling Win Rate (20)', rwr !== null && rwr !== undefined ? rwr + '%' : '—',
      rwr >= 50 ? 'green' : rwr >= 40 ? 'yellow' : 'red');
    perfRow('pr-avg-win',      'Avg Win',          closedWins.length  ? '+' + num(avgWin) + ' USD' : '—',  'green');
    perfRow('pr-avg-loss',     'Avg Loss',         closedLoss.length  ? '-' + num(Math.abs(avgLoss)) + ' USD' : '—',  'red');
    perfRow('pr-profit-factor','Profit Factor',    pf,                                                       'cyan');
    perfRow('pr-max-dd',       'Max Drawdown',     maxDD > 0 ? '-' + num(maxDD) + ' USD' : '—',             'yellow');
    const callWinRate = callCount ? Math.round(callWins / callCount * 100) : null;
    const putWinRate  = putCount  ? Math.round(putWins  / putCount  * 100) : null;
    perfRow('pr-call-wr', '▲ CALL Win Rate', callWinRate !== null ? callWinRate + '% (' + callCount + ' trades)' : '—', callWinRate >= 50 ? 'green' : 'red');
    perfRow('pr-put-wr',  '▼ PUT Win Rate',  putWinRate  !== null ? putWinRate  + '% (' + putCount  + ' trades)' : '—', putWinRate  >= 50 ? 'green' : 'red');

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
      if (line.includes('HOLD | BUY='))
        return `<div class="log-signal-score">${safe}</div>`;
      if (line.includes('Signal=HOLD'))
        return `<div class="log-signal-hold">${safe}</div>`;
      return `<div class="log-info">${safe}</div>`;
    }).join('');
    if (atBottom) box.scrollTop = box.scrollHeight;
  } catch {}
}

async function refresh() {
  await Promise.all([fetchStats(), fetchLog()]);
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
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/stats", api_stats)
    app.router.add_get("/api/log", api_log)
    return app


if __name__ == "__main__":
    app = build_app()
    print(f"Real Account Dashboard running at http://{HOST}:{PORT}")
    print(f"Reading data from: {os.path.abspath(DATA_DIR)}")
    web.run_app(app, host=HOST, port=PORT, print=None)
