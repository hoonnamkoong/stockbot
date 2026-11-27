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
_KNOWN_GAP: dict[tuple[str, str], str] = {
    # 2026-11-27: 마지막으로 남아 있던 `eod_data.yml` / `Deploy CSV to db-data`를
    # 같은 날 고쳤다(재clone 3회). 구조 변경이 필요했던 이유와 멱등성 근거는
    # 그 스텝 주석에 적혀 있다. 이제 10곳 전부 재시도가 있다.
    #
    # 새로 예외를 둘 때는 **이유와 폭발 반경**을 같이 적는다. 이유 없는 예외는
    # 다음 사람에게 "여긴 원래 이래도 된다"로 읽힌다.
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


def _eod_deploy_step() -> str:
    for wf, step, body in _steps_that_push():
        if (wf, step) == ('eod_data.yml', 'Deploy CSV to db-data'):
            return body
    raise AssertionError('eod_data.yml의 CSV 배포 스텝을 못 찾았다')


def test_eod_재시도_루프는_exit가_아니라_break로_끝난다():
    """이 스텝 **뒤에** 종료코드로 내는 고장이 둘 더 있다.

    종가 0행(`csv_ok=0`)과 심 실행 실패(`sims_ok=0`)는 배포를 끝낸 다음 맨 끝에서
    `exit 1`로 낸다 — 그 순서는 2026-08-05(심9-1이 매일 매수하고도 db-data에 한
    번도 반영되지 못함)과 2026-09-10(두 심이 다 실패했는데 런이 초록)에서 각각
    산 교훈이다. 재시도 루프가 `exit 0`으로 빠져나오면 그 두 고장이 **영구히
    조용해진다**. trading.yml의 같은 루프는 뒤에 아무것도 없어 `exit 0`이다.
    """
    body = _eod_deploy_step()
    assert 'break ;;' in body, '재시도 루프가 break로 빠져나오지 않는다'
    done = body.rindex('done')
    for tail in ('if [ "$csv_ok" = 0 ]', 'sims_ok'):
        assert body.index(tail) > done, f'{tail} 블록이 재시도 루프보다 앞에 있다'


def test_eod_재시도가_되돌릴_수_없는_세_명령을_모두_감싼다():
    """재시도 범위가 어긋나면 2회차가 **다른 입력**으로 돈다.

    `merge_ohlcv_bars`는 첫 인자(`output/…`)를 덮어쓰고 `reset_epoch_guard`는
    로컬 파일을 지운다. 둘이 루프 밖에 있으면 1회차가 바꿔 놓은 상태로 2회차가
    새 원격과 합쳐지는데, 그 조합까지 멱등인지는 확인한 적이 없다. clone과 같은
    함수 안에 있어야 "clone→병합→가드→add→push"가 한 덩어리로 다시 돈다.
    """
    body = _eod_deploy_step()
    fn = body.index('attempt() {')
    close = body.index('\n}', fn)   # YAML이 공통 들여쓰기를 벗겨 열0이다
    inside = body[fn:close]
    for cmd in ('git clone --branch db-data', 'merge_ohlcv_bars.py',
                'reset_epoch_guard.py', 'git -C db_repo push'):
        assert cmd in inside, f'{cmd}가 attempt() 밖에 있다'
