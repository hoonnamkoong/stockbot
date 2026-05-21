
import os
import requests
import json

def run_ollama_api(model, prompt):
    print(f"--- Requesting {model} via API ---")
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False
    }
    try:
        response = requests.post(url, json=payload, timeout=300)
        if response.status_code == 200:
            return response.json().get('response', '')
        else:
            return f"Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Exception: {e}"

def main():
    files_to_review = [
        "src/pipeline/orchestrator.py",
        "src/pipeline/context.py",
        "src/pipeline/workers/trade_engine.py",
        "src/strategy/advisor.py",
        "src/data/schemas.py",
        "src/app/api/trade/history/route.ts"
    ]
    
    code_context = ""
    for f_path in files_to_review:
        if os.path.exists(f_path):
            with open(f_path, 'r', encoding='utf-8') as f:
                code_context += f"\n\n--- File: {f_path} ---\n"
                code_context += f.read()

    system_prompt = f"""
당신은 한국 주식 자동 매매 시스템(Stockbot)의 시니어 코드 리뷰어입니다. 
최근 수행된 다음 변경 사항들에 대해 정밀 교차 분석을 수행하십시오.

[최근 변경 사항 요약]
1. orchestrator.py: is_trading_day() 체크 추가.
2. context.py: should_notify() 조건을 정각(0-2분)으로 제한.
3. trade_engine.py: 상세 리포트 대상(2+1) 선정 로직 및 중복 발송 방지.
4. advisor.py: 딥다이브 리포트 양식 고정 및 매도 후보 선정 로직 추가.
5. schemas.py: SyncState 필드 확장.
6. history/route.ts: 신규 시뮬레이터 매핑.

[분석 요청 사항]
1. 설계 최적화: 현재 수정안보다 더 우수한 패턴이 있는가?
2. 영향도 추적: 연관된 다른 함수(StorageManager, NotifierWorker 등), DB, UI에서 발생할 수 있는 잠재적 버그는?
3. 버그 포착: 시간대(KST), 인코딩(UTF-8), 데이터 타입(JSON) 관련 잠재적 위험 요소를 찾아내십시오.

소스 코드:
{code_context}

비평을 한국어로 작성하십시오.
"""

    models = ["deepseek-coder-v2:16b", "deepseek-r1:8b"]
    responses = []
    
    for model in models:
        response = run_ollama_api(model, system_prompt)
        responses.append(f"### Model: {model}\n\n{response}\n")

    with open("scratch/coding_debate_results.md", "w", encoding='utf-8') as f:
        f.write("# Coding Debate Results (DeepSeek Coder V2 & R1)\n\n")
        for r in responses:
            f.write(r)
            f.write("\n---\n")

if __name__ == "__main__":
    main()
