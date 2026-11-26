# -*- coding: utf-8 -*-
"""db-data로 push하는 모든 자리에 재시도가 있는가.

db-data writer는 **아홉 개 워크플로**이고 전부 concurrency 그룹이 달라 서로
동시에 돈다. 그래서 `! [rejected] (fetch first)`는 드문 사고가 아니라 구조적으로
자주 나는 일이다 — 장중 db-data 커밋 간격이 2~4분이고, clone→commit→push 창이
수십 초면 그 안에 남이 끼어든다.

2026-11-25 `eod_data.yml`의 CSV 배포가 정확히 그렇게 죽었다(런 45668700330):

    ! [rejected]        db-data -> db-data (fetch first)
    ##[error]Process completed with exit code 1.

재시도가 **한 줄도** 없었다. 같은 레포의 `trading.yml`에는 재clone 3회 루프가,
`dart_fundamentals.yml`에는 rebase 3회 루프가 있는데 그 자리만 빠져 있었다.
한 곳을 고치고 같은 부류를 안 찾는 습관을 이 테스트가 막는다.

재시도를 **rebase가 아니라 재clone**으로 하는 이유는 trading.yml 주석에 실측이
있다: db-data는 커밋 8,800개가 넘어 `fetch --unshallow` 후 rebase가 **142초**다.
하는 일이 "남의 최신 위에 내 파일 얹기"이면 depth 1 재clone이면 되고, 비용이
이력 길이와 무관하다.
"""
import os
import re

import pytest
import yaml

WF_DIR = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows')

_PUSH = re.compile(r'git\s+(?:-C\s+\S+\s+)?push\s+origin\s+db-data')
# 재clone 루프 또는 rebase 루프. 둘 다 "남의 최신 위에 다시 얹는다"는 같은 일을 한다.
_RETRY = re.compile(r'for\s+i\s+in\s+1\s+2\s+3')

# 아직 재시도가 없는 자리. **비워 두는 것이 목표다.**
#
# 여기 적는 것은 "괜찮다"가 아니라 "알고 남겼다"는 뜻이다 — 이유와 폭발 반경을
# 같이 적어야 다음 사람이 판단할 수 있다.
_KNOWN_GAP = {
    ('eod_data.yml', 'Deploy CSV to db-data'):
        '2026-11-27: 이 스텝만 재시도가 없다. 단순 cp가 아니라 '
        'merge_ohlcv_bars.py(첫 인자를 덮어쓴다)·reset_epoch_guard.py(로컬 파일을 '
        '지운다)·`cd db_repo` 상대경로(`../data/$f`)가 얽혀 있어, 재시도 루프로 '
        '감싸려면 그 셋의 멱등성을 전제로 구조를 바꿔야 한다. 전제 자체는 확인됐다'
        '(병합은 "오늘 행=선착순 / 과거 행=최신"이라 멱등·단조, 가드는 2차 시도에 '
        'no-op, 원본은 output/·data/로 클론 밖). 폭발 반경: 그날 종가·OHLCV·'
        '심9-1 상태·심11 감시목록이 db-data에 도달하지 못하고 다음 EOD 런이 복구한다. '
        '전제를 안 가져가면 PR #60(프리마켓 2주 사망)과 같은 사고가 된다.',
}


def _steps_that_push():
    out = []
    for name in sorted(os.listdir(WF_DIR)):
        if not name.endswith('.yml'):
            continue
        with open(os.path.join(WF_DIR, name), encoding='utf-8') as f:
            doc = yaml.safe_load(f)
        for job in (doc.get('jobs') or {}).values():
            for step in job.get('steps') or []:
                body = step.get('run') or ''
                if _PUSH.search(body):
                    out.append((name, step.get('name') or '(이름 없음)', body))
    return out


def test_push_sites_are_discoverable():
    """자리를 못 찾으면 이 테스트는 아무것도 지키지 않는다."""
    sites = _steps_that_push()
    assert len(sites) >= 8, f'db-data push 지점이 {len(sites)}개뿐 — 탐지가 깨졌나'


@pytest.mark.parametrize('wf,step,body', _steps_that_push(),
                         ids=lambda v: v if isinstance(v, str) and len(v) < 40 else '')
def test_every_db_data_push_retries(wf, step, body):
    """푸시 충돌에 재시도가 없으면 그 런의 산출물이 조용히 사라진다."""
    if _RETRY.search(body):
        return
    reason = _KNOWN_GAP.get((wf, step))
    assert reason, (
        f'{wf} / {step} 가 db-data에 push하는데 재시도가 없다. '
        'trading.yml의 재clone 3회 패턴을 쓰거나, 알고 남기는 것이면 '
        '_KNOWN_GAP에 이유와 폭발 반경을 적을 것')


def test_known_gaps_still_exist():
    """고친 자리가 목록에 남아 있으면 목록이 거짓말을 한다.

    `_KNOWN_GAP`은 "알고 남겼다"는 선언이다. 고친 뒤에도 남아 있으면 다음 사람이
    "여긴 아직 안 됐구나"로 읽는다 — 낡은 예외 목록은 없는 것보다 나쁘다.
    """
    live = {(wf, step) for wf, step, body in _steps_that_push()
            if not _RETRY.search(body)}
    stale = set(_KNOWN_GAP) - live
    assert not stale, f'이미 고쳐진 자리가 _KNOWN_GAP에 남아 있다: {stale}'
