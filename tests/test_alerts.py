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
