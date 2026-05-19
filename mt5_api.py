import MetaTrader5 as mt5
import logging

logger = logging.getLogger("MT5_API")

class MT5Trader:
    def __init__(self):
        self.connected = False
        self.account_info = None

    def login(self, login_id, password, server):
        """Initialize and login to MT5"""
        if not mt5.initialize():
            logger.error(f"MT5 initialize() failed, error code: {mt5.last_error()}")
            return False

        try:
            authorized = mt5.login(login=int(login_id), password=password, server=server)
            if authorized:
                self.connected = True
                self.account_info = mt5.account_info()
                logger.info(f"Connected to MT5 - Server: {server}, Account: {login_id}")
                logger.info(f"MT5 Balance: {self.account_info.balance}, Equity: {self.account_info.equity}")
                return True
            else:
                logger.error(f"MT5 failed to connect to account {login_id}, error code: {mt5.last_error()}")
                return False
        except Exception as e:
            logger.error(f"MT5 Login Exception: {e}")
            return False

    def get_balance(self):
        if not self.connected: return 0.0
        acc = mt5.account_info()
        return acc.balance if acc else 0.0

    def get_price(self, symbol):
        """Get current Ask/Bid for a symbol (e.g. XAUUSD)"""
        if not self.connected: return None
        # Symbol mapping handling XAUUSD vs GOLD etc.
        actual_sym = "XAUUSD" if symbol.upper() in ["GOLD", "XAU/USD"] else symbol.upper()
        
        tick = mt5.symbol_info_tick(actual_sym)
        if tick:
            return {"bid": tick.bid, "ask": tick.ask}
        return None

    def place_order(self, symbol, action, volume, sl=0.0, tp=0.0):
        """Action: 'BUY' or 'SELL'. Forex has no CE/PE, just Long/Short."""
        if not self.connected: return False

        actual_sym = "XAUUSD" if symbol.upper() in ["GOLD", "XAU/USD"] else symbol.upper()
        
        # Ensure symbol is visible in market watch
        if not mt5.symbol_select(actual_sym, True):
            logger.error(f"Symbol {actual_sym} not found or not visible in MT5")
            return False

        tick = mt5.symbol_info_tick(actual_sym)
        if not tick:
            return False
            
        if action.upper() == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        elif action.upper() == "SELL":
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            return False

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": actual_sym,
            "volume": float(volume),
            "type": order_type,
            "price": price,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": 20, # Slippage tolerance
            "magic": 100100, # Bot ID
            "comment": "LKS_AI_Trade",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"MT5 Order SUCCESS: {action} {actual_sym} Vol:{volume} Price:{price}")
            return True
        else:
            logger.error(f"MT5 Order failed, retcode={(result.retcode if result else 'None')}")
            return False
            
    def shutdown(self):
        if self.connected:
            mt5.shutdown()
            self.connected = False
