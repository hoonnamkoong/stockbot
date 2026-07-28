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
    """'2026-07-27' 또는 '20260727' → 'data/post_titles_2026-07.csv'

    호출부가 넘기는 ctx.today_str이 '%Y%m%d'라 [:7] 슬라이스는 '2026072'가 됐다.
    월이 아니라 10일 단위로 파일이 쪼개지고 있었다(2026-07-28 발견,
    db-data에 post_titles_2026072.csv로 남아 있다). 구분자 유무와 무관하게
    앞 6자리 숫자를 연·월로 읽는다.
    """
    digits = ''.join(ch for ch in str(date_str) if ch.isdigit())
    if len(digits) < 6:
        return os.path.join(DATA_DIR, "post_titles_unknown.csv")
    return os.path.join(DATA_DIR, f"post_titles_{digits[:4]}-{digits[4:6]}.csv")


def _legacy_paths(path: str) -> list:
    """같은 달의 옛 이름 파일들. 파일명 버그로 흩어진 것을 중복 판정에 포함한다.

    이게 없으면 이미 아카이브된 글이 새 파일에 다시 들어가 사전 검증의
    빈도 통계가 부풀려진다 — 이 모듈이 nid로 거르는 이유 그대로다.
    """
    import glob
    base = os.path.basename(path)                      # post_titles_2026-07.csv
    if not base.startswith('post_titles_') or '-' not in base:
        return []
    ym = base[len('post_titles_'):-len('.csv')]        # 2026-07
    pattern = os.path.join(DATA_DIR, f"post_titles_{ym.replace('-', '')}*.csv")
    return [p for p in glob.glob(pattern) if p != path]


def _read_nids(path: str) -> set:
    if not os.path.exists(path):
        return set()
    try:
        with open(path, newline='', encoding='utf-8') as f:
            return {r['nid'] for r in csv.DictReader(f) if r.get('nid')}
    except Exception:
        return set()


def _existing_nids(path: str) -> set:
    nids = _read_nids(path)
    for legacy in _legacy_paths(path):
        nids |= _read_nids(legacy)
    return nids


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
