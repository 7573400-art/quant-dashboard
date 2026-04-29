import FinanceDataReader as fdr
import yfinance as yf
import pandas as pd
import datetime
import db
import time
import strategy

def run_dual_momentum_backtest(ticker, initial_capital=10000000, years=5, end_date_str="2024-12-31"):
    """특정 종목에 대해 듀얼 모멘텀(추세추종) 전략 5년치 백테스트를 수행합니다."""
    # 지표 계산(SMA200, ROC60 등)을 위해 300일 여유분 수집
    end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d')
    start_date = (end_date - datetime.timedelta(days=(365 * years) + 300)).strftime('%Y-%m-%d')
    try:
        df = fdr.DataReader(ticker, start=start_date, end=end_date_str)
        if (df is None or len(df) == 0) and str(ticker).isdigit():
            df = yf.download(f"{ticker}.KS", start=start_date, end=end_date_str, progress=False)
            if df.empty:
                df = yf.download(f"{ticker}.KQ", start=start_date, end=end_date_str, progress=False)
    except Exception as e:
        return None
        
    df = strategy.calculate_indicators(df)
    if df is None:
        return None
        
    backtest_days = int(252 * years)
    if len(df) <= backtest_days + 1:
        return None
        
    test_df = df.iloc[-(backtest_days+1):].copy()
    
    position = False
    buy_price = 0
    buy_qty = 0
    buy_date = None
    capital = initial_capital
    highest_price_since_buy = 0
    trades = []
    
    # 성과 기록용
    equity_curve = []
    equity_records = []
    
    for i in range(1, len(test_df)):
        latest = test_df.iloc[i]
        curr_price = latest['Close']
        date = test_df.index[i]
        
        # 듀얼 모멘텀 스코어 산출
        score = strategy.calculate_dual_momentum_score(latest)
        
        if not position:
            # 진입 조건: 모멘텀 스코어가 80점 이상 (강한 상승세 + 추세 정배열)
            if score >= 80:
                position = True
                buy_price = curr_price
                buy_qty = capital / curr_price # 풀매수 (단일 종목 테스트)
                buy_date = date
                highest_price_since_buy = curr_price
        else:
            # 보유 중: 최고가 갱신 추적 (트레일링 스탑용)
            if latest['High'] > highest_price_since_buy:
                highest_price_since_buy = latest['High']
                
            # 청산 조건 검사: 고점 대비 -15% 하락
            sell, reason, trigger_price = strategy.check_trailing_stop_condition(latest, highest_price_since_buy, trail_pct=0.15)
                
            if sell:
                # 슬리피지 고려 없이 트리거 가격(혹은 종가)으로 매도
                sell_price = trigger_price if trigger_price > 0 else curr_price
                sell_amount = buy_qty * sell_price
                profit_pct = (sell_price - buy_price) / buy_price
                capital = sell_amount
                
                trades.append({
                    'buy_date': buy_date.strftime('%Y-%m-%d'),
                    'sell_date': date.strftime('%Y-%m-%d'),
                    'buy_price': buy_price,
                    'sell_price': sell_price,
                    'profit_pct': profit_pct * 100,
                    'reason': reason
                })
                position = False
                highest_price_since_buy = 0
                buy_qty = 0
                
        # 자산 평가액 기록
        curr_equity = (buy_qty * curr_price) if position else capital
        equity_curve.append(curr_equity)
        equity_records.append({'date': date, 'equity': curr_equity})
        
    # 시뮬레이션 종료 시점에 포지션을 보유하고 있으면 강제 청산 (최종 성과 측정용)
    if position:
        sell_price = test_df.iloc[-1]['Close']
        profit_pct = (sell_price - buy_price) / buy_price
        capital = buy_qty * sell_price
        trades.append({
            'buy_date': buy_date.strftime('%Y-%m-%d'),
            'sell_date': test_df.index[-1].strftime('%Y-%m-%d'),
            'buy_price': buy_price,
            'sell_price': sell_price,
            'profit_pct': profit_pct * 100,
            'reason': "백테스트 종료 강제 청산"
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
        
        # 연도별 수익률 계산
        eq_df = pd.DataFrame(equity_records)
        eq_df['year'] = eq_df['date'].dt.year
        annual_returns = {}
        for year, group in eq_df.groupby('year'):
            s_eq = group.iloc[0]['equity']
            e_eq = group.iloc[-1]['equity']
            annual_returns[year] = ((e_eq - s_eq) / s_eq) * 100
    else:
        mdd = 0
        annual_returns = {}

    return {
        'ticker': ticker,
        'total_return': total_return,
        'win_rate': win_rate,
        'trades_count': len(trades),
        'mdd': mdd,
        'annual_returns': annual_returns,
        'final_capital': capital
    }

if __name__ == "__main__":
    print("="*50)
    print("🚀 공격적 듀얼 모멘텀 과거 5년(2020~2024) 백테스트 시작")
    print("="*50)
    
    try:
        tickers = db.get_watchlist()
    except Exception as e:
        print(f"데이터베이스 오류: {e}")
        exit()
        
    if not tickers:
        print("관심종목(Watchlist)이 비어있습니다.")
        exit()
        
    results = []
    start_time = time.time()
    
    for t in tickers:
        print(f"[{t}] 백테스트 진행 중...", end="", flush=True)
        res = run_dual_momentum_backtest(t, end_date_str="2024-12-31")
        if res:
            results.append(res)
            print(f" 완료! (수익률: {res['total_return']:+.2f}%)")
        else:
            print(" 데이터 부족 건너뜀.")
            
    print("\n" + "="*50)
    print("📊 듀얼 모멘텀 백테스트 결과 요약 (최근 5년)")
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
        
        # 연도별 평균 수익률 집계
        all_years = set()
        for res in results:
            all_years.update(res['annual_returns'].keys())
        all_years = sorted(list(all_years))
        
        print("📅 연도별 평균 수익률:")
        for y in all_years:
            y_returns = [r['annual_returns'][y] for r in results if y in r['annual_returns']]
            if y_returns:
                print(f"  - {y}년: {sum(y_returns)/len(y_returns):+.2f}%")
        print("-"*50)
        
        pd.set_option('display.max_rows', None)
        pd.set_option('display.float_format', lambda x: f'{x:.2f}')
        display_df = df_res[['ticker', 'total_return', 'win_rate', 'mdd', 'trades_count']].copy()
        display_df.columns = ['종목', '수익률(%)', '승률(%)', 'MDD(%)', '거래횟수']
        display_df = display_df.sort_values(by='수익률(%)', ascending=False).reset_index(drop=True)
        print(display_df.to_string())
    else:
        print("백테스트 데이터가 없습니다.")
        
    print(f"\n소요 시간: {time.time() - start_time:.2f}초")
