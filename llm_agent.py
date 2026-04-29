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
    earnings_date = fund_data.get('earnings_date', '미정')
    
    news_text = "\n".join([f"- {n}" for n in news_titles])
    
    # 2. Prompt 구성
    if short_summary:
        system_prompt = """
당신은 최고의 월스트리트 퀀트 애널리스트이자 가치투자 전문가입니다.
단순히 과거에 발표된 뉴스를 요약하는 것이 아니라, 향후 주가를 움직일 '선행적 기대감'과 '예정된 촉매제(일정, 실적발표 등)'를 바탕으로 미래 모멘텀을 추론해야 합니다.

[분석 지침]
1. 향후 촉매제 발굴: 제공된 예상/전망 뉴스 및 실적발표일에서 주가 폭등의 트리거가 될 이벤트를 찾아라.
2. 결론 도출: 최종 투자 의견(선취매/관망/매도)을 결정하라.

[출력 포맷 (반드시 아래 형식에 맞춰 단 한 줄로만 출력할 것)]
{종목명} ({할인율}% 저평가) - [향후 1~3개월 내 핵심 모멘텀 및 예상 이벤트 1문장 요약] ([투자의견])
예시: 삼성전자 (-19.5% 저평가) - 다음 달 HBM 퀄테스트 통과 및 3분기 가이던스 상향 기대감으로 반등 예상 (선취매 권고)
"""
    else:
        system_prompt = """
당신은 최고의 월스트리트 퀀트 애널리스트이자 가치투자 전문가입니다.
과거에 발생한 뉴스를 후행적으로 요약하는 것을 금지합니다. 오직 향후 시장의 '선행적 기대감'과 다가오는 '촉매제(Catalyst)'에 집중하여 폭발적인 모멘텀을 추론해야 합니다.

[분석 지침]
1. 미래 가치 분석: 현재 주가와 적정가(애널리스트 목표가)의 괴리를 바탕으로, 앞으로 이 괴리를 좁힐 강력한 미래 이벤트가 무엇인지 찾아라.
2. 논리 구축: 다가오는 이벤트를 바탕으로 현재 위치를 다음 3가지 중 하나로 명확히 분류하라.
   - 선취매 기회 (강력한 호재 대기중)
   - 모멘텀 부재/가치 함정 (예정된 이벤트 없음)
   - 불확실성 리스크 (이벤트 결과 예측 불가)
3. 결론 도출: 주가가 오르기 위한 '예정된 상승 촉매제(Upcoming Trigger)'를 제시하고 최종 투자 의견(적극 선취매/관망/매도)을 결정하라.

[출력 포맷 (반드시 아래 양식을 정확히 지킬 것)]
종목명: {종목명}
현재가 vs 적정가: {현재가}원 / {적정가}원 ({할인율}% 저평가)
예정된 모멘텀: "[향후 1~3개월 내 주가를 견인할 핵심 이벤트 및 기대감 요약]"
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
- 다음 실적발표일: {earnings_date}
- 시장 대비 상대 모멘텀(RS): {rs_score:.1f}%
- 선행적 기대감 / 전망 뉴스:
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
