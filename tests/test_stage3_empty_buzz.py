"""신규 버즈 종목이 없는 사이클에도 Stage 3은 돌아야 한다.

orchestrator Stage 2는 이 경우를 명시적으로 다룬다:

    "신규 수집 종목 없음 (Buzz 임계값 미달). 기존 포트폴리오 관리 모드로 진입합니다."
    # [V50.2] 신규 종목이 없어도 Stage 3(시뮬레이터)를 실행하기 위해 빈 리스트로 계속 진행

그런데 TradeEngineWorker.run()이 첫 줄에서 `if not stocks: return`으로 빠져나가
그 의도를 무효화하고 있었다. 결과:
  - 전 페이퍼 심이 그 사이클을 통째로 건너뛴다(보유 종목 손절·익절도 안 된다)
  - 버즈 필요 심을 실전에 올린 상태면 **그 사이클의 실전 매매도 없다**
    (그 경로의 주문 주체는 Stage 3 하나뿐이다)

심들은 현재가가 없는 종목을 이미 걸러낸다(`if cur <= 0: continue`)므로 빈
후보로 도는 것 자체는 위험하지 않다 — 보유 종목 가격은 네이버 보강이 채운다.
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.trade_engine import TradeEngineWorker


class _Ctx:
    now_kst = datetime(2026, 8, 10, 11, 0, tzinfo=timezone(timedelta(hours=9)))

    def is_buy_window(self):
        return True

    def is_market_hours(self):
        return True

    def should_notify(self):
        return False

    def log(self, msg):
        pass


def _worker():
    return TradeEngineWorker(_Ctx(), mock.MagicMock())


def _sync():
    return mock.MagicMock(daily_deep_dive_codes=[], daily_reported_info=[],
                          morning_reported_info=[], afternoon_reported_info=[])


def test_simulators_run_even_with_no_new_buzz_stocks():
    w = _worker()
    with mock.patch.object(w, '_run_simulators') as rs:
        w.run([], _sync(), skip_program_trading=True)

    rs.assert_called_once()


def test_program_trading_still_happens_with_no_new_buzz_stocks():
    """버즈 필요 심이 실전이면 주문을 낼 수 있는 곳은 여기뿐이다."""
    w = _worker()
    with mock.patch.object(w, '_run_simulators'), \
         mock.patch('src.pipeline.workers.program_trader.run_program_trading') as rpt:
        w.run([], _sync(), skip_program_trading=False)

    rpt.assert_called_once()


def test_empty_input_still_returns_the_usual_shape():
    w = _worker()
    with mock.patch.object(w, '_run_simulators'):
        picks, results, sell = w.run([], _sync(), skip_program_trading=True)

    assert picks == [] and results == [] and sell is None
