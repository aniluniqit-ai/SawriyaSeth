import pandas as pd
import logging
from ai_director import AIDirector
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("BacktestEngine")

class BacktestEngine:
    def __init__(self):
        self.ai = AIDirector()
        
    def generate_dummy_data(self):
        """Generates dummy OHLCV data for testing the framework if no CSV is present."""
        import numpy as np
        dates = pd.date_range("2024-01-01", periods=1000, freq="5min")
        prices = np.random.normal(0, 10, size=1000).cumsum() + 20000
        vwap = prices * 0.999
        ema9 = prices * 1.001
        ema21 = prices * 0.998
        
        # 0: BEARISH, 1: SIDEWAYS, 2: BULLISH
        trends = np.random.randint(0, 3, size=1000)
        
        df = pd.DataFrame({
            "timestamp": dates,
            "close": prices,
            "vwap": vwap,
            "ema9": ema9,
            "ema21": ema21,
            "vwap_dist": (prices - vwap)/vwap * 100,
            "ema_diff": (ema9 - ema21)/ema21 * 100,
            "momentum": np.random.normal(0, 0.5, 1000),
            "volatility": np.random.uniform(5, 20, 1000),
            "trend": trends
        })
        return df

    def run(self, csv_file=None):
        logger.info("Starting Backtest Engine...")
        if csv_file and os.path.exists(csv_file):
            logger.info(f"Loading data from {csv_file}")
            df = pd.read_csv(csv_file)
        else:
            logger.warning("No CSV provided or file not found. Generating dummy data for test.")
            df = self.generate_dummy_data()
            
        # Step 1: Train AI
        logger.info("Training AI Director on historical data...")
        self.ai.train_model(df)
        
        # Step 2: Simulate Live Market
        logger.info("Simulating live market...")
        
        bullish_count = 0
        bearish_count = 0
        sideways_count = 0
        
        for idx, row in df.tail(100).iterrows(): # Test on last 100 rows
            trend = self.ai.analyze_live_market(
                "NIFTY", 
                row['close'], 
                row['vwap'], 
                row['ema9'], 
                row['ema21']
            )
            if trend == "TRENDING_BULLISH": bullish_count += 1
            elif trend == "TRENDING_BEARISH": bearish_count += 1
            else: sideways_count += 1
            
        logger.info(f"Backtest Results (Last 100 periods):")
        logger.info(f"BULLISH predictions: {bullish_count}")
        logger.info(f"BEARISH predictions: {bearish_count}")
        logger.info(f"SIDEWAYS predictions: {sideways_count}")
        logger.info("Backtest Complete.")

if __name__ == "__main__":
    engine = BacktestEngine()
    engine.run()
