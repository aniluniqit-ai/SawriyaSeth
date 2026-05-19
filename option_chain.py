"""
Option Chain Module — LKS WealthTech V21
Req 1: Budget Guard + Option Chain
NEW: OI Analysis Engine + PCR + Expiry Day Detection + Range Breakout
"""
import time, logging
from datetime import datetime, date, time as dtime
from typing import Optional, Dict
logger = logging.getLogger("OptionChain")

LOT_SIZES = {
    # Index Options (NSE/BSE)
    "NIFTY":      25,
    "BANKNIFTY":  15,
    "SENSEX":     10,
    "FINNIFTY":   25,
    "MIDCPNIFTY": 50,
    "BANKEX":     15,
    # MCX Commodity Options
    "CRUDEOIL":   100,    # 100 barrels per lot
    "NATURALGAS": 1250,   # 1250 mmBtu per lot
    # Stock Options (NSE)
    "RELIANCE":   250,
    "HDFCBANK":   550,
    "ICICIBANK":  700,
    "TATAMOTORS": 1425,
    "SBIN":       1500,
    "INFY":       400,
}

# Expiry day per segment (weekday: 0=Mon,1=Tue,2=Wed,3=Thu,4=Fri)
# Stocks = Last Thursday of the month (handled as -1 for weekday check)
EXPIRY_DAYS = {
    "FINNIFTY":   1,   # Tuesday (Kotak logic fix: 1=Tue)
    "NIFTY":      3,   # Thursday
    "BANKNIFTY":  2,   # Wednesday (recent NSE change)
    "SENSEX":     4,   # Friday
    "MIDCPNIFTY": 0,   # Monday
    "BANKEX":     0,   # Monday
    "CRUDEOIL":   -1,
    "NATURALGAS": -1,
    "RELIANCE":   -1,
    "HDFCBANK":   -1,
    "ICICIBANK":  -1,
}


# ── Expiry Day Helper ──────────────────────────────────────────
def is_expiry_day(segment: str) -> bool:
    """Returns True if today is expiry day for the given segment."""
    today_weekday = datetime.now().weekday()
    return EXPIRY_DAYS.get(segment, -1) == today_weekday


def expiry_trading_phase(segment: str = "NIFTY") -> str:
    """
    Expiry Day Master Plan phases:
      AVOID_MORNING   → 9:15–11:00 fake moves
      AVOID_MIDDAY    → 11:30–13:30 sideways
      RANGE_MARKING   → 13:15–13:30 mark the range
      BREAKOUT_WINDOW → 13:30–15:20 real game
      CLOSED          → rest
    """
    if not is_expiry_day(segment):
        return "NORMAL"
    now = datetime.now().time()
    if dtime(9, 15) <= now < dtime(11, 0):
        return "AVOID_MORNING"
    if dtime(11, 0) <= now < dtime(13, 15):
        return "AVOID_MIDDAY"
    if dtime(13, 15) <= now < dtime(13, 30):
        return "RANGE_MARKING"
    if dtime(13, 30) <= now <= dtime(15, 20):
        return "BREAKOUT_WINDOW"
    return "CLOSED"


# ── OI Analysis Engine ─────────────────────────────────────────
class OIAnalysisEngine:
    """
    Option Chain Master Strategy — OI, OI Change, PCR.

    OI Change Signal:
      Price↑ + OI↑  → STRONG_UPTREND   → BUY CE ✅
      Price↓ + OI↑  → STRONG_DOWNTREND → BUY PE ✅
      Price↑ + OI↓  → SHORT_COVERING   → Weak CE
      Price↓ + OI↓  → LONG_UNWINDING   → Weak PE

    PCR:
      >1.2  → Bullish (bears trapped)
      <0.8  → Bearish (bulls trapped)
      else  → Neutral

    Support / Resistance:
      Max Put OI strike  → Support
      Max Call OI strike → Resistance
    """

    def __init__(self):
        self._data: Dict[str, dict] = {}

    def update(self, segment: str, chain_data: dict, current_price: float):
        """Parse option chain and compute OI metrics."""
        if not chain_data:
            return

        strikes      = chain_data.get("data", {}).get("strikePrices", [])
        total_call_oi = 0.0
        total_put_oi  = 0.0
        max_call_oi   = 0.0
        max_put_oi    = 0.0
        resistance_strike = 0
        support_strike    = 0

        for s in strikes:
            c_oi   = s.get("CE", {}).get("oi", 0) or 0
            p_oi   = s.get("PE", {}).get("oi", 0) or 0
            strike = s.get("strikePrice", 0)

            total_call_oi += c_oi
            total_put_oi  += p_oi

            if c_oi > max_call_oi:
                max_call_oi = c_oi
                resistance_strike = strike   # Max Call OI = resistance

            if p_oi > max_put_oi:
                max_put_oi = p_oi
                support_strike = strike      # Max Put OI = support

        pcr = total_put_oi / total_call_oi if total_call_oi > 0 else 1.0

        prev          = self._data.get(segment, {})
        prev_total_oi = prev.get("call_oi", 0) + prev.get("put_oi", 0)
        prev_price    = prev.get("price", current_price)
        curr_total_oi = total_call_oi + total_put_oi

        # OI Change Signal
        oi_signal = "NEUTRAL"
        if curr_total_oi > 0 and prev_total_oi > 0:
            oi_up    = curr_total_oi > prev_total_oi
            price_up = current_price > prev_price
            price_dn = current_price < prev_price

            if price_up and oi_up:     oi_signal = "STRONG_UPTREND"
            elif price_dn and oi_up:   oi_signal = "STRONG_DOWNTREND"
            elif price_up and not oi_up: oi_signal = "SHORT_COVERING"
            elif price_dn and not oi_up: oi_signal = "LONG_UNWINDING"

        pcr_bias = "BULLISH" if pcr > 1.2 else ("BEARISH" if pcr < 0.8 else "NEUTRAL")

        self._data[segment] = {
            "call_oi":    total_call_oi,
            "put_oi":     total_put_oi,
            "pcr":        round(pcr, 3),
            "pcr_bias":   pcr_bias,
            "support":    support_strike,
            "resistance": resistance_strike,
            "oi_signal":  oi_signal,
            "price":      current_price,
        }

        logger.info(
            f"[OI] {segment} | PCR={pcr:.2f}({pcr_bias}) | "
            f"OI_Signal={oi_signal} | Support={support_strike} | Resist={resistance_strike}"
        )

    def get_trade_bias(self, segment: str) -> str:
        """
        Combined OI + PCR → CE / PE / NEUTRAL
        Strong signal:  OI Change confirms direction
        Weak signal:    PCR alone (avoid in sideways)
        """
        d    = self._data.get(segment, {})
        sig  = d.get("oi_signal", "NEUTRAL")
        pcr  = d.get("pcr_bias", "NEUTRAL")

        if sig == "STRONG_UPTREND":    return "CE"
        if sig == "STRONG_DOWNTREND":  return "PE"
        if pcr == "BULLISH" and sig != "LONG_UNWINDING":  return "CE"
        if pcr == "BEARISH" and sig != "SHORT_COVERING":  return "PE"
        return "NEUTRAL"

    def is_near_support(self, segment: str, price: float, margin_pct: float = 0.3) -> bool:
        support = self._data.get(segment, {}).get("support", 0)
        if not support: return False
        return abs(price - support) / price * 100 <= margin_pct

    def is_near_resistance(self, segment: str, price: float, margin_pct: float = 0.3) -> bool:
        resistance = self._data.get(segment, {}).get("resistance", 0)
        if not resistance: return False
        return abs(price - resistance) / price * 100 <= margin_pct

    def get_status(self, segment: str) -> dict:
        return self._data.get(segment, {
            "call_oi": 0, "put_oi": 0, "pcr": 1.0,
            "pcr_bias": "NEUTRAL", "oi_signal": "NEUTRAL",
            "support": 0, "resistance": 0
        })


# ── Expiry Day Range Breakout Engine ──────────────────────────
class ExpiryRangeEngine:
    """
    Expiry Day Master Plan (1:15–1:30 range, 1:30+ breakout):
    - Mark range high/low between 1:15–1:30
    - After 1:30: breakout above range → CE, below → PE
    - Target: ₹10–₹30 fast exit
    - Avoid deep OTM (₹2–₹5)
    """

    def __init__(self):
        self._ranges: Dict[str, dict] = {}

    def _reset_if_new_day(self, segment: str):
        today = date.today()
        r = self._ranges.get(segment, {})
        if r.get("mark_date") != today:
            self._ranges[segment] = {
                "range_high": 0.0,
                "range_low":  float("inf"),
                "marked":     False,
                "triggered":  False,
                "mark_date":  today,
            }

    def feed_price(self, segment: str, price: float):
        self._reset_if_new_day(segment)
        r   = self._ranges[segment]
        now = datetime.now().time()

        if dtime(13, 15) <= now <= dtime(13, 30):
            if price > r["range_high"]: r["range_high"] = price
            if price < r["range_low"]:  r["range_low"]  = price
        elif now > dtime(13, 30) and r["range_high"] > 0 and r["range_low"] < float("inf"):
            r["marked"] = True

    def check_breakout(self, segment: str, price: float) -> dict:
        """Returns {signal: 'CE'/'PE'/None, reason: str}"""
        self._reset_if_new_day(segment)
        r   = self._ranges[segment]
        now = datetime.now().time()

        if not (dtime(13, 30) <= now <= dtime(15, 20)):
            return {"signal": None, "reason": "Outside breakout window"}
        if not r.get("marked") or r.get("triggered"):
            return {"signal": None, "reason": "Range not ready"}

        rh = r["range_high"]
        rl = r["range_low"]

        if price > rh:
            r["triggered"] = True
            logger.info(f"[ExpiryRange] {segment} UP break: {price:.1f} > {rh:.1f} → CE")
            return {"signal": "CE", "reason": f"Expiry Range Break UP {price:.0f}>{rh:.0f}"}
        if price < rl:
            r["triggered"] = True
            logger.info(f"[ExpiryRange] {segment} DOWN break: {price:.1f} < {rl:.1f} → PE")
            return {"signal": "PE", "reason": f"Expiry Range Break DOWN {price:.0f}<{rl:.0f}"}

        return {"signal": None, "reason": f"Inside range [{rl:.0f}–{rh:.0f}]"}

    def get_range(self, segment: str) -> dict:
        r = self._ranges.get(segment, {})
        return {
            "high":      round(r.get("range_high", 0), 1),
            "low":       round(r.get("range_low", 0), 1),
            "marked":    r.get("marked", False),
            "triggered": r.get("triggered", False),
        }


# ── Option Chain Fetcher ───────────────────────────────────────
class OptionChainFetcher:
    CACHE_TTL  = 30   # seconds — reuse cached data longer
    MAX_RETRY  = 3    # retry attempts on empty response
    # MCX segments that use commodity option chains
    MCX_SEGMENTS = {"CRUDEOIL", "NATURALGAS"}

    def __init__(self, kotak_api=None):
        self.api    = kotak_api
        self._cache = {}

    def _mcx_market_open(self) -> bool:
        """MCX options trade 9 AM – 11:30 PM only."""
        now = datetime.now().time()
        return dtime(9, 0) <= now <= dtime(23, 30)

    def get_chain(self, segment: str, expiry: str = None) -> Optional[dict]:
        now = time.time()

        # MCX: silently skip if market closed — no error spam
        if segment in self.MCX_SEGMENTS and not self._mcx_market_open():
            return None

        # Return cached data if fresh enough
        if segment in self._cache:
            data, ts = self._cache[segment]
            if now - ts < self.CACHE_TTL:
                return data

        if not self.api or not self.api.logged_in:
            return None

        # MCX gets 1 attempt only (different API format — no point retrying)
        max_tries = 1 if segment in self.MCX_SEGMENTS else self.MAX_RETRY

        for attempt in range(max_tries):
            try:
                url    = f"{self.api.base_url}/market-data/1.0/option-chain"
                params = {"segment": segment}
                if expiry:
                    params["expiry"] = expiry
                r    = self.api._session.get(url, params=params,
                        headers=self.api._h(), timeout=10)
                
                if r.status_code != 200:
                    raise Exception(f"HTTP {r.status_code} {r.text.strip()[:100]}")

                text = r.text.strip()
                if not text:
                    if segment not in self.MCX_SEGMENTS:
                        logger.warning(f"Option chain {segment}: empty response (attempt {attempt+1})")
                        time.sleep(1)
                    return None
                data = r.json()
                self._cache[segment] = (data, now)
                return data
            except Exception as e:
                if segment not in self.MCX_SEGMENTS:
                    logger.error(f"Option chain fetch {segment} attempt {attempt+1}: {e}")
                    time.sleep(1)
                # MCX: silent fail — system continues without OI data

        # Return stale cache if all retries fail (NSE/BSE only)
        if segment in self._cache and segment not in self.MCX_SEGMENTS:
            logger.warning(f"Using stale cache for {segment} after {max_tries} failed retries")
            return self._cache[segment][0]
        return None


# ── Budget Guard (ATM-first selection) ────────────────────────
class BudgetGuard:
    """
    Req 1.3–1.6: Select affordable ATM/OTM strike.
    Master Strategy rules:
      - ATM = safest (spot ≈ strike)
      - Micro accounts (≤₹5000): 100% capital allowed, min_premium=5
      - Normal accounts: 60% capital, min_premium=15
      - SL base: ₹15–₹20 | Target: ₹30–₹60
      - Smart OTM fallback: if ATM unaffordable, go deeper automatically
    """

    def __init__(self, capital: float, cfg: dict):
        self.capital     = capital
        self.min_premium = cfg.get("min_premium", 15)   # no deep OTM
        self.max_premium = cfg.get("max_premium", 200)

    def update_capital(self, c: float):
        self.capital = c

    def _is_micro_account(self) -> bool:
        """Micro account = capital ≤ ₹10000. Different rules apply."""
        return self.capital <= 10000

    def select_strike(self, segment: str, option_type: str,
                      chain_data: dict, preferred_strike: int = None,
                      index_ltp: float = 0) -> Optional[dict]:
        lot = LOT_SIZES.get(segment, 25)
        micro = self._is_micro_account()

        # Micro account rules: 100% capital allowed
        if micro:
            eff_max     = self.capital / lot          # 100% for micro
            min_prem    = self.min_premium
        else:
            # For > 10000, use 80%
            eff_max     = min(self.max_premium, (self.capital * 0.80) / lot)
            min_prem    = self.min_premium

        logger.info(
            f"[BudgetGuard] {segment} {option_type} | micro={micro} | "
            f"capital=₹{self.capital:.0f} | lot={lot} | max_prem=₹{eff_max:.0f}"
        )

        if not chain_data:
            logger.warning("No chain data — skipping strike selection")
            return None

        strikes = chain_data.get("data", {}).get("strikePrices", [])

        # Find ATM strike (closest to index price)
        atm_strike = 0
        if index_ltp > 0 and strikes:
            atm_strike = min(
                (s.get("strikePrice", 0) for s in strikes),
                key=lambda x: abs(x - index_ltp)
            )

        # ── Preferred strike (from Telegram signal) ─────────────
        if preferred_strike and chain_data:
            for s in strikes:
                if s.get("strikePrice") == preferred_strike:
                    opt = s.get(option_type, {})
                    ltp = opt.get("ltp", 0)
                    cost = ltp * lot
                    if cost <= self.capital and ltp >= min_prem:
                        logger.info(f"✅ Preferred strike {preferred_strike} OK ltp={ltp} cost=₹{cost:.0f}")
                        return {"strike": preferred_strike, "ltp": ltp,
                                "oi": opt.get("oi", 0), "lot": lot}
                    else:
                        logger.info(
                            f"⚠️ Preferred strike {preferred_strike} too expensive "
                            f"(ltp={ltp}, cost=₹{cost:.0f} > ₹{self.capital:.0f}) — "
                            f"will try OTM fallback"
                        )
                    break

        # ── Collect affordable candidates ────────────────────────
        candidates = []
        for s in strikes:
            opt    = s.get(option_type, {})
            ltp    = opt.get("ltp", 0)
            oi     = opt.get("oi", 0)
            strike = s.get("strikePrice", 0)

            if min_prem <= ltp <= eff_max:
                atm_dist = abs(strike - atm_strike) if atm_strike else 99999
                candidates.append({
                    "strike":   strike,
                    "ltp":      ltp,
                    "oi":       oi,
                    "lot":      lot,
                    "atm_dist": atm_dist,
                })

        # ── Micro OTM fallback: relax min_premium to ₹10 ─────────
        if not candidates and micro:
            logger.warning(
                f"No strike in ₹{min_prem}–₹{eff_max:.0f} range. "
                f"Trying deep OTM fallback (min ₹10)..."
            )
            for s in strikes:
                opt    = s.get(option_type, {})
                ltp    = opt.get("ltp", 0)
                oi     = opt.get("oi", 0)
                strike = s.get("strikePrice", 0)
                if 10 <= ltp <= eff_max:
                    atm_dist = abs(strike - atm_strike) if atm_strike else 99999
                    candidates.append({
                        "strike":   strike,
                        "ltp":      ltp,
                        "oi":       oi,
                        "lot":      lot,
                        "atm_dist": atm_dist,
                        "otm_fallback": True,
                    })

        if not candidates:
            logger.warning(
                f"❌ No affordable strike found [{min_prem}–{eff_max:.0f}] "
                f"capital=₹{self.capital:.0f} segment={segment}"
            )
            return None

        # ATM first, then highest OI
        candidates.sort(key=lambda x: (x["atm_dist"], -x["oi"]))
        best = candidates[0]
        tag = " [OTM FALLBACK]" if best.get("otm_fallback") else ""
        logger.info(
            f"✅ Strike selected{tag}: {best['strike']} | "
            f"ltp={best['ltp']} | oi={best['oi']} | atm_dist={best['atm_dist']}"
        )
        return best
