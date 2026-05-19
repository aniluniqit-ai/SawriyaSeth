"""
Capital Manager — LKS WealthTech V21
Req 11: Daily reset at 9:15 AM
"""
import json, os, logging
from datetime import datetime, date
logger = logging.getLogger("Capital")

class CapitalManager:

    def __init__(self, cfg:dict):
        c = cfg.get("capital", {})
        self.initial    = c.get("initial_capital", 1000)
        self.current    = self.initial
        self.peak       = self.initial
        self.daily_pnl  = 0.0
        self.total_pnl  = 0.0
        self.trades     = 0
        self.wins       = 0
        self.losses     = 0
        self.max_drawdown = 0.0
        self.today      = str(date.today())
        self.daily_loss_pct   = c.get("daily_loss_limit_pct", 10)
        self.max_daily_loss   = c.get("max_daily_loss_amount", 200) # Absolute Limit
        self.daily_profit_pct = c.get("daily_profit_target_pct", 20)
        
        # Risk Reward Tracking
        self.total_win_amount = 0.0
        self.total_loss_amount = 0.0
        
        # Advanced Metrics: Track returns for Sharpe/Sortino
        self.trade_returns = [] # List of PnL amounts for each trade
        
        self._load()

    def _load(self):
        p = "logs/capital.json"
        if os.path.exists(p):
            try:
                with open(p) as f: d = json.load(f)
                self.current   = d.get("current", self.initial)
                self.peak      = d.get("peak", self.current)
                self.total_pnl = d.get("total_pnl", 0)
                self.max_drawdown = d.get("max_drawdown", 0.0)
                self.total_win_amount = d.get("total_win_amount", 0.0)
                self.total_loss_amount = d.get("total_loss_amount", 0.0)
                self.trade_returns = d.get("trade_returns", [])
                if d.get("today") == self.today:
                    self.daily_pnl = d.get("daily_pnl", 0)
                    self.trades    = d.get("trades", 0)
                    self.wins      = d.get("wins", 0)
                    self.losses    = d.get("losses", 0)
                logger.info(f"Capital loaded: ₹{self.current:,.0f}")
            except: pass

    def _save(self):
        os.makedirs("logs", exist_ok=True)
        with open("logs/capital.json","w") as f:
            json.dump({
                "current": self.current, "peak": self.peak,
                "total_pnl": self.total_pnl, "daily_pnl": self.daily_pnl,
                "trades": self.trades, "wins": self.wins, "losses": self.losses,
                "max_drawdown": self.max_drawdown,
                "total_win_amount": self.total_win_amount,
                "total_loss_amount": self.total_loss_amount,
                "trade_returns": self.trade_returns[-500:], # keep last 500
                "today": self.today, "initial": self.initial
            }, f, indent=2)

    def daily_reset(self):
        """Reset daily counters only — capital carries forward (compounding)"""
        self.today      = str(date.today())
        self.daily_pnl  = 0
        self.trades     = 0
        self.wins       = 0
        self.losses     = 0
        self._save()
        growth = ((self.current - self.initial) / self.initial * 100) if self.initial else 0
        logger.info(
            f"Capital daily reset — Current: ₹{self.current:,.0f} "
            f"| Initial: ₹{self.initial:,.0f} | Growth: {growth:+.1f}%"
        )

    def record(self, pnl:float):
        self.daily_pnl += pnl
        self.total_pnl += pnl
        self.current   += pnl
        self.current    = max(0, round(self.current, 2))
        self.trades    += 1
        
        self.trade_returns.append(pnl)
        
        if pnl > 0:
            self.wins += 1
            self.total_win_amount += pnl
        else:
            self.losses += 1
            self.total_loss_amount += abs(pnl)
            
        if self.current > self.peak:
            self.peak = self.current
        
        # Calculate Drawdown
        drawdown = self.peak - self.current
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
            
        self._save()

    def sync_real_capital(self, real_margin: float):
        """Syncs the current capital with actual Kotak Neo available margin"""
        if real_margin > 0:
            old = self.current
            self.current = round(real_margin, 2)
            if self.current > self.peak: self.peak = self.current
            self._save()
            logger.info(f"Synced real capital: {old} -> {self.current}")

    def can_trade(self, cost:float, max_positions:int, current_positions:int) -> tuple:
        # Req 6.3: cost check
        # Allow 100% usage for micro accounts (<= 10000), otherwise 80% usage
        max_allowed_cost = self.current if self.current <= 10000 else self.current * 0.8
        if cost > max_allowed_cost:
            return False, f"Cost ₹{cost:.0f} > allowed capital ₹{max_allowed_cost:.0f}"
        if current_positions >= max_positions:
            return False, f"Max positions {max_positions} reached"
        loss_pct = abs(min(0, self.daily_pnl)) / self.current * 100
        abs_loss = abs(min(0, self.daily_pnl))
        if loss_pct >= self.daily_loss_pct:
            return False, f"Daily loss limit {loss_pct:.1f}% hit"
        if abs_loss >= self.max_daily_loss:
            return False, f"Absolute daily loss limit ₹{abs_loss:.0f} hit"
        profit_pct = max(0, self.daily_pnl) / self.current * 100
        if profit_pct >= self.daily_profit_pct:
            return False, f"Daily profit target {profit_pct:.1f}% hit"
        return True, "OK"

    def risk_amount(self, pct:float=2.0) -> float:
        return self.current * pct / 100

    def calculate_sharpe(self) -> float:
        """Simplified Sharpe Ratio based on trade-by-trade returns"""
        if not self.trade_returns or len(self.trade_returns) < 5: return 0.0
        import statistics
        avg = statistics.mean(self.trade_returns)
        std = statistics.stdev(self.trade_returns)
        return round(avg / std, 2) if std > 0 else 0.0

    def calculate_sortino(self) -> float:
        """Simplified Sortino Ratio (only considers downside risk)"""
        if not self.trade_returns or len(self.trade_returns) < 5: return 0.0
        import statistics
        avg = statistics.mean(self.trade_returns)
        downside = [r for r in self.trade_returns if r < 0]
        if not downside: return 5.0 # Arbitrary high value if no losses
        std_down = statistics.stdev(downside) if len(downside) > 1 else abs(downside[0])
        return round(avg / std_down, 2) if std_down > 0 else 0.0

    def get_kelly_lots(self, lot_size_cost: float, max_lots: int = 10) -> int:
        """
        Calculate optimal position size using Kelly Criterion.
        Kelly % = W - [(1 - W) / R]
        W = Win probability
        R = Risk/Reward Ratio
        """
        if self.trades < 5:
            return 1 # Not enough data, stick to 1 lot
            
        win_rate = self.wins / self.trades
        avg_win = self.total_win_amount / max(1, self.wins)
        avg_loss = self.total_loss_amount / max(1, self.losses)
        
        if avg_loss == 0:
            return 1
            
        rrr = avg_win / avg_loss
        
        # Kelly Fraction
        kelly_pct = win_rate - ((1 - win_rate) / rrr)
        
        # Half-Kelly for safety (standard practice in trading)
        safe_kelly_pct = max(0, kelly_pct / 2)
        
        # Cap max risk at 10% of capital per trade regardless of Kelly
        safe_kelly_pct = min(safe_kelly_pct, 0.10)
        
        max_affordable_cost = self.current * safe_kelly_pct
        lots = int(max_affordable_cost // lot_size_cost)
        
        # Ensure at least 1 lot if we have enough capital, but cap at max_lots
        if lots < 1 and self.current >= lot_size_cost:
            lots = 1
            
        return min(lots, max_lots)

    def summary(self) -> dict:
        wr = self.wins/max(1,self.trades)*100
        avg_win = self.total_win_amount / max(1, self.wins)
        avg_loss = self.total_loss_amount / max(1, self.losses)
        rrr = avg_win / max(1, avg_loss)
        
        mdd_pct = (self.max_drawdown / self.peak * 100) if self.peak > 0 else 0
        
        return {
            "current": round(self.current, 2),
            "initial": self.initial,
            "peak": round(self.peak, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "total_pnl": round(self.total_pnl, 2),
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(wr, 1),
            "max_drawdown": round(self.max_drawdown, 2),
            "max_drawdown_pct": round(mdd_pct, 2),
            "rrr": round(rrr, 2),
            "sharpe": self.calculate_sharpe(),
            "sortino": self.calculate_sortino(),
            "growth_pct": round((self.current-self.initial)/self.initial*100, 2) if self.initial else 0
        }

