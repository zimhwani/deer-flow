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
#property version   "1.01"
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
input double InpLotSize        = 0.30;  // Fallback lot size (used if dynamic sizing fails)
input double InpMaxRiskPct     = 2.0;   // Max risk % of balance per trade

input group "Exit Levels — ATR-based (both paths)"
input double InpTrendSLAtrMult = 1.5;  // ATR multiplier for trend stop loss
input double InpTrendTPRatio   = 2.0;  // TP = SL * this ratio for trend trades
input double InpRevSLAtrMult   = 2.5;  // ATR multiplier for mean-rev stop loss
input double InpRevTPRatio     = 2.0;  // TP = SL * this ratio for mean-rev trades

input group "Risk Management"
input int    InpMaxPositions   = 2;     // Max open positions at once (reduced for correlation control)
input int    InpMaxPerDirection = 1;    // Max positions per direction class (CRASH or BOOM)
input bool   InpUseDailyLoss   = true;  // Enable daily loss limit
input double InpDailyLossPct   = 6.0;  // Daily loss limit % of balance (tightened from 10%)
input bool   InpUseDailyTarget = false; // Enable daily profit target
input double InpDailyTargetPct = 999.0; // Daily profit target %
input double InpSpikeAtrMult   = 3.0;  // Candle range > this * ATR14 = spike, skip mean-rev

input group "Dashboard Bridge"
input string InpDashboardUrl   = "http://209.38.87.199/api/mt5/trade"; // Dashboard URL (empty to disable)

input group "EA Settings"
input int    InpMagicNumber    = 20260528; // Magic number (unique ID)
input bool   InpTradeOnNewBar  = true;  // Only trade on new M1 bar open

//── Globals ─────────────────────────────────────────────────────────
CTrade  trade;
double  g_dailyStartBalance = 0;
datetime g_currentDay       = 0;
int     g_hEmaFast, g_hEmaSlow, g_hEmaMacro, g_hRsi, g_hBB, g_hAtr;

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
   g_hAtr     = iATR(_Symbol, PERIOD_M1, 14);

   if(g_hEmaFast == INVALID_HANDLE || g_hEmaSlow == INVALID_HANDLE ||
      g_hEmaMacro == INVALID_HANDLE || g_hRsi == INVALID_HANDLE ||
      g_hBB == INVALID_HANDLE || g_hAtr == INVALID_HANDLE)
   {
      Print("ERROR: Failed to create indicator handles");
      return INIT_FAILED;
   }

   g_dailyStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   g_currentDay        = iTime(_Symbol, PERIOD_D1, 0);

   Print("DeerFlow EA v1.01 started | Symbol: ", _Symbol,
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
   IndicatorRelease(g_hAtr);
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

   // Max total positions guard
   if(CountMyPositions() >= InpMaxPositions) return;

   // ── Read indicators ──────────────────────────────────────────────
   double ema10[3], ema20[6], ema50[1], rsi[4], bbUp[1], bbLow[1], atrBuf[2];

   if(CopyBuffer(g_hEmaFast,  0, 0, 3, ema10)  < 3) return;
   if(CopyBuffer(g_hEmaSlow,  0, 0, 6, ema20)  < 6) return;
   if(CopyBuffer(g_hEmaMacro, 0, 0, 1, ema50)  < 1) return;
   if(CopyBuffer(g_hRsi,      0, 0, 4, rsi)    < 4) return;
   if(CopyBuffer(g_hBB, UPPER_BAND, 0, 1, bbUp)  < 1) return;
   if(CopyBuffer(g_hBB, LOWER_BAND, 0, 1, bbLow) < 1) return;
   if(CopyBuffer(g_hAtr,      0, 0, 2, atrBuf) < 2) return;

   ArraySetAsSeries(ema10,   true);
   ArraySetAsSeries(ema20,   true);
   ArraySetAsSeries(ema50,   true);
   ArraySetAsSeries(rsi,     true);
   ArraySetAsSeries(bbUp,    true);
   ArraySetAsSeries(bbLow,   true);
   ArraySetAsSeries(atrBuf,  true);

   double price       = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double emaFast     = ema10[0];
   double emaSlow     = ema20[0];
   double emaMacro    = ema50[0];
   double rsiNow      = rsi[0];
   double rsiPrev     = rsi[1];
   double rsi3Ago     = rsi[3];   // 3-candle lookback for direction confirmation
   double bbUpper     = bbUp[0];
   double bbLower     = bbLow[0];
   double atrNow      = atrBuf[0];
   double pt          = SymbolInfoDouble(_Symbol, SYMBOL_POINT);

   // ── Spike filter — skip mean-reversion on spike candles ─────────
   double lastCandleHigh  = iHigh(_Symbol, PERIOD_M1, 1);
   double lastCandleLow   = iLow (_Symbol, PERIOD_M1, 1);
   double lastCandleRange = lastCandleHigh - lastCandleLow;
   bool   isSpike         = (atrNow > 0 && lastCandleRange > InpSpikeAtrMult * atrNow);

   // ── Derived conditions ───────────────────────────────────────────
   bool trendUp   = ema20[0] > ema20[4];
   bool trendDown = ema20[0] < ema20[4];
   // Require RSI to have moved ≥2 pts over 3 candles to count as genuine reversal
   bool rsiRising  = (rsiNow - rsi3Ago) >= 2.0;
   bool rsiFalling = (rsi3Ago - rsiNow) >= 2.0;
   bool macroBull  = price > emaMacro;
   bool macroBear  = price < emaMacro;

   double emaSpreadPct = MathAbs(emaFast - emaSlow) / emaSlow * 100.0;
   bool   emaSpreadOk  = emaSpreadPct >= 0.05;  // raised from 0.02 — require meaningful crossover

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

   // ── Correlation cap — count CRASH vs BOOM exposure separately ───
   int crashCount = 0, boomCount = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      string sym = PositionGetSymbol(i);
      if((long)PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;
      if(StringFind(sym, "CRASH") >= 0) crashCount++;
      if(StringFind(sym, "BOOM")  >= 0) boomCount++;
   }
   bool isCrashSymbol = StringFind(_Symbol, "CRASH") >= 0;
   bool isBoomSymbol  = StringFind(_Symbol, "BOOM")  >= 0;
   if(isCrashSymbol && crashCount >= InpMaxPerDirection) return;
   if(isBoomSymbol  && boomCount  >= InpMaxPerDirection) return;

   // ── Signal scoring ───────────────────────────────────────────────
   double buyConf  = 0.0;
   double sellConf = 0.0;
   bool   isMeanRevBuy  = false;
   bool   isMeanRevSell = false;

   // Path 1 — Mean-reversion BUY
   // Base 0.45 requires macro confirmation (+0.20) to cross the 0.60 threshold.
   // Prevents fading into a strong macro downtrend.
   if(!isSpike && price < bbLower && rsiNow < 30.0 && rsiRising)
   {
      buyConf += 0.45;
      isMeanRevBuy = true;
      if(macroBull) buyConf += 0.20;  // macro aligned: don't buy into downtrend
   }
   // Path 2 — Trend BUY
   else if(macroBull && rsiNow > 28.0 && rsiNow < 72.0)
   {
      if(emaFast > emaSlow && emaSpreadOk)                          buyConf += 0.30;
      if(trendUp)                                                    buyConf += 0.15;
      if(rsiNow > 35.0 && rsiNow < 60.0 && rsiRising)              buyConf += 0.15;
      if(consecBull)                                                 buyConf += 0.15;
   }

   // Path 1 — Mean-reversion SELL
   // Base 0.45 requires macro confirmation (+0.20) to cross the 0.60 threshold.
   if(!isSpike && price > bbUpper && rsiNow > 70.0 && rsiFalling)
   {
      sellConf += 0.45;
      isMeanRevSell = true;
      if(macroBear) sellConf += 0.20;  // macro aligned: don't sell into uptrend
   }
   // Path 2 — Trend SELL
   else if(macroBear && rsiNow > 45.0 && rsiNow < 65.0)
   {
      if(emaFast < emaSlow && emaSpreadOk)                           sellConf += 0.30;
      if(trendDown)                                                   sellConf += 0.15;
      if(rsiNow > 40.0 && rsiNow < 65.0 && rsiFalling)              sellConf += 0.15;
      if(consecBear)                                                  sellConf += 0.15;
   }

   // ── Execute ──────────────────────────────────────────────────────
   if(buyConf >= InpConfidence && buyConf > sellConf)
   {
      double slPts, tpPts;
      if(isMeanRevBuy)
      {
         // ATR-based SL/TP for mean-reversion — adapts to current volatility
         slPts = MathMax(InpRevSLAtrMult * atrNow / pt, (double)MinStopPoints());
         tpPts = slPts * InpRevTPRatio;
      }
      else
      {
         slPts = MathMax(InpTrendSLAtrMult * atrNow / pt, (double)MinStopPoints());
         tpPts = slPts * InpTrendTPRatio;
      }
      OpenBuy(slPts, tpPts, isMeanRevBuy ? "mean-rev" : "trend");
   }
   else if(sellConf >= InpConfidence && sellConf > buyConf)
   {
      double slPts, tpPts;
      if(isMeanRevSell)
      {
         slPts = MathMax(InpRevSLAtrMult * atrNow / pt, (double)MinStopPoints());
         tpPts = slPts * InpRevTPRatio;
      }
      else
      {
         slPts = MathMax(InpTrendSLAtrMult * atrNow / pt, (double)MinStopPoints());
         tpPts = slPts * InpTrendTPRatio;
      }
      OpenSell(slPts, tpPts, isMeanRevSell ? "mean-rev" : "trend");
   }
}

//+------------------------------------------------------------------+
void PostToDashboard(string json)
{
   if(StringLen(InpDashboardUrl) < 8) return;
   char   post[], result[];
   string headers = "Content-Type: application/json\r\n";
   string resultHeaders;
   int    len = StringToCharArray(json, post) - 1;
   ArrayResize(post, len);
   PrintFormat("Dashboard POST attempt: %s", InpDashboardUrl);
   int res = WebRequest("POST", InpDashboardUrl, headers, 5000, post, result, resultHeaders);
   PrintFormat("Dashboard POST result: http=%d err=%d body=%s", res, GetLastError(), CharArrayToString(result));
}

//+------------------------------------------------------------------+
int MinStopPoints()
{
   int    stopLevel = (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double price     = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double pt        = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   // Deriv returns 0 or a tiny stop level for synthetic indices.
   // Use the larger of: 5x reported level, or 0.5% of current price.
   // 0.5% scales automatically across V25 (~2764), V50 (~92), V75 (~28400), V100 (~383).
   int pricePct = (pt > 0) ? (int)(price * 0.005 / pt) : 0;
   return MathMax(stopLevel * 5 + 100, pricePct);
}

//+------------------------------------------------------------------+
// Calculates lot size based on account risk % and SL distance.
// Falls back to InpLotSize if calculation produces invalid result.
double CalcLots(double slPoints)
{
   double balance   = AccountInfoDouble(ACCOUNT_BALANCE);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double pt        = SymbolInfoDouble(_Symbol, SYMBOL_POINT);

   if(tickValue <= 0 || tickSize <= 0 || slPoints <= 0)
      return NormaliseLots(InpLotSize);

   double riskAmount  = balance * InpMaxRiskPct / 100.0;
   double slInTicks   = slPoints * pt / tickSize;
   double lotSize     = riskAmount / (slInTicks * tickValue);

   lotSize = NormaliseLots(lotSize);

   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(lotSize < minLot || lotSize > maxLot)
      return NormaliseLots(InpLotSize);

   return lotSize;
}

//+------------------------------------------------------------------+
void OpenBuy(double slPoints, double tpPoints, string reason)
{
   double ask   = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double pt    = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   int    minSL = MinStopPoints();
   slPoints = MathMax(slPoints, (double)minSL);
   tpPoints = MathMax(tpPoints, (double)minSL);
   double sl   = ask - slPoints * pt;
   double tp   = ask + tpPoints * pt;
   double lots = CalcLots(slPoints);

   if(trade.Buy(lots, _Symbol, ask, sl, tp,
                StringFormat("DeerFlow BUY %s", reason)))
   {
      PrintFormat("BUY %s opened | lots=%.2f ask=%.5f SL=%.5f TP=%.5f sl_pts=%.0f",
                  reason, lots, ask, sl, tp, slPoints);
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
void OpenSell(double slPoints, double tpPoints, string reason)
{
   double bid  = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double pt   = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   int    minSL = MinStopPoints();
   slPoints = MathMax(slPoints, (double)minSL);
   tpPoints = MathMax(tpPoints, (double)minSL);
   double sl   = bid + slPoints * pt;
   double tp   = bid - tpPoints * pt;
   double lots = CalcLots(slPoints);

   if(trade.Sell(lots, _Symbol, bid, sl, tp,
                 StringFormat("DeerFlow SELL %s", reason)))
   {
      PrintFormat("SELL %s opened | lots=%.2f bid=%.5f SL=%.5f TP=%.5f sl_pts=%.0f",
                  reason, lots, bid, sl, tp, slPoints);
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
