"""Sim17 패닉 바닥 판정기 — 판정 로직과 폴백 계약."""
import pytest

from src.data import macro_panic
from src.strategy.simulators.sim17_panic_floor import (
    NORMAL, PANIC, UNKNOWN, WATCH, classify, format_notice,
)


def _m(**kw):
    base = {'ready': True, 'epu_12m_pct': 50.0, 'epu_z': 0.0, 'stress_z': 0.0,
            'epu_level': 100.0, 'epu_month': '2026-09', 'epu_obs': 30,
            'stress_level': -0.5, 'stress_month': '2026-09'}
    base.update(kw)
    return base


# ── 판정 ──────────────────────────────────────────────
def test_정상():
    assert classify(_m())[0] == NORMAL


def test_관찰은_EPU_분위_80부터():
    assert classify(_m(epu_12m_pct=79.9))[0] == NORMAL
    assert classify(_m(epu_12m_pct=80.0))[0] == WATCH


def test_패닉은_두_z가_동시에_2이상일_때만():
    assert classify(_m(stress_z=2.5, epu_z=1.9))[0] != PANIC
    assert classify(_m(stress_z=1.9, epu_z=2.5))[0] != PANIC
    assert classify(_m(stress_z=2.0, epu_z=2.0))[0] == PANIC


def test_패닉이_관찰보다_우선한다():
    # 분위가 낮아도 두 z가 극단이면 패닉이다
    assert classify(_m(epu_12m_pct=10.0, stress_z=3.0, epu_z=3.0))[0] == PANIC


# ── 값이 없으면 판정하지 않는다 (0으로 채우고 '정상'이라 말하지 않는다) ──
def test_지표_미완성이면_판정불가():
    assert classify(None)[0] == UNKNOWN
    assert classify({'ready': False})[0] == UNKNOWN


@pytest.mark.parametrize('missing', ['epu_12m_pct', 'epu_z', 'stress_z'])
def test_핵심_지표가_하나라도_없으면_판정불가(missing):
    m = _m()
    m[missing] = None
    assert classify(m)[0] == UNKNOWN


# ── 폴백 계약 ────────────────────────────────────────
def test_같은_날이면_직전_값을_그대로_쓴다(monkeypatch):
    called = []
    monkeypatch.setattr(macro_panic, 'collect',
                        lambda **kw: (called.append(1), ({'ready': True}, []))[1])
    prev = _m(asof='2026-10-07')
    got = macro_panic.get_metrics(prev, today='2026-10-07')
    assert got is prev and not called, '같은 날 재호출은 네트워크를 타면 안 된다'


def test_수집_실패하면_직전_값을_stale로_표시해_쓴다(monkeypatch):
    monkeypatch.setattr(macro_panic, 'collect',
                        lambda **kw: ({'ready': False, 'errors': ['fred down']}, []))
    prev = _m(asof='2026-10-06')
    got = macro_panic.get_metrics(prev, today='2026-10-07')
    assert got['stale'] is True
    assert 'fred down' in got['stale_reason']
    assert got['epu_12m_pct'] == prev['epu_12m_pct']


def test_직전_값도_없고_수집도_실패하면_판정불가(monkeypatch):
    monkeypatch.setattr(macro_panic, 'collect',
                        lambda **kw: ({'ready': False, 'errors': ['fred down']}, []))
    got = macro_panic.get_metrics(None, today='2026-10-07')
    assert not got.get('ready')
    assert classify(got)[0] == UNKNOWN


# ── 알림 본문 ────────────────────────────────────────
def test_알림에_단계전이와_근거가_들어간다():
    m = _m(stress_z=2.5, epu_z=2.5)
    stage, reason = classify(m)
    text = format_notice(stage, reason, m, NORMAL)
    assert f'{NORMAL} → {PANIC}' in text
    assert '금융스트레스' in text and 'EPU' in text
    assert '관찰용' in text, '검증되지 않은 규칙이라는 사실이 본문에 있어야 한다'


def test_미완결_월이면_알림에_표시된다():
    m = _m(epu_month_partial=True, epu_obs=5)
    text = format_notice(*classify(m), m, UNKNOWN)
    assert '미완결' in text


def test_stale이면_알림에_표시된다():
    m = _m(stale=True, stale_reason='fred down')
    text = format_notice(*classify(m), m, UNKNOWN)
    assert '어제 값' in text and 'fred down' in text


# ── 매매하지 않는다 ──────────────────────────────────
def test_분석기_플래그와_빈_유니버스():
    from src.strategy.simulators.sim17_panic_floor import PanicFloorSimulator
    assert PanicFloorSimulator.IS_ANALYZER is True
    assert PanicFloorSimulator.IS_EOD is True
    sim = PanicFloorSimulator.__new__(PanicFloorSimulator)
    assert sim.get_universe() == []
