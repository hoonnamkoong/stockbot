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
    # 현재 수정된 코드들을 로드
    base_dir = "c:/Users/Hoon_DT/gemini/stock/src/strategy/simulators"
    files_to_review = ["base_simulator.py", "sim1_psych.py", "sim2_spillover.py", "sim3_risk.py"]
    
    code_context = ""
    for f_name in files_to_review:
        path = os.path.join(base_dir, f_name)
        with open(path, 'r', encoding='utf-8') as f:
            code_context += f"### {f_name}\n```python\n{f.read()}\n```\n\n"

    prompt_context = f"""
당신은 스톡봇(Stockbot)의 시니어 코드 리뷰어입니다. 
최근 '차세대 V2 시뮬레이터'로 대규모 로직 수정이 있었습니다. 아래 코드를 정밀 분석하여 비평하세요.

[수정된 코드 목록]
{code_context}

[분석 지침]
1. 설계 최적화: 트레일링 스탑, 지수 필터, 동적 테마 매핑 로직이 효율적인가? 더 나은 패턴이 있는가?
2. 영향도 추적 (Side Effect):
   - BaseSimulator의 state 구조 변경이 기존 JSON 저장/로드와 호환되는가?
   - sim2에서 SECTOR_MAP을 제거했는데, 이를 참조하던 다른 기능(UI, 스크래퍼 등)에서 에러가 발생할 가능성은?
   - UI(TradeClient.tsx)에서 시뮬레이터 통계를 렌더링할 때 데이터 구조 변화로 인한 깨짐 현상이 예상되는가?
3. 안정성: ZeroDivision, NaN 처리, 데이터 누락 방어 로직이 완벽한가?

비평 결과를 한국어로 작성하세요.
"""

    models = ["deepseek-coder-v2:16b", "deepseek-r1:8b"]
    results = {}

    for model in models:
        print(f"Running code review for: {model}...")
        results[model] = call_ollama(model, prompt_context)

    with open('scratch/coding_review_v2_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("Code review complete. Results saved to scratch/coding_review_v2_results.json")

if __name__ == "__main__":
    main()
