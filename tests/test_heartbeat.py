"""매매 루프의 생존 신호 — 세션이 아니라 **분** 단위로 잰다.

지금 감시는 전부 세션 단위다(config/data_freshness.yaml의 max_age_sessions,
하루 1~2회 실행). 그래서 09:05에 루프가 멈추면 **그 세션이 통째로 끝난 뒤에야**
결손으로 잡힌다. 오늘도 그 공백이 있었고(2026-09-02 07시대 트리거 한 시간 실종은
어떤 실패 목록에도 안 떴다), 상주 워커로 옮기면 이 공백이 그대로 최대 위험이 된다
— 상주 구조의 고장은 "사이클 하나가 빠졌다"가 아니라 "죽었고 아무도 모른다"라서
범위가 열리기 때문이다.

판정을 순수 함수로 빼는 이유는 이 레포가 두 번 배운 것이다(window_state,
should_reconnect). 루프와 알림 사이에 섞여 있으면 아무도 테스트하지 않고,
그래서 도달 불가가 돼도 모른다.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src import heartbeat  # noqa: E402

_KST = dt.timezone(dt.timedelta(hours=9))


def kst(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=_KST)


# 2026-09-07은 월요일.
OPEN = kst(2026, 9, 7, 10, 30)      # 장중
AFTER_CLOSE = kst(2026, 9, 7, 16, 30)


def test_장중에_하트비트가_임계를_넘으면_stale():
    beat = OPEN - dt.timedelta(minutes=heartbeat.MAX_AGE_MIN + 1)
    assert heartbeat.judge(OPEN, beat, trading_day=True) == heartbeat.STALE


def test_장중에_방금_뛰었으면_ok():
    beat = OPEN - dt.timedelta(minutes=2)
    assert heartbeat.judge(OPEN, beat, trading_day=True) == heartbeat.OK


def test_장_마감_뒤에는_낡아도_알리지_않는다():
    """루프는 장 밖에서 안 돈다 — 그때의 '낡음'은 정상이다."""
    beat = AFTER_CLOSE - dt.timedelta(hours=3)
    assert heartbeat.judge(AFTER_CLOSE, beat, trading_day=True) == heartbeat.OFF_SESSION


def test_휴장일에는_알리지_않는다():
    beat = OPEN - dt.timedelta(days=3)
    assert heartbeat.judge(OPEN, beat, trading_day=False) == heartbeat.OFF_SESSION


def test_거래일_판정_불가는_stale로_뭉개지_않는다():
    """달력을 모르는 것과 루프가 죽은 것은 다르다.

    뭉개면 공휴일마다 거짓 경보가 나가고, 도배는 침묵과 같다. 반대로 stale을
    unknown으로 뭉개면 진짜 죽음을 놓친다. 그래서 세 번째 값으로 남긴다.
    """
    beat = OPEN - dt.timedelta(hours=5)
    assert heartbeat.judge(OPEN, beat, trading_day=None) == heartbeat.UNKNOWN


def test_장중인데_하트비트가_아예_없으면_stale():
    """폰이 아침에 아예 안 깬 경우 — 상주 워커에서 가장 중요한 케이스다.

    '오늘 한 번은 뛰었다'를 전제로 낡음만 재면 이 경우가 통째로 빠진다.
    """
    assert heartbeat.judge(OPEN, None, trading_day=True) == heartbeat.STALE


# ── 런 이력에서 생존 시각 꺼내기 ──────────────────────────────────
# 상주 워커가 생기기 전까지 매매 루프의 생존 증거는 trading.yml의 런 이력이다.
# 워커로 옮긴 뒤에는 beat_at의 출처만 바뀌고 judge()는 그대로 쓴다.

def test_가장_최근_성공_런의_완료시각을_KST로_준다():
    runs = [{'conclusion': 'success', 'updated_at': '2026-09-07T01:00:00Z'},
            {'conclusion': 'success', 'updated_at': '2026-09-07T00:40:00Z'}]
    assert heartbeat.last_success_at(runs) == kst(2026, 9, 7, 10, 0)


def test_실패한_런은_생존_신호가_아니다():
    """빨간 런은 '돌긴 돌았다'이지 '한 바퀴를 마쳤다'가 아니다.

    이걸 세면 루프가 매번 죽고 있는데도 하트비트가 초록으로 보인다 —
    실패 알림과 생존 감시가 같은 고장을 서로 미루게 된다.
    """
    runs = [{'conclusion': 'failure', 'updated_at': '2026-09-07T01:20:00Z'},
            {'conclusion': 'success', 'updated_at': '2026-09-07T01:00:00Z'}]
    assert heartbeat.last_success_at(runs) == kst(2026, 9, 7, 10, 0)


def test_진행중인_런은_아직_생존_신호가_아니다():
    """conclusion이 없으면 아직 한 바퀴를 안 끝냈다."""
    runs = [{'conclusion': None, 'updated_at': '2026-09-07T01:20:00Z'},
            {'conclusion': 'success', 'updated_at': '2026-09-07T01:00:00Z'}]
    assert heartbeat.last_success_at(runs) == kst(2026, 9, 7, 10, 0)


def test_성공한_런이_하나도_없으면_None():
    """'모른다'를 '방금 돌았다'로 폴백하지 않는다."""
    assert heartbeat.last_success_at([{'conclusion': 'failure',
                                       'updated_at': '2026-09-07T01:20:00Z'}]) is None
    assert heartbeat.last_success_at([]) is None


# ── 감시 스크립트 배선 ─────────────────────────────────────────────
# 판정이 맞아도 알림이 나갈 수 없으면 감시가 없는 것과 같다. 이 레포는 그 모양을
# 이미 겪었다 — weekly_report가 GMAIL_PASSWORD(없는 시크릿)를 넘기며 5개월간
# 정상 종료했다. 그래서 "stale이면 실제로 send_alert가 불린다"를 못박는다.

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import check_heartbeat as chk  # noqa: E402


def _wire(monkeypatch, runs, now, trading_day=True):
    sent = []
    monkeypatch.setattr(chk, 'fetch_runs', lambda log=print: runs)
    monkeypatch.setattr(chk, 'load_calendar', lambda: {})
    monkeypatch.setattr(chk, 'lookup', lambda days, ymd: trading_day)
    monkeypatch.setattr(chk.alerts, 'send_alert',
                        lambda text, log=print: sent.append(text))

    class _Now(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return now
    monkeypatch.setattr(chk.dt, 'datetime', _Now)
    return sent


def test_장중에_멎어_있으면_실제로_알림이_나간다(monkeypatch):
    runs = [{'conclusion': 'success', 'updated_at': '2026-09-07T00:10:00Z'}]
    sent = _wire(monkeypatch, runs, now=kst(2026, 9, 7, 10, 30))

    assert chk.main(log=lambda *a: None) == 0
    assert len(sent) == 1
    assert '09:10' in sent[0], f'마지막 완주 시각이 본문에 없다: {sent[0]}'


def test_장_밖에서는_알림이_나가지_않는다(monkeypatch):
    runs = [{'conclusion': 'success', 'updated_at': '2026-09-04T14:58:00Z'}]
    sent = _wire(monkeypatch, runs, now=kst(2026, 9, 6, 18, 41))

    assert chk.main(log=lambda *a: None) == 0
    assert sent == []


def test_조회_실패는_알림이_아니라_실패로_끝난다(monkeypatch):
    """측정 불가를 '루프가 죽었다'로 알리면 API 장애마다 거짓 경보가 나간다."""
    sent = _wire(monkeypatch, None, now=kst(2026, 9, 7, 10, 30))

    assert chk.main(log=lambda *a: None) == 1
    assert sent == []
