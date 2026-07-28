"""
Gemini 호출 계측 로그.

감정분석 경제성(표본 확대 여력, 본문 수집 실효성)을 추정이 아니라 실측으로
판단하기 위한 기록이다. 여기서 나온 숫자로 배치 크기·표본 수·본문 포함 여부를
정한다.

CSV인 이유: scraper.yml 배포 스텝이 data/*.json, data/*.csv, data/*.xlsx만
db-data로 실어 나른다. .jsonl은 배포 루프에 안 걸려 매 런 증발한다.
"""

import csv
import os
from datetime import datetime

DEFAULT_PATH = os.path.join('data', 'gemini_usage.csv')

COLUMNS = [
    'timestamp',
    'event',           # batch_call | run_summary | cache_summary
    'model',
    'prompt_tokens',
    'output_tokens',
    'total_tokens',
    'req_stocks',      # 배치에 넣은 종목 수
    'resp_stocks',     # 응답에서 파싱된 종목 수 (누락 감지)
    'req_posts',       # 배치에 넣은 게시글 수
    'req_chars',       # 프롬프트 길이 (토큰 미보고 시 대체 지표)
    'body_ok',         # 본문 수집 성공 건수
    'body_fail',       # 본문 수집 실패 건수
    'cache_hit',       # nid 집합 캐시 적중 종목 수 (재분석 회피)
    'cache_miss',      # 캐시 미스로 실제 호출한 종목 수
]


def _ensure_header(path: str) -> None:
    """옛 헤더로 만들어진 파일에 새 컬럼 행을 덧붙이면 열이 어긋난다.

    헤더가 다르면 기존 행을 살린 채 새 헤더로 다시 쓴다. 이 로그는 비용·표본
    결정의 근거라, 조용히 밀린 열 하나가 판단을 통째로 뒤집을 수 있다.
    """
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return
    try:
        with open(path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames == COLUMNS:
                return
            rows = list(reader)
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows({c: r.get(c, '') for c in COLUMNS} for r in rows)
    except Exception:
        pass


def append(record: dict, path: str | None = None) -> None:
    """계측 1행을 추가한다.

    계측 실패로 스크래퍼 런이 죽으면 안 되므로 모든 예외를 삼킨다.

    path 기본값은 호출 시점에 읽는다. 기본 인자로 박으면 정의 시점에 값이
    고정되어 DEFAULT_PATH를 바꿔도 반영되지 않는다.
    """
    try:
        path = path or DEFAULT_PATH
        _ensure_header(path)
        row = {c: record.get(c, '') for c in COLUMNS}
        if not row['timestamp']:
            row['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        is_new = not os.path.exists(path) or os.path.getsize(path) == 0
        with open(path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            if is_new:
                writer.writeheader()
            writer.writerow(row)
    except Exception:
        pass
