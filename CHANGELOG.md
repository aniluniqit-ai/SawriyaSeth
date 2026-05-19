# LKS WealthTech V21 - Changelog & Current State

## Updates Completed Today (Latest AI & Database Upgrade)
1. **Microsoft SQL Server Database Integration**
   - Created `db_manager.py` to auto-log every single price movement (ticks) and closed trades into `LKS_Trader_DB`.
   
2. **AI Director (Machine Learning Strategy Selector)**
   - Created `ai_director.py` that runs at 8:30 AM to analyze past 5 days of database history.
   - Automatically selects between SMC or VWAP strategy based on highest win-rate.

3. **Multi-Market & Forex Trading (XM Global MT5)**
   - Integrated Python `MetaTrader5` via `mt5_api.py`.
   - Live Dashboard now fetches $ Dollar balance from XM automatically.
   - Auto-maps "GOLD" and "XAU/USD" signals to MT5 `XAUUSD` and places Buy/Sell orders instantly.
   
4. **Dashboard Upgrades**
   - **Live PnL Chart:** Integrated Matplotlib to draw a real-time Equity curve directly on the UI.
   - **Account Settings UI:** Added a popup tab to securely save Kotak Neo and XM MT5 credentials to `config/accounts.json`.
   - **Live/Paper Toggle:** Added a single-click button to switch trading modes without restarting.
   
5. **Emergency Kill Switch**
   - **Manual:** Big red button on sidebar to lock the system and square off all trades instantly.
   - **Auto:** System monitors `daily_loss_pct` and auto-triggers Kill Switch if loss limits are breached to prevent revenge trading.
   
6. **Critical Bug Fixes & Adjustments**
   - **Lot Size Safety:** Strictly locked to exactly 1 Lot as long as capital is below ₹10,000. Compounding (80% allocation) starts only after 10K.
   - **PE Calculation Fix:** Resolved an inversion bug where Put (PE) profits were calculating incorrectly.
   - **MCX Night Trading:** Modified time limits so `CRUDEOIL` and `NATURALGAS` can continue taking auto-trades until 11:30 PM (23:30).

## Older Updates
1. **Advanced Trailing Stop Loss (TSL)**
   - Initial Stop Loss is fixed at 10 points. Target 1 books 50% qty. SL trails 5 points.
2. **UI Theme:** Vastu-compliant Dark Green & Golden aesthetics with Shubh-Labh images.
3. **SMC Engine:** Identifies BOS/CHoCH.

## Note
- If testing Forex/MT5, ensure MetaTrader 5 software is installed and running on the PC/VPS.
