# -*- coding: utf-8 -*-
"""네이버 증권 JSON API — 이 레포가 네이버 시세·수급·종토방을 얻는 창구.

## 왜 생겼나 (2026-09-10 실측)

그날 09~21시 사이 네이버가 finance.naver.com을 stock.naver.com("Npay 증권")으로
옮겼다. 우리가 긁던 옛 주소가 전부 302다:

    sise/sise_market_sum → stock.naver.com/market/stock/kr/stocklist/capitalization
    sise/sise_quant      → …/stocklist/trading
    item/frgn            → stock.naver.com/domestic/stock/{code}/investmentinfo
    item/main            → …/{code}/price
    item/board           → …/{code}/discussion

새 페이지는 SPA라 HTML 표가 없다. requests는 리다이렉트를 따라가 **HTTP 200**을
받으므로, 표를 못 찾은 파서들은 예외 없이 "0건"을 냈다. 크게 죽은 건 목록이 0이면
exit 1 하던 EOD·프리마켓뿐이고, 종토방·수급·국면 breadth는 **초록인 채 비었다.**

같은 데이터를 m.stock.naver.com의 JSON API가 준다. 네이버 호출은 여기로 모은다 —
또 옮기면 고칠 곳이 이 파일 하나다.
(아직 살아 있는 옛 페이지: item/sise_day, item/sise_time, item/news_news, item/news_notice)

## 계약

못 얻으면 `None`. **응답 모양이 기대와 달라도 `None`이다** — "표가 없으면 0건"이
이번 사고의 모양이었다. 빈 리스트는 "정상적으로 비었다"(장 시작 전 거래량 순위 등)만
뜻한다. 값이 없는 필드도 None이다 — 0으로 채우지 않는다.
"""
import requests

from src.core import net

_BASE ='https://m.stock.naver.com'
_HDRS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
_PAGE_SIZE = 100
_MAX_LIST_PAGES = 10

# 등락 방향. fluctuationsRatio의 부호를 믿지 않고 이것으로 정한다.
_UP = {'RISING', 'UPPER_LIMIT'}
_DOWN = {'FALLING', 'LOWER_LIMIT'}


def _num(value):
    """'269,000' / '+4,266,985' / '46.71%' → float. '-'·''·'N/A'·None → None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(',', '').replace('%', '').replace('+', '').strip()
    try:
        return float(text)
    except ValueError:
        return None


def _int(value):
    v = _num(value)
    return int(v) if v is not None else None


def _note(reasons, key):
    if reasons is not None:
        reasons[key] = reasons.get(key, 0) + 1


def _json(url, *, policy, target, session=None, reasons=None):
    res = net.get(url, policy=policy, target=target, session=session,
                  reasons=reasons, headers=_HDRS)
    if res is None:
        return None
    try:
        return res.json()
    except ValueError:
        # 리다이렉트 끝의 HTML 페이지가 여기로 온다 — 이번 사고의 모양이다.
        _note(reasons, 'not_json')
        return None


def _signed_rate(item):
    rate = _num(item.get('fluctuationsRatio'))
    if rate is None:
        return None
    direction = (item.get('compareToPreviousPrice') or {}).get('name')
    if direction in _DOWN:
        return -abs(rate)
    if direction in _UP:
        return abs(rate)
    return rate


def stock_list(kind, market, limit, *, stock_only=True, policy=net.BULK):
    """순위 목록. kind: 'marketValue'(시총) | 'quantTop'(거래량). market: 'KOSPI' | 'KOSDAQ'.

    stock_only: ETF·ETN을 뺀다. 시총 목록은 옛 sise_market_sum과 달리 ETF가 섞여
    온다(2026-09-11 실측: KOSPI 상위 200 중 43개가 ETF).

    행: code, name, price, change_rate(%, 부호 있음), volume(주), amount(원),
        market_cap(억원). 한 페이지라도 실패하면 None — 부분 목록을 전체처럼 쓰지 않는다.
    """
    rows, seen = [], set()
    for page in range(1, _MAX_LIST_PAGES + 1):
        d = _json(f'{_BASE}/api/stocks/{kind}/{market}?page={page}&pageSize={_PAGE_SIZE}',
                  policy=policy, target='naver')
        batch = d.get('stocks') if isinstance(d, dict) else None
        if not isinstance(batch, list):
            return None
        for item in batch:
            code = str(item.get('itemCode') or '')
            if len(code) != 6 or not code.isdigit() or code in seen:
                continue
            if stock_only and item.get('stockEndType') != 'stock':
                continue
            seen.add(code)
            rows.append({
                'code': code,
                'name': item.get('stockName') or '',
                'price': _num(item.get('closePrice')),
                'change_rate': _signed_rate(item),
                'volume': _int(item.get('accumulatedTradingVolume')),
                'amount': _trading_value_won(item.get('accumulatedTradingValue')),
                'market_cap': _num(item.get('marketValue')),
            })
            if len(rows) >= limit:
                return rows
        if len(batch) < _PAGE_SIZE:
            break
    return rows


def _trading_value_won(value):
    """accumulatedTradingValue(백만원 단위) → 원."""
    v = _num(value)
    return v * 1_000_000 if v is not None else None


def investor_trend(code, days=20, *, policy=net.BULK):
    """일별 수급 — 옛 item/frgn 표와 같은 재료. 최신이 앞이다.

    행: date(YYYYMMDD), close, volume, organ_net(기관 순매매량),
        foreign_net(외국인 순매매량), foreign_hold_ratio(%).
    """
    d = _json(f'{_BASE}/api/stock/{code}/trend?pageSize={days}', policy=policy,
              target='naver')
    if not isinstance(d, list):
        return None
    out = []
    for r in d:
        if not isinstance(r, dict):
            continue
        date, close = r.get('bizdate'), _int(r.get('closePrice'))
        if not date or close is None:
            continue
        out.append({
            'date': str(date),
            'close': close,
            'volume': _int(r.get('accumulatedTradingVolume')),
            'organ_net': _int(r.get('organPureBuyQuant')),
            'foreign_net': _int(r.get('foreignerPureBuyQuant')),
            'foreign_hold_ratio': _num(r.get('foreignerHoldRatio')),
        })
    return out


def new_session():
    """같은 호스트를 연달아 칠 때 연결을 재사용한다. 스레드 안전이 아니다 — 스레드마다 하나."""
    return requests.Session()


def discussion_page(code, offset=None, *, session=None, reasons=None):
    """종목토론 한 페이지(최신순). `(posts, next_offset)` 또는 None.

    커서(offset) 방식이다 — 옛 board.naver의 page=N과 달리 다음 페이지를 알려면
    이전 응답이 있어야 해서 **병렬로 긁을 수 없다.**

    post: nid, title, likes(공감), writer(프로필 id), written_at('YYYY-MM-DDTHH:MM:SS')
    """
    url = (f'{_BASE}/front-api/discussion/list?discussionType=domesticStock'
           f'&itemCode={code}&isHolderOnly=false&excludesItemNews=true'
           f'&isItemNewsOnly=false&isCleanbotPassedOnly=false&pageSize={_PAGE_SIZE}')
    if offset:
        url += f'&offset={offset}'
    d = _json(url, policy=net.SCRAPE, target='naver_board', session=session,
              reasons=reasons)
    if d is None:
        return None
    result = d.get('result') if isinstance(d, dict) else None
    posts = result.get('posts') if isinstance(result, dict) else None
    if not isinstance(posts, list):
        _note(reasons, 'bad_shape')
        return None
    out = []
    for p in posts:
        nid, written = str(p.get('id') or ''), str(p.get('writtenAt') or '')
        if not nid or not written:
            continue
        writer = p.get('writer') or {}
        out.append({
            'nid': nid,
            'title': p.get('title') or '',
            'likes': _int(p.get('recommendCount')) or 0,
            'writer': str(writer.get('profileId') or writer.get('nickname') or ''),
            'written_at': written,
        })
    return out, result.get('lastOffset')


def asking_price(code, *, policy=net.BULK):
    """호가 잔량 합계 `{'total_sell', 'total_buy'}` 또는 None."""
    d = _json(f'{_BASE}/api/stock/{code}/askingPrice', policy=policy, target='naver')
    if not isinstance(d, dict):
        return None
    sell, buy = _int(d.get('totalSell')), _int(d.get('totalBuy'))
    if sell is None or buy is None:
        return None
    return {'total_sell': sell, 'total_buy': buy}


def current_price(code, *, policy=net.FAST):
    """현재가(장중) / 종가(마감 뒤). int 또는 None."""
    d = _json(f'{_BASE}/api/stock/{code}/basic', policy=policy, target='naver')
    if not isinstance(d, dict):
        return None
    return _int(d.get('closePrice'))
