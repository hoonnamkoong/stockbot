"""실계좌에서 사라진 프로그램 포지션은 조용히 지우면 안 된다.

2026-07-08에 진흥기업 1,230주(매입원가 1,495,680원)와 비엘팜텍 72주(295,920원)가
원장에서 사라졌는데 그날 realized_pnl 변화는 -6,417원(다른 두 종목의 프로그램 매도)
뿐이었다. 179만원어치의 청산 결과가 집계에 들어가지 않았고, 수동 매도는 대개
손절이라 손실만 빠지고 이익은 남아 수익률이 실제보다 좋아 보였다.

체결가는 우리 기록에 없으므로 손익을 지어내지 않는다. 대신 '빠졌다'는 사실을
원장에 남겨 나중에 정산할 수 있게 하고, 로그로 즉시 드러낸다.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.program_trader import reconcile_positions


def _pos(qty, avg, name):
    return {'name': name, 'quantity': qty, 'avg_price': avg,
            'peak_price': avg, 'entry_date': '2026-07-07', 'is_scaled_out': False}


def test_keeps_positions_that_still_exist_in_account():
    ledger = {'positions': {'005930': _pos(10, 3000, '삼성전자')}}
    logs = []

    out = reconcile_positions(ledger, {'005930': {}}, '2026-07-08', logs.append)

    assert out == {'005930': _pos(10, 3000, '삼성전자')}
    assert ledger.get('unreconciled_exits') is None
    assert logs == []


def test_records_vanished_position_instead_of_dropping_it_silently():
    """실보유에 없으면 원장에서는 빠지되, 빠진 사실이 기록으로 남아야 한다."""
    ledger = {'positions': {'002780': _pos(1230, 1216, '진흥기업'),
                            '005930': _pos(10, 3000, '삼성전자')}}
    logs = []

    out = reconcile_positions(ledger, {'005930': {}}, '2026-07-08', logs.append)

    assert list(out) == ['005930']                      # 실보유만 남는다
    rec = ledger['unreconciled_exits']
    assert len(rec) == 1
    assert rec[0]['code'] == '002780'
    assert rec[0]['quantity'] == 1230
    assert rec[0]['cost_basis'] == 1230 * 1216          # 1,495,680
    assert rec[0]['date'] == '2026-07-08'
    assert 'pnl' not in rec[0]                          # 체결가를 모르므로 손익은 만들지 않는다
    assert any('002780' in m for m in logs)


def test_accumulates_across_runs():
    """이미 기록된 건이 있어도 덮어쓰지 않고 누적한다."""
    ledger = {'positions': {'065170': _pos(72, 4110, '비엘팜텍')},
              'unreconciled_exits': [{'date': '2026-07-08', 'code': '002780', 'name': '진흥기업',
                                      'quantity': 1230, 'avg_price': 1216, 'cost_basis': 1495680}]}

    reconcile_positions(ledger, {}, '2026-07-08', lambda _m: None)

    assert [r['code'] for r in ledger['unreconciled_exits']] == ['002780', '065170']


def test_empty_ledger_is_noop():
    ledger = {}
    out = reconcile_positions(ledger, {'005930': {}}, '2026-07-08', lambda _m: None)
    assert out == {}
    assert 'unreconciled_exits' not in ledger


# ── 사라진 날이 아니라 '언제부터 사이'인지 남긴다 ─────────────────────

def test_records_the_window_not_a_false_sell_date():
    """`date`는 발견일이지 매도일이 아니다. 둘을 같다고 적으면 조회가 0건이 된다.

    태스커가 멈춰 있으면 수동 매도를 며칠 뒤에야 알아챈다. 원장은 그 발견일을
    적고, KIS에 그 날짜로 물으면 해당 종목 매도는 없다. 정산하려면 **직전
    완주일부터 발견일까지**의 구간이 필요하다 — 그 값은 원장의 `last_run`이
    이미 들고 있다.
    """
    ledger = {'positions': {'000111': _pos(50, 10000, '테스트항공')},
              'last_run': '2026-01-02T12:48:04.746813'}

    reconcile_positions(ledger, {}, '2026-01-07', lambda _m: None)

    rec = ledger['unreconciled_exits'][0]
    assert rec['since'] == '2026-01-02'       # 마지막으로 정상이었던 날
    assert rec['detected_on'] == '2026-01-07'
    assert rec['date'] == '2026-01-07'        # 기존 소비자 호환


def test_window_start_is_omitted_when_the_ledger_never_ran():
    """모르면 적지 않는다 — 정산이 되돌아보기 기본값으로 떨어진다."""
    ledger = {'positions': {'000111': _pos(50, 10000, '테스트항공')}}

    reconcile_positions(ledger, {}, '2026-01-07', lambda _m: None)

    assert 'since' not in ledger['unreconciled_exits'][0]
