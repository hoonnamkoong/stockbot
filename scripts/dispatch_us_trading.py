# -*- coding: utf-8 -*-
"""국내 트리거(trading.yml)에서 미국 장중 루프(us_trading.yml)를 깨운다.

    python3 scripts/dispatch_us_trading.py

태스커가 2분마다 부르는데 us_trading 런은 30초~3분 걸린다. 확인 없이 매번
dispatch하면 concurrency 그룹(us-trading)에 런이 쌓이고, 세 번째가 들어올 때
대기 중이던 런이 취소된다 — 그 사이클 판단이 통째로 사라진다(2026-08-07 국내에서
실측 196런 중 26런, 13%).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts import gh_dispatch as gh  # noqa: E402

_WORKFLOW = 'us_trading.yml'


def dispatch_us_trading(log=print) -> str:
    """'dispatched' | 'skipped' | 'failed' | 'no-token'."""
    if not gh.token():
        log('[US-Dispatch] GH 토큰 없음 → dispatch 불가')
        return 'no-token'

    if gh.is_running(_WORKFLOW, log=log) is not False:
        # True(실행 중)든 None(조회 실패)든 부르지 않는다. 다음 트리거가 2분 뒤에
        # 다시 시도하고, 대기열이 취소돼 사이클이 통째로 사라지는 쪽이 더 비싸다.
        # dispatch_scraper는 반대로 부르는 쪽에 실패하는데, 거기는 스크래퍼가
        # 자체 게이트로 중복을 걸러내고 여기는 안 걸러낸다.
        #
        # 이 선택 때문에 '영영 안 부름'이 조용해질 수 있어, 세션 밖 미발화
        # 감지기(scripts/check_us_loop_fired.py)가 짝이다.
        log('[US-Dispatch] 이미 실행 중이거나 확인 불가 — dispatch 생략')
        return 'skipped'

    return 'dispatched' if gh.dispatch(_WORKFLOW, log=log) else 'failed'


if __name__ == '__main__':
    # dispatch 실패로 국내 워크플로를 빨갛게 만들지 않는다 — 미국 심은 페이퍼이고
    # 이 워크플로의 본업은 실전 매매다. 침묵이 길어지는 건 세션 밖 감지기가 잡는다.
    dispatch_us_trading()
