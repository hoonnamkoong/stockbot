# -*- coding: utf-8 -*-
"""수집 창이 이미 닫혔으면 KIS 웹소켓에 붙지 않는다.

2026-09-02 실측 — 이 가드가 대기 루프 **안**에 있어서, 시작 시각을 이미 지나
깨어난 런에서는 한 번도 실행되지 않았다:

    09-02 00:19Z(09:19 KST) → 09:31에 "0800 도달 — 수집 시작" → ConnectionClosedError
    08-28 06:10Z(15:10 KST) → 15:22에 "0800 도달 — 수집 시작" → exit 1
    08-27 03:22Z(12:22 KST) → 12:31에 "0800 도달 — 수집 시작" → exit 1

GitHub cron이 몇 시간씩 미는 이 레포에서는 그게 예외가 아니라 기본 경로였고,
premarket_data.yml이 08-17부터 거의 매일 실패하며 그때마다 사람을 불렀다.
"0800 도달"이라는 로그가 09:31에 찍힌 것도 같은 결함이다 — 기다린 적이 없는데
기다렸다고 말한다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from collect_kis_realtime import window_state


def test_창이_닫힌_뒤_깨어나면_붙지_않는다():
    """이게 그 사고다 — 09:31에 08:00~08:50 창을 수집하려 들었다."""
    assert window_state('0931', '0800', '0850') == 'past'


def test_시작_전이면_기다린다():
    assert window_state('0744', '0800', '0850') == 'wait'


def test_창_안이면_수집한다():
    assert window_state('0815', '0800', '0850') == 'go'


def test_시작_시각_정각은_수집이다():
    assert window_state('0800', '0800', '0850') == 'go'


def test_종료_시각_정각은_이미_지난_것이다():
    """until은 '이 시각까지'가 아니라 '이 시각에 끝'이다 — 수신 루프와 같은 판정."""
    assert window_state('0850', '0800', '0850') == 'past'


def test_start가_없으면_기다리지_않는다():
    """--start 없이 즉시 수집하는 용법을 깨지 않는다."""
    assert window_state('0744', '', '0850') == 'go'


def test_start가_없어도_창이_닫혔으면_붙지_않는다():
    """대기 여부와 무관하게, 지난 창에 접속하는 건 언제나 실패한다."""
    assert window_state('0931', '', '0850') == 'past'
