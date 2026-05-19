"""Telegram Bot Notifier — LKS V21"""
import requests, logging
from datetime import datetime
logger = logging.getLogger("Bot")

class TelegramBot:
    def __init__(self, cfg:dict):
        self.token   = cfg.get("bot_token","")
        self.chat_id = cfg.get("chat_id","")
        self.enabled = bool(self.token and self.chat_id and "YAHAN" not in self.token)

    def _send(self, text:str) -> bool:
        if not self.enabled: return False
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id":self.chat_id,"text":text,"parse_mode":"HTML"},timeout=8)
            return r.status_code == 200
        except Exception as e:
            logger.error(f"Bot send: {e}"); return False

    def test(self) -> bool:
        if not self.enabled: return False
        try:
            r = requests.get(f"https://api.telegram.org/bot{self.token}/getMe",timeout=8)
            return r.json().get("ok",False)
        except: return False

    def send_startup(self, client_code:str, capital:float, mode:str, channels:list):
        chs = "\n".join(f"  📡 {c}" for c in channels[:8])
        self._send(f"""
🚀 <b>LKS WealthTech V21 — Started!</b>
━━━━━━━━━━━━━━━━━━━━━━
🕐 {datetime.now().strftime('%d-%b-%Y %H:%M:%S')}
👤 Account : <code>{client_code}</code>
💰 Capital : <code>₹{capital:,.0f}</code>
⚡ Mode    : {'📄 PAPER' if mode=='paper' else '💰 LIVE'}
━━━━━━━━━━━━━━━━━━━━━━
📡 <b>Monitoring:</b>
{chs}
━━━━━━━━━━━━━━━━━━━━━━
🌐 Dashboard: http://localhost:5000
॥ ॐ श्री गणेशाय नमः ॥
""")

    def send_error(self, msg:str):
        self._send(f"⚠️ <b>Error</b>\n{msg}\n🕐 {datetime.now().strftime('%H:%M:%S')}")
