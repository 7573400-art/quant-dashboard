import requests
import json
import fundamental

def generate_reasoning_report(ticker, stock_name, model="llama3.2", short_summary=False):
    """
    Ollama를 통해 가치-추론 리포트를 생성합니다.
    """
    # 1. Input Data 수집
    fund_data = fundamental.get_fundamental_data(ticker)
    rs_score = fundamental.get_relative_strength(ticker)
    news_titles = fundamental.fetch_news(stock_name, max_items=5)
    
    current_price = fund_data.get('current_price', 0)
    target_price = fund_data.get('target_mean_price', 0)
    discount = fund_data.get('discount_rate', 0)
    pe = fund_data.get('trailingPE', 0)
    forward_pe = fund_data.get('forwardPE', 0)
    
    news_text = "\n".join([f"- {n}" for n in news_titles])
    
    # 2. Prompt 구성
    if short_summary:
        system_prompt = """
당신은 최고의 월스트리트 퀀트 애널리스트이자 가치투자 전문가입니다.
단순한 기술적 지표가 아닌, '가치-가격 괴리 분석'과 '촉매제(Catalyst) 추론'을 수행하여 핵심만 '단 한 줄'로 요약해야 합니다.

[분석 지침]
1. 현상 파악: 현재 주가와 적정가의 괴리 원인을 파악하라.
2. 논리 구축: 일시적 악재 / 가치 함정 / 정보 비대칭 중 하나로 분류하라.
3. 결론 도출: 최종 투자 의견(매수/관망/매도)을 결정하라.

[출력 포맷 (반드시 아래 형식에 맞춰 단 한 줄로만 출력할 것)]
{종목명} ({할인율}% 저평가) - [저평가 사유 및 촉매제 1문장 요약] ([투자의견])
예시: 삼성전자 (-19.5% 저평가) - 노조 파업 리스크 등 일시적 악재로 하락했으나 HBM 승인 시 반등 예상 (매수 권고)
"""
    else:
        system_prompt = """
당신은 최고의 월스트리트 퀀트 애널리스트이자 가치투자 전문가입니다.
단순한 기술적 지표가 아닌, '가치-가격 괴리 분석'과 '촉매제(Catalyst) 추론'을 수행해야 합니다.

[분석 지침]
1. 현상 파악: 현재 주가와 적정가(애널리스트 목표가)의 괴리가 왜 발생하는지 주어진 뉴스와 지표에서 찾아라.
2. 논리 구축: 현재 저평가된 이유를 다음 3가지 중 하나로 명확히 분류하라.
   - 일시적 악재 (매수 기회)
   - 구조적 저평가/가치 함정 (매수 보류)
   - 정보 비대칭 (대박 기회)
3. 결론 도출: 주가가 오르기 위한 '상승 촉매제(Trigger)'를 제시하고 최종 투자 의견(적극 매수/관망/매도)을 결정하라.

[출력 포맷 (반드시 아래 양식을 정확히 지킬 것)]
종목명: {종목명}
현재가 vs 적정가: {현재가}원 / {적정가}원 ({할인율}% 저평가)
저평가 사유: "[사유 요약]"
상승 촉매제: "[촉매제 요약]"
최종 의견: "[의견 요약]"
"""

    user_prompt = f"""
[Input Data]
- 종목: {stock_name} ({ticker})
- 현재가: {current_price}
- 애널리스트 평균 목표가(적정가): {target_price}
- 할인율(괴리율): {discount:.1f}%
- P/E: {pe:.1f}, Forward P/E: {forward_pe:.1f}
- 시장 대비 상대 모멘텀(RS): {rs_score:.1f}%
- 최근 주요 뉴스:
{news_text}

위 데이터를 바탕으로 분석 지침에 맞게 추론 리포트를 작성해.
"""
    if short_summary:
        user_prompt += "\n반드시 단 한 줄로 핵심만 요약해서 출력해줘."
    else:
        user_prompt += "\n출력 포맷에 맞춰서 텍스트만 깔끔하게 출력해줘."
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "stream": False,
        "options": {
            "temperature": 0.2
        }
    }
    
    try:
        res = requests.post("http://localhost:11434/api/chat", json=payload, timeout=30)
        if res.status_code == 200:
            return res.json().get("message", {}).get("content", "").strip()
        else:
            return f"Ollama API Error: {res.status_code}"
    except Exception as e:
        return f"Error communicating with Ollama: {e}"

if __name__ == "__main__":
    # Test logic
    print("삼성전자 추론 리포트 생성 중...")
    report = generate_reasoning_report("005930.KS", "삼성전자")
    print("\n" + "="*50 + "\n")
    print(report)
    print("\n" + "="*50 + "\n")
