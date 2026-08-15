"""실거래 이력에서 '주문했다'와 '체결됐다'를 가른다.

2026-08-12: 001210(금호전기)을 7번 주문했고 **체결은 0건**인데,
`trade_history_real.csv`에는 매수 7행이 남았다. 주문 접수 시점에 무조건 한 줄을
쓰고 status 컬럼이 없어서, 미체결과 체결이 똑같이 보였다.

지우지 않고 덧붙인다. 이 파일은 writer가 둘(trading.yml·scraper.yml)이라
read-modify-write를 하면 lost update가 난다 — `alert_dedup.json`에서 이미 겪었다.
그래서 pending 행을 남긴 채 filled 행을 뒤에 붙이고, 읽는 쪽이 짝지어 본다.
주문/체결 비율이 그대로 체결률이 된다.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.trade.pending import reconcile_pending
from src.trade.executions import FILLED, UNFILLED
from src.trade_executor import TRADE_HISTORY_HEADER


def test_status_is_the_last_column():
    """뒤에만 추가한다 — 기존 8칸 행이 그대로 유효하게 읽혀야 한다."""
    assert TRADE_HISTORY_HEADER[-1] == 'status'
    assert TRADE_HISTORY_HEADER[:8] == ["timestamp", "symbol", "action", "price",
                                        "quantity", "total_amount", "roi", "reason"]


def _ledger():
    return {
        'positions': {}, 'realized_pnl': 0,
        'pending_orders': {
            '001210': {'odno': 'OD1', 'side': 'buy', 'qty': 34, 'price': 5300.0,
                       'ordered_at': '2026-08-12T15:29:21', 'avg_price': None,
                       'tag': 'sim4', 'snapshot': {}, 'applied_qty': 0},
        },
    }


def test_fill_hook_fires_with_actual_price_not_order_price():
    """주문가 5,300이 아니라 실제 체결가 5,250으로 남아야 한다."""
    calls = []
    reconcile_pending(_ledger(), {'OD1': (FILLED, {'qty': 34, 'price': 5250.0})},
                      '2026-08-12', on_fill=lambda *a: calls.append(a))

    assert len(calls) == 1
    code, qty, price, _entry = calls[0]
    assert (code, qty, price) == ('001210', 34, 5250.0)


def test_unfilled_order_does_not_fire_the_hook():
    """이게 001210 7행의 원인이다 — 미체결은 체결 이력을 만들지 않는다."""
    calls = []
    reconcile_pending(_ledger(), {'OD1': (UNFILLED, None)}, '2026-08-12',
                      on_fill=lambda *a: calls.append(a))

    assert calls == []


def test_partial_fill_reports_only_the_new_portion():
    """누적 체결량이 두 번 반영되면 이력도 두 배가 된다."""
    led = _ledger()
    led['pending_orders']['001210']['applied_qty'] = 10
    calls = []
    reconcile_pending(led, {'OD1': (FILLED, {'qty': 24, 'price': 5250.0})},
                      '2026-08-12', on_fill=lambda *a: calls.append(a))

    assert [c[1] for c in calls] == [14], '이미 반영한 10주를 빼고 14주만'


def test_hook_is_optional():
    """백테스트 등 이력을 안 남기는 호출은 그대로 돈다."""
    reconcile_pending(_ledger(), {'OD1': (FILLED, {'qty': 34, 'price': 5250.0})},
                      '2026-08-12')


def test_stale_header_is_refreshed(tmp_path, monkeypatch):
    """컬럼을 늘렸는데 기존 파일이 옛 헤더를 유지하면, 읽는 쪽이 컬럼 이름을
    잘못 짚는다. 예전엔 파일이 비었을 때만 헤더를 썼다."""
    from src.trade import secret_store

    seen = {}

    def fake_update_text(path, transform, message, log=print):
        seen['out'] = transform('﻿a,b,c\n1,2,3\n')
        return True

    monkeypatch.setattr(secret_store, 'update_text', fake_update_text)
    secret_store.append_csv_row('x.csv', '4,5,6,7', 'a,b,c,d', 'msg')

    lines = seen['out'].split('\n')
    assert lines[0].lstrip('﻿') == 'a,b,c,d', '헤더가 갱신돼야 한다'
    assert lines[1] == '1,2,3', '기존 행은 건드리지 않는다'
    assert lines[2] == '4,5,6,7'


def test_matching_header_is_left_alone(tmp_path, monkeypatch):
    from src.trade import secret_store

    seen = {}
    monkeypatch.setattr(secret_store, 'update_text',
                        lambda p, t, m, log=print: seen.update(out=t('﻿a,b\n1,2\n')) or True)
    secret_store.append_csv_row('x.csv', '3,4', 'a,b', 'msg')

    assert seen['out'] == '﻿a,b\n1,2\n3,4\n'
