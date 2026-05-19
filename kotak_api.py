"""
Kotak Neo API — LKS WealthTech V21
Req 10: Session persistence
"""
import requests, pyotp, json, os, logging, time, urllib.parse, threading
try:
    import websocket
except ImportError:
    pass
from datetime import datetime
logger = logging.getLogger("KotakAPI")

SESSION_FILE = "sessions/kotak_session.json"

# MCX near-month symbol builder
# Returns e.g. "CRUDEOIL26MAYFUT" for May 2026
_MCX_MONTH = ["JAN","FEB","MAR","APR","MAY","JUN",
              "JUL","AUG","SEP","OCT","NOV","DEC"]

def mcx_symbol(base: str) -> str:
    """
    Auto-build active near-month MCX futures symbol.
    MCX contracts expire around the 25th of the month.
    If today >= 25th, the NEXT month contract is already active.
    """
    now   = datetime.now()
    yr    = str(now.year)[-2:]    # '26'
    # Switch to next month contract on/after 25th (MCX expiry week)
    if now.day >= 25:
        if now.month == 12:
            month_idx = 0          # January of next year
        else:
            month_idx = now.month  # next month (0-indexed = now.month)
    else:
        month_idx = now.month - 1  # current month (0-indexed)
    month = _MCX_MONTH[month_idx]
    sym   = f"{base}{yr}{month}FUT"
    logger.info(f"MCX symbol auto-built: {sym} (today={now.strftime('%d %b')})")
    return sym

class KotakWebSocket:
    def __init__(self, token, sid):
        self.url = "wss://mlhsm.kotaksecurities.com"
        self.token = token
        self.sid = sid
        self.ws = None
        self.thread = None
        self.live_prices = {}
        self.subscriptions = set()
        
    def start(self):
        if "websocket" not in globals():
            logger.warning("websocket-client not installed. WebSocket stream disabled.")
            return
        self.ws = websocket.WebSocketApp(
            self.url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        self.thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        self.thread.start()
        
    def on_open(self, ws):
        logger.info("⚡ Kotak WebSocket Connected (Zero-Delay Feed Active) ⚡")
        auth_msg = {
            "Authorization": self.token,
            "Sid": self.sid,
            "type": "cn"
        }
        ws.send(json.dumps(auth_msg))
        
        # Resubscribe to previous subscriptions if reconnecting
        for sub in self.subscriptions:
            self._send_sub(sub)
            
    def on_message(self, ws, message):
        try:
            # Kotak Neo sends market data updates as JSON strings or lists of JSON
            data = json.loads(message)
            
            # Robust parser to extract LTP regardless of exact JSON structure
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict) and "ltp" in item:
                    # Extract token (tk, token, scrip) and exchange (e, ex, exchange)
                    tk = item.get("tk", item.get("token", item.get("scrip", "")))
                    e = item.get("e", item.get("ex", item.get("exchange", "")))
                    if tk:
                        # Clean up scrip if it comes as nse_cm|2885
                        if "|" in str(tk):
                            e_split, tk_split = str(tk).split("|", 1)
                            e = e or e_split
                            tk = tk_split
                            
                        val = float(item["ltp"])
                        if e:
                            self.live_prices[f"{e}|{tk}"] = val
                        self.live_prices[str(tk)] = val
        except Exception as e:
            # Ignore minor parse errors for unknown messages like heartbeats
            pass
            
    def on_error(self, ws, error):
        logger.debug(f"Kotak WebSocket Error: {error}")
        
    def on_close(self, ws, close_status_code, close_msg):
        logger.warning(f"Kotak WebSocket Closed. Reconnecting in 5s...")
        time.sleep(5)
        self.start()
        
    def subscribe(self, token, exchange="nse_cm"):
        sym = f"{exchange}|{token}"
        if sym not in self.subscriptions:
            self.subscriptions.add(sym)
            if self.ws and self.ws.sock and self.ws.sock.connected:
                self._send_sub(sym)
            
    def _send_sub(self, sym):
        msg = {
            "type": "sub",
            "scrip": f"{sym}&"
        }
        try:
            self.ws.send(json.dumps(msg))
        except Exception as e:
            logger.error(f"WS Sub Error: {e}")
            
    def get_price(self, token, exchange="nse_cm"):
        key = f"{exchange}|{token}"
        if key in self.live_prices: return self.live_prices[key]
        if str(token) in self.live_prices: return self.live_prices[str(token)]
        return None

class KotakNeoAPI:
    LOGIN_URL = "https://mis.kotaksecurities.com/login/1.0/tradeApiLogin"
    MPIN_URL  = "https://mis.kotaksecurities.com/login/1.0/tradeApiValidate"
    URLS = {
        "limits":    "/quick/user/limits",
        "margins":   "/quick/order/rule/ms/margin",
        "holdings":  "/portfolio/v1/holdings",
        "positions": "/quick/user/positions"
    }

    def __init__(self, cfg: dict):
        self.access_token = cfg.get("access_token", "")
        self.mobile       = cfg.get("mobile", "")
        self.client_code  = cfg.get("client_code", "")
        self.mpin         = cfg.get("mpin", "")
        self.totp_secret  = cfg.get("totp_secret", "")
        self.trade_token  = None
        self.trade_sid    = None
        self.base_url     = None
        self.logged_in    = False
        self._session     = requests.Session()
        self._opt_cache   = {"time": 0, "data": {}}
        # MCX active contract cache: {"CRUDEOIL": "CRUDEOIL26MAYFUT", ...}, refreshes every 30 min
        self._mcx_cache   = {"time": 0, "contracts": {}}
        # Scrip Master Cache: {segment: {symbol: {lot: X, token: Y, full_name: Z}}}
        self.master_data  = {}
        self._master_last_sync = 0
        self.ws_client    = None

    def _h(self):
        return {"accept": "application/json", "Auth": self.trade_token,
                "Sid": self.trade_sid, "neo-fin-key": "neotradeapi",
                "Content-Type": "application/x-www-form-urlencoded"}

    def _quote_h(self):
        return {"Authorization": self.access_token, "Content-Type": "application/json"}

    # ── Req 10.2: Try restore session first ─────────────────
    def login(self) -> bool:
        if self._restore_session():
            logger.info("Session restored from file ✅")
            return True
        return self._fresh_login()

    def _restore_session(self) -> bool:
        if not os.path.exists(SESSION_FILE):
            return False
        try:
            with open(SESSION_FILE) as f:
                d = json.load(f)
            self.trade_token = d["trade_token"]
            self.trade_sid   = d["trade_sid"]
            self.base_url    = d["base_url"]
            # Quick verify with limits endpoint
            r = self._session.get(f"{self.base_url}/quick/user/limits",
                                  headers=self._h(), timeout=8)
            if r.status_code == 200:
                self.logged_in = True
                logger.info("Session valid ✅")
                if not self.ws_client:
                    self.ws_client = KotakWebSocket(self.trade_token, self.trade_sid)
                    self.ws_client.start()
                return True
            else:
                logger.warning(f"Old session expired (HTTP {r.status_code}) — deleting, will do fresh login")
                try:
                    os.remove(SESSION_FILE)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Session restore failed: {e} — deleting stale session file")
            try:
                os.remove(SESSION_FILE)
            except Exception:
                pass
        return False

    def _fresh_login(self) -> bool:
        # Guard: no credentials
        if not self.totp_secret or "YAHAN" in self.totp_secret:
            logger.warning("No Kotak TOTP secret — running in paper mode")
            return False

        if not self.access_token or len(self.access_token) < 8:
            logger.error(
                "❌ Kotak Consumer Key (access_token) is MISSING in config/config.json!\n"
                "   FIX: Go to https://kstreet.kotaksecurities.com\n"
                "        → Login → 'My Apps' → Copy your Consumer Key\n"
                "        → Paste it in config/config.json under 'access_token'"
            )
            return False

        totp = pyotp.TOTP(self.totp_secret).now()
        logger.info(f"TOTP generated: {totp}")

        # Try raw token first, then 'Bearer <token>' format as fallback
        auth_formats = [self.access_token, f"Bearer {self.access_token}"]

        for auth_val in auth_formats:
            try:
                h = {
                    "Authorization": auth_val,
                    "neo-fin-key":   "neotradeapi",
                    "Content-Type":  "application/json"
                }
                r = self._session.post(
                    self.LOGIN_URL, headers=h,
                    json={"mobileNumber": self.mobile, "ucc": self.client_code, "totp": totp},
                    timeout=15
                )
                d = r.json()

                # ── SUCCESS ──────────────────────────────────────
                if d.get("data", {}).get("status") == "success":
                    fmt_label = "Bearer" if "Bearer" in auth_val else "raw"
                    logger.info(f"Kotak TOTP login OK (format={fmt_label}) ✅")
                    vt = d["data"]["token"]
                    vs = d["data"]["sid"]
                    h.update({"sid": vs, "Auth": vt})

                    r2 = self._session.post(
                        self.MPIN_URL, headers=h,
                        json={"mpin": self.mpin}, timeout=15
                    )
                    d2 = r2.json()
                    if d2.get("data", {}).get("status") != "success":
                        logger.error(f"MPIN validation failed: {d2}")
                        return False

                    self.trade_token = d2["data"]["token"]
                    self.trade_sid   = d2["data"]["sid"]
                    self.base_url    = d2["data"]["baseUrl"]
                    self.logged_in   = True
                    self._save_session()
                    if not self.ws_client:
                        self.ws_client = KotakWebSocket(self.trade_token, self.trade_sid)
                        self.ws_client.start()
                    return True

                # ── CONSUMER KEY ERROR ────────────────────────────
                errors = d.get("error", [])
                if isinstance(errors, list) and errors:
                    code = str(errors[0].get("code", ""))
                    msg  = errors[0].get("message", "")
                    if code == "424" or "does not exist" in msg.lower() or "consumer key" in msg.lower():
                        logger.error(
                            f"\n{'='*60}\n"
                            f"❌ KOTAK CONSUMER KEY INVALID!\n"
                            f"   Error: {msg}\n"
                            f"   Current key in config: {self.access_token[:20]}...\n"
                            f"\n   ✅ HOW TO FIX:\n"
                            f"   1. Open browser → https://kstreet.kotaksecurities.com\n"
                            f"   2. Login with your Kotak credentials\n"
                            f"   3. Click 'My Apps' → find your app\n"
                            f"   4. Copy the 'Consumer Key'\n"
                            f"   5. Open config/config.json\n"
                            f"   6. Replace 'access_token' value with new Consumer Key\n"
                            f"   7. Restart the application\n"
                            f"{'='*60}"
                        )
                        return False  # No point retrying with Bearer format for this error

                logger.warning(f"Login attempt failed (auth={auth_val[:15]}...): {d}")

            except requests.exceptions.ConnectionError:
                logger.error("❌ No internet connection! Cannot reach Kotak servers.")
                return False
            except requests.exceptions.Timeout:
                logger.error("❌ Kotak server timeout! Try again after a few seconds.")
                return False
            except Exception as e:
                logger.error(f"Login request error: {e}")

        logger.error("❌ All Kotak login attempts failed. Please update your Consumer Key.")
        return False

    def _save_session(self):       # Req 10.1
        os.makedirs("sessions", exist_ok=True)
        with open(SESSION_FILE, "w") as f:
            json.dump({
                "trade_token": self.trade_token,
                "trade_sid":   self.trade_sid,
                "base_url":    self.base_url,
                "saved_at":    datetime.now().isoformat()
            }, f, indent=2)
        logger.info(f"Session saved to {SESSION_FILE}")

    def get_ltp(self, symbol: str, exchange: str = "nse_cm") -> float:
        if not self.logged_in: return 0.0
        try:
            # Step 1: Auto-resolve symbol name to token if possible (e.g. RELIANCE -> 2885)
            # This ensures we use the correct 'pSymbol' required by Quotes API
            if self.master_data and not symbol.isdigit():
                info = self.get_master_info(symbol, exchange)
                if info.get("token"):
                    symbol = info["token"]
                    logger.debug(f"Resolved {symbol} to token {symbol}")

            # ── NEW WEBSOCKET FAST PATH ──
            if self.ws_client:
                # 1. Ask WebSocket to subscribe (non-blocking, only subscribes if new)
                self.ws_client.subscribe(symbol, exchange)
                # 2. Check if we already have a live price tick
                ws_price = self.ws_client.get_price(symbol, exchange)
                if ws_price and ws_price > 0:
                    return ws_price
            # ─────────────────────────────

            sym_enc = urllib.parse.quote(f"{exchange}|{symbol}")
            url = f"{self.base_url}/script-details/1.0/quotes/neosymbol/{sym_enc}/ltp"
            r = self._session.get(url, headers=self._quote_h(), timeout=8)
            
            # If neosymbol fails, try instrument token endpoint if symbol looks like a token
            if not r.text.strip() or r.status_code != 200:
                if symbol.isdigit():
                    url = f"{self.base_url}/script-details/1.0/quotes/quote/instrument/{exchange}|{symbol}/ltp"
                    r = self._session.get(url, headers=self._quote_h(), timeout=8)

            if not r.text.strip():
                return 0.0
            
            try:
                d = r.json()
                if isinstance(d, list) and d: 
                    return float(d[0].get("ltp", 0))
                elif isinstance(d, dict) and "data" in d:
                    data = d.get("data", [])
                    if isinstance(data, list) and data:
                        return float(data[0].get("ltp", 0))
            except:
                pass
        except Exception as e:
            logger.debug(f"LTP {symbol} Error: {e}")
        return 0.0
        return 0.0

    def get_ohlc(self, symbol: str, exchange: str = "nse_cm") -> dict:
        if not self.logged_in: return {}
        try:
            sym_enc = urllib.parse.quote(f"{exchange}|{symbol}")
            url = f"{self.base_url}/script-details/1.0/quotes/neosymbol/{sym_enc}/ohlc"
            r = self._session.get(url, headers=self._quote_h(), timeout=8)
            d = r.json()
            if isinstance(d, list) and d: return d[0].get("ohlc", {})
        except: pass
        return {}

    def place_order(self, symbol: str, exchange: str, qty: int,
                    txn: str, product: str = "MIS",
                    order_type: str = "MKT", price: float = 0) -> dict:
        if not self.logged_in: return {"stat": "Not_Ok", "emsg": "Not logged in"}
        url   = f"{self.base_url}/quick/order/rule/ms/place"
        jdata = {"am": "NO", "dq": "0", "es": exchange, "mp": "0", "pc": product,
                 "pf": "N", "pr": str(price), "pt": order_type,
                 "qt": str(qty), "rt": "DAY", "tp": "0", "ts": symbol, "tt": txn}
        r = self._session.post(url, headers=self._h(),
                               data={"jData": json.dumps(jdata)}, timeout=15)
        return r.json()

    def get_margins(self, jData: dict) -> dict:
        """Fetch required margin for a specific order before placing it."""
        if not self.logged_in: return {}
        try:
            r = self._session.post(f"{self.base_url}{self.URLS['margins']}",
                                   headers=self._h(), data={"jData": json.dumps(jData)}, timeout=8)
            return r.json()
        except Exception as e:
            logger.error(f"Error fetching margins: {e}")
            return {}

    def get_holdings_v2(self) -> list:
        """Fetch detailed portfolio holdings using the NEW V1 endpoint."""
        if not self.logged_in: return []
        try:
            r = self._session.get(f"{self.base_url}{self.URLS['holdings']}",
                                   headers=self._h(), timeout=10)
            data = r.json()
            if data.get("stat") == "Ok":
                return data.get("data", [])
            return []
        except Exception as e:
            logger.error(f"Error fetching holdings V2: {e}")
            return []

    def get_positions(self) -> list:
        if not self.logged_in: return []
        try:
            r = self._session.get(f"{self.base_url}{self.URLS['positions']}",
                                   headers=self._h(), timeout=10)
            data = r.json()
            if data.get("stat") == "Ok":
                return data.get("data", [])
            return []
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    def sync_master_scrip(self, segments=["nse_cm", "nse_fo", "mcx_fo"]):
        """
        Download and parse official Kotak Scrip Master files.
        Auto-populates lot sizes, tokens, and correct trading symbols.
        Implements local caching to speed up startup.
        """
        now = time.time()
        # Memory check first
        if now - self._master_last_sync < 3600 and self.master_data:
            return True

        import requests, csv, io, os
        from datetime import date
        
        cache_dir = "data/master"
        os.makedirs(cache_dir, exist_ok=True)
        today_str = date.today().strftime("%Y%m%d")
        
        logger.info("🔄 Syncing Scrip Master (Lot sizes & Symbols)...")
        try:
            # 1. Get the latest file paths from API
            url = f"{self.base_url}/script-details/1.0/masterscrip/file-paths"
            r = self._session.get(url, headers={"Authorization": self.access_token}, timeout=10)
            paths = r.json().get("data", {}).get("filesPaths", [])
            
            for segment in segments:
                target_url = next((p for p in paths if segment in p.lower()), None)
                if not target_url: continue
                
                cache_file = os.path.join(cache_dir, f"{segment}_{today_str}.csv")
                
                # 2. Check if we already have today's file locally
                content = None
                if os.path.exists(cache_file):
                    logger.debug(f"Loading {segment} from local cache...")
                    with open(cache_file, "r", encoding="utf-8") as f:
                        content = f.read()
                else:
                    # 3. Download and save to cache
                    logger.info(f"Downloading latest {segment} master...")
                    resp = requests.get(target_url, timeout=45)
                    if resp.status_code == 200:
                        content = resp.text
                        with open(cache_file, "w", encoding="utf-8") as f:
                            f.write(content)
                        # Clean up old files for this segment
                        for f_name in os.listdir(cache_dir):
                            if f_name.startswith(segment) and today_str not in f_name:
                                try: os.remove(os.path.join(cache_dir, f_name))
                                except: pass
                
                if content:
                    reader = csv.DictReader(io.StringIO(content))
                    seg_data = {}
                    for row in reader:
                        sym   = row.get("pTrdSymbol", "")
                        token = row.get("pSymbol", "")
                        lot   = int(row.get("lLotSize", 1))
                        
                        if sym:
                            seg_data[sym] = {"lot": lot, "token": token, "row": row}
                            # Also store by base symbol (e.g. RELIANCE for RELIANCE-EQ)
                            base_sym = sym.split("-")[0].split(" ")[0].upper()
                            if base_sym not in seg_data:
                                seg_data[base_sym] = {"lot": lot, "token": token, "row": row}
                    
                    self.master_data[segment] = seg_data
            
            self._master_last_sync = now
            logger.info("✅ Scrip Master sync complete!")
            return True
        except Exception as e:
            logger.error(f"Scrip Master Sync Error: {e}")
            return False

    def get_master_info(self, symbol: str, segment: str = "nse_cm") -> dict:
        """Returns {lot, token, full_symbol} for any instrument."""
        seg_dict = self.master_data.get(segment, {})
        return seg_dict.get(symbol.upper(), {"lot": 1, "token": symbol, "full_symbol": symbol})

    def get_limits(self) -> dict:
        if not self.logged_in: return {}
        try:
            r = self._session.get(f"{self.base_url}{self.URLS['limits']}",
                                   headers=self._h(), timeout=8)
            data = r.json()
            # Log for debugging (will be visible in logs folder)
            logger.debug(f"Limits Response: {json.dumps(data)[:200]}...")
            return data
        except Exception as e:
            logger.error(f"Error fetching limits: {e}")
            return {}

    def get_option_chain(self, segment: str, expiry: str = None) -> dict:
        if not self.logged_in: return {}
        # Req 1.1: 5-second cache TTL
        now = time.time()
        cache_key = f"{segment}_{expiry}"
        if now - self._opt_cache.get("time", 0) < 5 and cache_key in self._opt_cache.get("data", {}):
            return self._opt_cache["data"][cache_key]
        try:
            url = f"{self.base_url}/market-data/1.0/option-chain"
            p = {"segment": segment}
            if expiry: p["expiry"] = expiry
            r = self._session.get(url, headers=self._h(), params=p, timeout=10)
            data = r.json()
            self._opt_cache["time"] = now
            self._opt_cache.setdefault("data", {})[cache_key] = data
            return data
        except Exception as e:
            logger.error(f"Option chain: {e}")
            return {}

    def get_active_mcx_symbol(self, base: str) -> str:
        """
        Auto-detect active MCX near-month contract using Kotak Master Scrip file.
        Result is cached for 12 hours.
        """
        now = time.time()
        # Return cached result if fresh (< 12 hours)
        if now - self._mcx_cache.get("time", 0) < 43200 and base in self._mcx_cache.get("contracts", {}):
            return self._mcx_cache["contracts"][base]

        import requests, csv, io, re
        active = f"{base}26MAYFUT"  # fallback default
        try:
            url = f"{self.base_url}/script-details/1.0/masterscrip/file-paths"
            # Master file requires 'Authorization' header explicitly
            r = self._session.get(url, headers={"Authorization": self.access_token}, timeout=10)
            data = r.json()
            
            mcx_url = None
            for path in data.get("data", {}).get("filesPaths", []):
                if "mcx_fo" in path.lower():
                    mcx_url = path
                    break
                    
            if mcx_url:
                logger.debug(f"[MCX AutoDetect] Downloading MCX master file for {base}...")
                resp = requests.get(mcx_url, timeout=20)
                reader = csv.DictReader(io.StringIO(resp.text))
                
                futs = []
                for row in reader:
                    sym = row.get("pTrdSymbol", row.get("pTrdSym", row.get("trdSym", "")))
                    inst = row.get("pInstType", row.get("instType", ""))
                    token = row.get("pSymbol", row.get("lInstToken", ""))
                    
                    # Exactly match the base prefix (so GOLD doesn't match GOLDGUINEA)
                    match = re.match(r"^([A-Za-z]+)\d+", sym)
                    if match and match.group(1) == base and "FUT" in sym and inst == "FUTCOM":
                        futs.append((sym, token))
                
                if futs:
                    logger.debug(f"[MCX AutoDetect] Found candidates for {base}: {[f[0] for f in futs[:5]]}")
                    for sym, token in futs[:15]:
                        # Try different exchange codes and formats
                        for exch_code in ["mcx_fo", "MCX", "MX"]:
                            # Try 1: Trading Symbol
                            ltp = self.get_ltp(sym, exch_code)
                            if ltp and ltp > 0:
                                logger.info(f"[MCX AutoDetect] {base}: Found active contract = {sym} with exchange {exch_code}")
                                self._mcx_cache.setdefault("contracts", {})[base] = sym
                                self._mcx_cache["time"] = now
                                return sym
                            
                            # Try 2: Instrument Token
                            if token:
                                ltp = self.get_ltp(token, exch_code)
                                if ltp and ltp > 0:
                                    logger.info(f"[MCX AutoDetect] {base}: Found active contract via TOKEN = {token} (Sym={sym})")
                                    self._mcx_cache.setdefault("contracts", {})[base] = token
                                    self._mcx_cache["time"] = now
                                    return token
                    logger.warning(f"[MCX AutoDetect] All candidates returned 0 LTP for {base}. Using fallback.")
            else:
                logger.warning(f"[MCX AutoDetect] Could not find mcx_fo CSV path from Kotak.")
        except Exception as e:
            logger.error(f"[MCX AutoDetect] Master file error for {base}: {e}")

        # Cache even fallback to prevent spam
        self._mcx_cache.setdefault("contracts", {})[base] = active
        self._mcx_cache["time"] = now
        return active

    def get_index_ltp(self, index: str) -> float:
        # NSE/BSE indices
        nse_map = {
            "NIFTY":      ("nse_cm", "Nifty 50"),
            "BANKNIFTY":  ("nse_cm", "Nifty Bank"),
            "FINNIFTY":   ("nse_cm", "Nifty Fin Service"),
            "SENSEX":     ("bse_cm", "SENSEX"),
            "BANKEX":     ("bse_cm", "BANKEX"),
            "MIDCPNIFTY": ("nse_cm", "Nifty Midcap Select"),
        }
        if index in nse_map:
            exch, sym = nse_map[index]
            return self.get_ltp(sym, exch)

        # MCX Commodities — auto-detect active contract from Kotak
        mcx_map = {
            "CRUDEOIL":   "CRUDEOIL",
            "NATURALGAS": "NATURALGAS",
        }
        if index in mcx_map:
            # Fully automatic — queries Kotak to find active contract
            sym = self.get_active_mcx_symbol(mcx_map[index])
            # Try both common MCX exchange codes
            for exch in ["mcx_fo", "MCX", "mcx"]:
                ltp = self.get_ltp(sym, exch)
                if ltp > 0: return ltp
            return 0.0

        return 0.0
