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
    'event',           # batch_call | run_summary
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
]


def append(record: dict, path: str | None = None) -> None:
    """계측 1행을 추가한다.

    계측 실패로 스크래퍼 런이 죽으면 안 되므로 모든 예외를 삼킨다.

    path 기본값은 호출 시점에 읽는다. 기본 인자로 박으면 정의 시점에 값이
    고정되어 DEFAULT_PATH를 바꿔도 반영되지 않는다.
    """
    try:
        path = path or DEFAULT_PATH
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
