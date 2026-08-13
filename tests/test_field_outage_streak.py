"""전량 결손 알림이 '한 런의 blip'과 '몇 주째 죽은 측정'을 구분하게 만든다.

(tests/test_tick_power_probe.py를 대체한다. 그 파일이 지키던 `missing_field_alert`는
여기 `outage_alert`로 바뀌었다. 원래 배경: 2026-08-08에 diag 4,576행(7~8월)의
`tick_power`가 **전부 0**임이 드러났다 — 고유값 1개. 결손 경고는 `log_error`(=print)
라 GitHub Actions 로그에만 찍혔고 아무도 보지 않았다. 그래서 사람 경로가 생겼다.)

2026-08-13: KIS 연결이 한 런(14:50 스크래퍼) 동안만 60건 전부 connect timeout이
났다. 같은 시각 다른 러너의 trading 런은 KIS에 정상 도달했으므로 KIS 전면
장애가 아니라 그 러너의 egress가 죽은 것이다. 그 한 런 때문에 per·tick_power가
30/30 결손이 됐고, 알림이 두 건 나갔다.

원래 이 알림이 잡으려던 건 "tick_power가 7~8월 내내 0"이라는 **지속성** 문제인데,
판정은 그 런 하나의 missing==total만 봤다. 그래서 단발 사고가 사람을 깨웠다.

여기서 고정하는 것은 둘이다.
  1. 전량 결손이 **연속 N런** 이어질 때만 사람 경로로 올린다.
  2. 같은 사고로 죽은 여러 필드는 **한 건**으로 묶는다(per와 tick_power는
     엔드포인트가 달라도 같은 호스트라 항상 같이 죽는다).
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src import alerts
from src.pipeline.workers.data_fetcher import OUTAGE_ALERT_RUNS, outage_alert


# ── 연속 카운터 (src/alerts.py) ──────────────────────────────────────

def test_first_outage_is_one_run(tmp_path):
    assert alerts.bump_outage_streak('field_outage', True, data_dir=str(tmp_path)) == 1


def test_streak_accumulates_across_runs(tmp_path):
    """런마다 새 프로세스다. 카운터가 파일에 남아야 이어진다."""
    d = str(tmp_path)
    assert alerts.bump_outage_streak('field_outage', True, data_dir=d) == 1
    assert alerts.bump_outage_streak('field_outage', True, data_dir=d) == 2
    assert alerts.bump_outage_streak('field_outage', True, data_dir=d) == 3


def test_one_healthy_run_resets_the_streak(tmp_path):
    """08-13이 정확히 이 모양이다 — 결손 1런, 앞뒤 39런 정상."""
    d = str(tmp_path)
    alerts.bump_outage_streak('field_outage', True, data_dir=d)
    assert alerts.bump_outage_streak('field_outage', False, data_dir=d) == 0
    assert alerts.bump_outage_streak('field_outage', True, data_dir=d) == 1


def test_streak_shares_the_file_with_cooldowns_without_colliding(tmp_path, monkeypatch):
    """카운터를 쿨다운 기록과 같은 파일에 둔다(동기화 자리를 늘리지 않으려고).
    그러면 send_alert_once가 카운터를 '보낸 시각'으로 읽지 않아야 한다."""
    from datetime import datetime

    d = str(tmp_path)
    alerts.bump_outage_streak('field_outage', True, data_dir=d)

    sent = []
    monkeypatch.setattr(
        alerts, '_telegram_manager',
        lambda: type('M', (), {'send_message': lambda _s, t: sent.append(t) or True})())
    assert alerts.send_alert_once('some_key', '본문', datetime(2026, 8, 13, 14, 51),
                                  data_dir=d, log=lambda *_: None) is True

    raw = json.loads((tmp_path / alerts.STATE_FILENAME).read_text(encoding='utf-8'))
    assert raw[alerts.OUTAGE_STREAK_KEY] == {'field_outage': 1}
    assert isinstance(raw['some_key'], str)


def test_streak_marks_state_written_so_it_gets_deployed(tmp_path):
    """카운터는 **다음 런에** 보여야 뜻이 있다. 배포 목록이 이 신호로 정한다."""
    alerts._state_written = False
    alerts.bump_outage_streak('field_outage', True, data_dir=str(tmp_path))
    assert alerts.state_was_written() is True


def test_reset_on_healthy_run_does_not_rewrite_when_already_zero(tmp_path):
    """정상 런마다 파일을 건드리면, 그 배포가 다른 워크플로의 쿨다운 기록을
    런 시작 사본으로 되돌린다(lost update). 바뀔 게 없으면 쓰지 않는다."""
    alerts._state_written = False
    assert alerts.bump_outage_streak('field_outage', False, data_dir=str(tmp_path)) == 0
    assert alerts.state_was_written() is False


# ── 문구 조립 (src/pipeline/workers/data_fetcher.py) ─────────────────

_DOWN = [('per', 'Sim3 가치페어 밸류에이션 판정 불가'),
         ('tick_power', '체결강도 판정 불가')]


def test_single_bad_run_is_silent():
    """08-13의 실제 상황. 여기가 조용해지는 것이 이 변경의 목적이다."""
    assert outage_alert(_DOWN, streak=1, total=30) is None


def test_alerts_once_the_outage_persists():
    msg = outage_alert(_DOWN, streak=OUTAGE_ALERT_RUNS, total=30)

    assert msg is not None
    assert 'per' in msg and 'tick_power' in msg
    assert str(OUTAGE_ALERT_RUNS) in msg


def test_co_failing_fields_make_one_message():
    """per와 tick_power는 엔드포인트가 다르지만 같은 호스트라 같이 죽는다.
    필드별로 쪼개면 사고 하나에 사람이 두 번 깨어난다(08-13에 그랬다)."""
    msg = outage_alert(_DOWN, streak=OUTAGE_ALERT_RUNS, total=30)

    assert msg.count('<b>') == 1


def test_nothing_down_is_silent():
    assert outage_alert([], streak=OUTAGE_ALERT_RUNS, total=30) is None


def test_no_candidates_is_not_an_outage():
    """후보가 0개인 사이클은 결손률 0/0이다. '전량 결손'으로 읽으면 조용한
    날마다 알림이 나간다."""
    assert outage_alert(_DOWN, streak=OUTAGE_ALERT_RUNS, total=0) is None
