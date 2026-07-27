"""게시글 원문 제목 아카이브.

원문은 지금 어디에도 남지 않는다. 월별 엑셀과 시간별 스냅샷은 Gemini 요약·
키워드만 담고, latest_stocks.json은 매 런 덮어쓰기이며, db-data 히스토리는
2026-07-23 재작성으로 그 이전이 없다. 열망 사전을 재검증하고 백테스트하려면
제목이 축적되어야 한다.

CSV인 이유: scraper.yml 배포 스텝이 data/*.json|csv|xlsx만 db-data로 실어
나른다. 월별로 쪼개는 이유는 한 파일이 무한정 커지는 것을 막기 위해서다.
"""

import csv
import os

COLUMNS = ['date', 'code', 'name', 'nid', 'title', 'likes']

DATA_DIR = 'data'


def month_path(date_str: str) -> str:
    """'2026-07-27' → 'data/post_titles_2026-07.csv'"""
    return os.path.join(DATA_DIR, f"post_titles_{date_str[:7]}.csv")


def _existing_nids(path: str) -> set:
    if not os.path.exists(path):
        return set()
    try:
        with open(path, newline='', encoding='utf-8') as f:
            return {r['nid'] for r in csv.DictReader(f) if r.get('nid')}
    except Exception:
        return set()


def append(records: list, path: str = None) -> int:
    """중복 nid를 제외하고 추가한다. 추가된 행 수를 반환.

    스크래퍼는 하루 여러 번 돌며 같은 글을 다시 본다. nid로 걸러내지 않으면
    사전 검증의 빈도 통계가 실행 횟수에 비례해 부풀려진다.

    아카이브 실패로 스크래퍼 런이 죽으면 안 되므로 모든 예외를 삼킨다.
    """
    if not records:
        return 0
    try:
        path = path or month_path(records[0].get('date', ''))
        seen = _existing_nids(path)

        fresh = []
        for r in records:
            nid = str(r.get('nid', '')).strip()
            if not nid or nid in seen:
                continue
            seen.add(nid)
            fresh.append({c: r.get(c, '') for c in COLUMNS})

        if not fresh:
            return 0

        is_new = not os.path.exists(path) or os.path.getsize(path) == 0
        with open(path, 'a', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            if is_new:
                w.writeheader()
            w.writerows(fresh)
        return len(fresh)
    except Exception:
        return 0
