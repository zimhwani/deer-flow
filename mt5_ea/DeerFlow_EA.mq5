//+------------------------------------------------------------------+
//|  DeerFlow_EA.mq5                                                 |
//|  Mirrors the Python bot strategy:                                |
//|    Path 1 — Mean-reversion  (BB extreme + RSI extreme + reversal)|
//|    Path 2 — Trend-following (EMA crossover + macro trend + RSI)  |
//|                                                                  |
//|  Tested on: CRASH300N, CRASH500N, BOOM300N, BOOM500N             |
//|  Timeframe: M1                                                   |
//+------------------------------------------------------------------+
#property copyright "DeerFlow"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//── Inputs ──────────────────────────────────────────────────────────
input group "Strategy"
input int    InpEmaFast        = 10;     // Fast EMA period
input int    InpEmaSlow        = 20;     // Slow EMA period
input int    InpEmaMacro       = 50;     // Macro EMA period (trend gate)
input int    InpRsiPeriod      = 14;     // RSI period
input int    InpBbPeriod       = 20;     // Bollinger Bands period
input double InpBbDeviation    = 2.0;   // Bollinger Bands std deviation
input double InpConfidence     = 0.60;  // Signal confidence threshold

input group "Trade Sizing"
input double InpLotSize        = 0.30;  // Default lot size
input double InpMaxRiskPct     = 2.0;   // Max risk % of balance per trade

input group "Exit Levels — Trend trades"
input int    InpTrendSL        = 300;   // Stop loss  (points) for trend trades
input int    InpTrendTP        = 600;   // Take profit (points) for trend trades

input group "Exit Levels — Mean-reversion trades"
input int    InpRevSL          = 500;   // Stop loss  (points) for mean-rev trades
input int    InpRevTP          = 1000;  // Take profit (points) for mean-rev trades

input group "Risk Management"
input int    InpMaxPositions   = 3;     // Max open positions at once
input bool   InpUseDailyLoss   = true;  // Enable daily loss limit
input double InpDailyLossPct   = 10.0; // Daily loss limit % of balance
input bool   InpUseDailyTarget = false; // Enable daily profit target
input double InpDailyTargetPct = 999.0; // Daily profit target %

input group "Dashboard Bridge"
input string InpDashboardUrl   = "http://209.38.87.199/api/mt5/trade"; // Dashboard URL (empty to disable)

input group "EA Settings"
input int    InpMagicNumber    = 20260528; // Magic number (unique ID)
input bool   InpTradeOnNewBar  = true;  // Only trade on new M1 bar open

//── Globals ─────────────────────────────────────────────────────────
CTrade  trade;
double  g_dailyStartBalance = 0;
datetime g_currentDay       = 0;
int     g_hEmaFast, g_hEmaSlow, g_hEmaMacro, g_hRsi, g_hBB;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(50);

   g_hEmaFast = iMA(_Symbol, PERIOD_M1, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   g_hEmaSlow = iMA(_Symbol, PERIOD_M1, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
   g_hEmaMacro= iMA(_Symbol, PERIOD_M1, InpEmaMacro,0, MODE_EMA, PRICE_CLOSE);
   g_hRsi     = iRSI(_Symbol, PERIOD_M1, InpRsiPeriod, PRICE_CLOSE);
   g_hBB      = iBands(_Symbol, PERIOD_M1, InpBbPeriod, 0, InpBbDeviation, PRICE_CLOSE);

   if(g_hEmaFast == INVALID_HANDLE || g_hEmaSlow == INVALID_HANDLE ||
      g_hEmaMacro == INVALID_HANDLE || g_hRsi == INVALID_HANDLE || g_hBB == INVALID_HANDLE)
   {
      Print("ERROR: Failed to create indicator handles");
      return INIT_FAILED;
   }

   g_dailyStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   g_currentDay        = iTime(_Symbol, PERIOD_D1, 0);

   Print("DeerFlow EA started | Symbol: ", _Symbol,
         " | Balance: ", g_dailyStartBalance,
         " | Magic: ", InpMagicNumber);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(g_hEmaFast);
   IndicatorRelease(g_hEmaSlow);
   IndicatorRelease(g_hEmaMacro);
   IndicatorRelease(g_hRsi);
   IndicatorRelease(g_hBB);
   Print("DeerFlow EA stopped");
}

//+------------------------------------------------------------------+
void OnTick()
{
   // Only act on new M1 bar
   if(InpTradeOnNewBar)
   {
      static datetime lastBar = 0;
      datetime currentBar = iTime(_Symbol, PERIOD_M1, 0);
      if(currentBar == lastBar) return;
      lastBar = currentBar;
   }

   // Daily reset
   datetime today = iTime(_Symbol, PERIOD_D1, 0);
   if(today != g_currentDay)
   {
      g_currentDay        = today;
      g_dailyStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
      PrintFormat("New day. Start balance: %.2f", g_dailyStartBalance);
   }

   // Daily loss / target guards
   double balance   = AccountInfoDouble(ACCOUNT_BALANCE);
   double dailyPnl  = balance - g_dailyStartBalance;

   if(InpUseDailyLoss && dailyPnl < -(g_dailyStartBalance * InpDailyLossPct / 100.0))
   {
      PrintFormat("Daily loss limit hit (%.2f). Skipping.", dailyPnl);
      return;
   }
   if(InpUseDailyTarget && dailyPnl >= g_dailyStartBalance * InpDailyTargetPct / 100.0)
   {
      PrintFormat("Daily profit target hit (+%.2f). Skipping.", dailyPnl);
      return;
   }

   // Max positions guard
   if(CountMyPositions() >= InpMaxPositions) return;

   // ── Read indicators ──────────────────────────────────────────────
   double ema10[3], ema20[6], ema50[1], rsi[2], bbUp[1], bbLow[1];

   if(CopyBuffer(g_hEmaFast,  0, 0, 3, ema10)  < 3) return;
   if(CopyBuffer(g_hEmaSlow,  0, 0, 6, ema20)  < 6) return;
   if(CopyBuffer(g_hEmaMacro, 0, 0, 1, ema50)  < 1) return;
   if(CopyBuffer(g_hRsi,      0, 0, 2, rsi)    < 2) return;
   if(CopyBuffer(g_hBB, UPPER_BAND, 0, 1, bbUp)  < 1) return;
   if(CopyBuffer(g_hBB, LOWER_BAND, 0, 1, bbLow) < 1) return;

   // ArraySetAsSeries so index 0 = most recent
   ArraySetAsSeries(ema10,  true);
   ArraySetAsSeries(ema20,  true);
   ArraySetAsSeries(ema50,  true);
   ArraySetAsSeries(rsi,    true);
   ArraySetAsSeries(bbUp,   true);
   ArraySetAsSeries(bbLow,  true);

   double price       = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double emaFast     = ema10[0];
   double emaSlow     = ema20[0];
   double emaMacro    = ema50[0];
   double rsiNow      = rsi[0];
   double rsiPrev     = rsi[1];
   double bbUpper     = bbUp[0];
   double bbLower     = bbLow[0];

   // ── Derived conditions ───────────────────────────────────────────
   bool trendUp   = ema20[0] > ema20[4];   // EMA20 slope over ~5 bars
   bool trendDown = ema20[0] < ema20[4];
   bool rsiRising  = rsiNow > rsiPrev;
   bool rsiFalling = rsiNow < rsiPrev;
   bool macroBull  = price > emaMacro;
   bool macroBear  = price < emaMacro;

   double emaSpreadPct = MathAbs(emaFast - emaSlow) / emaSlow * 100.0;
   bool   emaSpreadOk  = emaSpreadPct >= 0.02;

   // Consecutive candles (last 3)
   int bullCount = 0, bearCount = 0;
   for(int i = 1; i <= 3; i++)
   {
      double c = iClose(_Symbol, PERIOD_M1, i);
      double o = iOpen (_Symbol, PERIOD_M1, i);
      if(c > o) bullCount++;
      if(c < o) bearCount++;
   }
   bool consecBull = bullCount >= 2;
   bool consecBear = bearCount >= 2;

   // ── Signal scoring (mirrors Python) ─────────────────────────────
   double buyConf  = 0.0;
   double sellConf = 0.0;
   bool   isMeanRevBuy  = false;
   bool   isMeanRevSell = false;

   // Path 1 — Mean-reversion BUY
   if(price < bbLower && rsiNow < 35.0 && rsiRising)
   {
      buyConf += 0.65;
      isMeanRevBuy = true;
   }
   // Path 2 — Trend BUY
   else if(macroBull && rsiNow > 28.0 && rsiNow < 72.0)
   {
      if(emaFast > emaSlow && emaSpreadOk)  buyConf += 0.30;
      if(trendUp)                           buyConf += 0.15;
      if(rsiNow > 35.0 && rsiNow < 60.0 && rsiRising) buyConf += 0.15;
      if(consecBull)                        buyConf += 0.15;
   }

   // Path 1 — Mean-reversion SELL
   if(price > bbUpper && rsiNow > 65.0 && rsiFalling)
   {
      sellConf += 0.65;
      isMeanRevSell = true;
   }
   // Path 2 — Trend SELL
   else if(macroBear && rsiNow > 45.0)
   {
      if(emaFast < emaSlow && emaSpreadOk)  sellConf += 0.30;
      if(trendDown)                         sellConf += 0.15;
      if(rsiNow > 40.0 && rsiNow < 65.0 && rsiFalling) sellConf += 0.15;
      if(consecBear)                        sellConf += 0.15;
   }

   // ── Execute ──────────────────────────────────────────────────────
   if(buyConf >= InpConfidence && buyConf > sellConf)
   {
      int sl = isMeanRevBuy ? InpRevSL : InpTrendSL;
      int tp = isMeanRevBuy ? InpRevTP : InpTrendTP;
      OpenBuy(sl, tp, isMeanRevBuy ? "mean-rev" : "trend");
   }
   else if(sellConf >= InpConfidence && sellConf > buyConf)
   {
      int sl = isMeanRevSell ? InpRevSL : InpTrendSL;
      int tp = isMeanRevSell ? InpRevTP : InpTrendTP;
      OpenSell(sl, tp, isMeanRevSell ? "mean-rev" : "trend");
   }
}

//+------------------------------------------------------------------+
// Posts a JSON payload to the dashboard. Requires the URL to be
// whitelisted in MT5 → Tools → Options → Expert Advisors → Allow WebRequests.
void PostToDashboard(string json)
{
   if(StringLen(InpDashboardUrl) < 8) return;
   char   post[], result[];
   string headers = "Content-Type: application/json\r\n";
   string resultHeaders;
   int    len = StringToCharArray(json, post) - 1;  // strip null terminator
   ArrayResize(post, len);
   PrintFormat("Dashboard POST attempt: %s", InpDashboardUrl);
   int res = WebRequest("POST", InpDashboardUrl, headers, 5000, post, result, resultHeaders);
   PrintFormat("Dashboard POST result: http=%d err=%d body=%s", res, GetLastError(), CharArrayToString(result));
}

//+------------------------------------------------------------------+
// Returns the minimum stop distance in points, with a small buffer.
int MinStopPoints()
{
   int stopLevel = (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   return stopLevel + 10;  // 10-point buffer above the minimum
}

//+------------------------------------------------------------------+
void OpenBuy(int slPoints, int tpPoints, string reason)
{
   double ask  = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double pt   = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   int    minSL = MinStopPoints();
   slPoints = MathMax(slPoints, minSL);
   tpPoints = MathMax(tpPoints, minSL);
   double sl   = ask - slPoints * pt;
   double tp   = ask + tpPoints * pt;
   double lots = NormaliseLots(InpLotSize);

   if(trade.Buy(lots, _Symbol, ask, sl, tp,
                StringFormat("DeerFlow BUY %s", reason)))
   {
      PrintFormat("BUY %s opened | lots=%.2f ask=%.5f SL=%.5f TP=%.5f", reason, lots, ask, sl, tp);
      PostToDashboard(StringFormat(
         "{\"type\":\"open\",\"direction\":\"BUY\",\"symbol\":\"%s\",\"lots\":%.2f,"
         "\"price\":%.5f,\"sl\":%.5f,\"tp\":%.5f,\"reason\":\"%s\",\"time\":\"%s\"}",
         _Symbol, lots, ask, sl, tp, reason,
         TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES|TIME_SECONDS)));
   }
   else
      PrintFormat("BUY failed: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
void OpenSell(int slPoints, int tpPoints, string reason)
{
   double bid  = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double pt   = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   int    minSL = MinStopPoints();
   slPoints = MathMax(slPoints, minSL);
   tpPoints = MathMax(tpPoints, minSL);
   double sl   = bid + slPoints * pt;
   double tp   = bid - tpPoints * pt;
   double lots = NormaliseLots(InpLotSize);

   if(trade.Sell(lots, _Symbol, bid, sl, tp,
                 StringFormat("DeerFlow SELL %s", reason)))
   {
      PrintFormat("SELL %s opened | lots=%.2f bid=%.5f SL=%.5f TP=%.5f", reason, lots, bid, sl, tp);
      PostToDashboard(StringFormat(
         "{\"type\":\"open\",\"direction\":\"SELL\",\"symbol\":\"%s\",\"lots\":%.2f,"
         "\"price\":%.5f,\"sl\":%.5f,\"tp\":%.5f,\"reason\":\"%s\",\"time\":\"%s\"}",
         _Symbol, lots, bid, sl, tp, reason,
         TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES|TIME_SECONDS)));
   }
   else
      PrintFormat("SELL failed: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
// Fires when a deal is added to history — catches trade closes.
void OnTradeTransaction(const MqlTradeTransaction& trans,
                        const MqlTradeRequest&     request,
                        const MqlTradeResult&      result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(trans.deal))           return;

   long magic = HistoryDealGetInteger(trans.deal, DEAL_MAGIC);
   if(magic != InpMagicNumber) return;

   long entry = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
   if(entry != DEAL_ENTRY_OUT) return;

   string sym    = HistoryDealGetString(trans.deal,  DEAL_SYMBOL);
   double profit = HistoryDealGetDouble(trans.deal,  DEAL_PROFIT);
   double vol    = HistoryDealGetDouble(trans.deal,  DEAL_VOLUME);
   double price  = HistoryDealGetDouble(trans.deal,  DEAL_PRICE);

   PostToDashboard(StringFormat(
      "{\"type\":\"close\",\"symbol\":\"%s\",\"profit\":%.2f,\"lots\":%.2f,"
      "\"price\":%.5f,\"time\":\"%s\"}",
      sym, profit, vol, price,
      TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES|TIME_SECONDS)));
}

//+------------------------------------------------------------------+
double NormaliseLots(double lots)
{
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   lots = MathMax(minLot, MathMin(maxLot, lots));
   return MathRound(lots / lotStep) * lotStep;
}

//+------------------------------------------------------------------+
int CountMyPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(PositionGetSymbol(i) == _Symbol &&
         (long)PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
         count++;
   return count;
}
