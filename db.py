import sqlite3
import pandas as pd
import datetime

DB_PATH = 'myquant.db'

def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker TEXT PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                ticker TEXT,
                score INTEGER,
                curr_price REAL,
                target_price REAL,
                signal TEXT,
                horizon INTEGER
            )
        ''')
        conn.commit()
    finally:
        conn.close()

# 앱 실행 시 자동 초기화
init_db()

def get_watchlist():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ticker FROM watchlist ORDER BY added_at ASC")
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()

def add_watchlist(ticker):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO watchlist (ticker) VALUES (?)", (ticker.strip().upper(),))
        conn.commit()
    finally:
        conn.close()

def remove_watchlist(ticker):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker.strip().upper(),))
        conn.commit()
    finally:
        conn.close()

def get_log_data(as_dataframe=False):
    conn = get_connection()
    try:
        # Return equivalent of sheet_log.get_all_values()
        # [Date, Ticker, Score, Price, TargetPrice, Signal, Horizon]
        cursor = conn.cursor()
        cursor.execute("SELECT date, ticker, score, curr_price, target_price, signal, horizon FROM log ORDER BY id ASC")
        rows = cursor.fetchall()
        
        # Adding header for backwards compatibility with get_all_values()
        header = ["Date", "Ticker", "Score", "Price", "TargetPrice", "Signal", "TargetDays"]
        data = [header] + [list(row) for row in rows]
        
        if as_dataframe:
            # Drop header row for dataframe creation if needed
            return pd.DataFrame(data[1:], columns=header)
        return data
    finally:
        conn.close()

def append_log(date, ticker, score, curr_price, target_price, signal, horizon=5):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO log (date, ticker, score, curr_price, target_price, signal, horizon)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (date, ticker.strip().upper(), score, curr_price, target_price, signal, horizon))
        conn.commit()
    finally:
        conn.close()
