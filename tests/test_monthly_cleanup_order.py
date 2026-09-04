# -*- coding: utf-8 -*-
"""월간 정리는 **아카이브 → 삭제 → 절단** 순서여야 한다.

세 단계가 짝이다:
  1. 지난달을 메일로 내보낸다            monthly_archive.yml
  2. 보관 창 밖의 달을 지운다            같은 잡 (발송 기록이 있는 달만)
  3. 이력을 버린다                       db_data_truncate.yml

**순서가 뒤집히면 2단계가 무의미해진다.** 파일을 지워도 블롭은 이력에 남으므로,
절단이 삭제보다 **먼저** 오면 그달 삭제분이 다음 절단까지 한 달을 더 이력에
남아 있는다. 2026-09-04 실측에서 레포 1.0GB의 86%가 그렇게 쌓인 이력이었다.

그리고 절단이 1회성이면 4개월 뒤 같은 자리로 온다 — 그래서 스케줄이 필요하다.
"""
import os
import re

import yaml

WF_DIR = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows')


def _crons(name: str) -> list:
    with open(os.path.join(WF_DIR, name), encoding='utf-8') as f:
        wf = yaml.safe_load(f)
    # PyYAML은 `on:`을 불리언 True로 읽는다.
    trig = wf.get('on') or wf.get(True) or {}
    sched = trig.get('schedule') or []
    return [s['cron'] for s in sched]


def _minute_of_month(cron: str) -> int:
    """'분 시 일 월 요일' → 그 달 안에서의 분 단위 위치. 비교용이라 근사면 된다."""
    minute, hour, day = cron.split()[:3]
    return ((int(day) - 1) * 24 + int(hour)) * 60 + int(minute)


def test_두_배치_모두_월_1회_스케줄이_있다():
    """절단이 1회성이면 이력이 다시 쌓인다 — 보관 정책과 짝이어야 한다."""
    for name in ('monthly_archive.yml', 'db_data_truncate.yml'):
        crons = _crons(name)
        assert crons, f'{name}에 schedule이 없다 — 월간 정리가 성립하지 않는다'
        for c in crons:
            day = c.split()[2]
            assert re.fullmatch(r'\d+', day), (
                f'{name}의 cron `{c}`이 월 1회가 아니다(일 필드 ={day})')


def test_절단이_아카이브보다_뒤에_온다():
    """삭제 뒤에 절단해야 그달 삭제분이 이력에서 같이 사라진다."""
    archive = min(_minute_of_month(c) for c in _crons('monthly_archive.yml'))
    truncate = min(_minute_of_month(c) for c in _crons('db_data_truncate.yml'))
    assert truncate > archive, (
        f'절단(월중 {truncate}분)이 아카이브(월중 {archive}분)보다 앞선다 — '
        '그달 삭제분이 다음 절단까지 이력에 남는다')
    # 아카이브는 96MB를 gzip해 메일로 보낸다(실측 8월 2통). 너무 붙여 두면
    # 아직 도는 중에 절단이 시작해 가드에 막힌다.
    assert truncate - archive >= 60, (
        f'간격이 {truncate - archive}분뿐이다 — 아카이브가 끝날 시간을 둘 것')
