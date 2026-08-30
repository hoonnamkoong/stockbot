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
