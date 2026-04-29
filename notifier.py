import requests
import datetime
import os
import db
import yfinance as yf
import llm_agent

# 환경변수 로드
from dotenv import load_dotenv
load_dotenv()
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_msg(text):
    if not TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, data=payload)

def get_stock_name(ticker):
    try:
        info = yf.Ticker(ticker).info
        return info.get('shortName') or info.get('longName') or ticker
    except:
        return ticker

if __name__ == "__main__":
    print("="*50)
    print("🧠 AI 가치-추론 스크리너 브리핑 시작")
    print("="*50)
    
    try:
        tickers = db.get_watchlist()
    except Exception as e:
        print(f"❌ 데이터베이스 연결 실패: {e}")
        exit()
        
    if not tickers:
        print("💡 분석할 종목이 데이터베이스에 없습니다.")
        exit()

    now_date = datetime.datetime.now().strftime('%Y-%m-%d')
    report_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    
    # 텔레그램 리포트 시작
    send_msg(f"📅 *AI 가치-추론 모닝 브리핑 ({report_time})*\n\n오늘의 종목 분석을 시작합니다...")
    
    for t in tickers:
        t = t.strip()
        # 한국 주식 처리 (야후 파이낸스용)
        yf_ticker = f"{t}.KS" if t.isdigit() else t
        
        stock_name = get_stock_name(yf_ticker)
        print(f"[{stock_name}] 추론 리포트 생성 중...")
        
        try:
            fund_data = fundamental.get_fundamental_data(yf_ticker)
            rs_score = fundamental.get_relative_strength(yf_ticker)
            market_score = fundamental.calculate_market_score(fund_data.get('discount_rate', 0), rs_score)
            
            import FinanceDataReader as fdr
            import strategy
            import datetime
            df = fdr.DataReader(yf_ticker, start=(datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d'))
            df = strategy.calculate_indicators(df)
            chart_score = strategy.calculate_dual_momentum_score(df.iloc[-1])
        except Exception as e:
            print(e)
            chart_score, market_score = 0, 0
            
        # Ollama 에이전트로 1줄 요약 리포트 생성
        report = llm_agent.generate_reasoning_report(yf_ticker, stock_name, short_summary=True)
        
        if report:
            # 텔레그램 메시지용으로 줄바꿈 제거 및 정리
            report = report.replace('\n', ' ').strip()
            msg = f"🔸 [차트: {chart_score} | 시장: {market_score}] {report}"
            send_msg(msg)
            
            # TODO: 대시보드 표시용 DB 저장 로직 (선택)
            # 여기서는 알림 목적으로만 전송
        
    print("\n브리핑이 완료되었습니다.")