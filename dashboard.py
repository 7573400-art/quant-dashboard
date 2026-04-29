import streamlit as st
import pandas as pd
import FinanceDataReader as fdr
import yfinance as yf
from urllib.error import URLError
import re
import fundamental
import llm_agent
import plotly.graph_objects as go
from dotenv import load_dotenv
import requests
import db
import datetime
import os
import strategy

def get_env_or_secret(key):
    val = os.environ.get(key)
    if val: return val
    try:
        return st.secrets[key]
    except:
        return None

load_dotenv()
OPENAI_API_KEY = get_env_or_secret("OPENAI_API_KEY")

# --- 1. 페이지 설정 및 보안 인증 ---
st.set_page_config(page_title="My Quant Dashboard", layout="wide")

# --- 2. 핵심 분석 함수 ---
@st.cache_data(ttl=86400) # 하루 한 번 KRX 맵핑 갱신 (오프라인 캐시 우선 로드)
def get_krx_mapping():
    import json
    import os
    path = os.path.join(os.path.dirname(__file__), 'krx_mapping.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        pass
        
    try:
        import FinanceDataReader as fdr
        df = fdr.StockListing('KRX')
        return dict(zip(df['Code'], df['Name']))
    except:
        return {}

@st.cache_data(ttl=3600) # 1시간마다 데이터 캐시 갱신
def get_company_name(ticker):
    # 한국 증시 종목인 경우 KRX 맵핑에서 이름 확인
    if str(ticker).isdigit():
        krx_map = get_krx_mapping()
        if str(ticker) in krx_map:
            return krx_map[str(ticker)]
            
    return ticker

@st.cache_data(ttl=179) # 3분마다 캐시 갱신 (Rate Limit 방지, 캐시 강제 무효화)
def get_stock_analysis(ticker):
    try:
        df = fdr.DataReader(ticker, start=(datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d'))
        
        # [해외망 차단 우회] Streamlit Cloud에서 한국 증시 조회가 차단(403)되어 비어있을 경우 yfinance를 통해 우회 (코스피/코스닥)
        if (df is None or len(df) == 0) and str(ticker).isdigit():
            import yfinance as yf
            start_date = (datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
            df = yf.download(f"{ticker}.KS", start=start_date, progress=False)
            if df.empty:
                df = yf.download(f"{ticker}.KQ", start=start_date, progress=False)
                
        df = df.dropna(subset=['Close']) # 주말/휴장일 NaN 결측치 보정
        if len(df) < 21: return None # 최근 상장 종목(최소 20일)도 표출되도록 완화
        
        # 지표 계산을 strategy 모듈로 중앙화
        df = strategy.calculate_indicators(df)
        if df is None: return None
        
        latest, prev = df.iloc[-1], df.iloc[-2]
        curr_price = latest['Close']
        
        # [실시간 시세 보정] 프리장/애프터장 반영 (미국 주식 한정)
        if not str(ticker).isdigit():
            try:
                import yfinance as yf
                curr_price = float(yf.Ticker(ticker).fast_info.last_price)
            except: pass
            
        prev_price = prev['Close']
        change_val = curr_price - prev_price
        change_pct = (change_val / prev_price) * 100
        
        # 펀더멘털 데이터 수집 (적정 주가, 할인율 등)
        fund_data = fundamental.get_fundamental_data(ticker)
        target_price = fund_data.get('target_mean_price', curr_price)
        discount_rate = fund_data.get('discount_rate', 0)
        
        # 듀얼 스코어 산출
        chart_score = strategy.calculate_dual_momentum_score(latest)
        rs_score = fundamental.get_relative_strength(ticker)
        days_to_earnings = fund_data.get('days_to_earnings')
        market_score = fundamental.calculate_market_score(discount_rate, rs_score, days_to_earnings=days_to_earnings)
        
        return {
            'name': get_company_name(ticker),
            'curr_price': curr_price,
            'change_val': change_val,
            'change_pct': change_pct,
            'target_price': target_price,
            'discount_rate': discount_rate,
            'chart_score': chart_score,
            'market_score': market_score,
            'earnings_date': fund_data.get('earnings_date')
        }
    except: return None

# --- 3. 사이드바 UI (종목 추가/삭제 및 관리) ---
st.sidebar.header("📊 시스템 제어 센터")

# --- 3. 데이터 로드 ---
try:
    tickers = db.get_watchlist()
except Exception as e:
    st.error(f"❌ 데이터베이스에서 관심종목을 불러오는 데 실패했습니다: {e}")
    tickers = []

# 종목 추가
st.sidebar.subheader("➕ 종목 추가")
new_t = st.sidebar.text_input("신규 티커 입력 (예: AAPL, 005930)").upper()
if st.sidebar.button("리스트에 추가"):
    if new_t and new_t not in tickers:
        db.add_watchlist(new_t)
        st.sidebar.success(f"'{new_t}' 추가됨!")
        st.rerun()

# 종목 삭제
st.sidebar.subheader("🗑️ 종목 삭제")
def format_ticker(t):
    if t == "선택하세요": return t
    name = get_company_name(t)
    return f"{t} ({name})" if name != t else t

del_t = st.sidebar.selectbox("삭제할 종목 선택", ["선택하세요"] + tickers, format_func=format_ticker)
if st.sidebar.button("선택 종목 삭제") and del_t != "선택하세요":
    db.remove_watchlist(del_t)
    st.sidebar.warning(f"'{del_t}' 삭제됨!")
    st.rerun()

# --- 4. 메인 대시보드 UI ---
st.markdown("""
<style>
/* 카드형 메트릭 UI CSS */
div[data-testid="metric-container"] {
    background-color: #ffffff;
    border: 1px solid #eef0f3;
    padding: 20px;
    border-radius: 16px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.02);
}
</style>
""", unsafe_allow_html=True)

st.title("My Quant Dashboard")
st.caption("로컬 데이터베이스와 AI 분석 기반 퀀트 운용 시스템입니다.")

# --- 매크로 지표 및 뉴스 패널 ---
@st.cache_data(ttl=1800)
def fetch_macro_data():
    indices = {
        "S&P 500": "^GSPC", "나스닥": "IXIC", "코스피": "KS11", "코스닥": "KQ11", "환율": "USD/KRW",
        "금": "GC=F", "원유": "CL=F", "비트코인": "BTC-USD", "국채 10년물": "^TNX", "VIX 공포지수": "^VIX"
    }
    results = {}
    for name, ticker in indices.items():
        try:
            if ticker in ["KS11", "KQ11", "USD/KRW"]:
                df = fdr.DataReader(ticker, start=(datetime.datetime.now() - datetime.timedelta(days=10)).strftime('%Y-%m-%d'))
                curr, prev = df['Close'].iloc[-1], df['Close'].iloc[-2]
            else:
                sym = {"IXIC": "^IXIC"}.get(ticker, ticker)
                tkr = yf.Ticker(sym)
                hist = tkr.history(period="5d")
                curr, prev = hist['Close'].iloc[-1], hist['Close'].iloc[-2]
            pct = ((curr - prev) / prev) * 100
            results[name] = (curr, pct)
        except: results[name] = (0, 0)
    return results

@st.cache_data(ttl=1800)
def fetch_top_news():
    url = "https://news.google.com/rss/search?q=글로벌+경제+주식+when:1d&hl=ko&gl=KR&ceid=KR:ko"
    try:
        import xml.etree.ElementTree as ET
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            items = root.findall('.//item')
            if not items: return []
            
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
                
            try:
                news_text = "\n".join([n['title'] for n in raw_news])
                prompt = f"다음 경제 뉴스 3개의 제목을 각 1줄씩 임팩트 있는 평문으로 요약해줘.\n출력예시:\n1. [요약]\n2. [요약]\n3. [요약]\n\n뉴스입력:\n{news_text}"
                payload = {
                    "model": "llama3.2",
                    "prompt": prompt,
                    "stream": False
                }
                res_ai = requests.post("http://localhost:11434/api/generate", json=payload, timeout=15)
                if res_ai.status_code == 200:
                    ai_text = res_ai.json().get("response", "").strip().split('\n')
                    idx = 0
                    for line in ai_text:
                        line = re.sub(r'^\d+\.?\s*|\[요약\]', '', line).replace('*', '').strip()
                        if line and idx < len(raw_news):
                            raw_news[idx]['summary'] = f"{line}{raw_news[idx]['time_str']}"
                            idx += 1
            except Exception as e: 
                pass # Ollama 실패 시 원본 그대로 유지
                    
            for n in raw_news:
                if 'summary' not in n: n['summary'] = f"{n['title']}{n['time_str']}"
            return raw_news
        else:
            return [{"summary": f"⚠️ 구글 뉴스 API 에러 (상태코드: {res.status_code})", "link": ""}]
    except Exception as e:
        return [{"summary": f"⚠️ 뉴스 크롤링 서버 통신 에러: {e}", "link": ""}]

st.subheader("🌍 글로벌 매크로 지표")
macro_data = fetch_macro_data()
if macro_data:
    cols1 = st.columns(5)
    cols2 = st.columns(5)
    all_cols = cols1 + cols2
    for i, (name, (curr, pct)) in enumerate(macro_data.items()):
        if name in ["나스닥", "S&P 500", "금", "원유", "비트코인"]:
            val_str = f"${curr:,.2f}" if name != "비트코인" else f"${curr:,.0f}"
        elif "국채" in name or "VIX" in name:
            val_str = f"{curr:,.2f}"
        else:
            val_str = f"{curr:,.2f}"
            
        delta_str = f"{pct:+.2f}%"
        if i < len(all_cols):
            all_cols[i].metric(name, val_str, delta_str)

st.markdown("<br>", unsafe_allow_html=True)
news_data = fetch_top_news()
if news_data:
    st.markdown("##### 📰 오늘의 핵심 경제 뉴스 (AI 요약)")
    for n in news_data:
        st.markdown(f"- **{n['summary']}** [🔗기사원문]({n['link']})")
st.divider()

if tickers:
    def format_ticker_main(t):
        name = get_company_name(t)
        return f"{t} ({name})" if name != t else t
        
    selected_ticker = st.selectbox("상세 분석 종목 선택", tickers, format_func=format_ticker_main)
    
    if selected_ticker:
        data = get_stock_analysis(selected_ticker)
        if data:
            # 화폐 단위 결정
            is_kr = selected_ticker.isdigit()
            curr_fmt = f"₩{int(data['curr_price']):,}" if is_kr else f"${data['curr_price']:.2f}"
            target_fmt = f"₩{int(data['target_price']):,}" if is_kr else f"${data['target_price']:.2f}"
            
            # 전일비 포맷
            chg_val = data['change_val']
            chg_pct = data['change_pct']
            chg_val_fmt = f"₩{int(abs(chg_val)):,}" if is_kr else f"${abs(chg_val):.2f}"
            
            if chg_val > 0:
                delta_str = f"▲ {chg_val_fmt} (+{chg_pct:.2f}%)"
                line_color = "#f04452"
                fill_color = "rgba(240, 68, 82, 0.1)"
            elif chg_val < 0:
                delta_str = f"▼ {chg_val_fmt} ({chg_pct:.2f}%)"
                line_color = "#3282f6"
                fill_color = "rgba(50, 130, 246, 0.1)"
            else:
                delta_str = f"- 0 (0.00%)"
                line_color = "#8b95a1"
                fill_color = "rgba(139, 149, 161, 0.1)"
                
            chart_score = data['chart_score']
            market_score = data['market_score']
            
            if chart_score >= 70: chart_text = f"🚀 모멘텀 돌파 ({chart_score}점)"
            elif chart_score <= 30: chart_text = f"❄️ 추세 이탈 ({chart_score}점)"
            else: chart_text = f"👀 횡보 구간 ({chart_score}점)"

            if market_score >= 70: market_text = f"✨ 초강력 주도주 ({market_score}점)"
            elif market_score <= 30: market_text = f"⚠️ 밸류/모멘텀 상실 ({market_score}점)"
            else: market_text = f"📊 적정 수준 ({market_score}점)"

            # 토스증권 스타일 헤더 (현재가 및 등락률)
            st.markdown(f"""
            <div style='padding: 24px; background-color: #ffffff; border-radius: 20px; box-shadow: 0 8px 16px rgba(0,0,0,0.03); margin-bottom: 24px; border: 1px solid #eef0f3;'>
                <p style='margin: 0; color: #8b95a1; font-size: 16px;'>{selected_ticker}</p>
                <h3 style='margin: 0 0 10px 0; color: #333d4b; font-size: 20px;'>{data['name']}</h3>
                <h1 style='margin: 0; color: #191f28; font-size: 40px; font-weight: 700;'>{curr_fmt}</h1>
                <p style='margin: 8px 0 0 0; font-size: 18px; font-weight: 600; color: {line_color};'>{delta_str}</p>
            </div>
            """, unsafe_allow_html=True)
            
            # 카드형 지표
            earnings_str = data.get('earnings_date') or "미정"
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("📈 기술적 차트 점수", chart_text)
            col2.metric("🏢 가치 및 시장 점수", market_text)
            col3.metric("🎯 적정 주가", target_fmt)
            col4.metric("📅 예상 촉매제 (실적일)", earnings_str)
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # AI 가치-추론 리포트 생성 버튼
            if st.button("🤖 Ollama AI 가치-추론 리포트 생성", use_container_width=True):
                with st.spinner("AI가 재무 데이터와 뉴스를 분석하며 추론 중입니다... (10~30초 소요)"):
                    report = llm_agent.generate_reasoning_report(selected_ticker, data['name'])
                    st.success("분석 완료!")
                    st.markdown(f"""
                    <div style='background-color:#f8f9fa; padding:20px; border-radius:12px; border-left:5px solid #3282f6;'>
                        {report.replace(chr(10), '<br>')}
                    </div>
                    """, unsafe_allow_html=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # 차트 시각화 (Plotly)
            df_chart = fdr.DataReader(selected_ticker, start=(datetime.datetime.now() - datetime.timedelta(days=90)).strftime('%Y-%m-%d'))
            
            # Y축 범위 최적화로 고저차를 명확하게 (fill='tozeroy'로 인해 0부터 시작하는 문제 해결)
            min_price = df_chart['Close'].min()
            max_price = df_chart['Close'].max()
            y_margin = (max_price - min_price) * 0.1 if max_price != min_price else max_price * 0.1
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_chart.index, y=df_chart['Close'],
                mode='lines',
                line=dict(color=line_color, width=3, shape='spline'), # 스플라인으로 부드럽고 세련된 곡선
                fill='tozeroy',
                fillcolor=fill_color,
                hovertemplate='%{x|%Y-%m-%d}<br><b>%{y}</b><extra></extra>'
            ))
            fig.update_layout(
                margin=dict(l=0, r=0, t=20, b=0),
                height=250,
                xaxis=dict(showgrid=False, visible=False),
                yaxis=dict(showgrid=False, visible=False, range=[min_price - y_margin, max_price + y_margin]),
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                hovermode='x unified'
            )
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

st.divider()

# --- 5. 전체 종목 요약 리포트 ---
st.subheader("📋 관심 종목 상태")
kr_data = []
us_data = []

for t in tickers:
    res = get_stock_analysis(t)
    if res:
        is_kr = t.isdigit()
        curr_fmt = f"₩{int(res['curr_price']):,}" if is_kr else f"${res['curr_price']:.2f}"
        target_fmt = f"₩{int(res['target_price']):,}" if is_kr else f"${res['target_price']:.2f}"
        
        target_str = f"{target_fmt} ({res['discount_rate']:+.1f}% 괴리율)"
        earnings_str = res.get('earnings_date') or "-"
        
        row = {
            "종목코드": t,
            "종목명": res['name'],
            "현재가": curr_fmt,
            "적정가": target_str,
            "실적발표일": earnings_str,
            "차트 점수": res['chart_score'],
            "시장 점수": res['market_score'],
            "등락(%)": round(res['change_pct'], 2)
        }
        if is_kr: kr_data.append(row)
        else: us_data.append(row)

tab1, tab2 = st.tabs(["🇰🇷 한국 증시", "🇺🇸 미국 증시"])

with tab1:
    if kr_data:
        df_kr = pd.DataFrame(kr_data)
        st.dataframe(df_kr, use_container_width=True, hide_index=True)
    else:
        st.info("한국 증시 관심 종목이 없습니다.")

with tab2:
    if us_data:
        df_us = pd.DataFrame(us_data)
        st.dataframe(df_us, use_container_width=True, hide_index=True)
    else:
        st.info("미국 증시 관심 종목이 없습니다. API 호출 제한(Rate Limit)이 발생했을 수 있습니다. 잠시 후 새로고침해주세요.")

# --- 6. 아침 알림 로그 확인 (Log 탭 연동) ---
st.divider()
st.subheader("📝 최근 AI 퀀트 알림 히스토리")
try:
    log_data = db.get_log_data()
except:
    log_data = None

if log_data and len(log_data) > 1:
    df_log = pd.DataFrame(log_data[1:], columns=log_data[0]).tail(15) # 최근 15개 기록만 표시
    
    # 열 이름 한글화 처리 (존재할 경우)
    df_log = df_log.rename(columns={
        "Date": "시간", "Time": "시간",
        "Ticker": "종목", 
        "Score": "알고리즘 점수", 
        "Price": "현재가", 
        "TargetPrice": "예측가", "Target": "예측가",
        "Signal": "시그널",
        "TargetDays": "예상기한"
    })
    
    st.dataframe(df_log, use_container_width=True, hide_index=True)
else:
    st.info("아직 누적된 아침 알림 로그 기록이 없습니다. (봇이 알림을 보내면 여기에 추가됩니다)")