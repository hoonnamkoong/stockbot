# -*- coding: utf-8 -*-
"""PR '배포 후 검증 지점' 게이트.

"고쳤다"의 근거가 *코드를 바꿨다*이지 *다음 런에서 실제로 통과했다*가 아니었던
사례가 2026-08-30 하루에 둘 나왔다(PR #60의 프리마켓 격리 누락, 같은 PR의
감지기 배치 오류). 초록 런은 의도한 경로를 탔다는 증거가 아니다.
"""
from scripts.check_pr_checklist import check

FILLED = """## 무엇을 왜
설명

## 배포 후 검증 지점

| 언제 | 어디서 | 무엇이 보이면 고쳐진 것인가 |
|---|---|---|
| 오늘 07:20 KST | premarket_data 런 로그 | `[Deploy] push 성공` |

## 검증
테스트 통과
"""

EMPTY = FILLED.replace(
    '| 오늘 07:20 KST | premarket_data 런 로그 | `[Deploy] push 성공` |', '|  |  |  |')


def test_채워져_있으면_통과():
    assert check(FILLED) is None


def test_빈_표는_막는다():
    assert '비어 있다' in check(EMPTY)


def test_절이_아예_없으면_막는다():
    assert '없다' in check('## 무엇을 왜\n설명')


def test_본문이_비면_막는다():
    assert check('') is not None


def test_템플릿_안내문만으로는_통과_못한다():
    """<!-- --> 주석은 템플릿 문구지 사람이 쓴 내용이 아니다."""
    body = ('## 배포 후 검증 지점\n\n<!-- | 언제 | 어디서 | 무엇 |\n'
            '|---|---|---| -->\n\n|  |  |  |\n')
    assert check(body) is not None


def test_이유를_적으면_빠져나갈_수_있다():
    """못 적을 이유가 있는 변경도 있다. 모른다고 적는 게 모르는 채 두는 것보다 낫다."""
    assert check('## 무엇을 왜\n오타 수정\n\n검증 지점 없음: 주석만 고쳤다') is None


def test_이유_없는_빠져나가기는_막는다():
    assert check('검증 지점 없음:\n') is not None
