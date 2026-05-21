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
    # 모델별 ROI 향상 제안 요약
    roi_proposals = {
        "DeepSeek-r1": "트레일링 스탑(Trailing Stop) 도입, 추세 지속 기간에 따른 다단계 손절/익절 전략, 하락장 역추종 전략.",
        "Qwen2.5": "거래대금/유동성 필터 강화로 잡음 제거, 너무 타이트한 손절 지양하여 추세 추종 기회 확보, 고성장 섹터 집중.",
        "Antigravity": "시장 지수(KOSPI/KOSDAQ) 필터링 도입, 수익률 상한제보다는 동적 목표치 설정."
    }

    prompt_context = f"""
당신은 스톡봇(Stockbot)의 ROI 최적화 전담 위원회입니다. 
다음은 각 모델이 제안한 수익률(ROI) 향상 방안입니다.

[제안서 요약]
{json.dumps(roi_proposals, ensure_ascii=False, indent=2)}

[과제]
1. 상대 모델의 제안 중 '가장 실전적이고 강력한 것' 하나를 선정하고 그 이유를 설명하세요.
2. 상대 모델 제안의 '잠재적 허점(Side Effect)'을 지적하세요. (예: 너무 잦은 매매, 수수료 문제 등)
3. 세 가지 제안을 통합하여, 1~4월 백테스트 수익률을 **확실히 플러스로 바꿀 수 있는 최적화된 '통합 ROI 매뉴얼'**을 도출하세요.

모든 답변은 한국어로 작성하세요.
"""

    models = ["deepseek-r1:8b", "qwen2.5-coder:7b"]
    results = {}

    for model in models:
        print(f"Running ROI optimization debate for: {model}...")
        results[model] = call_ollama(model, prompt_context)

    # 최종 통합 요약 (Antigravity's role)
    with open('scratch/roi_optimization_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("ROI Optimization Debate complete. Results saved to scratch/roi_optimization_results.json")

if __name__ == "__main__":
    main()
