import streamlit as st
import FinanceDataReader as fdr
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os
import datetime

st.set_page_config(page_title="Quant Dashboard", layout="wide", initial_sidebar_state="collapsed")

WATCHLIST_FILE = 'watchlist.txt'

def get_watchlist():
    if not os.path.exists(WATCHLIST_FILE): return []
    try:
        with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f: 
            return [line.strip().upper() for line in f if line.strip()]
    except Exception: return []

def save_watchlist(tickers):
    with open(WATCHLIST_FILE, 'w', encoding='utf-8') as f:
        for t in tickers: f.write(f"{t}\n")

# --- 종목명 추출 로직 (최적화 및 경량화 버전) ---
@st.cache_data(ttl=3600) # 한 번 가져온 이름은 1시간 동안 메모리에 저장 (속도 향상)
def get_company_name(ticker):
    try:
        stock = yf.Ticker(ticker)
        # 1. fast_info 시도 (가장 빠르고 차단율 낮음)
        info = stock.fast_info
        if 'longName' in info: return info['longName']
        if 'shortName' in info: return info['shortName']
        
        # 2. 실패 시 기본 info에서 추출 시도
        name = stock.info.get('longName') or stock.info.get('shortName')
        if name: return name
    except:
        pass
    return ticker # 모두 실패 시 티커 그대로 반환 (멈춤 방지)

def fetch_stock_data(ticker):
    try:
        start_date = (datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
        df = fdr.DataReader(ticker, start=start_date)
        return df.copy()
    except Exception:
        return None

def calculate_indicators(df):
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    df['SMA_200'] = df['Close'].rolling(window=200).mean()
    
    ranges = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - df['Close'].shift()).abs(),
        (df['Low'] - df['Close'].shift()).abs()
    ], axis=1)
    df['ATR'] = ranges.max(axis=1).rolling(14).mean()
    
    df['VOL_20'] = df['Volume'].rolling(20).mean()
    df['RVOL'] = df['Volume'] / df['VOL_20']
    df['RVOL'] = df['RVOL'].fillna(1.0).replace([np.inf, -np.inf], 1.0)
    
    return df

def calculate_score(df):
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    score = 0
    
    if latest['Close'] > latest['SMA_20']: score += 10
    if latest['SMA_20'] > latest['SMA_50']: score += 10
    if latest['SMA_50'] > latest['SMA_200']: score += 20
    if latest['RVOL'] >= 1.5: score += 30
    elif latest['RVOL'] >= 1.0: score += 15
    if latest['Close'] > prev['High']: score += 15
    if latest['Close'] > latest['Open']: score += 15
        
    return score

# --- 커스텀 CSS (모바일 앱 스타일) ---
st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    div[data-testid="metric-container"] {
        background-color: #1e1e24; border-radius: 10px; padding: 15px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    </style>
""", unsafe_allow_html=True)

st.markdown("<h3 style='text-align: center; color: #ffffff; margin-bottom: 20px;'>📊 퀀트 전략 대시보드</h3>", unsafe_allow_html=True)

# --- 사이드바 ---
st.sidebar.header("📂 관심 종목 관리")
watchlist = get_watchlist()

with st.sidebar.form("add_ticker_form", clear_on_submit=True):
    raw_ticker = st.text_input("종목 티커 입력 (예: TSLA)")
    submitted = st.form_submit_button("추가하기 ➕")
    if submitted and raw_ticker:
        new_ticker = str(raw_ticker).strip().upper()
        if new_ticker not in watchlist:
            watchlist.append(new_ticker)
            save_watchlist(watchlist)
            st.rerun()

st.sidebar.markdown("---")
for t in watchlist:
    if st.sidebar.button(f"🗑️ {t} 삭제", key=f"del_{t}", use_container_width=True):
        if t in watchlist:
            watchlist.remove(t)
            save_watchlist(watchlist)
            st.rerun()

# --- 메인 화면 ---
if not watchlist:
    st.info("👈 왼쪽 메뉴를 열어 관심종목을 추가해주세요.")
else:
    selected_ticker = st.selectbox("분석 종목 선택", watchlist, label_visibility="collapsed")
    
    if st.button("차트 및 지표 분석 실행 🚀", use_container_width=True):
        try:
            with st.spinner('데이터를 분석 중입니다...'):
                df = fetch_stock_data(selected_ticker)
                comp_name = get_company_name(selected_ticker)
                
                # 티커와 기업명이 같으면(야후 서버 차단 시) 중복 출력 방지
                display_name = comp_name if comp_name != selected_ticker else "Name Unavailable"
                
                if df is not None and not df.empty and len(df) > 200:
                    df = calculate_indicators(df)
                    score = calculate_score(df)
                    
                    if score >= 70: color, status = "#ff4b4b", "강력 매수"
                    elif score >= 40: color, status = "#faca2b", "관망/분할"
                    else: color, status = "#00d4ff", "매도/제외"

                    st.markdown(f"""
                        <div style='background: linear-gradient(145deg, #23252b, #1e1e24); padding: 25px; border-radius: 15px; box-shadow: 0 8px 16px rgba(0,0,0,0.2); border-left: 6px solid {color}; margin-bottom: 20px;'>
                            <div style='display: flex; justify-content: space-between; align-items: center;'>
                                <div>
                                    <h2 style='margin: 0; color: #fff; font-size: 24px;'>{selected_ticker}</h2>
                                    <p style='margin: 0; color: #888; font-size: 13px; font-weight: normal; margin-top: 5px;'>{display_name}</p>
                                </div>
                                <div style='text-align: right;'>
                                    <h1 style='margin: 0; font-size: 42px; color: {color}; line-height: 1;'>{score}<span style='font-size: 20px;'>점</span></h1>
                                    <h4 style='margin: 0; color: {color}; margin-top: 5px;'>{status}</h4>
                                </div>
                            </div>
                        </div>
                    """, unsafe_allow_html=True)
                    
                    latest = df.iloc[-1]
                    current_price = float(latest['Close'])
                    prev_price = float(df['Close'].iloc[-2])
                    change_pct = (current_price - prev_price) / prev_price * 100
                    
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("현재가", f"${current_price:.2f}", f"{change_pct:.2f}%")
                    col2.metric("RVOL", f"{latest['RVOL']:.2f}x")
                    col3.metric("ATR", f"${latest['ATR']:.2f}")
                    col4.metric("20일 추세", "상승" if current_price > latest['SMA_20'] else "하락")
                    
                    fig = go.Figure()
                    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'))
                    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='#ffd700', width=1.5), name='20 SMA'))
                    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_50'], line=dict(color='#ff00ff', width=1.5), name='50 SMA'))
                    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_200'], line=dict(color='#ffffff', width=1, dash='dot'), name='200 SMA', opacity=0.5))
                    
                    fig.update_layout(
                        template="plotly_dark", 
                        xaxis_rangeslider_visible=False, 
                        height=450, 
                        margin=dict(l=0, r=0, t=10, b=0),
                        paper_bgcolor='rgba(0,0,0,0)',
                        plot_bgcolor='rgba(0,0,0,0)'
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("데이터가 부족합니다.")
        except Exception as e:
            st.error(f"오류 발생: {e}")