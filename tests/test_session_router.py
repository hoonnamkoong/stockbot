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


def test_국내장중에는_kr과_두_배치창이_함께_참():
    """워치리스트(07~15시)·프리마켓(07:20~12시) 창은 국내 장중과 겹친다.

    겹치는 게 의도다 — 두 창은 아침에 실패했을 때 오후까지 재시도할 여유를
    주려고 넓게 잡았다. 실제 중복 발사는 각 dispatch 스크립트의 '이미 성공한
    런이 있나'가 막는다.
    """
    # 2026-08-27(목) 01:00 UTC = 10:00 KST
    assert session_router.decide(_utc(2026, 8, 27, 1, 0)) == {
        'kr': True, 'us': False, 'eod': False, 'audit': False,
        'watchlist': True, 'premarket': True, 'weekly': False}


def test_미국장중이면_us만_참():
    # 2026-08-27(목) 15:00 UTC = 11:00 EDT / 다음날 00:00 KST
    assert session_router.decide(_utc(2026, 8, 27, 15, 0)) == {
        'kr': False, 'us': True, 'eod': False, 'audit': False,
        'watchlist': False, 'premarket': False, 'weekly': False}


def test_둘_다_아니면_둘_다_거짓():
    # 2026-08-27(목) 21:00 UTC = 다음날 06:00 KST — 미국장도 닫혔고,
    # 국내 개장 전이며, EOD 창(16:00~23:00)도 아니다.
    # 예전에는 20:00 KST를 썼는데 EOD 창을 저녁까지 넓히면서 그 시각이
    # eod=True가 됐다(2026-09-01).
    assert session_router.decide(_utc(2026, 8, 27, 21, 0)) == {
        'kr': False, 'us': False, 'eod': False, 'audit': False,
        'watchlist': False, 'premarket': False, 'weekly': False}


def test_저녁에도_eod_창은_열려_있다():
    """2026-09-01: 창을 16~17시에서 16~23시로 넓혔다.

    그날 16:00 EOD가 KIS 연결 타임아웃으로 죽었고 16:46 재시도도 같은 이유로
    죽었는데, 17:00에 창이 닫혀 그날 감시목록이 통째로 비었다. 심9-1·심11이
    다음 세션을 잃는다는 뜻이다. 늦게 도는 것은 무해하다 — eod_data.yml 자체가
    장중이면 수집을 건너뛴다.
    """
    # 11:00 UTC = 20:00 KST
    assert session_router.decide(_utc(2026, 8, 27, 11, 0))['eod'] is True


def test_개장_직후는_kr과_audit이_함께_참():
    # 2026-08-27(목) 00:10 UTC = 09:10 KST
    assert session_router.decide(_utc(2026, 8, 27, 0, 10)) == {
        'kr': True, 'us': False, 'eod': False, 'audit': True,
        'watchlist': True, 'premarket': True, 'weekly': False}


def test_마감_직후는_eod만_참():
    # 2026-08-27(목) 07:10 UTC = 16:10 KST
    assert session_router.decide(_utc(2026, 8, 27, 7, 10)) == {
        'kr': False, 'us': False, 'eod': True, 'audit': False,
        'watchlist': False, 'premarket': False, 'weekly': False}


def test_출력은_github_output_형식():
    with mock.patch.object(session_router, 'decide',
                           return_value={'kr': True, 'us': False, 'eod': False,
                                         'audit': False}):
        lines = session_router.render()
    assert lines == 'kr=true\nus=false\neod=false\naudit=false'


def test_표준_라이브러리만_import한다():
    """pip install 앞에서 도는 스텝이다 — 서드파티가 섞이면 거기서 죽는다."""
    # 인터프리터가 기동만으로 들여온 것(.pth 등)은 뺀다 — 우리가 늘린 것만 본다.
    heavy = '("requests","yfinance","pandas","numpy","yaml","google","bs4","dotenv")'
    code = ('import sys; sys.path.insert(0, "."); '
            f'base={{m for m in sys.modules if m.split(".")[0] in {heavy}}}; '
            'import scripts.session_router, scripts.dispatch_us_trading, '
            'scripts.dispatch_eod_data, scripts.dispatch_us_eod_watchlist, '
            'scripts.dispatch_premarket_data, scripts.dispatch_weekly_report; '
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
TASKER_TO = (8, 0)


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


def test_소스의_태스커_상수가_이_파일의_실제_설정과_일치한다():
    """위 TASKER_* 는 **핸드폰의 실제 프로파일**을 적어 둔 값이고,
    src/session_gate.py의 상수는 창 함수가 사각지대를 잘라낼 때 쓰는 값이다.

    둘이 갈라지면 창은 열려 있는데 아무도 안 부르는 시각이 생긴다 — 정확히
    이 파일의 창 검사가 막으려는 것인데, 그 검사 자신이 다른 값을 보게 된다.
    """
    from src import session_gate as sg
    assert sg.TASKER_WAKE_HHMM == TASKER_FROM
    assert sg.TASKER_SLEEP_HHMM == TASKER_TO


def test_trading_yml이_세_배치를_실제로_깨운다():
    """라우터가 창을 열어도 워크플로에 스텝이 없으면 아무 일도 안 일어난다.

    이 레포는 그 실패를 이미 겪었다 — 오프틱 매매를 위임한 워크플로가 실재하지
    않았고, 단위 테스트는 '위임한다'만 검증해 초록이었다. 실행 이력 0건인
    경로는 어떤 실패 목록에도 안 뜬다.
    """
    import os
    wf = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows',
                      'trading.yml')
    with open(wf, encoding='utf-8') as f:
        text = f.read()
    for out, script in (('watchlist', 'dispatch_us_eod_watchlist.py'),
                        ('premarket', 'dispatch_premarket_data.py'),
                        ('weekly', 'dispatch_weekly_report.py')):
        assert f"steps.route.outputs.{out} == 'true'" in text, (
            f'trading.yml이 {out} 출력을 안 읽는다 — 창이 열려도 발화가 없다')
        # 파일 어딘가에 이름이 있는 것으로는 부족하다 — 주석에도 적혀 있어서
        # 스텝을 통째로 지워도 통과했다(이 테스트를 변이로 깨보다 발견).
        assert f'run: python3 scripts/{script}' in text, (
            f'{script}를 **실행하는** 스텝이 없다 — 이름만 주석에 남아 있다')
