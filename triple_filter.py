"""
Triple Filter Entry System — LKS WealthTech V21
Requirement 3: EMA50 trend + EMA9/21 momentum + RSI zone
"""
import logging
from dataclasses import dataclass
from typing import Optional
logger = logging.getLogger("TripleFilter")

WARMUP_TICKS = 20  # Reduced from 50 → 20 for faster market readiness

@dataclass
class FilterResult:
    passed: bool
    action: str   # BUY_CE / BUY_PE / HOLD
    reason: str
    ema9:   float = 0
    ema21:  float = 0
    ema50:  float = 0
    rsi:    float = 50
    ticks:  int   = 0

class TripleFilterSystem:
    """One instance per segment (Req 3.7)"""

    def __init__(self, segment:str):
        self.segment = segment
        self.prices  = []
        self.ema9    = 0.0
        self.ema21   = 0.0
        self.ema50   = 0.0
        self.rsi     = 50.0
        self._gains  = []
        self._losses = []
        self._rsi_period = 14
        self.ticks   = 0
        self._seeded9 = self._seeded21 = self._seeded50 = False

    def _sma(self, n:int) -> float:
        if len(self.prices) < n: return 0
        return sum(self.prices[-n:]) / n

    def _update_ema(self, price:float):
        """Req 3.6: Incremental EMA with SMA seed"""
        k9 = 2/(9+1); k21 = 2/(21+1); k50 = 2/(50+1)
        if not self._seeded9 and len(self.prices) >= 9:
            self.ema9 = self._sma(9); self._seeded9 = True
        elif self._seeded9:
            self.ema9 = price*k9 + self.ema9*(1-k9)

        if not self._seeded21 and len(self.prices) >= 21:
            self.ema21 = self._sma(21); self._seeded21 = True
        elif self._seeded21:
            self.ema21 = price*k21 + self.ema21*(1-k21)

        if not self._seeded50 and len(self.prices) >= 50:
            self.ema50 = self._sma(50); self._seeded50 = True
        elif self._seeded50:
            self.ema50 = price*k50 + self.ema50*(1-k50)

    def _update_rsi(self, price:float):
        if len(self.prices) < 2: return
        chg = price - self.prices[-2]
        gain = max(0, chg); loss = abs(min(0, chg))
        self._gains.append(gain); self._losses.append(loss)
        if len(self._gains) > self._rsi_period:
            self._gains.pop(0); self._losses.pop(0)
        avg_g = sum(self._gains)/max(1,len(self._gains))
        avg_l = sum(self._losses)/max(1,len(self._losses))
        if avg_l == 0: self.rsi = 100
        else: self.rsi = 100 - (100/(1+avg_g/avg_l))

    def feed(self, price:float):
        self.prices.append(price)
        if len(self.prices) > 200: self.prices.pop(0)
        self._update_ema(price)
        self._update_rsi(price)
        self.ticks += 1

    def check(self, signal_type:str="CE") -> FilterResult:
        """Req 3.1–3.5: All three filters"""
        base = FilterResult(False,"HOLD","",self.ema9,self.ema21,self.ema50,self.rsi,self.ticks)

        # Req 3.1: warmup
        if self.ticks < WARMUP_TICKS:
            base.reason = f"Warmup {self.ticks}/{WARMUP_TICKS}"
            return base

        price = self.prices[-1]

        # Req 3.2: Filter 1 — EMA50 trend
        f1_bull = price > self.ema50
        f1_bear = price < self.ema50

        # Req 3.3: Filter 2 — EMA9/21 momentum
        f2_bull = self.ema9 > self.ema21
        f2_bear = self.ema9 < self.ema21

        # Req 3.4: Filter 3 — RSI zone
        f3_ce = 40 <= self.rsi <= 65
        f3_pe = 35 <= self.rsi <= 60

        reasons = []

        # Req 3.5: BUY_CE needs all bullish; BUY_PE all bearish
        if signal_type == "CE":
            if f1_bull and f2_bull and f3_ce:
                return FilterResult(True,"BUY_CE",
                    f"EMA50✅ MOM✅ RSI{self.rsi:.0f}✅",
                    self.ema9,self.ema21,self.ema50,self.rsi,self.ticks)
            else:
                fails=[]
                if not f1_bull: fails.append(f"Price<EMA50({self.ema50:.0f})")
                if not f2_bull: fails.append(f"EMA9<EMA21")
                if not f3_ce:   fails.append(f"RSI{self.rsi:.0f} not 40-65")
                return FilterResult(False,"HOLD",", ".join(fails),
                    self.ema9,self.ema21,self.ema50,self.rsi,self.ticks)
        else:  # PE
            if f1_bear and f2_bear and f3_pe:
                return FilterResult(True,"BUY_PE",
                    f"EMA50✅ MOM✅ RSI{self.rsi:.0f}✅",
                    self.ema9,self.ema21,self.ema50,self.rsi,self.ticks)
            else:
                fails=[]
                if not f1_bear: fails.append(f"Price>EMA50({self.ema50:.0f})")
                if not f2_bear: fails.append(f"EMA9>EMA21")
                if not f3_pe:   fails.append(f"RSI{self.rsi:.0f} not 35-60")
                return FilterResult(False,"HOLD",", ".join(fails),
                    self.ema9,self.ema21,self.ema50,self.rsi,self.ticks)

    def get_status(self) -> dict:
        return {
            "segment":  self.segment,
            "ticks":    self.ticks,
            "warmed_up":self.ticks >= WARMUP_TICKS,
            "warmup_pct":min(100, int(self.ticks/WARMUP_TICKS*100)),
            "ema9":     round(self.ema9,2),
            "ema21":    round(self.ema21,2),
            "ema50":    round(self.ema50,2),
            "rsi":      round(self.rsi,2),
            "price":    round(self.prices[-1],2) if self.prices else 0,
        }
