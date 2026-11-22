"""장애 알림(src/alerts.py) 테스트.

여기서 지키려는 것: "조용히 실패하지 않는다"와 "같은 장애로 2분마다 울리지
않는다"는 서로 반대 방향이라 둘 다 명시적으로 고정해 둔다.
"""
import json
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src import alerts


class _Spy:
    """TelegramManager 대역. 발송 시도를 기록한다."""

    def __init__(self, result=True):
        self.result = result
        self.sent = []

    def __call__(self):
        return self

    def send_message(self, text):
        self.sent.append(text)
        return self.result


@pytest.fixture
def spy(monkeypatch):
    s = _Spy()
    monkeypatch.setattr(alerts, '_telegram_manager', s)
    return s


def test_send_alert_prefixes_and_sends(spy):
    assert alerts.send_alert('원장 락을 빼앗겼습니다') is True
    assert len(spy.sent) == 1
    assert '원장 락을 빼앗겼습니다' in spy.sent[0]


def test_send_alert_reports_false_when_delivery_fails(monkeypatch):
    s = _Spy(result=False)
    monkeypatch.setattr(alerts, '_telegram_manager', s)
    assert alerts.send_alert('x') is False


def test_send_alert_never_raises(monkeypatch):
    """알림이 터져서 매매 경로를 죽이면 안 된다."""
    def boom():
        raise RuntimeError('telegram down')

    monkeypatch.setattr(alerts, '_telegram_manager', boom)
    assert alerts.send_alert('x') is False


def test_send_alert_once_suppresses_within_cooldown(spy, tmp_path):
    now = datetime(2026, 8, 10, 9, 0)
    assert alerts.send_alert_once('holiday', 'msg', now=now,
                                  cooldown_min=60, data_dir=str(tmp_path)) is True
    later = datetime(2026, 8, 10, 9, 2)
    assert alerts.send_alert_once('holiday', 'msg', now=later,
                                  cooldown_min=60, data_dir=str(tmp_path)) is False
    assert len(spy.sent) == 1


def test_send_alert_once_fires_again_after_cooldown(spy, tmp_path):
    alerts.send_alert_once('holiday', 'msg', now=datetime(2026, 8, 10, 9, 0),
                           cooldown_min=60, data_dir=str(tmp_path))
    alerts.send_alert_once('holiday', 'msg', now=datetime(2026, 8, 10, 10, 1),
                           cooldown_min=60, data_dir=str(tmp_path))
    assert len(spy.sent) == 2


def test_send_alert_once_keys_are_independent(spy, tmp_path):
    alerts.send_alert_once('a', 'msg', now=datetime(2026, 8, 10, 9, 0),
                           cooldown_min=60, data_dir=str(tmp_path))
    alerts.send_alert_once('b', 'msg', now=datetime(2026, 8, 10, 9, 0),
                           cooldown_min=60, data_dir=str(tmp_path))
    assert len(spy.sent) == 2


def test_send_alert_once_does_not_record_when_delivery_failed(monkeypatch, tmp_path):
    """못 보낸 알림을 '보냈다'로 적으면 장애가 통째로 묻힌다."""
    s = _Spy(result=False)
    monkeypatch.setattr(alerts, '_telegram_manager', s)
    alerts.send_alert_once('holiday', 'msg', now=datetime(2026, 8, 10, 9, 0),
                           cooldown_min=60, data_dir=str(tmp_path))
    s.result = True
    assert alerts.send_alert_once('holiday', 'msg', now=datetime(2026, 8, 10, 9, 2),
                                  cooldown_min=60, data_dir=str(tmp_path)) is True


def test_send_alert_once_survives_corrupt_state(spy, tmp_path):
    """상태 파일이 깨졌으면 '보낸 적 없다'로 읽는다 — 침묵보다 중복이 낫다."""
    path = tmp_path / alerts.STATE_FILENAME
    path.write_text('{ not json', encoding='utf-8')
    assert alerts.send_alert_once('holiday', 'msg', now=datetime(2026, 8, 10, 9, 0),
                                  cooldown_min=60, data_dir=str(tmp_path)) is True


def test_send_alert_once_state_is_json_readable(spy, tmp_path):
    alerts.send_alert_once('holiday', 'msg', now=datetime(2026, 8, 10, 9, 0),
                           cooldown_min=60, data_dir=str(tmp_path))
    raw = json.loads((tmp_path / alerts.STATE_FILENAME).read_text(encoding='utf-8'))
    assert raw['holiday'] == '2026-08-10T09:00:00'


# ── 정산 알림 ───────────────────────────────────────────────────────
# 정산은 realized_pnl → effective_budget → 실주문 크기다. 그 결과가 print로만
# 남아 출근한 사람에게 닿지 않았다. 본문에 금액이 실제로 들어가는지, 그리고
# 실패 알림이 2분마다 도배되지 않는지를 고정한다.

def test_정산_완료는_장애가_아니라_알림으로_간다(spy):
    assert alerts.notify_program_settled(
        5, -100000.0, -300000.0, 1000000,
        datetime(2026, 11, 23, 9, 2)) is True
    body, = spy.sent
    assert alerts.NOTICE_TITLE in body, '장애 머리글로 보내면 사람이 길들여진다'
    assert alerts.ALERT_TITLE not in body


def test_정산_완료_본문에_전후_금액과_주문기준이_있다(spy):
    alerts.notify_program_settled(5, -100000.0, -300000.0, 1000000,
                                  datetime(2026, 11, 23, 9, 2))
    body, = spy.sent
    assert '5건' in body
    assert '-100,000원' in body       # 전
    assert '-300,000원' in body        # 후
    assert '700,000원' in body         # 1,000,000 + (-300,000) = 다음 주문 기준


def test_정산_완료는_금액을_못_읽어도_지어내지_않는다(spy):
    alerts.notify_program_settled(1, None, 'x', None, datetime(2026, 11, 23, 9, 2))
    body, = spy.sent
    assert body.count('측정 불가') >= 2
    assert '0원' not in body


def test_정산_실패는_쿨다운으로_도배를_막는다(spy, tmp_path):
    now = datetime(2026, 11, 23, 9, 2)
    first = alerts.notify_program_settle_failed(
        2, ['[Program] 000111 확정 실현손익 조회 실패'], now, log=lambda *_: None)
    second = alerts.notify_program_settle_failed(
        2, ['[Program] 000111 확정 실현손익 조회 실패'], now, log=lambda *_: None)
    assert first is True and second is False, '2분마다 재시도되므로 억제가 필수다'
    assert len(spy.sent) == 1


def test_정산_실패_본문에_사유가_실린다(spy):
    alerts.notify_program_settle_failed(
        2, ['[Program] 000111 확정 실현손익 조회 실패',
            '[Program] 000222 수량이 맞는 매도를 특정하지 못했습니다'],
        datetime(2026, 11, 23, 9, 2), log=lambda *_: None)
    body, = spy.sent
    assert '2건' in body
    assert '조회 실패' in body and '수량' in body
    assert '[Program]' not in body, '텔레그램 본문에 로그 태그는 군더더기다'


def test_정산_실패는_사유가_없어도_보낸다(spy):
    alerts.notify_program_settle_failed(1, [], datetime(2026, 11, 23, 9, 2),
                                        log=lambda *_: None)
    body, = spy.sent
    assert '사유가 로그에 남지 않았습니다' in body
