"""
Momentum Candle Scalping Master Plan (Req: ₹100–₹500 Target)
Author: AI (LKS WealthTech)
"""
import time, logging
from datetime import datetime, time as dtime
from typing import Dict
from candlestick import InstitutionalCandleEngine

logger = logging.getLogger("MomentumScalper")

class MomentumScalper:
    def __init__(self, segment: str, bot=None):
        self.segment = segment
        self.bot = bot
        self.candle_engine = InstitutionalCandleEngine(timeframe_seconds=60) # 1 min candles
        
        self.vwap = 0.0
        self.total_volume = 0.0
        self.total_pv = 0.0
        self._vwap_reset_date = None  # Fix 1: VWAP daily reset tracking
        
        self.daily_trades = 0
        self.daily_losses = 0
        self.last_trade_date = None
        
        # State
        self.armed_direction = None # "CE" or "PE"
        self.momentum_candle = None
        
    def _is_valid_time(self) -> bool:
        now = datetime.now().time()
        # MCX segments can trade till 11:30 PM
        if self.segment in ["CRUDEOIL", "NATURALGAS"]:
            return dtime(9, 0) <= now <= dtime(23, 30)
        # 9:25–11:30
        if dtime(9, 25) <= now <= dtime(11, 30): return True
        # 13:30–15:00
        if dtime(13, 30) <= now <= dtime(15, 0): return True
        return False

    def feed_price(self, price: float, volume: float = 1.0):
        # Fix 1: Reset VWAP daily so yesterday's data doesn't bleed into today
        today = datetime.now().date()
        if self._vwap_reset_date != today:
            self.total_volume = 0.0
            self.total_pv = 0.0
            self.vwap = price
            self._vwap_reset_date = today
            logger.info(f"[{self.segment}] VWAP reset for new day")
        
        # Update VWAP
        self.total_volume += volume
        self.total_pv += price * volume
        self.vwap = self.total_pv / self.total_volume if self.total_volume > 0 else price
        
        # Feed candle
        self.candle_engine.feed_price(price)
        
    def record_loss(self):
        self.daily_losses += 1
        
    def check_signal(self, current_price: float) -> dict:
        today = datetime.now().date()
        if self.last_trade_date != today:
            self.daily_trades = 0
            self.daily_losses = 0
            self.last_trade_date = today
            self.armed_direction = None
            
        if self.daily_trades >= 3 or self.daily_losses >= 2:
            return {"action": None}
            
        if not self._is_valid_time():
            self.armed_direction = None
            return {"action": None}
            
        candles = self.candle_engine.candles
        if len(candles) < 2: return {"action": None}
        
        last_closed = candles[-1]
        
        # If not armed, check for new big momentum candle
        if not self.armed_direction:
            body = last_closed.body_size()
            avg_body = sum(c.body_size() for c in candles[-5:]) / max(1, len(candles[-5:]))
            
            # Volume Spike (using tick_count as proxy)
            v_spike = last_closed.tick_count
            avg_v   = sum(c.tick_count for c in candles[-5:]) / max(1, len(candles[-5:]))
            
            # Momentum = candle is 2.0x bigger than recent average OR > 2.0x ATR
            atr = self.candle_engine.get_atr(14)
            min_size = current_price * 0.0005
            
            is_momentum = body > (avg_body * 2.2) and body > min_size
            if atr > 0:
                is_momentum = is_momentum or (body > atr * 2.0)
                
            is_vol_spike = v_spike > (avg_v * 1.5)
            
            if is_momentum and is_vol_spike:
                # Check VWAP condition
                if last_closed.is_bullish() and last_closed.close > self.vwap:
                    self.armed_direction = "CE"
                    self.momentum_candle = last_closed
                    logger.info(f"[{self.segment}] Armed CE on Momentum Candle High: {last_closed.high}")
                    msg = (f"⚡ <b>SCALPING SETUP ARMED</b> ⚡\n"
                           f"<b>Segment:</b> {self.segment}\n"
                           f"<b>Direction:</b> CE (Call)\n"
                           f"<b>Condition:</b> Buy IF index crosses above <code>{last_closed.high:.1f}</code>\n"
                           f"<b>Index SL:</b> <code>{last_closed.low:.1f}</code>\n"
                           f"<i>Waiting for breakout...</i>")
                    if self.bot: self.bot._send(msg)
                elif last_closed.is_bearish() and last_closed.close < self.vwap:
                    self.armed_direction = "PE"
                    self.momentum_candle = last_closed
                    logger.info(f"[{self.segment}] Armed PE on Momentum Candle Low: {last_closed.low}")
                    msg = (f"⚡ <b>SCALPING SETUP ARMED</b> ⚡\n"
                           f"<b>Segment:</b> {self.segment}\n"
                           f"<b>Direction:</b> PE (Put)\n"
                           f"<b>Condition:</b> Buy IF index crosses below <code>{last_closed.low:.1f}</code>\n"
                           f"<b>Index SL:</b> <code>{last_closed.high:.1f}</code>\n"
                           f"<i>Waiting for breakout...</i>")
                    if self.bot: self.bot._send(msg)
                    
            return {"action": None}
            
        # If armed, check if current price breaks high/low
        else:
            if self.armed_direction == "CE":
                if current_price > self.momentum_candle.high:
                    self.armed_direction = None # Disarm
                    self.daily_trades += 1
                    return {
                        "action": "BUY",
                        "option_type": "CE",
                        "index_sl": self.momentum_candle.low, # Price SL on Index
                        "reason": "Momentum High Breakout"
                    }
                # Disarm if price goes below momentum candle low
                if current_price < self.momentum_candle.low:
                    self.armed_direction = None
                    
            elif self.armed_direction == "PE":
                if current_price < self.momentum_candle.low:
                    self.armed_direction = None # Disarm
                    self.daily_trades += 1
                    return {
                        "action": "BUY",
                        "option_type": "PE",
                        "index_sl": self.momentum_candle.high, # Price SL on Index
                        "reason": "Momentum Low Breakout"
                    }
                # Disarm if price goes above momentum candle high
                if current_price > self.momentum_candle.high:
                    self.armed_direction = None
                    
        return {"action": None}
