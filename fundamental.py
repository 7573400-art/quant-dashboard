import yfinance as yf
import pandas as pd
import datetime
import urllib.parse
import xml.etree.ElementTree as ET
import requests

def get_fundamental_data(ticker):
    """
    yfinance를 활용하여 종목의 펀더멘털 데이터와 애널리스트 목표가를 수집합니다.
    """
    info = {}
    try:
        # 한국 주식의 경우 .KS, .KQ 접미사 처리 로직 필요 (이전 로직 참고)
        ticker_obj = yf.Ticker(ticker)
        
        info['ticker'] = ticker
        info['current_price'] = ticker_obj.info.get('currentPrice') or ticker_obj.info.get('regularMarketPrice', 0)
        
        # 적정 주가 (애널리스트 평균 목표가)
        info['target_mean_price'] = ticker_obj.info.get('targetMeanPrice', info['current_price'])
        
        # 밸류에이션 지표
        info['trailingPE'] = ticker_obj.info.get('trailingPE', 0)
        info['forwardPE'] = ticker_obj.info.get('forwardPE', 0)
        info['priceToBook'] = ticker_obj.info.get('priceToBook', 0)
        
        # 괴리율 계산 (현재가 vs 적정가)
        if info['current_price'] > 0 and info['target_mean_price'] > 0:
            diff = info['target_mean_price'] - info['current_price']
            info['discount_rate'] = (diff / info['target_mean_price']) * 100
        else:
            info['discount_rate'] = 0
            
    except Exception as e:
        print(f"Error fetching fundamental data for {ticker}: {e}")
        
    return info

def get_relative_strength(ticker, market_index='^GSPC', days=90):
    """
    최근 90일간 시장 지수(S&P 500 등) 대비 상대적 수익률(Relative Strength) 산출
    """
    try:
        start_date = (datetime.datetime.now() - datetime.timedelta(days=days+30)).strftime('%Y-%m-%d')
        
        # 종목 데이터
        stock_df = yf.download(ticker, start=start_date, progress=False)
        if stock_df.empty: return 0
        
        # 지수 데이터
        market_df = yf.download(market_index, start=start_date, progress=False)
        if market_df.empty: return 0
        
        stock_df = stock_df.iloc[-days:]
        market_df = market_df.iloc[-days:]
        
        stock_return = float((stock_df['Close'].iloc[-1] - stock_df['Close'].iloc[0]) / stock_df['Close'].iloc[0] * 100)
        market_return = float((market_df['Close'].iloc[-1] - market_df['Close'].iloc[0]) / market_df['Close'].iloc[0] * 100)
        
        return stock_return - market_return
    except Exception as e:
        print(f"Error fetching relative strength for {ticker}: {e}")
        return 0.0

def fetch_news(query, max_items=5):
    """
    구글 뉴스 RSS에서 쿼리와 관련된 최신 뉴스를 가져옵니다.
    """
    encoded_query = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
    news_list = []
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            root = ET.fromstring(res.text)
            for item in root.findall('.//item')[:max_items]:
                title = item.find('title').text
                news_list.append(title)
    except Exception as e:
        print(f"Error fetching news for {query}: {e}")
    return news_list

def calculate_market_score(discount_rate, rs_score):
    """
    할인율(50점)과 상대 모멘텀(50점)을 결합하여 100점 만점의 시장/펀더멘털 점수를 산출합니다.
    """
    score = 0
    
    # 1. 가치 밸류에이션 (할인율 50점)
    if discount_rate >= 20: score += 50
    elif discount_rate >= 10: score += 30
    elif discount_rate > 0: score += 10
    
    # 2. 시장 주도력 (상대강도 RS 50점)
    if rs_score >= 10: score += 50
    elif rs_score >= 5: score += 30
    elif rs_score > 0: score += 10
    elif rs_score < -10: score -= 10 # 심각한 언더퍼폼 감점
    
    return max(0, min(100, score))
