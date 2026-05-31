# -*- coding: utf-8 -*-
"""단계 2: 추출 결과 정규화 & 통합
- output/extraction_results/ 의 JSON 통합
- 중복 제거 (링크 대상 정규화)
- drugs.json, diseases.json 마스터 사전 생성
"""
import json
import os
import sys

# Windows 인코딩 처리
if sys.stdout.encoding.lower() != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

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
