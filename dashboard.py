import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import FinanceDataReader as fdr
import yfinance as yf
import pandas as pd
import datetime
import os
import plotly.graph_objects as go

# --- 1. 페이지 설정 및 보안 인증 ---
st.set_page_config(page_title="Homin Quant Dashboard", layout="wide")

# 구글 시트 인증 설정
# 로컬(Mac mini)에서는 service_account.json 파일을 읽고, 
# Streamlit Cloud에서는 Secrets 설정을 권장하지만 여기서는 파일 기준으로 작성합니다.
JSON_FILE = 'service_account.json'

@st.cache_resource
def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_FILE, scope)
    return gspread.authorize(creds)

try:
    client = get_gspread_client()
    doc = client.open("MyQuant_Data")
    sheet_watch = doc.worksheet("Watchlist")
    sheet_log = doc.worksheet("Log")
except Exception as e:
    st.error(f"❌ 구글 시트 연결 실패: {e}")
    st.stop()

# --- 2. 핵심 분석 함수 ---
@st.cache_data(ttl=3600) # 1시간마다 데이터 캐시 갱신
def get_company_name(ticker):
    try:
        search = yf.Search(ticker)
        if search.quotes:
            return search.quotes[0].get('longname') or search.quotes[0].get('shortname')
    except: pass
    return ticker

def get_stock_analysis(ticker):
    try:
        df = fdr.DataReader(ticker, start=(datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d'))
        if len(df) < 200: return None
        
        # 지표 계산
        df['SMA_20'] = df['Close'].rolling(20).mean()
        df['SMA_50'] = df['Close'].rolling(50).mean()
        df['SMA_200'] = df['Close'].rolling(200).mean()
        df['RVOL'] = df['Volume'] / df['Volume'].rolling(20).mean()
        
        latest, prev = df.iloc[-1], df.iloc[-2]
        curr_price = latest['Close']
        prev_price = prev['Close']
        change_val = curr_price - prev_price
        change_pct = (change_val / prev_price) * 100
        score = 0
        
        # 스코어링 (100점 만점)
        if curr_price > latest['SMA_20']: score += 10
        if latest['SMA_20'] > latest['SMA_50']: score += 10
        if latest['SMA_50'] > latest['SMA_200']: score += 20
        if latest['RVOL'] >= 1.5: score += 30
        elif latest['RVOL'] >= 1.0: score += 15
        if curr_price > prev['High']: score += 15
        if curr_price > latest['Open']: score += 15
        
        # 모멘텀 예측가 공식: 50점 기준 상하 15% 가중치
        target_price = curr_price * (1 + ((score - 50) / 50) * 0.15)
        
        return {
            'name': get_company_name(ticker),
            'score': score,
            'curr_price': curr_price,
            'change_val': change_val,
            'change_pct': change_pct,
            'target_price': target_price
        }
    except: return None

# --- 3. 사이드바 UI (종목 추가/삭제 및 관리) ---
st.sidebar.header("📊 시스템 제어 센터")

# 실시간 티커 리스트 불러오기 (구글 시트 A열)
tickers = sheet_watch.col_values(1)[1:] 

# 종목 추가
st.sidebar.subheader("➕ 종목 추가")
new_t = st.sidebar.text_input("신규 티커 입력 (예: AAPL, 005930)").upper()
if st.sidebar.button("리스트에 추가"):
    if new_t and new_t not in tickers:
        sheet_watch.append_row([new_t])
        st.sidebar.success(f"'{new_t}' 추가됨! (구글 시트 반영)")
        st.rerun()

# 종목 삭제
st.sidebar.subheader("🗑️ 종목 삭제")
del_t = st.sidebar.selectbox("삭제할 종목 선택", ["선택하세요"] + tickers)
if st.sidebar.button("선택 종목 삭제") and del_t != "선택하세요":
    cell = sheet_watch.find(del_t)
    sheet_watch.delete_rows(cell.row)
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

st.title("📈 퀀트 실시간 통합 대시보드")
st.caption("Google Sheets와 실시간으로 동기화되는 1인 퀀트 운용 시스템입니다.")

if tickers:
    selected_ticker = st.selectbox("상세 분석 종목 선택", tickers)
    
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
                
            score = data['score']
            if score >= 70:
                score_text = f"🚀 상승 모멘텀 강함 ({score}점)"
            elif score <= 30:
                score_text = f"❄️ 차가운 하락세 ({score}점)"
            else:
                score_text = f"👀 횡보 및 관망세 ({score}점)"

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
            col1, col2 = st.columns(2)
            col1.metric("📊 AI 퀀트 분석", score_text)
            col2.metric("🎯 모멘텀 목표가", target_fmt)
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # 차트 시각화 (Plotly)
            df_chart = fdr.DataReader(selected_ticker, start=(datetime.datetime.now() - datetime.timedelta(days=90)).strftime('%Y-%m-%d'))
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_chart.index, y=df_chart['Close'],
                mode='lines',
                line=dict(color=line_color, width=2.5),
                fill='tozeroy',
                fillcolor=fill_color,
                hovertemplate='%{x|%Y-%m-%d}<br><b>%{y}</b><extra></extra>'
            ))
            fig.update_layout(
                margin=dict(l=0, r=0, t=20, b=0),
                height=250,
                xaxis=dict(showgrid=False, visible=False),
                yaxis=dict(showgrid=False, visible=False),
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                hovermode='x unified'
            )
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

st.divider()

# --- 5. 전체 종목 요약 리포트 ---
st.subheader("📋 관심 종목 상태")
summary_data = []
for t in tickers:
    res = get_stock_analysis(t)
    if res:
        is_kr = t.isdigit()
        chg_pct = res['change_pct']
        
        # 방향 이모지
        if chg_pct > 0: chg_icon = "🔴"
        elif chg_pct < 0: chg_icon = "🔵"
        else: chg_icon = "⚪"
        
        summary_data.append({
            "종목명": f"{res['name']} ({t})",
            "현재가": f"₩{int(res['curr_price']):,}" if is_kr else f"${res['curr_price']:.2f}",
            "전일비": f"{chg_icon} {chg_pct:+.2f}%",
            "퀀트 점수": f"{res['score']}점",
            "목표가": f"₩{int(res['target_price']):,}" if is_kr else f"${res['target_price']:.2f}"
        })
if summary_data:
    st.dataframe(pd.DataFrame(summary_data), use_container_width=True, hide_index=True)

# --- 6. 아침 알림 로그 확인 (Log 탭 연동) ---
st.divider()
st.subheader("📝 아침 알림 히스토리 (Google Sheets Log)")
log_data = sheet_log.get_all_records()
if log_data:
    df_log = pd.DataFrame(log_data).tail(15) # 최근 15개 기록만 표시
    st.dataframe(df_log, use_container_width=True)
else:
    st.info("아직 누적된 로그 기록이 없습니다.")