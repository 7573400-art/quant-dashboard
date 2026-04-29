import sqlite3
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

JSON_FILE = 'service_account.json'
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_FILE, scope)
client = gspread.authorize(creds)
doc = client.open("MyQuant_Data")
sheet_watch = doc.worksheet("Watchlist")
sheet_log = doc.worksheet("Log")

conn = sqlite3.connect('myquant.db')
cursor = conn.cursor()

# Create Watchlist table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS watchlist (
        ticker TEXT PRIMARY KEY,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

# Create Log table
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

# Migrate Watchlist
watch_data = sheet_watch.col_values(1)[1:]
for ticker in watch_data:
    ticker = ticker.strip().upper()
    if ticker:
        cursor.execute("INSERT OR IGNORE INTO watchlist (ticker) VALUES (?)", (ticker,))

# Migrate Log
log_data = sheet_log.get_all_values()
if len(log_data) > 1:
    for row in log_data[1:]:
        if len(row) >= 6:
            r_date = row[0]
            r_ticker = row[1]
            try:
                r_score = int(row[2])
            except:
                r_score = 0
            
            try:
                r_curr = float(str(row[3]).replace(',', '').replace('₩', '').replace('$', ''))
                r_target = float(str(row[4]).replace(',', '').replace('₩', '').replace('$', ''))
            except:
                continue
                
            r_signal = row[5]
            
            r_horizon = 5
            if len(row) >= 7:
                try:
                    r_horizon = int(row[6])
                except:
                    pass
            
            cursor.execute('''
                INSERT INTO log (date, ticker, score, curr_price, target_price, signal, horizon)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (r_date, r_ticker, r_score, r_curr, r_target, r_signal, r_horizon))

conn.commit()
conn.close()
print("Migration completed to myquant.db!")
