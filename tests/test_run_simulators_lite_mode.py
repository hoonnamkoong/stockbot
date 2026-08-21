"""lite 경로(_run_simulators)는 네이버를 두드리지 않고, 모르는 가격을 0으로 읽지 않는다.

_run_simulators([])를 그대로 부르면 보유 종목 현재가가 전부 '미확보'로 잡혀
_fetch_portfolio_prices()가 finance.naver.com을 직접 스크래핑한다
(trade_engine.py:613-641). "스크래핑을 하지 않는다"가 전제인 2분 주기 경로에서
이게 살아 있으면 네이버를 5배 빈도로 두드리게 된다.

그리고 가격을 못 구했을 때 0을 넘기면 심은 −100% 손실로 읽고 손절을 낸다.
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.trade_engine import TradeEngineWorker


class _FakeCtx:
    now_kst = datetime(2026, 8, 6, 11, 0, tzinfo=timezone(timedelta(hours=9)))

    def is_buy_window(self):
        return True

    def is_market_hours(self):
        return True

    def should_notify(self):
        return False

    def log(self, msg):
        pass


class _FakeSim:
    IS_ANALYZER = False
    IS_EOD = False

    def __init__(self, portfolio=None, universe=None):
        self.state = {'portfolio': portfolio or {}}
        self._universe = universe
        self.ran_with = None

    def get_universe(self):
        return self._universe

    def run(self, candidates, current_prices=None):
        self.ran_with = {'candidates': candidates, 'prices': current_prices}


def _worker():
    return TradeEngineWorker(_FakeCtx(), mock.MagicMock())


def test_lite_mode_never_calls_naver_fallback():
    """보유 종목 현재가가 없어도 네이버 조회를 하지 않는다(KIS 단건 조회는 별개)."""
    sim = _FakeSim(portfolio={'005930': {}})
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[sim]), \
         mock.patch.object(w, '_fetch_portfolio_prices') as naver, \
         mock.patch.object(w, '_fetch_kis_prices', return_value={}):
        w._run_simulators([], allow_price_fallback=False)

    naver.assert_not_called()


def test_default_mode_still_uses_naver_fallback():
    """기존 10분 경로의 동작은 그대로다."""
    sim = _FakeSim(portfolio={'005930': {}})
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[sim]), \
         mock.patch.object(w, '_fetch_portfolio_prices', return_value={'005930': 70000}) as naver:
        w._run_simulators([])

    naver.assert_called_once()


def test_lite_mode_skips_sim_whose_holding_price_is_unknown():
    """KIS 단건 보강도 실패하면 0으로 넘기지 않고 그 심을 건너뛴다 (허위 손절 방지)."""
    sim = _FakeSim(portfolio={'005930': {}})
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[sim]), \
         mock.patch.object(w, '_fetch_kis_prices', return_value={}) as kis:
        w._run_simulators([], allow_price_fallback=False)

    kis.assert_called_once_with(['005930'])
    assert sim.ran_with is None, '현재가를 모르는 채로 심을 돌리면 안 된다'


def test_lite_mode_kis_backfill_recovers_blind_holding():
    """보유 종목이 그날 자체 유니버스 밖으로 밀려나도, KIS 단건 조회가 가격을
    채워주면 그 사이클에 정상적으로 돈다 — 2026-08-19 23:57 lite 전환 이후
    심2/4/8/9가 랭킹 밖 보유 종목 하나 때문에 영구히 멈췄던 회귀의 재발 방지."""
    sim = _FakeSim(portfolio={'005935': {}})
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[sim]), \
         mock.patch.object(w, '_fetch_kis_prices',
                           return_value={'005935': 68000}) as kis:
        w._run_simulators([], allow_price_fallback=False)

    kis.assert_called_once_with(['005935'])
    assert sim.ran_with is not None
    assert sim.ran_with['prices']['005935'] == 68000


def test_lite_mode_runs_sim_when_own_universe_covers_holdings():
    """자체 유니버스가 보유 종목 가격을 채워주면 정상 실행한다."""
    sim = _FakeSim(portfolio={'005930': {}},
                   universe=[{'code': '005930', 'price': 71000}])
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[sim]), \
         mock.patch.object(w, '_enrich_universe', side_effect=lambda x: x):
        w._run_simulators([], allow_price_fallback=False)

    assert sim.ran_with is not None
    assert sim.ran_with['prices']['005930'] == 71000


def test_lite_mode_runs_sim_with_no_holdings():
    """보유가 없으면 막을 이유가 없다."""
    sim = _FakeSim(portfolio={}, universe=[{'code': '000660', 'price': 200000}])
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[sim]), \
         mock.patch.object(w, '_enrich_universe', side_effect=lambda x: x):
        w._run_simulators([], allow_price_fallback=False)

    assert sim.ran_with is not None


def test_fetch_kis_prices_uses_kis_quote_not_naver():
    """_fetch_kis_prices는 KISDataProvider.get_price_quote로 가격을 채운다."""
    w = _worker()
    fake_provider = mock.MagicMock()
    fake_provider.get_price_quote.side_effect = [
        {'price': 68000}, {'price': 0}, {},
    ]
    w._kis_provider = fake_provider

    with mock.patch('time.sleep'):
        result = w._fetch_kis_prices(['005935', '000660', '005930'])

    assert result == {'005935': 68000}, '가격이 0이거나 없는 응답은 채우지 않는다'
    assert fake_provider.get_price_quote.call_count == 3


def test_fetch_kis_prices_survives_per_code_exception():
    """한 종목 조회가 예외를 던져도 나머지 종목은 계속 조회한다."""
    w = _worker()
    fake_provider = mock.MagicMock()
    fake_provider.get_price_quote.side_effect = [
        Exception('boom'), {'price': 71000},
    ]
    w._kis_provider = fake_provider

    with mock.patch('time.sleep'):
        result = w._fetch_kis_prices(['005930', '000660'])

    assert result == {'000660': 71000}


def test_only_sim_id_runs_just_that_one():
    """lite는 실전 선택 심의 페이퍼 쌍둥이 하나만 돌린다."""
    picked = _FakeSim(universe=[{'code': '000660', 'price': 200000}])
    w = _worker()

    with mock.patch('src.strategy.registry.get_simulator_by_id',
                    return_value=picked) as by_id, \
         mock.patch('src.pipeline.workers.trade_engine.get_active_simulators') as all_sims, \
         mock.patch.object(w, '_enrich_universe', side_effect=lambda x: x):
        w._run_simulators([], only_sim_id='sim4_bull_daytrading',
                          allow_price_fallback=False)

    by_id.assert_called_once_with('sim4_bull_daytrading')
    all_sims.assert_not_called()
    assert picked.ran_with is not None


def test_only_sim_id_missing_is_not_fatal():
    """선택 심을 못 만들어도 예외로 파이프라인을 죽이지 않는다."""
    w = _worker()

    with mock.patch('src.strategy.registry.get_simulator_by_id', return_value=None):
        w._run_simulators([], only_sim_id='nonexistent_sim')



# ── 파일당 writer 하나 (2026-08-08) ──────────────────────────────────
# 실전 선택 심의 페이퍼 쌍둥이는 trading.yml이 60초마다 갱신하고 배포한다.
# 스크래퍼가 같은 심을 자기 스냅샷(런 시작 시점)에서 다시 돌려 data/*.json을
# 통째로 밀면 그 4~5분치 페이퍼 매매가 되돌아간다(lost update). 워크플로는
# 초록색이고 숫자만 과거로 간다. 심을 상태 파일로 식별하는 이유: 같은 클래스가
# 여러 번 등장할 수 있고(파라미터만 다른 변형), 매니페스트의 신원은 파일이다.

class _NamedSim(_FakeSim):
    def __init__(self, state_file, **kw):
        super().__init__(**kw)
        self.state_file = os.path.join('/repo/data', state_file)


def test_the_sim_owned_by_trading_yml_is_not_run_here():
    mine = _NamedSim('sim_bulldaytrade_state.json')
    other = _NamedSim('sim_psych_state.json')
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[mine, other]):
        w._run_simulators([], exclude_sim_id='sim4_bull_daytrading')

    assert mine.ran_with is None, 'trading.yml이 소유한 심을 스크래퍼가 또 돌렸다'
    assert other.ran_with is not None, '나머지 심은 여기서 돌아야 한다'


def test_nothing_is_excluded_when_no_owner_is_given():
    """소유권 판정 불가(None)면 trading.yml도 그 심을 안 돌린다 — 여기서 빼면
    아무도 안 돌려 페이퍼가 멈춘다."""
    mine = _NamedSim('sim_bulldaytrade_state.json')
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[mine]):
        w._run_simulators([], exclude_sim_id=None)

    assert mine.ran_with is not None


# ── exclude_sim_ids / include_only_sim_ids (2026-08-19) ────────────────
# 버즈 불필요 심 전체(Sim2,3,4,6,8,9 등)를 trading.yml의 60초 루프로 옮기면서
# 필요해진 것들. exclude_sim_id(단일)의 다중판이 scraper.yml 쪽에서, 그
# 역(포함만) 버전이 trading.yml 쪽에서 쓰인다.

def test_exclude_sim_ids_excludes_the_whole_set():
    a = _NamedSim('sim_spillover_state.json')
    b = _NamedSim('sim_risk_state.json')
    c = _NamedSim('sim_psych_state.json')
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[a, b, c]):
        w._run_simulators([], exclude_sim_ids={'sim_spillover', 'sim_risk'})

    assert a.ran_with is None
    assert b.ran_with is None
    assert c.ran_with is not None


def test_exclude_sim_id_and_exclude_sim_ids_combine():
    """단일 exclude_sim_id와 복수 exclude_sim_ids를 같이 줘도 합집합으로 제외된다."""
    a = _NamedSim('sim_spillover_state.json')
    b = _NamedSim('sim_bulldaytrade_state.json')
    c = _NamedSim('sim_psych_state.json')
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[a, b, c]):
        w._run_simulators([], exclude_sim_id='sim4_bull_daytrading',
                          exclude_sim_ids={'sim_spillover'})

    assert a.ran_with is None
    assert b.ran_with is None
    assert c.ran_with is not None


def test_include_only_sim_ids_runs_just_that_set():
    a = _NamedSim('sim_spillover_state.json')
    b = _NamedSim('sim_risk_state.json')
    c = _NamedSim('sim_psych_state.json')
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[a, b, c]):
        w._run_simulators([], include_only_sim_ids={'sim_spillover', 'sim_risk'})

    assert a.ran_with is not None
    assert b.ran_with is not None
    assert c.ran_with is None


def test_include_only_sim_ids_empty_set_runs_nothing():
    """빈 집합은 'None(필터 없음)'과 다르다 — '아무도 포함되지 않았다'로 읽는다."""
    a = _NamedSim('sim_spillover_state.json')
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[a]):
        w._run_simulators([], include_only_sim_ids=set())

    assert a.ran_with is None


def test_include_only_sim_ids_none_does_not_filter():
    """None(기본값)은 기존 동작 그대로 — 전 심이 돈다."""
    a = _NamedSim('sim_spillover_state.json')
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[a]):
        w._run_simulators([], include_only_sim_ids=None)

    assert a.ran_with is not None
