import telebot
import FinanceDataReader as fdr
import pandas as pd
import datetime
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.environ.get("TELEGRAM_TOKEN")
WATCHLIST_FILE = 'watchlist.txt'

bot = telebot.TeleBot(TOKEN)

def get_stock_info(ticker):
    try:
        df = fdr.DataReader(ticker, start=(datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d'))
        if len(df) < 200: return None
        
        df['SMA_20'] = df['Close'].rolling(20).mean()
        df['SMA_50'] = df['Close'].rolling(50).mean()
        df['SMA_200'] = df['Close'].rolling(200).mean()
        df['RVOL'] = df['Volume'] / df['Volume'].rolling(20).mean()
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        curr_price = latest['Close']
        prev_price = prev['Close']
        change_val = curr_price - prev_price
        change_pct = (change_val / prev_price) * 100
        score = 0
        
        # 퀀트 스코어 계산
        if curr_price > latest['SMA_20']: score += 10
        if latest['SMA_20'] > latest['SMA_50']: score += 10
        if latest['SMA_50'] > latest['SMA_200']: score += 20
        if latest['RVOL'] >= 1.5: score += 30
        elif latest['RVOL'] >= 1.0: score += 15
        if curr_price > prev['High']: score += 15
        if curr_price > latest['Open']: score += 15
        
        # 📌 선생님 요청: 스코어 비례형 단기 목표가 (Target Price) 계산
        # 50점을 기준으로, 1점당 0.3%씩 가격이 비례하여 움직임 (최대 상하 15% 밴드)
        target_multiplier = 1 + ((score - 50) / 50) * 0.15
        target_price = curr_price * target_multiplier
        
        return {'score': score, 'curr_price': curr_price, 'change_pct': change_pct, 'change_val': change_val, 'target_price': target_price}
    except:
        return None

@bot.message_handler(commands=['score'])
def send_all_scores(message):
    bot.reply_to(message, "⏳ 전 종목 퀀트 스코어 및 모멘텀 예측가 분석 중입니다...")
    
    if not os.path.exists(WATCHLIST_FILE):
        bot.send_message(message.chat.id, "관심종목 파일이 없습니다.")
        return
        
    with open(WATCHLIST_FILE, 'r') as f:
        tickers = [line.strip().upper() for line in f if line.strip()]
        
    report = ["📋 *[전 종목 퀀트 스코어 및 예측가]*\n"]
    
    for t in tickers:
        data = get_stock_info(t)
        if data:
            score = data['score']
            curr = data['curr_price']
            target = data['target_price'] 
            chg_pct = data['change_pct']
            
            # 1. 상태 이모지 및 전일비(%) 표시 결정
            if chg_pct > 0: chg_str = f"🔺{chg_pct:+.2f}%"
            elif chg_pct < 0: chg_str = f"🔻{chg_pct:+.2f}%"
            else: chg_str = f"➖0.00%"
            
            if score >= 70: icon = "🚀"
            elif score <= 30: icon = "❄️"
            else: icon = "👀"
            
            # 2. 한/미 화폐 포맷 결정
            if t.isdigit(): 
                curr_fmt = f"₩{int(curr):,}"
                target_fmt = f"₩{int(target):,}"
            else: 
                curr_fmt = f"${curr:.2f}"
                target_fmt = f"${target:.2f}"
            
            # 3. 최종 출력 텍스트 조립
            report.append(f"{icon} *{t}*: {curr_fmt} ({chg_str})\n   - 퀀트: {score}점 / 목표가: {target_fmt}")
    
    bot.send_message(message.chat.id, "\n".join(report), parse_mode="Markdown")

if __name__ == "__main__":
    bot.polling(none_stop=True)