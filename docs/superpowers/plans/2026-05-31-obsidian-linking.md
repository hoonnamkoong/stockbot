# Obsidian 위키링크 추가 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 본초서적 MD 파일들에 약물 ↔ 질병/증상 양방향 마크다운 링크를 추가하여 Obsidian에서 의학 용어 네트워크를 시각화.

**Architecture:** Ollama(qwen3:14b)로 25개 파일에서 약물/질병을 자동 추출 → 정규화 및 통합 → 정방향 링크([[term]]) 삽입 → 역방향 링크(본초備要 항목에 "관련 질병" 섹션) 추가 → 본문 보존 검증.

**Tech Stack:** Python 3.8+, Ollama (qwen3:14b), JSON, Regex, Pathlib

---

## File Structure

```
scratch/
├── extract_drugs_diseases.py    # 단계 1: Ollama 호출로 약물/질병 추출
├── normalize_drugs_diseases.py  # 단계 2: 정규화 & 통합, 마스터 사전 생성
├── insert_forward_links.py      # 단계 3-1: 정방향 링크 [[term]] 삽입
├── insert_backlinks.py          # 단계 3-2: 역방향 링크 (본초備要) 추가
└── validate_links.py            # 단계 4: 검증 (diff, 링크 정확도)

output/
├── drugs.json                   # 마스터 사전: 약물 목록
├── diseases.json                # 마스터 사전: 질병 목록
└── extraction_results/          # 중간 결과: 각 파일당 JSON
    ├── 初1_drugs_diseases.json
    ├── 初2_drugs_diseases.json
    └── ... (25개 파일)
```

---

## Task 1: 추출 스크립트 작성 (Ollama)

**Files:**
- Create: `scratch/extract_drugs_diseases.py`

**Steps:**

- [ ] **Step 1: 추출 스크립트 작성**

Create `scratch/extract_drugs_diseases.py`:

```python
# -*- coding: utf-8 -*-
"""단계 1: 올라마로 약물/질병 추출
- 각 MD 파일에서 올라마 호출
- JSON 결과를 output/extraction_results/ 에 저장
"""
import sys, json, os, urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = r"C:\Users\Hoon_DT\Desktop\本初書籍\_md"
OUTPUT_DIR = r"C:\Users\Hoon_DT\gemini\stock\output\extraction_results"
os.makedirs(OUTPUT_DIR, exist_ok=True)

BOOKS = [
    "景岳全書",
    "本草備要",
    "本草問答",
    "本草求眞",
    "本草蒙筌",
    "醫學入門",
    "변증기문",
    "본초종신",
]

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
        "model": "qwen3:14b",
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "think": False,
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
    """모든 책의 MD 파일 처리"""
    all_files = []
    for book in BOOKS:
        book_dir = os.path.join(ROOT, book)
        if os.path.isdir(book_dir):
            for f in sorted(os.listdir(book_dir)):
                if f.lower().endswith(".md"):
                    all_files.append((book, f, os.path.join(book_dir, f)))
    
    print(f"전체 파일: {len(all_files)}개")
    for i, (book, fname, path) in enumerate(all_files, 1):
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            drugs, diseases = ask_ollama(text)
            
            result = {"drugs": drugs, "diseases": diseases}
            stem = os.path.splitext(fname)[0]
            out_path = os.path.join(OUTPUT_DIR, f"{book}_{stem}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            print(f"{i:>3}. OK  {book}/{stem:30s}  drugs={len(drugs):3d}  diseases={len(diseases):3d}")
        except Exception as e:
            print(f"{i:>3}. FAIL {book}/{fname:30s}  {e}")

if __name__ == "__main__":
    extract_all()
    print(f"OUT={OUTPUT_DIR}")
```

- [ ] **Step 2: 테스트 실행 (샘플 1개 파일)**

Run:
```bash
cd c:\Users\Hoon_DT\gemini\stock
python scratch/extract_drugs_diseases.py 2>&1 | head -20
```

Expected: 1-3개 파일 처리 완료, JSON 결과 저장

- [ ] **Step 3: 전체 파일 추출 (약 30-40분)**

Run:
```bash
cd c:\Users\Hoon_DT\gemini\stock
python scratch/extract_drugs_diseases.py 2>&1 | tail -10
```

Expected: 25개 파일 모두 완료, 각 파일당 drugs, diseases 개수 출력

- [ ] **Step 4: 추출 결과 확인**

Run:
```bash
ls output/extraction_results/ | wc -l
head output/extraction_results/*.json | head -30
```

Expected: 25개 JSON 파일, 각각 drugs/diseases 배열 포함

- [ ] **Step 5: Commit**

```bash
cd c:\Users\Hoon_DT\gemini\stock
git add scratch/extract_drugs_diseases.py
git commit -m "feat: 올라마로 약물/질병 자동 추출"
```

---

## Task 2: 정규화 & 통합 스크립트

**Files:**
- Create: `scratch/normalize_drugs_diseases.py`
- Output: `output/drugs.json`, `output/diseases.json`

**Steps:**

- [ ] **Step 1: 정규화 스크립트 작성**

Create `scratch/normalize_drugs_diseases.py`:

```python
# -*- coding: utf-8 -*-
"""단계 2: 추출 결과 정규화 & 통합
- output/extraction_results/ 의 25개 JSON 통합
- 중복 제거 (링크 대상 정규화)
- drugs.json, diseases.json 마스터 사전 생성
"""
import json, os
from pathlib import Path
from collections import defaultdict

EXTRACTION_DIR = r"C:\Users\Hoon_DT\gemini\stock\output\extraction_results"
OUTPUT_DIR = r"C:\Users\Hoon_DT\gemini\stock\output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def normalize_term(term):
    """용어 정규화 (링크 대상)
    
    예:
    - 黃耆, 黃芪 → 黃耆 (첫 등장)
    - 甘草 → 甘草 (이미 정규화)
    """
    # 공백 제거
    term = term.strip()
    # 여기서는 간단한 정규화만 (첫 등장 기준)
    return term

def load_all_extractions():
    """모든 추출 결과 로드"""
    all_drugs = []
    all_diseases = []
    
    for json_file in sorted(os.listdir(EXTRACTION_DIR)):
        if not json_file.endswith(".json"):
            continue
        path = os.path.join(EXTRACTION_DIR, json_file)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            all_drugs.extend(data.get("drugs", []))
            all_diseases.extend(data.get("diseases", []))
        except Exception as e:
            print(f"로드 실패: {json_file} - {e}")
    
    return all_drugs, all_diseases

def deduplicate(items):
    """중복 제거 (정규화 후)
    
    - 같은 의미 항목은 정규화해 하나로 통일
    - 결과: 정규화된 유일한 용어 목록
    """
    seen = {}
    unique = []
    
    for item in items:
        norm = normalize_term(item)
        if norm and norm not in seen:
            seen[norm] = item
            unique.append(norm)
    
    return sorted(unique)

def main():
    print("추출 결과 통합 중...")
    all_drugs, all_diseases = load_all_extractions()
    
    print(f"총 약물 언급: {len(all_drugs)}개")
    print(f"총 질병 언급: {len(all_diseases)}개")
    
    # 정규화 & 중복 제거
    unique_drugs = deduplicate(all_drugs)
    unique_diseases = deduplicate(all_diseases)
    
    print(f"유일한 약물: {len(unique_drugs)}개")
    print(f"유일한 질병: {len(unique_diseases)}개")
    
    # 마스터 사전 생성
    drugs_dict = {"items": unique_drugs, "count": len(unique_drugs)}
    diseases_dict = {"items": unique_diseases, "count": len(unique_diseases)}
    
    with open(os.path.join(OUTPUT_DIR, "drugs.json"), "w", encoding="utf-8") as f:
        json.dump(drugs_dict, f, ensure_ascii=False, indent=2)
    
    with open(os.path.join(OUTPUT_DIR, "diseases.json"), "w", encoding="utf-8") as f:
        json.dump(diseases_dict, f, ensure_ascii=False, indent=2)
    
    print(f"✓ drugs.json 생성: {len(unique_drugs)}개 항목")
    print(f"✓ diseases.json 생성: {len(unique_diseases)}개 항목")
    print(f"OUT={OUTPUT_DIR}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 스크립트 실행**

Run:
```bash
cd c:\Users\Hoon_DT\gemini\stock
python scratch/normalize_drugs_diseases.py
```

Expected: 
```
유일한 약물: 200+ 개
유일한 질병: 150+ 개
✓ drugs.json 생성
✓ diseases.json 생성
```

- [ ] **Step 3: 마스터 사전 확인**

Run:
```bash
python -c "
import json
with open(r'output/drugs.json', encoding='utf-8') as f:
    drugs = json.load(f)
print(f'Drugs: {drugs[\"count\"]}')
print(f'샘플: {drugs[\"items\"][:10]}')
"
```

Expected: 약물 목록이 정렬되어 출력됨

- [ ] **Step 4: Commit**

```bash
cd c:\Users\Hoon_DT\gemini\stock
git add scratch/normalize_drugs_diseases.py output/drugs.json output/diseases.json
git commit -m "feat: 약물/질병 정규화 & 마스터 사전 생성"
```

---

## Task 3: 정방향 링크 삽입 (모든 약물/질병)

**Files:**
- Create: `scratch/insert_forward_links.py`
- Modify: `C:\Users\Hoon_DT\Desktop\本初書籍\_md\**\*.md` (25개 파일)

**Steps:**

- [ ] **Step 1: 정방향 링크 삽입 스크립트 작성**

Create `scratch/insert_forward_links.py`:

```python
# -*- coding: utf-8 -*-
"""단계 3-1: 정방향 링크 삽입
- 마스터 사전(drugs.json, diseases.json)의 용어를 [[term]] 로 링크
- 원본 텍스트 절대 변경 금지 (마크다운 링크만 추가)
"""
import json, re, os
from pathlib import Path

MASTER_DIR = r"C:\Users\Hoon_DT\gemini\stock\output"
BOOKS_ROOT = r"C:\Users\Hoon_DT\Desktop\本初書籍\_md"

def load_master_dicts():
    """마스터 사전 로드"""
    with open(os.path.join(MASTER_DIR, "drugs.json"), encoding="utf-8") as f:
        drugs = json.load(f)["items"]
    with open(os.path.join(MASTER_DIR, "diseases.json"), encoding="utf-8") as f:
        diseases = json.load(f)["items"]
    return drugs, diseases

def escape_for_regex(term):
    """정규식용 이스케이프"""
    return re.escape(term)

def insert_links(text, drugs, diseases):
    """텍스트에 링크 삽입
    
    - 약물/질병을 찾아 [[term]] 로 변환
    - 이미 링크인 부분은 건너뜀
    - 원본 텍스트는 보존 (링크만 추가)
    """
    # 이미 링크인 부분은 보호
    already_linked = set(re.findall(r'\[\[([^\]]+)\]\]', text))
    
    all_terms = diseases + drugs  # 질병 먼저 (더 우선순위 높게)
    
    for term in all_terms:
        if term in already_linked:
            continue
        
        # 단어 경계 정규식 (한글/한문 문자 포함)
        pattern = r'(?<![[\w一-鿿])' + escape_for_regex(term) + r'(?![]\w一-鿿])'
        replacement = f'[[{term}]]'
        
        text = re.sub(pattern, replacement, text)
        already_linked.add(term)
    
    return text

def process_all_files():
    """모든 MD 파일 처리"""
    drugs, diseases = load_master_dicts()
    print(f"약물: {len(drugs)}개, 질병: {len(diseases)}개")
    
    books = [d for d in os.listdir(BOOKS_ROOT) 
             if os.path.isdir(os.path.join(BOOKS_ROOT, d))]
    
    total, processed = 0, 0
    for book in sorted(books):
        book_dir = os.path.join(BOOKS_ROOT, book)
        md_files = [f for f in os.listdir(book_dir) if f.endswith(".md")]
        
        for md_file in sorted(md_files):
            path = os.path.join(book_dir, md_file)
            total += 1
            
            try:
                with open(path, encoding="utf-8") as f:
                    original = f.read()
                
                # 링크 삽입
                linked = insert_links(original, drugs, diseases)
                
                # 변경 사항 확인
                if original != linked:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(linked)
                    
                    # 링크 개수 계산
                    added_links = len(re.findall(r'\[\[', linked)) - len(re.findall(r'\[\[', original))
                    print(f"✓ {book:15s}/{md_file:30s} +{added_links:3d} links")
                    processed += 1
                else:
                    print(f"- {book:15s}/{md_file:30s} (no changes)")
            
            except Exception as e:
                print(f"✗ {book:15s}/{md_file:30s} ERROR: {e}")
    
    print(f"\n처리 완료: {processed}/{total} 파일 수정됨")

if __name__ == "__main__":
    process_all_files()
```

- [ ] **Step 2: 샘플 파일에서 테스트 (백업 후)**

Run:
```bash
cd c:\Users\Hoon_DT\gemini\stock
cp "C:\Users\Hoon_DT\Desktop\本初書籍\_md\本草備要\초1.md" output/초1_backup.md
python scratch/insert_forward_links.py 2>&1 | head -5
```

Expected: 초1.md에 링크 추가, 변경 사항 출력

- [ ] **Step 3: 변경 내용 diff 확인**

Run:
```bash
diff output/초1_backup.md "C:\Users\Hoon_DT\Desktop\本初書籍\_md\本草備要\초1.md" | head -20
```

Expected: `[[약물]]`, `[[질병]]` 형태의 링크 추가만 보임 (본문 텍스트 변경 없음)

- [ ] **Step 4: 전체 파일 링크 삽입 (약 10-15분)**

Run:
```bash
cd c:\Users\Hoon_DT\gemini\stock
python scratch/insert_forward_links.py 2>&1 | tail -15
```

Expected: 25개 파일 모두 처리, 총 링크 개수 출력

- [ ] **Step 5: Commit**

```bash
cd c:\Users\Hoon_DT\gemini\stock
git add "C:\Users\Hoon_DT\Desktop\本初書籍\_md"
git commit -m "feat: 정방향 링크 삽입 ([[약물]], [[질병]])"
```

---

## Task 4: 역방향 링크 삽입 (本草備要)

**Files:**
- Create: `scratch/insert_backlinks.py`
- Modify: `C:\Users\Hoon_DT\Desktop\本初書籍\_md\本草備要\*.md` (각 약물 항목)

**Steps:**

- [ ] **Step 1: 역방향 링크 맵 생성 스크립트**

Create `scratch/insert_backlinks.py`:

```python
# -*- coding: utf-8 -*-
"""단계 3-2: 역방향 링크 삽입
- 각 약물이 어디서 쓰이는지 추적
- 本草備要의 약물 항목 끝에 "## 관련 질병" 섹션 추가
"""
import json, re, os
from pathlib import Path
from collections import defaultdict

BOOKS_ROOT = r"C:\Users\Hoon_DT\Desktop\本初書籍\_md"
MASTER_DIR = r"C:\Users\Hoon_DT\gemini\stock\output"

def load_master_dicts():
    """마스터 사전 로드"""
    with open(os.path.join(MASTER_DIR, "drugs.json"), encoding="utf-8") as f:
        drugs = json.load(f)["items"]
    with open(os.path.join(MASTER_DIR, "diseases.json"), encoding="utf-8") as f:
        diseases = json.load(f)["items"]
    return drugs, diseases

def extract_diseases_from_text(text, diseases):
    """텍스트에서 질병 추출"""
    found = set()
    for disease in diseases:
        if disease in text:
            found.add(disease)
    return found

def build_drug_disease_map():
    """약물 → 질병 매핑 생성
    
    모든 파일 스캔: 같은 섹션 내에서 약물과 질병이 함께 나오는 경우 기록
    """
    drugs, diseases = load_master_dicts()
    drug_disease_map = defaultdict(set)
    
    for book in sorted(os.listdir(BOOKS_ROOT)):
        book_dir = os.path.join(BOOKS_ROOT, book)
        if not os.path.isdir(book_dir):
            continue
        
        for md_file in sorted(os.listdir(book_dir)):
            if not md_file.endswith(".md"):
                continue
            
            path = os.path.join(book_dir, md_file)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            
            # ## 섹션별 분석
            sections = re.split(r'^## ', text, flags=re.MULTILINE)
            
            for section in sections[1:]:  # 첫 분할은 제목 이전
                lines = section.split('\n', 1)
                if len(lines) < 2:
                    continue
                
                section_title = lines[0]
                section_body = lines[1]
                
                # 섹션 제목 자체가 질병인가?
                if section_title in diseases:
                    # 본문에서 약물 찾기
                    for drug in drugs:
                        if drug in section_body:
                            drug_disease_map[drug].add(section_title)
    
    return dict({k: sorted(v) for k, v in drug_disease_map.items()})

def add_backlinks_to_bonchobiyo():
    """本草備要에 역링크 섹션 추가"""
    bonchobiyo_dir = os.path.join(BOOKS_ROOT, "本草備要")
    drug_disease_map = build_drug_disease_map()
    
    print(f"약물-질병 맵: {len(drug_disease_map)}개 약물")
    
    for md_file in sorted(os.listdir(bonchobiyo_dir)):
        if not md_file.endswith(".md"):
            continue
        
        path = os.path.join(bonchobiyo_dir, md_file)
        with open(path, encoding="utf-8") as f:
            original = f.read()
        
        # 파일에서 약물 항목 찾기 (## 약물명 형식)
        drug_items = re.findall(r'^## ([^\n]+)$', original, flags=re.MULTILINE)
        
        modified = original
        
        for drug_name in drug_items:
            if drug_name not in drug_disease_map:
                continue
            
            diseases = drug_disease_map[drug_name]
            if not diseases:
                continue
            
            # 약물 항목 끝을 찾아 역링크 섹션 추가
            pattern = rf'(## {re.escape(drug_name)}\n.*?)(?=\n## |\Z)'
            
            def add_backlink(match):
                section = match.group(1)
                # 이미 "## 관련 질병"이 있으면 스킵
                if "## 관련 질병" in section:
                    return section
                
                backlink_text = "\n## 관련 질병\n"
                for disease in diseases:
                    backlink_text += f"- [[{disease}]]\n"
                
                return section + backlink_text
            
            modified = re.sub(pattern, add_backlink, modified, flags=re.DOTALL)
        
        if original != modified:
            with open(path, "w", encoding="utf-8") as f:
                f.write(modified)
            
            added = modified.count("## 관련 질병") - original.count("## 관련 질병")
            print(f"✓ {md_file:30s} +{added} 역링크 섹션")
        else:
            print(f"- {md_file:30s} (no changes)")

if __name__ == "__main__":
    add_backlinks_to_bonchobiyo()
```

- [ ] **Step 2: 역링크 생성 스크립트 실행**

Run:
```bash
cd c:\Users\Hoon_DT\gemini\stock
python scratch/insert_backlinks.py 2>&1 | tail -20
```

Expected: 本草備要 파일들에 "## 관련 질병" 섹션 추가

- [ ] **Step 3: 본초備要 샘플 파일 확인**

Run:
```bash
tail -50 "C:\Users\Hoon_DT\Desktop\本初書籍\_md\本草備要\초1.md"
```

Expected: 마지막에 "## 관련 질병" 섹션이 보임

- [ ] **Step 4: Commit**

```bash
cd c:\Users\Hoon_DT\gemini\stock
git add "C:\Users\Hoon_DT\Desktop\本初書籍\_md\本草備要"
git commit -m "feat: 역방향 링크 삽입 (本草備要 약물 항목)"
```

---

## Task 5: 전체 파이프라인 통합 테스트

**Files:**
- Verify: 모든 25개 MD 파일

**Steps:**

- [ ] **Step 1: 파이프라인 완료 확인**

Run:
```bash
cd c:\Users\Hoon_DT\gemini\stock
echo "=== 추출 결과 ==="
ls output/extraction_results/ | wc -l
echo ""
echo "=== 마스터 사전 ==="
python -c "
import json
with open('output/drugs.json') as f:
    print(f'약물: {json.load(f)[\"count\"]}')
with open('output/diseases.json') as f:
    print(f'질병: {json.load(f)[\"count\"]}')
"
```

Expected:
```
=== 추출 결과 ===
25

=== 마스터 사전 ===
약물: 200+
질병: 150+
```

- [ ] **Step 2: 링크 삽입 결과 샘플 확인**

Run:
```bash
grep -c "\\[\\[" "C:\Users\Hoon_DT\Desktop\本初書籍\_md\本草備要\초1.md"
grep "\\[\\[" "C:\Users\Hoon_DT\Desktop\本初書籍\_md\本草備要\초1.md" | head -5
```

Expected: 10+ 개의 `[[term]]` 링크

- [ ] **Step 3: 역링크 섹션 확인**

Run:
```bash
grep -c "## 관련 질病" "C:\Users\Hoon_DT\Desktop\本初書籍\_md\本草備要\초1.md"
```

Expected: 1+ (약물 항목당 1개 역링크 섹션)

- [ ] **Step 4: Commit (통합 확인)**

```bash
cd c:\Users\Hoon_DT\gemini\stock
git add scratch/insert_forward_links.py scratch/insert_backlinks.py
git commit -m "feat: 정방향/역방향 링크 파이프라인 완성"
```

---

## Task 6: 검증 (본문 보존 확인)

**Files:**
- Create: `scratch/validate_links.py`

**Steps:**

- [ ] **Step 1: 검증 스크립트 작성**

Create `scratch/validate_links.py`:

```python
# -*- coding: utf-8 -*-
"""단계 4: 검증
- 원본 vs 링크 추가본 diff 확인 (마크다운만 변경되었는가?)
- 링크 정확도 샘플 확인
"""
import re, os
from pathlib import Path

BOOKS_ROOT = r"C:\Users\Hoon_DT\Desktop\本初書籍\_md"

def validate_no_text_changes():
    """원본 텍스트 변경이 없는지 확인
    
    현재는 MD 파일이 이미 변경되었으므로,
    링크를 제거했을 때 원본이 복구되는지 확인
    """
    sample_files = [
        (r"C:\Users\Hoon_DT\Desktop\本初書籍\_md\本草備要\초1.md", "output/초1_backup.md"),
    ]
    
    for modified_path, backup_path in sample_files:
        if not os.path.exists(backup_path):
            print(f"백업 파일 없음: {backup_path}")
            continue
        
        with open(modified_path, encoding="utf-8") as f:
            modified = f.read()
        
        with open(backup_path, encoding="utf-8") as f:
            backup = f.read()
        
        # 링크 제거
        no_links = re.sub(r'\[\[([^\]]+)\]\]', r'\1', modified)
        
        if no_links == backup:
            print(f"✓ {os.path.basename(modified_path)}: 원본 텍스트 완벽 보존")
        else:
            print(f"✗ {os.path.basename(modified_path)}: 텍스트 변경 감지!")
            # diff 출력
            import difflib
            diff = difflib.unified_diff(
                backup.split('\n'), no_links.split('\n'),
                lineterm='', n=1
            )
            for line in list(diff)[:20]:
                print(f"  {line}")

def count_links():
    """전체 링크 개수 통계"""
    total_links = 0
    
    for book in sorted(os.listdir(BOOKS_ROOT)):
        book_dir = os.path.join(BOOKS_ROOT, book)
        if not os.path.isdir(book_dir):
            continue
        
        book_links = 0
        for md_file in os.listdir(book_dir):
            if not md_file.endswith(".md"):
                continue
            
            path = os.path.join(book_dir, md_file)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            
            links = len(re.findall(r'\[\[', text))
            book_links += links
        
        print(f"{book:15s}: {book_links:5d} 개 링크")
        total_links += book_links
    
    print(f"\n전체: {total_links} 개 링크")

def validate_link_format():
    """링크 형식 검증 (올바른 [[term]] 형식)"""
    sample_path = r"C:\Users\Hoon_DT\Desktop\本初書籍\_md\本草備要\초1.md"
    
    with open(sample_path, encoding="utf-8") as f:
        text = f.read()
    
    # 올바른 링크
    valid_links = re.findall(r'\[\[([^\]]+)\]\]', text)
    print(f"유효한 링크: {len(valid_links)}개")
    print(f"샘플: {valid_links[:10]}")
    
    # 손상된 링크 (예: [[ 뒤에 바로 ] 등)
    broken = re.findall(r'\[\[\s*\]\]', text)
    if broken:
        print(f"✗ 손상된 링크: {len(broken)}개")
    else:
        print(f"✓ 손상된 링크 없음")

if __name__ == "__main__":
    print("=== 본문 보존 검증 ===")
    validate_no_text_changes()
    
    print("\n=== 링크 개수 통계 ===")
    count_links()
    
    print("\n=== 링크 형식 검증 ===")
    validate_link_format()
```

- [ ] **Step 2: 검증 스크립트 실행**

Run:
```bash
cd c:\Users\Hoon_DT\gemini\stock
python scratch/validate_links.py
```

Expected:
```
=== 본문 보존 검증 ===
✓ 초1.md: 원본 텍스트 완벽 보존

=== 링크 개수 통계 ===
本草備要: XXXX 개 링크
...
전체: XXXXX 개 링크

=== 링크 형식 검증 ===
유효한 링크: XXX개
✓ 손상된 링크 없음
```

- [ ] **Step 3: 최종 결과 정리**

Run:
```bash
cd c:\Users\Hoon_DT\gemini\stock
echo "=== 최종 결과 ==="
echo "생성 파일:"
ls -lh output/*.json
echo ""
echo "MD 파일 확인:"
find "C:\Users\Hoon_DT\Desktop\本初書籍\_md" -name "*.md" | wc -l
```

Expected: 마스터 사전 JSON 파일 존재, 25개 MD 파일 모두 링크 추가됨

- [ ] **Step 4: 최종 Commit**

```bash
cd c:\Users\Hoon_DT\gemini\stock
git add scratch/validate_links.py
git commit -m "feat: 위키링크 검증 및 통계"
```

---

## Success Criteria

✅ **구현 완료 시 확인사항:**

1. 25개 파일 모두 약물/질병 추출 완료 (extraction_results 25개 JSON)
2. 마스터 사전 생성 (drugs.json 100+, diseases.json 100+)
3. 정방향 링크 삽입: 모든 약물/질병이 `[[term]]` 형식
4. 역방향 링크 삽입: 本草備要 약물 항목에 "## 관련 질병" 섹션
5. **본문 완벽 보존**: diff로 확인 시 링크만 추가, 텍스트 무변경
6. Obsidian에서 그래프 뷰 열기 → 약물-질병 네트워크 시각화 가능

---

**Plan saved to `docs/superpowers/plans/2026-05-31-obsidian-linking.md`.**

**Two execution options:**

**1. Subagent-Driven (권장)** — 각 작업마다 fresh subagent 실행, 작업 후 검토 및 빠른 피드백

**2. Inline Execution** — 이 세션에서 `superpowers:executing-plans` 스킬로 순차 실행

어느 방법으로 진행하시겠어요?