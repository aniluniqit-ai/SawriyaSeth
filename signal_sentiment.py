"""
Signal Sentiment — LKS V10
NLP-based sentiment analysis of Telegram signal text.
Scores confidence, aggressiveness, and market bias from message text.
"""
import re
import logging

logger = logging.getLogger("SignalSentiment")

# ── Keywords & weights ─────────────────────────────────
_BULLISH_WORDS = {
    "breakout": 3, "break out": 3, "bullish": 4, "buy": 2, "strong": 3,
    "sure": 2, "confirm": 2, "target": 1, "rally": 3, "upside": 3,
    "momentum": 2, "support": 1, "reversal": 2, "accumulation": 2,
    "rocket": 4, "moon": 4, "super": 2, "massive": 3, "huge": 2,
    "profit": 2, "green": 1, "high probability": 3, "confirmed": 3,
    "entry": 1, "call": 1, "signal": 1,
}
_BEARISH_WORDS = {
    "breakdown": 3, "break down": 3, "bearish": 4, "sell": 2, "weak": 3,
    "dump": 3, "correction": 2, "downside": 3, "resistance": 1,
    "distribution": 2, "crash": 4, "fall": 2, "drop": 2, "panic": 3,
    "red": 1, "stop loss": 1, "exit": 1, "square off": 1,
}
_AGGRESSIVE_WORDS = {
    "urgent": 3, "fast": 2, "quick": 2, "now": 1, "immediate": 3,
    "🔥": 3, "🚀": 3, "⚠️": 2, "❗": 2, "‼️": 2, "💥": 3,
    "must": 2, "compulsory": 2, "sure shot": 4, "sureshot": 4,
    "guaranteed": 4, "guarantee": 4, "100%": 3, "confirmed": 2,
    "don't miss": 3, "dont miss": 3, "book now": 2,
}
_CAUTIOUS_WORDS = {
    "maybe": -2, "might": -2, "could": -1, "possibly": -2,
    "careful": -2, "wait": -2, "watch": -1, "risk": -2,
    "uncertain": -3, "confusion": -2, "volatile": -1,
}

# ── Emoji sentiment map ────────────────────────────────
_EMOJI_SENTIMENT = {
    "🚀": 4, "🔥": 3, "💥": 3, "✅": 2, "💰": 2, "📈": 3,
    "📉": -3, "❌": -3, "⚠️": -2, "🛑": -2, "🎯": 1,
}

# ── Casing patterns ────────────────────────────────────
_ALL_CAPS_PATTERN = re.compile(r"\b[A-Z]{4,}\b")  # 4+ uppercase chars
_EXCLAMATION_PATTERN = re.compile(r"!{2,}")

class SentimentScore:
    def __init__(self, text: str):
        self.text = text
        self.text_lower = text.lower()
        self.bullish_score: float = 50.0   # 0–100
        self.bearish_score: float = 50.0
        self.aggression: float = 0.0       # -100 (very cautious) to +100 (very aggressive)
        self.confidence: float = 50.0      # 0–100 overall confidence
        self.bias: str = "NEUTRAL"         # BULLISH / BEARISH / NEUTRAL
        self.urgency: bool = False
        self._analyze()

    def _analyze(self):
        text = self.text_lower
        bullish_pts = 0
        bearish_pts = 0
        aggressive_pts = 0
        cautious_pts = 0
        word_count = max(1, len(text.split()))

        # Word matching
        for word, weight in _BULLISH_WORDS.items():
            if word in text:
                bullish_pts += weight * text.count(word)
        for word, weight in _BEARISH_WORDS.items():
            if word in text:
                bearish_pts += weight * text.count(word)
        for word, weight in _AGGRESSIVE_WORDS.items():
            if word in text:
                aggressive_pts += weight * text.count(word)
        for word, weight in _CAUTIOUS_WORDS.items():
            if word in text:
                cautious_pts += abs(weight) * text.count(word)

        # Emoji sentiment
        for emoji, val in _EMOJI_SENTIMENT.items():
            cnt = self.text.count(emoji)
            if cnt:
                if val > 0:
                    bullish_pts += val * cnt
                    aggressive_pts += val * cnt
                else:
                    bearish_pts += abs(val) * cnt
                    aggressive_pts += abs(val) * cnt

        # All-caps words (conviction indicator)
        caps_words = _ALL_CAPS_PATTERN.findall(self.text)
        if caps_words:
            aggressive_pts += len(caps_words) * 2

        # Exclamation marks
        excl = _EXCLAMATION_PATTERN.findall(self.text)
        if excl:
            aggressive_pts += len(excl) * 2

        # Numeric targets (specificity = confidence)
        numbers = re.findall(r'\d+', text)
        if numbers:
            aggressive_pts += min(3, len(numbers))

        # Normalize scores to 0–100
        total = bullish_pts + bearish_pts + 1
        self.bullish_score = min(100, (bullish_pts / total) * 100)
        self.bearish_score = min(100, (bearish_pts / total) * 100)

        # Net aggression (-100 cautious to +100 aggressive)
        net_agg = aggressive_pts - cautious_pts
        self.aggression = max(-100, min(100, net_agg * 10))

        # Overall confidence (50 base + adjustments)
        self.confidence = 50.0
        if bullish_pts > bearish_pts:
            self.confidence += min(30, bullish_pts - bearish_pts)
        else:
            self.confidence += min(30, bearish_pts - bullish_pts)
        self.confidence += min(10, aggressive_pts)
        self.confidence -= min(10, cautious_pts)
        self.confidence = max(0, min(100, self.confidence))

        # Bias
        if self.bullish_score >= 65:
            self.bias = "BULLISH"
        elif self.bearish_score >= 65:
            self.bias = "BEARISH"
        else:
            self.bias = "NEUTRAL"

        # Urgency
        self.urgency = aggressive_pts >= 3 or self.aggression > 30

    def summary(self) -> str:
        parts = [
            f"Bias: {self.bias}",
            f"Bullish: {self.bullish_score:.0f}%",
            f"Bearish: {self.bearish_score:.0f}%",
            f"Confidence: {self.confidence:.0f}%",
            f"Aggression: {self.aggression:+.0f}",
        ]
        if self.urgency:
            parts.append("⚡URGENT")
        return " | ".join(parts)
