"""미국 주식 유니버스 소스 — 네이버 시총랭킹의 미국판.

api.nasdaq.com 스크리너는 키가 필요 없고 나스닥·NYSE·AMEX 상장 전체를
시가총액 포함해 JSON으로 준다. ETF·우선주·워런트는 심볼에 `.`/`^`/`/`가
섞이거나 marketCap이 비는 경우가 많아 그걸로 거른다 — 완벽하지는 않지만
추가 조회 없이 되는 선에서의 근사다.
"""
import json
import os

import requests

NASDAQ_SCREENER_URL = 'https://api.nasdaq.com/api/screener/stocks'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
}


def _to_float(v):
    try:
        v = str(v).replace(',', '').strip()
        return float(v) if v else None
    except (TypeError, ValueError):
        return None


def fetch_us_universe(limit: int = 1000) -> list[dict]:
    """나스닥 스크리너에서 미국 상장 종목을 가져온다. 실패하면 예외를 올린다."""
    params = {
        'tableonly': 'true',
        'limit': str(limit),
        'offset': '0',
        'exchange': 'nasdaq,nyse,amex',
        'download': 'true',
        # 정렬을 명시하지 않으면 limit=1000이 "시총 상위 1000"이 아니라
        # API 기본 순서(심볼 알파벳 등)의 앞 1000이 될 수 있다.
        'sortColumn': 'marketcap',
        'sortOrder': 'desc',
    }
    r = requests.get(NASDAQ_SCREENER_URL, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    body = r.json()
    rows = ((body or {}).get('data') or {}).get('rows')
    if not rows:
        raise RuntimeError(
            '나스닥 스크리너가 빈 응답을 반환했다(data.rows가 null/비어있음) — '
            'HTTP 200이지만 소프트 차단 등으로 실패했을 가능성이 높다.'
        )
    out = []
    for row in rows:
        out.append({
            'symbol': row.get('symbol', ''),
            'name': row.get('name', ''),
            'market_cap': _to_float(row.get('marketCap')),
            'country': row.get('country', ''),
            'sector': row.get('sector') or None,
        })
    return out


def filter_universe(rows: list[dict]) -> list[dict]:
    """ETF/우선주/워런트 및 시총 결손 종목을 제외한다."""
    out = []
    for r in rows:
        symbol = r.get('symbol', '')
        if not symbol or any(c in symbol for c in ('.', '^', '/')):
            continue
        mc = r.get('market_cap')
        if not mc or mc <= 0:
            continue
        out.append(r)
    return out


def save_universe(rows: list[dict], path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def load_universe(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding='utf-8-sig') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []
