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
import re
import subprocess
import sys

import yaml

# 2026-11-27: 이 스텝이 재clone 재시도 루프로 바뀌면서 `cd db_repo` + `git push`가
# `git -C db_repo push`가 됐다. 리터럴 'git push'로 스텝을 찾던 헬퍼가 조용히
# 아무것도 못 찾아 네 건이 한꺼번에 깨졌다 — 탐지기는 명령 형태를 받아들여야 한다.
# tests/test_db_data_push_retry.py의 _PUSH와 같은 패턴이다.
_PUSH = re.compile(r'git\s+(?:-C\s+\S+\s+)?push\s+origin\s+db-data')


def _push_at(body: str) -> int:
    m = _PUSH.search(body)
    assert m, 'db-data push 명령을 못 찾았다 — 탐지 패턴이 낡았다'
    return m.start()

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
            if 'kospi_top100_close.csv' in s and _PUSH.search(s):
                return s
    return ''


def test_배포_스텝이_행수를_검사한다():
    s = _deploy_step()
    assert s, '종가 CSV 배포 스텝을 못 찾았다 — 탐지 로직이 깨졌다'
    assert 'check_csv_rows.py' in s, '행 0개를 못 거른다(2026-09-10 사고 재발)'
    guard_at = s.index('check_csv_rows.py')
    assert guard_at < _push_at(s), '가드는 push보다 앞이어야 한다'
    assert guard_at < s.index('cp output/kospi_top100_close.csv'), '가드는 복사보다 앞이어야 한다'


def _deploy_and_jobs():
    with open(WF, encoding='utf-8') as f:
        wf = yaml.safe_load(f)
    step = next(s for j in wf['jobs'].values() for s in j.get('steps', [])
                if 'kospi_top100_close.csv' in (s.get('run') or '')
                and _PUSH.search(s.get('run') or ''))
    return step['run'], wf['jobs']


def test_0행이어도_심_상태_배포는_막지_않는다():
    """가드를 스텝 맨 앞에서 exit 1로 끊으면 같은 스텝 뒤쪽의 심9-1 상태·심11
    감시목록 배포까지 죽는다 — 2026-08-05에 겪은 그 사고(심9-1이 매일 매수하고도
    db-data에 한 번도 반영 못 함)를 0행인 날에 재현하게 된다."""
    run, _ = _deploy_and_jobs()
    assert 'sim11_watchlist.json' in run
    guard = run.index('check_csv_rows.py output/kospi_top100_close.csv')
    assert guard < run.index('sim11_watchlist.json')
    # 가드와 심 상태 배포 사이에 종료가 없어야 한다. 주석은 **뺀다** —
    # 2026-11-27에 "즉시 exit 1이었다"라고 적은 주석 한 줄이 이 검사를 깨뜨렸다.
    # 불변식은 실행되는 줄에 대한 것이다.
    between = '\n'.join(
        ln for ln in run[guard:run.index('sim11_watchlist.json')].split('\n')
        if not ln.lstrip().startswith('#'))
    assert 'exit 1' not in between, '0행이면 심 상태까지 못 올린다'


def test_0행이면_배포_뒤에_실패로_끝난다():
    """조용히 넘어가면 안 된다 — 기존 실패 알림(job.status != 'success')이 사람을 부른다."""
    run, _ = _deploy_and_jobs()
    assert run.rstrip().endswith('fi'), run[-120:]
    assert 'exit 1' in run[_push_at(run):], '종가 0행이 실패로 이어지지 않는다'


def test_분봉_잡은_collect_실패에도_돈다():
    """분봉은 당일치만 조회된다. 종가 CSV 한 파일의 0행이 분봉 하루를 통째로
    날리면 이 가드가 원래 막으려던 것보다 큰 손실이다."""
    _, jobs = _deploy_and_jobs()
    assert 'always()' in str(jobs['minute_bars'].get('if', ''))
