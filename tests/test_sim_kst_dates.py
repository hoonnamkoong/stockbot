# -*- coding: utf-8 -*-
"""심의 날짜 판정은 KST여야 한다.

`get_kst_now()`는 "시스템 환경과 무관하게 한국 표준시(UTC+9) 강제 적용"을 위해 있는데
일부 심이 `date.today()`(시스템 로컬 날짜)를 쓰고 있었다.

**지금은 어긋나지 않는다** — 심이 도는 창이 Tasker(KST 09:00~15:30 = UTC 00:00~06:30)와
EOD cron(KST 18~20 = UTC 09~11)이라 UTC 날짜와 KST 날짜가 같다.
**UTC 15:00 이후(= KST 자정 이후)** 실행되면 하루 뒤처져 보유일수가 1일 어긋나고,
강제청산·타임스탑이 밀리거나 당겨진다. 밤 수동 dispatch나 cron 8시간+ 지연이 그 조건이다.

`sim1_psych`은 이미 주입으로 고쳐져 있었다(그 함수 주석에 근거가 있다).
"""
import ast
import datetime
import io
import os

from src.strategy.simulators.base_simulator import get_kst_date, get_kst_now

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_DIR = os.path.join(ROOT, 'src', 'strategy', 'simulators')

# 매니페스트에 등록된 심 + 공통 기반. 여기에 시간대 없는 호출이 있으면 안 된다.
# sim1_original.py·sim2_conservative.py·sim3_aggressive.py는 매니페스트에 없는
# 죽은 파일이라 제외한다 — 안 도는 코드를 지키는 것은 소음이다.
GUARDED = (
    'base_simulator.py', 'sim0_libero.py', 'sim1_psych.py', 'sim2_spillover.py',
    'sim3_risk.py', 'sim4_bull_daytrading.py', 'sim4_bull_momentum.py',
    'sim5_sideways_swing.py', 'sim6_bear_hedge.py', 'sim7_report_follower.py',
    'sim8_accumulation.py', 'sim9_gap_fade.py', 'sim9_1_donchian.py',
    'sim10_orchestrator.py',
)

def _read(name):
    with io.open(os.path.join(SIM_DIR, name), encoding='utf-8') as f:
        return f.read()


def _naive_time_calls(source):
    """시간대 없는 '현재 시각/날짜' 호출을 찾는다. (줄번호, 표현) 리스트.

    소스를 정규식으로 훑으면 독스트링에 적힌 `date.today()`까지 잡는다(실제로 잡혔다).
    AST로 호출 노드만 본다. `datetime.now(timezone(...))`처럼 tz를 주면 통과다.
    """
    hits = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attr = node.func.attr
        base = node.func.value
        base_name = base.id if isinstance(base, ast.Name) else (
            base.attr if isinstance(base, ast.Attribute) else '')
        if attr == 'today' and base_name in ('date', 'datetime'):
            hits.append((node.lineno, f'{base_name}.today()'))
        elif attr == 'now' and base_name == 'datetime' and not node.args and not node.keywords:
            hits.append((node.lineno, 'datetime.now()'))
    return hits


def test_get_kst_date는_KST_달력_날짜다():
    assert get_kst_date() == get_kst_now().date()
    assert isinstance(get_kst_date(), datetime.date)


def test_KST_날짜는_UTC_저녁에_이미_다음_날이다():
    # 이 성질이 없으면 시간대를 붙인 의미가 없다.
    utc_evening = datetime.datetime(2026, 7, 30, 16, 0, tzinfo=datetime.timezone.utc)
    kst = utc_evening.astimezone(datetime.timezone(datetime.timedelta(hours=9)))
    assert kst.date() == datetime.date(2026, 7, 31)
    assert utc_evening.date() == datetime.date(2026, 7, 30), '로컬이 UTC면 하루 뒤처진다'


def test_심이_시간대_없는_날짜를_쓰지_않는다():
    offenders = []
    for name in GUARDED:
        path = os.path.join(SIM_DIR, name)
        if not os.path.exists(path):
            continue
        for lineno, expr in _naive_time_calls(_read(name)):
            offenders.append(f'{name}:{lineno}: {expr}')
    assert not offenders, (
        'KST를 쓸 것 — get_kst_now() / get_kst_date(). 위반:\n  ' + '\n  '.join(offenders))


def test_감시기가_실제로_잡는다():
    # 이 테스트가 없으면 위 테스트는 '아무것도 안 잡는 감시기'일 때도 통과한다.
    bad = 'from datetime import date, datetime\nx = date.today()\ny = datetime.now()\n'
    assert [e for _, e in _naive_time_calls(bad)] == ['date.today()', 'datetime.now()']

    good = ('from datetime import datetime, timedelta, timezone\n'
            'z = datetime.now(timezone(timedelta(hours=9)))\n')
    assert _naive_time_calls(good) == [], 'tz를 준 호출은 통과해야 한다'

    prose = '"""독스트링에 date.today()라고 적혀 있어도 호출이 아니다."""\n'
    assert _naive_time_calls(prose) == []


def test_쿨다운_만료가_KST_기준이다(tmp_path):
    from src.strategy.simulators.base_simulator import BaseSimulator
    sim = BaseSimulator.__new__(BaseSimulator)
    sim.name = 'T'
    sim.state_file = str(tmp_path / 's.json')
    sim.state = {'cooldown_codes': {}}
    sim.add_cooldown('005930', 2)
    expire = sim.state['cooldown_codes']['005930']
    assert expire == (get_kst_date() + datetime.timedelta(days=2)).isoformat()


def test_쿨다운은_만료일_당일에_풀린다():
    from src.strategy.simulators.base_simulator import BaseSimulator
    today = get_kst_date().isoformat()
    tomorrow = (get_kst_date() + datetime.timedelta(days=1)).isoformat()
    assert BaseSimulator.cooldown_active({'A': tomorrow}, 'A') is True
    assert BaseSimulator.cooldown_active({'A': today}, 'A') is False, '만료 당일부터 재진입 허용'
    assert BaseSimulator.cooldown_active({}, 'A') is False
