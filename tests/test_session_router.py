# -*- coding: utf-8 -*-
"""태스커 트리거 하나를 국내/미국으로 가르는 라우터 CLI.

trading.yml의 첫 스텝이 이걸 돌려 GITHUB_OUTPUT에 kr/us를 적고, 나머지 스텝이
`if:`로 그걸 읽는다. pip install **앞에서** 도는 스텝이라 표준 라이브러리만
써야 한다 — 여기서 requests를 끌어오면 장 밖 트리거(하루 200건 남짓)도
설치 비용을 문다.
"""
import datetime as dt
import subprocess
import sys
from unittest import mock

from scripts import session_router


def _utc(y, mo, d, h, mi):
    return dt.datetime(y, mo, d, h, mi, tzinfo=dt.timezone.utc)


def test_국내장중이면_kr만_참():
    # 2026-08-27(목) 01:00 UTC = 10:00 KST
    assert session_router.decide(_utc(2026, 8, 27, 1, 0)) == {'kr': True, 'us': False, 'eod': False}


def test_미국장중이면_us만_참():
    # 2026-08-27(목) 15:00 UTC = 11:00 EDT / 다음날 00:00 KST
    assert session_router.decide(_utc(2026, 8, 27, 15, 0)) == {'kr': False, 'us': True, 'eod': False}


def test_둘_다_아니면_둘_다_거짓():
    # 2026-08-27(목) 11:00 UTC = 20:00 KST — 국내 마감 뒤, 미국 개장 전
    assert session_router.decide(_utc(2026, 8, 27, 11, 0)) == {
        'kr': False, 'us': False, 'eod': False}


def test_마감_직후는_eod만_참():
    # 2026-08-27(목) 07:10 UTC = 16:10 KST
    assert session_router.decide(_utc(2026, 8, 27, 7, 10)) == {
        'kr': False, 'us': False, 'eod': True}


def test_출력은_github_output_형식():
    with mock.patch.object(session_router, 'decide',
                           return_value={'kr': True, 'us': False, 'eod': False}):
        lines = session_router.render()
    assert lines == 'kr=true\nus=false\neod=false'


def test_표준_라이브러리만_import한다():
    """pip install 앞에서 도는 스텝이다 — 서드파티가 섞이면 거기서 죽는다."""
    # 인터프리터가 기동만으로 들여온 것(.pth 등)은 뺀다 — 우리가 늘린 것만 본다.
    heavy = '("requests","yfinance","pandas","numpy","yaml","google","bs4","dotenv")'
    code = ('import sys; sys.path.insert(0, "."); '
            f'base={{m for m in sys.modules if m.split(".")[0] in {heavy}}}; '
            'import scripts.session_router, scripts.dispatch_us_trading, '
            'scripts.dispatch_eod_data; '
            f'now={{m for m in sys.modules if m.split(".")[0] in {heavy}}}; '
            'print(",".join(sorted(now - base)))')
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == '', f'서드파티 import: {out.stdout.strip()}'


# ── 태스커 창과의 결합 ──────────────────────────────────────────────
# 실제 설정: **월~토** 09:00~06:00 KST, 2분 간격. 요일이 월~금이 아니라 월~토인
# 게 핵심이다 — 금요일 미국장이 KST로 금 22:30~토 05:00(EST면 토 06:00)이라
# 월~금으로 걸면 금요일 세션을 통째로 놓친다.
#
# 라우터를 넓히거나(예: EOD 창을 18시로) 창을 좁히면 이 테스트가 깨진다.
TASKER_DAYS = range(6)          # 월(0)~토(5)
TASKER_FROM = (9, 0)
TASKER_TO = (6, 0)


def _tasker_on(t_kst):
    if t_kst.weekday() not in TASKER_DAYS:
        return False
    hm = (t_kst.hour, t_kst.minute)
    return hm >= TASKER_FROM or hm < TASKER_TO


def test_태스커_창이_필요한_시각을_전부_덮는다():
    kst = dt.timezone(dt.timedelta(hours=9))
    for label, start in (('EDT', dt.date(2026, 8, 24)), ('EST', dt.date(2026, 1, 12))):
        needed = 0
        t = dt.datetime.combine(start, dt.time(0, 0), tzinfo=kst)
        end = t + dt.timedelta(days=8)
        while t < end:
            for key, on in session_router.decide(t.astimezone(dt.timezone.utc)).items():
                if not on:
                    continue
                needed += 1
                assert _tasker_on(t), (
                    f'{label} {t:%a %m-%d %H:%M} KST에 {key} 트리거가 필요한데 '
                    '태스커 창 밖이다')
            t += dt.timedelta(minutes=2)
        assert needed > 2000, f'{label} 표본이 너무 적다({needed}) — 창 계산을 확인할 것'


def test_금요일_미국장_마감까지_커버된다():
    """토요일 새벽이 빠지면 금요일 세션을 통째로 놓친다."""
    kst = dt.timezone(dt.timedelta(hours=9))
    for label, sat, last in (('EDT', dt.date(2026, 8, 29), '04:58'),
                             ('EST', dt.date(2026, 1, 17), '05:58')):
        t = dt.datetime.combine(sat, dt.time(0, 0), tzinfo=kst)
        covered = [t + dt.timedelta(minutes=2 * i) for i in range(360)
                   if session_router.decide(
                       (t + dt.timedelta(minutes=2 * i)).astimezone(dt.timezone.utc))['us']
                   and _tasker_on(t + dt.timedelta(minutes=2 * i))]
        assert covered, f'{label}: 토요일 새벽에 미국장 커버가 하나도 없다'
        assert covered[-1].strftime('%H:%M') == last, (
            f'{label}: 마지막 커버가 {covered[-1]:%H:%M} (기대 {last})')
