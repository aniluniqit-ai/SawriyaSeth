"""
OptionChainTrader — LKS WealthTech V21
Req 6,7: Order management + integration hub
"""
import time, uuid, logging, threading, csv, os
from datetime import datetime, time as dtime
from typing import Dict, List, Optional

from option_chain  import (OptionChainFetcher, BudgetGuard, LOT_SIZES,
                            OIAnalysisEngine, ExpiryRangeEngine,
                            is_expiry_day, expiry_trading_phase)
from triple_filter import TripleFilterSystem
from smc_engine    import SMCEngine
from exit_manager  import SmartExitManager, Position
from signal_parser import ParsedSignal
from candlestick   import NextCandleAnalyzer
from prev_day_levels import PrevDayLevels
from excel_tracker import ExcelTracker

logger = logging.getLogger("OptionTrader")


def _estimate_atm_premium(index_price: float, opt_type: str = "CE",
                          strike: int = 0, capital: float = 0, lot_size: int = 1) -> float:
    """
    Delta-based ATM option premium estimator.
    Used when Kotak option chain is not available.
    """
    if index_price <= 0:
        return 50.0  # absolute last resort only
    
    if strike and strike > 0:
        dist_pct = abs(index_price - strike) / index_price
        if dist_pct < 0.005:    pct = 0.0035  # ATM
        elif dist_pct < 0.015:  pct = 0.0020  # Slight OTM
        else:                   pct = 0.0010  # Deep OTM
    else:
        pct = 0.0035  # Assume ATM when no strike given
    
    premium = round(index_price * pct, 1)
    premium = max(5.0, premium)  # minimum ₹5
    if capital > 0 and premium * lot_size > capital:
        # Force a deep OTM fake premium so trade is not blocked in paper mode
        premium = max(5.0, capital / lot_size)
    return round(premium, 1)

class OptionChainTrader:
    SEGMENTS = ["NIFTY","BANKNIFTY","FINNIFTY","SENSEX","MIDCPNIFTY", "BANKEX", "CRUDEOIL", "NATURALGAS", "NATGASMINI", "GOLD", "GOLDM", "GOLDGUINEA", "SILVER", "SILVERM", "SILVERMIC", "RELIANCE", "HDFCBANK", "ICICIBANK", "TATAMOTORS", "SBIN", "INFY"]

    def __init__(self, kotak_api, capital_mgr, cfg:dict, bot=None, db=None):
        self.api      = kotak_api
        self.cap      = capital_mgr
        self.cfg      = cfg
        self.bot      = bot
        self.db       = db
        oc = cfg.get("option_trading",{})
        bg = cfg.get("budget_guard",{})

        self.mode        = oc.get("mode","paper")
        self.auto_trade  = oc.get("auto_trade", False)
        self.require_bos = oc.get("require_bos", True)
        self.min_conf    = oc.get("min_confidence", 55)
        self.max_pos     = cfg.get("capital",{}).get("max_concurrent_positions",2)
        self.start_t     = oc.get("trade_start","09:20")
        self.end_t       = oc.get("trade_end","15:00")
        self.sq_off_t    = oc.get("square_off_time","15:10")

        # Realistic Simulation Settings
        sim = cfg.get("simulation", {})
        self.slippage_pct  = sim.get("slippage_pct", 0.5)      # 0.5% slippage
        self.brokerage     = sim.get("brokerage_per_order", 20) # ₹20 per order
        self.latency_ms    = sim.get("latency_ms", 200)        # 200ms latency
        self.rejection_prob = sim.get("rejection_prob", 0.02)  # 2% chance of rejection
        self.spread_pct    = sim.get("spread_pct", 0.3)        # 0.3% spread impact

        self.chain_fetcher = OptionChainFetcher(kotak_api)
        self.budget_guard  = BudgetGuard(capital_mgr.current, bg)
        self.exit_mgr      = SmartExitManager()

        # Per-segment filters & SMC (Req 3.7, 4.1)
        self.filters:Dict[str,TripleFilterSystem] = {s:TripleFilterSystem(s) for s in self.SEGMENTS}
        self.smcs:Dict[str,SMCEngine]             = {s:SMCEngine() for s in self.SEGMENTS}

        from momentum_scalper import MomentumScalper
        self.momentum_scalpers:Dict[str,MomentumScalper] = {s:MomentumScalper(s, bot=self.bot) for s in self.SEGMENTS}

        # Candle-based entry + next candle trail SL (per segment)
        self.candle_analyzers:Dict[str,NextCandleAnalyzer] = {s:NextCandleAnalyzer(s, 60) for s in self.SEGMENTS}

        # OI Analysis Engine (PCR + OI Change + Support/Resistance)
        self.oi_engine = OIAnalysisEngine()

        # Expiry Day Range Breakout Engine
        self.expiry_range = ExpiryRangeEngine()
        
        # Previous Day High / Low / Close engine (Master Combo Plan)
        self.pdl_engine = PrevDayLevels()
        
        # Excel Logger
        self.excel = ExcelTracker()
        
        # Fix 6: AI Director reference (set externally after init)
        self.ai_director = None

        # Positions & stats
        self.positions:Dict[str,Position] = {}
        self.closed_positions: List[dict]  = []
        self.signals_parsed = 0
        self.signals_valid  = 0
        self._lock = threading.Lock()

        # Active index prices
        self.index_prices:Dict[str,float] = {s:0 for s in self.SEGMENTS}
        
        # AI Market Learning (Track missed big moves)
        self.price_history:Dict[str,list] = {s:[] for s in self.SEGMENTS}
        import os
        if not os.path.exists("logs"): os.makedirs("logs")
        
        self.start_auto_strategy()

    def start_auto_strategy(self):
        threading.Thread(target=self._auto_strategy_loop, daemon=True).start()

    def _auto_strategy_loop(self):
        while True:
            time.sleep(5)
            if not self.auto_trade:
                continue
                
            # Don't take new auto trades if we are at max positions
            with self._lock:
                if len(self.positions) >= self.max_pos:
                    continue
                # Also avoid taking trades in segments we already have open
                active_segments = [p.symbol for p in self.positions.values()]

            for seg in self.SEGMENTS:
                if seg in active_segments: continue
                
                # ── LOSS PROTECTION CHECK ──
                # ── ALIGNMENT CHECK (Nifty vs BankNifty) ──
                # If we are trading indices, ensure they are not in opposite directions
                if seg in ["NIFTY", "BANKNIFTY"]:
                    n_trend = self.smcs["NIFTY"].state.structure
                    bn_trend = self.smcs["BANKNIFTY"].state.structure
                    if n_trend != "SIDEWAYS" and bn_trend != "SIDEWAYS" and n_trend != bn_trend:
                        # logger.debug(f"[Alignment] Blocked {seg} trade: Nifty={n_trend}, BankNifty={bn_trend}")
                        continue

                # 1. Choppy Hours (Avoid 11:30 AM to 1:15 PM)
                now_time = datetime.now().time()
                if dtime(11, 30) <= now_time <= dtime(13, 15):
                    continue

                # 2. Max Losses Rule (Stop if 3+ losses today)
                if self.cap.losses >= 3 and self.cap.daily_pnl < 0:
                    continue
                
                # Check if market is open for this specific segment
                if not self._market_open(seg) or self._sq_off_time(seg):
                    continue

                # MOMENTUM SCALPING STRATEGY CHECK
                if seg in self.momentum_scalpers:
                    ms_sig = self.momentum_scalpers[seg].check_signal(self.index_prices.get(seg, 0))
                    if ms_sig["action"] == "BUY":
                        sig = ParsedSignal(valid=True, action="BUY", symbol=seg, option_type=ms_sig["option_type"], 
                                         strike=0, entry=0, sl=0, targets=[], confidence=95, channel="momentum_scalper")
                        sig.reason = ms_sig["reason"]
                        self.process_telegram_signal(sig)
                        time.sleep(2)
                        continue

                # ── TREND + MOMENTUM CANDLE STRATEGY ──
                if seg in self.candle_analyzers:
                    # Get trend from SMC Engine if available, default to SIDEWAYS
                    trend = self.smcs[seg].state.structure if seg in self.smcs else "SIDEWAYS"
                    
                    # If SMC is SIDEWAYS, fallback to Previous Day Close Bias to catch more trades
                    if trend == "SIDEWAYS":
                        trend = self.pdl_engine.get_bias(seg, self.index_prices.get(seg, 0))
                        
                    opt_type = "CE" if trend == "BULLISH" else ("PE" if trend == "BEARISH" else None)
                    
                    if opt_type:
                        ca_res = self.candle_analyzers[seg].should_enter(opt_type, self.index_prices.get(seg, 0))
                        if ca_res.get("enter", False):
                            sig = ParsedSignal(valid=True, action="BUY", symbol=seg, option_type=opt_type, 
                                             strike=0, entry=0, sl=0, targets=[], confidence=90, channel="candle_analyzer")
                            sig.reason = f"Trend {trend} + {ca_res.get('reason', '')}"
                            self.process_telegram_signal(sig)
                            time.sleep(2)
                            continue

                # ── EXPIRY DAY RANGE BREAKOUT STRATEGY ──
                if hasattr(self, 'expiry_range'):
                    ex_res = self.expiry_range.check_breakout(seg, self.index_prices.get(seg, 0))
                    if ex_res.get("signal"):
                        sig = ParsedSignal(valid=True, action="BUY", symbol=seg, option_type=ex_res["signal"], 
                                         strike=0, entry=0, sl=0, targets=[], confidence=90, channel="expiry_breakout")
                        sig.reason = ex_res.get("reason", "")
                        self.process_telegram_signal(sig)
                        time.sleep(2)
                        continue

    # ── Price feed ──────────────────────────────────
    def set_index_price(self, segment:str, ltp:float):
        if ltp <= 0: return
        self.index_prices[segment] = ltp
        if segment in self.filters:
            self.filters[segment].feed(ltp)
        if segment in self.smcs:
            self.smcs[segment].feed_price(ltp)
        if segment in self.momentum_scalpers:
            self.momentum_scalpers[segment].feed_price(ltp, volume=1.0)
        # Feed candle analyzer for candle-based entry
        if segment in self.candle_analyzers:
            self.candle_analyzers[segment].feed_price(ltp)
        # Feed expiry range engine (marks 1:15–1:30 range)
        self.expiry_range.feed_price(segment, ltp)
        # Feed Previous Day Levels engine
        self.pdl_engine.feed_price(segment, ltp)
        self.budget_guard.update_capital(self.cap.current)
        
        # Update open positions with real option chain prices
        # (called on every real price tick from Kotak)
        if self.positions:
            self.update_positions()
        
        # AI Anomaly Tracker (Self-Learning Logic)
        now = time.time()
        self.price_history.setdefault(segment, []).append((now, ltp))
        self.price_history[segment] = [(t, p) for t, p in self.price_history[segment] if now - t <= 300] # keep 5 mins
        
        if len(self.price_history[segment]) > 20:
            prices = [p for t, p in self.price_history[segment]]
            high, low = max(prices), min(prices)
            move_pct = (high - low) / low * 100
            
            has_active = any(p.symbol == segment for p in self.positions.values())
            # If segment moved wildly (>0.4% in 5 mins) but our strategy didn't catch it
            if move_pct >= 0.4 and not has_active:
                try:
                    # Capture current state for the Audit
                    smc = self.smcs[segment].state.structure if segment in self.smcs else "N/A"
                    oi = self.oi_engine.get_trade_bias(segment)
                    tf = self.filters[segment].get_status()
                    
                    with open("logs/Market_Audit_Journal.txt", "a", encoding="utf-8") as f:
                        dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        direction = "UP" if prices[-1] > prices[0] else "DOWN"
                        f.write(f"[{dt}] MISSED {direction} MOVE: {segment} moved {move_pct:.2f}% in 5 mins.\n")
                        f.write(f"      - Technical State: SMC={smc}, OI={oi}, TripleFilter={tf}\n")
                        
                        # Logic to identify the main blocker
                        blocker = "Unknown"
                        if direction == "UP" and oi == "PE": blocker = "OI Engine (Bearish Bias)"
                        elif direction == "DOWN" and oi == "CE": blocker = "OI Engine (Bullish Bias)"
                        elif smc == "SIDEWAYS": blocker = "SMC Engine (No Trend Detected)"
                        else: blocker = "Triple Filter (Momentum/RSI mismatch)"
                        
                        f.write(f"      - Primary Blocker: {blocker}\n")
                        f.write(f"      - Advice: Consider refining {blocker.split(' ')[0]} thresholds.\n")
                        f.write("-" * 50 + "\n")
                except: pass
                self.price_history[segment] = [] # clear to avoid spam

    # ── Market time ─────────────────────────────────
    def _market_open(self, segment="NIFTY") -> bool:
        now_dt = datetime.now()
        n = now_dt.time()
        
        # Weekend Check + Muhurat Trading Override
        is_weekend = now_dt.weekday() >= 5 # 5=Sat, 6=Sun
        is_muhurat = self.cfg.get("option_trading", {}).get("muhurat_trading", False)
        if is_weekend and not is_muhurat:
            return False

        s = dtime(*map(int,self.start_t.split(":")))
        
        # MCX Market Timing (runs till 11:30 PM)
        mcx_segs = ["CRUDEOIL", "NATURALGAS", "NATGASMINI", "GOLD", "GOLDM", "GOLDGUINEA", "SILVER", "SILVERM", "SILVERMIC"]
        if segment in mcx_segs:
            e = dtime(23, 30)
        else:
            e = dtime(*map(int,self.end_t.split(":")))
            
        return s <= n <= e

    def _sq_off_time(self, segment="NIFTY") -> bool:
        n = datetime.now().time()
        mcx_segs = ["CRUDEOIL", "NATURALGAS", "NATGASMINI", "GOLD", "GOLDM", "GOLDGUINEA", "SILVER", "SILVERM", "SILVERMIC"]
        if segment in mcx_segs:
            return n >= dtime(23, 30)
        t = dtime(*map(int,self.sq_off_t.split(":")))
        return n >= t

    # ── Process Telegram signal ───────────────────────
    def process_telegram_signal(self, parsed: ParsedSignal):
        """
        TWO paths:
          1. TELEGRAM signal  → Simple flow: market open + capital check → BUY
             (No Triple Filter, No BOS, No OI block — channel ne analysis kar li hai)
          2. AUTO signal      → Full 7-layer analysis before entry
        """
        self.signals_parsed += 1
        if not parsed.valid:
            logger.info("Invalid signal — skip")
            return
        self.signals_valid += 1

        seg = parsed.symbol
        if seg not in self.SEGMENTS:
            logger.warning(f"Unknown segment {seg}")
            return

        if not self._market_open(seg):
            logger.info(f"Market closed for {seg} — signal ignored")
            return

        # ── Identify source ──────────────────────────────
        AUTO_SOURCES = ("auto_strategy", "expiry_breakout", "momentum_scalper", "prev_day_breakout")
        is_telegram  = parsed.channel not in AUTO_SOURCES

        # ── AUTO path: Full 7-layer analysis ─────────────
        if not is_telegram:
            tf = self.filters[seg]
            fr = tf.check(parsed.option_type)
            logger.info(f"TF [{seg}] {parsed.option_type}: passed={fr.passed} {fr.reason}")
            if not fr.passed:
                logger.info(f"Auto signal TF blocked: {fr.reason}")
                return

            smc = self.smcs[seg]
            if self.require_bos and not smc.bos_confirmed(parsed.option_type):
                logger.info(f"Auto signal BOS not confirmed for {parsed.option_type}")
                return

            oi_bias = self.oi_engine.get_trade_bias(seg)
            if oi_bias not in ("NEUTRAL", parsed.option_type):
                logger.info(f"Auto signal OI conflict: signal={parsed.option_type}, OI={oi_bias}")
                self._log_audit_rejection(parsed, f"OI Conflict (Signal={parsed.option_type}, OI={oi_bias})")
                return

        # ── TELEGRAM path: log what channel said ─────────
        else:
            if parsed.confidence < self.min_conf:
                logger.info(f"Telegram signal low confidence {parsed.confidence} — skip")
                self._log_audit_rejection(parsed, f"Low Confidence ({parsed.confidence} < {self.min_conf})")
                return
            logger.info(
                f"📡 Telegram signal from [{parsed.channel}]: "
                f"{seg} {parsed.option_type} — proceeding to buy best ATM"
            )

        # ── Common: ATM strike selection ─────────────────
        chain = self.chain_fetcher.get_chain(seg)
        # Update OI engine with fresh data
        if chain:
            self.oi_engine.update(seg, chain, self.index_prices.get(seg, 0))

        strike_data = self.budget_guard.select_strike(
            seg, parsed.option_type, chain,
            preferred_strike=parsed.strike if not is_telegram else None,  # Telegram → always ATM
            index_ltp=self.index_prices.get(seg, 0)
        )

        if not strike_data:
            idx_price = self.index_prices.get(seg, 0)
            lot = LOT_SIZES.get(seg, 25)
            if idx_price > 0:
                # Estimate realistic ATM premium from index price
                entry_price = _estimate_atm_premium(idx_price, parsed.option_type, parsed.strike, self.cap.current, lot)
                logger.warning(
                    f"[{seg}] No option chain — estimated ATM premium: ₹{entry_price} "
                    f"(index={idx_price:.0f}). Connect Kotak for real prices."
                )
            else:
                entry_price = parsed.entry or 50.0
                logger.warning(f"[{seg}] No index price and no chain — using ₹{entry_price} fallback")
            strike = parsed.strike or 0
        else:
            entry_price = strike_data["ltp"] or parsed.entry or 50.0
            strike      = strike_data["strike"]
            lot         = strike_data["lot"]

        # ── Cost check ───────────────────────────────────
        cost = entry_price * lot
        ok, reason = self.cap.can_trade(cost, self.max_pos, len(self.positions))
        if not ok:
            logger.warning(f"Trade blocked: {reason}")
            if self.bot:
                src_label = "📡 Telegram" if is_telegram else "🤖 Auto"
                self.bot.send_error(f"{src_label} Trade blocked: {reason}")
            return

        # Notify if OTM fallback was used
        if strike_data and strike_data.get("otm_fallback") and self.bot and is_telegram:
            self.bot._send(
                f"⚠️ <b>OTM Fallback Used</b>\n"
                f"Telegram ne jo strike bola tha woh ₹{self.cap.current:.0f} capital mein "
                f"afford nahi hoti.\n"
                f"Auto-selected OTM strike: <code>{strike_data['strike']}</code> @ "
                f"₹{strike_data['ltp']} (affordable)"
            )

        # ── SL / Targets ─────────────────────────────────
        # Telegram: always use auto SL/targets (candle reversal handles quick exit)
        sl, targets = SmartExitManager.auto_sl_targets(entry_price, seg)
        targets = list(targets)

        self._open_position(seg, parsed.option_type, strike, entry_price,
                            lot, sl, targets, parsed.channel)

    def _resolve_trading_symbol(self, symbol: str, segment: str = "nse_fo") -> str:
        """Resolve common name to official Kotak trading symbol (e.g. RELIANCE -> RELIANCE-EQ)"""
        if not self.api.master_data:
            return symbol
        info = self.api.get_master_info(symbol, segment)
        # The row from CSV usually has 'pTrdSymbol'
        if "row" in info:
            return info["row"].get("pTrdSymbol", symbol)
        return symbol

    # ── Open position ────────────────────────────────
    def _open_position(self, seg:str, opt_type:str, strike:int,
                       entry:float, lot:int, sl:float,
                       targets:List[float], source:str):
        with self._lock:
            # New: Get Lot Size and Correct Symbol from Scrip Master (Kotak)
            # Try NSE FO for options, NSE CM for stocks
            is_option = (strike > 0 or opt_type in ["CE", "PE"])
            exch_seg = "nse_fo" if is_option else "nse_cm"
            if seg in ["CRUDEOIL", "NATURALGAS", "GOLD", "SILVER"]:
                exch_seg = "mcx_fo"

            master_info = self.api.get_master_info(seg, exch_seg)
            if master_info and master_info.get("lot") and master_info["lot"] > 1:
                lot = master_info["lot"]
                logger.info(f"[{seg}] Using Scrip Master Lot Size: {lot}")

            # Official Symbol Resolution (RELIANCE -> RELIANCE-EQ)
            official_symbol = self._resolve_trading_symbol(seg, exch_seg)
            opt_sym = f"{official_symbol} {strike}{opt_type}".strip() if is_option else official_symbol
            
            pos_id  = str(uuid.uuid4())[:8]
            
            # Compounding Lot Calculation based on 80% Capital
            cost_per_lot = entry * lot
            
            # Dynamic Kelly Sizing
            if hasattr(self.cap, 'get_kelly_lots'):
                num_lots = self.cap.get_kelly_lots(cost_per_lot)
            else:
                num_lots = 1
                
            qty = lot * num_lots
            logger.info(f"[{seg}] Kelly Dynamic Sizing: {num_lots} lots, qty={qty}")


            # ── SL / Targets (ATR Based for Best Risk/Reward) ──
            # Try to get ATR from Candle Analyzer
            atr = 0
            if seg in self.candle_analyzers:
                atr = self.candle_analyzers[seg].engine.get_atr(14)
            
            if atr > 0:
                # Use 1.5x ATR for SL, but cap it at 20% of premium
                sl_points = round(atr * 1.5, 1)
                sl = round(entry - min(sl_points, entry * 0.20), 2)
                t1 = round(entry + sl_points, 2) # 1:1 T1
                t2 = round(entry + sl_points * 2.5, 2) # 1:2.5 T2
                targets = [t1, t2]
                logger.info(f"[{seg}] ATR-Based SL used: {sl} (ATR={atr:.1f})")
            else:
                sl, targets = SmartExitManager.auto_sl_targets(entry, seg)
                targets = list(targets)

            # Req 6.1 paper / 6.2 live
            exch = "mcx_fo" if seg in ["CRUDEOIL", "NATURALGAS", "NATGASMINI", "GOLD", "GOLDM", "GOLDGUINEA", "SILVER", "SILVERM", "SILVERMIC"] else "nse_fo"
            import random
            
            # Simulate Latency
            if self.latency_ms > 0:
                time.sleep(self.latency_ms / 1000.0)

            # Order Rejection Probability
            if random.random() < self.rejection_prob:
                logger.warning(f"Order REJECTED (Simulated): {opt_sym}")
                if self.bot: self.bot.send_error(f"Order REJECTED (Simulated): {opt_sym}")
                return

            if self.mode == "paper" or not self.auto_trade:
                # Apply Dynamic Slippage based on ATR (Volatility)
                dynamic_slippage = self.slippage_pct
                if atr > 0:
                    dynamic_slippage += min(1.0, (atr / entry) * 10) # Add max 1% extra slippage
                    
                impact = 1 + (dynamic_slippage / 100.0) + (self.spread_pct / 100.0)
                filled = round(entry * impact, 2)
                order_status = "COMPLETE"
                logger.info(f"PAPER order: {opt_sym} qty={qty} @{filled} (Original: {entry}, Impact: {impact-1:.2%})")
            else:
                result = self.api.place_order(opt_sym,exch,qty,"B","MIS","MKT")
                if result.get("stat") != "Ok":
                    logger.error(f"Order fail: {result}")
                    if self.bot: self.bot.send_error(f"Order fail: {result.get('emsg')}")
                    return
                filled = entry; order_status = "COMPLETE"

            pos = Position(
                id=pos_id, symbol=seg, option_type=opt_type,
                strike=strike, option_symbol=opt_sym,
                entry=filled, lot=lot, qty=qty, sl=sl,
                targets=targets, source=source,
                mode=self.mode
            )
            
            # Deduct Brokerage from capital
            self.cap.record(-self.brokerage)
            
            self.positions[pos_id] = pos
            
            # Excel Log Open
            self.excel.log_trade_open({
                "id": pos_id, "segment": seg, "option_type": opt_type,
                "strike": strike, "entry": filled, "qty": qty, "lot": lot,
                "sl": sl, "targets": targets, "source": source, "mode": self.mode
            })
            
            # Add Buy marker to candlestick chart
            if seg in self.candle_analyzers:
                cc = self.candle_analyzers[seg].engine.current_candle
                if cc: cc.markers.append(("B", "lime"))

            AUTO_SOURCES = ("auto_strategy", "expiry_breakout", "momentum_scalper", "prev_day_breakout")
            src_emoji = "📡 TELEGRAM" if source not in AUTO_SOURCES else "🤖 AUTO STRATEGY"
            mode_icon = "📄 PAPER" if self.mode == "paper" else "💰 LIVE"
            msg = (f"{mode_icon} | {src_emoji}\n"
                   f"🟢 <b>NEW BUY TRADE EXECUTED</b>\n"
                   f"━━━━━━━━━━━━━━━\n"
                   f"📊 Option    : <b>{opt_sym}</b>\n"
                   f"💵 Buy Rate  : <code>₹{filled}</code>\n"
                   f"🛑 Stop Loss : <code>₹{sl}</code>\n"
                   f"🎯 Target T1 : <code>₹{targets[0]}</code>\n"
                   f"🎯 Target T2 : <code>₹{targets[1] if len(targets)>1 else '—'}</code>\n"
                   f"📦 Quantity  : {qty} ({qty // lot} lot)\n"
                   f"📈 Trend     : {self.smcs[seg].state.structure if seg in self.smcs else 'Unknown'}\n"
                   f"📡 Source    : {source}")
            logger.info(msg.replace("<b>","").replace("</b>","").replace("<code>","").replace("</code>",""))
            if self.bot: self.bot._send(msg)

    # ── Update positions (Req 7.2) ───────────────────
    def update_positions(self):
        """Called every 3 seconds from price loop"""
        with self._lock:
            to_close = []
            for pid, pos in self.positions.items():
                seg = pos.symbol
                
                if self._sq_off_time(seg):
                    to_close.append((pid, "TIME_SQ_OFF"))
                    continue
                    
                # Get option LTP (approximate from index ltp for paper)
                idx_ltp  = self.index_prices.get(seg, 0)
                # In paper mode simulate premium movement
                cur_prem = self._get_real_premium(pos, idx_ltp)
                choch    = self.smcs[seg].state.choch

                result = self.exit_mgr.check_exit(pos, cur_prem, choch)

                if result["action"] == "EXIT":
                    pnl = self.exit_mgr.calc_pnl(pos, cur_prem, pos.qty_remaining)
                    self._close_position(pos, cur_prem, result["reason"], pnl)
                    to_close.append(pid)
                elif result["action"] == "PARTIAL":
                    half = pos.qty_remaining // 2
                    pnl  = self.exit_mgr.calc_pnl(pos, cur_prem, half)
                    pos.qty_remaining -= half
                    self.cap.record(pnl)
                    logger.info(f"Partial exit {pos.option_symbol} +{half} pnl={pnl:.0f}")
                    if self.bot:
                        self.bot._send(f"🎯 <b>T1 Hit — Partial Exit</b>\n"
                                       f"{pos.option_symbol} | P&L: ₹{pnl:+.0f}")
                else:
                    # Next-candle trail/exit check (candle-based SL trail)
                    ca = self.candle_analyzers.get(seg)
                    if ca:
                        nc = ca.analyze_next_candle(pos.option_type, pos.sl)
                        if nc["action"] == "EXIT":
                            pnl = self.exit_mgr.calc_pnl(pos, cur_prem, pos.qty_remaining)
                            self._close_position(pos, cur_prem, f"CANDLE_{nc['reason']}", pnl)
                            to_close.append(pid)
                            logger.info(f"[NextCandle] EXIT {pos.option_symbol}: {nc['reason']}")
                        elif nc["action"] == "TRAIL_SL" and nc["new_sl"] != pos.sl:
                            old_sl = pos.sl
                            pos.sl = nc["new_sl"]
                            logger.info(f"[NextCandle] TRAIL_SL {pos.option_symbol}: "
                                        f"{old_sl:.1f} → {pos.sl:.1f}")
                            if self.bot:
                                self.bot._send(
                                    f"📈 <b>SL Trailed (Candle)</b>\n"
                                    f"{pos.option_symbol}\n"
                                    f"SL: <code>{old_sl:.1f} → {pos.sl:.1f}</code>\n"
                                    f"Reason: {nc['reason']}"
                                )

                # Update P&L display
                pos.pnl = self.exit_mgr.calc_pnl(pos, cur_prem, pos.qty_remaining)

            for pid in to_close:
                del self.positions[pid]

    def _get_real_premium(self, pos: Position, idx_ltp: float) -> float:
        """
        Fetch REAL option LTP from Kotak option chain cache.
        Paper mode = real prices, virtual order execution.
        Falls back to last known real price if chain not yet refreshed.
        """
        seg = pos.symbol
        opt_type = pos.option_type
        strike   = pos.strike

        # Try to get from cached option chain (refreshed every 30s)
        try:
            chain = self.chain_fetcher.get_chain(seg)
            if chain:
                strikes = chain.get("data", {}).get("strikePrices", [])
                for s in strikes:
                    if s.get("strikePrice") == strike:
                        ltp = s.get(opt_type, {}).get("ltp", 0)
                        if ltp and ltp > 0:
                            pos._last_real_premium = ltp   # remember it
                            return float(ltp)
        except Exception as e:
            logger.debug(f"[RealPremium] {pos.option_symbol}: {e}")

        # Fallback: use last known real premium (not delta estimate)
        if hasattr(pos, '_last_real_premium') and pos._last_real_premium > 0:
            return pos._last_real_premium

        # Last resort: estimate from index price (NOT fake ₹50)
        idx_ltp = self.index_prices.get(seg, 0)
        if idx_ltp > 0:
            estimated = _estimate_atm_premium(idx_ltp, opt_type, strike)
            logger.debug(f"[RealPremium] {pos.option_symbol}: using delta estimate ₹{estimated} (index={idx_ltp:.0f})")
            return estimated
        
        # Absolute last resort: entry price (prevents ₹50 stale forever)
        return pos.entry

    def _close_position(self, pos:Position, exit_price:float, reason:str, pnl:float):
        import random
        # Simulate Latency
        if self.latency_ms > 0:
            time.sleep(self.latency_ms / 1000.0)

        # Apply Slippage and Spread for Exit (Selling → get slightly less)
        if self.mode == "paper" or not self.auto_trade:
            # Dynamic Slippage for Exit
            dynamic_slippage = self.slippage_pct
            # Estimate ATR if possible, fallback to static if not
            if hasattr(self, 'candle_analyzers') and pos.symbol in self.candle_analyzers:
                atr = self.candle_analyzers[pos.symbol].engine.get_atr(14)
                if atr > 0:
                    dynamic_slippage += min(1.0, (atr / exit_price) * 10)
                    
            impact = 1 - (dynamic_slippage / 100.0) - (self.spread_pct / 100.0)
            final_exit = round(exit_price * impact, 2)
            # Re-calculate PnL based on realistic exit
            pnl = (final_exit - pos.entry) * pos.qty_remaining
        else:
            final_exit = exit_price

        if self.mode == "live" and self.auto_trade and self.api.logged_in:
            exch = "mcx_fo" if pos.symbol in ["CRUDEOIL", "NATURALGAS", "NATGASMINI", "GOLD", "GOLDM", "GOLDGUINEA", "SILVER", "SILVERM", "SILVERMIC"] else "nse_fo"
            self.api.place_order(pos.option_symbol,exch,
                                 pos.qty_remaining,"S","MIS","MKT")
        
        pos.status     = "CLOSED"
        pos.exit_reason= reason
        pos.pnl        = pnl
        
        # Deduct Brokerage and record PnL
        self.cap.record(pnl - self.brokerage)
        
        # Add Sell marker to candlestick chart
        seg = pos.symbol
        if seg in self.candle_analyzers:
            cc = self.candle_analyzers[seg].engine.current_candle
            if cc: cc.markers.append(("S", "red"))
        
        # Fix 2: Link momentum scalper loss counter to actual trade outcomes
        if pnl < 0 and pos.source == "momentum_scalper":
            seg = pos.symbol
            if seg in self.momentum_scalpers:
                self.momentum_scalpers[seg].record_loss()
                logger.info(f"MomentumScalper [{seg}] loss recorded. Daily losses updated.")
        self.closed_positions.append({
            "symbol":pos.option_symbol,"entry":pos.entry,
            "exit":final_exit,"pnl":round(pnl,2),"reason":reason,
            "time":datetime.now().strftime("%H:%M:%S")
        })
        emoji = "✅" if pnl > 0 else "❌"
        res_text = "PROFIT BOOKED" if pnl > 0 else "STOP LOSS HIT / EXIT"
        if self.bot:
            self.bot._send(f"{emoji} <b>POSITION CLOSED — {res_text}</b>\n"
                           f"Reason: {reason}\n"
                           f"━━━━━━━━━━━━━━━\n"
                           f"📊 Option: <b>{pos.option_symbol}</b>\n"
                           f"💵 Buy Rate: ₹{pos.entry}\n"
                           f"💸 Sell Rate: ₹{final_exit}\n"
                           f"💰 P&L: <code>₹{pnl:+.0f}</code>\n"
                           f"🏦 Capital: ₹{self.cap.current:,.0f}")
        logger.info(f"Closed {pos.option_symbol} {reason} pnl={pnl:.0f} (Exit: {final_exit})")

        # Excel Log Close
        self.excel.log_trade_close({
            "id": pos.id, "exit_price": final_exit, "pnl": round(pnl, 2), "reason": reason
        })

        # CSV Export
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            csv_file = f"logs/trades_{today}.csv"
            file_exists = os.path.exists(csv_file)
            with open(csv_file, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["Time", "Symbol", "Type", "Entry Price", "Exit Price", "Qty", "PnL", "Reason", "Mode"])
                writer.writerow([
                    datetime.now().strftime("%H:%M:%S"),
                    pos.option_symbol,
                    pos.option_type,
                    pos.entry,
                    final_exit,
                    pos.qty,
                    round(pnl, 2),
                    reason,
                    self.mode
                ])
        except Exception as e:
            logger.error(f"Failed to write CSV: {e}")

    def _log_audit_rejection(self, parsed, reason: str):
        """Log rejected signals to the Audit Journal."""
        try:
            with open("logs/Market_Audit_Journal.txt", "a", encoding="utf-8") as f:
                dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{dt}] REJECTED SIGNAL: {parsed.channel} | {parsed.symbol} {parsed.option_type}\n")
                f.write(f"      - Reason: {reason}\n")
                f.write("-" * 50 + "\n")
        except: pass

    def _square_off_all(self):
        with self._lock:
            pids = list(self.positions.keys())
            for pid in pids:
                pos = self.positions[pid]
                idx = self.index_prices.get(pos.symbol, 0)
                cur = self._get_real_premium(pos, idx)   # Fix: was _estimate_premium (old name)
                pnl = self.exit_mgr.calc_pnl(pos, cur, pos.qty_remaining)
                self._close_position(pos, cur, "SQUAREOFF", pnl)
                del self.positions[pid]
            if pids and self.bot:
                self.bot._send(f"🔔 <b>Auto Square Off</b>\n{len(pids)} positions closed")

    # ── Status for dashboard (Req 7.4) ──────────────
    def get_filter_status(self) -> dict:
        return {s: self.filters[s].get_status() for s in self.SEGMENTS}

    def get_smc_status(self) -> dict:
        return {s: self.smcs[s].get_status() for s in self.SEGMENTS}

    def get_opt_stats(self) -> dict:
        return {
            "open_positions": [
                {"id":p.id,"symbol":p.option_symbol,"opt_type":p.option_type,
                 "entry":p.entry,"sl":p.sl,"targets":p.targets,
                 "pnl":round(p.pnl,2),"source":p.source,"mode":p.mode,
                 "partial":p.partial_booked}
                for p in self.positions.values()
            ],
            "closed_today": self.closed_positions[-20:],
            "auto_trade":   self.auto_trade,
            "mode":         self.mode,
        }

    def get_parser_stats(self) -> dict:
        rate = (self.signals_valid/max(1,self.signals_parsed)*100)
        return {"total_parsed":self.signals_parsed,
                "valid":self.signals_valid,
                "success_rate":round(rate,1)}
