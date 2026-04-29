import pandas as pd
import numpy as np

def calculate_indicators(df):
    """데이터프레임에 보조지표를 계산하여 추가합니다."""
    if df is None or len(df) < 200:
        return None
        
    df = df.copy()
    
    # 이동평균선
    df['SMA_20'] = df['Close'].rolling(20).mean()
    df['SMA_50'] = df['Close'].rolling(50).mean()
    df['SMA_200'] = df['Close'].rolling(200).mean()
    
    # 상대거래량 (RVOL)
    df['RVOL'] = df['Volume'] / df['Volume'].rolling(20).mean()
    
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # MACD
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # 듀얼 모멘텀용 60일 수익률 (Rate of Change)
    df['ROC_60'] = df['Close'].pct_change(periods=60) * 100
    
    # ATR (목표가 산출 및 변동성 측정용)
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift()).abs()
    low_close = (df['Low'] - df['Close'].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    df['ATR'] = true_range.rolling(14).mean()
    
    return df

def calculate_score(latest, prev):
    """
    실전 자동매매용 '눌림목(Pullback)' 패턴 기반 퀀트 스코어 산출
    100점 만점 기준
    """
    score = 0
    curr_price = latest['Close']
    
    # 1. 추세 및 눌림목 조건 (가장 중요: 40점)
    # 50일선이 상승 추세에 있고, 주가가 20일선 근처(±2%)로 눌렸을 때 가점
    if latest['SMA_20'] > latest['SMA_50']:
        score += 10 # 기본 정배열
        
        # 20일선 눌림목 조건 (주가가 20일선의 98% ~ 102% 사이)
        lower_bound = latest['SMA_20'] * 0.98
        upper_bound = latest['SMA_20'] * 1.02
        if lower_bound <= curr_price <= upper_bound:
            score += 30 # 완벽한 눌림목 타점
    
    # 2. 과열 방지 및 모멘텀 (RSI: 20점)
    rsi = latest['RSI']
    if 40 <= rsi <= 60:
        # 눌림목은 RSI가 40~60 사이로 식었을 때가 좋음
        score += 20
    elif rsi > 70:
        # 과매수 구간 진입은 눌림목이 아님 (추격매수 방지)
        score -= 20
        
    # 3. 수급 (RVOL: 15점)
    # 눌림목에서 반등할 때 거래량이 실리면 긍정적
    if latest['RVOL'] >= 1.2:
        score += 15
        
    # 4. MACD 모멘텀 반전 (15점)
    if latest['MACD'] > latest['Signal_Line'] or (latest['MACD'] - latest['Signal_Line']) > (prev['MACD'] - prev['Signal_Line']):
        score += 15
        
    # 5. 당일 양봉 및 반등 확인 (10점)
    if curr_price > latest['Open'] and curr_price > prev['Close']:
        score += 10
        
    return int(max(0, min(100, score)))

def check_sell_condition(latest, buy_price, target_price, current_score, stop_loss_pct=0.05):
    """
    실전 하드 손절매 및 청산 조건을 검사합니다.
    return: (매도여부(bool), 청산사유(str), 체결가격(float))
    """
    curr_price = latest['Close']
    
    # 1. 하드 손절매 (Stop-Loss)
    stop_price = buy_price * (1 - stop_loss_pct)
    if latest['Low'] <= stop_price:
        return True, f"하드 손절매(-{stop_loss_pct*100}%)", stop_price
        
    # 2. 목표가 도달 (Take-Profit)
    if latest['High'] >= target_price:
        return True, "목표가 도달", target_price
        
    # 3. 모멘텀 상실 (시간끌기 또는 추세이탈)
    if current_score <= 30:
        return True, "스코어 하락(모멘텀 상실)", curr_price
        
    return False, "", 0.0

def calculate_target_price(curr_price, atr, score):
    """점수 기반 변동성(ATR)을 곱한 동적 목표가 산출"""
    atr_val = atr if not pd.isna(atr) else (curr_price * 0.05)
    atr_multiplier = 1.0 + ((score / 100) * 1.5) # 눌림목이므로 기대 수익을 조금 더 길게(최대 2.5배)
    return curr_price + (atr_val * atr_multiplier)

# ==========================================
# 듀얼 모멘텀 (추세추종) 전용 매매 로직
# ==========================================

def calculate_dual_momentum_score(latest):
    """
    절대 모멘텀(SMA200)과 상대 모멘텀(ROC_60)을 결합한 스코어 산출
    """
    score = 0
    
    # 1. 절대 모멘텀 필터: 200일선 아래면 스코어 0 (절대 매수 불가)
    if latest['Close'] < latest['SMA_200']:
        return 0
        
    # 2. 상대 모멘텀 (ROC 60) - 진입 시점 앞당기기
    roc = latest['ROC_60'] if not pd.isna(latest['ROC_60']) else 0
    if roc > 10: score += 50
    elif roc > 5: score += 30
    elif roc > 0: score += 10
    
    # 3. 단기 추세 정배열 (골든크로스 초입 포착)
    if latest['Close'] > latest['SMA_20'] and latest['SMA_20'] > latest['SMA_50']:
        score += 30
        
    # 4. 볼린저밴드나 RSI 과열 방지 (급등주 묻지마 추격 방지)
    if not pd.isna(latest.get('RSI', 50)) and latest.get('RSI', 50) > 80:
        score -= 20
        
    return int(max(0, min(100, score)))

def check_trailing_stop_condition(latest, highest_price, trail_pct=0.15):
    """
    고점 대비 일정 비율(trail_pct) 하락 시 전량 청산 (휩쏘 견디기)
    """
    curr_price = latest['Close']
    
    # 1. 트레일링 스탑 (최고점 대비 하락)
    trailing_stop_price = highest_price * (1 - trail_pct)
    if latest['Low'] <= trailing_stop_price:
        return True, f"트레일링 스탑(-{trail_pct*100}%) 발동", trailing_stop_price
        
    return False, "", 0.0

