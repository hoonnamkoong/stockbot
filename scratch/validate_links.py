# -*- coding: utf-8 -*-
"""단계 4: 검증
- 원본 vs 링크 추가본 diff 확인 (마크다운만 변경되었는가?)
- 링크 정확도 샘플 확인
"""
import re, os
from pathlib import Path

BOOKS_ROOT = r"C:\Users\Hoon_DT\Desktop\본초서적\_md"

def validate_no_text_changes():
    """원본 텍스트 변경이 없는지 확인

    현재는 MD 파일이 이미 변경되었으므로,
    링크를 제거했을 때 원본이 복구되는지 확인
    """
    sample_files = [
        (r"C:\Users\Hoon_DT\Desktop\본초서적\_md\本草備要\초1.md", "output/초1_backup.md"),
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
    sample_path = r"C:\Users\Hoon_DT\Desktop\본초서적\_md\本草備要\초1.md"

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
