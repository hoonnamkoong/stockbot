# -*- coding: utf-8 -*-
"""단계 1: 올라마로 약물/질병 추출
- 각 MD 파일에서 올라마 호출
- JSON 결과를 output/extraction_results/ 에 저장
"""
import sys, json, os, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = r"C:\Users\Hoon_DT\Desktop\본초서적\_md"
OUTPUT_DIR = r"C:\Users\Hoon_DT\gemini\stock\output\extraction_results"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def ask_ollama(text):
    """Ollama로 약물/질병 추출"""
    prompt = (
        "이 한문 의학 텍스트에서 모든 약물명과 질병/증상명을 추출하라.\n"
        "약물: 개별 약재 (黃耆, 甘草, 防風 등)\n"
        "질병/증상: 질환명, 증상 (黃疸, 自汗, 痘症 등)\n"
        "절대 텍스트를 바꾸지 말고, JSON으로만 반환하라.\n"
        '형식: {"drugs": ["약물1", "약물2", ...], "diseases": ["질병1", "질병2", ...]}\n\n'
        "텍스트:\n" + text[:3000]  # 토큰 절약
    )
    body = {
        "model": "qwen3-vl:8b-instruct-q8_0",
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    try:
        data = json.loads(out["response"])
        return data.get("drugs", []), data.get("diseases", [])
    except Exception as e:
        print(f"  JSON 파싱 실패: {e}")
        return [], []

def extract_all():
    """모든 MD 파일 처리"""
    all_files = []
    # 재귀적으로 모든 서브디렉토리의 MD 파일 찾기
    for root, dirs, files in os.walk(ROOT):
        for f in sorted(files):
            if f.lower().endswith(".md"):
                path = os.path.join(root, f)
                all_files.append((f, path))

    print(f"전체 파일: {len(all_files)}개")
    for i, (fname, path) in enumerate(all_files, 1):
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            drugs, diseases = ask_ollama(text)

            result = {"drugs": drugs, "diseases": diseases}
            # 순번을 파일명으로 사용 (충돌 방지, 간단함)
            out_path = os.path.join(OUTPUT_DIR, f"{i:02d}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            print(f"{i:>3}. OK  {fname:35s}  drugs={len(drugs):3d}  diseases={len(diseases):3d}")
        except Exception as e:
            print(f"{i:>3}. FAIL {fname:35s}  {e}")

if __name__ == "__main__":
    extract_all()
    print(f"OUT={OUTPUT_DIR}")
