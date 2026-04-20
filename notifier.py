import FinanceDataReader as fdr
import pandas as pd
import requests
import datetime
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
JSON_FILE = 'service_account.json'

# --- 1. 구글 스프레드시트 인증 및 연결 ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_FILE, scope)
client = gspread.authorize(creds)

# 시트 열기 (파일명: MyQuant_Data)
try:
    doc = client.open("MyQuant_Data")
    sheet_watch = doc.worksheet("Watchlist")
    sheet_log = doc.worksheet("Log")
except Exception as e:
    print(f"❌ 구글 시트 연결 실패: {e}")
    exit()

def send_msg(text):
    if not TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, data=payload)

def get_stock_info(ticker):
    """지표 계산 및 퀀트 점수 산출"""
    try:
        df = fdr.DataReader(ticker, start=(datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d'))
        if len(df) < 200: return None
        
        df['SMA_20'] = df['Close'].rolling(20).mean()
        df['SMA_50'] = df['Close'].rolling(50).mean()
        df['SMA_200'] = df['Close'].rolling(200).mean()
        df['RVOL'] = df['Volume'] / df['Volume'].rolling(20).mean()
        
        # 추가 추세/모멘텀 지표 계산 (RSI, MACD, ATR)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
        
        high_low = df['High'] - df['Low']
        high_close = (df['High'] - df['Close'].shift()).abs()
        low_close = (df['Low'] - df['Close'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        df['ATR'] = true_range.rolling(14).mean()
        
        latest, prev = df.iloc[-1], df.iloc[-2]
        curr_price = latest['Close']
        score = 0
        
        # 스코어링 최적화 (100점 만점)
        # 1. 이동평균 추세 (30점)
        if latest['SMA_20'] > latest['SMA_50']: score += 15
        if latest['SMA_50'] > latest['SMA_200']: score += 15
        
        # 2. RSI 모멘텀/과매수 필터 (20점)
        rsi = latest['RSI']
        if 40 <= rsi <= 70: score += 20
        elif rsi > 75: score -= 10 # 과매수 페널티
        
        # 3. RVOL 거래량 완화 (15점)
        rvol = latest['RVOL']
        if rvol >= 1.2: score += 15
        
        # 4. MACD 모멘텀 (20점)
        if latest['MACD'] > latest['Signal_Line'] or (latest['MACD'] - latest['Signal_Line']) > (prev['MACD'] - prev['Signal_Line']):
            score += 20
            
        # 5. 당일 강세 및 돌파 (15점)
        if curr_price > prev['High'] and curr_price > latest['Open']: 
            score += 15
        
        # 스코어 범위 클리핑
        score = int(max(0, min(100, score)))
        
        # 동적 목표가 (Target Price) 산출: 스코어에 맞춰 목표 ATR을 1.0~2.0배 곱함
        atr_val = latest['ATR'] if not pd.isna(latest['ATR']) else (curr_price * 0.05)
        atr_multiplier = 1.0 + ((score / 100) * 1.0)
        target_price = curr_price + (atr_val * atr_multiplier)
        
        return {'score': score, 'curr_price': curr_price, 'target_price': target_price}
    except:
        return None

if __name__ == "__main__":
    # --- 2. 구글 시트에서 티커 리스트 가져오기 ---
    # Watchlist 탭의 첫 번째 열(A열)에서 헤더를 제외한 모든 티커를 읽어옵니다.
    tickers = sheet_watch.col_values(1)[1:] 
    
    if not tickers:
        print("💡 분석할 종목이 시트에 없습니다.")
        exit()

    buy_signals = []
    sell_signals = []
    now_date = datetime.datetime.now().strftime('%Y-%m-%d')
    report_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    for t in tickers:
        t = t.strip().upper()
        data = get_stock_info(t)
        
        if data:
            score = data['score']
            curr = data['curr_price']
            target = data['target_price']
            
            # 신호 분류
            signal_type = "HOLD"
            if score >= 70: signal_type = "BUY"
            elif score <= 30: signal_type = "SELL"

            # --- 3. 구글 시트 'Log' 탭에 결과 기록 ---
            try:
                sheet_log.append_row([
                    report_time, 
                    t, 
                    score, 
                    round(curr, 2), 
                    round(target, 2), 
                    signal_type,
                    5 # Default Horizon
                ])
            except Exception as e:
                print(f"⚠️ 구글 시트 로그 기록 실패({t}): {e}")

            # 4. 텔레그램 메시지용 화폐 포맷팅
            if t.isdigit():
                curr_fmt, target_fmt = f"₩{int(curr):,}", f"₩{int(target):,}"
            else:
                curr_fmt, target_fmt = f"${curr:.2f}", f"${target:.2f}"
            
            # 신호 리스트에 추가
            if signal_type == "BUY":
                buy_signals.append(f"🔴 *{t}*: {score}점\n   - 현재: {curr_fmt} / 예측: {target_fmt}")
            elif signal_type == "SELL":
                sell_signals.append(f"🔵 *{t}*: {score}점\n   - 현재: {curr_fmt} / 예측: {target_fmt}")

    # --- 5. 텔레그램 리포트 발송 ---
    report = [f"📅 *퀀트 신호 리포트 ({report_time})*"]
    
    if buy_signals:
        report.append("\n🚀 *[강력 매수 후보]*")
        report.extend(buy_signals)
    
    if sell_signals:
        report.append("\n⚠️ *[매도/관망 권고]*")
        report.extend(sell_signals)

    if len(report) > 1:
        send_msg("\n".join(report))
    else:
        send_msg(f"📅 {now_date}\n분석은 완료되었으나 특이 신호 종목이 없습니다.")