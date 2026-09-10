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

⚠ `_fetch_top100_breadth`(trade_engine)가 같은 시총 목록을 따로 부른다. 그쪽은
등락률만 쓰고 이쪽은 종목 목록을 쓴다 — 지금은 합치지 않았다. 합칠 때는 국면
판정 경로를 건드리게 되므로 별도로 검증해야 한다.

[2026-09-11] 원천이 finance.naver.com HTML 표에서 네이버 JSON API로 바뀌었다
(src/data/naver_api.py). 09-10에 옛 페이지가 302로 옮겨가 표를 못 찾았고, 그날부터
이 함수는 None을 냈다. 고정 열 인덱스로 읽던 위험은 필드명으로 사라졌다.
"""
from src.data import naver_api


def to_universe_rows(rows: list[dict]) -> list[dict]:
    """시총 목록 행 → [{code, name, price, amount, change_rate}]. 가격이 없는 행은 버린다.

    ⚠ `amount`(거래대금)와 `change_rate`는 2026-08-17에 추가했다. 그전까지
    `{code, name, price}`만 돌려줬는데, **심5는 `amount < 10억`이면 `continue`**라
    키가 없으면 `get('amount', 0)` → 0 → **후보 99종목이 전부 첫 게이트에서 탈락**했다.
    실제로 심5는 배포 이래 거래 0건, 현금 200만원 그대로였다.

    거래대금은 현재가 × 거래량으로 만든다 — `get_fluctuation_rank`가 쓰는 방식과 같다.
    """
    out = []
    for r in rows:
        price = r.get('price')
        if not price or price <= 0:
            continue
        row_out = {'code': r['code'], 'name': r['name'], 'price': int(price)}
        # 거래량을 못 읽으면 키를 넣지 않는다 — 0을 넣으면
        # "유동성 0"으로 오판되어 유동성 게이트를 쓰는 심이 전량 탈락한다.
        if r.get('volume'):
            row_out['amount'] = int(price) * r['volume']
        if r.get('change_rate') is not None:
            row_out['change_rate'] = f"{r['change_rate']:+.2f}%"
        out.append(row_out)
    return out


def fetch_top100(limit: int = 100, fetch=None) -> list[dict] | None:
    """시총 상위 종목. **실패하면 None** — 빈 리스트와 구분한다.

    호출부(심의 get_universe)가 둘을 정반대로 처리한다: None이면 파이프라인
    후보를 그대로 쓰고, 빈 리스트면 '후보가 없다'가 된다. 조회 실패를 빈
    리스트로 돌려주면 그날 그 심이 조용히 아무것도 안 한다.
    """
    fetch = fetch or naver_api.stock_list
    try:
        rows = fetch('marketValue', 'KOSPI', limit)
    except Exception:
        return None
    if not rows:
        return None
    return to_universe_rows(rows)[:limit] or None
