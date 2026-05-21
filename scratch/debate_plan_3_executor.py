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
    # 현재 상황 데이터
    current_results = {
        "Track 1 (심리 폭발형)": "-2.44% (방어력은 좋으나 수익성 부족)",
        "Track 2 (섹터 전이형)": "0.00% (리더-아우 매칭 실패로 거래 전무)",
        "Track 3 (스마트 리스크)": "-8.29% (추세 추종 실패 및 잦은 손절)"
    }

    prompt_context = f"""
당신은 스톡봇(Stockbot)의 전략 팀에 소속된 AI 퀀트 전문가입니다. 
현재 도입된 '차세대 3-Track 시뮬레이터'의 1~4월 백테스트 결과가 다음과 같이 실망스럽습니다.

[현재 결과]
{json.dumps(current_results, ensure_ascii=False, indent=2)}

[집중 토론 과제]
1. Track 2 (섹터 전이형) 해결안: 
   - 현재 삼성전자 같은 리더가 올라도 '아우(관련주)'가 리스트에 늦게 뜨거나 진입 문턱(1%)에 걸려 거래가 안 됨.
   - 데이터 수집 한계(상한 800개)를 고려하여, 리스트에 없어도 리더를 추적하거나 아우의 진입 문턱을 높이는 것 외에 더 창의적이고 실질적인 해결책은?
2. 전체 수익률(ROI) 향상 방안:
   - 하락장에서 방어만 하는 게 아니라, 변동성을 이용해 수익을 낼 수 있는 구체적인 튜닝 방안(익절/손절 로직, 시장 필터 등).

각 모델별로 위 과제에 대한 구체적인 '개선 설계안'과 '비평'을 제출하세요. 
모든 답변은 한국어로 작성하세요.
"""

    models = ["deepseek-r1:8b", "qwen2.5-coder:7b"]
    results = {}

    for model in models:
        print(f"Running debate for: {model}...")
        results[model] = call_ollama(model, prompt_context)

    # 교차 비평 단계 (Simple version for Plan 3)
    critique_prompt = f"""
다음은 두 모델의 제안서입니다. 
서로의 제안에서 '실행 불가능한 점'이나 '추가적인 리스크'를 비평하고, 
가장 수익성이 높을 것으로 예상되는 최적의 조합을 추천하세요.

[제안서]
{json.dumps(results, ensure_ascii=False, indent=2)}
"""
    print("Running cross-critique...")
    results['final_critique'] = call_ollama("deepseek-r1:8b", critique_prompt)

    with open('scratch/debate_plan_3_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("Debate complete. Results saved to scratch/debate_plan_3_results.json")

if __name__ == "__main__":
    main()
