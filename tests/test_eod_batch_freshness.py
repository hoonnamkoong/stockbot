"""EOD 배치가 안 돌았으면 장중에 사람에게 알린다.

2026-08-27: eod_data.yml의 cron('0 7 * * 1-5')이 그날 한 번도 발화하지 않았다
(다른 cron은 정상 발화 — GitHub이 이 스케줄만 드롭했다). 심9-1·심11은 이 배치
안에서만 판단하므로 그날 판단 자체가 없었는데, 워크플로가 실패한 게 아니라
**아예 안 생겨서** Actions에도 빨간 X가 없었다. 아무도 몰랐다.

배치가 안 돈 걸 감지할 수 있는 자리는 그 다음 장중이다 — 심11 감시 목록의
날짜 키가 오늘 세션과 안 맞으면 전날 배치가 없었거나 실패한 것이다.
"""
import datetime as dt

from scripts.trade_loop import eod_batch_is_stale

_KST = dt.timezone(dt.timedelta(hours=9))


def _kst(y, mo, d, h, mi=0):
    return dt.datetime(y, mo, d, h, mi, tzinfo=_KST)


def test_watchlist_stamped_for_today_is_fresh():
    """전날 배치가 오늘 세션 키를 찍어 뒀으면 정상."""
    assert eod_batch_is_stale(_kst(2026, 8, 28, 10), '20260828') is False


def test_yesterdays_key_means_batch_never_ran():
    """오늘 세션 키가 아니라 어제 날짜면 어젯밤 배치가 없었다."""
    assert eod_batch_is_stale(_kst(2026, 8, 28, 10), '20260827') is True


def test_missing_watchlist_is_stale():
    """파일이 없거나 날짜를 못 읽어도 낡은 것과 같게 다룬다 — 읽을 게 없다."""
    assert eod_batch_is_stale(_kst(2026, 8, 28, 10), None) is True


def test_monday_reads_fridays_stamp_of_monday():
    """금요일 배치는 월요일 키를 찍는다 — 월요일 장중에 그게 오늘 키다."""
    assert eod_batch_is_stale(_kst(2026, 8, 31, 10), '20260831') is False


def test_future_key_is_not_stale():
    """앞선 키(장 마감 뒤 돈 배치를 그날 늦게 읽는 경우)는 장애가 아니다."""
    assert eod_batch_is_stale(_kst(2026, 8, 28, 10), '20260831') is False


# ── 알림 경로 ─────────────────────────────────────────
# 판정 함수만 테스트하면 알림 본문이 깨진 걸 못 잡는다. warn_if_eod_batch_stale은
# 통째로 try/except에 싸여 있어, 본문 f-string이 NameError를 내도 "[경고] ...
# 점검 실패(무시)" 한 줄로 조용히 넘어간다 — 감지기 자체가 조용히 죽는다.

class _Ctx:
    def __init__(self, now, tmp):
        self.now_kst = now
        self.lines = []
        self.data_dir = str(tmp)

    def log(self, msg):
        self.lines.append(str(msg))


def _run_warn(tmp_path, monkeypatch, watchlist_payload):
    import json

    import scripts.trade_loop as tl
    from src.strategy.simulators import sim11_minervini as m

    wl = tmp_path / 'sim11_watchlist.json'
    if watchlist_payload is not None:
        wl.write_text(json.dumps(watchlist_payload), encoding='utf-8')
    monkeypatch.setattr(m, 'WATCHLIST_PATH', str(wl))

    sent = []
    monkeypatch.setattr(tl.alerts, 'send_alert_once',
                        lambda key, text, **kw: sent.append((key, text)) or True)
    ctx = _Ctx(_kst(2026, 8, 28, 10), tmp_path)
    tl.warn_if_eod_batch_stale(ctx)
    return ctx, sent


def test_stale_watchlist_sends_alert_with_readable_body(tmp_path, monkeypatch):
    ctx, sent = _run_warn(tmp_path, monkeypatch, {'date': '20260827', 'entries': {}})
    assert [k for k, _ in sent] == ['eod_batch_stale']
    body = sent[0][1]
    assert '20260827' in body and '20260828' in body
    assert '점검 실패' not in ' '.join(ctx.lines), (
        f'알림 본문 생성이 예외로 죽었다: {ctx.lines}')


def test_fresh_watchlist_sends_nothing(tmp_path, monkeypatch):
    _, sent = _run_warn(tmp_path, monkeypatch, {'date': '20260828', 'entries': {}})
    assert sent == []


def test_missing_watchlist_file_still_alerts(tmp_path, monkeypatch):
    _, sent = _run_warn(tmp_path, monkeypatch, None)
    assert [k for k, _ in sent] == ['eod_batch_stale']
