"""페이퍼 쌍둥이는 실전이 실제로 돈 사이클에만 따라 움직인다.

2026-08-08 발견. trade_if_buzz_free는 run_program_trading이 게이트에 막혀
아무것도 못 하고 None을 돌려줘도 선택 심 id를 그대로 반환했다. 호출부는 그걸
"매매했다"로 읽고 페이퍼 쌍둥이를 돌린다 — 그런데 넘길 유니버스가 없으니
페이퍼는 **자기 유니버스를 새로 만들어 독자 판단**을 한다.

결과: 잔고 조회 실패·예산 0·락 점유 같은 순간에 실전은 아무것도 안 했는데
페이퍼만 매수한다. 대시보드의 페이퍼 성과가 실계좌와 갈라지고, '승자를 뽑아
실전에 올린다'는 방식의 근거가 그 숫자다.
"""
import os
import sys
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline import trading_cycle


class _Ctx:
    now_kst = datetime(2026, 8, 10, 10, 30)

    def __init__(self):
        self.logs = []

    def is_market_hours(self):
        return True

    def log(self, msg):
        self.logs.append(str(msg))


def _call(program_result):
    ctx = _Ctx()
    with mock.patch.object(trading_cycle, 'selected_sim_and_buzz',
                           return_value=('sim4_bull_daytrading', False)), \
         mock.patch.object(trading_cycle, 'run_program_trading',
                           return_value=program_result):
        return trading_cycle.trade_if_buzz_free(ctx, mock.MagicMock(), 'BULL')


def test_no_paper_sync_when_the_real_path_was_gated_off():
    """None = 심을 돌리지 못했다(예산·원장·잔고·락). 페이퍼도 돌면 안 된다."""
    assert _call(None) == (None, None)


def test_paper_syncs_with_the_universe_the_real_path_used():
    universe = [{'code': '005930', 'price': 70000}]
    assert _call(universe) == ('sim4_bull_daytrading', universe)


def test_empty_universe_still_counts_as_a_real_run():
    """빈 리스트는 '못 돌았다'가 아니라 '돌았는데 후보가 없었다'이다 —
    그 사이클의 보유 종목 관리(손절·익절)는 실제로 일어났다."""
    assert _call([]) == ('sim4_bull_daytrading', [])


def test_the_selected_sim_is_looked_up_exactly_once():
    """선택 심 조회는 한 사이클에 한 번뿐이어야 한다(2026-08-09 발견).

    이 조회는 GitHub API를 직접 읽는다 — `selected_sim_and_buzz`가 굳이 try로
    감싼 이유다. 두 번째 호출을 맨몸으로 두면 두 가지가 난다.

      1. 예외가 `run_trade_loop`까지 튀어 런이 죽는다. 그러면 `if: success()`인
         배포 스텝이 통째로 건너뛰어져 그 런의 국면·순위 갱신이 유실된다.
      2. 두 호출 사이(수 초)에 selected_sim이 바뀌면 소유권을 판정한 심과 실제로
         매매한 심이 갈린다 — 버즈 필요 심을 빈 후보로 실전 매매할 수 있다.
    """
    ctx = _Ctx()
    peek = mock.Mock(side_effect=['sim4_bull_daytrading',
                                  RuntimeError('GitHub 조회 실패')])
    with mock.patch.object(trading_cycle, 'peek_selected_sim', peek), \
         mock.patch.object(trading_cycle, 'sim_needs_buzz', return_value=False), \
         mock.patch.object(trading_cycle, 'run_program_trading', return_value=[]):
        assert trading_cycle.trade_if_buzz_free(ctx, mock.MagicMock(), 'BULL') == \
            ('sim4_bull_daytrading', [])
    assert peek.call_count == 1, f'선택 심을 {peek.call_count}번 조회했다'
