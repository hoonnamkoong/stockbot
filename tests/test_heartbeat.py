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


# ── 멎은 원인을 가른다 (2026-11-27) ───────────────────────────────
# 2026-11-26 장중에 `🫀 매매 루프가 멎었습니다 / 마지막 완주: 없음`이 30분마다 왔다.
# 경보는 **참**이었다(장중 200런 중 성공 2건). 그런데 메시지는 "trading.yml이 장중인데
# 트리거를 못 받고 있습니다. 태스커(폰) → /api/cron 경로를 확인하세요"였고,
# **트리거는 2분 간격으로 정확히 도착하고 있었다**(createdAt 00:00:09 / 00:02:08 /
# 00:04:06 …). 런은 생성됐고 예산을 넘겨 전부 취소됐다.
#
# 런이 0건인 것과, 런은 도는데 완주가 0건인 것은 **원인도 고칠 곳도 전혀 다르다**.
# 전자는 태스커, 후자는 잡 예산이다. 판정에 필요한 정보(런 목록)는 이미 손에 있다.

def _run(minutes_ago, conclusion, now=None):
    now = now or dt.datetime(2026, 11, 26, 11, 0, tzinfo=heartbeat._KST)
    ts = (now - dt.timedelta(minutes=minutes_ago)).astimezone(dt.timezone.utc)
    return {'created_at': ts.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'conclusion': conclusion}


_NOW = dt.datetime(2026, 11, 26, 11, 0, tzinfo=heartbeat._KST)


def test_창_안에_런이_없으면_트리거_미도착():
    """태스커가 멈춘 모양. 2026-11-05~10 전체 정지가 이것이었다."""
    runs = [_run(40, 'success'), _run(60, 'success')]
    assert heartbeat.stale_cause(runs, _NOW) == heartbeat.TRIGGER_MISSING


def test_런은_도는데_전부_취소면_예산_초과():
    """2026-11-26의 실제 모양 — 2분마다 생성되고 3분 예산에 잘렸다."""
    runs = [_run(m, 'cancelled') for m in (2, 4, 6, 8, 10, 12)]
    assert heartbeat.stale_cause(runs, _NOW) == heartbeat.RUNS_CUT


def test_런은_도는데_전부_실패면_실패():
    runs = [_run(m, 'failure') for m in (2, 4, 6, 8)]
    assert heartbeat.stale_cause(runs, _NOW) == heartbeat.RUNS_FAILED


def test_생성됐지만_아무것도_안_끝났으면_정체():
    """conclusion이 없는 런만 있는 경우 — 큐에 박혔거나 전부 진행 중이다."""
    runs = [_run(m, None) for m in (2, 4, 6)]
    assert heartbeat.stale_cause(runs, _NOW) == heartbeat.RUNS_STUCK


def test_섞여_있으면_단정하지_않는다():
    """원인을 모를 때 아는 척하면 지금 고장의 재현이다."""
    runs = [_run(2, 'cancelled'), _run(4, 'failure')]
    assert heartbeat.stale_cause(runs, _NOW) == heartbeat.RUNS_MIXED


def test_창_밖_런은_세지_않는다():
    """40분 전 취소는 지금 멎은 원인이 아니다."""
    runs = [_run(40, 'cancelled'), _run(50, 'cancelled')]
    assert heartbeat.stale_cause(runs, _NOW) == heartbeat.TRIGGER_MISSING


def test_원인마다_지시문이_다르다():
    """같은 문구를 쓰면 가른 의미가 없다 — 그게 2026-11-26에 사람을 폰으로 보냈다."""
    texts = {c: heartbeat.stale_hint(c) for c in (
        heartbeat.TRIGGER_MISSING, heartbeat.RUNS_CUT,
        heartbeat.RUNS_FAILED, heartbeat.RUNS_STUCK, heartbeat.RUNS_MIXED)}
    assert len(set(texts.values())) == len(texts), f'중복 지시문: {texts}'
    # 트리거 미도착에만 태스커가 나와야 한다.
    assert '태스커' in texts[heartbeat.TRIGGER_MISSING]
    for c in (heartbeat.RUNS_CUT, heartbeat.RUNS_FAILED, heartbeat.RUNS_STUCK):
        assert '태스커' not in texts[c], f'{c}가 태스커를 지목한다'


def test_알림_본문이_원인을_담는다(monkeypatch):
    """11-26 재현: 런이 2분마다 도는데 전부 취소 → 태스커를 지목해선 안 된다."""
    import scripts.check_heartbeat as chk

    sent = []
    monkeypatch.setattr(chk.alerts, 'send_alert', lambda m, log=None: sent.append(m))
    monkeypatch.setattr(chk, 'fetch_runs',
                        lambda log=None: [_run(m, 'cancelled') for m in (2, 4, 6, 8)])
    monkeypatch.setattr(chk, 'load_calendar', lambda: {})
    monkeypatch.setattr(chk, 'lookup', lambda c, d: True)
    monkeypatch.setattr(chk.dt, 'datetime', _FrozenNow)

    chk.main(log=lambda *a: None)
    assert sent, '장중에 멎었으면 알림이 나가야 한다'
    body = sent[0]
    assert '태스커' not in body, f'런이 도는데 태스커를 지목한다: {body}'
    assert '예산' in body or '취소' in body, f'원인이 안 담겼다: {body}'


class _FrozenNow(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return _NOW if tz else _NOW.replace(tzinfo=None)


def test_창은_상한도_본다():
    """하한만 보면 창이 'cutoff 이후 전부'가 된다.

    2026-11-26 11:00 시점으로 리허설했더니 15분 창에 **442건**이 들어와
    판정이 runs_mixed로 뒤집혔다(정답은 runs_cut). 운영에서는 now가 실시간이라
    티가 안 나고, 그래서 틀린 채로 오래 살 수 있는 모양이다.
    """
    runs = [_run(2, 'cancelled'), _run(-30, 'success')]  # 음수 = 미래
    recent = heartbeat.runs_within(runs, _NOW)
    assert len(recent) == 1, f'미래 런이 창에 들어왔다: {len(recent)}건'
    assert heartbeat.stale_cause(runs, _NOW) == heartbeat.RUNS_CUT
