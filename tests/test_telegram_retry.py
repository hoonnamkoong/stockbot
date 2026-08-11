import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import requests

from src.telegram_manager import TelegramManager


class _FakeResponse:
    """requests.Response 흉내. status가 4xx/5xx면 raise_for_status()가 던진다."""

    def __init__(self, status):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error")


@pytest.fixture
def tg():
    return TelegramManager(token='t', chat_id='c')


def _fake_post(responses, calls):
    """호출 순서대로 responses를 돌려주는 가짜 post. 호출 인자를 calls에 기록."""
    def post(url, json=None, timeout=None):
        calls.append(json)
        return responses[len(calls) - 1]
    return post


def test_retry_reports_failure_when_telegram_rejects_again(tg, monkeypatch):
    """토큰 만료(401)처럼 재시도해도 거부되는 경우를 성공으로 보고하면 안 된다.

    이 경로가 True를 돌려주면 호출부(마감 브리핑 등)의 발송 실패 감지가 통째로 무력화된다.
    """
    calls = []
    monkeypatch.setattr(requests, 'post',
                        _fake_post([_FakeResponse(401), _FakeResponse(401)], calls))

    assert tg.send_message('hi') is False
    assert len(calls) == 2                    # 1차 + 평문 재시도
    assert 'parse_mode' not in calls[1]       # 재시도는 서식을 뺀다


def test_retry_succeeds_when_plain_text_is_accepted(tg, monkeypatch):
    """서식 오류(400)로 거부된 뒤 평문 재시도가 통하면 성공이 맞다.

    재시도가 존재하는 원래 이유 — 종목명에 < 나 & 가 섞이면 텔레그램이 HTML 해석을 거부한다.
    """
    calls = []
    monkeypatch.setattr(requests, 'post',
                        _fake_post([_FakeResponse(400), _FakeResponse(200)], calls))

    assert tg.send_message('종목 <A> & <B>') is True
    assert len(calls) == 2
    assert 'parse_mode' not in calls[1]


def test_first_attempt_success_does_not_retry(tg, monkeypatch):
    calls = []
    monkeypatch.setattr(requests, 'post', _fake_post([_FakeResponse(200)], calls))

    assert tg.send_message('hi') is True
    assert len(calls) == 1
    assert calls[0]['parse_mode'] == 'HTML'


def test_network_failure_on_retry_reports_failure(tg, monkeypatch):
    """답장을 아예 못 받는 경우(타임아웃 등)는 원래도 실패로 잡혔다 — 회귀 방지."""
    calls = []

    def post(url, json=None, timeout=None):
        calls.append(json)
        raise requests.ConnectionError('unreachable')

    monkeypatch.setattr(requests, 'post', post)

    assert tg.send_message('hi') is False
    assert len(calls) == 2


# ── 4096자 상한 — [2026-08-11] 딥다이브가 5종목으로 늘며 실제로 넘을 수 있게 됨 ──

def test_short_message_is_sent_as_a_single_call(tg, monkeypatch):
    calls = []
    monkeypatch.setattr(requests, 'post', _fake_post([_FakeResponse(200)], calls))

    assert tg.send_message('짧은 메시지') is True
    assert len(calls) == 1


def test_long_message_is_split_into_multiple_calls(tg, monkeypatch):
    """상한을 넘는 메시지는 한 번에 안 보내고 문단 경계로 나눠 여러 번 보낸다."""
    paragraph = '가' * 2000
    long_text = f"{paragraph}\n\n{paragraph}\n\n{paragraph}"  # 6000+자, 3개 문단
    calls = []
    monkeypatch.setattr(requests, 'post',
                        _fake_post([_FakeResponse(200)] * 10, calls))

    ok = tg.send_message(long_text)

    assert ok is True
    assert len(calls) >= 2, '4096자 상한을 넘는데 한 번에 보내려 했다'
    for c in calls:
        assert len(c['text']) <= tg.TELEGRAM_SAFE_LEN


def test_one_failed_chunk_makes_the_whole_send_report_failure(tg, monkeypatch):
    """나눠 보낸 조각 중 하나라도 실패하면 전체를 성공으로 기록하면 안 된다 —
    안 그러면 일부 종목 리포트가 조용히 사라진다."""
    paragraph = '나' * 2000
    long_text = f"{paragraph}\n\n{paragraph}\n\n{paragraph}"
    calls = []
    # 첫 조각 성공, 나머지는 재시도까지 전부 401
    responses = [_FakeResponse(200)] + [_FakeResponse(401)] * 10
    monkeypatch.setattr(requests, 'post', _fake_post(responses, calls))

    assert tg.send_message(long_text) is False


def test_split_into_chunks_keeps_each_chunk_under_limit():
    text = '\n\n'.join(['단락' * 100] * 5)  # 각 단락 400자, 5개
    chunks = TelegramManager._split_into_chunks(text, limit=1000)

    assert all(len(c) <= 1000 for c in chunks)
    # 원문의 모든 문단이 어딘가에는 남아있어야 한다(유실 없음)
    assert ''.join(chunks).replace('\n\n', '') == text.replace('\n\n', '')


def test_split_into_chunks_force_splits_a_single_oversized_paragraph():
    """문단 하나가 그 자체로 limit을 넘는 드문 경우도 유실 없이 잘라야 한다."""
    text = '다' * 5000  # 문단 하나, 구분자 없음
    chunks = TelegramManager._split_into_chunks(text, limit=2000)

    assert all(len(c) <= 2000 for c in chunks)
    assert ''.join(chunks) == text
