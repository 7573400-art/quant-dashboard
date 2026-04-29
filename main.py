import telebot
import FinanceDataReader as fdr
import pandas as pd
import datetime
import os
from dotenv import load_dotenv
import threading
import time
import db
import strategy

load_dotenv()
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    print("WARNING: OPENAI_API_KEY가 등록되지 않았습니다.")

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
        "🤖 *My Quant Bot에 오신 것을 환영합니다!*\n\n"
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
            
        new_tickers = parts[1].split(',')
        results = []
        try:
            tickers = db.get_watchlist()
        except Exception as e:
            bot.reply_to(message, f"데이터베이스 연결 에러: {e}")
            return
            
        for t in new_tickers:
            ticker = t.strip().upper()
            if not ticker: continue
            if ticker in tickers:
                results.append(f"⚠️ {ticker}는 이미 등록되어 있습니다.")
            else:
                try:
                    db.add_watchlist(ticker)
                    results.append(f"✅ {ticker} 종목이 추가되었습니다.")
                except Exception as e:
                    results.append(f"❌ {ticker} 추가 실패: {e}")
        bot.reply_to(message, "\n".join(results), parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"오류가 발생했습니다: {e}")

@bot.message_handler(commands=['remove'])
def remove_ticker_cmd(message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ 사용법: `/remove 종목기호` (예: /remove AAPL)", parse_mode="Markdown")
            return
            
        del_tickers = parts[1].split(',')
        results = []
        try:
            tickers = db.get_watchlist()
            if not tickers:
                bot.reply_to(message, "삭제할 종목이 없습니다.")
                return

            for t in del_tickers:
                ticker = t.strip().upper()
                if ticker in tickers:
                    db.remove_watchlist(ticker)
                    results.append(f"✅ {ticker} 종목이 삭제되었습니다.")
                else:
                    results.append(f"⚠️ {ticker}는 리스트에 없습니다.")
        except Exception as e:
            results.append(f"❌ 작업 중 에러 발생: {e}")
        bot.reply_to(message, "\n".join(results), parse_mode="Markdown")
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
    url = "https://news.google.com/rss/search?q=글로벌+경제+주식+when:1d&hl=ko&gl=KR&ceid=KR:ko"
    try:
        import xml.etree.ElementTree as ET
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            items = root.findall('.//item')
            if not items: return "최근 관련 뉴스 없음"
            
            raw_news = []
            for item in items[:3]:
                title = item.find('title').text
                link = item.find('link').text
                
                pub_date = item.find('pubDate')
                time_str = ""
                if pub_date is not None:
                    import email.utils
                    try:
                        dt = email.utils.parsedate_to_datetime(pub_date.text)
                        now = datetime.datetime.now(datetime.timezone.utc)
                        diff = now - dt
                        if diff.total_seconds() < 3600:
                            mins = int(diff.total_seconds() // 60)
                            time_str = f" ({mins}분 전)"
                        elif diff.total_seconds() < 86400:
                            hrs = int(diff.total_seconds() // 3600)
                            time_str = f" ({hrs}시간 전)"
                        else:
                            days = int(diff.total_seconds() // 86400)
                            time_str = f" ({days}일 전)"
                    except: pass
                
                raw_news.append({"title": title, "link": link, "time_str": time_str})
            
            return "\n\n".join([f"- {n['title']}{n['time_str']}\n   🔗 [원문 링크]({n['link']})" for n in raw_news])
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

krx_map_cache = {}

def get_krx_mapping():
    global krx_map_cache
    if not krx_map_cache:
        import json
        import os
        path = os.path.join(os.path.dirname(__file__), 'krx_mapping.json')
        try:
            with open(path, 'r', encoding='utf-8') as f:
                krx_map_cache = json.load(f)
        except:
            krx_map_cache = {}
            
    return krx_map_cache

def get_company_name(ticker):
    if str(ticker).isdigit():
        krx_map = get_krx_mapping()
        if str(ticker) in krx_map:
            return krx_map[str(ticker)]
    return ticker

def get_recent_news(ticker, name=""):
    search_query = name if name else ticker
    if ticker.isdigit():
        url = f"https://search.naver.com/search.naver?where=news&query={search_query}+주식"
        try:
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
            titles = re.findall(r'class="news_tit"[^>]*title="([^"]+)"', res.text)
            if not titles: return "최근 관련 뉴스 없음"
            news_text = []
            for t in titles[:3]:
                news_text.append(f"- {t}")
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
            log_data = db.get_log_data()
        for row in reversed(log_data):
            if str(row[1]).strip().upper() == ticker:
                try:
                    target = float(str(row[4]).replace('₩','').replace('$','').replace(',',''))
                    diff = ((curr_price - target) / target) * 100
                    return f"최근 예측({row[0]}) 대비 오차 {diff:.2f}%"
                except:
                    break
    except:
        pass
    return "과거 예측 데이터 없음"

def analyze_with_openai(ticker, technical_score, diff_history, news_summary):
    if not OPENAI_API_KEY:
        return technical_score, "OpenAI API 키가 없어 기술 점수만 반영됨", 5
        
    prompt = f"""당신은 월스트리트의 최고급 퀀트 트레이더이자 딥러닝 추론 AI입니다. 현재 '{ticker}' 종목의 모멘텀을 분석해야 합니다.

[입력 데이터]
1. 수학적 퀀트 알고리즘 점수: {technical_score} / 100
2. 과거 분석 오차율: {diff_history}
3. 최신 시장/기업 뉴스 3개: 
{news_summary}

[행동 지침]
- 알고리즘 점수를 기반으로 뉴스/오차율을 고려해 ±15점 범위 내에서 조정하세요.

[출력 형식]
추론: [판단 과정 1~2문장]
최종 스코어: [숫자]
예상도달일: [3, 5, 7, 10 중 하나]
코멘트: [최종 한 줄 브리핑]"""

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert quantitative AI model."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        text = response.choices[0].message.content.strip()
        
        final_score = technical_score
        score_match = re.search(r'(?:최종\s*)?스코어\s*[:-]?\s*(?:\*\*)?\s*(\d+)', text)
        if score_match:
            try: final_score = int(score_match.group(1))
            except: pass
            
        horizon = 5
        horizon_match = re.search(r'예상도달일\s*[:-]?\s*(?:\*\*)?\s*(\d+)', text)
        if horizon_match:
            try: horizon = int(horizon_match.group(1))
            except: pass
            
        ai_comment = "알고리즘 스코어만 산출되었습니다."
        if "코멘트:" in text:
            ai_comment = text.split("코멘트:")[1].strip()
        elif "코멘트" in text:
            ai_comment = text.split("코멘트")[1].strip()
            
        return final_score, ai_comment, horizon
    except Exception as e:
        return technical_score, f"AI 추론 오류 발생: {e}", 5

def get_stock_info(ticker, log_data=None, fast_mode=False):
    try:
        df = fdr.DataReader(ticker, start=(datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d'))
        if (df is None or len(df) == 0) and str(ticker).isdigit():
            import yfinance as yf
            start_date = (datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
            df = yf.download(f"{ticker}.KS", start=start_date, progress=False)
            if df.empty:
                df = yf.download(f"{ticker}.KQ", start=start_date, progress=False)
                
        df = df.dropna(subset=['Close'])
        if len(df) < 21: return None
        
        # 지표 계산을 strategy 모듈로 중앙화
        df = strategy.calculate_indicators(df)
        if df is None: return None
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        curr_price = latest['Close']
        
        if not str(ticker).isdigit():
            try:
                import yfinance as yf
                curr_price = float(yf.Ticker(ticker).fast_info.last_price)
            except: pass
            
        prev_price = prev['Close']
        change_val = curr_price - prev_price
        change_pct = (change_val / prev_price) * 100
        
        # 퀀트 스코어 산출을 strategy 모듈로 중앙화
        score = strategy.calculate_score(latest, prev)
        
        # 동적 목표가 (Target Price) 산출
        target_price = strategy.calculate_target_price(curr_price, latest['ATR'], score)
        
        if fast_mode and score < 55:
            return {'score': score, 'curr_price': curr_price, 'change_pct': change_pct, 'change_val': change_val, 'target_price': target_price, 'ai_comment': "패스 (베이스 모멘텀 점수 55점 미달)", 'horizon': 5}
        
        if not fast_mode:
            c_name = get_company_name(ticker)
            news_summary = get_recent_news(ticker, c_name)
            diff_history = get_diff_history(ticker, curr_price, log_data)
            final_score, ai_comment, horizon = analyze_with_openai(ticker, score, diff_history, news_summary)
        else:
            final_score = score
            ai_comment = ""
            horizon = 5
            
        return {'score': final_score, 'curr_price': curr_price, 'change_pct': change_pct, 'change_val': change_val, 'target_price': target_price, 'ai_comment': ai_comment, 'horizon': horizon}
    except:
        return None

@bot.message_handler(commands=['score'])
def send_all_scores(message):
    bot.reply_to(message, "⏳ 전 종목 퀀트 정보 수집 및 AI 딥러닝 분석 중입니다... 잠시만 기다려주세요!")
    
    try:
        tickers = db.get_watchlist()
    except:
        bot.send_message(message.chat.id, "데이터베이스를 읽어오는데 실패했습니다.")
        return
        
    report = ["📋 *[전 종목 퀀트 스코어 및 딥러닝 예측가]*\n"]
    kr_results = []
    us_results = []
    
    try:
        log_data = db.get_log_data()
    except:
        log_data = None
        
    for t in tickers:
        data = get_stock_info(t, log_data)
        if data:
            score = data['score']
            curr = data['curr_price']
            target = data['target_price'] 
            chg_pct = data['change_pct']
            horizon = data.get('horizon', 5)
            
            if chg_pct > 0: chg_str = f"🔺{chg_pct:+.2f}%"
            elif chg_pct < 0: chg_str = f"🔻{chg_pct:+.2f}%"
            else: chg_str = f"➖0.00%"
            
            if score >= 70: icon = "🚀"
            elif score <= 30: icon = "❄️"
            else: icon = "👀"
            
            exp_return = ((target - curr) / curr) * 100
            exp_date = (datetime.datetime.now() + datetime.timedelta(days=horizon)).strftime('%m/%d')
            
            name_str = f"{t} ({get_company_name(t)})" if t.isdigit() else t
            
            if t.isdigit(): 
                curr_fmt = f"₩{int(curr):,}"
                target_fmt = f"₩{int(target):,}"
                item_str = f"{icon} *{name_str}*: {curr_fmt} ({chg_str})\n   - AI 스코어: {score}점 / 목표가: {target_fmt} (예상 수익 {exp_return:+.2f}%, {exp_date} 도달 예상)\n   - 🤖 AI 진단: {data.get('ai_comment','')}"
                kr_results.append(item_str)
            else: 
                curr_fmt = f"${curr:.2f}"
                target_fmt = f"${target:.2f}"
                item_str = f"{icon} *{name_str}*: {curr_fmt} ({chg_str})\n   - AI 스코어: {score}점 / 목표가: {target_fmt} (예상 수익 {exp_return:+.2f}%, {exp_date} 도달 예상)\n   - 🤖 AI 진단: {data.get('ai_comment','')}"
                us_results.append(item_str)
                
    if kr_results:
        report.append("🇰🇷 *[한국 증시]*")
        report.extend(kr_results)
        report.append("")
        
    if us_results:
        report.append("🇺🇸 *[미국 증시]*")
        report.extend(us_results)
    
    bot.send_message(message.chat.id, "\n".join(report), parse_mode="Markdown")

@bot.message_handler(commands=['review'])
def send_review(message):
    bot.reply_to(message, "🔍 과거 예측 목표가와 현재 실제가의 오차(괴리율)를 분석 중입니다...")
    
    try:
        log_data = db.get_log_data()
    except Exception as e:
        bot.send_message(message.chat.id, f"로그 데이터 접근 에러: {e}")
        return
        
    latest_targets = {}
    if log_data:
        for row in log_data:
            if len(row) >= 7:
                ticker = str(row[1]).strip().upper()
                try:
                    target = float(str(row[4]).replace('₩','').replace('$','').replace(',',''))
                    horizon = int(row[6])
                    latest_targets[ticker] = {'date': str(row[0]), 'target': target, 'horizon': horizon}
                except: continue
                
    try:
        tickers = db.get_watchlist()
    except:
        return
        
    report = ["📊 *[AI 예측 성과 채점 및 괴리율 리포트]*\n"]
    kr_results = []
    us_results = []
    
    for t in tickers:
        data = get_stock_info(t, log_data)
        if not data: continue
        
        curr = data['curr_price']
        new_target = data['target_price']
        new_horizon = data.get('horizon', 5)
        
        report_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        try:
            db.append_log(report_time, t, data['score'], round(curr, 2), round(new_target, 2), "REVIEW", new_horizon)
        except: pass
            
        if t in latest_targets:
            info = latest_targets[t]
            old_date_str = info['date']
            old_target = info['target']
            horizon = info['horizon']
            diff_pct = ((curr - old_target) / old_target) * 100
            
            try:
                old_dt = pd.to_datetime(old_date_str)
                passed_days = (datetime.datetime.now() - old_dt).days
                passed_days = max(1, passed_days)
            except: passed_days = 1
                
            is_expired = passed_days >= horizon
            curr_fmt = f"₩{int(curr):,}" if t.isdigit() else f"${curr:.2f}"
            old_target_fmt = f"₩{int(old_target):,}" if t.isdigit() else f"${old_target:.2f}"
                
            if diff_pct > 0: eval_str = f"✅ 목표 초과 달성! (+{diff_pct:.2f}%)"
            elif diff_pct > -3: eval_str = f"🎯 예측 오차 3% 이내 적중! ({diff_pct:.2f}%)"
            else:
                if not is_expired: eval_str = f"⏳ 도달 진행 중 (목표 기한 {horizon}일 중 {passed_days}일 경과) ({diff_pct:.2f}%)"
                else: eval_str = f"⚠️ 기한 초과 및 예측 미달 ({diff_pct:.2f}%)"
                
            name_str = f"{t} ({get_company_name(t)})" if t.isdigit() else t    
            item_str = f"*{name_str}* (목표가 기준: {old_date_str})\n - 당시 예측가: {old_target_fmt}\n - 현재 실제가: {curr_fmt}\n ➜ {eval_str}\n"
            
            if t.isdigit(): kr_results.append(item_str)
            else: us_results.append(item_str)
            
    if kr_results:
        report.append("🇰🇷 *[한국 증시 피드백]*")
        report.extend(kr_results)
    if us_results:
        report.append("🇺🇸 *[미국 증시 피드백]*")
        report.extend(us_results)
    
    if (len(kr_results) + len(us_results)) == 0:
        report.append("비교할 어제의 로그 데이터가 없거나 부족합니다.")
        
    bot.send_message(message.chat.id, "\n".join(report), parse_mode="Markdown")

def auto_check_buy_signals():
    last_alert_scores = {}
    while True:
        try:
            print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] 🔍 1분 단위 초고속 모니터링 가동 시작...")
            try:
                tickers = db.get_watchlist()
            except Exception as e:
                print(f"데이터베이스 읽기 에러: {e}")
                time.sleep(60)
                continue
            
            if not tickers:
                time.sleep(60)
                continue
            
            try:
                log_data = db.get_log_data()
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
                    
                    horizon = data.get('horizon', 5)
                    exp_return = ((data['target_price'] - data['curr_price']) / data['curr_price']) * 100
                    exp_date = (datetime.datetime.now() + datetime.timedelta(days=horizon)).strftime('%m/%d')

                    name_str = f"{t} ({get_company_name(t)})" if t.isdigit() else t
                    buy_signals.append(f"🚀 *{name_str}*: 강력 매수 추천 (AI 스코어: {score}점)\n   - 현재: {curr_fmt} ({chg_str})\n   - 목표: {target_fmt} (수익 {exp_return:+.2f}%, {exp_date} 도달 예상)\n   - 🤖 코멘트: {data.get('ai_comment','')}")
            
            if buy_signals and CHAT_ID:
                msg = "🔔 *[1분 실시간 감시] 신규 매수 시그널 포착!*\n\n" + "\n\n".join(buy_signals)
                bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
                print(f"텔레그램 매수 시그널 발송 완료! ({len(buy_signals)} 종목)")
            else:
                print("상태 유지 중 ➜ 기존 감시 점수를 초과한 새로운 돌파/매수 신호 없음.")
                
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