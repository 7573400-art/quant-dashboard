import FinanceDataReader as fdr
import yfinance as yf
import pandas as pd
import datetime
import numpy as np
import db
import time
import strategy

def run_backtest(ticker, initial_capital=10000, years=5):
    """특정 종목에 대해 다년도 백테스트를 수행합니다."""
    # 데이터 수집 (지표 계산을 위해 200일 여유분 추가)
    start_date = (datetime.datetime.now() - datetime.timedelta(days=(365 * years) + 200)).strftime('%Y-%m-%d')
    try:
        df = fdr.DataReader(ticker, start=start_date)
        if (df is None or len(df) == 0) and str(ticker).isdigit():
            df = yf.download(f"{ticker}.KS", start=start_date, progress=False)
            if df.empty:
                df = yf.download(f"{ticker}.KQ", start=start_date, progress=False)
    except Exception as e:
        return None
        
    df = strategy.calculate_indicators(df)
    if df is None:
        return None
        
    # 설정된 연도(약 252 거래일 * years)만 백테스트 대상으로 삼음
    backtest_days = int(252 * years)
    if len(df) <= backtest_days + 1:
        return None
        
    test_df = df.iloc[-(backtest_days+1):].copy() # prev를 참조해야 하므로 +1
    
    position = False
    buy_price = 0
    buy_date = None
    target_price = 0
    capital = initial_capital
    trades = []
    
    # 성과 기록용 (MDD 계산을 위함)
    equity_curve = []
    
    for i in range(1, len(test_df)):
        prev = test_df.iloc[i-1]
        latest = test_df.iloc[i]
        curr_price = latest['Close']
        date = test_df.index[i]
        
        score = strategy.calculate_score(latest, prev)
        
        if not position:
            # 매수 조건 (70점 이상)
            if score >= 70:
                position = True
                buy_price = curr_price
                buy_date = date
                
                # 동적 목표가 산출
                target_price = strategy.calculate_target_price(curr_price, latest['ATR'], score)
        else:
            # 매도 조건 검사 (하드 손절, 목표가, 모멘텀 상실)
            sell, reason, sell_price = strategy.check_sell_condition(latest, buy_price, target_price, score, stop_loss_pct=0.05)
                
            if sell:
                profit_pct = (sell_price - buy_price) / buy_price
                profit_val = capital * profit_pct
                capital += profit_val
                
                trades.append({
                    'buy_date': buy_date.strftime('%Y-%m-%d'),
                    'sell_date': date.strftime('%Y-%m-%d'),
                    'buy_price': buy_price,
                    'sell_price': sell_price,
                    'profit_pct': profit_pct * 100,
                    'reason': reason
                })
                position = False
                
        # 매일의 자산 가치 기록
        curr_capital = capital
        if position:
            # 보유 중인 경우 당일 종가 기준으로 자산 평가
            curr_capital = capital + (capital * ((curr_price - buy_price) / buy_price))
        equity_curve.append(curr_capital)
        
    # 시뮬레이션 종료 시점에 포지션을 보유하고 있으면 강제 청산
    if position:
        sell_price = test_df.iloc[-1]['Close']
        profit_pct = (sell_price - buy_price) / buy_price
        capital += capital * profit_pct
        trades.append({
            'buy_date': buy_date.strftime('%Y-%m-%d'),
            'sell_date': test_df.index[-1].strftime('%Y-%m-%d'),
            'buy_price': buy_price,
            'sell_price': sell_price,
            'profit_pct': profit_pct * 100,
            'reason': "백테스트 종료 강제 청산"
        })
        equity_curve.append(capital)
        
    # 지표 계산
    total_return = ((capital - initial_capital) / initial_capital) * 100
    win_trades = [t for t in trades if t['profit_pct'] > 0]
    win_rate = (len(win_trades) / len(trades) * 100) if len(trades) > 0 else 0
    
    # MDD (최대 낙폭) 계산
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
        'mdd': mdd,
        'final_capital': capital
    }

if __name__ == "__main__":
    print("="*50)
    print("🚀 퀀트 알고리즘 5년치 백테스트 시작")
    print("="*50)
    
    try:
        tickers = db.get_watchlist()
    except Exception as e:
        print(f"데이터베이스 오류: {e}")
        exit()
        
    if not tickers:
        print("관심종목(Watchlist)이 비어있습니다. 대시보드에서 종목을 추가해주세요.")
        exit()
        
    results = []
    start_time = time.time()
    
    print(f"총 {len(tickers)}개 종목에 대한 시뮬레이션을 진행합니다...\n")
    
    for t in tickers:
        print(f"[{t}] 백테스트 진행 중...", end="", flush=True)
        res = run_backtest(t)
        if res:
            results.append(res)
            print(f" 완료! (수익률: {res['total_return']:+.2f}%)")
        else:
            print(" 데이터 부족 또는 오류로 건너뜀.")
            
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
        
        # 종목별 상세 결과 출력
        # Pandas 출력 옵션 설정
        pd.set_option('display.max_rows', None)
        pd.set_option('display.float_format', lambda x: f'{x:.2f}')
        
        display_df = df_res[['ticker', 'total_return', 'win_rate', 'mdd', 'trades_count']].copy()
        display_df.columns = ['종목', '수익률(%)', '승률(%)', 'MDD(%)', '거래횟수']
        display_df = display_df.sort_values(by='수익률(%)', ascending=False).reset_index(drop=True)
        print(display_df.to_string())
    else:
        print("백테스트를 완료할 수 있는 종목 데이터가 없습니다.")
        
    print(f"\n소요 시간: {time.time() - start_time:.2f}초")
