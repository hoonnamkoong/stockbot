# -*- coding: utf-8 -*-
"""NXT 프리마켓 체결은 intraday-data에 남아야 한다.

2026-09-11 점검에서 확인: **08-17 이후 NXT 원자료가 한 번도 저장되지 않았다.**
08-16에 수집기는 `data/nxt_<TR>_<날짜>.csv`로 쓰고 워크플로는 `data/nxt_*.csv`를
db-data에 복사했는데, 08-17(`9354b875e`)에 수집기가 `collect_kis_realtime.py`로
바뀌면서 기본 출력이 `data/rt_<TR>_<날짜>.csv`가 됐다. 복사 글롭은 그대로였다.
원격 어느 브랜치에도 NXT 파일이 0개다(하루 약 3.9만 행).

**왜 db-data가 아니라 intraday-data인가:** db-data는 trading.yml이 2분마다 depth 1로
받는 핫패스라 ~15MB 예산에 묶여 있다. NXT는 하루 수 MB가 무한 누적된다 — 장중
호가·체결 아카이브를 intraday-data로 뺀 것과 같은 이유다.

파일은 collect 잡이 만들고 커밋 스텝은 intraday 잡에 있으므로 artifact로 넘긴다.
"""
import os

import yaml

WF = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows',
                  'premarket_data.yml')


def _wf():
    with open(WF, encoding='utf-8') as f:
        return yaml.safe_load(f)


def _steps(job):
    return _wf()['jobs'][job]['steps']


def test_collect가_NXT_산출물을_artifact로_올린다():
    up = [s for s in _steps('collect')
          if 'upload-artifact' in str(s.get('uses', ''))]
    assert up, 'NXT 파일을 intraday 잡으로 넘길 방법이 없다'
    s = up[0]
    assert 'rt_H0NXCNT0' in str(s['with']['path']), '실제 출력 파일명과 안 맞는다'
    assert 'always()' in str(s.get('if', '')), \
        '뒤 스텝이 실패해도 그때까지 받은 NXT는 남겨야 한다'


def test_intraday가_커밋_전에_artifact를_내려받는다():
    steps = _steps('intraday')
    down = [i for i, s in enumerate(steps)
            if 'download-artifact' in str(s.get('uses', ''))]
    commit = [i for i, s in enumerate(steps)
              if 'intraday-data' in (s.get('name') or '')]
    assert down and commit, f'download={down} commit={commit}'
    assert down[0] < commit[0], '커밋 뒤에 내려받으면 아무 소용이 없다'


def test_커밋_스텝이_NXT도_gz로_올린다():
    s = next(s for s in _steps('intraday') if 'intraday-data' in (s.get('name') or ''))
    run = s['run']
    assert 'rt_H0NXCNT0' in run, 'NXT 파일이 압축·커밋 대상에 없다'
    assert 'gzip' in run and '104857600' in run, '기존 압축·100MB 가드는 유지돼야 한다'


def test_db_data_복사에서_죽은_패턴을_없앤다():
    """`data/nxt_*.csv`는 08-17 이후 한 번도 매칭된 적이 없다 — 남겨두면 또 속는다."""
    s = next(s for s in _steps('collect') if 'push origin db-data' in (s.get('run') or ''))
    assert 'data/nxt_*.csv' not in s['run']
