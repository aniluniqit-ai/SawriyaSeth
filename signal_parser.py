"""
SignalParserV2 — LKS WealthTech V21
Requirement 2: Full signal parsing with confidence scoring
"""
import re, logging
from dataclasses import dataclass, field
from typing import List, Optional
logger = logging.getLogger("SignalParser")

# Req 2.2: Symbol aliases longest-match-first
SYMBOL_ALIASES = [
    ("banknifty","BANKNIFTY"),("bnf","BANKNIFTY"),("bank nifty","BANKNIFTY"),
    ("finnifty","FINNIFTY"),("fin nifty","FINNIFTY"),("fnf","FINNIFTY"),
    ("midcpnifty","MIDCPNIFTY"),("midcap nifty","MIDCPNIFTY"),
    ("sensex","SENSEX"),("bankex","BANKEX"),
    ("nifty","NIFTY"),("nf","NIFTY"),
    ("crudeoil","CRUDEOIL"),("crude","CRUDEOIL"),("crude oil","CRUDEOIL"),
    ("naturalgas","NATURALGAS"),("natural gas","NATURALGAS"),("ng","NATURALGAS"),
    ("gold","GOLD"),("goldm","GOLDM"),
    ("silver","SILVER"),("silverm","SILVERM"),
]

# Req 2.4: Strike ranges per symbol (nearest 50)
STRIKE_RANGES = {
    "NIFTY":     (20000, 30000),
    "BANKNIFTY": (40000, 60000),
    "FINNIFTY":  (18000, 28000),
    "SENSEX":    (70000,100000),
    "MIDCPNIFTY":(10000, 20000),
    "BANKEX":    (50000, 70000),
    "CRUDEOIL":  (2000, 15000),
    "NATURALGAS":(100, 1000),
    "GOLD":      (60000, 90000),
    "GOLDM":     (60000, 90000),
    "SILVER":    (70000, 110000),
    "SILVERM":   (70000, 110000),
}

def strip_emojis(text:str) -> str:
    return re.sub(r'[^\x00-\x7F\u0900-\u097F]+', ' ', text)

def nearest_50(n:int) -> int:
    return round(n / 50) * 50

@dataclass
class ParsedSignal:
    symbol:        Optional[str]  = None
    strike:        Optional[int]  = None
    option_type:   Optional[str]  = None   # CE / PE
    action:        str            = "BUY"
    entry:         Optional[float]= None
    targets:       List[float]    = field(default_factory=list)
    sl:            Optional[float]= None
    confidence:    int            = 30
    valid:         bool           = False
    raw:           str            = ""
    channel:       str            = ""
    time:          str            = ""

class SignalParserV2:

    # Req 2.3: Emoji hints
    CE_EMOJIS = ["🟢","📈","🚀","💚","⬆"]
    PE_EMOJIS = ["🔴","📉","💔","❌","⬇"]

    @classmethod
    def parse(cls, message:str, channel:str="") -> ParsedSignal:
        from datetime import datetime
        sig = ParsedSignal(raw=message, channel=channel,
                           time=datetime.now().strftime("%H:%M:%S"))
        raw = message
        clean = strip_emojis(message).upper()

        # ── Symbol ───────────────────────────────────────
        for alias, sym in SYMBOL_ALIASES:
            if alias.upper() in clean:
                sig.symbol = sym
                break

        # ── Strike ───────────────────────────────────────
        strike_m = re.findall(r'\b(\d{4,6})\b', clean)
        rng = STRIKE_RANGES.get(sig.symbol, (0, 999999)) if sig.symbol else (0,999999)
        for sm in strike_m:
            v = int(sm)
            if rng[0] <= v <= rng[1]:
                sig.strike = nearest_50(v)
                break

        # ── Option type ──────────────────────────────────
        # Req 2.3: explicit CE/PE/CALL/PUT
        if re.search(r'\bCE\b|\bCALL\b', clean): sig.option_type = "CE"
        elif re.search(r'\bPE\b|\bPUT\b', clean): sig.option_type = "PE"
        else:
            # emoji hints
            for e in cls.CE_EMOJIS:
                if e in raw: sig.option_type = "CE"; break
            if not sig.option_type:
                for e in cls.PE_EMOJIS:
                    if e in raw: sig.option_type = "PE"; break
            # directional
            if not sig.option_type:
                if re.search(r'\b(BULLISH|ABOVE|BUY CALL|LONG CALL)\b', clean):
                    sig.option_type = "CE"
                elif re.search(r'\b(BEARISH|BELOW|BUY PUT|LONG PUT)\b', clean):
                    sig.option_type = "PE"

        # ── Action ───────────────────────────────────────
        if re.search(r'\b(SELL|SHORT)\b', clean): sig.action = "SELL"
        else: sig.action = "BUY"

        # ── Entry ────────────────────────────────────────
        entry_m = re.search(
            r'(?:ENTRY|ABOVE|@|BUY\s+(?:ABOVE\s+)?)\s*(\d+(?:\.\d+)?)', clean)
        if entry_m: sig.entry = float(entry_m.group(1))
        else:
            # fallback: first number after option type keyword
            nums = re.findall(r'(?:CE|PE|CALL|PUT)\s+(?:BUY\s+)?(\d+(?:\.\d+)?)', clean)
            if nums: sig.entry = float(nums[0])

        # ── Targets ──────────────────────────────────────
        tgt_block = re.search(
            r'(?:TARGET|TGT|TP)[:\s-]*'
            r'(\d+(?:\.\d+)?)(?:[,/\s]+(\d+(?:\.\d+)?))?', clean)
        if tgt_block:
            sig.targets.append(float(tgt_block.group(1)))
            if tgt_block.group(2):
                sig.targets.append(float(tgt_block.group(2)))

        # ── SL ───────────────────────────────────────
        sl_m = re.search(r'(?:SL|STOP\s*LOSS)[:\s-]*(\d+(?:\.\d+)?)', clean)
        if sl_m:
            sig.sl = float(sl_m.group(1))
        # Fix 5: Fallback auto-SL when SL is hidden ("PAID") or missing
        # Auto-SL = Entry price - 10% of entry (safe conservative default)
        if not sig.sl and sig.entry:
            sig.sl = round(sig.entry * 0.90, 2)  # 10% below entry as auto-SL

        # ── Confidence (Req 2.5) ─────────────────────────
        score = 40  # base
        if sig.symbol:      score += 15
        if sig.strike:      score += 10
        if sig.option_type: score += 15
        if sig.entry:       score += 5
        if sig.targets:     score += 5
        if sig.sl:          score += 5
        sig.confidence = max(30, min(95, score))

        # ── Valid (Req 2.6) ──────────────────────────────
        sig.valid = bool(sig.symbol and sig.option_type)

        logger.info(f"Parsed [{channel}]: valid={sig.valid} "
                    f"{sig.symbol} {sig.strike} {sig.option_type} "
                    f"entry={sig.entry} conf={sig.confidence}")
        return sig
