"""FINRA 공매도 잔고 수집 — 가장 최근 결제일, 페이지 넘김, 실패는 예외로."""
from unittest import mock

import pytest

from src.core import net
from src.data import us_short_interest as m


class _Resp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def _serve(pages_by_date, dates):
    def post(url, **kw):
        payload = kw['json']
        flt = payload['compareFilters'][0]
        if flt['fieldName'] == 'symbolCode':
            return _Resp([{'settlementDate': d} for d in dates])
        rows = pages_by_date[flt['fieldValue']]
        off = payload.get('offset', 0)
        return _Resp(rows[off:off + payload['limit']])
    return post


def test_latest_settlement_date_is_the_max():
    with mock.patch.object(net, 'post', side_effect=_serve({}, ['2026-08-31', '2026-09-15', '2026-08-14'])):
        assert m.fetch_latest_settlement_date() == '2026-09-15'


def test_fetch_pages_until_a_short_page_and_keeps_zero():
    rows = [{'symbolCode': f'S{i}', 'currentShortPositionQuantity': i} for i in range(m.PAGE + 3)]
    with mock.patch.object(net, 'post', side_effect=_serve({'2026-09-15': rows}, ['2026-09-15'])) as post:
        date, out = m.fetch_latest_short_interest()
    assert date == '2026-09-15' and len(out) == m.PAGE + 3
    assert out['S0'] == 0.0, '잔고 0주는 값이다 — 버리면 "모른다"와 섞인다'
    assert post.call_count == 3      # 결제일 탐침 1 + 두 페이지


def test_rows_without_quantity_are_dropped_not_zeroed():
    rows = [{'symbolCode': 'AAA', 'currentShortPositionQuantity': None}, {'symbolCode': 'BBB', 'currentShortPositionQuantity': 5}]
    with mock.patch.object(net, 'post', side_effect=_serve({'2026-09-15': rows}, ['2026-09-15'])):
        assert m.fetch_short_interest('2026-09-15') == {'BBB': 5.0}


def test_unexpected_body_raises():
    with mock.patch.object(net, 'post', return_value=_Resp({'message': 'error'})):
        with pytest.raises(net.NetError):
            m.fetch_latest_settlement_date()


def test_requests_are_required_so_failure_is_not_silent():
    with mock.patch.object(net, 'post', return_value=_Resp([{'settlementDate': '2026-09-15'}])) as post:
        m.fetch_latest_settlement_date()
    assert post.call_args.kwargs['required'] is True
