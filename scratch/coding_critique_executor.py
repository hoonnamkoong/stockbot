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
    # Load the draft code
    draft_files = [
        "src/strategy/simulators/sim1_psych.py",
        "src/strategy/simulators/sim2_spillover.py",
        "src/strategy/simulators/sim3_risk.py"
    ]
    code_context = ""
    for f in draft_files:
        with open(f, 'r', encoding='utf-8') as file:
            code_context += f"\n--- {f} ---\n{file.read()}\n"

    models = [
        "deepseek-coder-v2:16b",
        "deepseek-r1:8b"
    ]

    prompt_template = f"""
당신은 스톡봇(Stockbot)의 시니어 퀀트 개발자 및 QA입니다. 
Antigravity가 작성한 차세대 3-Track 시뮬레이터 1차 코드를 비평하세요.

[수정된 코드]
{code_context}

[비평 지침]
1. 설계 최적화: 현재 수정안보다 더 효율적이고 구조적으로 우수한 코딩 패턴이 있는가?
2. 영향도 추적: 이 수정으로 인해 연관된 다른 함수나 DB, UI에서 발생할 수 있는 버그는 무엇인가?
3. 범위 확인: 수정 대상 외의 코드가 변형되지 않았는가?
4. 로직의 구멍: 예를 들어, 섹터 맵핑의 한계, 데이터 지연에 따른 슬리피지(Slippage) 문제, 변수명 충돌 등을 확인하세요.

모든 답변은 한국어로 작성하세요.
"""

    results = {}
    for model in models:
        print(f"Running critique model: {model}...")
        results[model] = call_ollama(model, prompt_template)

    with open('scratch/coding_critique_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("Critique gathering complete. Results saved to scratch/coding_critique_results.json")

if __name__ == "__main__":
    main()
