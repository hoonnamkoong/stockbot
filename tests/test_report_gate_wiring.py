"""브리핑 발송 배선 — 슬롯은 **성공했을 때만** 닫힌다.

왜 슬롯 상태인가: 예전 판정은 `PipelineContext.should_notify()`의 "파이썬 시작
분이 0~2인가" 하나였다. 그 값은 디스패치 + 큐 대기 + 셋업(약 50초) 뒤의 시각이라
런마다 몇 초씩 흔들린다. 2026-08-07에 격자가 밀리면서 정각 발송이 하루 7회에서
3회로 줄었다 — 57% 누락인데 워크플로는 내내 초록색이었다. 하루 2회가 되면 한 번
놓치는 게 50% 손실이라, 판정을 분 창이 아니라 슬롯 상태로 바꿨다.

그 설계는 닫는 쪽에도 조건을 건다. 실패한 발송을 '보냈다'로 적으면 40분 창이
있어도 재시도가 사라지고 그날 회차가 통째로 없어진다.

여기서 지키는 것 둘 —
  ① 발송에 **성공했을 때만** 슬롯을 닫는가
  ② 실패하면 창 안에서 다시 열려 있는가

(2026-08-31: 11:00·14:00 리포트 슬롯은 폐기됐다. 이 배선을 쓰는 발송 경로는
브리핑 하나만 남았다.)
"""
import os
import sys
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.context import PipelineContext  # noqa: E402
from src.report import gate  # noqa: E402

BRIEF_AT = datetime(2026, 8, 10, 12, 5)


def _ctx(now, data_dir, event='workflow_dispatch'):
    c = PipelineContext.__new__(PipelineContext)
    c.now_kst = now
    c.github_event = event
    c.today_str = now.strftime('%Y%m%d')
    c._report_data_dir = data_dir
    return c


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


def _notifier(tmp_path, tg):
    from src.pipeline.workers.notifier import NotifierWorker
    w = NotifierWorker.__new__(NotifierWorker)
    w.ctx = _ctx(BRIEF_AT, str(tmp_path))
    w.storage = mock.MagicMock()
    w.tg = tg
    w._aggregate_multi_day = lambda *a, **k: None
    w._run_trade_executor = lambda *a, **k: None
    return w


def _fake_balance():
    return {'deposit': 0, 'holdings': []}


def test_a_successful_send_closes_the_slot(tmp_path, monkeypatch):
    monkeypatch.setattr('src.trade.balance.get_balance', _fake_balance)
    w = _notifier(tmp_path, _Tg(ok=True))
    w.run(all_stocks=[], simulation_results=[], sync_state=mock.MagicMock())

    assert gate.brief_due(datetime(2026, 8, 10, 12, 20), str(tmp_path)) is None


def test_a_failed_send_leaves_the_slot_open_for_retry(tmp_path, monkeypatch):
    """이게 40분 창을 만든 이유다. 실패를 '보냈다'로 적으면 그날 회차가 사라진다."""
    monkeypatch.setattr('src.trade.balance.get_balance', _fake_balance)
    w = _notifier(tmp_path, _Tg(ok=False))
    w.run(all_stocks=[], simulation_results=[], sync_state=mock.MagicMock())

    assert gate.brief_due(datetime(2026, 8, 10, 12, 20), str(tmp_path)) == '12:00'
