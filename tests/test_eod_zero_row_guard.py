# -*- coding: utf-8 -*-
"""EOD는 데이터 행이 0개인 CSV를 db-data에 배포하지 않는다.

2026-09-10 16:00 EOD 로그: `[완료] output/kospi_top100_close.csv 저장 (0행 × 101열)`.
네이버가 이관된 직후라 종목 목록이 비었는데, 배포 가드가 "파일이 있는가"만 봐서
헤더만 든 2,201바이트(정상 약 66KB) 파일이 db-data를 덮었다. 런은 초록이었다.

대가는 다음 날 하루였다. 리베로 trend는 이 CSV를 읽는데, 09-11 장중 관측 40건이
전부 trend 빈칸이었고(정상은 40/40 채움) 심9-1·심11 감시목록도 그 세션에 없었다.
`0 맥락/quiet-wrong-outlives-loud-broken.md`가 말하는 부류다 — 실패보다 오래 산다.
"""
import os
import subprocess
import sys

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
GUARD = os.path.join(ROOT, 'scripts', 'check_csv_rows.py')
WF = os.path.join(ROOT, '.github', 'workflows', 'eod_data.yml')


def _run(path, *args):
    return subprocess.run([sys.executable, GUARD, path, *args],
                          capture_output=True, text=True)


def test_헤더만_있으면_비0_종료(tmp_path):
    """09-10에 배포된 그 파일의 모양이다 — 헤더 한 줄, 데이터 0행."""
    f = tmp_path / 'k.csv'
    f.write_text('date,005930_삼성전자,000660_SK하이닉스\n', encoding='utf-8-sig')
    assert _run(str(f)).returncode != 0


def test_데이터_행이_있으면_0_종료(tmp_path):
    f = tmp_path / 'k.csv'
    f.write_text('date,005930\n20260911,259500\n', encoding='utf-8-sig')
    r = _run(str(f))
    assert r.returncode == 0, r.stderr


def test_파일이_없으면_비0_종료(tmp_path):
    assert _run(str(tmp_path / '없는파일.csv')).returncode != 0


def test_min으로_하한을_올릴_수_있다(tmp_path):
    f = tmp_path / 'k.csv'
    f.write_text('date,code\n20260911,005930\n', encoding='utf-8-sig')
    assert _run(str(f), '--min', '2').returncode != 0


def _deploy_step():
    with open(WF, encoding='utf-8') as f:
        wf = yaml.safe_load(f)
    for job in wf['jobs'].values():
        for step in job.get('steps', []):
            s = step.get('run') or ''
            if 'kospi_top100_close.csv' in s and 'git push' in s:
                return s
    return ''


def test_배포_스텝이_행수를_검사한다():
    s = _deploy_step()
    assert s, '종가 CSV 배포 스텝을 못 찾았다 — 탐지 로직이 깨졌다'
    assert 'check_csv_rows.py' in s, '행 0개를 못 거른다(2026-09-10 사고 재발)'
    guard_at = s.index('check_csv_rows.py')
    assert guard_at < s.index('git push'), '가드는 push보다 앞이어야 한다'
    assert guard_at < s.index('cp output/kospi_top100_close.csv'), '가드는 복사보다 앞이어야 한다'
