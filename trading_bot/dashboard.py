"""
Trading Bot Dashboard
A lightweight aiohttp web server that exposes real-time bot stats via a browser UI.
Run with:  python -m trading_bot.dashboard   (or python dashboard.py from this dir)
"""

import json
import os
import sys
from pathlib import Path

from aiohttp import web

# ── config ───────────────────────────────────────────────────────────────────
DATA_DIR = os.environ.get("TRADING_DATA_DIR", "./data")
HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.environ.get("DASHBOARD_PORT", "8080"))
LOG_TAIL_LINES = 150


# ── helpers ───────────────────────────────────────────────────────────────────
def _tail(path: str, n: int) -> list[str]:
    """Return last n lines of a file without reading the whole thing."""
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
    wins = [t for t in trades if t.get("profit", 0) > 0]
    losses = [t for t in trades if t.get("profit", 0) <= 0]
    total_profit = sum(t.get("profit", 0) for t in trades)
    win_rate = round(len(wins) / len(trades) * 100, 1) if trades else 0

    # Equity curve: cumulative profit per closed trade
    equity = []
    running = 0.0
    for t in trades:
        running += t.get("profit", 0)
        equity.append({"time": t.get("closed_at", ""), "equity": round(running, 2)})

    payload = {
        "date": state.get("date", ""),
        "daily_pnl": round(state.get("daily_pnl", 0.0), 2),
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "total_profit": round(total_profit, 2),
        "equity_curve": equity,
        "recent_trades": trades[-20:][::-1],  # newest first, last 20
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
<title>Trading Bot Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0f1117; --surface: #1a1d27; --border: #2a2d3a;
    --text: #e2e8f0; --muted: #8892a4;
    --green: #22c55e; --red: #ef4444; --yellow: #eab308; --blue: #3b82f6;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; font-size: 14px; }
  header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 14px 24px;
           display: flex; align-items: center; justify-content: space-between; }
  header h1 { font-size: 18px; font-weight: 600; letter-spacing: .3px; }
  #status-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--muted); display: inline-block; margin-right: 6px; }
  #status-dot.live { background: var(--green); box-shadow: 0 0 6px var(--green); }
  #last-updated { color: var(--muted); font-size: 12px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; padding: 20px 24px 0; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px 20px; }
  .card .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .8px; margin-bottom: 6px; }
  .card .value { font-size: 28px; font-weight: 700; }
  .card .value.green { color: var(--green); }
  .card .value.red   { color: var(--red); }
  .card .value.blue  { color: var(--blue); }
  .card .value.yellow{ color: var(--yellow); }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 16px 24px 0; }
  .panel { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 18px 20px; }
  .panel h2 { font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .8px; margin-bottom: 14px; }
  .chart-wrap { position: relative; height: 200px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th { color: var(--muted); text-align: left; padding: 4px 8px; font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: .6px; border-bottom: 1px solid var(--border); }
  td { padding: 6px 8px; border-bottom: 1px solid #1e2130; }
  tr:last-child td { border-bottom: none; }
  .win  { color: var(--green); font-weight: 600; }
  .loss { color: var(--red);   font-weight: 600; }
  .log-panel { margin: 16px 24px; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 18px 20px; }
  .log-panel h2 { font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .8px; margin-bottom: 12px; }
  #log-box { background: #090b10; border-radius: 6px; padding: 10px 14px; height: 220px; overflow-y: auto;
             font-family: 'Cascadia Code', 'Fira Mono', monospace; font-size: 11.5px; line-height: 1.6; color: #a8b4c8; }
  .log-info  { color: #a8b4c8; }
  .log-warn  { color: var(--yellow); }
  .log-error { color: var(--red); }
  footer { text-align: center; padding: 20px; color: var(--muted); font-size: 11px; }
  @media (max-width: 700px) { .row { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<header>
  <h1><span id="status-dot"></span> Deriv Trading Bot</h1>
  <span id="last-updated">Connecting…</span>
</header>

<div class="grid">
  <div class="card"><div class="label">Daily P&amp;L</div><div class="value" id="daily-pnl">—</div></div>
  <div class="card"><div class="label">Total Profit</div><div class="value" id="total-profit">—</div></div>
  <div class="card"><div class="label">Win Rate</div><div class="value blue" id="win-rate">—</div></div>
  <div class="card"><div class="label">Total Trades</div><div class="value" id="total-trades">—</div></div>
  <div class="card"><div class="label">Wins / Losses</div><div class="value" id="wl">—</div></div>
</div>

<div class="row">
  <div class="panel">
    <h2>Equity Curve</h2>
    <div class="chart-wrap"><canvas id="equity-chart"></canvas></div>
  </div>
  <div class="panel">
    <h2>Recent Trades</h2>
    <table>
      <thead><tr><th>Time</th><th>Type</th><th>Stake</th><th>Profit</th></tr></thead>
      <tbody id="trades-body"></tbody>
    </table>
  </div>
</div>

<div class="log-panel">
  <h2>Live Bot Log</h2>
  <div id="log-box"></div>
</div>

<footer>Auto-refreshes every 5 seconds &nbsp;·&nbsp; Data dir: <code id="data-dir-label">data/</code></footer>

<script>
let equityChart = null;

function colorClass(val) {
  if (val > 0) return 'green';
  if (val < 0) return 'red';
  return '';
}

function fmt(val) {
  const sign = val >= 0 ? '+' : '';
  return sign + val.toFixed(2);
}

function fmtTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch { return iso.slice(11, 19) || '—'; }
}

async function fetchStats() {
  try {
    const r = await fetch('/api/stats');
    const d = await r.json();

    // Stat cards
    const pnl = d.daily_pnl ?? 0;
    const tp  = d.total_profit ?? 0;
    document.getElementById('daily-pnl').textContent   = fmt(pnl) + ' AUD';
    document.getElementById('daily-pnl').className     = 'value ' + colorClass(pnl);
    document.getElementById('total-profit').textContent = fmt(tp) + ' AUD';
    document.getElementById('total-profit').className   = 'value ' + colorClass(tp);
    document.getElementById('win-rate').textContent     = (d.win_rate ?? 0) + '%';
    document.getElementById('total-trades').textContent = d.total_trades ?? 0;
    document.getElementById('wl').textContent           = (d.wins ?? 0) + ' / ' + (d.losses ?? 0);

    // Equity chart
    const labels = (d.equity_curve ?? []).map(e => fmtTime(e.time));
    const values = (d.equity_curve ?? []).map(e => e.equity);
    if (!equityChart) {
      const ctx = document.getElementById('equity-chart').getContext('2d');
      equityChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [{
            label: 'Cumulative P&L (AUD)',
            data: values,
            borderColor: '#3b82f6',
            backgroundColor: 'rgba(59,130,246,0.08)',
            borderWidth: 2,
            pointRadius: 2,
            fill: true,
            tension: 0.3,
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { ticks: { color: '#8892a4', maxTicksLimit: 8, font: { size: 10 } }, grid: { color: '#1e2130' } },
            y: { ticks: { color: '#8892a4', font: { size: 10 } }, grid: { color: '#1e2130' } }
          }
        }
      });
    } else {
      equityChart.data.labels = labels;
      equityChart.data.datasets[0].data = values;
      equityChart.update('none');
    }

    // Recent trades table
    const tbody = document.getElementById('trades-body');
    tbody.innerHTML = '';
    (d.recent_trades ?? []).forEach(t => {
      const profit = t.profit ?? 0;
      const row = document.createElement('tr');
      row.innerHTML =
        `<td>${fmtTime(t.closed_at)}</td>` +
        `<td>${t.contract_type ?? '—'}</td>` +
        `<td>${(t.stake ?? 0).toFixed(2)}</td>` +
        `<td class="${profit > 0 ? 'win' : 'loss'}">${fmt(profit)}</td>`;
      tbody.appendChild(row);
    });

    // Status dot
    document.getElementById('status-dot').className = 'live';
    document.getElementById('last-updated').textContent =
      'Updated ' + new Date().toLocaleTimeString();
  } catch (e) {
    document.getElementById('status-dot').className = '';
    document.getElementById('last-updated').textContent = 'Offline — retrying…';
  }
}

async function fetchLog() {
  try {
    const r = await fetch('/api/log');
    const d = await r.json();
    const box = document.getElementById('log-box');
    const atBottom = box.scrollHeight - box.clientHeight <= box.scrollTop + 4;
    box.innerHTML = (d.lines ?? []).map(line => {
      let cls = 'log-info';
      if (line.includes('[WARNING]') || line.includes('[WARN]')) cls = 'log-warn';
      if (line.includes('[ERROR]') || line.includes('[CRITICAL]')) cls = 'log-error';
      return `<div class="${cls}">${line.replace(/</g,'&lt;')}</div>`;
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


# ── app factory ───────────────────────────────────────────────────────────────
def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/stats", api_stats)
    app.router.add_get("/api/log", api_log)
    return app


if __name__ == "__main__":
    app = build_app()
    print(f"Dashboard running at http://{HOST}:{PORT}")
    print(f"Reading data from: {os.path.abspath(DATA_DIR)}")
    web.run_app(app, host=HOST, port=PORT, print=None)
