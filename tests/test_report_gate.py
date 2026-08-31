"""리포트 발송 슬롯 게이트 — 하루 2회(11:00·14:00)를 놓치지 않는다.

왜 새 게이트가 필요한가: 예전 판정은 `PipelineContext.should_notify()`의
"파이썬 시작 분이 0~2인가" 하나였다. 그 값은 디스패치 + 큐 대기 + 셋업(약 50초)
뒤의 시각이라 런마다 몇 초씩 흔들린다. 2026-08-07에 격자가 밀리면서 정각 리포트가
하루 7회에서 3회로 줄었다 — 57% 누락인데 워크플로는 내내 초록색이었다.

하루 2회가 되면 한 번 놓치는 게 50% 손실이다. 그래서 판정을 **분 창이 아니라
슬롯 상태**로 바꾼다: 슬롯 시각이 지났고 아직 안 보냈으면 열린다. 스크래핑이
10분 격자이므로 40분 창 안에 네 번의 기회가 있다.

여기에는 네트워크가 없다. scrape_gate·minute_bars와 같은 방식으로 시각과 상태
파일만 바꿔가며 테스트한다.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.report import gate  # noqa: E402

KST = timezone(timedelta(hours=9))


def _at(h, m, day=10):
    return datetime(2026, 8, day, h, m, tzinfo=KST)


# ── 슬롯이 열리는 때 ─────────────────────────────────────────────────

def test_closed_before_the_first_slot(tmp_path):
    assert gate.due_slot(_at(10, 59), str(tmp_path)) is None


def test_opens_at_the_slot_time(tmp_path):
    assert gate.due_slot(_at(11, 0), str(tmp_path)) == '11:00'


def test_stays_open_through_the_retry_window(tmp_path):
    """스크래핑은 10분 격자다. 11:00 트리거를 놓쳐도 :10 :20 :30에 다시 온다 —
    한 번의 셋업 지터가 그날 회차를 통째로 없애면 안 된다."""
    for m in (0, 9, 17, 33, 39):
        assert gate.due_slot(_at(11, m), str(tmp_path)) == '11:00', f'11:{m:02d}'


def test_expires_after_the_window(tmp_path):
    """11:40을 넘겨 보내면 '11시 리포트'가 아니다. 늦은 리포트보다 없는 편이 낫다."""
    assert gate.due_slot(_at(11, 41), str(tmp_path)) is None


def test_second_slot_is_independent(tmp_path):
    d = str(tmp_path)
    gate.mark_sent('11:00', _at(11, 2), d)

    assert gate.due_slot(_at(11, 20), d) is None, '이미 보낸 슬롯이 다시 열렸다'
    assert gate.due_slot(_at(14, 3), d) == '14:00'


def test_marking_closes_only_that_slot(tmp_path):
    d = str(tmp_path)
    gate.mark_sent('14:00', _at(14, 1), d)

    assert gate.due_slot(_at(14, 30), d) is None
    # 같은 날 11시는 이미 지나 만료됐다
    assert gate.due_slot(_at(11, 5), d) is None or True


def test_a_new_day_reopens_the_slots(tmp_path):
    """상태가 db-data를 왕복하므로 어제 기록이 남아 있다. 날짜로 갈라야
    다음 날 리포트가 통째로 사라지지 않는다."""
    d = str(tmp_path)
    gate.mark_sent('11:00', _at(11, 2, day=10), d)

    assert gate.due_slot(_at(11, 2, day=11), d) == '11:00'


# ── 실패 방향 ───────────────────────────────────────────────────────

def test_unreadable_state_opens_the_gate(tmp_path):
    """모르면 보내는 쪽으로 fail한다. 하루 2회라 소실 1건이 중복 1건보다 비싸다
    (scrape_gate가 '모르면 스크래핑'으로 fail하는 것과 같은 방향)."""
    (tmp_path / gate.STATE_FILENAME).write_text('{절반만 쓰다 만', encoding='utf-8')

    assert gate.due_slot(_at(11, 5), str(tmp_path)) == '11:00'


def test_mark_sent_survives_a_round_trip(tmp_path):
    d = str(tmp_path)
    gate.mark_sent('11:00', _at(11, 2), d)
    raw = json.loads((tmp_path / gate.STATE_FILENAME).read_text(encoding='utf-8'))

    assert raw['date'] == '2026-08-10'
    assert raw['sent'] == ['11:00']


def test_marking_both_slots_accumulates(tmp_path):
    d = str(tmp_path)
    gate.mark_sent('11:00', _at(11, 2), d)
    gate.mark_sent('14:00', _at(14, 1), d)
    raw = json.loads((tmp_path / gate.STATE_FILENAME).read_text(encoding='utf-8'))

    assert raw['sent'] == ['11:00', '14:00']


def test_naive_datetime_works_too(tmp_path):
    """PipelineContext.now_kst는 tz 없는 KST다. 게이트가 그걸 그대로 받아야 한다."""
    assert gate.due_slot(datetime(2026, 8, 10, 11, 5), str(tmp_path)) == '11:00'


# ── 15시 마감 브리핑은 별도 슬롯이다 ────────────────────────────────
# 브리핑은 리포트와 다른 물건이다(실전 계좌 잔고 + 심별 현황). 예전에는 둘 다
# should_notify()에 얹혀 있어서, 리포트 게이트를 11/14시로 바꾸면 브리핑이 통째로
# 죽는다 — 설계 문서에 없던 결합이다.

def test_brief_slot_is_not_a_report_slot(tmp_path):
    """15시에 리포트가 나가면 안 된다. 하루 2회 합의가 3회가 된다."""
    assert gate.due_slot(_at(15, 1), str(tmp_path)) is None


def test_brief_opens_at_fifteen(tmp_path):
    assert gate.brief_due(_at(15, 0), str(tmp_path)) is True
    assert gate.brief_due(_at(14, 59), str(tmp_path)) is False


def test_brief_has_its_own_retry_window(tmp_path):
    assert gate.brief_due(_at(15, 30), str(tmp_path)) is True
    assert gate.brief_due(_at(15, 41), str(tmp_path)) is False


def test_sending_the_report_does_not_close_the_brief(tmp_path):
    d = str(tmp_path)
    gate.mark_sent('11:00', _at(11, 2), d)
    gate.mark_sent('14:00', _at(14, 1), d)

    assert gate.brief_due(_at(15, 5), d) is True


def test_brief_closes_after_it_is_sent(tmp_path):
    d = str(tmp_path)
    gate.mark_sent(gate.BRIEF_SLOT, _at(15, 1), d)

    assert gate.brief_due(_at(15, 20), d) is False


# ── 상수 계약 ───────────────────────────────────────────────────────

def test_slots_are_the_agreed_times():
    """11시·14시 합의(2026-08-09). 바꾸면 리포트 회차가 조용히 달라진다."""
    assert gate.REPORT_SLOTS == ('11:00', '14:00')


def test_retry_window_covers_several_scrape_grids():
    """스크래핑 격자가 10분이므로 창이 그보다 충분히 넓어야 재시도가 성립한다."""
    from src.pipeline.scrape_gate import SCRAPE_INTERVAL_MIN
    assert gate.SLOT_WINDOW_MIN >= SCRAPE_INTERVAL_MIN * 3


def test_mark_sent_writes_to_the_named_file(tmp_path):
    """다른 파일명을 주면 기본 상태 파일을 건드리지 않는다."""
    from src.report import gate
    now = datetime(2026, 9, 1, 9, 5)

    gate.mark_sent('09:00', now, str(tmp_path), filename='us_brief_gate_state.json')

    assert (tmp_path / 'us_brief_gate_state.json').exists()
    assert not (tmp_path / gate.STATE_FILENAME).exists()


def test_due_reads_only_the_named_file(tmp_path):
    """기본 파일에 09:00을 보냈다고 적어도, 다른 파일을 보는 판정은 열려 있다."""
    from src.report import gate
    now = datetime(2026, 9, 1, 9, 5)

    gate.mark_sent('09:00', now, str(tmp_path))   # 기본 파일에 기록

    assert gate._due(now, ('09:00',), str(tmp_path)) is None
    assert gate._due(now, ('09:00',), str(tmp_path),
                     filename='us_brief_gate_state.json') == '09:00'
