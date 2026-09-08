"""시뮬레이터 동기화도 자기 예산 안에서 끝나야 한다.

2026-09-08에 실전매매 런 넷이 잡 타임아웃(3분)에 잘렸다. 주문 루프에는 이미
자체 데드라인(_ORDER_LOOP_DEADLINE_SEC)이 있어서 멀쩡했고(매매 18.6초), 그
**뒤에** 도는 이 스테이지가 156초를 태우고 끝내 안 닫혔다.

잘리는 것과 스스로 비켜주는 것은 다르다.
  - 잘리면 잡이 cancelled가 되고, 뒤에 있는 배포 스텝이 통째로 죽는다.
    그 사이클의 심 상태가 db-data에 안 올라간다.
  - 잘리면 실패 알림이 나간다(게이트가 `job.status != 'success'`).
  - 스스로 비켜주면 남은 심은 다음 사이클이 돈다. 60초마다 다시 오므로
    한 사이클을 미루는 비용은 작다.

KIS 연결 차단기(test_kis_connection_breaker.py)는 "연결이 안 되는" 경우만
줄인다. 서버가 **느리게 대답하는** 경우는 차단기가 안 걸리므로 이 데드라인이
아니면 못 막는다.
"""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.workers.trade_engine import TradeEngineWorker


class _Sim:
    IS_ANALYZER = False
    IS_EOD = False

    def __init__(self, name):
        self._name = name
        self.state = {'portfolio': {}}
        self.state_file = f'{name}.json'
        self.ran = False

    def get_universe(self):
        return []

    def run(self, candidates, current_prices=None):
        self.ran = True

    @property
    def __class__(self):          # 로그가 클래스 이름을 쓴다
        return type(self._name, (), {})


def _worker(logs):
    ctx = mock.Mock()
    ctx.log = lambda m: logs.append(str(m))
    w = TradeEngineWorker(ctx, storage=mock.Mock())
    w.log = lambda m: logs.append(str(m))
    w.log_error = lambda m: logs.append(f'ERROR {m}')
    return w


def _clock(jump_after_first: float):
    """첫 심을 돈 직후 시간이 확 뛴 것처럼 보이게 한다."""
    ticks = [0.0, 0.0, 0.0, 0.0]
    ticks += [jump_after_first] * 200
    return iter(ticks).__next__


@pytest.fixture
def sims():
    return [_Sim('SimA'), _Sim('SimB'), _Sim('SimC')]


def test_예산을_넘기면_남은_심을_다음_사이클로_미룬다(sims, monkeypatch):
    logs = []
    w = _worker(logs)
    over = TradeEngineWorker.SYNC_STAGE_DEADLINE_SEC + 1

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=sims), \
         mock.patch.object(TradeEngineWorker, '_enrich_universe', lambda self, p: p), \
         mock.patch('src.pipeline.workers.trade_engine.time.monotonic',
                    side_effect=_clock(over)):
        w._run_simulators([], allow_price_fallback=False)

    assert sims[0].ran, '첫 심은 예산 안에서 돌았어야 한다'
    assert not sims[1].ran and not sims[2].ran, '예산을 넘긴 뒤에는 멈춰야 한다'


def test_비켜준_사실을_로그에_남긴다(sims, monkeypatch):
    """스킵과 미발화가 같은 모양이면 안 된다 — 왜 안 돌았는지 남는다."""
    logs = []
    w = _worker(logs)
    over = TradeEngineWorker.SYNC_STAGE_DEADLINE_SEC + 1

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=sims), \
         mock.patch.object(TradeEngineWorker, '_enrich_universe', lambda self, p: p), \
         mock.patch('src.pipeline.workers.trade_engine.time.monotonic',
                    side_effect=_clock(over)):
        w._run_simulators([], allow_price_fallback=False)

    assert any('데드라인' in m for m in logs), logs


def test_예산_안이면_전부_돈다(sims, monkeypatch):
    """데드라인이 정상 사이클을 자르면 그게 더 큰 사고다."""
    logs = []
    w = _worker(logs)

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=sims), \
         mock.patch.object(TradeEngineWorker, '_enrich_universe', lambda self, p: p), \
         mock.patch('src.pipeline.workers.trade_engine.time.monotonic',
                    side_effect=_clock(1.0)):
        w._run_simulators([], allow_price_fallback=False)

    assert all(s.ran for s in sims)


def test_예산이_잡_타임아웃보다_짧다():
    """예산이 잡 예산보다 길면 데드라인은 아무것도 막지 못한다.

    trading.yml의 timeout-minutes는 3이고, 이 스테이지 앞뒤로 체크아웃·의존성
    설치·토큰·매매·배포가 함께 그 3분을 쓴다. 여유 없이 잡으면 데드라인을
    지켰는데도 잘린다."""
    assert TradeEngineWorker.SYNC_STAGE_DEADLINE_SEC <= 120
