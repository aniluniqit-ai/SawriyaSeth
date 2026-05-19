"""Telegram Channel Reader — LKS V21"""
import asyncio, os, logging, re
from datetime import datetime
from typing import Callable
from signal_parser import SignalParserV2
logger = logging.getLogger("TGReader")

class TelegramReader:
    def __init__(self, cfg:dict, callback:Callable, bot=None, otp_callback=None, on_connect=None):
        self.api_id   = cfg.get("api_id",0)
        self.api_hash = cfg.get("api_hash","")
        self.phone    = cfg.get("phone","")
        self.session  = cfg.get("session_file","lks_session")
        self.channels = cfg.get("channels",[])
        self.callback = callback
        self.bot      = bot
        self.otp_callback = otp_callback
        self.on_connect   = on_connect
        self.client   = None
        self._resolved_count = 0

    async def _resolve(self):
        resolved=[]; seen=set()
        async for d in self.client.iter_dialogs():
            if not getattr(d, 'name', None): continue
            nl = d.name.lower()
            for c in self.channels:
                cl = c.lower().strip()
                if not cl: continue
                if cl in nl:
                    if d.id not in seen:
                        resolved.append(d.entity); seen.add(d.id)
                        logger.info(f"Channel: {d.name}")
                    break
        return resolved

    async def start(self):
        if not self.api_id or self.api_id == 0:
            logger.warning("Telegram Reader: api_id not set"); return
        try:
            from telethon import TelegramClient, events
            exists = os.path.exists(f"{self.session}.session")
            print(f"\n{'✅ Session mili — OTP nahi maangega' if exists else '📱 Pehli baar — OTP aayega'}")
            self.client = TelegramClient(self.session, self.api_id, self.api_hash)
            if self.otp_callback:
                await self.client.start(phone=self.phone, code_callback=self.otp_callback)
            else:
                await self.client.start(phone=self.phone)
            if not exists: print("✅ Session file bani!")
            entities = await self._resolve()
            self._resolved_count = len(entities)
            if self.bot: self.bot._send(f"✅ Telegram Reader: {len(entities)}/8 channels")

            monitored_ids = [e.id for e in entities]
            
            @self.client.on(events.NewMessage())
            async def handler(event):
                chat = await event.get_chat()
                if not chat: return
                
                # Filter manually by ID or Title to fix Telethon entity bugs
                is_monitored = False
                if chat.id in monitored_ids:
                    is_monitored = True
                else:
                    ch_title_lower = getattr(chat, "title", "").lower()
                    for c in self.channels:
                        c_str = c.lower().strip()
                        if c_str and c_str in ch_title_lower:
                            is_monitored = True
                            break
                            
                if not is_monitored:
                    return

                txt = event.message.message
                if not txt or len(txt)<5: return
                ch = getattr(chat, "title", "Unknown")
                logger.info(f"[LIVE TG: {ch}] {txt[:60]}")
                
                # Pass 'LIVE' action so UI knows it's a new message
                sig = SignalParserV2.parse(txt, channel=ch)
                self.callback(sig)

            print(f"✅ {len(entities)} channels monitoring...\n")
            if self.on_connect:
                self.on_connect(len(entities))
                
            # Fetch last message for dashboard
            from telethon.tl.types import Message
            for ent in entities:
                try:
                    async for msg in self.client.iter_messages(ent, limit=1):
                        if msg and msg.text:
                            from signal_parser import ParsedSignal
                            sig = ParsedSignal(raw=msg.text, channel=ent.title, valid=False, action="HISTORY")
                            self.callback(sig)
                except: pass
                
            await self.client.run_until_disconnected()
        except ImportError:
            print("❌ pip install telethon")
        except Exception as e:
            logger.error(f"TG error: {e}")
            if self.bot: self.bot.send_error(str(e))
