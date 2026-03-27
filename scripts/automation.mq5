//+------------------------------------------------------------------+
//|                                                TradingClient.mq5 |
//|                                    Elastic DCA Trading Client v4 |
//|                           Execution Bridge for Elastic DCA Engine|
//+------------------------------------------------------------------+
#property copyright "Elastic DCA System"
#property link "https://github.com/kumawat-aditya/elastic-dca-trader"
#property version "4.0.0"
#property strict

//--- Input Parameters ---
// input string InpServerURL   = "http://127.0.0.1:8000"; for dev
input string InpServerURL = "http://YOUR_SERVER_IP:8000"; // Server Base URL
input int InpTimeout = 5000;                              // Request timeout (ms)
input int InpMagicNumber = 789456;                        // Magic number for trades
input int InpSlippage = 10;                               // Slippage in points
input bool InpDebugMode = true;                           // Enable debug logging

//--- Global Variables ---
string g_BrokerName = "";
string g_AccountID = "";
string g_Symbol = "";
int g_Digits = 0;
datetime g_LastTickTime = 0;
int g_ConsecutiveErrors = 0;
bool g_ServerReachable = true;

// Indicator Handles for Trend
int g_HandleH1 = INVALID_HANDLE;
int g_HandleH4 = INVALID_HANDLE;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   // Initialize broker and account info
   g_BrokerName = AccountInfoString(ACCOUNT_COMPANY);
   g_AccountID = IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
   g_Symbol = _Symbol;
   g_Digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   // Initialize Trend Indicators (20 SMA)
   g_HandleH1 = iMA(g_Symbol, PERIOD_H1, 20, 0, MODE_SMA, PRICE_CLOSE);
   g_HandleH4 = iMA(g_Symbol, PERIOD_H4, 20, 0, MODE_SMA, PRICE_CLOSE);

   // Set timer for 1-second polling (Heartbeat)
   EventSetTimer(1);

   Print("==================================================");
   Print("Elastic DCA Client v4.0.0 Initialized");
   Print("Status: Waiting for Server Command...");
   Print("==================================================");
   Print("Broker: ", g_BrokerName);
   Print("Account: ", g_AccountID);
   Print("Symbol: ", g_Symbol);
   Print("Engine: ", InpServerURL);
   Print("==================================================");
   Print("IMPORTANT: Ensure server URL is whitelisted in:");
   Print("Tools -> Options -> Expert Advisors -> Allow WebRequest");
   Print("==================================================");

   return (INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   
   if(g_HandleH1 != INVALID_HANDLE) IndicatorRelease(g_HandleH1);
   if(g_HandleH4 != INVALID_HANDLE) IndicatorRelease(g_HandleH4);

   Print("==================================================");
   Print("Elastic DCA Client Stopped. Reason: ", reason);
   Print("==================================================");
}

//+------------------------------------------------------------------+
//| Timer function - Polls server every second                       |
//+------------------------------------------------------------------+
void OnTimer()
{
   // Prevent excessive polling within the same second
   datetime currentTime = TimeCurrent();
   if (currentTime == g_LastTickTime)
      return;

   g_LastTickTime = currentTime;

   // Build and send tick data
   string jsonPayload = BuildTickPayload();

   if (jsonPayload == "")
   {
      Print("[ERROR] Failed to build payload");
      return;
   }

   // Send to server
   SendTickToServer(jsonPayload);
}

//+------------------------------------------------------------------+
//| Calculate Trend helper                                           |
//+------------------------------------------------------------------+
string GetTrend(int handle, ENUM_TIMEFRAMES tf)
{
   if(handle == INVALID_HANDLE) return "neutral";
   
   double ma[1];
   double close[1];
   
   if(CopyBuffer(handle, 0, 0, 1, ma) <= 0) return "neutral";
   if(CopyClose(g_Symbol, tf, 0, 1, close) <= 0) return "neutral";
   
   if(close[0] > ma[0]) return "up";
   if(close[0] < ma[0]) return "down";
   return "neutral";
}

//+------------------------------------------------------------------+
//| Build JSON payload with account and position data                |
//+------------------------------------------------------------------+
string BuildTickPayload()
{
   // Gather account data
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double ask = SymbolInfoDouble(g_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(g_Symbol, SYMBOL_BID);

   // Validate prices
   if (ask <= 0 || bid <= 0)
   {
      Print("[WARN] Invalid prices - Ask: ", ask, ", Bid: ", bid);
      return "";
   }

   // Start JSON construction
   string json = "{";
   json += "\"account_id\":\"" + g_AccountID + "\",";
   json += "\"equity\":" + DoubleToString(equity, 2) + ",";
   json += "\"balance\":" + DoubleToString(balance, 2) + ",";
   json += "\"symbol\":\"" + g_Symbol + "\",";
   json += "\"ask\":" + DoubleToString(ask, g_Digits) + ",";
   json += "\"bid\":" + DoubleToString(bid, g_Digits) + ",";
   json += "\"trend_h1\":\"" + GetTrend(g_HandleH1, PERIOD_H1) + "\",";
   json += "\"trend_h4\":\"" + GetTrend(g_HandleH4, PERIOD_H4) + "\",";
   json += "\"positions\":[";

   // Add all open positions
   int total = PositionsTotal();
   int added = 0;

   for (int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if (ticket > 0 && PositionSelectByTicket(ticket))
      {
         string symbol = PositionGetString(POSITION_SYMBOL);

         // Include all positions (server will filter by comment hash)
         if (added > 0)
            json += ",";

         json += "{";
         json += "\"ticket\":" + IntegerToString(ticket) + ",";
         json += "\"symbol\":\"" + symbol + "\",";

         ENUM_POSITION_TYPE posType = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
         json += "\"type\":\"" + (posType == POSITION_TYPE_BUY ? "BUY" : "SELL") + "\",";

         json += "\"volume\":" + DoubleToString(PositionGetDouble(POSITION_VOLUME), 2) + ",";
         json += "\"price\":" + DoubleToString(PositionGetDouble(POSITION_PRICE_OPEN), g_Digits) + ",";
         json += "\"profit\":" + DoubleToString(PositionGetDouble(POSITION_PROFIT), 2) + ",";
         json += "\"comment\":\"" + PositionGetString(POSITION_COMMENT) + "\"";
         json += "}";

         added++;
      }
   }

   json += "]}";

   if (InpDebugMode && added > 0)
   {
      Print("[INFO] Sending ", added, " positions to server");
   }

   return json;
}

//+------------------------------------------------------------------+
//| Send tick data to server and process response                    |
//+------------------------------------------------------------------+
void SendTickToServer(string jsonPayload)
{
   char data[];
   char result[];
   string headers = "Content-Type: application/json\r\n";
   string resultHeaders;

   // Proper conversion to UTF8 array
   int len = StringToCharArray(jsonPayload, data, 0, WHOLE_ARRAY, CP_UTF8);

   // Remove null terminator
   if (len > 0)
      ArrayResize(data, len - 1);

   // Send POST request
   ResetLastError();
   // Endpoint updated to V4 structure
   string url = InpServerURL + "/api/v1/ea/tick";
   int statusCode = WebRequest("POST", url, headers, InpTimeout, data, result, resultHeaders);

   // Handle response
   if (statusCode == 200)
   {
      g_ConsecutiveErrors = 0;
      g_ServerReachable = true;

      string response = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
      ProcessBulkServerResponse(response);
   }
   else if (statusCode != 204)
   {
      g_ConsecutiveErrors++;
      if(g_ConsecutiveErrors % 20 == 1) Print("[SERVER ERROR] Status: ", statusCode, " Err: ", GetLastError());
   }
}

//+------------------------------------------------------------------+
//| Bulk Actions Parser (Loops through multiple actions concurrently)|
//+------------------------------------------------------------------+
void ProcessBulkServerResponse(string response)
{
   if (response == "") 
      return;

   // Locate the actions array
   int arrayStart = StringFind(response, "[");
   int arrayEnd = StringFind(response, "]", arrayStart);
   
   if (arrayStart == -1 || arrayEnd == -1) return;

   string arrayStr = StringSubstr(response, arrayStart + 1, arrayEnd - arrayStart - 1);
   int objStart = 0;

   // Loop through all JSON objects inside the array
   while(true)
   {
      objStart = StringFind(arrayStr, "{", objStart);
      if (objStart == -1) break;
      
      int objEnd = StringFind(arrayStr, "}", objStart);
      if (objEnd == -1) break;

      string objStr = StringSubstr(arrayStr, objStart, objEnd - objStart + 1);
      ProcessSingleActionObject(objStr);

      objStart = objEnd + 1;
   }
}

//+------------------------------------------------------------------+
//| Action Router (Executes the parsed JSON object command)          |
//+------------------------------------------------------------------+
void ProcessSingleActionObject(string obj)
{
   string action = ExtractJsonValue(obj, "action");

   if (action == "" || action == "WAIT")
      return; // No action needed

   if (InpDebugMode) 
      Print("[SERVER ACTION] ", action, " | Payload: ", obj);

   // 1. CLOSE_ALL (Cycle Cleanup or Zombie Cleanup)
   if (action == "CLOSE_ALL")
   {
      string comment = ExtractJsonValue(obj, "comment");
      if (comment != "") 
      Print("[ACTION] Closing positions with ID: ", comment);
      ClosePositionsByComment(comment);
      return;
   }

   // 2. GRID BUY / SELL (No SL/TP)
   if (action == "BUY" || action == "SELL")
   {
      double volume = StringToDouble(ExtractJsonValue(obj, "volume"));
      string comment = ExtractJsonValue(obj, "comment");

      if (volume > 0 && comment != "")
      {
         if (action == "BUY") 
            ExecuteOrder(ORDER_TYPE_BUY, volume, comment, 0.0, 0.0);
         else 
            ExecuteOrder(ORDER_TYPE_SELL, volume, comment, 0.0, 0.0);
      }
      return;
   }

   // 3. HEDGE (Requires exact SL and TP from server)
   if (action == "HEDGE")
   {
      string typeStr = ExtractJsonValue(obj, "type");
      double volume = StringToDouble(ExtractJsonValue(obj, "volume"));
      double tp = StringToDouble(ExtractJsonValue(obj, "tp"));
      double sl = StringToDouble(ExtractJsonValue(obj, "sl"));
      string comment = ExtractJsonValue(obj, "comment");

      if (volume > 0 && comment != "" && tp > 0 && sl > 0)
      {
         ENUM_ORDER_TYPE orderType = (typeStr == "BUY") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
         ExecuteOrder(orderType, volume, comment, sl, tp);
      }
      return;
   }

   Print("[WARN] Unknown action: ", action);
}

//+------------------------------------------------------------------+
//| Unified Execution Function for BUY, SELL, and HEDGE              |
//+------------------------------------------------------------------+
void ExecuteOrder(ENUM_ORDER_TYPE type, double lots, string comment, double sl, double tp)
{
   double price = (type == ORDER_TYPE_BUY) ? SymbolInfoDouble(g_Symbol, SYMBOL_ASK) : SymbolInfoDouble(g_Symbol, SYMBOL_BID);

   if (price <= 0)
   {
      Print("[ERROR] Invalid Market Price");
      return;
   }

   // Normalize volume
   double minLot = SymbolInfoDouble(g_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(g_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(g_Symbol, SYMBOL_VOLUME_STEP);

   lots = MathMax(lots, minLot);
   lots = MathMin(lots, maxLot);
   lots = NormalizeDouble(lots / lotStep, 0) * lotStep;

   // Prepare request
   MqlTradeRequest request;
   MqlTradeResult result;
   ZeroMemory(request);
   ZeroMemory(result);

   request.action = TRADE_ACTION_DEAL;
   request.symbol = g_Symbol;
   request.volume = lots;
   request.type = type;
   request.price = price;
   
   // Apply Hard SL/TP if provided (for Hedging)
   request.sl = (sl > 0) ? NormalizeDouble(sl, g_Digits) : 0;
   request.tp = (tp > 0) ? NormalizeDouble(tp, g_Digits) : 0;
   
   request.deviation = InpSlippage;
   request.magic = InpMagicNumber;
   request.comment = comment;
   request.type_filling = GetOrderFillingType();

   // Send order
   ResetLastError();
   bool sent = OrderSend(request, result);

   string typeStr = (type == ORDER_TYPE_BUY) ? "BUY" : "SELL";

   if (sent && result.retcode == TRADE_RETCODE_DONE)
   {
      Print("[EXECUTE] ", typeStr, " OK - Ticket: ", result.order, " | Vol: ", lots, " | Price: ", result.price, " | Comment: ", comment);
   }
   else
   {
      Print("[ERROR] ", typeStr, " FAILED - Retcode: ", result.retcode, " | Err: ", GetLastError(), " | Comment: ", comment);
   }
}

//+------------------------------------------------------------------+
//| Close positions by filter substring (Cleanup)                    |
//+------------------------------------------------------------------+
void ClosePositionsByComment(string commentFilter)
{
   int total = PositionsTotal();
   int closed = 0;
   int matched = 0;

   // Loop backwards to safely delete items from the pool
   for (int i = total - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if (ticket > 0 && PositionSelectByTicket(ticket))
      {
         string comment = PositionGetString(POSITION_COMMENT);

         // Check if comment contains filter string
         if (StringFind(comment, commentFilter) != -1)
         {
            matched++;
            if (ClosePosition(ticket)) closed++;
         }
      }
   }
   if (InpDebugMode && matched > 0) Print("[CLOSE] Matched '", commentFilter, "': ", matched, " | Closed: ", closed);
}

//+------------------------------------------------------------------+
//| Close single position by ticket                                  |
//+------------------------------------------------------------------+
bool ClosePosition(ulong ticket)
{
   if (!PositionSelectByTicket(ticket)) return false;

   string symbol = PositionGetString(POSITION_SYMBOL);
   double volume = PositionGetDouble(POSITION_VOLUME);
   ENUM_POSITION_TYPE posType = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
   ENUM_ORDER_TYPE orderType = (posType == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;

   MqlTradeRequest request;
   MqlTradeResult result;
   ZeroMemory(request);
   ZeroMemory(result);

   request.action = TRADE_ACTION_DEAL;
   request.symbol = symbol;
   request.volume = volume;
   request.type = orderType;
   request.position = ticket;
   request.deviation = InpSlippage;
   request.magic = InpMagicNumber;
   request.type_filling = GetOrderFillingType();

   ResetLastError();
   bool sent = OrderSend(request, result);

   if (sent && result.retcode == TRADE_RETCODE_DONE) return true;
   
   Print("[ERROR] Failed to close ticket ", ticket, " - Retcode: ", result.retcode, " | Err: ", GetLastError());
   return false;
}

//+------------------------------------------------------------------+
//| Simple JSON String Extractor                                     |
//+------------------------------------------------------------------+
string ExtractJsonValue(string json, string key)
{
   string search = "\"" + key + "\"";
   int pos = StringFind(json, search);
   if (pos == -1) return "";

   pos = StringFind(json, ":", pos);
   if (pos == -1) return "";
   pos++;

   while (pos < StringLen(json))
   {
      ushort c = StringGetCharacter(json, pos);
      if (c != ' ' && c != '\t' && c != '\n' && c != '\r') break;
      pos++;
   }

   bool isString = false;
   if (StringGetCharacter(json, pos) == '"')
   {
      isString = true;
      pos++; 
   }

   int endPos = pos;
   if (isString)
   {
      while (endPos < StringLen(json))
      {
         if (StringGetCharacter(json, endPos) == '"') break;
         endPos++;
      }
   }
   else
   {
      while (endPos < StringLen(json))
      {
         ushort c = StringGetCharacter(json, endPos);
         if (c == ',' || c == '}' || c == ']' || c == ' ') break;
         endPos++;
      }
   }

   return StringSubstr(json, pos, endPos - pos);
}

//+------------------------------------------------------------------+
//| Get appropriate order filling type for broker                    |
//+------------------------------------------------------------------+
ENUM_ORDER_TYPE_FILLING GetOrderFillingType()
{
   // Specific logic for Prop Firms / ECN Brokers
   if (StringFind(g_BrokerName, "XM") != -1 ||
       StringFind(g_BrokerName, "Raw Trading") != -1 ||
       StringFind(g_BrokerName, "Royal ETP") != -1 ||
       StringFind(g_BrokerName, "International Capital Markets") != -1 ||
       StringFind(g_BrokerName, "Atlas Funded") != -1)
   {
      return ORDER_FILLING_IOC;
   }

   // Fallback to Symbol settings
   int fillingMode = (int)SymbolInfoInteger(g_Symbol, SYMBOL_FILLING_MODE);

   if ((fillingMode & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK)
      return ORDER_FILLING_FOK;
   if ((fillingMode & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC)
      return ORDER_FILLING_IOC;

   return ORDER_FILLING_RETURN;
}
//+------------------------------------------------------------------+