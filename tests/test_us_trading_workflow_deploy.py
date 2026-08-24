"""us_trading.yml의 배포 스텝은 국내 trading.yml과 달리 `data/*.json` 전체가
아니라 심마다 상태·CSV 파일명을 정적으로 나열한다. US Sim2를 추가하면서 이
목록에 없어 db-data로 안 나가는 걸 직접 겪었다 — 심을 추가할 때마다 여기도
같이 갱신해야 한다는 걸 잊기 쉬운 자리라, 매니페스트에서 파생해 검증한다.
"""
import os

from src.strategy.us_registry import get_us_sim_registry

WF = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows', 'us_trading.yml')


def test_us_trading_deploys_every_registered_sims_files():
    with open(WF, encoding='utf-8') as f:
        deploy = f.read().split('Deploy state (db-data)', 1)[1]

    for entry in get_us_sim_registry():
        assert entry['state_file'] in deploy, (
            f"{entry['state_file']}이 us_trading.yml 배포 스텝에 없다 — "
            f"이 심의 상태가 컨테이너 종료와 함께 사라진다")
        assert entry['csv_file'] in deploy, (
            f"{entry['csv_file']}이 us_trading.yml 배포 스텝에 없다 — "
            f"이 심의 매매기록이 db-data에 영영 도달하지 못한다")
