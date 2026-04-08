import telebot
import FinanceDataReader as fdr
import pandas as pd
import datetime
import os
from dotenv import load_dotenv
import threading
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai
import requests
import re
import xml.etree.ElementTree as ET

load_dotenv()
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# 구글 시트 연동
JSON_FILE = 'service_account.json'
try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_FILE, scope)
    g_client = gspread.authorize(creds)
    doc = g_client.open("MyQuant_Data")
    sheet_watch = doc.worksheet("Watchlist")
    sheet_log = doc.worksheet("Log")
except Exception as e:
    print(f"❌ 구글 시트 연결 실패: {e}")

bot = telebot.TeleBot(TOKEN)
from telebot import types

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_score = types.KeyboardButton('/score')
    btn_report = types.KeyboardButton('/report')
    btn_review = types.KeyboardButton('/review')
    btn_dash = types.KeyboardButton('/dashboard')
    markup.add(btn_report, btn_score, btn_review, btn_dash)
    
    welcome_text = (
        "🤖 *Homin Quant Bot에 오신 것을 환영합니다!*\n\n"
        "아래 메뉴 버튼을 누르시거나 명령어를 직접 입력해주세요.\n\n"
        "📊 `/score` : 관심종목 전체 스코어 및 AI 진단\n"
        "🌍 `/report` : 글로벌 매크로 지표 & 메인 뉴스 AI 요약\n"
        "🧐 `/review` : 어제 일자 예측가와 오늘 실제가 오차 채점\n"
        "🌐 `/dashboard` : 모바일 웹 대시보드 바로가기\n"
        "💡 *(15분 자동 감시 로직은 백그라운드에서 동작 중입니다)*"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['dashboard'])
def send_dash(message):
    bot.reply_to(message, "🌐 [여기서 대시보드를 엽니다](https://quant-dashboard-h9vyzzgzkehnhmd47aprhc.streamlit.app/)", parse_mode="Markdown")

@bot.message_handler(commands=['add'])
def add_ticker_cmd(message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ 사용법: `/add 종목기호` (예: /add AAPL, /add 005930)", parse_mode="Markdown")
            return
            
        ticker = parts[1].strip().upper()
        tickers = [str(t).upper() for t in sheet_watch.col_values(1)[1:]]
        
        if ticker in tickers:
            bot.reply_to(message, f"❌ 이미 편입된 종목입니다: {ticker}")
            return
            
        sheet_watch.append_row([ticker])
        bot.reply_to(message, f"✅ `{ticker}` 종목이 관심종목(Watchlist)에 추가되었습니다!\n이제 대시보드와 AI 봇이 실시간으로 감시합니다.", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"오류가 발생했습니다: {e}")

@bot.message_handler(commands=['remove'])
def remove_ticker_cmd(message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ 사용법: `/remove 종목기호` (예: /remove AAPL)", parse_mode="Markdown")
            return
            
        ticker = parts[1].strip().upper()
        
        tickers = sheet_watch.col_values(1)
        upper_tickers = [str(t).upper() for t in tickers]
        
        if ticker in upper_tickers:
            row_idx = upper_tickers.index(ticker) + 1
            sheet_watch.delete_rows(row_idx)
            bot.reply_to(message, f"🗑 `{ticker}` 종목이 감시 목록에서 삭제되었습니다.", parse_mode="Markdown")
        else:
            bot.reply_to(message, f"❌ 목록에서 {ticker} 종목을 찾을 수 없습니다.")
    except Exception as e:
        bot.reply_to(message, f"오류가 발생했습니다: {e}")

def get_macro_data():
    def fetch_ticker_data(ticker):
        try:
            import yfinance as yf
            if ticker in ["KS11", "KQ11", "USD/KRW"]:
                df = fdr.DataReader(ticker, start=(datetime.datetime.now() - datetime.timedelta(days=10)).strftime('%Y-%m-%d'))
                if len(df) >= 2:
                    return df['Close'].iloc[-1], ((df['Close'].iloc[-1] - df['Close'].iloc[-2]) / df['Close'].iloc[-2]) * 100
            else:
                sym = {"IXIC": "^IXIC"}.get(ticker, ticker)
                tkr = yf.Ticker(sym)
                hist = tkr.history(period="5d")
                if len(hist) >= 2:
                    return hist['Close'].iloc[-1], ((hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
        except: pass
        return 0, 0

    indices = {
        "🇺🇸 S&P 500": "^GSPC",
        "🇺🇸 나스닥": "IXIC",
        "🇰🇷 코스피": "KS11",
        "🇰🇷 코스닥": "KQ11",
        "💵 환율(원/달러)": "USD/KRW",
        "🥇 금": "GC=F",
        "🛢️ WTI 원유": "CL=F",
        "₿ 비트코인": "BTC-USD",
        "📈 국채 10년물": "^TNX",
        "😨 VIX 공포지수": "^VIX"
    }
    
    lines = []
    for name, ticker in indices.items():
        curr, pct = fetch_ticker_data(ticker)
        if curr == 0: continue
        
        icon = "🔺" if pct > 0 else "🔻" if pct < 0 else "➖"
        if "나스닥" in name or "S&P" in name or "금" in name or "원유" in name or "비트코인" in name:
            val_fmt = f"${curr:,.2f}" if "비트코인" not in name else f"${curr:,.0f}"
        elif "국채" in name or "VIX" in name:
            val_fmt = f"{curr:.2f}"
        else:
            val_fmt = f"{curr:,.2f}"
            
        lines.append(f"{name}: {val_fmt} ({icon}{pct:+.2f}%)")
        
    return "\n".join(lines) if lines else "매크로 지표 서버 접근 실패"

def get_news_report():
    url = "https://news.google.com/rss/search?q=글로벌+경제+주식&hl=ko&gl=KR&ceid=KR:ko"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            items = root.findall('.//item')
            if not items: return "최근 관련 뉴스 없음"
            
            raw_news = []
            for item in items[:3]:
                title = item.find('title').text
                link = item.find('link').text
                raw_news.append({"title": title, "link": link})
                
            if GEMINI_API_KEY:
                model = genai.GenerativeModel('gemini-2.5-flash')
                news_text = "\n".join([n['title'] for n in raw_news])
                prompt = f"""다음 경제 뉴스 3개의 제목을 보고, 각각 1줄씩 임팩트 있는 평문으로 짧게 핵심 요약해줘.
[출력 형식]
1. [첫번째 뉴스 1줄 요약]
2. [두번째 뉴스 1줄 요약]
3. [세번째 뉴스 1줄 요약]

뉴스입력:
{news_text}"""
                try:
                    response = model.generate_content(prompt)
                    ai_text = response.text.strip().split('\n')
                    
                    final_lines = []
                    idx = 0
                    for line in ai_text:
                        line = line.strip()
                        if line and idx < len(raw_news):
                            final_lines.append(f"{line}\n   🔗 [{raw_news[idx]['title']}]({raw_news[idx]['link']})")
                            idx += 1
                        elif line:
                            final_lines.append(line)
                            
                    return "\n\n".join(final_lines)
                except: pass
            
            return "\n\n".join([f"- {n['title']}\n   🔗 [원문 링크]({n['link']})" for n in raw_news])
    except: pass
    return "뉴스 수집 실패"

@bot.message_handler(commands=['report'])
def send_report(message):
    bot.reply_to(message, "🌍 글로벌 매크로 증시 지표와 최신 뉴스를 AI가 총정리하고 있습니다...")
    
    macro_text = get_macro_data()
    news_text = get_news_report()
    
    report_msg = (
        "🌍 *[글로벌 매크로 증시 모닝 리포트]*\n\n"
        f"{macro_text}\n\n"
        "📰 *[오늘의 핵심 AI 경제 뉴스]*\n"
        f"{news_text}"
    )
    bot.send_message(message.chat.id, report_msg, parse_mode="Markdown", disable_web_page_preview=True)

def get_company_name(ticker):
    try:
        import yfinance as yf
        search = yf.Search(ticker)
        if search.quotes:
            return search.quotes[0].get('longname') or search.quotes[0].get('shortname')
    except: pass
    return ticker

def get_recent_news(ticker, name=""):
    search_query = name if name else ticker
    if ticker.isdigit():
        # 한국 주식의 경우 "종목명+주식" 키워드 사용 및 최근 7일(when:7d) 기사로 필터링
        url = f"https://news.google.com/rss/search?q={search_query}+주식+when:7d&hl=ko&gl=KR&ceid=KR:ko"
        try:
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
            root = ET.fromstring(res.content)
            items = root.findall('.//item')
            if not items: return "최근 관련 뉴스 없음"
            news_text = []
            for item in items[:3]:
                title = item.find('title').text
                news_text.append(f"- {title}")
            return "\n".join(news_text)
        except Exception as e: 
            return f"뉴스 검색 오류: {e}"
    else:
        try:
            import yfinance as yf
            tkr = yf.Ticker(ticker)
            news = tkr.news
            if news:
                news_text = []
                for n in news[:3]:
                    news_text.append(f"- {n.get('title', '')}")
                return "\n".join(news_text)
            return "최근 미국 영문 뉴스 없음"
        except: return "뉴스 검색 오류"

def get_diff_history(ticker, curr_price, log_data=None):
    try:
        if log_data is None:
            log_data = sheet_log.get_all_values()
        for row in reversed(log_data[1:]): # 최신순
            if str(row[1]).strip().upper() == ticker:
                try:
                    target = float(row[4].replace('₩','').replace('$','').replace(',',''))
                    diff = ((curr_price - target) / target) * 100
                    return f"최근 예측({row[0]}) 대비 오차 {diff:.2f}%"
                except:
                    break
    except:
        pass
    return "과거 예측 데이터 없음"

def analyze_with_gemini(ticker, technical_score, diff_history, news_summary):
    if not GEMINI_API_KEY:
        return technical_score, "Gemini API 키가 없어 기술 점수만 반영됨"
        
    prompt = f"""당신은 월스트리트의 최고급 퀀트 트레이더이자 딥러닝 추론 AI입니다. 현재 '{ticker}' 종목의 모멘텀을 분석해야 합니다.

[입력 데이터]
1. 수학적 퀀트 알고리즘 점수: {technical_score} / 100 (이동평균선, 돌파, 거래량 등을 기반으로 입증된 시스템 트레이딩 스코어)
2. 과거 분석 오차율 (피드백 데이터): {diff_history} (당신의 과거 예측치 대비 오차율. 음수면 예측 실패/보수적 하향 조정 필요, 양수면 모멘텀 초과 달성/상향 조정 필요)
3. 최신 시장/기업 뉴스 3개: 
{news_summary}

[행동 지침 및 추론 원칙]
- 가장 중요: '수학적 퀀트 알고리즘 점수'를 절대적인 근거 및 시작점으로 삼으십시오.
- 뉴스 호재/악재와 과거 오차율 데이터는 논리적 추론을 거친 후, 알고리즘 점수를 최대 ±15점 범위 내에서만 상향/하향 미세 조정(Fine-tuning)하는 데 쓰여야 합니다. (예: 점수가 60점임에도 뉴스가 치명적일 경우 완전히 새로운 점수를 매기는 것이 아니라 -15점 감점하여 45점으로 도출)
- 뉴스의 표면적 정보가 아닌, 해당 뉴스가 주가 모멘텀과 기술적 지표에 미칠 연쇄적 파급력을 심층 추론(Reasoning) 하세요.

[출력 형식]
추론: [당신의 심층적이고 논리적인 판단 과정을 1~2문장으로 서술]
최종 스코어: [숫자]
코멘트: [당신의 추론을 바탕으로 사용자에게 건네는 최종 한 줄 브리핑]"""

    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        final_score = technical_score
        
        # 1. 정규식(Regex)을 사용한 스코어 안전 파싱 (코멘트 내용 속 숫자가 스코어로 오인되는 것 방지)
        score_match = re.search(r'(?:최종\s*)?스코어\s*[:-]?\s*(?:\*\*)?\s*(\d+)', text)
        if score_match:
            final_score = int(score_match.group(1))
            
        # 2. 코멘트 안전 파싱 (코멘트: 이후의 모든 문자열을 추출)
        comment_match = re.search(r'코멘트\s*[:-]?\s*(.*)', text, flags=re.DOTALL)
        if comment_match:
            comment = comment_match.group(1).strip()
        else:
            comment = text.replace('\n', ' ')
            
        return final_score, comment
    except Exception as e:
        return technical_score, f"AI 분석 에러: {e}"

def get_stock_info(ticker, log_data=None, fast_mode=False):
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
        
        if fast_mode and score < 55:
            return {'score': score, 'curr_price': curr_price, 'change_pct': change_pct, 'change_val': change_val, 'target_price': target_price, 'ai_comment': "패스 (베이스 모멘텀 점수 55점 미달)"}
        
        # AI 복합 스코어링 (뉴스 및 과거 오차 학습 반영)
        name = get_company_name(ticker)
        news_summary = get_recent_news(ticker, name)
        diff_history = get_diff_history(ticker, curr_price, log_data)
        
        final_score, ai_comment = analyze_with_gemini(ticker, score, diff_history, news_summary)
        
        return {'score': final_score, 'curr_price': curr_price, 'change_pct': change_pct, 'change_val': change_val, 'target_price': target_price, 'ai_comment': ai_comment}
    except:
        return None

@bot.message_handler(commands=['score'])
def send_all_scores(message):
    bot.reply_to(message, "⏳ 전 종목 퀀트 정보 수집 및 AI 딥러닝 분석 중입니다... 잠시만 기다려주세요!")
    
    try:
        tickers = sheet_watch.col_values(1)[1:]
        if not tickers:
            bot.send_message(message.chat.id, "구글 시트 관심종목 리스트가 비어있습니다.")
            return
    except Exception as e:
        bot.send_message(message.chat.id, f"구글 시트를 읽어오는데 실패했습니다: {e}")
        return
        
    report = ["📋 *[전 종목 퀀트 스코어 및 예측가]*\n"]
    
    try:
        log_data = sheet_log.get_all_values()
    except:
        log_data = None
        
    for t in tickers:
        data = get_stock_info(t, log_data)
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
            report.append(f"{icon} *{t}*: {curr_fmt} ({chg_str})\n   - AI 스코어: {score}점 / 목표가: {target_fmt}\n   - 🤖 AI 진단: {data.get('ai_comment','')}")
    
    bot.send_message(message.chat.id, "\n".join(report), parse_mode="Markdown")

@bot.message_handler(commands=['review'])
def send_review(message):
    bot.reply_to(message, "🔍 과거 예측 목표가와 현재 실제가의 오차(괴리율)를 분석 중입니다...")
    
    try:
        log_data = sheet_log.get_all_values()
    except Exception as e:
        bot.send_message(message.chat.id, f"로그 시트 접근 에러: {e}")
        return
        
    latest_targets = {}
    if len(log_data) > 1:
        for row in log_data[1:]:
            if len(row) >= 5:
                ticker = str(row[1]).strip().upper()
                try:
                    target = float(row[4].replace('₩','').replace('$','').replace(',',''))
                except:
                    continue
                latest_targets[ticker] = (str(row[0]), target)
                
    try:
        tickers = sheet_watch.col_values(1)[1:]
    except:
        return
        
    report = ["📊 *[AI 예측 성과 채점 및 괴리율 리포트]*\n"]
    
    for t in tickers:
        data = get_stock_info(t, log_data)
        if not data: continue
        
        curr = data['curr_price']
        new_target = data['target_price']
        
        # 내일의 평가를 위해 오늘 퀀트 결과를 Log에 기록
        report_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        try:
            sheet_log.append_row([report_time, t, data['score'], round(curr, 2), round(new_target, 2), "REVIEW"])
        except:
            pass
            
        if t in latest_targets:
            old_date, old_target = latest_targets[t]
            diff_pct = ((curr - old_target) / old_target) * 100
            
            curr_fmt = f"₩{int(curr):,}" if t.isdigit() else f"${curr:.2f}"
            old_target_fmt = f"₩{int(old_target):,}" if t.isdigit() else f"${old_target:.2f}"
                
            if diff_pct > 0:
                eval_str = f"✅ 목표 초과 달성! (+{diff_pct:.2f}%)"
            elif diff_pct > -3:
                eval_str = f"🎯 예측 오차 3% 이내 적중! ({diff_pct:.2f}%)"
            else:
                eval_str = f"⚠️ 예측 미달/차질 발생 ({diff_pct:.2f}%)"
                
            report.append(f"*{t}* (목표가 기준: {old_date})")
            report.append(f" - 당시 예측가: {old_target_fmt}")
            report.append(f" - 현재 실제가: {curr_fmt}")
            report.append(f" ➜ {eval_str}\n")
    
    if len(report) == 1:
        report.append("비교할 어제의 로그 데이터가 없거나 부족합니다.\n방금 평가된 오늘의 가격 명세가 내일의 채점을 위해 Log 탭에 새롭게 저장되었습니다.")
        
    bot.send_message(message.chat.id, "\n".join(report), parse_mode="Markdown")

def auto_check_buy_signals():
    """1분마다 백그라운드에서 실행되며 강력 매수 신호 발생 시 알람 중복을 최소화하여 텔레그램으로 보냅니다."""
    last_alert_scores = {}
    while True:
        try:
            try:
                tickers = sheet_watch.col_values(1)[1:]
            except Exception as e:
                print(f"구글 시트 읽기 에러: {e}")
                time.sleep(60)
                continue
            
            if not tickers:
                time.sleep(60)
                continue
            
            try:
                log_data = sheet_log.get_all_values()
            except:
                log_data = None
                
            buy_signals = []
            for t in tickers:
                data = get_stock_info(t, log_data, fast_mode=True)
                if not data: continue
                
                score = data['score']
                
                # 점수가 역치(70) 아래로 떨어지면 리셋하여 나중에 다시 70을 돌파할 때 알림을 주도록 함
                if score < 70:
                    if t in last_alert_scores:
                        del last_alert_scores[t]
                    continue
                    
                prev_alert_score = last_alert_scores.get(t, 0)
                
                # 70점 이상이면서 동시에 이전에 알림을 보냈던 점수보다 높을 때만 신호 발생 (중복 방지)
                if score >= 70 and score > prev_alert_score:
                    last_alert_scores[t] = score
                    
                    curr_fmt = f"₩{int(data['curr_price']):,}" if t.isdigit() else f"${data['curr_price']:.2f}"
                    target_fmt = f"₩{int(data['target_price']):,}" if t.isdigit() else f"${data['target_price']:.2f}"
                    
                    chg_pct = data['change_pct']
                    if chg_pct > 0: chg_str = f"🔺{chg_pct:+.2f}%"
                    elif chg_pct < 0: chg_str = f"🔻{chg_pct:+.2f}%"
                    else: chg_str = f"➖0.00%"

                    buy_signals.append(f"🚀 *{t}*: 강력 매수 추천 (AI 스코어: {score}점)\n   - 현재: {curr_fmt} ({chg_str})\n   - 🤖 코멘트: {data.get('ai_comment','')}")
            
            if buy_signals and CHAT_ID:
                msg = "🔔 *[1분 실시간 감시] 신규 매수 시그널 포착!*\n\n" + "\n\n".join(buy_signals)
                bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
                
        except Exception as e:
            print(f"자동 확인 도중 에러가 발생했습니다: {e}")
            
        time.sleep(60) # 1분(60초) 대기 후 반복

if __name__ == "__main__":
    print("텔레그램 수동 응답 봇 및 1분 단위 초고속 백그라운드 탐색기를 시작합니다...")
    
    # 백그라운드 쓰레드로 1분 자동 체크 로직 구동
    if CHAT_ID:
        scheduler_thread = threading.Thread(target=auto_check_buy_signals, daemon=True)
        scheduler_thread.start()
    else:
        print("⚠️ .env에 TELEGRAM_CHAT_ID가 설정되어 있지 않아 15분 자동 알림 기능은 실행되지 않습니다.")
        
    bot.polling(none_stop=True)