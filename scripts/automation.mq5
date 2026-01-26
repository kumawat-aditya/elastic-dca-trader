//+------------------------------------------------------------------+
//|                                                TradingClient.mq5 |
//|                                    Elastic DCA Trading Client v3 |
//|                           Execution Bridge for Elastic DCA Engine|
//+------------------------------------------------------------------+
#property copyright "Elastic DCA System"
#property link      "https://github.com/Adikumaw/elastic-dca-trader"
#property version   "3.4.2"
#property strict

//--- Input Parameters ---
//input string InpServerURL   = "http://127.0.0.1:8000"; for dev
input string InpServerURL = "http://YOUR_SERVER_IP:8000";  // Server URL
input int    InpTimeout     = 5000;                    // Request timeout (ms)
input int    InpMagicNumber = 789456;                  // Magic number for trades
input int    InpSlippage    = 10;                      // Slippage in points
input bool   InpDebugMode   = true;                    // Enable debug logging

//--- Global Variables ---
string g_BrokerName = "";
string g_AccountID = "";
string g_Symbol = "";
int g_Digits = 0;
datetime g_LastTickTime = 0;
int g_ConsecutiveErrors = 0;
bool g_ServerReachable = true;

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
   
   // Set timer for 1-second polling (Heartbeat)
   EventSetTimer(1);
   
   Print("==================================================");
   Print("Elastic DCA Client v3.4.2 Initialized");
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
   
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   
   string reasonText = "";
   switch(reason)
   {
      case REASON_PROGRAM: reasonText = "Program terminated"; break;
      case REASON_REMOVE: reasonText = "EA removed from chart"; break;
      case REASON_RECOMPILE: reasonText = "EA recompiled"; break;
      case REASON_CHARTCHANGE: reasonText = "Chart changed"; break;
      case REASON_CHARTCLOSE: reasonText = "Chart closed"; break;
      case REASON_PARAMETERS: reasonText = "Parameters changed"; break;
      case REASON_ACCOUNT: reasonText = "Account changed"; break;
      default: reasonText = "Unknown reason";
   }
   
   Print("==================================================");
   Print("Elastic DCA Client Stopped: ", reasonText);
   Print("==================================================");
}

//+------------------------------------------------------------------+
//| Timer function - Polls server every second                       |
//+------------------------------------------------------------------+
void OnTimer()
{
   // Prevent excessive polling within the same second
   datetime currentTime = TimeCurrent();
   if(currentTime == g_LastTickTime)
      return;
   
   g_LastTickTime = currentTime;
   
   // Build and send tick data
   string jsonPayload = BuildTickPayload();
   
   if(jsonPayload == "")
   {
      Print("[ERROR] Failed to build payload");
      return;
   }
   
   // Send to server
   SendTickToServer(jsonPayload);
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
   if(ask <= 0 || bid <= 0)
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
   json += "\"positions\":[";
   
   // Add all open positions
   int total = PositionsTotal();
   int added = 0;
   
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && PositionSelectByTicket(ticket))
      {
         string symbol = PositionGetString(POSITION_SYMBOL);
         
         // Include all positions (server will filter by comment hash)
         if(added > 0) json += ",";
         
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
   
   if(InpDebugMode && added > 0)
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
   if(len > 0)
      ArrayResize(data, len - 1);
   
   // Send POST request
   ResetLastError();
   string url = InpServerURL + "/api/tick";
   int statusCode = WebRequest("POST", url, headers, InpTimeout, data, result, resultHeaders);
   
   // Handle response
   if(statusCode == 200)
   {
      g_ConsecutiveErrors = 0;
      g_ServerReachable = true;
      
      string response = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
      ProcessServerResponse(response);
   }
   else if(statusCode == 204)
   {
      // No content - heartbeat OK (Waiting state)
      g_ConsecutiveErrors = 0;
      g_ServerReachable = true;
   }
   else if(statusCode == -1)
   {
      // Request failed
      int error = GetLastError();
      g_ConsecutiveErrors++;
      
      if(error == 4060)
      {
         Print("[ERROR] WebRequest not allowed! Add server URL to allowed list:");
         Print("  Tools -> Options -> Expert Advisors -> Allow WebRequest for:");
         Print("  ", InpServerURL);
         g_ServerReachable = false;
      }
      else
      {
         // Only log sporadic errors to avoid spamming journal
         if(g_ConsecutiveErrors % 20 == 1) 
         {
            Print("[CONN] Connection failed. Code: ", error, " (", g_ConsecutiveErrors, " retries)");
         }
      }
   }
   else
   {
      // Server error (500, 404, etc)
      g_ConsecutiveErrors++;
      if(g_ConsecutiveErrors % 10 == 1)
      {
         Print("[SERVER ERROR] Status: ", statusCode);
      }
   }
}

//+------------------------------------------------------------------+
//| Process server response and execute actions                      |
//+------------------------------------------------------------------+
void ProcessServerResponse(string response)
{
   if(response == "")
      return;
   
   // Parse action
   string action = ExtractJsonValue(response, "action");
   
   if(action == "" || action == "WAIT")
      return; // No action needed
   
   if(InpDebugMode)
   {
      Print("[SERVER] Action: ", action);
   }
   
   // Handle CLOSE_ALL (Snap-Back or Panic)
   if(action == "CLOSE_ALL")
   {
      string comment = ExtractJsonValue(response, "comment");
      
      if(comment == "")
      {
         Print("[WARN] CLOSE_ALL received but no comment specified");
         return;
      }
      
      // Check for special keywords
      if(comment == "server" || comment == "EMERGENCY" || comment == "CLOSE_ALL_EMERGENCY")
      {
         Print("[ACTION] EMERGENCY CLOSE ALL POSITIONS");
         CloseAllPositions();
         return;
      }
      
      // Otherwise, it's a hash ID (buy_XXXXXXXX or sell_XXXXXXXX)
      // Close only positions matching this hash
      Print("[ACTION] Closing positions with ID: ", comment);
      ClosePositionsByComment(comment);
      
      return;
   }
   
   // Handle BUY (Elastic Expansion)
   if(action == "BUY")
   {
      string sVolume = ExtractJsonValue(response, "volume");
      double volume = StringToDouble(sVolume);
      string comment = ExtractJsonValue(response, "comment");
      bool alert = ExtractJsonBool(response, "alert");
      
      if(volume > 0 && comment != "")
      {
         if(alert)
         {
            Alert("🟢 BUY SIGNAL: ", g_Symbol, " | Volume: ", volume, " | ", comment);
         }
         ExecuteBuyOrder(volume, comment);
      }
      else
      {
         Print("[WARN] Invalid BUY signal - Volume: ", volume, ", Comment: ", comment);
      }
      
      return;
   }
   
   // Handle SELL (Elastic Expansion)
   if(action == "SELL")
   {
      string sVolume = ExtractJsonValue(response, "volume");
      double volume = StringToDouble(sVolume);
      string comment = ExtractJsonValue(response, "comment");
      bool alert = ExtractJsonBool(response, "alert");
      
      if(volume > 0 && comment != "")
      {
         if(alert)
         {
            Alert("🔴 SELL SIGNAL: ", g_Symbol, " | Volume: ", volume, " | ", comment);
         }
         ExecuteSellOrder(volume, comment);
      }
      else
      {
         Print("[WARN] Invalid SELL signal - Volume: ", volume, ", Comment: ", comment);
      }
      
      return;
   }
   
   Print("[WARN] Unknown action: ", action);
}

//+------------------------------------------------------------------+
//| Extract value from JSON string (Simple Parser)                   |
//+------------------------------------------------------------------+
string ExtractJsonValue(string json, string key)
{
   string search = "\"" + key + "\"";
   int pos = StringFind(json, search);
   
   if(pos == -1)
      return "";
   
   // Find the colon after key
   pos = StringFind(json, ":", pos);
   if(pos == -1)
      return "";
   
   pos++; // Move past colon
   
   // Skip whitespace
   while(pos < StringLen(json))
   {
      ushort c = StringGetCharacter(json, pos);
      if(c != ' ' && c != '\t' && c != '\n' && c != '\r')
         break;
      pos++;
   }
   
   // Check if value is string (starts with quote)
   bool isString = false;
   if(StringGetCharacter(json, pos) == '"')
   {
      isString = true;
      pos++; // Skip opening quote
   }
   
   // Find end of value
   int endPos = pos;
   
   if(isString)
   {
      // Find closing quote
      while(endPos < StringLen(json))
      {
         if(StringGetCharacter(json, endPos) == '"')
            break;
         endPos++;
      }
   }
   else
   {
      // Find comma, closing brace, or end
      while(endPos < StringLen(json))
      {
         ushort c = StringGetCharacter(json, endPos);
         if(c == ',' || c == '}' || c == ']' || c == ' ')
            break;
         endPos++;
      }
   }
   
   return StringSubstr(json, pos, endPos - pos);
}

//+------------------------------------------------------------------+
//| Extract boolean value from JSON string                           |
//+------------------------------------------------------------------+
bool ExtractJsonBool(string json, string key)
{
   string value = ExtractJsonValue(json, key);
   return (value == "true" || value == "True" || value == "1");
}

//+------------------------------------------------------------------+
//| Execute BUY order                                                |
//+------------------------------------------------------------------+
void ExecuteBuyOrder(double lots, string comment)
{
   double ask = SymbolInfoDouble(g_Symbol, SYMBOL_ASK);
   
   if(ask <= 0)
   {
      Print("[ERROR] Invalid ASK price: ", ask);
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
   request.type = ORDER_TYPE_BUY;
   request.price = ask;
   request.sl = 0;
   request.tp = 0;
   request.deviation = InpSlippage;
   request.magic = InpMagicNumber;
   request.comment = comment;
   request.type_filling = GetOrderFillingType();
   
   // Send order
   ResetLastError();
   bool sent = OrderSend(request, result);
   
   if(sent && result.retcode == TRADE_RETCODE_DONE)
   {
      Print("[BUY] Order executed - Ticket: ", result.order, 
            ", Volume: ", lots, 
            ", Price: ", result.price,
            ", Comment: ", comment);
   }
   else
   {
      Print("[ERROR] BUY order failed - Retcode: ", result.retcode,
            ", Error: ", GetLastError(),
            ", Comment: ", comment);
   }
}

//+------------------------------------------------------------------+
//| Execute SELL order                                               |
//+------------------------------------------------------------------+
void ExecuteSellOrder(double lots, string comment)
{
   double bid = SymbolInfoDouble(g_Symbol, SYMBOL_BID);
   
   if(bid <= 0)
   {
      Print("[ERROR] Invalid BID price: ", bid);
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
   request.type = ORDER_TYPE_SELL;
   request.price = bid;
   request.sl = 0;
   request.tp = 0;
   request.deviation = InpSlippage;
   request.magic = InpMagicNumber;
   request.comment = comment;
   request.type_filling = GetOrderFillingType();
   
   // Send order
   ResetLastError();
   bool sent = OrderSend(request, result);
   
   if(sent && result.retcode == TRADE_RETCODE_DONE)
   {
      Print("[SELL] Order executed - Ticket: ", result.order,
            ", Volume: ", lots,
            ", Price: ", result.price,
            ", Comment: ", comment);
   }
   else
   {
      Print("[ERROR] SELL order failed - Retcode: ", result.retcode,
            ", Error: ", GetLastError(),
            ", Comment: ", comment);
   }
}

//+------------------------------------------------------------------+
//| Close all positions (EMERGENCY)                                      |
//+------------------------------------------------------------------+
void CloseAllPositions()
{
   int total = PositionsTotal();
   int closed = 0;
   
   for(int i = total - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && PositionSelectByTicket(ticket))
      {
         if(ClosePosition(ticket)) closed++;
      }
   }
   
   Print("[CLOSE] Closed ", closed, " of ", total, " positions");
}

//+------------------------------------------------------------------+
//| Close positions by Hash ID (Snap-Back)                           |
//+------------------------------------------------------------------+
void ClosePositionsByComment(string commentFilter)
{
   int total = PositionsTotal();
   int closed = 0;
   int matched = 0;
   
   for(int i = total - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      
      if(ticket > 0 && PositionSelectByTicket(ticket))
      {
         string comment = PositionGetString(POSITION_COMMENT);
         
         // Check if comment contains filter string (the hash ID)
         if(StringFind(comment, commentFilter) != -1)
         {
            matched++;
            if(ClosePosition(ticket)) closed++;
         }
      }
   }
   
   if(InpDebugMode)
   {
      Print("[CLOSE] Found ", matched, " positions matching '", commentFilter, "', closed ", closed);
   }
}

//+------------------------------------------------------------------+
//| Close single position by ticket                                  |
//+------------------------------------------------------------------+
bool ClosePosition(ulong ticket)
{
   if(!PositionSelectByTicket(ticket))
   {
      Print("[ERROR] Position not found: ", ticket);
      return false;
   }
   
   string symbol = PositionGetString(POSITION_SYMBOL);
   double volume = PositionGetDouble(POSITION_VOLUME);
   ENUM_POSITION_TYPE posType = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
   
   // Determine opposite order type
   ENUM_ORDER_TYPE orderType = (posType == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   
   // Prepare close request
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
   
   // Send close request
   ResetLastError();
   bool sent = OrderSend(request, result);
   
   if(sent && result.retcode == TRADE_RETCODE_DONE)
   {
      if(InpDebugMode)
      {
         Print("[CLOSE] Position closed - Ticket: ", ticket, ", Profit: ", PositionGetDouble(POSITION_PROFIT));
      }
      return true;
   }
   else
   {
      Print("[ERROR] Failed to close position ", ticket, " - Retcode: ", result.retcode, ", Error: ", GetLastError());
      return false;
   }
}

//+------------------------------------------------------------------+
//| Get appropriate order filling type for broker                    |
//+------------------------------------------------------------------+
ENUM_ORDER_TYPE_FILLING GetOrderFillingType()
{
   // Specific logic for Prop Firms / ECN Brokers
   if(StringFind(g_BrokerName, "XM") != -1 ||
      StringFind(g_BrokerName, "Raw Trading") != -1 ||
      StringFind(g_BrokerName, "Royal ETP") != -1 ||
      StringFind(g_BrokerName, "International Capital Markets") != -1 ||
      StringFind(g_BrokerName, "Atlas Funded") != -1)
   {
      return ORDER_FILLING_IOC;
   }
   
   // Fallback to Symbol settings
   int fillingMode = (int)SymbolInfoInteger(g_Symbol, SYMBOL_FILLING_MODE);
   
   if((fillingMode & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK) return ORDER_FILLING_FOK;
   if((fillingMode & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC) return ORDER_FILLING_IOC;
   
   return ORDER_FILLING_RETURN;
}
//+------------------------------------------------------------------+