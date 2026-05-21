import urllib.request
import json
import os

def run_ollama(model_name, prompt):
    data = {'model': model_name, 'prompt': prompt, 'stream': False}
    req = urllib.request.Request('http://localhost:11434/api/generate', 
                                 data=json.dumps(data).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=600) as response:
            res = json.loads(response.read().decode('utf-8'))
            return res.get('response', 'No response')
    except Exception as e: return f'Error: {e}'

def read_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

sims = {
    'Psych': read_file('src/strategy/simulators/sim1_psych.py'),
    'Spillover': read_file('src/strategy/simulators/sim2_spillover.py'),
    'Risk': read_file('src/strategy/simulators/sim3_risk.py')
}

prompt_template = """당신은 코드 분석 전문가입니다. 아래 제공된 3개의 시뮬레이터 클래스 코드를 분석하고, **오직 코드에 기술된 수치와 로직**만을 바탕으로 평가하십시오.
RSI, 볼린저 밴드 등 코드에 없는 지표를 언급하면 절대 안 됩니다.

[분석 코드]
{code_content}

[요청 사항]
1. 각 클래스별 진입(buy) 및 청산(sell) 조건 요약 (실제 수치 포함)
2. 리스크 관리 방식 (손절, 트레일링 스탑 등)
3. 코드의 취약점 또는 개선 필요 사항

한국어로 답변해 주세요."""

code_content = "\n\n".join([f"--- {name} ---\n{code}" for name, code in sims.items()])
prompt = prompt_template.format(code_content=code_content)

models = {
    'deepr': 'deepseek-r1:8b',
    'gemma': 'gemma4:latest',
    'qwen': 'qwen2.5-coder:14b' # 7b 대신 14b 사용
}

for key, model_name in models.items():
    print(f'Running {key}...')
    resp = run_ollama(model_name, prompt)
    with open(f'scratch/analysis_v3_{key}.md', 'w', encoding='utf-8') as f:
        f.write(resp)
    print(f'Finished {key}.')
