# -*- coding: utf-8 -*-
"""PR이 '배포 후 검증 지점'을 비운 채 올라오는 걸 막는다.

2026-08-30 조사에서 나온 이유:

- PR #60은 trading.yml의 rebase 재시도 루프를 프리마켓에 복사하면서 그게 성립하는
  전제(전용 클론 격리)를 안 가져왔다. "고쳤다"고 기록됐지만 프리마켓은 그 뒤로도
  2주를 더 실패했다.
- PR #60이 붙인 EOD 미발화 감지기는 감시 대상인 장중 루프 **안에** 있었다.
  미발화가 그 루프 자신에게 일어나자 감지기도 같이 안 돌아 08-27~28 사고를 놓쳤다.

두 경우 다 "고쳤다"의 근거가 *코드를 바꿨다*였지 *다음 런에서 실제로 통과했다*가
아니었다.

빠져나갈 문은 있다 — `검증 지점 없음: <이유>`라고 적으면 통과한다. 못 적을 이유가
있는 변경도 있고, **모른다고 적는 것이 모르는 채로 두는 것보다 낫다.** 다만 빈 칸은
안 된다.
"""
import os
import re
import sys

HEADING = '배포 후 검증 지점'
OPT_OUT = '검증 지점 없음:'
EMPTY_ROW = re.compile(r'^\|\s*(\|\s*)+$')


def check(body: str) -> str | None:
    """통과면 None, 아니면 사람에게 보여줄 사유."""
    if not body or not body.strip():
        return 'PR 본문이 비어 있다.'
    if OPT_OUT in body:
        reason = body.split(OPT_OUT, 1)[1].strip().splitlines()
        if reason and reason[0].strip():
            return None
        return f'`{OPT_OUT}` 뒤에 이유가 없다.'
    if HEADING not in body:
        return f'`{HEADING}` 절이 없다.'

    section = body.split(HEADING, 1)[1]
    section = re.split(r'\n##\s', section, 1)[0]
    # 주석(<!-- -->)은 템플릿 안내문이라 내용으로 치지 않는다.
    section = re.sub(r'<!--.*?-->', '', section, flags=re.S)

    rows = [ln for ln in section.splitlines()
            if ln.strip().startswith('|') and not re.match(r'^\|[\s:|-]+\|$', ln.strip())]
    filled = [ln for ln in rows
              if not EMPTY_ROW.match(ln.strip())
              and '무엇이 보이면' not in ln]
    if not filled:
        return (f'`{HEADING}` 표가 비어 있다. 언제·어디서·무엇이 보이면 '
                '고쳐진 것인지 한 줄이라도 적을 것.')
    return None


def main() -> int:
    problem = check(os.environ.get('PR_BODY', ''))
    if problem:
        print(f'::error::{problem}')
        print()
        print('초록 런은 의도한 경로를 탔다는 증거가 아니다 — 스킵된 런과 게이트가')
        print('깨진 런은 로그에서 같은 모양이다. 다음 런에서 무엇이 보이면 고쳐진')
        print(f'것인지 적거나, `{OPT_OUT} <이유>`로 명시적으로 빠져나갈 것.')
        return 1
    print('[PR] 배포 후 검증 지점 확인됨')
    return 0


if __name__ == '__main__':
    sys.exit(main())
