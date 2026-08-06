"""원장 락 — 두 런이 겹쳐도 같은 주문을 두 번 내지 않는다.

기존 구조는 원장을 읽고(_read_ledger_fresh) → 주문을 전부 집행하고 → 마지막에
last_run을 썼다. 읽기와 쓰기 사이가 런 전체라, 두 런이 겹치면 둘 다 같은 last_run을
읽고 중복가드를 통과해 같은 주문을 두 번 냈다. _write_ledger는 409를 만나면 fresh
sha로 재시도해 덮어쓰므로 방어가 아니라 오히려 충돌 감지를 무력화했다.

태스커 주기가 2분으로 좁혀지면서 런 실행시간(60~90초)과 주기가 비슷해져 겹침이
상시화되므로, last_run과 분리된 전용 락 필드로 주문 전에 배타권을 잡는다.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.program_trader import (
    _LOCK_LEASE_MIN,
    _lock_is_live,
    _claim_payload,
    _release_payload,
    _lock_held_by,
)


def _now():
    return datetime(2026, 8, 6, 10, 30, 0)


# ── 살아있는 락 판정 ────────────────────────────────────────────────

def test_no_lock_field_means_free():
    assert _lock_is_live({}, _now()) is False
    assert _lock_is_live({'lock_run_id': None, 'lock_at': None}, _now()) is False


def test_fresh_lock_is_live():
    now = _now()
    ledger = {'lock_run_id': 'run-1', 'lock_at': (now - timedelta(seconds=30)).isoformat()}
    assert _lock_is_live(ledger, now) is True


def test_lock_within_lease_is_live():
    """리스 만료 직전까지는 남의 락으로 본다."""
    now = _now()
    just_inside = now - timedelta(minutes=_LOCK_LEASE_MIN) + timedelta(seconds=5)
    ledger = {'lock_run_id': 'run-1', 'lock_at': just_inside.isoformat()}
    assert _lock_is_live(ledger, now) is True


def test_expired_lock_is_reclaimable():
    """죽은 런이 남긴 락은 리스 만료로 자동 회수된다."""
    now = _now()
    expired = now - timedelta(minutes=_LOCK_LEASE_MIN) - timedelta(seconds=1)
    ledger = {'lock_run_id': 'run-1', 'lock_at': expired.isoformat()}
    assert _lock_is_live(ledger, now) is False


def test_released_lock_is_free_regardless_of_time():
    """정상 종료한 런은 락을 비운다 — 리스와 무관하게 다음 사이클이 바로 진입한다."""
    now = _now()
    ledger = {'lock_run_id': None, 'lock_at': (now - timedelta(seconds=1)).isoformat()}
    assert _lock_is_live(ledger, now) is False


def test_corrupt_lock_timestamp_is_treated_as_live():
    """파싱 불가는 '락 없음'이 아니다 — 모르는 것을 자유로 읽으면 중복 주문이 난다."""
    now = _now()
    ledger = {'lock_run_id': 'run-1', 'lock_at': 'not-a-timestamp'}
    assert _lock_is_live(ledger, now) is True


# ── 락 선점 / 해제 페이로드 ────────────────────────────────────────

def test_claim_sets_run_id_and_timestamp_but_not_last_run():
    """선점 단계에서 last_run을 건드리면 안 된다.

    last_run은 중복가드(_recently_ran)의 입력이고, 락과 수명이 다르다.
    선점 시점에 last_run을 밀면 주문이 실패해도 다음 사이클이 가드에 걸린다.
    """
    now = _now()
    ledger = {'positions': {'005930': {}}, 'last_run': '2026-08-06T10:20:00', 'realized_pnl': -100}

    out = _claim_payload(ledger, 'run-42', now)

    assert out['lock_run_id'] == 'run-42'
    assert out['lock_at'] == now.isoformat()
    assert out['last_run'] == '2026-08-06T10:20:00'
    assert out['positions'] == {'005930': {}}
    assert out['realized_pnl'] == -100


def test_claim_does_not_mutate_input():
    now = _now()
    ledger = {'last_run': None}
    _claim_payload(ledger, 'run-42', now)
    assert 'lock_run_id' not in ledger


def test_release_clears_lock():
    ledger = {'lock_run_id': 'run-42', 'lock_at': _now().isoformat(), 'positions': {}}

    out = _release_payload(ledger)

    assert out['lock_run_id'] is None
    assert out['lock_at'] is None
    assert out['positions'] == {}


# ── 좀비 방어: 2단계 기록 직전 소유권 확인 ────────────────────────

def test_lock_held_by_matches_own_run():
    assert _lock_held_by({'lock_run_id': 'run-42'}, 'run-42') is True


def test_lock_held_by_rejects_stolen_lock():
    """리스 만료 후 남이 락을 가져갔으면 내 것이 아니다."""
    assert _lock_held_by({'lock_run_id': 'run-99'}, 'run-42') is False


def test_lock_held_by_rejects_released_lock():
    assert _lock_held_by({'lock_run_id': None}, 'run-42') is False


# ── 리스와 중복가드의 관계 ────────────────────────────────────────

def test_lease_is_longer_than_dup_guard():
    """리스가 중복가드보다 짧으면 락이 풀린 뒤에도 가드가 남아 사이클을 낭비한다.

    반대로 리스는 런 최대 실행시간보다 길어야 실행 중인 런의 락이 안 뺏긴다.
    """
    from src.pipeline.workers.program_trader import _DUP_GUARD_MIN
    assert _LOCK_LEASE_MIN > _DUP_GUARD_MIN


def test_dup_guard_fits_two_minute_cadence():
    """태스커 2분 주기에서 정상 간격의 트리거가 가드에 막히면 안 된다."""
    from src.pipeline.workers.program_trader import _DUP_GUARD_MIN
    assert _DUP_GUARD_MIN < 2.0
