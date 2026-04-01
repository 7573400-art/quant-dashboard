import os
import asyncio
import selectors
import datetime
import urllib.request
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
from dotenv import load_dotenv

# ==========================================
# 0. 맥(macOS) 전용 asyncio 호환성 패치
# ==========================================
class State:
    pass

selector = selectors.SelectSelector()
loop = asyncio.SelectorEventLoop(selector)
asyncio.set_event_loop(loop)

import yfinance as yf
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ==========================================
# 1. 환경 변수 및 기본 설정
# ==========================================
load_dotenv()
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
WATCHLIST_FILE = 'watchlist.txt'

if not TOKEN or not CHAT_ID:
    print("🚨 오류: .env 파일에서 토큰이나 챗 아이디를 찾을 수 없습니다!")
    exit(1)

KST = datetime.timezone(datetime.timedelta(hours=9))

# ==========================================
# 2. 파일 관리 및 구글 뉴스 크롤러 (100% 수집)
# ==========================================
def get_watchlist():
    if not os.path.exists(WATCHLIST_FILE): return []
    with open(WATCHLIST_FILE, 'r') as f: return [line.strip().upper() for line in f if line.strip()]

def save_watchlist(tickers):
    with open(WATCHLIST_FILE, 'w') as f:
        for t in tickers: f.write(f"{t}\n")

def get_latest_news(ticker):
    """야후 파이낸스가 막힐 경우를 대비해 구글 뉴스 RSS를 사용하여 100% 뉴스를 가져옵니다."""
    try:
        # 구글 경제 뉴스 RSS 활용 (우회 및 차단 방지)
        url = f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)
            items = root.findall('.//item')
            
            if items:
                news_text = "\n📰 *[최신 시장 뉴스]*\n"
                for i, item in enumerate(items[:3]):
                    title = item.find('title').text
                    # 너무 긴 제목은 잘라내기
                    short_title = title[:45] + "..." if len(title) > 45 else title
                    news_text += f"• {short_title}\n"
                return news_text
    except Exception as e:
        print(f"[{ticker}] 뉴스 수집 오류: {e}")
    
    return "\n📰 관련 뉴스가 없습니다."

def get_market_indicators():
    symbols = {"🇺🇸 나스닥": "^IXIC", "🇰🇷 코스피": "^KS11", "🥇 금(Gold)": "GC=F", "🥈 은(Silver)": "SI=F"}
    report = "📊 *[주요 거시경제 지표]*\n"
    for name, ticker in symbols.items():
        try:
            data = yf.Ticker(ticker).history(period="5d")
            if len(data) >= 2:
                current, prev = data['Close'].iloc[-1], data['Close'].iloc[-2]
                change_pct = ((current - prev) / prev) * 100
                report += f"• {name}: {current:,.2f} ({'+' if change_pct > 0 else ''}{change_pct:.2f}%)\n"
        except: pass
    return report + "\n"

# ==========================================
# 3. 핵심 퀀트 엔진 (손절가/목표가 논리적 보완)
# ==========================================
def analyze_ticker(ticker):
    stock = yf.Ticker(ticker)
    info = stock.info
    hist = stock.history(period="1y")
    
    if hist.empty or len(hist) < 200: return None
    
    current_price = hist['Close'].iloc[-1]
    quote_type = info.get('quoteType', 'EQUITY')
    
    # ATR (절대 변동성) 계산
    ranges = pd.concat([
        hist['High'] - hist['Low'],
        np.abs(hist['High'] - hist['Close'].shift()),
        np.abs(hist['Low'] - hist['Close'].shift())
    ], axis=1)
    atr = np.max(ranges, axis=1).rolling(14).mean().iloc[-1]
    
    # RVOL (상대 거래량) 계산
    avg_vol_20 = hist['Volume'].rolling(20).mean().iloc[-1]
    current_vol = hist['Volume'].iloc[-1]
    rvol = current_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0
    
    # 이동평균 및 RSI
    sma_20 = hist['Close'].rolling(20).mean().iloc[-1]
    sma_50 = hist['Close'].rolling(50).mean().iloc[-1]
    sma_200 = hist['Close'].rolling(200).mean().iloc[-1]
    
    delta = hist['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rsi = 100 - (100 / (1 + (gain / loss))).iloc[-1]

    # ========================================
    # [전략 A] 터틀 트레이딩 모델 (ETF 등)
    # ========================================
    if quote_type == 'ETF' or ticker in ['CONL', 'CONI', 'MSTR']:
        analysis_type = "📈 터틀 트레이딩 (추세/변동성)"
        trend_score = sum([15 if current_price > sma_20 else 0, 15 if sma_20 > sma_50 else 0, 10 if sma_50 > sma_200 else 0])
        vol_score = 30 if rvol >= 1.5 else (15 if rvol >= 1.0 else 0)
        rsi_score = 30 if 40 <= rsi <= 70 else (10 if rsi < 40 else 0)
        total_score = trend_score + vol_score + rsi_score
        
        target_price = current_price + (atr * 2.0)
        # 손절가: 현재가에서 무조건 ATR의 1.5배 아래로 설정하여 현재가 역전 방지
        stop_loss = current_price - (atr * 1.5)
        details = f"• RVOL: {rvol:.2f}배\n• ATR(변동성): ${atr:.2f}\n• 정배열 추세 점수: {trend_score}/40"

    # ========================================
    # [전략 B] CAN SLIM 모델 (성장 기술주)
    # ========================================
    else:
        analysis_type = "🚀 CAN SLIM (고성장/거래량)"
        peg = info.get('pegRatio')
        growth_score = 40 if peg and 0 < peg <= 1.2 else (20 if peg and peg <= 2.0 else (5 if peg else 20))
        mom_score = 30 if current_price > sma_200 else 0
        vol_score = 30 if rvol >= 1.5 else (15 if rvol >= 1.0 else 0)
        total_score = growth_score + mom_score + vol_score
        
        # 목표가 논리적 보완: 컨센서스가 현재가보다 낮거나 없으면 무조건 현재가 + 20%
        analyst_target = info.get('targetMeanPrice')
        if analyst_target and analyst_target > current_price:
            target_price = analyst_target
        else:
            target_price = current_price * 1.2
            
        # 손절가 논리적 보완: 50일선이 현재가보다 아래일 때만 지지선으로 쓰고, 역배열이면 무조건 -8% 컷
        if sma_50 < current_price:
            stop_loss = max(sma_50, current_price * 0.92)
        else:
            stop_loss = current_price * 0.92 # 윌리엄 오닐의 철칙 적용 (-8% 절대 손절)
            
        details = f"• RVOL: {rvol:.2f}배\n• PEG Ratio: {peg if peg else 'N/A'}\n• 200일 추세: {'상승' if mom_score > 0 else '하락'}"

    return {
        "price": current_price, "target": target_price, "stop_loss": stop_loss,
        "score": total_score, "type": analysis_type, "details": details
    }

# ==========================================
# 4. 스케줄러 (실시간 감시 및 일간 리포트)
# ==========================================
async def monitor_market(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    tickers = get_watchlist()
    
    for ticker in tickers:
        try:
            result = analyze_ticker(ticker)
            if not result: continue
            score = result['score']
            
            if score >= 75 or score <= 35:
                signal = "🔥 *[강력 매수 / 추세 돌파]*" if score >= 75 else "⚠️ *[주의 / 추세 이탈]*"
                msg = (f"{signal} {ticker}\n\n"
                       f"💰 *현재가:* `${result['price']:.2f}`\n"
                       f"🎯 *익절 목표가:* `${result['target']:.2f}`\n"
                       f"🛡 *기계적 손절가:* `${result['stop_loss']:.2f}`\n\n"
                       f"📊 *적용 전략:* {result['type']}\n"
                       f"⭐️ *스코어:* {score}점\n"
                       f"{result['details']}\n"
                       f"{get_latest_news(ticker)}")
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
        except Exception as e: print(f"[{ticker}] 에러: {e}")

async def daily_summary_report(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    msg = f"🌅 *[오전 7시 퀀트 전략 브리핑]*\n기준: {datetime.datetime.now(KST).strftime('%Y-%m-%d %H:%M')}\n\n"
    msg += get_market_indicators()
    msg += "📂 *[감시 리스트 포지션 요약]*\n"
    for ticker in get_watchlist():
        try:
            res = analyze_ticker(ticker)
            if res:
                icon = "🟢" if res['score'] >= 75 else ("🔴" if res['score'] <= 35 else "🟡")
                msg += f"{icon} *{ticker}* : {res['score']}점 (🎯${res['target']:.1f} / 🛡${res['stop_loss']:.1f})\n"
        except: msg += f"⚪️ *{ticker}* : 분석 데이터 부족\n"
    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

# ==========================================
# 5. 텔레그램 명령어 처리부
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 *정통 퀀트 분석 비서 가동*\n➕ `/add [종목]`\n📋 `/list`", parse_mode='Markdown')

async def add_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    t = context.args[0].upper(); ts = get_watchlist()
    if t not in ts: ts.append(t); save_watchlist(ts); await update.message.reply_text(f"✅ {t} 추가됨.")

async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ts = get_watchlist()
    if not ts: return
    kb = [[InlineKeyboardButton(f"🗑️ {t}", callback_data=f"del_{t}")] for t in ts]
    await update.message.reply_text("📂 *현재 감시 리스트*", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    t = q.data.split("_")[1]; ts = get_watchlist()
    if t in ts: ts.remove(t); save_watchlist(ts); await q.edit_message_text(f"🗑️ {t} 삭제 완료.")

def main():
    app = Application.builder().token(TOKEN).build()
    for cmd, func in [("start", start), ("add", add_ticker), ("list", show_list)]:
        app.add_handler(CommandHandler(cmd, func))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    app.job_queue.run_repeating(monitor_market, interval=1800, first=5, chat_id=CHAT_ID)
    app.job_queue.run_daily(daily_summary_report, time=datetime.time(hour=7, tzinfo=KST), chat_id=CHAT_ID)
    
    print("🚀 무결성 패치 완료! 퀀트 시스템 재가동.")
    app.run_polling()

if __name__ == "__main__": main()