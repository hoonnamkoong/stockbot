"""폰이 상주 프로세스를 3일 죽이지 않는지 재는 도구.

이관 2단계의 **게이트**다. 안드로이드는 충전 중이면 Doze에 안 들어가지만
(조건: 화면 꺼짐 + 미충전 + 정지), OEM 킬러와 메모리 압박은 남는다.
"될 것 같다"로 돈을 걸 수 없으므로 실측한다.

여기서 재는 것은 "죽었나"가 아니라 **"연속이었나"**다. Termux:Boot이 다시
띄우면 프로세스는 살아 있지만 그 사이 매매는 없었다 — 로그에 구멍으로 남는다.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src import soak  # noqa: E402

_KST = dt.timezone(dt.timedelta(hours=9))


def ticks(start_min, count, step_sec=60, skip=()):
    """start_min분부터 step_sec 간격 틱. skip에 든 인덱스는 빠뜨린다."""
    base = dt.datetime(2026, 9, 7, 0, start_min, tzinfo=_KST)
    return [base + dt.timedelta(seconds=step_sec * i)
            for i in range(count) if i not in skip]


def test_균등한_틱에는_구멍이_없다():
    assert soak.gaps(ticks(0, 60), expected_sec=60) == []


def test_허용_배수를_넘는_간격만_구멍으로_센다():
    """1~2초 지터까지 구멍으로 세면 통과가 영영 안 난다."""
    t = ticks(0, 10)
    t[5] += dt.timedelta(seconds=25)          # 85초 간격 — 지터
    assert soak.gaps(t, expected_sec=60) == []


def test_한_틱이라도_빠지면_구멍이다():
    found = soak.gaps(ticks(0, 10, skip=(4,)), expected_sec=60)
    assert len(found) == 1
    assert found[0]['seconds'] == 120


def test_구멍이_하나라도_있으면_통과가_아니다():
    v = soak.verdict(ticks(0, 60 * 24 * 4, skip=(100,)),
                     expected_sec=60, required_hours=72)
    assert v['passed'] is False
    assert v['gaps'] == 1


def test_촘촘해도_기간이_모자라면_통과가_아니다():
    """구멍이 없다는 것과 3일을 버텼다는 것은 다르다."""
    v = soak.verdict(ticks(0, 60 * 10), expected_sec=60, required_hours=72)
    assert v['passed'] is False
    assert v['covered_hours'] < 72


def test_사흘을_구멍_없이_돌면_통과():
    v = soak.verdict(ticks(0, 60 * 73), expected_sec=60, required_hours=72)
    assert v['passed'] is True
    assert v['gaps'] == 0


def test_틱이_없으면_통과가_아니다():
    """빈 로그를 '구멍 없음'으로 읽으면 안 돌린 것이 통과가 된다."""
    v = soak.verdict([], expected_sec=60, required_hours=72)
    assert v['passed'] is False


# ── 로그 읽기 ──────────────────────────────────────────────────────
# 킬 당시 잘린 줄이 남을 수 있다. 거기서 예외가 나면 **사흘을 돌린 뒤에야**
# 판정을 못 낸다는 걸 알게 된다 — 알아내기 가장 나쁜 시점이다.

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import phone_soak  # noqa: E402


def test_잘린_줄이_있어도_나머지를_읽는다(tmp_path):
    log = tmp_path / 'soak.log'
    log.write_text(
        '2026-09-07T00:00:00+09:00\n'
        '2026-09-07T00:0\n'            # 킬 당시 잘린 줄
        '\n'
        '2026-09-07T00:02:00+09:00\n', encoding='utf-8')

    ticks = phone_soak.read_ticks(str(log))

    assert len(ticks) == 2, '잘린 줄 하나에 판정이 통째로 실패하면 안 된다'


def test_로그가_없으면_빈_목록(tmp_path):
    assert phone_soak.read_ticks(str(tmp_path / '없음.log')) == []
