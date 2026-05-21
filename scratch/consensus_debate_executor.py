import requests
import json
import os

def call_ollama(model, prompt):
    url = "http://localhost:11434/api/generate"
    data = {
        "model": model,
        "prompt": prompt,
        "stream": False
    }
    try:
        response = requests.post(url, json=data, timeout=600)
        if response.status_code == 200:
            return response.json().get('response', '')
        else:
            return f"Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Exception: {str(e)}"

def main():
    prompt_context = """
당신은 스톡봇(Stockbot)의 전략 설계자입니다. 이전 토론에서 당신들은 각자의 주장만 나열했을 뿐 진정한 합의를 이루지 못했습니다. 
이번에는 다음 지침에 따라 '최종 합의안'을 도출하세요.

[필수 과제]
1. 상대 모델의 제안(DeepSeek의 트레일링 스탑, Qwen의 유동성 필터, Antigravity의 지수 필터) 중 **당신의 로직에 반드시 결합해야 할 '신의 한 수'**를 선정하고, 왜 그것이 당신의 약점을 보완하는지 설명하세요.
2. **Track 2 (섹터 전이형)의 핵심 질문에 답하세요**:
   - '형님(리더)'과 '아우(팔로워)'의 관계를 누가, 어떻게 정합니까?
   - 수동 매핑(Hardcoding)의 한계를 극복하기 위해, **실시간 데이터(뉴스 키워드 중복도, 주가 상관계수, 섹터 분류 등)**를 활용하여 이 관계를 자동으로 찾아낼 '알고리즘적 메커니즘'을 제안하세요.
   - 예: "매일 아침 Gemini가 뉴스 키워드를 분석해 테마 그룹을 생성한다" 또는 "5일간 주가 흐름이 80% 일치하는 종목을 형제주로 묶는다" 등.

[금기 사항]
- "내 말이 맞다"는 식의 주장을 반복하지 마십시오.
- 상대의 장점을 구체적으로 어떻게 코드로 구현할지 '통합'에 집중하세요.

모든 답변은 한국어로 작성하세요.
"""

    models = ["deepseek-r1:8b", "qwen2.5-coder:7b"]
    results = {}

    for model in models:
        print(f"Running Consensus Debate for: {model}...")
        results[model] = call_ollama(model, prompt_context)

    # 최종 합의 요약 (Antigravity's role)
    with open('scratch/consensus_debate_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("Consensus Debate complete. Results saved to scratch/consensus_debate_results.json")

if __name__ == "__main__":
    main()
