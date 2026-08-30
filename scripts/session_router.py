# -*- coding: utf-8 -*-
"""태스커 트리거 하나를 국내장/미국장으로 가르는 라우터.

    python3 scripts/session_router.py >> "$GITHUB_OUTPUT"

태스커는 09:00~06:00 KST에 2분 간격으로 trading.yml **하나만** 부른다. 그 창의
절반 이상은 어느 장도 아니므로(15:50~22:30 KST), 이 스텝은 pip install 앞에
놓여 장 밖 트리거를 checkout만 하고 끝내야 한다. 그래서 표준 라이브러리만 쓴다
— tests/test_session_router.py가 그 제약을 지킨다.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.session_gate import kr_session_open, us_session_open  # noqa: E402

_KST = dt.timezone(dt.timedelta(hours=9))


def decide(now_utc: dt.datetime | None = None) -> dict[str, bool]:
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    # 국내 게이트는 naive KST를 받는다(PipelineContext.now_kst와 같은 표현).
    now_kst = now_utc.astimezone(_KST).replace(tzinfo=None)
    return {'kr': kr_session_open(now_kst), 'us': us_session_open(now_utc)}


def render() -> str:
    return '\n'.join(f'{k}={"true" if v else "false"}' for k, v in decide().items())


if __name__ == '__main__':
    print(render())
