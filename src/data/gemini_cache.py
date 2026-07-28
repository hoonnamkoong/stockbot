"""Gemini 배치 분석 결과 캐시 — 당일, 게시글 nid 집합 기준.

같은 글을 하루에 몇 번씩 다시 분석하고 있었다. 스크래퍼는 하루 39번 돌고
채택 임계값이 시간대별 누적(20/40/80/120/130)이라 같은 종목이 반복 선정되는데,
그 종목의 상위 5개 게시글은 대개 그대로다. 2026-07-28 계측 기준 하루 3,100글이
Gemini로 갔다.

**무효화가 필요 없다 — 키가 곧 내용이기 때문이다.** 프롬프트는 (종목, 그 종목의
상위 글 제목들)로만 결정되므로 nid 집합이 같으면 응답도 같다. 글이 바뀌면 nid
집합이 바뀌어 자동으로 미스가 된다. 날짜가 넘어가면 통째로 버린다(글·추천수 리셋).

JSON 파일인 이유: 런마다 프로세스가 새로 뜨므로 메모리 캐시는 의미가 없고,
scraper.yml 배포 스텝이 data/*.json을 db-data로 실어 나르기 때문이다.
"""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

DEFAULT_PATH = os.path.join('data', 'gemini_cache.json')


def today_kst() -> str:
    return (datetime.now(timezone(timedelta(hours=9)))).strftime('%Y%m%d')


def make_key(code: str, posts: list) -> str:
    """(종목코드, 게시글 nid 집합) → 캐시 키.

    순서에 흔들리지 않도록 정렬해서 해시한다. 같은 글 5개가 다른 순서로 와도
    프롬프트 내용은 같으므로 같은 키여야 한다.
    """
    nids = sorted(str(p.get('nid', '')) for p in (posts or []))
    digest = hashlib.sha1('|'.join(nids).encode('utf-8')).hexdigest()[:16]
    return f"{code}:{digest}"


def load(path: str = None, today: str = None) -> dict:
    """당일 캐시 엔트리. 날짜가 다르거나 읽기 실패면 빈 dict."""
    path = path or DEFAULT_PATH
    today = today or today_kst()
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        if data.get('date') != today:
            return {}
        entries = data.get('entries')
        return entries if isinstance(entries, dict) else {}
    except Exception:
        return {}


def save(entries: dict, path: str = None, today: str = None) -> None:
    """캐시 저장. 실패로 스크래퍼 런이 죽으면 안 되므로 예외를 삼킨다."""
    path = path or DEFAULT_PATH
    today = today or today_kst()
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'date': today, 'entries': entries}, f, ensure_ascii=False)
    except Exception:
        pass
