"""Sim19 반도체 붐의 질 — 가격·물량 분해와 관세청 파서 함정.

여기서 지키는 것은 둘 —
  ① 질 판정이 2026-08 실측(금액 +203.1% / 단가 +199.3% / 중량 +1.3%)을
     '가격주도'로 읽는가
  ② 관세청 응답 파서가 함정 셋을 피하는가 — 세부코드 합산 · 연간 합계 행
     제외 · XML(JSON 아님)
"""
import pytest

from src.data import semi_trade
from src.strategy.simulators.sim19_semi_boom import (
    CONTRACTING, MIXED, PRICE_LED, UNKNOWN, VOLUME_LED,
    classify, format_notice,
)


# ── 질 판정 ──────────────────────────────────────────
def test_2026_08_actual_is_price_led():
    """실측값이 가격주도로 읽혀야 한다 — 이 심의 존재 이유다."""
    q, reason = classify(203.1, 199.3, 1.3)
    assert q == PRICE_LED
    assert '제자리' in reason


def test_volume_led():
    assert classify(30.0, 5.0, 25.0)[0] == VOLUME_LED


def test_mixed():
    q = classify(40.0, 20.0, 16.0)[0]
    assert q == MIXED


def test_contracting_when_amount_falls():
    assert classify(-12.0, -20.0, +9.0)[0] == CONTRACTING


def test_price_share_alone_is_not_enough_if_volume_grows():
    """단가 비중이 높아도 물량이 늘고 있으면 '물량 없는 붐'이 아니다."""
    assert classify(100.0, 80.0, 20.0)[0] != PRICE_LED


@pytest.mark.parametrize('miss', [(None, 1.0, 1.0), (1.0, None, 1.0),
                                  (1.0, 1.0, None)])
def test_missing_any_metric_is_unknown(miss):
    assert classify(*miss)[0] == UNKNOWN


# ── 알림 본문 ────────────────────────────────────────
def test_notice_warns_on_price_led_and_states_no_prediction():
    m = {'month': '2026-08', '금액': 3.824e10, '단가': 22837.0,
         '중량': 1.674e6, '중량추이': [12.8, 9.9, 3.7, 8.5, -1.2, 1.3]}
    t = format_notice(PRICE_LED, '금액 +203.1% 중 단가가 +199.3%p', MIXED, m)
    assert '물량 없는 가격 붐' in t
    assert '예측이 아니라 상태 기술' in t, '예측력 없음을 본문에 밝혀야 한다'
    assert 'p=0.092' in t, '검정 결과를 숨기지 않는다'
    assert '2026-08' in t


# ── 관세청 파서 함정 ─────────────────────────────────
_XML = '''<?xml version="1.0"?><response><header><resultCode>00</resultCode>
</header><body><items>
<item><year>2026.08</year><hsCode>8542311000</hsCode>
<expDlr>1000</expDlr><expWgt>10</expWgt></item>
<item><year>2026.08</year><hsCode>8542321000</hsCode>
<expDlr>3000</expDlr><expWgt>20</expWgt></item>
<item><year>2026</year><hsCode>8542</hsCode>
<expDlr>999999</expDlr><expWgt>9999</expWgt></item>
</items></body></response>'''


class _Res:
    text = _XML


def test_parser_sums_subcodes_and_drops_annual_row(monkeypatch):
    """세부코드를 덮어쓰면 300억$가 0.4억$로 읽힌다. 연간 합계 행을 더하면 10배가 된다."""
    monkeypatch.setattr(semi_trade.net, 'get', lambda *a, **k: _Res())
    got, err = semi_trade.fetch_year(2026, key='dummy')
    assert err is None
    assert set(got) == {'2026-08-01'}, '연간 합계 행(year=2026)이 들어오면 안 된다'
    assert got['2026-08-01'] == (4000.0, 30.0), '세부코드를 합산해야 한다'


def test_series_computes_unit_price(monkeypatch):
    monkeypatch.setattr(semi_trade.net, 'get', lambda *a, **k: _Res())
    s, errs = semi_trade.fetch_series([2026], key='dummy', log=lambda *a: None)
    assert s['2026-08-01']['단가'] == pytest.approx(4000.0 / 30.0)


def test_missing_key_is_an_error_not_an_empty_result(monkeypatch):
    """키가 없으면 '0건'이 아니라 '측정 불가'여야 한다."""
    monkeypatch.delenv(semi_trade.ENV_KEY, raising=False)
    got, err = semi_trade.fetch_year(2026, key='')
    assert got is None and semi_trade.ENV_KEY in err


def test_zero_weight_month_is_dropped_not_zero_filled(monkeypatch):
    """중량 0이면 단가가 무한이 된다 — 그 달을 버려야 한다."""
    class R:
        text = ('<response><items><item><year>2026.08</year>'
                '<expDlr>100</expDlr><expWgt>0</expWgt></item></items>'
                '</response>')
    monkeypatch.setattr(semi_trade.net, 'get', lambda *a, **k: R())
    s, _ = semi_trade.fetch_series([2026], key='x', log=lambda *a: None)
    assert s == {}


# ── 매매하지 않는다 ──────────────────────────────────
def test_analyzer_flags_and_empty_universe():
    from src.strategy.simulators.sim19_semi_boom import SemiBoomSimulator
    assert SemiBoomSimulator.IS_ANALYZER is True
    assert SemiBoomSimulator.IS_EOD is True
    sim = SemiBoomSimulator.__new__(SemiBoomSimulator)
    assert sim.get_universe() == []
