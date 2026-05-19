"""
Previous Day Levels Engine — LKS WealthTech V21
Master Combo Scalping Plan: PDH / PDL / PDC detection
- Previous Day High (PDH) = Resistance → Breakout = CE signal
- Previous Day Low  (PDL) = Support   → Breakdown = PE signal
- Previous Day Close (PDC) = Bias reference
"""
import logging
from datetime import datetime, date, time as dtime
from typing import Dict, Optional

logger = logging.getLogger("PrevDayLevels")


class PrevDayLevels:
    """
    Per-segment previous day H/L/C tracking.
    Automatically rolls over at 9:15 AM each new trading day.
    """

    def __init__(self):
        self._data: Dict[str, dict] = {}

    def _default(self) -> dict:
        return {
            "pdh":         0.0,   # Previous Day High
            "pdl":         0.0,   # Previous Day Low
            "pdc":         0.0,   # Previous Day Close
            "today_high":  0.0,
            "today_low":   float("inf"),
            "mark_date":   None,
            "breakout_ce": False, # PDH breakout already triggered
            "breakout_pe": False, # PDL breakdown already triggered
        }

    def _get(self, segment: str) -> dict:
        if segment not in self._data:
            self._data[segment] = self._default()
        return self._data[segment]

    def _rollover(self, segment: str):
        """
        At market start (9:15 AM) of a new day, promote today's H/L/C
        to become the previous day's levels and reset today's tracking.
        """
        d = self._get(segment)
        today = date.today()

        if d["mark_date"] == today:
            return  # Already reset for today

        # First time ever — no previous day data yet
        if d["mark_date"] is None:
            d["mark_date"]   = today
            d["today_high"]  = 0.0
            d["today_low"]   = float("inf")
            logger.info(f"[PDL] {segment}: First run — waiting to build today's H/L")
            return

        # Roll previous day
        if d["today_high"] > 0 and d["today_low"] < float("inf"):
            d["pdh"] = round(d["today_high"], 2)
            d["pdl"] = round(d["today_low"],  2)
            d["pdc"] = round(d["today_high"] - (d["today_high"] - d["today_low"]) * 0.5, 2)
            # Use a better close approximation: last fed price (we'll update this separately)
        d["today_high"]  = 0.0
        d["today_low"]   = float("inf")
        d["mark_date"]   = today
        d["breakout_ce"] = False
        d["breakout_pe"] = False
        logger.info(
            f"[PDL] {segment} rolled over → PDH={d['pdh']}, PDL={d['pdl']}, PDC={d['pdc']}"
        )

    def set_previous_day(self, segment: str, pdh: float, pdl: float, pdc: float):
        """
        Manually set previous day levels (call once at startup from API/config).
        Useful when you have exact OHLC from broker.
        """
        d = self._get(segment)
        d["pdh"] = round(pdh, 2)
        d["pdl"] = round(pdl, 2)
        d["pdc"] = round(pdc, 2)
        d["mark_date"] = date.today()
        logger.info(f"[PDL] {segment} levels set manually: PDH={pdh}, PDL={pdl}, PDC={pdc}")

    def feed_price(self, segment: str, price: float):
        """Called on every price tick to track today's intraday range."""
        if price <= 0:
            return

        now = datetime.now().time()
        # Rollover happens at market start
        if now >= dtime(9, 15):
            self._rollover(segment)

        d = self._get(segment)

        # Track today's high/low intraday
        if price > d["today_high"]:
            d["today_high"] = price
        if price < d["today_low"]:
            d["today_low"] = price

        # Also keep running PDC as last-seen price (end of day this will be close)
        # Only during market close window (after 3 PM) update PDC
        if now >= dtime(15, 0):
            d["pdc"] = round(price, 2)

    def check_breakout(self, segment: str, price: float) -> Optional[str]:
        """
        Returns 'CE' if price broke above PDH (bullish breakout),
        Returns 'PE' if price broke below PDL (bearish breakdown),
        Returns None if inside range.
        """
        d = self._get(segment)
        if not d["pdh"] or not d["pdl"]:
            return None  # No previous day data yet

        margin = 0.1  # 0.1% buffer to confirm breakout

        # PDH Breakout → CE
        if not d["breakout_ce"] and price > d["pdh"] * (1 + margin / 100):
            d["breakout_ce"] = True
            logger.info(f"[PDL] {segment} PDH BREAKOUT: {price:.0f} > {d['pdh']:.0f} → CE")
            return "CE"

        # PDL Breakdown → PE
        if not d["breakout_pe"] and price < d["pdl"] * (1 - margin / 100):
            d["breakout_pe"] = True
            logger.info(f"[PDL] {segment} PDL BREAKDOWN: {price:.0f} < {d['pdl']:.0f} → PE")
            return "PE"

        return None

    def get_bias(self, segment: str, price: float) -> str:
        """
        Price vs PDC bias:
        Price > PDC → BULLISH (lean CE)
        Price < PDC → BEARISH (lean PE)
        """
        d = self._get(segment)
        if not d["pdc"] or price <= 0:
            return "NEUTRAL"
        if price > d["pdc"]:
            return "BULLISH"
        if price < d["pdc"]:
            return "BEARISH"
        return "NEUTRAL"

    def get_status(self, segment: str) -> dict:
        d = self._get(segment)
        return {
            "pdh":      d["pdh"],
            "pdl":      d["pdl"],
            "pdc":      d["pdc"],
            "bias":     self.get_bias(segment, d["today_high"]),
            "today_high": round(d["today_high"], 2),
            "today_low":  round(d["today_low"] if d["today_low"] < float("inf") else 0, 2),
            "breakout_ce": d["breakout_ce"],
            "breakout_pe": d["breakout_pe"],
        }

    def get_all_status(self) -> dict:
        return {seg: self.get_status(seg) for seg in self._data}
