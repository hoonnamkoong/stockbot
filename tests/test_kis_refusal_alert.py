"""KIS가 엔드포인트를 끊으면 사람에게 알린다.

2026-11-11 16:00에 KIS가 국내주식 종목분석 API 7종을 막았다. `financial-ratio`
(FHKST66430300)가 404가 되고, 그걸 먹던 심3(TTM PER/PBR)·심11(EPS 성장률)이
**13일간** 모든 후보를 탈락시켰다. 아무도 몰랐다.

계측은 있었다 — `reject_counts`가 세고 EOD 로그가 `KIS 거부: FHKST66430300
HTTP 404×295`를 매일 찍었다. 없던 것은 **발화**다. 기존 가드
(`sim11_fetch_problems`)의 세 조건이 전부 이걸 비껴갔다:

  - `skipped_budget`     → 0
  - `failed / target`    → **failed가 0이다.** `get_earnings_growth`가 빈손으로
                            와도 후보는 그대로 만들어진다(성장률 키만 빠진다).
                            그 후보는 나중에 `no_eps` 게이트에서 조용히 죽는다.
  - 유량제한             → `EGW00201`만 센다. 우리 건 `HTTP 404`였다.

그리고 산출물 신선도로도 안 잡힌다 — `sim11_watchlist.json`은 비어 있어도
(`{"entries": {}}`, 35바이트) 매일 갱신되므로 초록이다.

그래서 분모를 가진 기제를 둔다: **tr_id별 조회 시도 대 거부**. 295번 시도해서
295번 거부당했으면 100%이고, 종목 하나가 결손인 것과는 섞이지 않는다.
깔때기(하류)로 재지 않는 이유는 분모가 모호해서다 — `no_eps 10`은 후보 295 중
3.4%지만 그 게이트에 도달한 10건 중에서는 100%다.
"""
import datetime
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src import alerts
from src.trade.kis_data_provider import KISDataProvider

NOW = datetime.datetime(2026, 11, 24, 16, 30)


class _Res:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        if self._payload is None:
            raise ValueError('not json')
        return self._payload


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(KISDataProvider, '_init_auth', lambda self: None)
    KISDataProvider.reject_counts.clear()
    KISDataProvider.attempt_counts.clear()
    KISDataProvider._logged_rejects.clear()
    KISDataProvider._conn_fail_streak = 0
    p = KISDataProvider()
    p._token = 'tok'
    p._base_url = 'https://openapi.example'
    p._app_key = 'k'
    p._app_secret = 's'
    return p


# ── 분모: 시도 횟수 ────────────────────────────────────────────────────────

def test_시도_횟수를_tr_id별로_센다(provider, monkeypatch):
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Res({'rt_cd': '0'}))
    for _ in range(3):
        provider._get('/p', 'TR_A', {})
    provider._get('/p', 'TR_B', {})
    assert KISDataProvider.attempt_counts['TR_A'] == 3
    assert KISDataProvider.attempt_counts['TR_B'] == 1


def test_거부도_시도로_센다(provider, monkeypatch):
    """거부는 '시도하지 않은 것'이 아니다. 분모에서 빠지면 비율이 영원히 0이다."""
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Res(None, status=404))
    for _ in range(5):
        provider._get('/p', 'TR_DEAD', {})
    assert KISDataProvider.attempt_counts['TR_DEAD'] == 5
    assert sum(n for (tr, _c), n in KISDataProvider.reject_counts.items()
               if tr == 'TR_DEAD') == 5


def test_토큰이_없으면_시도로_세지_않는다(provider, monkeypatch):
    """네트워크에 나가지도 않았다. 이걸 시도로 세면 설정 오류가 KIS 장애로 보인다."""
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Res({'rt_cd': '0'}))
    provider._token = None
    provider._get('/p', 'TR_A', {})
    assert KISDataProvider.attempt_counts['TR_A'] == 0


def test_차단기가_걸려_있으면_시도로_세지_않는다(provider, monkeypatch):
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Res({'rt_cd': '0'}))
    KISDataProvider._conn_fail_streak = KISDataProvider.CONN_BREAKER_STREAK
    try:
        provider._get('/p', 'TR_A', {})
        assert KISDataProvider.attempt_counts['TR_A'] == 0
    finally:
        KISDataProvider._conn_fail_streak = 0


def test_재시도는_시도를_한_번만_센다(provider, monkeypatch):
    """한 종목의 한 조회가 재시도로 3콜이 되어도 '조회 1건'이다 —
    분모가 재시도 횟수에 따라 늘면 비율이 희석돼 발화가 늦는다."""
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError('down')
    monkeypatch.setattr(requests, 'get', boom)
    monkeypatch.setattr(KISDataProvider, 'RETRY_BACKOFF_SEC', 0)
    provider._get('/p', 'TR_A', {})
    assert KISDataProvider.attempt_counts['TR_A'] == 1


# ── 발화 ──────────────────────────────────────────────────────────────────

def _fired(monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, 'send_alert_once',
                        lambda key, text, now, **kw: sent.append((key, text)) or True)
    return sent


def test_전량_거부면_알린다(monkeypatch):
    sent = _fired(monkeypatch)
    alerts.notify_kis_refusals({'FHKST66430300': 295},
                               {('FHKST66430300', 'HTTP 404'): 295}, now=NOW)
    assert len(sent) == 1
    key, text = sent[0]
    assert 'FHKST66430300' in key
    assert 'FHKST66430300' in text and '404' in text
    assert '295' in text


def test_종목_몇_개_결손은_알리지_않는다(monkeypatch):
    """결손은 늘 조금씩 있다. 조금에 울리는 알림은 아무도 안 본다."""
    sent = _fired(monkeypatch)
    alerts.notify_kis_refusals({'FHKST66430300': 295},
                               {('FHKST66430300', 'HTTP 500'): 3}, now=NOW)
    assert sent == []


def test_표본이_작으면_알리지_않는다(monkeypatch):
    """2번 시도해서 2번 거부당한 것으로는 엔드포인트 사망을 말할 수 없다."""
    sent = _fired(monkeypatch)
    alerts.notify_kis_refusals({'TR_X': 2}, {('TR_X', 'HTTP 404'): 2}, now=NOW)
    assert sent == []


def test_거부가_없으면_알리지_않는다(monkeypatch):
    sent = _fired(monkeypatch)
    alerts.notify_kis_refusals({'TR_X': 300}, {}, now=NOW)
    assert sent == []


def test_tr_id별로_따로_알린다(monkeypatch):
    """하나가 죽었는데 다른 하나의 정상 호출에 비율이 희석되면 안 된다."""
    sent = _fired(monkeypatch)
    alerts.notify_kis_refusals(
        {'TR_DEAD': 295, 'TR_OK': 295},
        {('TR_DEAD', 'HTTP 404'): 295, ('TR_OK', 'HTTP 500'): 1}, now=NOW)
    assert len(sent) == 1
    assert 'TR_DEAD' in sent[0][0]


def test_시도_기록이_없는_tr은_알리지_않는다(monkeypatch):
    """거부만 있고 분모가 없으면 비율을 못 낸다. 0으로 나누거나 지어내지 않는다."""
    sent = _fired(monkeypatch)
    alerts.notify_kis_refusals({}, {('TR_X', 'HTTP 404'): 295}, now=NOW)
    assert sent == []


def test_사유_코드를_본문에_싣는다(monkeypatch):
    """HTTP 404(경로 사망)와 EGW00123(appkey 불일치)은 고치는 곳이 다르다."""
    sent = _fired(monkeypatch)
    alerts.notify_kis_refusals({'TR_X': 100}, {('TR_X', 'EGW00123'): 100}, now=NOW)
    assert 'EGW00123' in sent[0][1]


# ── 배선 ──────────────────────────────────────────────────────────────────
#
# 발화 함수가 있어도 아무도 부르지 않으면 13일 침묵이 그대로다. 호출부가
# 사라지면 테스트가 빨개져야 한다.

def _src(rel):
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    with open(os.path.join(root, rel), encoding='utf-8') as f:
        return f.read()


@pytest.mark.parametrize('path', ['scripts/trade_loop.py', 'scripts/run_eod_sims.py'])
def test_두_경로가_모두_거부율을_점검한다(path):
    """장중(심3)과 EOD(심11)는 다른 워크플로다. 한쪽만 배선하면 다른 쪽이 침묵한다."""
    assert 'notify_kis_refusals' in _src(path), f'{path}에 배선이 없다'


def test_장중_점검이_쿨다운_배포_판정보다_앞에_있다():
    """순서가 뒤집히면 이 런이 쓴 쿨다운이 배포 목록에서 빠지고, 다음 런이
    백지에서 또 울린다 — 2분마다 도배된다."""
    s = _src('scripts/trade_loop.py')
    # 기준점은 **정상 경로 말미의 그 대입문**이다. 파일 앞쪽에도
    # `alerts.state_was_written()`이 하나 더 있는데(휴장 판정 불가 조기 return),
    # 그 경로는 KIS 조회를 하기 전에 끝나므로 보고할 거부가 애초에 없다.
    assert s.index('notify_kis_refusals') < s.index(
        'alerts_written = alerts.state_was_written()')
