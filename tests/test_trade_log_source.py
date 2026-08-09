"""매매 기록의 소스는 CSV 하나다 — 옛 JSON 사본이 그것을 가리지 못한다.

2026-08-09 점검에서 나온 것: `_load_trade_logs`가 `sim_<name>_log.json`이
있으면 **CSV보다 우선**했다. 그런데 그 파일을 쓰는 코드는 이미 없다(base_simulator는
reset에서 지우기만 한다). 즉 writer 없는 파일이 reader를 가로채는 구조였고,
어느 배포 목록·제외 목록에도 없어서 누가 올려도 아무도 몰랐다.

승률·수익률이 이 함수에서 나오므로, 가려진 순간 대시보드의 성과 숫자가 통째로
낡은 사본이 된다. main·db-data 어디에도 실제 파일은 없었지만(확인함), 구조가
그렇게 열려 있는 것 자체가 문제다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators.base_simulator import BaseSimulator  # noqa: E402

CSV = ('timestamp,symbol,action,price,quantity,total_amount\n'
       '2026-08-10 10:00:00,삼성전자(005930),BUY,70000,10,700000\n')


def _sim(tmp_path):
    sim = BaseSimulator.__new__(BaseSimulator)
    sim.name = 'LogSource'
    sim.state_file = os.path.join(tmp_path, 'sim_logsource_state.json')
    sim.log_file = os.path.join(tmp_path, 'sim_logsource_log.json')
    sim.csv_file = os.path.join(tmp_path, 'trade_history_sim_logsource.csv')
    return sim


def test_reads_the_csv(tmp_path):
    sim = _sim(tmp_path)
    with open(sim.csv_file, 'w', encoding='utf-8') as f:
        f.write(CSV)

    logs = sim._load_trade_logs()

    assert [(r['code'], r['quantity']) for r in logs] == [('005930', 10)]


def test_a_stale_json_copy_does_not_shadow_the_csv(tmp_path):
    """writer가 없는 파일이 reader를 가로채면, 그 심의 성과는 영영 안 움직인다."""
    sim = _sim(tmp_path)
    with open(sim.csv_file, 'w', encoding='utf-8') as f:
        f.write(CSV)
    with open(sim.log_file, 'w', encoding='utf-8') as f:
        f.write('[{"code": "000000", "action": "BUY", "price": 1, '
                '"quantity": 999, "amount": 999, "timestamp": "2020-01-01"}]')

    logs = sim._load_trade_logs()

    assert [r['code'] for r in logs] == ['005930'], '옛 JSON 사본이 CSV를 가렸다'
