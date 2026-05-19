import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os

try:
    from sklearn.ensemble import RandomForestClassifier
    import joblib
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

logger = logging.getLogger("AIDirector")

class AIDirector:
    def __init__(self, db_manager=None):
        self.db = db_manager
        self.primary_strategy = "ML_SCALP" 
        self.market_trend = "SIDEWAYS"
        
        self.is_trained = False
        self.model_path = "models/ai_model.pkl"
        
        if HAS_SKLEARN:
            self.model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
            self.load_model()
        else:
            self.model = None
            logger.warning("scikit-learn not installed. AI Director will run in rule-based fallback mode.")
            
        self.history_buffer = [] # To store recent ticks for feature calculation

    def train_model(self, df: pd.DataFrame):
        """
        Expects a DataFrame with features: 
        ['vwap_dist', 'ema_diff', 'momentum', 'volatility']
        and target: 'trend' (0: BEARISH, 1: SIDEWAYS, 2: BULLISH)
        """
        if not HAS_SKLEARN:
            logger.error("scikit-learn not available. Cannot train ML model.")
            return False
            
        try:
            features = ['vwap_dist', 'ema_diff', 'momentum', 'volatility']
            if not all(f in df.columns for f in features) or 'trend' not in df.columns:
                logger.error("Missing required columns for ML training.")
                return False
                
            X = df[features]
            y = df['trend']
            
            logger.info(f"Training AI Model on {len(df)} samples...")
            self.model.fit(X, y)
            self.is_trained = True
            
            # Save model
            os.makedirs("models", exist_ok=True)
            joblib.dump(self.model, self.model_path)
            logger.info("AI Model trained and saved successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to train AI model: {e}")
            return False

    def load_model(self):
        if HAS_SKLEARN and os.path.exists(self.model_path):
            try:
                self.model = joblib.load(self.model_path)
                self.is_trained = True
                logger.info("Loaded pre-trained AI Model.")
            except Exception as e:
                logger.error(f"Failed to load AI model: {e}")

    def morning_analysis(self):
        """Run at 8:30 AM to analyze past data and set today's rules"""
        if not self.db or not self.db.conn:
            logger.warning("No DB connection for Morning Analysis.")
            return

        try:
            logger.info("AI Director starting morning analysis...")
            query = "SELECT Strategy, PnL, EntryTime FROM TradeLogs WHERE EntryTime >= GETDATE() - 5"
            df = pd.read_sql(query, self.db.conn)
            
            if not df.empty:
                df['IsWin'] = df['PnL'] > 0
                stats = df.groupby('Strategy').agg(
                    Trades=('PnL', 'count'),
                    Wins=('IsWin', 'sum'),
                    TotalPnL=('PnL', 'sum')
                )
                stats['WinRate'] = (stats['Wins'] / stats['Trades']) * 100
                logger.info(f"AI Morning Analysis - Past 5 Days:\n{stats}")
        except Exception as e:
            logger.error(f"Morning Analysis Failed: {e}")

    def analyze_live_market(self, index_symbol, current_price, vwap, ema9, ema21):
        """Analyze live data using ML to predict market trend"""
        
        # Calculate live features
        vwap_dist = (current_price - vwap) / max(vwap, 1) * 100
        ema_diff = (ema9 - ema21) / max(ema21, 1) * 100
        
        self.history_buffer.append(current_price)
        if len(self.history_buffer) > 20:
            self.history_buffer.pop(0)
            
        momentum = (current_price - self.history_buffer[0]) / self.history_buffer[0] * 100 if len(self.history_buffer) > 1 else 0
        volatility = np.std(self.history_buffer) if len(self.history_buffer) > 1 else 0
        
        # If model is trained, use it
        if HAS_SKLEARN and self.is_trained:
            try:
                features = pd.DataFrame([{
                    'vwap_dist': vwap_dist,
                    'ema_diff': ema_diff,
                    'momentum': momentum,
                    'volatility': volatility
                }])
                
                prediction = self.model.predict(features)[0]
                probabilities = self.model.predict_proba(features)[0]
                max_prob = max(probabilities) * 100
                
                trend_map = {0: "TRENDING_BEARISH", 1: "SIDEWAYS", 2: "TRENDING_BULLISH"}
                self.market_trend = trend_map.get(prediction, "SIDEWAYS")
                
                # Only trust strong predictions
                if max_prob < 60:
                    self.market_trend = "SIDEWAYS"
                    
                logger.debug(f"[ML Prediction] {self.market_trend} (Confidence: {max_prob:.1f}%)")
                return self.market_trend
            except Exception as e:
                logger.error(f"ML Prediction error: {e}")
                
        # Fallback to logic rules if ML fails or isn't trained
        if current_price > vwap and ema9 > ema21:
            self.market_trend = "TRENDING_BULLISH"
        elif current_price < vwap and ema9 < ema21:
            self.market_trend = "TRENDING_BEARISH"
        else:
            self.market_trend = "SIDEWAYS"
            
        return self.market_trend
