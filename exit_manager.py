"""
Smart Exit System — LKS WealthTech V21
Requirement 5: Priority exit conditions
"""
import time, logging
from dataclasses import dataclass, field
from typing import List, Optional
logger = logging.getLogger("ExitMgr")

@dataclass
class Position:
    id:            str
    symbol:        str
    option_type:   str   # CE / PE
    strike:        int
    option_symbol: str
    entry:         float
    lot:           int
    qty:           int
    sl:            float
    targets:       List[float]
    source:        str   = "telegram"   # telegram / auto
    mode:          str   = "paper"
    partial_booked:bool  = False
    booked_level:  int   = 0
    qty_remaining: int   = 0
    entry_time:    float = 0.0
    last_move_price:float= 0.0
    last_move_time: float= 0.0
    pnl:           float = 0.0
    status:        str   = "OPEN"   # OPEN / CLOSED
    exit_reason:   str   = ""

    def __post_init__(self):
        self.qty_remaining = self.qty
        self.last_move_price = self.entry
        self.entry_time = time.time()
        self.last_move_time = time.time()

class SmartExitManager:
    """Req 5.1–5.7"""

    MOMENTUM_WINDOW  = 30   # seconds (faster exit on stale trades)
    MOMENTUM_MIN_PCT = 0.3  # %

    @staticmethod
    def auto_sl_targets(entry: float):
        """
        Smart Capital-Aware SL & Targets:

        MICRO/OTM entry (entry <= ₹30):
          SL     = entry - max(₹5, entry * 25%)   ← tight (₹5–₹8)
          Target1= entry + ₹8                     ← quick scalp book
          Target2= entry + ₹15                    ← runner target

        NORMAL entry (₹30 < entry <= ₹100):
        Now includes Micro-Scalping for Commodities (MCX).
        """
        # MCX Micro-Scalping Logic (Natural Gas, Crude, Gold, Silver)
        mcx_segs = ["CRUDEOIL", "NATURALGAS", "NATGASMINI", "GOLD", "GOLDM", "GOLDGUINEA", "SILVER", "SILVERM", "SILVERMIC"]
        
        if symbol in mcx_segs:
            # Commodities move in small points but high value.
            # Book quick at 0.5 - 1.0 point move
            sl = round(entry - 1.5, 2)   # 1.5 points SL
            t1 = round(entry + 0.5, 2)   # T1: Quick Scalp @ 0.5 pts
            t2 = round(entry + 2.0, 2)   # T2: Runner @ 2.0 pts
            return max(0.5, sl), [t1, t2]

        if entry <= 30:
            # Micro/OTM: tight SL, small achievable targets
            sl = round(entry - max(5.0, entry * 0.25), 2)
            t1 = round(entry + 8.0, 2)
            t2 = round(entry + 15.0, 2)
        elif entry <= 100:
            # Normal: moderate SL, decent targets
            sl = round(entry - max(10.0, entry * 0.20), 2)
            t1 = round(entry + 15.0, 2)
            t2 = round(entry + 30.0, 2)
        else:
            # High premium: original rule
            sl = round(entry - max(15.0, entry * 0.20), 2)
            t1 = round(entry + 30.0, 2)
            t2 = round(entry + 60.0, 2)

        sl = max(0.5, sl)  # Never go below ₹0.5
        return sl, [t1, t2]

    def check_exit(self, pos:Position, current_premium:float,
                   smc_choch:Optional[str]=None) -> dict:
        """
        Req 5.1: Priority order check
        Returns {action, pct, reason}
        """
        now = time.time()

        # 0. ABSOLUTE PROFIT BOOKING (User Req: Book at ₹100 profit)
        current_pnl = (current_premium - pos.entry) * pos.qty_remaining
        if current_pnl >= 100:
            return {"action":"EXIT","pct":100,"reason":"PROFIT_TARGET_100"}

        # Track momentum
        move = abs(current_premium - pos.last_move_price)
        if move / max(pos.last_move_price, 0.01) * 100 > self.MOMENTUM_MIN_PCT:
            pos.last_move_price = current_premium
            pos.last_move_time  = now

        # 1. SL_HIT (Req 5.2)
        if current_premium <= pos.sl:
            return {"action":"EXIT","pct":100,"reason":"SL_HIT"}

        # 2. CHOCH (Req 5.3)
        if smc_choch:
            if pos.option_type == "CE" and smc_choch == "bearish":
                return {"action":"EXIT","pct":100,"reason":"CHOCH_BEARISH"}
            if pos.option_type == "PE" and smc_choch == "bullish":
                return {"action":"EXIT","pct":100,"reason":"CHOCH_BULLISH"}

        # 3. TARGET_T2
        if len(pos.targets) >= 2 and current_premium >= pos.targets[1] and pos.booked_level < 2:
            pos.booked_level = 2
            pos.partial_booked = True
            # Move SL to T1
            if pos.sl < pos.targets[0]:
                pos.sl = pos.targets[0]
            return {"action":"PARTIAL","pct":30,"reason":"TARGET_T2"}

        # 4. TARGET_T1
        if pos.targets and current_premium >= pos.targets[0] and pos.booked_level < 1:
            pos.booked_level = 1
            pos.partial_booked = True
            # Move SL to Break-even
            if pos.sl < pos.entry:
                pos.sl = pos.entry
            return {"action":"PARTIAL","pct":30,"reason":"TARGET_T1"}
            
        # 4.5 COST LOCKING (1:1 Reward Hit)
        if pos.booked_level == 0:
            initial_risk = pos.entry - pos.sl
            if initial_risk > 0:
                current_profit = current_premium - pos.entry
                if current_profit >= initial_risk:
                    pos.sl = pos.entry # Move to Break-even
                    pos.booked_level = 0.5 # Marking as cost-locked
                    logger.info(f"COST-LOCKING: {pos.option_symbol} SL moved to Break-even (₹{pos.entry})")
                    return {"action":"HOLD","pct":0,"reason":"COST_LOCK_BREAK_EVEN"}

        # Advanced TSL Logic (Runner Trailing)
        # Micro OTM: trail every ₹2 | Normal: trail every ₹5
        if pos.booked_level > 0 and pos.targets:
            highest_mark = pos.last_move_price
            if highest_mark > pos.targets[0]:
                points_above = highest_mark - pos.targets[0]
                if pos.entry <= 30:
                    # Micro/OTM: tight trail every ₹2
                    trail_step = 2
                    trail_base = pos.entry
                else:
                    # Normal: trail every ₹5
                    trail_step = 5
                    trail_base = pos.entry
                trail_steps = int(points_above / trail_step)
                new_sl = trail_base + (trail_steps * trail_step)
                if new_sl > pos.sl:
                    pos.sl = new_sl
                    logger.info(
                        f"TSL updated: {pos.option_symbol} SL={new_sl:.1f} "
                        f"(step=₹{trail_step}, above_T1={points_above:.1f})"
                    )

        # 5. MOMENTUM_LOST (Req 5.6)
        in_profit = current_premium > pos.entry
        stale = (now - pos.last_move_time) >= self.MOMENTUM_WINDOW
        if stale and in_profit:
            return {"action":"EXIT","pct":100,"reason":"MOMENTUM_LOST"}

        return {"action":"HOLD","pct":0,"reason":"HOLD"}

    def calc_pnl(self, pos:Position, exit_price:float, qty:int) -> float:
        # Since we are BUYING options (both CE and PE), profit is always exit - entry
        return (exit_price - pos.entry) * qty
