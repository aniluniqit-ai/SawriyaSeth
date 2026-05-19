"""
Market Analyzer — LKS V10
Data-science approach: regime detection, segment scoring, direction prediction
"""
import logging, statistics, math
from collections import deque
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger("MarketAnalyzer")

# ── Constants ────────────────────────────────────────────
TREND_STRONG    = 0.15   # 15%+ price vs EMA50 = strong trend
TREND_WEAK      = 0.05   # 5% = weak trend
VOL_HIGH        = 0.008  # 0.8%+ daily range = high vol
VOL_LOW         = 0.003  # 0.3% = low vol
RSI_OB          = 72     # overbought
RSI_OS          = 28     # oversold
MIN_SCORE       = 55     # minimum score to recommend trade

class Regime:
    STRONG_UPTREND  = "STRONG_UPTREND"
    UPTREND         = "UPTREND"
    STRONG_DOWNTREND= "STRONG_DOWNTREND"
    DOWNTREND       = "DOWNTREND"
    RANGING         = "RANGING"
    HIGH_VOL        = "HIGH_VOLATILITY"
    LOW_VOL         = "LOW_VOLATILITY"

class SegmentAnalysis:
    def __init__(self, segment: str):
        self.segment = segment
        self.regime: str = Regime.RANGING
        self.trend_strength: float = 0.0
        self.volatility: float = 0.0
        self.momentum: float = 0.0    # % change in last 3 periods
        self.rsi: float = 50.0
        self.ce_score: float = 50.0   # 0-100: higher = better for CE
        self.pe_score: float = 50.0   # 0-100: higher = better for PE
        self.recommendation: str = "HOLD"
        self.confidence: str = "LOW"
        self.reason: str = ""
        self.atr_premium: float = 0.0  # avg true range in premium terms
        self.min_target_premium: float = 0.0  # min move for Rs 100

class MarketAnalyzer:
    """One instance per segment — analyzes price action + indicators"""

    def __init__(self, segment: str, lot_size: int = 25):
        self.segment = segment
        self.lot_size = lot_size
        self.prices: List[float] = []
        self.ema9  = 0.0
        self.ema21 = 0.0
        self.ema50 = 0.0
        self.rsi   = 50.0
        self.atr14 = 0.0
        self._gains: List[float] = []
        self._losses: List[float] = []
        self._seeded9 = self._seeded21 = self._seeded50 = False
        self.ticks = 0

    def feed(self, price: float):
        self.prices.append(price)
        if len(self.prices) > 200:
            self.prices.pop(0)
        self._update_emas(price)
        self._update_rsi(price)
        self._update_atr(price)
        self.ticks += 1

    # ── EMAs ─────────────────────────────────────────────
    def _sma(self, n: int) -> float:
        if len(self.prices) < n:
            return 0
        return sum(self.prices[-n:]) / n

    def _update_emas(self, price: float):
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

    # ── RSI ──────────────────────────────────────────────
    def _update_rsi(self, price: float):
        if len(self.prices) < 2:
            return
        chg = price - self.prices[-2]
        gain = max(0, chg); loss = abs(min(0, chg))
        self._gains.append(gain); self._losses.append(loss)
        if len(self._gains) > 14:
            self._gains.pop(0); self._losses.pop(0)
        avg_g = sum(self._gains)/max(1, len(self._gains))
        avg_l = sum(self._losses)/max(1, len(self._losses))
        if avg_l == 0:
            self.rsi = 100
        else:
            self.rsi = 100 - (100/(1+avg_g/avg_l))

    # ── ATR ──────────────────────────────────────────────
    def _update_atr(self, price: float):
        if len(self.prices) < 2:
            return
        tr = abs(price - self.prices[-2])
        n = 14
        if len(self.prices) < n + 2:
            self.atr14 = (self.atr14 * (len(self.prices) - 2) + tr) / max(1, len(self.prices) - 1)
        else:
            self.atr14 = (self.atr14 * (n - 1) + tr) / n

    # ── Core analysis ────────────────────────────────────
    def analyze(self, capital: float = 2000.0) -> SegmentAnalysis:
        result = SegmentAnalysis(self.segment)
        px = self.prices[-1] if self.prices else 0
        if not px or len(self.prices) < 30:
            result.reason = f"Warmup {len(self.prices)}/30 ticks"
            return result

        # 1. Regime detection (trend strength)
        if self.ema50 > 0:
            pct_vs_ema50 = (px - self.ema50) / self.ema50 * 100
        else:
            pct_vs_ema50 = 0.0

        ema9_21 = (self.ema9 - self.ema21) / max(1, self.ema21) * 100 if self.ema21 > 0 else 0

        if pct_vs_ema50 > TREND_STRONG and ema9_21 > 0:
            result.regime = Regime.STRONG_UPTREND
        elif pct_vs_ema50 > TREND_WEAK and ema9_21 > 0:
            result.regime = Regime.UPTREND
        elif pct_vs_ema50 < -TREND_STRONG and ema9_21 < 0:
            result.regime = Regime.STRONG_DOWNTREND
        elif pct_vs_ema50 < -TREND_WEAK and ema9_21 < 0:
            result.regime = Regime.DOWNTREND
        else:
            result.regime = Regime.RANGING
        result.trend_strength = abs(pct_vs_ema50)

        # 2. Momentum (3-period % change)
        if len(self.prices) >= 4:
            mom = (px - self.prices[-4]) / max(1, self.prices[-4]) * 100
        else:
            mom = 0.0
        result.momentum = mom

        # 3. Volatility (ATR as % of price)
        if self.atr14 > 0 and px > 0:
            result.volatility = (self.atr14 / px) * 100
        else:
            result.volatility = 0.0

        # 4. RSI
        result.rsi = self.rsi

        # 5. CE / PE scoring (weighted multi-factor)
        ce_score = 50.0
        pe_score = 50.0
        reasons_ce = []
        reasons_pe = []

        # Trend factor (weight: 30)
        if result.regime in (Regime.STRONG_UPTREND, Regime.UPTREND):
            ce_score += 20
            pe_score -= 10
            reasons_ce.append(f"Trend+{pct_vs_ema50:.1f}%")
            reasons_pe.append(f"Against trend")
        elif result.regime in (Regime.STRONG_DOWNTREND, Regime.DOWNTREND):
            ce_score -= 10
            pe_score += 20
            reasons_ce.append("Against trend")
            reasons_pe.append(f"Trend{pct_vs_ema50:.1f}%")
        else:
            reasons_ce.append("Ranging")
            reasons_pe.append("Ranging")

        # Momentum factor (weight: 25)
        if mom > 0.1:
            ce_score += 15
            pe_score -= 5
            reasons_ce.append(f"Mom+{mom:.2f}%")
        elif mom < -0.1:
            ce_score -= 5
            pe_score += 15
            reasons_pe.append(f"Mom{mom:.2f}%")
        else:
            reasons_ce.append("Mom flat")
            reasons_pe.append("Mom flat")

        # RSI factor (weight: 20)
        if self.rsi < RSI_OS:
            ce_score += 10
            pe_score -= 5
            reasons_ce.append(f"RSI OS{self.rsi:.0f}")
        elif self.rsi > RSI_OB:
            ce_score -= 5
            pe_score += 10
            reasons_pe.append(f"RSI OB{self.rsi:.0f}")
        elif 40 <= self.rsi <= 60:
            ce_score += 5
            pe_score += 5
            reasons_ce.append("RSI mid")
            reasons_pe.append("RSI mid")
        else:
            ce_score += 2
            pe_score += 2

        # EMA9/21 crossover (weight: 15)
        if self.ema9 > self.ema21:
            ce_score += 10
            pe_score -= 5
            reasons_ce.append("EMA9>21")
        else:
            ce_score -= 5
            pe_score += 10
            reasons_pe.append("EMA9<21")

        # Volatility factor (weight: 10)
        if result.volatility > VOL_HIGH * 100:
            ce_score += 5
            pe_score += 5
            reasons_ce.append("HiVol")
            reasons_pe.append("HiVol")
        elif result.volatility < VOL_LOW * 100:
            ce_score -= 3
            pe_score -= 3
            reasons_ce.append("LoVol")
            reasons_pe.append("LoVol")

        # Clamp scores
        result.ce_score = max(0, min(100, ce_score))
        result.pe_score = max(0, min(100, pe_score))

        # 6. Recommendation
        if capital < 500:
            result.recommendation = "HOLD"
            result.confidence = "LOW"
            result.reason = "Capital too low (<500)"
            return result

        max_prem = min(200, (capital * 0.58) / max(1, self.lot_size))
        result.min_target_premium = max(4.0, 100.0 / max(1, self.lot_size))

        if result.ce_score >= MIN_SCORE and result.ce_score > result.pe_score + 5:
            result.recommendation = "BUY_CE"
            result.confidence = "HIGH" if result.ce_score >= 70 else "MEDIUM"
            result.reason = "; ".join(reasons_ce[:3])
        elif result.pe_score >= MIN_SCORE and result.pe_score > result.ce_score + 5:
            result.recommendation = "BUY_PE"
            result.confidence = "HIGH" if result.pe_score >= 70 else "MEDIUM"
            result.reason = "; ".join(reasons_pe[:3])
        elif max(result.ce_score, result.pe_score) >= 45:
            result.recommendation = "BUY_CE" if result.ce_score >= result.pe_score else "BUY_PE"
            result.confidence = "LOW"
            dom = "CE" if result.ce_score >= result.pe_score else "PE"
            result.reason = f"Weak {dom} bias"
        else:
            result.recommendation = "HOLD"
            result.confidence = "LOW"
            result.reason = "No clear direction"

        # ATR-based target estimate
        if self.atr14 > 0 and self.lot_size > 0:
            result.atr_premium = self.atr14 * 0.3  # ~30% of index ATR as premium move
            req_move_rs = max(100, capital * 0.02)  # min Rs 100 or 2% of capital
            result.min_target_premium = max(
                result.min_target_premium,
                req_move_rs / max(1, self.lot_size)
            )

        return result

    def get_market_context(self) -> str:
        """Human-readable market context for Telegram messages"""
        if len(self.prices) < 30:
            return "Analyzing..."
        a = self.analyze()
        lines = [
            f"Segment: {self.segment}",
            f"Regime: {a.regime}",
            f"CE Score: {a.ce_score:.0f}/100 | PE Score: {a.pe_score:.0f}/100",
            f"Recommend: {a.recommendation} ({a.confidence})",
            f"Momentum: {a.momentum:+.2f}% | RSI: {a.rsi:.0f}",
            f"Volatility: {a.volatility:.2f}% | ATR: {self.atr14:.2f}",
            f"Reason: {a.reason}",
        ]
        return "\n".join(lines)
