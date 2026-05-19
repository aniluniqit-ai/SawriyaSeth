import pyodbc
import logging
import pandas as pd
from datetime import datetime

logger = logging.getLogger("Database")

class DBManager:
    def __init__(self, server="WIN-640Q5QFSSBM", database="LKS_Trader_DB", username="sa", password="sa"):
        self.server = server
        self.database = database
        self.username = username
        self.password = password
        # You may need to change the Driver version depending on what's installed (e.g., 'ODBC Driver 17 for SQL Server' or 'SQL Server')
        self.conn_str = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={self.server};DATABASE={self.database};UID={self.username};PWD={self.password}'
        self.conn = None
        self.connect()

    def connect(self):
        try:
            self.conn = pyodbc.connect(self.conn_str)
            logger.info(f"Connected to SQL Server: {self.database}")
            self.create_tables()
        except Exception as e:
            logger.error(f"SQL Connection Failed (Make sure database '{self.database}' is created): {e}")

    def create_tables(self):
        if not self.conn: return
        try:
            cursor = self.conn.cursor()
            
            # Table 1: Market Data (Tick data / Candles)
            cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='MarketData' and xtype='U')
            CREATE TABLE MarketData (
                ID INT IDENTITY(1,1) PRIMARY KEY,
                Symbol VARCHAR(50),
                Price FLOAT,
                Timestamp DATETIME
            )
            ''')
            
            # Table 2: Trade Logs
            cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='TradeLogs' and xtype='U')
            CREATE TABLE TradeLogs (
                TradeID VARCHAR(50) PRIMARY KEY,
                Symbol VARCHAR(50),
                OptType VARCHAR(10),
                EntryPrice FLOAT,
                ExitPrice FLOAT,
                Qty INT,
                PnL FLOAT,
                Strategy VARCHAR(50),
                EntryTime DATETIME,
                ExitTime DATETIME
            )
            ''')
            
            self.conn.commit()
            logger.info("Database Tables Verified")
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")

    def log_tick(self, symbol, price):
        if not self.conn: return
        try:
            cursor = self.conn.cursor()
            cursor.execute("INSERT INTO MarketData (Symbol, Price, Timestamp) VALUES (?, ?, ?)",
                           symbol, price, datetime.now())
            self.conn.commit()
        except Exception as e:
            pass # Suppress tick errors to avoid log spam

    def log_trade(self, pos):
        if not self.conn: return
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
            INSERT INTO TradeLogs (TradeID, Symbol, OptType, EntryPrice, ExitPrice, Qty, PnL, Strategy, EntryTime, ExitTime) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', pos.id, pos.option_symbol, pos.option_type, pos.entry, pos.last_move_price, pos.qty, pos.pnl, pos.source, 
               datetime.fromtimestamp(pos.entry_time), datetime.now())
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error logging trade to SQL: {e}")

