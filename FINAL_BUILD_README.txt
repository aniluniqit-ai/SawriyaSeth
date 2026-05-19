LKS V10 - FINAL FREEZE (PAPER-ONLY LIVE-DATA BUILD)
====================================================

What this build guarantees
--------------------------
1) Live market data from Kotak (when login is successful).
2) Trading engine runs in PAPER mode only (no real order placement).
3) Paper capital + paper PnL accounting.
4) Dashboard shows:
   - Live watch
   - Mini option chain (LTP/OI)
   - Open/closed trades
   - Scalp chart with Entry/SL/T1/T2
   - Kotak limits/wallet style fields (if API returns them)

Hard safety lock
----------------
- config/config.json -> option_trading.paper_only = true
- Even if mode is changed in UI, paper-only lock keeps execution paper.

Run steps
---------
1) Double click START.bat
2) If Telegram OTP appears, enter OTP.
3) Confirm logs show:
   - Capital loaded
   - Kotak API login successful

Important config keys
---------------------
File: config/config.json

- option_trading.paper_only
  Keep true for safety.

- option_trading.segments
  Symbols AI scalping considers.

- market_universe
  Symbols dashboard fetches live rates for.
  Each symbol supports aliases:
  {
    "CRUDEOIL": {
      "exchange": "mcx_fo",
      "symbol": "CRUDEOILM",
      "aliases": ["CRUDEOILM", "CRUDEOIL"]
    }
  }

- capital.initial_capital
  Paper capital baseline (currently 2000).

Known runtime blockers (not code bugs)
--------------------------------------
1) Kotak "Consumer key ... does not exist"
   - Invalid/revoked consumer key at broker side.
   - Fix by updating correct key in Settings.

2) Telegram "too many values to unpack"
   - Corrupt/old telethon session DB.
   - Build auto-resets session and tries fresh *_v2 file.

3) Option chain non-JSON/empty response
   - Broker endpoint intermittently returns empty/non-JSON.
   - Build now safely handles it, uses cache fallback, and rate-limits logs.

Operational checklist
---------------------
- Keep paper_only = true
- Keep option_trading.mode = paper
- Verify Kotak login each start
- Verify at least one symbol in live watch updates every few seconds
- Verify open trade appears in positions panel and chart lines

Freeze note
-----------
This freeze is production-safe for PAPER execution + LIVE data.
Any remaining failures are expected to be broker credential/symbol mapping issues.
