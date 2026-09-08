# -*- coding: utf-8 -*-
"""시각과 장 경계는 한 곳에서만 정의된다 — `src/core/clock.py`.

## 왜 필요했나 (2026-09-08 전수 실측)

**KST가 13개 파일에 각자 정의돼 있었다.** `_KST = dt.timezone(dt.timedelta(hours=9))`가
그만큼 복사돼 있고, "지금 KST"를 구하는 방식은 다섯 갈래였다:

    datetime.now(timezone(timedelta(hours=9)))       # aware
    datetime.utcnow() + timedelta(hours=9)           # naive + utcnow는 폐기 예정
    datetime.now(timezone.utc).astimezone(...)       # aware
    (_utc + timedelta(hours=9)).replace(tzinfo=None) # naive
    base_simulator.get_kst_now()

aware와 naive가 섞이면 비교에서 TypeError가 난다. `session_gate.kr_session_open`이
"naive든 aware든 받는다"고 방어하는 것도 그래서다 — 방어 코드가 있다는 것 자체가
원천이 갈라져 있다는 신호다.

**그리고 장 경계는 같은 이름이 파일마다 다른 값이었다:**

    KR_CLOSE_HHMM   = (15, 30)   src/data_freshness.py
    KR_CLOSE_HHMM   = (15, 50)   src/session_gate.py      ← 같은 이름, 다른 값
    MARKET_CLOSE_HHMM = (15, 30) src/pipeline/context.py
    _KR_CLOSE_HHMM  = (15, 30)   scripts/dispatch_eod_data.py
    (인라인 15:50)               src/pipeline/context.py:149

게다가 `session_gate.py`는 주석으로 이렇게 동기화하고 있었다 —
"상한이 15:50인 것은 context.is_market_hours와 **맞춘 것이다**".
**주석은 실행되지 않는다.** 이 레포는 그것으로 이미 두 번 사고를 겪었다.

## 이 파일이 지키는 것

통합 자체가 아니라 **다시 갈라지지 못하게 막는 것**이다. 토큰이 유일하게 재발하지
않은 통합인데, 그 이유가 `test_auth_delegates_token_issue.py`의 가드였다.
같은 방식으로 아래 마지막 두 테스트가 새 KST 정의와 새 경계 리터럴을 막는다.
"""
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.core import clock

REPO = os.path.join(os.path.dirname(__file__), '..')


# ── 시각 ────────────────────────────────────────────────────────────

def test_now는_KST가_붙은_값이다():
    """naive를 돌려주면 호출부가 각자 tz를 붙이다가 또 갈라진다."""
    now = clock.now()
    assert now.tzinfo is not None
    assert now.utcoffset() == dt.timedelta(hours=9)


def test_now_naive는_같은_벽시계를_tz없이_준다():
    """기존 PipelineContext.now_kst 관례(naive KST)를 그대로 유지한다 —
    한 번에 aware로 바꾸면 비교하는 자리마다 TypeError가 터진다."""
    aware, naive = clock.now(), clock.now_naive()

    assert naive.tzinfo is None
    assert abs((naive - aware.replace(tzinfo=None)).total_seconds()) < 2


def test_폐기된_utcnow를_호출하지_않는다():
    """`datetime.utcnow()`는 폐기 예정이고 naive를 준다. 전수 실측에서 6곳이
    그걸로 KST를 만들고 있었다.

    문자열이 아니라 **호출**을 본다 — 독스트링에서 그 이름을 설명만 해도
    걸리면, 테스트가 코드가 아니라 산문을 검사하게 된다.
    """
    import ast
    src = open(os.path.join(REPO, 'src', 'core', 'clock.py'),
               encoding='utf-8').read()

    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == 'utcnow']

    assert not calls, 'clock.py가 폐기된 utcnow()를 호출한다'


# ── 정규화 ──────────────────────────────────────────────────────────

def test_naive를_KST로_읽는다():
    """이 레포의 naive datetime은 전부 KST 벽시계다(UTC가 아니다)."""
    got = clock.to_kst(dt.datetime(2026, 9, 8, 9, 30))

    assert got.utcoffset() == dt.timedelta(hours=9)
    assert (got.hour, got.minute) == (9, 30)


def test_다른_tz는_KST로_변환한다():
    utc = dt.datetime(2026, 9, 8, 0, 30, tzinfo=dt.timezone.utc)

    assert (clock.to_kst(utc).hour, clock.to_kst(utc).minute) == (9, 30)


def test_날짜_문자열_두_형식():
    d = dt.datetime(2026, 9, 8, 14, 0)

    assert clock.date_str(d) == '2026-09-08'
    assert clock.date_compact(d) == '20260908'


# ── 장 경계 ─────────────────────────────────────────────────────────

def test_경계_셋이_순서대로다():
    assert clock.KR_OPEN < clock.KR_REGULAR_CLOSE < clock.KR_JUDGMENT_CLOSE


def test_경계_이름이_뜻을_말한다():
    """옛 이름 `KR_CLOSE_HHMM`은 파일마다 15:30이거나 15:50이었다.
    이름만 보고 어느 쪽인지 알 수 없으면 다음 사람이 또 틀린다."""
    assert clock.KR_REGULAR_CLOSE == (15, 30)   # 정규장 마감 = 신규 매수 차단선
    assert clock.KR_JUDGMENT_CLOSE == (15, 50)  # 매도·기타 판단 상한


# ── 가드: 다시 갈라지지 못하게 ────────────────────────────────────────

_KST_LITERAL = re.compile(r"timedelta\(hours=9\)|ZoneInfo\(['\"]Asia/Seoul['\"]\)")


def _production_py():
    skip = ('_legacy_backups', 'scratch', 'tests', 'node_modules', '.git',
            '.next', 'out', 'dist', '__pycache__')
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if f.endswith('.py') and not f.startswith('tmp_') and 'legacy' not in f:
                yield os.path.join(root, f)


def test_KST를_직접_만드는_프로덕션_파일이_없다():
    """파일 목록이 아니라 규칙으로 검사한다 — 새로 생겨도 잡힌다."""
    allowed = {os.path.normpath('src/core/clock.py')}

    offenders = []
    for path in _production_py():
        rel = os.path.normpath(os.path.relpath(path, REPO))
        if rel in allowed:
            continue
        with open(path, encoding='utf-8', errors='replace') as f:
            if _KST_LITERAL.search(f.read()):
                offenders.append(rel)

    assert not offenders, (
        f'{offenders}가 KST를 직접 만든다 — src.core.clock.KST 하나여야 한다. '
        '13곳으로 갈라졌던 것이 aware/naive 혼용을 만들었다')


def test_장_경계를_직접_적는_프로덕션_파일이_없다():
    """`(15, 30)`·`(15, 50)` 같은 리터럴이 다시 나타나면 막는다.

    같은 이름이 다른 값을 갖던 것이 이 통합의 이유다 —
    `KR_CLOSE_HHMM`이 한 파일에선 15:30, 다른 파일에선 15:50이었다.
    """
    allowed = {os.path.normpath('src/core/clock.py')}
    literal = re.compile(r'\(\s*15\s*,\s*(30|50)\s*\)')

    offenders = []
    for path in _production_py():
        rel = os.path.normpath(os.path.relpath(path, REPO))
        if rel in allowed:
            continue
        with open(path, encoding='utf-8', errors='replace') as f:
            if literal.search(f.read()):
                offenders.append(rel)

    assert not offenders, (
        f'{offenders}가 장 마감 경계를 직접 적는다 — '
        'clock.KR_REGULAR_CLOSE / clock.KR_JUDGMENT_CLOSE를 쓸 것')
