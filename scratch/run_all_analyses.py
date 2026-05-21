import urllib.request
import json
import os

def run_ollama(model_name, prompt):
    data = {
        'model': model_name,
        'prompt': prompt,
        'stream': False
    }
    req = urllib.request.Request('http://localhost:11434/api/generate', 
                                 data=json.dumps(data).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=600) as response:
            res = json.loads(response.read().decode('utf-8'))
            return res.get('response', 'No response')
    except Exception as e:
        return f'Error: {e}'

with open('scratch/final_analysis_prompt.txt', 'r', encoding='utf-8') as f:
    prompt = f.read()

models = {
    'deepr': 'deepseek-r1:8b',
    'gemma': 'gemma4:latest',
    'qwen': 'qwen3:8b'
}

for key, model_name in models.items():
    print(f'Running {key} ({model_name})...')
    response = run_ollama(model_name, prompt)
    with open(f'scratch/analysis_{key}.md', 'w', encoding='utf-8') as f:
        f.write(response)
    print(f'Finished {key}.')
