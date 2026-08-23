from src.strategy.us_registry import get_us_sim_registry, get_active_us_simulators, get_us_simulator_by_id


def test_get_us_sim_registry_has_sim1():
    reg = get_us_sim_registry()
    assert len(reg) == 1
    entry = reg[0]
    assert entry['id'] == 'us_sim1_minervini'
    assert entry['currency'] == 'USD'
    assert entry['state_file'] == 'sim_us1minervini_state.json'


def test_get_active_us_simulators_instantiates():
    sims = get_active_us_simulators()
    assert len(sims) == 1
    assert sims[0].name == 'Us1Minervini'


def test_get_us_simulator_by_id_unknown_returns_none():
    assert get_us_simulator_by_id('nope') is None


def test_get_us_simulator_by_id_known():
    sim = get_us_simulator_by_id('us_sim1_minervini')
    assert sim is not None
    assert sim.name == 'Us1Minervini'
