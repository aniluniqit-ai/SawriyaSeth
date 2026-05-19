import customtkinter as ctk
import threading, json, os, sys, time, logging
from datetime import datetime

# Initialize logging for the GUI
os.makedirs("logs", exist_ok=True)
os.makedirs("sessions", exist_ok=True)
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.FileHandler(f"logs/app_{datetime.now().strftime('%Y%m%d')}.log", encoding='utf-8'),
              logging.StreamHandler()])
logger = logging.getLogger("MainGUI")

from kotak_api import KotakNeoAPI
from capital_manager import CapitalManager
from telegram_bot import TelegramBot
from telegram_reader import TelegramReader
from option_trader import OptionChainTrader
from db_manager import DBManager
from ai_director import AIDirector
from webhook_server import TradingViewWebhook
import asyncio
from PIL import Image

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

INDEX_MAP = {
    "NIFTY": ("nse_cm", "Nifty 50"),
    "BANKNIFTY": ("nse_cm", "Nifty Bank"),
    "FINNIFTY": ("nse_cm", "Nifty Fin Service"),
    "MIDCPNIFTY": ("nse_cm", "NIFTY MID SELECT"),
    "BANKEX": ("bse_cm", "S&P BSE BANKEX"),
    "SENSEX": ("bse_cm", "SENSEX"),
    "CRUDEOIL": ("mcx_fo", "CRUDEOIL"),
    "NATURALGAS": ("mcx_fo", "NATURALGAS"),
    "NATGASMINI": ("mcx_fo", "NATGASMINI"),
    "GOLD": ("mcx_fo", "GOLD"),
    "GOLDM": ("mcx_fo", "GOLDM"),
    "GOLDGUINEA": ("mcx_fo", "GOLDGUINEA"),
    "SILVER": ("mcx_fo", "SILVER"),
    "SILVERM": ("mcx_fo", "SILVERM"),
    "SILVERMIC": ("mcx_fo", "SILVERMIC"),
    "RELIANCE": ("nse_cm", "RELIANCE"),
    "HDFCBANK": ("nse_cm", "HDFCBANK"),
    "ICICIBANK": ("nse_cm", "ICICIBANK"),
    "TATAMOTORS": ("nse_cm", "TATAMOTORS"),
    "SBIN": ("nse_cm", "SBIN"),
    "INFY": ("nse_cm", "INFY")
}

class LKSWealthTechApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("LKS WealthTech V21 - Option Chain Auto Trader")
        self.geometry("950x650")
        self.configure(fg_color="#002200")  # Very Dark Green Background

        self.G = {"api": None, "cap": None, "bot": None, "trader": None, "cfg": {}, "db": None, "ai": None,
                  "prices": {s: 0.0 for s in INDEX_MAP}, "status": {"kotak": False, "mode": "paper"}}

        self._setup_ui()
        self.after(500, self._start_background_tasks)

    def _setup_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Left Sidebar (Status & Controls)
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0, fg_color="#003300")
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(5, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="LKS WealthTech", font=ctk.CTkFont(size=20, weight="bold"), text_color="#FFD700")
        self.logo_label.grid(row=0, column=0, padx=20, pady=(10, 10))
        
        try:
            logo_img = ctk.CTkImage(light_image=Image.open("assets/robot.png"),
                                    dark_image=Image.open("assets/robot.png"), size=(100, 100))
            self.img_label = ctk.CTkLabel(self.sidebar_frame, image=logo_img, text="")
            self.img_label.grid(row=1, column=0, padx=20, pady=5)
        except: pass

        self.status_label = ctk.CTkLabel(self.sidebar_frame, text="System: Initializing...", font=ctk.CTkFont(size=14), text_color="#FFD700")
        self.status_label.grid(row=2, column=0, padx=20, pady=10)

        self.kotak_label = ctk.CTkLabel(self.sidebar_frame, text="Kotak API: Disconnected", text_color="#FF4444")
        self.kotak_label.grid(row=3, column=0, padx=20, pady=5)

        self.tg_label = ctk.CTkLabel(self.sidebar_frame, text="Telegram: Connecting...", text_color="#FFA500")
        self.tg_label.grid(row=5, column=0, padx=20, pady=5)

        self.mode_toggle_btn = ctk.CTkButton(self.sidebar_frame, text="Mode: PAPER (Click to LIVE)", fg_color="#DAA520", hover_color="#B8860B", text_color="black", font=ctk.CTkFont(weight="bold"), command=self._toggle_trading_mode)
        self.mode_toggle_btn.grid(row=6, column=0, padx=20, pady=10)

        self.orders_btn = ctk.CTkButton(self.sidebar_frame, text="📋 View My Orders", fg_color="#DAA520", hover_color="#B8860B", text_color="black", font=ctk.CTkFont(weight="bold"), command=self._show_orders)
        self.orders_btn.grid(row=7, column=0, padx=20, pady=10)

        self.sq_off_btn = ctk.CTkButton(self.sidebar_frame, text="Square Off All", fg_color="red", hover_color="darkred", command=self._square_off)
        self.sq_off_btn.grid(row=8, column=0, padx=20, pady=(15, 5))

        self.kill_switch_btn = ctk.CTkButton(self.sidebar_frame, text="🛑 EMERGENCY KILL SWITCH", fg_color="#8B0000", hover_color="#ff0000", text_color="white", font=ctk.CTkFont(weight="bold"), command=self._activate_kill_switch)
        self.kill_switch_btn.grid(row=9, column=0, padx=20, pady=5)

        self.settings_btn = ctk.CTkButton(self.sidebar_frame, text="⚙️ Account Settings", fg_color="#4682B4", hover_color="#4169E1", command=self._open_settings)
        self.settings_btn.grid(row=10, column=0, padx=20, pady=5)
        
        # Bottom sidebar images
        try:
            k_img = ctk.CTkImage(Image.open("assets/kalash.png"), size=(50, 50))
            ctk.CTkLabel(self.sidebar_frame, image=k_img, text="").grid(row=11, column=0, pady=2)
            mp_img = ctk.CTkImage(Image.open("assets/mor_pankh.png"), size=(50, 50))
            ctk.CTkLabel(self.sidebar_frame, image=mp_img, text="").grid(row=12, column=0, pady=2)
        except: pass

        # Main Area
        self.main_frame = ctk.CTkFrame(self, fg_color="#002200")
        self.main_frame.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self.main_frame.grid_rowconfigure(4, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)

        # Ganesh Image at Top Center with Shubh Labh and Swastik
        self.top_logo_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.top_logo_frame.grid(row=0, column=0, pady=(10, 0))
        
        # Left Images
        for img_name in ["hanging_deepak.png", "swastik.png", "om.png"]:
            try:
                img = ctk.CTkImage(Image.open(f"assets/{img_name}"), size=(40, 40))
                ctk.CTkLabel(self.top_logo_frame, image=img, text="").pack(side="left", padx=5)
            except: pass

        # Shubh
        ctk.CTkLabel(self.top_logo_frame, text="शुभ", font=ctk.CTkFont(size=30, weight="bold"), text_color="#FFD700").pack(side="left", padx=10)

        # Ganesh Ji
        try:
            ga_img = ctk.CTkImage(Image.open("assets/ganesh.png"), size=(80, 80))
            ctk.CTkLabel(self.top_logo_frame, image=ga_img, text="").pack(side="left", padx=15)
        except: pass

        # Labh
        ctk.CTkLabel(self.top_logo_frame, text="लाभ", font=ctk.CTkFont(size=30, weight="bold"), text_color="#FFD700").pack(side="left", padx=10)

        # Right Images
        for img_name in ["om.png", "swastik.png", "hanging_deepak.png"]:
            try:
                img = ctk.CTkImage(Image.open(f"assets/{img_name}"), size=(40, 40))
                ctk.CTkLabel(self.top_logo_frame, image=img, text="").pack(side="left", padx=5)
            except: pass

        # Multi-line Mantra
        mantra_text = "॥ ॐ श्री गणेशाय नमः ॥\n॥ श्री शिवाय नमस्तुभ्यं ॥\n॥ जय श्री सांवरीया सेठ जी ॥\n॥ लक्ष्मी कुबेर की कृपा ॥\n॥ शुभं करोति कल्याणं आरोग्यं धनसंपदा ॥\n॥ शत्रुबुद्धि विनाशाय दीपज्योतिर्नमोऽस्तु ते ॥"
        self.mantra_label = ctk.CTkLabel(self.main_frame, text=mantra_text, 
                                         font=ctk.CTkFont(size=18, weight="bold"), text_color="#00FF00", justify="center")
        self.mantra_label.grid(row=1, column=0, pady=(0, 10))

        # Capital Frame
        self.cap_frame = ctk.CTkFrame(self.main_frame, fg_color="#003300", border_color="#FFD700", border_width=2)
        self.cap_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")
        
        try:
            sb_img = ctk.CTkImage(Image.open("assets/shyam_baba.png"), size=(60, 60))
            ctk.CTkLabel(self.cap_frame, image=sb_img, text="").pack(side="left", padx=20)
        except: pass

        center_cap_frame = ctk.CTkFrame(self.cap_frame, fg_color="transparent")
        center_cap_frame.pack(side="left", expand=True)

        self.cap_label = ctk.CTkLabel(center_cap_frame, text="Capital: ₹0.00 | Daily PnL: ₹0.00 | Trades: 0", font=ctk.CTkFont(size=16, weight="bold"), text_color="#FFD700")
        self.cap_label.pack(pady=2)
        
        self.stats_label = ctk.CTkLabel(center_cap_frame, text="Win Rate: 0% | RRR: 0.0 | Max DD: 0.0%", font=ctk.CTkFont(size=14), text_color="#00FFFF")
        self.stats_label.pack(pady=1)

        self.real_margin_label = ctk.CTkLabel(center_cap_frame, text="Kotak Live Balance: ₹0.00 | Active Positions: 0", font=ctk.CTkFont(size=14, weight="bold"), text_color="#00FF00")
        self.real_margin_label.pack(pady=1)
        
        self.strategy_label = ctk.CTkLabel(center_cap_frame, text="Current Strategy: 🚀 LKS Auto Scalping + TSL", font=ctk.CTkFont(size=15, weight="bold"), text_color="#FFA500")
        self.strategy_label.pack(pady=2)

        # Confluence Meter
        self.confluence_frame = ctk.CTkFrame(center_cap_frame, fg_color="transparent")
        self.confluence_frame.pack(pady=2)
        ctk.CTkLabel(self.confluence_frame, text="Trade Confluence Score:", font=ctk.CTkFont(size=12), text_color="white").pack(side="left", padx=5)
        self.score_bar = ctk.CTkProgressBar(self.confluence_frame, width=150, height=12, progress_color="#00FF00", fg_color="#444444")
        self.score_bar.pack(side="left", padx=5)
        self.score_bar.set(0)
        self.score_label = ctk.CTkLabel(self.confluence_frame, text="0%", font=ctk.CTkFont(size=12, weight="bold"), text_color="#00FF00")
        self.score_label.pack(side="left", padx=5)

        try:
            lk_img = ctk.CTkImage(Image.open("assets/laxmi_kuber.png"), size=(60, 60))
            ctk.CTkLabel(self.cap_frame, image=lk_img, text="").pack(side="right", padx=20)
        except: pass

        # Prices Frame
        self.prices_frame = ctk.CTkFrame(self.main_frame, fg_color="#003300", border_color="#FFD700", border_width=1)
        self.prices_frame.grid(row=3, column=0, padx=10, pady=10, sticky="ew")
        
        try:
            bull_img = ctk.CTkImage(Image.open("assets/market_bull.png"), size=(50, 50))
            ctk.CTkLabel(self.prices_frame, image=bull_img, text="").grid(row=0, column=0, rowspan=2, padx=10)
        except: pass

        for c in range(1, 5): self.prices_frame.grid_columnconfigure(c, weight=1)
        
        self.price_labels = {}
        row_idx, col_idx = 0, 1
        for sym in INDEX_MAP.keys():
            lbl = ctk.CTkLabel(self.prices_frame, text=f"{sym}\n0.00", font=ctk.CTkFont(size=15, weight="bold"), text_color="#FFD700")
            lbl.grid(row=row_idx, column=col_idx, padx=5, pady=10)
            self.price_labels[sym] = lbl
            col_idx += 1
            if col_idx >= 5:
                col_idx = 1
                row_idx += 1
                
        try:
            bear_img = ctk.CTkImage(Image.open("assets/market_bear.png"), size=(50, 50))
            ctk.CTkLabel(self.prices_frame, image=bear_img, text="").grid(row=0, column=5, rowspan=2, padx=10)
        except: pass

        # Logs Toggle
        self.log_switch = ctk.CTkSwitch(self.main_frame, text="Show Logs & Telegram", command=self._toggle_logs, text_color="#FFD700")
        self.log_switch.grid(row=4, column=0, padx=10, pady=5, sticky="w")
        self.log_switch.select()

        # Bottom Frame for Logs and Telegram Chats
        self.bottom_frame = ctk.CTkFrame(self.main_frame, fg_color="#002200")
        self.bottom_frame.grid(row=5, column=0, padx=10, pady=10, sticky="nsew")
        self.bottom_frame.grid_columnconfigure(0, weight=1)
        self.bottom_frame.grid_columnconfigure(1, weight=1)
        self.bottom_frame.grid_rowconfigure(0, weight=1)

        self.log_textbox = ctk.CTkTextbox(self.bottom_frame, width=300, height=200, fg_color="#FFFF00", text_color="#000000", font=ctk.CTkFont(weight="bold"))
        self.log_textbox.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        
        self.tg_textbox = ctk.CTkTextbox(self.bottom_frame, width=300, height=200, fg_color="#FFFF00", text_color="#000000", font=ctk.CTkFont(weight="bold"))
        self.tg_textbox.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")
        self.tg_textbox.insert(ctk.END, "Telegram Live Chats:\n━━━━━━━━━━━━━━━━━━\n")

        try:
            # Embed Live PnL Chart
            import matplotlib
            matplotlib.use("TkAgg")
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
            
            self.fig = Figure(figsize=(8, 2.5), dpi=100, facecolor='#002200')
            self.ax = self.fig.add_subplot(121)
            self.ax.set_facecolor('#001100')
            self.ax.tick_params(colors='white')
            self.ax.plot([0], [0], color='#00FF00')
            self.ax.set_title("Live PnL Graph", color='#FFD700', fontsize=10)
            
            self.ax_candle = self.fig.add_subplot(122)
            self.ax_candle.set_facecolor('#001100')
            self.ax_candle.tick_params(colors='white')
            self.ax_candle.set_title("Live Candlestick", color='#FFD700', fontsize=10)
            
            self.fig.tight_layout(pad=1.0)
            
            self.canvas = FigureCanvasTkAgg(self.fig, master=self.bottom_frame)
            self.canvas.get_tk_widget().grid(row=0, column=2, columnspan=2, padx=10, sticky="nsew")
            
            self.chart_symbol_var = ctk.StringVar(value="NIFTY")
            self.chart_symbol_dropdown = ctk.CTkOptionMenu(
                self.bottom_frame, 
                values=["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY", "BANKEX", "CRUDEOIL", "NATURALGAS", "NATGASMINI", "GOLD", "GOLDM", "GOLDGUINEA", "SILVER", "SILVERM", "SILVERMIC", "RELIANCE", "HDFCBANK", "TATAMOTORS"], 
                variable=self.chart_symbol_var, 
                width=120
            )
            self.chart_symbol_dropdown.grid(row=1, column=2, columnspan=2, pady=5)
        except Exception as e:
            self._log(f"Matplotlib chart disabled: {e}")
            try:
                yantra_img = ctk.CTkImage(Image.open("assets/yantra.png"), size=(60, 60))
                ctk.CTkLabel(self.bottom_frame, image=yantra_img, text="").grid(row=0, column=2, padx=10)
                fish_img = ctk.CTkImage(Image.open("assets/golden_fish.png"), size=(60, 60))
                ctk.CTkLabel(self.bottom_frame, image=fish_img, text="").grid(row=0, column=3, padx=10)
            except: pass

    def _log(self, msg):
        now = datetime.now().strftime("%H:%M:%S")
        self.log_textbox.insert(ctk.END, f"[{now}] {msg}\n")
        self.log_textbox.see(ctk.END)
        logger.info(msg)

    def _toggle_logs(self):
        if self.log_switch.get():
            self.bottom_frame.grid(row=5, column=0, padx=10, pady=10, sticky="nsew")
        else:
            self.bottom_frame.grid_forget()

    def _show_orders(self):
        import tkinter.ttk as ttk
        w = ctk.CTkToplevel(self)
        w.title("My Orders & Portfolio")
        w.geometry("900x650")
        w.configure(fg_color="#002200")
        
        # Center popup
        w.update_idletasks()
        x = (w.winfo_screenwidth() // 2) - (900 // 2)
        y = (w.winfo_screenheight() // 2) - (650 // 2)
        w.geometry(f"+{x}+{y}")
        w.attributes("-topmost", True)
        
        header_frame = ctk.CTkFrame(w, fg_color="transparent")
        header_frame.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(header_frame, text="📈 Trade History & Performance", font=ctk.CTkFont(size=18, weight="bold"), text_color="#FFD700").pack(side="left")
        
        search_var = ctk.StringVar()
        search_entry = ctk.CTkEntry(header_frame, placeholder_text="Search Symbol...", textvariable=search_var, width=200)
        search_entry.pack(side="right", padx=10)

        # Performance Summary at the top
        perf_frame = ctk.CTkFrame(w, fg_color="#003300", border_color="#FFD700", border_width=1)
        perf_frame.pack(fill="x", padx=10, pady=5)
        
        if self.G["cap"]:
            s = self.G["cap"].summary()
            stats_text = (f"Total PnL: ₹{s['total_pnl']:,.2f} | Win Rate: {s['win_rate']}% | "
                          f"Sharpe: {s['sharpe']} | Sortino: {s['sortino']} | RRR: {s['rrr']}")
            ctk.CTkLabel(perf_frame, text=stats_text, font=ctk.CTkFont(size=14, weight="bold"), text_color="#00FF00").pack(pady=5)

        # Style for Treeview
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#001100", foreground="white", fieldbackground="#001100", borderwidth=0)
        style.map("Treeview", background=[('selected', '#DAA520')], foreground=[('selected', 'black')])

        # Table for Trade History
        table_frame = ctk.CTkFrame(w, fg_color="transparent")
        table_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        cols = ("Time", "Symbol", "Entry", "Exit", "PnL", "Reason", "Source", "Mode")
        tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=15)
        for col in cols:
            tree.heading(col, text=col)
            tree.column(col, width=100, anchor="center")
        
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def load_data(filter_text=""):
            for item in tree.get_children(): tree.delete(item)
            if not self.G["trader"]: return
            
            stats = self.G["trader"].get_opt_stats()
            closed = stats.get("closed_today", [])
            for c in reversed(closed):
                if filter_text.lower() in c['symbol'].lower():
                    tag = "profit" if c['pnl'] > 0 else "loss"
                    tree.insert("", "end", values=(c['time'], c['symbol'], c['entry'], c['exit'], f"₹{c['pnl']}", c['reason'], c.get('source','N/A'), c.get('mode','PAPER')), tags=(tag,))
            
            tree.tag_configure("profit", foreground="#00FF00")
            tree.tag_configure("loss", foreground="#FF4444")

        search_var.trace_add("write", lambda *args: load_data(search_var.get()))
        load_data()

    def _toggle_trading_mode(self):
        current = self.G["status"].get("mode", "paper")
        if current == "paper":
            self.G["status"]["mode"] = "live"
            self.mode_toggle_btn.configure(text="Mode: LIVE (Click to PAPER)", fg_color="red", hover_color="darkred", text_color="white")
            if self.G.get("trader"): self.G["trader"].mode = "live"
            self._log("Switched to LIVE TRADING mode. Real orders will be placed!")
            if self.G["bot"]: self.G["bot"]._send("⚠️ *WARNING: System switched to LIVE TRADING mode!*")
        else:
            self.G["status"]["mode"] = "paper"
            self.mode_toggle_btn.configure(text="Mode: PAPER (Click to LIVE)", fg_color="#DAA520", hover_color="#B8860B", text_color="black")
            if self.G.get("trader"): self.G["trader"].mode = "paper"
            self._log("Switched to PAPER TRADING mode. Virtual orders only.")
            if self.G["bot"]: self.G["bot"]._send("✅ System switched to PAPER TRADING mode.")

    def _square_off(self):
        if self.G["trader"]:
            self._log("Square Off Initiated!")
            self.G["trader"]._square_off_all()

    def _activate_kill_switch(self):
        self._log("🚨 KILL SWITCH ACTIVATED! Closing all positions and locking system!")
        self.kill_switch_btn.configure(text="LOCKED", state="disabled")
        self.mode_toggle_btn.configure(state="disabled")
        if self.G.get("bot"): self.G["bot"]._send("🚨 *KILL SWITCH TRIGGERED!* System locked and trades squared off.")
        if self.G.get("trader"):
            self.G["trader"]._square_off_all()
            self.G["trader"].auto_trade = False

    def _open_settings(self):
        w = ctk.CTkToplevel(self)
        w.title("Account Settings — Kotak & XM MT5")
        w.geometry("520x600")
        w.configure(fg_color="#002200")
        w.attributes("-topmost", True)

        # Center popup
        w.update_idletasks()
        x = (w.winfo_screenwidth() // 2) - (520 // 2)
        y = (w.winfo_screenheight() // 2) - (600 // 2)
        w.geometry(f"+{x}+{y}")

        tabview = ctk.CTkTabview(w, width=490, height=480)
        tabview.pack(padx=10, pady=10)

        tab_k  = tabview.add("🏦 Kotak Neo")

        # ── Kotak Tab ───────────────────────────────────────────
        ctk.CTkLabel(tab_k, text="Kotak Neo API Credentials",
                     font=ctk.CTkFont(size=14, weight="bold"), text_color="#FFD700").pack(pady=(8, 2))

        # Help banner for consumer key
        ctk.CTkLabel(
            tab_k,
            text="⚠️ Consumer Key kahan se milega?\n"
                 "  → kstreet.kotaksecurities.com → Login\n"
                 "  → 'My Apps' → apni App → Consumer Key copy karo",
            font=ctk.CTkFont(size=11), text_color="#FFA500", justify="left"
        ).pack(pady=(0, 6))

        # Pre-fill current values from config.json
        cfg_k = self.G.get("cfg", {}).get("kotak", {})

        e_k_mob = ctk.CTkEntry(tab_k, placeholder_text="Mobile No (e.g. +919XXXXXXXXX)", width=380)
        e_k_mob.pack(pady=3)
        if cfg_k.get("mobile"): e_k_mob.insert(0, cfg_k["mobile"])

        e_k_client = ctk.CTkEntry(tab_k, placeholder_text="Client Code (e.g. XV3ZT)", width=380)
        e_k_client.pack(pady=3)
        if cfg_k.get("client_code"): e_k_client.insert(0, cfg_k["client_code"])

        e_k_mpin = ctk.CTkEntry(tab_k, placeholder_text="MPIN", show="*", width=380)
        e_k_mpin.pack(pady=3)
        if cfg_k.get("mpin"): e_k_mpin.insert(0, cfg_k["mpin"])

        e_k_token = ctk.CTkEntry(tab_k, placeholder_text="Consumer Key (access_token)", width=380)
        e_k_token.pack(pady=3)
        if cfg_k.get("access_token"): e_k_token.insert(0, cfg_k["access_token"])

        e_k_totp = ctk.CTkEntry(tab_k, placeholder_text="TOTP Secret Key", show="*", width=380)
        e_k_totp.pack(pady=3)
        if cfg_k.get("totp_secret"): e_k_totp.insert(0, cfg_k["totp_secret"])

        status_lbl = ctk.CTkLabel(tab_k, text="", text_color="#00FF00", font=ctk.CTkFont(size=11))
        status_lbl.pack(pady=3)

        def save_and_reconnect_kotak():
            """Save new credentials directly to config.json and immediately reconnect."""
            new_token = e_k_token.get().strip()
            if not new_token:
                status_lbl.configure(text="❌ Consumer Key field khali hai!", text_color="#FF4444")
                return

            # Update config.json
            try:
                with open("config/config.json", encoding="utf-8") as f:
                    full_cfg = json.load(f)
                full_cfg["kotak"]["mobile"]       = e_k_mob.get().strip()
                full_cfg["kotak"]["client_code"]  = e_k_client.get().strip()
                full_cfg["kotak"]["mpin"]         = e_k_mpin.get().strip()
                full_cfg["kotak"]["access_token"] = new_token
                full_cfg["kotak"]["totp_secret"]  = e_k_totp.get().strip()
                with open("config/config.json", "w", encoding="utf-8") as f:
                    json.dump(full_cfg, f, indent=2, ensure_ascii=False)
                self.G["cfg"] = full_cfg
                status_lbl.configure(text="✅ config.json saved!", text_color="#00FF00")
                self._log("Kotak credentials updated in config.json")
            except Exception as e:
                status_lbl.configure(text=f"❌ Save failed: {e}", text_color="#FF4444")
                return

            # Delete stale session file so fresh login is forced
            import os as _os
            sess = "sessions/kotak_session.json"
            if _os.path.exists(sess):
                try: _os.remove(sess)
                except: pass

            # Reconnect Kotak in background thread
            status_lbl.configure(text="⏳ Reconnecting to Kotak...", text_color="#FFA500")
            w.update()

            def do_reconnect():
                from kotak_api import KotakNeoAPI
                kc = full_cfg.get("kotak", {})
                new_api = KotakNeoAPI(kc)
                try:
                    if new_api.login():
                        self.G["api"] = new_api
                        self.G["status"]["kotak"] = True
                        self.kotak_label.configure(text="Kotak API: Connected ✅", text_color="green")
                        status_lbl.configure(text="✅ Kotak Connected!", text_color="#00FF00")
                        self._log("✅ Kotak reconnected with new credentials!")
                        if self.G.get("trader"):
                            self.G["trader"].api = new_api
                            if hasattr(self.G["trader"], '_was_auto_paused'):
                                self.G["trader"].auto_trade = True
                                self.G["trader"]._was_auto_paused = False
                    else:
                        status_lbl.configure(text="❌ Login failed — check credentials", text_color="#FF4444")
                        self._log("❌ Kotak reconnect failed — check Consumer Key")
                except Exception as ex:
                    status_lbl.configure(text=f"❌ Error: {ex}", text_color="#FF4444")
                    self._log(f"Kotak reconnect error: {ex}")

            import threading as _th
            _th.Thread(target=do_reconnect, daemon=True).start()

        ctk.CTkButton(
            tab_k, text="💾 Save & Reconnect Kotak",
            fg_color="#006600", hover_color="#008800",
            font=ctk.CTkFont(weight="bold"), width=380,
            command=save_and_reconnect_kotak
        ).pack(pady=8)


    def _start_background_tasks(self):
        threading.Thread(target=self._initialize_system, daemon=True).start()
        self._gui_update_loop()

    def _initialize_system(self):
        p = "config/config.json"
        if not os.path.exists(p):
            self._log("Error: config/config.json not found! Creating default...")
            os.makedirs("config", exist_ok=True)
            self._write_default_config(p)
        
        # Robust JSON load — handle empty or corrupt file
        try:
            with open(p, encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                self._log("⚠️ config.json is EMPTY! Restoring default config...")
                self._write_default_config(p)
                with open(p, encoding="utf-8") as f:
                    content = f.read()
            self.G["cfg"] = json.loads(content)
        except json.JSONDecodeError as e:
            self._log(f"❌ config.json is corrupted ({e})! Restoring default...")
            self._write_default_config(p)
            with open(p, encoding="utf-8") as f:
                self.G["cfg"] = json.load(f)
        cfg = self.G["cfg"]

        # ── Weekend Auto-Shutdown Check ──
        now_dt = datetime.now()
        is_weekend = now_dt.weekday() >= 5
        is_muhurat = cfg.get("option_trading", {}).get("muhurat_trading", False)
        if is_weekend and not is_muhurat:
            self._log("🚨 Weekend Detected (Saturday/Sunday)! Auto-Shutdown Initiated.")
            try:
                if self.G.get("bot"):
                    self.G["bot"]._send("💤 Weekend Detected! Software Auto-Shutdown. Have a great weekend!")
            except: pass
            import sys
            sys.exit(0)

        self.G["status"]["mode"] = cfg.get("option_trading", {}).get("mode", "paper")
        if self.G["status"]["mode"] == "live":
            self.mode_toggle_btn.configure(text="Mode: LIVE (Click to PAPER)", fg_color="red", hover_color="darkred", text_color="white")
        else:
            self.mode_toggle_btn.configure(text="Mode: PAPER (Click to LIVE)", fg_color="#DAA520", hover_color="#B8860B", text_color="black")

        self.G["bot"] = TelegramBot(cfg.get("telegram_bot", {}))
        # Send Startup Mantra to Telegram Bot
        try:
            startup_msg = "॥ ॐ श्री गणेशाय नमः ॥\n॥ श्री शिवाय नमस्तुभ्यं ॥\n॥ जय श्री सांवरीया सेठ जी ॥\n॥ लक्ष्मी कुबेर की कृपा ॥\n\nLKS WealthTech V21 Trading System Started!\nReady for Auto Scalping."
            self.G["bot"]._send(startup_msg)
        except: pass

        self.G["cap"] = CapitalManager(cfg)
        self._log(f"Capital loaded: ₹{self.G['cap'].current:,.2f}")

        # Update INDEX_MAP with custom symbols from config
        custom_syms = cfg.get("custom_symbols", {})
        for k, v in custom_syms.items():
            if k in INDEX_MAP:
                exch, _ = INDEX_MAP[k]
                INDEX_MAP[k] = (exch, v)
                self._log(f"Mapped {k} to exact Kotak string: {v}")

        kc = cfg.get("kotak", {})


        # Initialize Kotak
        api = KotakNeoAPI(kc)
        try:
            if api.login():
                self.G["api"] = api
                self.G["status"]["kotak"] = True
                self.kotak_label.configure(text="Kotak API: Connected", text_color="green")
                self._log("Kotak API login successful.")
                
                # New: Sync Master Scrip for auto-lot sizes and symbols
                self._log("🔄 Syncing Scrip Master (Lot sizes & Symbols)...")
                api.sync_master_scrip()
                
                # Fetch Real Margin
                try:
                    limits = api.get_limits()
                    real_margin = 0
                    if limits:
                        if "avlCash" in limits:
                            real_margin = float(limits["avlCash"])
                        elif "data" in limits:
                            cash = limits["data"].get("equityLimit", limits["data"].get("cash", {}))
                            real_margin = float(cash.get("availableMargin", cash.get("net", 0)))
                        
                    positions = api.get_positions()
                    active_pos_count = len([p for p in positions if int(p.get('netTrdQty', 0)) != 0]) if positions else 0
                    
                    self.real_margin_label.configure(text=f"Kotak Cash: ₹{real_margin:,.2f} | Active Pos: {active_pos_count}")
                    
                    if real_margin > 0 and self.G["status"]["mode"] != "paper":
                        # self.G["cap"].sync_real_capital(real_margin) # Disabled to fix 1 lot issue
                        self._log(f"Real Kotak Margin available: ₹{real_margin:,.2f} (Using software tracking capital for lot size)")
                except Exception as ex:
                    self._log(f"Could not fetch real margin: {ex}")
            else:
                self._log("Kotak login failed - falling back to paper mode demo prices.")
        except Exception as e:
            self._log(f"Kotak login error: {e}")

        try:
            self.G["db"] = DBManager()
            self._log("Connected to Microsoft SQL Server Database.")
            
            # Initialize AI Director and run morning analysis
            self.G["ai"] = AIDirector(self.G["db"])
            self.G["ai"].morning_analysis()
            
            self._log(f"🤖 AI Director Selected Strategy: {self.G['ai'].primary_strategy}")
            self.strategy_label.configure(text=f"Current Strategy: 🚀 {self.G['ai'].primary_strategy} (AI Managed)", text_color="#00FF00")
            
        except Exception as e:
            self._log(f"Database/AI connection error: {e}")

        self.G["trader"] = OptionChainTrader(
            kotak_api=self.G["api"] or api,
            capital_mgr=self.G["cap"],
            cfg=cfg,
            bot=self.G["bot"],
            db=self.G.get("db")
        )
        
        # Fix 6: Link AI Director to trader so strategy bias is used in auto-trading
        if self.G.get("ai"):
            self.G["trader"].ai_director = self.G["ai"]
            self._log("🤖 AI Director linked to trader successfully!")

        threading.Thread(target=self._price_loop, daemon=True).start()
        
        tg_cfg = cfg.get("telegram_reader", {})
        if tg_cfg.get("api_id") and tg_cfg["api_id"] != 0:
            threading.Thread(target=self._tg_reader_thread, args=(tg_cfg,), daemon=True).start()

        # Start Webhook Server for TradingView Signals
        try:
            self.webhook = TradingViewWebhook(port=8080, bot=self.G["bot"], trader=self.G["trader"])
            self.webhook.start()
            self._log("⚡ TradingView Webhook Server Started on Port 8080")
        except Exception as e:
            self._log(f"Failed to start Webhook Server: {e}")

        self.status_label.configure(text="System: Active", text_color="green")

    def _tg_reader_thread(self, cfg):
        def cb(sig):
            # Display Raw Telegram Message in the UI
            now = datetime.now().strftime("%H:%M:%S")
            disp_msg = f"[{now}] From: {sig.channel}\n{sig.raw}\n{'-'*30}\n"
            
            def _update_ui():
                try:
                    self.tg_textbox.insert(ctk.END, disp_msg)
                    self.tg_textbox.see(ctk.END)
                except: pass
            self.after(0, _update_ui)
            
            if sig.valid and self.G["trader"]:
                self._log(f"Signal Received: {sig.action} {sig.symbol} {sig.option_type}")
                self.G["trader"].process_telegram_signal(sig)
                
        def on_connect(count):
            self.tg_label.configure(text=f"Telegram: Connected ({count} ch)", text_color="green")
            self._log(f"Telegram connected monitoring {count} channels")
        def get_otp_sync():
            otp = [None]
            ev = threading.Event()
            def ask():
                dialog = ctk.CTkInputDialog(text="Enter Telegram OTP code sent to your app:", title="Telegram Login")
                otp[0] = dialog.get_input()
                ev.set()
            self.after(0, ask)
            ev.wait()
            return otp[0]

        async def run():
            reader = TelegramReader(cfg, cb, self.G["bot"], otp_callback=get_otp_sync, on_connect=on_connect)
            await reader.start()
            
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try: loop.run_until_complete(run())
        except Exception as e: self._log(f"Telegram reader error: {e}")
        finally: loop.close()

    def _price_loop(self):
        from datetime import datetime
        self._last_reset_date = None  # Track daily reset
        self._offline_warned  = False
        while True:
            # ── DAILY RESET at 9:15 AM ──────────────────────────────────
            now_dt   = datetime.now()
            today_str = now_dt.strftime("%Y-%m-%d")
            if (now_dt.hour == 9 and now_dt.minute >= 15
                    and self._last_reset_date != today_str
                    and self.G.get("cap")):
                self.G["cap"].daily_reset()
                self._last_reset_date = today_str
                self._offline_warned  = False  # Reset warning for new day
                self._log(f"[{now_dt.strftime('%H:%M')}] Daily capital counters reset — {today_str}")
                if self.G.get("bot"):
                    self.G["bot"]._send(
                        f"\u2600\ufe0f <b>New Trading Day!</b>\n"
                        f"Capital: <code>\u20b9{self.G['cap'].current:,.0f}</code>\n"
                        f"Loss Limit: {self.G['cap'].daily_loss_pct}% | "
                        f"Profit Target: {self.G['cap'].daily_profit_pct}%\n"
                        f"Mode: <b>PAPER</b> (Real data, Virtual orders)"
                    )

            # ── REAL PRICES ONLY — 100% Live from Kotak API ─────────────
            if self.G.get("api") and self.G["status"].get("kotak"):
                if self._offline_warned:
                    # Kotak just reconnected — resume auto trading
                    self._offline_warned = False
                    self._log("✅ Kotak API reconnected — auto trading RESUMED with real prices!")
                    if self.G.get("trader") and hasattr(self.G["trader"], '_was_auto_paused'):
                        if self.G["trader"]._was_auto_paused:
                            self.G["trader"].auto_trade = True
                            self.G["trader"]._was_auto_paused = False
                    if self.G.get("bot"):
                        self.G["bot"]._send("✅ <b>Kotak API Reconnected!</b>\nAuto Trading RESUMED with real market prices.")

                for sym, (exch, idx) in INDEX_MAP.items():
                    try:
                        ltp = None
                        if exch == "mt5":
                            if self.G.get("mt5") and self.G["status"].get("mt5"):
                                tick = self.G["mt5"].get_price(idx)
                                if tick: ltp = float(tick.get("bid", 0))
                        else:
                            # Wrap individual API calls to prevent blocking
                            try:
                                if exch == "mcx_fo":
                                    actual_idx = self.G["api"].get_active_mcx_symbol(idx)
                                    raw = self.G["api"].get_ltp(actual_idx, exch)
                                else:
                                    raw = self.G["api"].get_ltp(idx, exch)
                                if raw: ltp = float(raw)
                            except: ltp = None

                        if ltp and ltp > 0:
                            self.G["prices"][sym] = ltp
                            if self.G["trader"] and exch != "mt5": 
                                self.G["trader"].set_index_price(sym, ltp)
                            if self.G.get("db"): self.G["db"].log_tick(sym, ltp)
                        
                        time.sleep(0.15)
                    except Exception as e:
                        logger.debug(f"[PriceLoop] {sym}: {e}")

            else:
                # ── Kotak NOT connected — PAUSE auto trading, warn once ───
                if not self._offline_warned:
                    self._offline_warned = True
                    self._log("⚠️ Kotak API disconnected — PAUSING auto trades. No fake prices.")
                    logger.warning("[PriceLoop] Kotak offline — auto trade paused, no fake data.")
                    # Pause auto trading to prevent ₹50 fake price trades
                    if self.G.get("trader") and self.G["trader"].auto_trade:
                        self.G["trader"]._was_auto_paused = True
                        self.G["trader"].auto_trade = False
                        self._log("🛑 Auto trading paused until Kotak reconnects.")
                        if self.G.get("bot"):
                            self.G["bot"]._send(
                                "⚠️ <b>Kotak API Disconnected!</b>\n"
                                "Auto trading PAUSED.\n"
                                "System waiting for real market data.\n"
                                "No trades will be placed with fake prices."
                            )

            # Polling speed adjusted to 1.0 seconds to avoid Kotak Neo API rate limits
            time.sleep(1.0)

    def _gui_update_loop(self):
        # Update capital
        if self.G["cap"]:
            s = self.G["cap"].summary()
            self.cap_label.configure(text=f"Capital: ₹{s['current']:.2f} | Daily PnL: ₹{s['daily_pnl']:.2f} | Trades: {s['trades']}")
            self.stats_label.configure(text=f"Win Rate: {s['win_rate']}% | Sharpe: {s['sharpe']} | Sortino: {s['sortino']} | RRR: {s['rrr']} | Max DD: {s['max_drawdown_pct']}%")
        
        # Update Confluence Score (Dynamic calculation for NIFTY by default)
        if self.G.get("trader"):
            score = 0
            if "NIFTY" in self.G["trader"].smcs:
                smc = self.G["trader"].smcs["NIFTY"].state.structure
                if smc == "BULLISH": score += 25
                elif smc == "BEARISH": score += 25
                
            if "NIFTY" in self.G["trader"].filters:
                if self.G["trader"].filters["NIFTY"].check("CE").passed or self.G["trader"].filters["NIFTY"].check("PE").passed:
                    score += 25
            
            # OI Bias score
            oi = self.G["trader"].oi_engine.get_trade_bias("NIFTY")
            if oi != "NEUTRAL": score += 25
            
            # VWAP score (implied from momentum)
            if "NIFTY" in self.G["trader"].momentum_scalpers:
                if self.G["trader"].momentum_scalpers["NIFTY"].armed_direction:
                    score += 25
            
            self.score_bar.set(score / 100)
            self.score_label.configure(text=f"{score}%", text_color="#00FF00" if score >= 75 else ("#FFA500" if score >= 50 else "#FF4444"))
        
        # Display Active Trades in Strategy Label
        if self.G.get("trader"):
            trader = self.G["trader"]
            active_texts = []
            for pos in trader.positions.values():
                t1 = pos.targets[0] if pos.targets else 0
                t2 = pos.targets[1] if len(pos.targets)>1 else 0
                active_texts.append(f"🟢 {pos.option_symbol} (Entry: {pos.entry} | SL: {pos.sl} | T1: {t1} | T2: {t2})")
            
            if active_texts:
                self.strategy_label.configure(text=" | ".join(active_texts), text_color="#00FFFF")
            else:
                ai_strat = self.G.get("ai").primary_strategy if self.G.get("ai") else "LKS Auto Scalping"
                self.strategy_label.configure(text=f"Current Strategy: 🚀 {ai_strat} (Waiting for Trade...)", text_color="#FFA500")
        
        # Update prices
        for sym, p in self.G["prices"].items():
            if p > 0:
                self.price_labels[sym].configure(text=f"{sym}\n{p:.2f}")

        # Update PnL Chart
        if hasattr(self, 'ax') and hasattr(self, 'G') and self.G.get("cap"):
            # Auto Kill Switch Trigger
            loss_pct = abs(min(0, self.G["cap"].daily_pnl)) / max(1, self.G["cap"].current) * 100
            if loss_pct >= self.G["cap"].daily_loss_pct and self.kill_switch_btn.cget("state") != "disabled":
                self._activate_kill_switch()
                
            if not hasattr(self, 'pnl_history'):
                self.pnl_history = []
            
            # Record current PnL for the graph
            self.pnl_history.append(self.G["cap"].daily_pnl)
            
            # Keep last 100 data points to make the chart look moving
            if len(self.pnl_history) > 100:
                self.pnl_history.pop(0)
                
            self.ax.clear()
            self.ax.set_facecolor('#001100')
            self.ax.tick_params(colors='white', labelsize=8)
            
            # Color Green if profit, Red if loss
            color = '#00FF00' if self.pnl_history[-1] >= 0 else '#FF4444'
            self.ax.plot(self.pnl_history, color=color, linewidth=2)
            self.ax.set_title("Live Daily PnL", color='#FFD700', fontsize=10)
            self.ax.grid(True, linestyle='--', alpha=0.3, color='grey')
            
            # Update Candlestick Chart
            if hasattr(self, 'ax_candle'):
                self.ax_candle.clear()
                self.ax_candle.set_facecolor('#001100')
                self.ax_candle.tick_params(colors='white', labelsize=8)
        
        # Periodic Kotak Status Update (Every 30 iterations ~ 30 seconds)
        if not hasattr(self, '_kotak_refresh_counter'):
            self._kotak_refresh_counter = 0
        
        self._kotak_refresh_counter += 1
        if self._kotak_refresh_counter >= 30:
            self._kotak_refresh_counter = 0
            if self.G.get("api") and self.G["status"].get("kotak"):
                def fetch_status():
                    try:
                        limits = self.G["api"].get_limits()
                        real_margin = 0
                        if limits:
                            # Try multiple possible keys based on different Kotak response versions
                            if "avlCash" in limits:
                                real_margin = float(limits["avlCash"])
                            elif "data" in limits:
                                d = limits["data"]
                                if isinstance(d, dict):
                                    # Try Equity/Commodity/Cash paths
                                    eq = d.get("equityLimit", d.get("cash", {}))
                                    com = d.get("commodityLimit", {})
                                    real_margin = float(eq.get("availableMargin", eq.get("net", 0))) + \
                                                  float(com.get("availableMargin", com.get("net", 0)))
                                elif isinstance(d, list) and len(d) > 0:
                                    real_margin = float(d[0].get("availableMargin", d[0].get("net", 0)))
                        
                        # New: Fetch Portfolio Holdings
                        holdings = self.G["api"].get_holdings_v2()
                        portfolio_value = 0
                        if isinstance(holdings, list):
                            for h in holdings:
                                # Standard Kotak fields for current value
                                # marketValue usually includes investment + profit
                                portfolio_value += float(h.get("marketValue", h.get("curVal", 0)))
                                # If marketValue is 0, try adding invested + unrealised profit
                                if portfolio_value == 0:
                                    portfolio_value += float(h.get("investedValue", 0)) + float(h.get("unrealisedGainLoss", 0))

                        positions = self.G["api"].get_positions()
                        active_pos_count = 0
                        if isinstance(positions, list):
                            # Filter only truly open positions (where net qty != 0)
                            active_pos_count = len([p for p in positions if int(p.get('netTrdQty', 0)) != 0])
                        
                        def update_ui():
                            self.real_margin_label.configure(text=f"Kotak Cash: ₹{real_margin:,.2f} | Portfolio: ₹{portfolio_value:,.2f} | Active Pos: {active_pos_count}")
                        self.after(0, update_ui)
                    except: pass
                threading.Thread(target=fetch_status, daemon=True).start()
                
                selected_sym = self.chart_symbol_var.get()
                self.ax_candle.set_title(f"{selected_sym} Live Candles", color='#FFD700', fontsize=10)
                
                if self.G.get("trader"):
                    trader = self.G["trader"]
                    if selected_sym in trader.candle_analyzers:
                        # Draw last 60 candles max for better visual clarity
                        candles = trader.candle_analyzers[selected_sym].engine.candles[-60:]
                        if candles:
                            import numpy as np
                            import matplotlib.patches as patches
                            for i, c in enumerate(candles):
                                c_color = '#00FF00' if c.close >= c.open else '#FF4444'
                                self.ax_candle.plot([i, i], [c.low, c.high], color=c_color, linewidth=1)
                                bottom = min(c.open, c.close)
                                height = max(abs(c.close - c.open), 0.05)
                                rect = patches.Rectangle((i - 0.3, bottom), 0.6, height, facecolor=c_color, edgecolor=c_color)
                                self.ax_candle.add_patch(rect)
                                
                                # Draw Buy/Sell markers if any
                                if getattr(c, 'markers', None):
                                    for m_txt, m_color in c.markers:
                                        if m_txt == "B":
                                            self.ax_candle.annotate("B", (i, c.low - 0.05), color=m_color, fontsize=10, ha='center', va='top')
                                        else:
                                            self.ax_candle.annotate("S", (i, c.high + 0.05), color=m_color, fontsize=10, ha='center', va='bottom')
                            
                            min_y = min(c.low for c in candles)
                            max_y = max(c.high for c in candles)
                            padding = (max_y - min_y) * 0.05 if max_y > min_y else 1
                            self.ax_candle.set_ylim(min_y - padding, max_y + padding)
                            self.ax_candle.set_xlim(-1, len(candles))
                
                self.ax_candle.grid(True, linestyle='--', alpha=0.3, color='grey')

            try:
                self.canvas.draw_idle()
            except: pass

        # Update XM Balance if connected
        if self.G.get("mt5") and self.G["status"]["mt5"]:
            try:
                bal = self.G["mt5"].get_balance()
                if bal > 0:
                    self.xm_margin_label.configure(text=f"XM Live Balance: ${bal:,.2f}")
            except: pass

        # Auto-Shutdown at 23:58 (After MCX Market Closes)
        now = datetime.now()
        if now.hour == 23 and now.minute >= 58:
            self._log("MCX Market Closed. Initiating Auto-Shutdown...")
            try:
                if self.G.get("trader"): self.G["trader"]._square_off_all()
                if self.G.get("bot"): self.G["bot"]._send("💤 System Auto-Shutdown (Night Mode). See you at 8:30 AM!")
            except: pass
            import os
            os._exit(0)

        self.after(1000, self._gui_update_loop)

if __name__ == "__main__":
    app = LKSWealthTechApp()
    app.mainloop()
