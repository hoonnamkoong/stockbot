# -*- coding: utf-8 -*-
"""관찰 심의 기록은 NAV 배열과 섞이지 않는다.

Sim17·18·19(관찰 전용, 매매 신호를 내지 않는다)가 단계 변화를 `history`에
쌓고 있었다. 그런데 `history`는 베이스의 **NAV 숫자 배열**이다
(`reset_state` 템플릿의 `[cash]`, `load_state`의
`setdefault('history', [initial_cash])`).

실제 결과가 db-data에 남아 있었다 — `sim_semiboom_state.json`의 history가
`[0, {관찰}, {관찰}]`이다. 첫 원소 `0`은 초기자본이고 관찰 기록이 아니다.

고치는 것은 둘이다: 이름이 거짓인 것, 그리고 숫자 시계열에 dict가 섞인 것.
리셋이 지우는 문제는 **여기서 고치지 않는다**(buildResetState가 템플릿 전체를
새로 쓴다) — 별개 일이고, 그 사실을 독스트링에 적어 뒀다.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy.simulators.base_simulator import BaseSimulator


class _Sim(BaseSimulator):
    """상태를 파일에서 읽지 않는 최소 대역. 관찰 목록만 본다."""

    def __init__(self, state):
        self.name = 'Probe'
        self.initial_cash = 0
        self.state = state

    def run(self, candidates, current_prices=None):
        return []


def test_빈_상태에서는_빈_목록을_준다():
    s = _Sim({'history': [0]})
    assert s.observation_log() == []
    assert s.state['observations'] == []
    assert s.state['history'] == [0], 'NAV 배열을 건드리지 않는다'


def test_history에_섞인_관찰_기록을_옮긴다():
    """db-data에 실제로 남아 있던 모양: [0, {...}, {...}]"""
    a = {'date': '2026-10-12', 'quality': '가격주도'}
    b = {'date': '2026-11-11', 'quality': '혼합'}
    s = _Sim({'history': [0, a, b]})

    assert s.observation_log() == [a, b]
    assert s.state['history'] == [0], '숫자만 남는다'


def test_숫자가_하나도_안_남으면_초기자본으로_되돌린다():
    """history는 NAV 배열이라 빈 배열로 두면 그 자리의 뜻이 사라진다."""
    s = _Sim({'history': [{'date': '2026-10-12'}]})
    s.initial_cash = 3_000_000
    s.observation_log()
    assert s.state['history'] == [3_000_000]


def test_두_번_불러도_중복되지_않는다():
    a = {'date': '2026-10-12'}
    s = _Sim({'history': [0, a]})
    first = s.observation_log()
    first.append({'date': '2026-11-11'})
    again = s.observation_log()
    assert again == [a, {'date': '2026-11-11'}], '이관은 한 번뿐이다'


def test_반환한_목록에_append하면_상태에_남는다():
    """호출부가 `h = self.observation_log(); h.append(...)`로 쓴다."""
    s = _Sim({'history': [0]})
    s.observation_log().append({'date': '2026-11-23'})
    assert s.state['observations'] == [{'date': '2026-11-23'}]


def test_history가_없거나_이상해도_죽지_않는다():
    assert _Sim({}).observation_log() == []
    assert _Sim({'history': None}).observation_log() == []
    assert _Sim({'history': 5}).observation_log() == []


# ── 관찰 심 셋이 실제로 이 목록을 쓴다 ──────────────────────────────
# 베이스에 메서드만 생기고 호출부가 옛 키를 그대로 두면 아무것도 안 고쳐진다.

import re  # noqa: E402

SIMS = ['sim17_panic_floor', 'sim18_meltup_phase', 'sim19_semi_boom']


def _src(name):
    p = os.path.join(os.path.dirname(__file__), '..', 'src', 'strategy',
                     'simulators', f'{name}.py')
    with open(p, encoding='utf-8') as f:
        return f.read()


def test_관찰_심은_history에_dict를_쌓지_않는다():
    for name in SIMS:
        s = _src(name)
        assert "setdefault('history'" not in s, f'{name}이 아직 history를 쓴다'
        assert 'observation_log()' in s, f'{name}이 관찰 목록을 안 쓴다'


def test_관찰_심_알림은_장애_머리글이_아니다():
    """본문에 '관찰용이고 매매 근거가 아니다'라고 적어 보내면서 머리글만 🚨였다."""
    for name in SIMS:
        s = _src(name)
        assert 'send_alert_once' in s, f'{name}에 알림이 없다'
        assert re.search(r'title\s*=\s*alerts\.NOTICE_TITLE', s), \
            f'{name} 알림이 아직 장애 머리글로 간다'
