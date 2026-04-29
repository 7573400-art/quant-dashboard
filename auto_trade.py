import os
import time
import datetime
import requests
from dotenv import load_dotenv
import strategy
import db
import FinanceDataReader as fdr
import pandas as pd

load_dotenv()

class KISTrader:
    """
    한국투자증권(KIS) Open API 자동매매 모듈 스켈레톤
    """
    def __init__(self, mode="VIRTUAL"):
        self.mode = mode # VIRTUAL (모의투자) or REAL (실전투자)
        self.api_key = os.environ.get("KIS_API_KEY", "")
        self.api_secret = os.environ.get("KIS_API_SECRET", "")
        self.acc_no = os.environ.get("KIS_ACC_NO", "")
        
        # 한국투자증권 도메인 (모의투자 vs 실전투자)
        if self.mode == "VIRTUAL":
            self.base_url = "https://openapivts.koreainvestment.com:29443"
        else:
            self.base_url = "https://openapi.koreainvestment.com:9443"
            
        self.access_token = self._get_access_token()
        self.headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.access_token}",
            "appKey": self.api_key,
            "appSecret": self.api_secret,
            "tr_id": "" # 거래 ID는 메서드 호출 시마다 지정
        }
        print(f"[{self.mode}] KIS Trader 초기화 완료")
        
    def _get_access_token(self):
        """API Access Token 발급 (스켈레톤)"""
        # 실제 환경에서는 API 키를 바탕으로 토큰을 발급받아 리턴
        if not self.api_key:
            print("⚠️ 경고: KIS_API_KEY가 설정되지 않았습니다.")
        return "DUMMY_TOKEN_FOR_TESTING"
        
    def get_balance(self):
        """계좌 잔고 조회"""
        # self.headers["tr_id"] = "VTTC8434R" (모의투자 주식잔고조회)
        print("💰 계좌 잔고를 조회합니다.")
        return 10000000 # 가상의 잔고 1000만원 리턴
        
    def get_current_price(self, ticker):
        """현재가 조회"""
        # 실제 API 호출 로직
        print(f"📈 {ticker} 현재가 조회 중...")
        return 50000
        
    def buy_market_order(self, ticker, amount):
        """시장가 매수 주문"""
        print(f"🟢 [BUY 주문 전송] 종목: {ticker}, 금액: {amount}원")
        # 실제 API 매수 주문 로직
        return True
        
    def sell_market_order(self, ticker, quantity):
        """시장가 매도 주문"""
        print(f"🔴 [SELL 주문 전송] 종목: {ticker}, 수량: {quantity}주")
        # 실제 API 매도 주문 로직
        return True

def run_auto_trader():
    """자동매매 메인 루프"""
    print("🤖 자동매매 봇 구동 시작...")
    trader = KISTrader(mode="VIRTUAL")
    
    # 텔레그램 봇 토큰
    tg_token = os.environ.get("TELEGRAM_TOKEN")
    tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    def send_tg_msg(text):
        if not tg_token or not tg_chat_id: return
        url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
        requests.post(url, data={"chat_id": tg_chat_id, "text": text})
    
    send_tg_msg("🚀 KIS 기반 가상 자동매매 시스템을 시작합니다.")
    
    # 1. 포트폴리오 관리 (매수한 종목의 단가 및 수량 보관)
    # 실제로는 DB나 API 잔고 조회를 통해 구성해야 함
    portfolio = {} 
    
    while True:
        now = datetime.datetime.now()
        # 장중 시간(09:00 ~ 15:20) 외에는 휴식 로직 추가 필요
        print(f"\n[{now.strftime('%H:%M:%S')}] 시장 스캔 중...")
        
        try:
            tickers = db.get_watchlist()
            # 포트폴리오(잔고)에 있는 종목도 검사 대상에 포함
            check_list = list(set(tickers + list(portfolio.keys())))
            
            # 1. 시세 데이터 및 모멘텀 스코어 수집
            scored_tickers = []
            for ticker in check_list:
                # 최근 300일 데이터
                start_date = (now - datetime.timedelta(days=300)).strftime('%Y-%m-%d')
                try:
                    df = fdr.DataReader(ticker, start=start_date)
                    df = strategy.calculate_indicators(df)
                    if df is not None and len(df) > 0:
                        latest = df.iloc[-1]
                        score = strategy.calculate_dual_momentum_score(latest)
                        scored_tickers.append({
                            'ticker': ticker,
                            'score': score,
                            'curr_price': latest['Close'],
                            'latest': latest
                        })
                except Exception as e:
                    print(f"[{ticker}] 시세 조회 오류: {e}")
                    
            # 2. 보유 종목 청산 모니터링 (트레일링 스탑)
            for item in list(portfolio.keys()):
                info = next((x for x in scored_tickers if x['ticker'] == item), None)
                if info:
                    latest = info['latest']
                    curr_price = info['curr_price']
                    
                    # 최고가 갱신
                    if curr_price > portfolio[item]['highest_price']:
                        portfolio[item]['highest_price'] = curr_price
                        
                    # 트레일링 스탑 검사
                    sell, reason, _ = strategy.check_trailing_stop_condition(latest, portfolio[item]['highest_price'], trail_pct=0.10)
                    
                    if sell:
                        trader.sell_market_order(item, portfolio[item]['qty'])
                        send_tg_msg(f"🔴 [청산] {item} ({reason})")
                        del portfolio[item]
                        
            # 3. 신규 매수 (모멘텀 스코어 80점 이상인 종목 중 상위 3개 분산투자)
            scored_tickers.sort(key=lambda x: x['score'], reverse=True)
            max_portfolio_size = 3
            
            for info in scored_tickers:
                ticker = info['ticker']
                if ticker not in portfolio and len(portfolio) < max_portfolio_size:
                    if info['score'] >= 80:
                        # 가상 매수 로직 (종목당 동일 비중)
                        balance = trader.get_balance()
                        allocate_amount = balance / max_portfolio_size
                        qty = allocate_amount // info['curr_price']
                        
                        if qty > 0:
                            trader.buy_market_order(ticker, allocate_amount)
                            send_tg_msg(f"🟢 [매수] {ticker} (모멘텀 점수: {info['score']}점)")
                            portfolio[ticker] = {
                                'buy_price': info['curr_price'],
                                'qty': qty,
                                'highest_price': info['curr_price']
                            }
            
            print("스캔 완료. 15분 대기...")
        except Exception as e:
            print(f"루프 에러: {e}")
            
        time.sleep(15 * 60) # 15분 대기 (테스트 시 짧게 조정)

if __name__ == "__main__":
    run_auto_trader()
