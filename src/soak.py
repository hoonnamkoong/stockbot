# -*- coding: utf-8 -*-
"""상주 프로세스가 끊기지 않고 돌았는지 판정한다 (이관 2단계 게이트).

**"죽었나"가 아니라 "연속이었나"를 본다.** Termux:Boot이 다시 띄우면 프로세스는
살아 있지만 그 사이 매매는 없었다 — 그 공백이 정확히 상주 구조의 위험이다.
그래서 프로세스 생존이 아니라 **틱 로그의 구멍**으로 잰다.

판정만 여기 둔다. 틱을 남기는 쪽(scripts/phone_soak.py)은 폰에서 돌고,
읽는 쪽은 사람이 돌린다 — 둘 사이 계약이 이 함수들이다.
"""
import datetime as dt

# 지터 허용 배수. 60초 틱에서 1~2초 밀리는 것까지 구멍으로 세면 통과가
# 영영 안 난다. 반대로 너무 넉넉하면 짧은 정지를 놓친다.
#
# **2.0으로 두면 안 된다.** 틱 하나가 통째로 빠지면 간격이 정확히 2×가 되는데,
# 그게 이 게이트가 잡아야 할 가장 작은 고장이다(경계에서 놓친다). 지터는
# 1.5×를 안 넘으므로 그 사이에 둔다.
GAP_TOLERANCE = 1.5


def gaps(ticks: list[dt.datetime], expected_sec: int,
         tolerance: float = GAP_TOLERANCE) -> list[dict]:
    """연속한 틱 사이가 expected_sec × tolerance를 넘는 구간 목록."""
    limit = expected_sec * tolerance
    out = []
    ordered = sorted(t for t in ticks if t is not None)
    for prev, cur in zip(ordered, ordered[1:]):
        seconds = (cur - prev).total_seconds()
        if seconds > limit:
            out.append({'from': prev, 'to': cur, 'seconds': seconds})
    return out


def verdict(ticks: list[dt.datetime], expected_sec: int,
            required_hours: float, tolerance: float = GAP_TOLERANCE) -> dict:
    """게이트 판정.

    구멍이 없다는 것과 요구 기간을 버텼다는 것은 **다르다.** 둘 다 봐야 한다 —
    한 시간만 촘촘하게 돈 로그를 통과시키면 게이트가 아무것도 안 막는다.
    빈 로그도 마찬가지다: '구멍 없음'으로 읽으면 안 돌린 것이 통과가 된다.
    """
    ordered = sorted(t for t in ticks if t is not None)
    found = gaps(ordered, expected_sec, tolerance)
    covered = ((ordered[-1] - ordered[0]).total_seconds() / 3600
               if len(ordered) >= 2 else 0.0)
    return {
        'passed': bool(ordered) and not found and covered >= required_hours,
        'gaps': len(found),
        'longest_gap_sec': max((g['seconds'] for g in found), default=0.0),
        'covered_hours': round(covered, 2),
        'ticks': len(ordered),
        'first': ordered[0] if ordered else None,
        'last': ordered[-1] if ordered else None,
        'detail': found[:10],
    }
