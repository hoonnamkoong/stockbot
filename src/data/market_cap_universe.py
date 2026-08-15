"""KOSPI 시가총액 상위 유니버스 — **중립** 종목 풀.

왜 필요한가: 기존 유니버스는 전부 방향이 있다.
  - `get_fluctuation_rank(sort='0')` = 오늘 오른 종목
  - `get_fluctuation_rank(sort='1')` = 오늘 내린 종목
  - `get_finance_ratio_rank` = ROE 수익성 상위
  - 버즈 후보 = 게시글이 몰린 종목(= 사실상 급등주)

방향이 있는 풀은 방향이 반대인 전략과 구조적으로 안 맞는다. 2026-08-14 실측:

    [레인지] 진입 없음 — 채널폭 통과 19개 중
    저점에 가장 가까운 000660 저점 대비 +24.4% (기준 +3% 이내)

심5(레인지 스윙)는 "박스권 저점 매수"인데 버즈 후보를 받고 있었다. 인기를
끌려면 올라야 하고, 오르면 채널 위쪽이다 — 저점 근처 후보가 **한 종목도**
들어올 수 없는 조합이었다. 심10도 SIDEWAYS 국면에서 같은 판단 함수를 쓴다.

시총 상위는 "오늘 어느 방향이었는가"와 무관하게 뽑히므로 박스권 저점도,
채널 상단 돌파도 똑같이 들어올 수 있다.

⚠ `_fetch_top100_breadth`(trade_engine)가 같은 페이지를 따로 파싱한다. 그쪽은
등락률만 쓰고 이쪽은 종목 목록을 쓴다 — 지금은 합치지 않았다. 합칠 때는 국면
판정 경로를 건드리게 되므로 별도로 검증해야 한다.
"""
import re

import requests
from bs4 import BeautifulSoup

_URL = 'https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page={page}'
_HDRS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Referer': 'https://finance.naver.com/',
}
_PER_PAGE = 50


def parse_rows(html: bytes) -> list[dict]:
    """시총 페이지 1장 → [{code, name, price}]. 파싱 실패 행은 버린다."""
    soup = BeautifulSoup(html.decode('euc-kr', 'replace'), 'html.parser')
    table = soup.select_one('table.type_2')
    if not table:
        return []
    out = []
    for row in table.select('tr'):
        cols = row.select('td')
        if len(cols) < 5:
            continue
        tag = cols[1].select_one('a')
        if not tag or 'code=' not in (tag.get('href') or ''):
            continue
        code = tag['href'].split('code=')[-1]
        if not re.fullmatch(r'\d{6}', code):
            continue
        try:
            price = int(cols[2].get_text(strip=True).replace(',', ''))
        except ValueError:
            continue
        if price <= 0:
            continue
        out.append({'code': code, 'name': tag.get_text(strip=True), 'price': price})
    return out


def fetch_top100(limit: int = 100, get=None) -> list[dict] | None:
    """시총 상위 종목. **실패하면 None** — 빈 리스트와 구분한다.

    호출부(심의 get_universe)가 둘을 정반대로 처리한다: None이면 파이프라인
    후보를 그대로 쓰고, 빈 리스트면 '후보가 없다'가 된다. 조회 실패를 빈
    리스트로 돌려주면 그날 그 심이 조용히 아무것도 안 한다.
    """
    fetch = get or (lambda url: requests.get(url, headers=_HDRS, timeout=10))
    rows: list[dict] = []
    seen: set = set()
    pages = (limit + _PER_PAGE - 1) // _PER_PAGE
    for page in range(1, pages + 1):
        try:
            res = fetch(_URL.format(page=page))
            parsed = parse_rows(res.content)
        except Exception:
            return None if not rows else rows[:limit]
        if not parsed:
            break
        for r in parsed:
            if r['code'] in seen:
                continue
            seen.add(r['code'])
            rows.append(r)
            if len(rows) >= limit:
                return rows
    return rows or None
