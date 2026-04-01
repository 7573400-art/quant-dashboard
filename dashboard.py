import streamlit as st
import FinanceDataReader as fdr
import yfinance as yf
import pandas as pd
import datetime
import os

# --- 페이지 설정 ---
st.set_page_config(page_title="Homin Quant Dashboard", layout="wide")

# --- 종목명 추출 로직 (yf.Search 활용으로 차단 우회) ---
@st.cache_data(ttl=86400)
def get_company_name(ticker):
    try:
        search = yf.Search(ticker)
        if search.quotes:
            name = search.quotes[0].get('longname') or search.quotes[0].get('shortname')
            if name: return name
        stock = yf.Ticker(ticker)
        if 'longName' in stock.fast_info: return stock.fast_info['longName']
    except:
        pass
    return ticker

# --- 퀀트 분석 엔진 (모멘텀 스코어 및 예측가) ---
def get_stock_analysis(ticker):
    try:
        # 데이터 로드 (최근 1년)
        df = fdr.DataReader(ticker, start=(datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d'))
        if len(df) < 200: return None
        
        # 지표 계산
        df['SMA_20'] = df['Close'].rolling(20).mean()
        df['SMA_50'] = df['Close'].rolling(50).mean()
        df['SMA_200'] = df['Close'].rolling(200).mean()
        df['RVOL'] = df['Volume'] / df['Volume'].rolling(20).mean()
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        curr_price = latest['Close']
        score = 0
        
        # 100점 만점 스코어링 로직
        if curr_price > latest['SMA_20']: score += 10
        if latest['SMA_20'] > latest['SMA_50']: score += 10
        if latest['SMA_50'] > latest['SMA_200']: score += 20
        if latest['RVOL'] >= 1.5: score += 30
        elif latest['RVOL'] >= 1.0: score += 15
        if curr_price > prev['High']: score += 15
        if curr_price > latest['Open']: score += 15
        
        # 스코어 비례형 모멘텀 예측가 (상하 15% 밴드)
        target_multiplier = 1 + ((score - 50) / 50) * 0.15
        target_price = curr_price * target_multiplier
        
        return {
            'name': get_company_name(ticker),
            'score': score,
            'curr_price': curr_price,
            'target_price': target_price
        }
    except:
        return None

# --- UI 구성 ---
st.title("📈 퀀트 투자 분석 대시보드")

# 사이드바: 관심종목 관리
WATCHLIST_FILE = 'watchlist.txt'
if os.path.exists(WATCHLIST_FILE):
    with open(WATCHLIST_FILE, 'r') as f:
        watchlist = [line.strip().upper() for line in f if line.strip()]
else:
    watchlist = []

st.sidebar.header("📋 관심 종목")
selected_ticker = st.sidebar.selectbox("종목 선택", watchlist) if watchlist else None

if selected_ticker:
    if st.sidebar.button("분석 실행 🚀"):
        data = get_stock_analysis(selected_ticker)
        
        if data:
            # 화폐 단위 자동 판별
            if selected_ticker.isdigit(): # 한국 주식
                curr_fmt = f"₩{int(data['curr_price']):,}"
                target_fmt = f"₩{int(data['target_price']):,}"
            else: # 미국 주식
                curr_fmt = f"${data['curr_price']:.2f}"
                target_fmt = f"${data['target_price']:.2f}"

            st.subheader(f"🔍 {data['name']} ({selected_ticker}) 분석 결과")
            
            col1, col2, col3 = st.columns(3)
            col1.metric("현재가", curr_fmt)
            col2.metric("퀀트 스코어", f"{data['score']}점")
            col3.metric("모멘텀 예측가", target_fmt)

            # 점수에 따른 상태 메시지
            if data['score'] >= 70:
                st.error("🔴 강력 매수 신호가 감지되었습니다.")
            elif data['score'] <= 30:
                st.info("🔵 매도 또는 관망을 권고합니다.")
            else:
                st.warning("⚪ 중립 상태입니다.")
        else:
            st.error("데이터를 불러올 수 없습니다. 티커를 확인하세요.")

# 하단: 전체 관심종목 요약 테이블
st.divider()
st.subheader("📊 전체 종목 요약 리포트")

if watchlist:
    results = []
    for t in watchlist:
        res = get_stock_analysis(t)
        if res:
            # 테이블용 화폐 포맷팅
            if t.isdigit():
                c_p = f"₩{int(res['curr_price']):,}"
                t_p = f"₩{int(res['target_price']):,}"
            else:
                c_p = f"${res['curr_price']:.2f}"
                t_p = f"${res['target_price']:.2f}"
            
            results.append({
                "종목": t,
                "이름": res['name'],
                "스코어": res['score'],
                "현재가": c_p,
                "예측가": t_p
            })
    
    if results:
        st.table(pd.DataFrame(results))