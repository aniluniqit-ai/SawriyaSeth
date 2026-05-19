import logging
from flask import Flask, request, jsonify
import threading

logger = logging.getLogger("WebhookServer")

class TradingViewWebhook:
    def __init__(self, port=8080, bot=None, trader=None):
        self.port = port
        self.app = Flask(__name__)
        self.bot = bot
        self.trader = trader
        
        # Disable Flask default logging to avoid clutter
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)

        @self.app.route('/tv-signal', methods=['POST'])
        def handle_signal():
            try:
                data = request.json
                logger.info(f"Webhook Received: {data}")
                
                # Expected format:
                # {
                #   "action": "BUY",
                #   "symbol": "BANKNIFTY",
                #   "option_type": "CE",
                #   "confidence": 95,
                #   "channel": "tradingview_webhook"
                # }
                
                if not data or "action" not in data or "symbol" not in data:
                    return jsonify({"error": "Invalid format"}), 400
                    
                if self.trader:
                    from signal_parser import ParsedSignal
                    sig = ParsedSignal(
                        valid=True,
                        action=data.get("action", "BUY"),
                        symbol=data.get("symbol"),
                        option_type=data.get("option_type", "CE"),
                        strike=int(data.get("strike", 0)),
                        entry=float(data.get("entry", 0)),
                        sl=float(data.get("sl", 0)),
                        targets=[],
                        confidence=int(data.get("confidence", 95)),
                        channel=data.get("channel", "tradingview_webhook")
                    )
                    sig.reason = data.get("reason", "TradingView Webhook Alert")
                    
                    # Process signal in a new thread to avoid blocking webhook
                    threading.Thread(target=self.trader.process_telegram_signal, args=(sig,), daemon=True).start()
                    
                    if self.bot:
                        self.bot._send(f"⚡ <b>WEBHOOK SIGNAL RECEIVED</b> ⚡\n"
                                       f"Symbol: {sig.symbol} {sig.option_type}\n"
                                       f"Executing trade...")
                                       
                return jsonify({"status": "success", "message": "Signal processing started"}), 200
                
            except Exception as e:
                logger.error(f"Webhook error: {e}")
                return jsonify({"error": str(e)}), 500

    def start(self):
        def run_server():
            logger.info(f"Starting TradingView Webhook server on port {self.port}...")
            # Run without reloader so it doesn't block or restart the GUI
            self.app.run(host='0.0.0.0', port=self.port, debug=False, use_reloader=False)
            
        threading.Thread(target=run_server, daemon=True).start()
