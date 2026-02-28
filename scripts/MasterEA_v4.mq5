//+------------------------------------------------------------------+
//|                                              MasterEA_v4.mq5     |
//|                          Elastic DCA Cloud — Phase 1 Master EA   |
//|                          Data Feeder: sends {ask, bid,           |
//|                          contract_size} to the server every 1s.  |
//+------------------------------------------------------------------+
//  Blueprint Section 3.1:
//    - Role: Sole source of market truth (XAUUSD)
//    - Sends: {ask, bid, contract_size, server_time}
//    - Auth:  X-Admin-Key header
//    - Retry: Log every 20 failures to avoid journal spam
//+------------------------------------------------------------------+
#property copyright "Elastic DCA System"
#property link "https://github.com/kumawat-aditya/elastic-dca-trader"
#property version "4.0.0"
#property strict

//--- Input Parameters (Section 3.1) ----------------------------------
input string InpServerURL = "http://YOUR_SERVER_IP:8000";  // Server URL
input string InpAdminKey = "CHANGE_ME_TO_A_STRONG_SECRET"; // X-Admin-Key
input int InpTimeout = 5000;                               // HTTP timeout (ms)
input bool InpDebugMode = false;                           // Verbose logging

//--- Global Variables -------------------------------------------------
int g_ConsecutiveErrors = 0;
double g_LastAsk = 0.0;
double g_LastBid = 0.0;

//+------------------------------------------------------------------+
//| Expert initialization                                            |
//+------------------------------------------------------------------+
int OnInit()
{
    EventSetTimer(1); // 1-second polling interval

    Print("══════════════════════════════════════════════════");
    Print("  Elastic DCA Cloud — Master EA v4.0 Initialized");
    Print("══════════════════════════════════════════════════");
    Print("  Symbol : ", _Symbol);
    Print("  Server : ", InpServerURL);
    Print("  Timeout: ", InpTimeout, " ms");
    Print("══════════════════════════════════════════════════");
    Print("  IMPORTANT: Whitelist the server URL in:");
    Print("  Tools → Options → Expert Advisors → Allow WebRequest");
    Print("══════════════════════════════════════════════════");

    return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    EventKillTimer();
    Print("Master EA stopped. Reason code: ", reason);
}

//+------------------------------------------------------------------+
//| Timer — fires every 1 second                                     |
//+------------------------------------------------------------------+
void OnTimer()
{
    SendTick();
}

//+------------------------------------------------------------------+
//| Send price tick to the server                                    |
//+------------------------------------------------------------------+
void SendTick()
{
    // Get current market data
    double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
    double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

    if (ask <= 0 || bid <= 0)
    {
        if (InpDebugMode)
            Print("[MASTER] Invalid price data: ask=", ask, " bid=", bid);
        return;
    }

    // Get contract size from broker (Section 3.1)
    // For XAUUSD this returns 100.0 (1 lot = 100 troy ounces)
    double contractSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE);

    // Build JSON payload (Section 11.1)
    string json = StringFormat(
        "{\"ask\":%.5f,\"bid\":%.5f,\"contract_size\":%.2f}",
        ask, bid, contractSize);

    // Build URL
    string url = InpServerURL + "/api/master-tick";

    // Build headers
    string headers = "Content-Type: application/json\r\n" + "X-Admin-Key: " + InpAdminKey + "\r\n";

    // Send HTTP POST
    char postData[];
    char resultData[];
    string resultHeaders;
    int dataLen = StringToCharArray(json, postData, 0, WHOLE_ARRAY, CP_UTF8) - 1;

    int responseCode = WebRequest(
        "POST",
        url,
        headers,
        InpTimeout,
        postData,
        resultData,
        resultHeaders);

    // Handle response
    if (responseCode == 200)
    {
        if (g_ConsecutiveErrors > 0)
        {
            Print("[MASTER] Connection restored after ", g_ConsecutiveErrors, " failures.");
            g_ConsecutiveErrors = 0;
        }

        g_LastAsk = ask;
        g_LastBid = bid;

        if (InpDebugMode)
        {
            string responseStr = CharArrayToString(resultData, 0, WHOLE_ARRAY, CP_UTF8);
            Print("[MASTER] Tick sent: ask=", ask, " bid=", bid,
                  " contract_size=", contractSize, " → ", responseStr);
        }
    }
    else
    {
        g_ConsecutiveErrors++;

        // Log every 20 failures to avoid journal spam (Section 3.1)
        if (g_ConsecutiveErrors % 20 == 1)
        {
            string errorMsg = "";
            if (responseCode == -1)
                errorMsg = "Connection failed (check WebRequest whitelist)";
            else if (responseCode == 401)
                errorMsg = "Unauthorized (check X-Admin-Key)";
            else
                errorMsg = StringFormat("HTTP %d", responseCode);

            Print("[MASTER] ERROR: ", errorMsg,
                  " (consecutive failures: ", g_ConsecutiveErrors, ")");
        }
    }
}
//+------------------------------------------------------------------+
