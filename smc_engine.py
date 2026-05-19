"""
SMC Engine — LKS WealthTech V21
Requirement 4: Swing highs/lows, BOS, CHOCH, Market Structure
"""
import logging
from typing import List, Optional
from dataclasses import dataclass
logger = logging.getLogger("SMC")

@dataclass
class SMCState:
    structure:    str  = "SIDEWAYS"   # BULLISH / BEARISH / SIDEWAYS
    last_swing_high: float = 0
    last_swing_low:  float = 999999
    bos_up:   bool = False
    bos_down: bool = False
    choch:    Optional[str] = None    # "bullish" / "bearish"
    prev_structure: str = "SIDEWAYS"

class SMCEngine:
    """Req 4.1–4.5"""

    def __init__(self, lookback:int=5):
        self.lookback = lookback
        self.candles:  List[float] = []
        self.state = SMCState()

    def feed_price(self, price:float):
        self.candles.append(price)
        if len(self.candles) > 200: self.candles.pop(0)
        if len(self.candles) >= self.lookback * 2 + 1:
            self._update()

    def _find_swing_high(self) -> float:
        lb = self.lookback
        c  = self.candles
        highs = []
        for i in range(lb, len(c)-lb):
            if c[i] == max(c[i-lb:i+lb+1]):
                highs.append(c[i])
        return max(highs) if highs else (max(self.candles) if self.candles else 0)

    def _find_swing_low(self) -> float:
        lb = self.lookback
        c  = self.candles
        lows = []
        for i in range(lb, len(c)-lb):
            if c[i] == min(c[i-lb:i+lb+1]):
                lows.append(c[i])
        return min(lows) if lows else (min(self.candles) if self.candles else 999999)

    def _update(self):
        sh = self._find_swing_high()
        sl = self._find_swing_low()
        cur = self.candles[-1]
        prev_sh = self.state.last_swing_high
        prev_sl = self.state.last_swing_low
        self.state.last_swing_high = sh
        self.state.last_swing_low  = sl

        # Req 4.3: BOS
        self.state.bos_up   = cur > sh
        self.state.bos_down = cur < sl

        # Req 4.2: Market structure
        self.state.prev_structure = self.state.structure
        hh = sh > prev_sh; hl = sl > prev_sl
        lh = sh < prev_sh; ll = sl < prev_sl
        if hh and hl:   self.state.structure = "BULLISH"
        elif lh and ll: self.state.structure = "BEARISH"
        else:           self.state.structure = "SIDEWAYS"

        # Req 4.4: CHOCH
        self.state.choch = None
        if (self.state.prev_structure == "BULLISH" and
                self.state.structure == "BEARISH"):
            self.state.choch = "bearish"
            logger.info("CHOCH: BULLISH→BEARISH")
        elif (self.state.prev_structure == "BEARISH" and
              self.state.structure == "BULLISH"):
            self.state.choch = "bullish"
            logger.info("CHOCH: BEARISH→BULLISH")

    def bos_confirmed(self, option_type:str) -> bool:
        """Req 4.5: BOS confirmation before order"""
        if option_type == "CE": return self.state.bos_up
        return self.state.bos_down

    def get_status(self) -> dict:
        return {
            "structure":       self.state.structure,
            "swing_high":      round(self.state.last_swing_high, 2),
            "swing_low":       round(self.state.last_swing_low, 2),
            "bos_up":          self.state.bos_up,
            "bos_down":        self.state.bos_down,
            "choch":           self.state.choch,
            "prev_structure":  self.state.prev_structure,
        }
