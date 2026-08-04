"""E3 (2026-08-04 스크래퍼 지연 재설계): peek_selected_sim().

순서 가변 분기(orchestrator Stage 0.5)가 스크래핑 전에 '어떤 심이 선택됐는가'만
미리 알기 위해 쓰는 가벼운 조회. run_program_trading()의 본 게이트(예산·원장·
실계좌 조회)를 앞지르지 않는다 — 그건 이 함수가 True를 준 뒤에도 그대로 다시
돈다.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers import program_trader


def _cfg(**overrides):
    base = {'enabled': True, 'selected_sim': 'sim4_bull_daytrading', 'budget': 2_000_000}
    base.update(overrides)
    return base


def test_returns_none_when_disabled():
    with mock.patch.object(program_trader, '_read_config_fresh', return_value=_cfg(enabled=False)):
        assert program_trader.peek_selected_sim() is None


def test_returns_none_when_config_missing():
    with mock.patch.object(program_trader, '_read_config_fresh', return_value=None):
        assert program_trader.peek_selected_sim() is None


def test_returns_none_for_invalid_sim_id():
    with mock.patch.object(program_trader, '_read_config_fresh',
                            return_value=_cfg(selected_sim='no_such_sim')):
        assert program_trader.peek_selected_sim() is None


def test_returns_none_for_non_tradeable_sim():
    """analyzer(sim0_libero)나 tradeable:false 심을 골라도(설정 손상 등) None."""
    with mock.patch.object(program_trader, '_read_config_fresh',
                            return_value=_cfg(selected_sim='sim0_libero')):
        assert program_trader.peek_selected_sim() is None


def test_returns_selected_sim_when_enabled_and_valid():
    with mock.patch.object(program_trader, '_read_config_fresh',
                            return_value=_cfg(selected_sim='sim4_bull_daytrading')):
        assert program_trader.peek_selected_sim() == 'sim4_bull_daytrading'


def test_does_not_touch_ledger_or_balance():
    """예산·원장·잔고 조회를 하면 안 된다 — Stage 0.5는 config만 본다."""
    with mock.patch.object(program_trader, '_read_config_fresh', return_value=_cfg()) as cfg_mock, \
         mock.patch.object(program_trader, '_read_ledger_fresh') as ledger_mock:
        program_trader.peek_selected_sim()
        cfg_mock.assert_called_once()
        ledger_mock.assert_not_called()
