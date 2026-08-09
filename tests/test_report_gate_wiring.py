"""발송 게이트 배선 — 슬롯 판정이 리포트 경로 전체에서 한 값이어야 한다.

should_notify()는 여섯 곳에서 쓰인다(딥다이브 생성, 매도 후보 선정, 보고 종목
상태 기록, 발송, 브리핑, reported_codes 갱신). 이들이 한 런 안에서 서로 다른
답을 받으면, 예를 들어 "딥다이브는 만들었는데 발송은 안 하는" 사이클이 생긴다.

여기서 지키는 것 셋 —
  ① should_notify()가 리포트 슬롯 판정과 정확히 같은 값인가
  ② 발송에 **성공했을 때만** 슬롯을 닫는가(실패하면 창 안에서 재시도돼야 한다)
  ③ 슬롯을 닫은 뒤에도 그 런의 나머지 후속 처리가 계속 도는가
"""
import os
import sys
from datetime import datetime
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.context import PipelineContext  # noqa: E402
from src.report import gate  # noqa: E402


def _ctx(now, data_dir, event='workflow_dispatch'):
    c = PipelineContext.__new__(PipelineContext)
    c.now_kst = now
    c.github_event = event
    c.today_str = now.strftime('%Y%m%d')
    c._report_data_dir = data_dir
    return c


# ── ① should_notify는 슬롯 판정이다 ─────────────────────────────────

@pytest.mark.parametrize('h,m,expected', [
    (10, 59, False),
    (11, 0, True),
    (11, 35, True),    # 분 창이 아니라 슬롯이다 — 예전 게이트는 여기서 False였다
    (11, 41, False),
    (12, 30, False),
    (14, 5, True),
    (15, 1, False),    # 15시는 브리핑 슬롯이지 리포트 슬롯이 아니다
])
def test_should_notify_follows_the_slot(tmp_path, h, m, expected):
    ctx = _ctx(datetime(2026, 8, 10, h, m), str(tmp_path))
    assert ctx.should_notify() is expected


def test_minute_zero_is_no_longer_special(tmp_path):
    """예전 게이트의 전부였던 '분이 0~2'가 이제 아무 의미도 없어야 한다.
    09:00 정각에 리포트가 나가면 하루 2회 합의가 깨진다."""
    assert _ctx(datetime(2026, 8, 10, 9, 1), str(tmp_path)).should_notify() is False


def test_push_event_still_never_notifies(tmp_path):
    ctx = _ctx(datetime(2026, 8, 10, 11, 5), str(tmp_path), event='push')
    assert ctx.should_notify() is False


def test_closing_the_slot_closes_should_notify(tmp_path):
    d = str(tmp_path)
    ctx = _ctx(datetime(2026, 8, 10, 11, 5), d)
    assert ctx.should_notify() is True

    gate.mark_sent('11:00', ctx.now_kst, d)

    assert _ctx(datetime(2026, 8, 10, 11, 15), d).should_notify() is False


# ── ② 성공했을 때만 닫는다 ──────────────────────────────────────────

class _Tg:
    """TelegramManager 스텁. send_message 성공 여부만 통제한다."""

    def __init__(self, ok=True):
        self.ok = ok
        self.sent = []

    def send_message(self, text, parse_mode='HTML'):
        if not self.ok:
            raise RuntimeError('텔레그램 다운')
        self.sent.append(text)
        return True

    def send_dashboard_link(self):
        return self.send_message('dashboard')

    def send_market_report(self, name, rows):
        return self.send_message(f'{name} {len(rows)}')


def _notifier(tmp_path, tg):
    from src.pipeline.workers.notifier import NotifierWorker
    w = NotifierWorker.__new__(NotifierWorker)
    w.ctx = _ctx(datetime(2026, 8, 10, 11, 5), str(tmp_path))
    w.storage = mock.MagicMock()
    w.tg = tg
    w._aggregate_multi_day = lambda *a, **k: None
    w._run_trade_executor = lambda *a, **k: None
    return w


def _sync_state():
    s = mock.MagicMock()
    s.reported_codes = []
    s.morning_complete = False
    s.afternoon_complete = False
    return s


def test_a_successful_send_closes_the_slot(tmp_path):
    w = _notifier(tmp_path, _Tg(ok=True))
    w.run(all_stocks=[], simulation_results=[], final_picks=[],
          deep_dive_report='리포트 본문', sync_state=_sync_state())

    assert gate.due_slot(datetime(2026, 8, 10, 11, 20), str(tmp_path)) is None


def test_a_failed_send_leaves_the_slot_open_for_retry(tmp_path):
    """이게 40분 창을 만든 이유다. 실패를 '보냈다'로 적으면 그날 회차가 사라진다."""
    w = _notifier(tmp_path, _Tg(ok=False))
    w.run(all_stocks=[], simulation_results=[], final_picks=[],
          deep_dive_report='리포트 본문', sync_state=_sync_state())

    assert gate.due_slot(datetime(2026, 8, 10, 11, 20), str(tmp_path)) == '11:00'


# ── ③ 슬롯을 닫아도 후속 처리는 돈다 ───────────────────────────────

def test_reported_codes_still_update_in_the_same_run(tmp_path):
    """슬롯을 발송 직후에 닫으면, 같은 run() 안의 뒤쪽 should_notify()가 False가
    되어 reported_codes 갱신이 조용히 건너뛰어진다. 한 번 잡아 쓰고 마지막에
    닫아야 한다."""
    w = _notifier(tmp_path, _Tg(ok=True))
    state = _sync_state()
    w.run(all_stocks=[{'code': '005930', 'name': '삼성전자'}],
          simulation_results=[], final_picks=[],
          deep_dive_report='리포트 본문', sync_state=state)

    assert state.reported_codes == ['005930'], '발송 런에서 보고 코드가 안 쌓였다'
