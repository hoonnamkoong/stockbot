from src.strategy.us_registry import get_us_sim_registry, get_active_us_simulators, get_us_simulator_by_id


def test_get_us_sim_registry_has_sim1():
    reg = get_us_sim_registry()
    assert len(reg) == 3
    entry = reg[0]
    assert entry['id'] == 'us_sim1_minervini'
    assert entry['currency'] == 'USD'
    assert entry['state_file'] == 'sim_us1minervini_state.json'


def test_get_us_sim_registry_has_sim2():
    reg = get_us_sim_registry()
    entry = next(e for e in reg if e['id'] == 'us_sim2_donchian')
    assert entry['currency'] == 'USD'
    assert entry['state_file'] == 'sim_us2donchian_state.json'


def test_get_active_us_simulators_instantiates():
    sims = get_active_us_simulators()
    assert len(sims) == 3
    names = {s.name for s in sims}
    assert names == {'Us1Minervini', 'Us2Donchian', 'Us3Liquidity'}


def test_get_us_sim_registry_has_sim3_baseline():
    reg = get_us_sim_registry()
    entry = next(e for e in reg if e['id'] == 'us_sim3_liquidity')
    assert entry['currency'] == 'USD'
    assert entry['state_file'] == 'sim_us3liquidity_state.json'
    # 기준선 심은 잣대라 매매 대상이 아니다
    assert entry['tradeable'] is False


def test_get_us_simulator_by_id_unknown_returns_none():
    assert get_us_simulator_by_id('nope') is None


def test_get_us_simulator_by_id_known():
    sim = get_us_simulator_by_id('us_sim1_minervini')
    assert sim is not None
    assert sim.name == 'Us1Minervini'
