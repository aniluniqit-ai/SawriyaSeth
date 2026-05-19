"""
Candlestick Analyzer — LKS WealthTech V21
Institutional 3-Candle Pattern Recognition
+ Next-Candle Entry & Trail SL Logic (Req: Candle-Based Entry)
"""
import time, logging
from typing import List, Dict, Optional

logger = logging.getLogger("Candlestick")

class Candle:
    def __init__(self, open_price: float):
        self.open  = open_price
        self.high  = open_price
        self.low   = open_price
        self.close = open_price
        self.tick_count = 1
        self.is_closed = False
        self.markers = []

    def update(self, price: float):
        if price > self.high: self.high = price
        if price < self.low:  self.low = price
        self.close = price
        self.tick_count += 1

    def is_bullish(self) -> bool:
        return self.close > self.open

    def is_bearish(self) -> bool:
        return self.close < self.open

    def body_size(self) -> float:
        return abs(self.close - self.open)

    def is_momentum_candle(self, index_price: float, threshold_pct: float = 0.03) -> bool:
        """Check if candle has strong momentum body >= threshold_pct% of index price."""
        if index_price <= 0:
            return False
        min_body = index_price * threshold_pct / 100
        return self.body_size() >= min_body

    def is_doji(self) -> bool:
        """Small body = indecision / reversal signal."""
        total_range = self.high - self.low
        if total_range == 0:
            return True
        return self.body_size() / total_range < 0.2

    def is_reversal_against(self, option_type: str) -> bool:
        """
        Returns True if this candle suggests a reversal against current trade:
        - CE trade (expecting up): reversal = bearish candle
        - PE trade (expecting down): reversal = bullish candle
        """
        if option_type == "CE":
            return self.is_bearish() and not self.is_doji()
        else:  # PE
            return self.is_bullish() and not self.is_doji()

    def is_continuation(self, option_type: str) -> bool:
        """
        Returns True if candle confirms trend continuation:
        - CE: next candle is bullish
        - PE: next candle is bearish
        """
        if option_type == "CE":
            return self.is_bullish()
        else:
            return self.is_bearish()


class InstitutionalCandleEngine:
    """Builds 1-min candles from live ticks and detects advanced 3-candle patterns."""
    
    def __init__(self, segment: str = "UNKNOWN", timeframe_seconds: int = 60):
        self.segment = segment
        self.tf_sec = timeframe_seconds
        self.candles: List[Candle] = []
        self.current_candle: Candle = None
        self.candle_start_time = 0

    def feed_price(self, price: float):
        now = time.time()
        
        # Start first candle
        if not self.current_candle:
            self.current_candle = Candle(price)
            self.candle_start_time = now
            return

        # Close current candle and start new one
        if now - self.candle_start_time >= self.tf_sec:
            self.current_candle.is_closed = True
            self.candles.append(self.current_candle)
            self._save_candle_to_csv(self.current_candle, self.candle_start_time)
            
            # Keep last 100 candles for dashboard chart and memory
            if len(self.candles) > 100:
                self.candles.pop(0)
                
            self.current_candle = Candle(price)
            self.candle_start_time = now
        else:
            self.current_candle.update(price)

    def get_atr(self, period: int = 14) -> float:
        """Calculate Average True Range (ATR) over the last N candles."""
        if len(self.candles) < period:
            # Fallback: simple range of last available candles
            if not self.candles: return 0.0
            ranges = [c.high - c.low for c in self.candles]
            return sum(ranges) / len(ranges)
        
        # Calculate True Ranges
        true_ranges = []
        for i in range(len(self.candles) - period, len(self.candles)):
            c = self.candles[i]
            prev_close = self.candles[i-1].close if i > 0 else c.open
            tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
            true_ranges.append(tr)
        
        return sum(true_ranges) / period

    def _save_candle_to_csv(self, c: Candle, timestamp: float):
        import os, csv
        from datetime import datetime
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            time_str = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
            csv_file = f"logs/candles_{today}.csv"
            file_exists = os.path.exists(csv_file)
            with open(csv_file, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["Time", "Segment", "Open", "High", "Low", "Close", "Bullish", "Doji"])
                writer.writerow([
                    time_str, self.segment,
                    round(c.open, 2), round(c.high, 2), round(c.low, 2), round(c.close, 2),
                    c.is_bullish(), c.is_doji()
                ])
        except Exception as e:
            logger.error(f"Failed to save candle: {e}")

    def analyze_patterns(self) -> str:
        """Returns the detected pattern name, or 'None'."""
        if len(self.candles) < 3:
            return "None"

        c1 = self.candles[-3]
        c2 = self.candles[-2]
        c3 = self.candles[-1]

        # Morning Star (Bullish Reversal)
        if c1.is_bearish() and c1.body_size() > 0:
            if c2.body_size() < (c1.body_size() * 0.3): # Doji/Small body
                if c3.is_bullish() and c3.close > (c1.open + c1.close) / 2:
                    return "BULLISH_MORNING_STAR"

        # Evening Star (Bearish Reversal)
        if c1.is_bullish() and c1.body_size() > 0:
            if c2.body_size() < (c1.body_size() * 0.3):
                if c3.is_bearish() and c3.close < (c1.open + c1.close) / 2:
                    return "BEARISH_EVENING_STAR"

        # Three White Soldiers (Strong Bullish Momentum)
        if c1.is_bullish() and c2.is_bullish() and c3.is_bullish():
            if c2.close > c1.close and c3.close > c2.close:
                if c1.body_size() > 0 and c2.body_size() > 0 and c3.body_size() > 0:
                    return "STRONG_BULLISH_3_SOLDIERS"

        # Three Black Crows (Strong Bearish Momentum)
        if c1.is_bearish() and c2.is_bearish() and c3.is_bearish():
            if c2.close < c1.close and c3.close < c2.close:
                if c1.body_size() > 0 and c2.body_size() > 0 and c3.body_size() > 0:
                    return "STRONG_BEARISH_3_CROWS"

        # Bullish Engulfing (Predicts Bullish Next)
        if c2.is_bearish() and c3.is_bullish() and c3.body_size() > c2.body_size():
            if c3.close > c2.open and c3.open <= c2.close:
                return "BULLISH_ENGULFING"

        # Bearish Engulfing (Predicts Bearish Next)
        if c2.is_bullish() and c3.is_bearish() and c3.body_size() > c2.body_size():
            if c3.close < c2.open and c3.open >= c2.close:
                return "BEARISH_ENGULFING"
                
        # Hammer (Bullish Reversal Prediction)
        c3_range = c3.high - c3.low
        if c3_range > 0 and c3.is_bullish():
            lower_wick = min(c3.open, c3.close) - c3.low
            if lower_wick > (c3.body_size() * 2) and (c3.high - c3.close) < (c3.body_size() * 0.5):
                return "BULLISH_HAMMER"

        # Shooting Star (Bearish Reversal Prediction)
        if c3_range > 0 and c3.is_bearish():
            upper_wick = c3.high - max(c3.open, c3.close)
            if upper_wick > (c3.body_size() * 2) and (c3.close - c3.low) < (c3.body_size() * 0.5):
                return "BEARISH_SHOOTING_STAR"

        return "None"


class NextCandleAnalyzer:
    """
    Candle-based entry + next candle trail SL system.

    Logic:
    1. Entry: current candle is momentum candle (body >= 0.03% of index)
    2. Next candle analysis (after that candle closes):
       - Reversal pattern  -> EXIT
       - Continuation      -> Trail SL to prev candle Low (CE) or High (PE)
       - Weak / Doji       -> Hold, SL same rahega
    """

    def __init__(self, segment: str = "UNKNOWN", timeframe_seconds: int = 60):
        self.engine = InstitutionalCandleEngine(segment, timeframe_seconds)
        self.entry_candle_index: Optional[int] = None

    def feed_price(self, price: float):
        self.engine.feed_price(price)

    def should_enter(self, option_type: str, index_price: float,
                     threshold_pct: float = 0.05) -> dict:
        """
        Check if current live candle justifies entry.
        Returns: {enter: bool, reason: str}
        """
        cur = self.engine.current_candle
        if not cur:
            return {"enter": False, "reason": "No candle data yet"}

        # Check for 3 consecutive same-color candles
        all_candles = self.engine.candles + [cur]
        last_three = all_candles[-3:]
        
        three_green = len(last_three) == 3 and all(c.is_bullish() for c in last_three)
        three_red = len(last_three) == 3 and all(c.is_bearish() for c in last_three)

        # Check for Predictive Patterns (Engulfing, Hammer, Star, etc.)
        pattern = self.engine.analyze_patterns()
        pattern_match = False
        if option_type == "CE" and "BULLISH" in pattern:
            pattern_match = True
        elif option_type == "PE" and "BEARISH" in pattern:
            pattern_match = True

        # Must be a momentum candle OR 3 consecutive candles OR a predictive pattern
        is_mom = cur.is_momentum_candle(index_price, threshold_pct)
        
        if not is_mom and not (option_type == "CE" and three_green) and not (option_type == "PE" and three_red) and not pattern_match:
            body = cur.body_size()
            min_needed = index_price * threshold_pct / 100
            return {
                "enter": False,
                "reason": f"No Momentum ({body:.1f} < {min_needed:.1f}) & No Pattern Detected"
            }

        # Direction must match option type (Relaxed if Pattern Match predicts reversal)
        if not pattern_match:
            if option_type == "CE" and not cur.is_bullish():
                return {"enter": False, "reason": "Candle bearish — CE entry blocked"}
            if option_type == "PE" and not cur.is_bearish():
                return {"enter": False, "reason": "Candle bullish — PE entry blocked"}

        # Record entry candle position — MUST wait for NEW candles after this
        # entry_candle_index = number of CLOSED candles at time of entry
        self.entry_candle_index = len(self.engine.candles)
        
        entry_reason = "Momentum candle"
        if pattern_match: entry_reason = f"Predictive Pattern: {pattern}"
        elif three_green or three_red: entry_reason = "3 Consecutive Candles"
        
        logger.info(
            f"[NextCandleAnalyzer] ENTRY: {option_type} | Reason: {entry_reason} | "
            f"Waiting for candle #{self.entry_candle_index + 1} to close before reversal exit."
        )
        return {
            "enter": True,
            "reason": entry_reason
        }

    def analyze_next_candle(self, option_type: str, current_sl: float) -> dict:
        """
        After the NEXT candle closes, decide: EXIT or TRAIL_SL or HOLD.
        Call this once per newly closed candle.

        Returns: {action: str, new_sl: float, reason: str}
          action = 'EXIT' | 'TRAIL_SL' | 'HOLD'
        """
        if len(self.engine.candles) < 1:
            return {"action": "HOLD", "new_sl": current_sl, "reason": "No closed candle yet"}

        # ── CRITICAL FIX: Minimum 1 NEW candle must close AFTER entry ──────────
        # Without this, system was exiting on same candle as entry (₹0 P&L bug)
        if self.entry_candle_index is not None:
            new_candles_since_entry = len(self.engine.candles) - self.entry_candle_index
            if new_candles_since_entry < 1:
                return {
                    "action": "HOLD",
                    "new_sl": current_sl,
                    "reason": f"Entry candle still open — waiting for next candle (need 1 new, have {new_candles_since_entry})"
                }

        next_c = self.engine.candles[-1]  # Most recently closed candle

        # --- REVERSAL? → EXIT ---
        if next_c.is_reversal_against(option_type):
            reason = (
                f"Next candle REVERSAL: {'Bearish' if next_c.is_bearish() else 'Bullish'} "
                f"| O={next_c.open:.1f} C={next_c.close:.1f}"
            )
            logger.info(f"[NextCandleAnalyzer] EXIT: {reason}")
            return {"action": "EXIT", "new_sl": current_sl, "reason": reason}

        # --- DOJI? → HOLD (no SL change) ---
        if next_c.is_doji():
            logger.info("[NextCandleAnalyzer] DOJI — HOLD, SL unchanged")
            return {
                "action": "HOLD", "new_sl": current_sl,
                "reason": "Doji/Indecision candle — waiting for clarity"
            }

        # --- CONTINUATION? → TRAIL SL ---
        if next_c.is_continuation(option_type):
            if option_type == "CE":
                # CE: Trail SL to this candle's Low (protect profits going up)
                new_sl = max(current_sl, next_c.low)
            else:
                # PE: Trail SL to this candle's High (protect profits going down)
                new_sl = min(current_sl, next_c.high) if current_sl > 0 else next_c.high

            reason = (
                f"CONTINUATION — Trail SL: {current_sl:.1f} → {new_sl:.1f} "
                f"({'Bull' if next_c.is_bullish() else 'Bear'} | "
                f"Low={next_c.low:.1f} High={next_c.high:.1f})"
            )
            logger.info(f"[NextCandleAnalyzer] TRAIL_SL: {reason}")
            return {"action": "TRAIL_SL", "new_sl": new_sl, "reason": reason}

        return {"action": "HOLD", "new_sl": current_sl, "reason": "Unclear candle — holding"}

    def get_current_candle_info(self) -> dict:
        """Debug / dashboard info about current live candle."""
        cur = self.engine.current_candle
        if not cur:
            return {}
        return {
            "open": cur.open,
            "high": cur.high,
            "low": cur.low,
            "close": cur.close,
            "body": round(cur.body_size(), 2),
            "bullish": cur.is_bullish(),
            "doji": cur.is_doji(),
            "closed_candles": len(self.engine.candles),
        }
