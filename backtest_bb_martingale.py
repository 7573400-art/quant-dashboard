import FinanceDataReader as fdr
import yfinance as yf
import pandas as pd
import datetime
import numpy as np
import db
import time

def calculate_bb_indicators(df):
    """EMA200 및 볼린저밴드(30, 2.0) 지표 계산"""
    df = df.dropna(subset=['Close']).copy()
    if len(df) < 200:
        return None
        
    # EMA 200
    df['EMA_200'] = df['Close'].ewm(span=200, adjust=False).mean()
    
    # Bollinger Bands (30, 2.0)
    period = 30
    multiplier = 2.0
    df['BB_MA'] = df['Close'].rolling(period).mean()
    df['BB_STD'] = df['Close'].rolling(period).std()
    df['BB_UPPER'] = df['BB_MA'] + (df['BB_STD'] * multiplier)
    df['BB_LOWER'] = df['BB_MA'] - (df['BB_STD'] * multiplier)
    
    # %b
    df['PCT_B'] = (df['Close'] - df['BB_LOWER']) / (df['BB_UPPER'] - df['BB_LOWER'])
    
    return df

def run_bb_backtest(ticker, initial_capital=10000000, years=5):
    """BB 마틴게일 전략 5년치 주식 일봉 백테스트"""
    start_date = (datetime.datetime.now() - datetime.timedelta(days=(365 * years) + 200)).strftime('%Y-%m-%d')
    try:
        df = fdr.DataReader(ticker, start=start_date)
        if (df is None or len(df) == 0) and str(ticker).isdigit():
            df = yf.download(f"{ticker}.KS", start=start_date, progress=False)
            if df.empty:
                df = yf.download(f"{ticker}.KQ", start=start_date, progress=False)
    except Exception as e:
        return None
        
    df = calculate_bb_indicators(df)
    if df is None: return None
        
    backtest_days = int(252 * years)
    if len(df) <= backtest_days + 1: return None
        
    test_df = df.iloc[-(backtest_days+1):].copy()
    
    # 포트폴리오 관리 변수
    capital = initial_capital
    free_cash = capital
    
    # 상태 관리
    position = False
    buy_price = 0
    buy_qty = 0
    buy_date = None
    trades = []
    equity_curve = []
    
    # 마틴게일 및 쿨다운
    consecutive_losses = 0
    cooldown_days = 0
    
    # 파라미터
    TP_PCT = 0.10  # 익절 +10%
    SL_PCT = -0.05 # 손절 -5%
    
    for i in range(1, len(test_df)):
        latest = test_df.iloc[i]
        curr_price = latest['Close']
        date = test_df.index[i]
        
        if cooldown_days > 0:
            cooldown_days -= 1
            
        if not position:
            # 진입 조건: 쿨다운 종료 & 장기 상승장(Close > EMA200) & 볼밴 하단 터치(%b <= 0.02)
            if cooldown_days == 0 and latest['Close'] > latest['EMA_200'] and latest['PCT_B'] <= 0.02:
                # 초기 비중 100% (마틴게일 미적용, 항상 풀시드 진입)
                risk_pct = 1.00
                    
                invest_amount = capital * risk_pct
                if invest_amount > free_cash: 
                    invest_amount = free_cash # 가진 돈이 부족하면 올인
                    
                buy_price = curr_price
                buy_qty = invest_amount / curr_price
                free_cash -= invest_amount
                position = True
                buy_date = date
        else:
            # 당일 변동 기준으로 TP/SL 검사 (High가 TP 도달 시 익절 우선, Low가 SL 도달 시 손절)
            profit_high = (latest['High'] - buy_price) / buy_price
            profit_low = (latest['Low'] - buy_price) / buy_price
            
            sell = False
            sell_price = 0
            reason = ""
            
            if profit_high >= TP_PCT:
                sell = True
                sell_price = buy_price * (1 + TP_PCT)
                reason = "TP 10%"
            elif profit_low <= SL_PCT:
                sell = True
                sell_price = buy_price * (1 + SL_PCT)
                reason = "SL 5%"
                
            if sell:
                sell_amount = buy_qty * sell_price
                free_cash += sell_amount
                capital = free_cash
                actual_profit_pct = (sell_price - buy_price) / buy_price
                
                trades.append({
                    'buy_date': buy_date.strftime('%Y-%m-%d'),
                    'sell_date': date.strftime('%Y-%m-%d'),
                    'buy_price': buy_price,
                    'sell_price': sell_price,
                    'profit_pct': actual_profit_pct * 100,
                    'reason': reason,
                    'loss_count_at_buy': consecutive_losses
                })
                
                if actual_profit_pct > 0:
                    consecutive_losses = 0 # 익절 시 마틴게일 리셋
                else:
                    consecutive_losses += 1
                    cooldown_days = 3 # 휩쏘 방지 3일 쿨다운
                    
                position = False
                buy_qty = 0
                
        # 자산 평가액 기록
        curr_equity = free_cash + (buy_qty * curr_price) if position else free_cash
        equity_curve.append(curr_equity)
        
    # 백테스트 종료 시 강제 청산
    if position:
        sell_price = test_df.iloc[-1]['Close']
        actual_profit_pct = (sell_price - buy_price) / buy_price
        free_cash += buy_qty * sell_price
        capital = free_cash
        trades.append({
            'buy_date': buy_date.strftime('%Y-%m-%d'),
            'sell_date': test_df.index[-1].strftime('%Y-%m-%d'),
            'buy_price': buy_price,
            'sell_price': sell_price,
            'profit_pct': actual_profit_pct * 100,
            'reason': "백테스트 종료"
        })
        equity_curve.append(capital)
        
    total_return = ((capital - initial_capital) / initial_capital) * 100
    win_trades = [t for t in trades if t['profit_pct'] > 0]
    win_rate = (len(win_trades) / len(trades) * 100) if len(trades) > 0 else 0
    
    if equity_curve:
        equity_series = pd.Series(equity_curve)
        roll_max = equity_series.cummax()
        drawdown = equity_series / roll_max - 1.0
        mdd = drawdown.min() * 100
    else:
        mdd = 0

    return {
        'ticker': ticker,
        'total_return': total_return,
        'win_rate': win_rate,
        'trades_count': len(trades),
        'mdd': mdd
    }

if __name__ == "__main__":
    print("="*50)
    print("📈 BB 역추세 + 마틴게일 (주식 버전) 5년 백테스트 시작")
    print("="*50)
    
    try:
        tickers = db.get_watchlist()
    except Exception as e:
        print(f"DB 오류: {e}")
        exit()
        
    results = []
    start_time = time.time()
    
    for t in tickers:
        print(f"[{t}] 백테스트 진행 중...", end="", flush=True)
        res = run_bb_backtest(t)
        if res:
            results.append(res)
            print(f" 완료! (수익률: {res['total_return']:+.2f}%)")
        else:
            print(" 데이터 부족 건너뜀.")
            
    print("\n" + "="*50)
    print("📊 백테스트 결과 요약 (최근 5년)")
    print("="*50)
    
    if results:
        df_res = pd.DataFrame(results)
        avg_return = df_res['total_return'].mean()
        avg_win_rate = df_res['win_rate'].mean()
        avg_mdd = df_res['mdd'].mean()
        total_trades = df_res['trades_count'].sum()
        
        print(f"✔️ 평균 수익률: {avg_return:+.2f}%")
        print(f"✔️ 평균 승률: {avg_win_rate:.2f}%")
        print(f"✔️ 평균 MDD: {avg_mdd:.2f}%")
        print(f"✔️ 총 거래 횟수: {total_trades}회")
        print("-"*50)
        
        pd.set_option('display.max_rows', None)
        pd.set_option('display.float_format', lambda x: f'{x:.2f}')
        display_df = df_res[['ticker', 'total_return', 'win_rate', 'mdd', 'trades_count']].copy()
        display_df.columns = ['종목', '수익률(%)', '승률(%)', 'MDD(%)', '거래횟수']
        display_df = display_df.sort_values(by='수익률(%)', ascending=False).reset_index(drop=True)
        print(display_df.to_string())
    
    print(f"\n소요 시간: {time.time() - start_time:.2f}초")
