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


def test_us_trading_deploys_the_alert_dedup_state():
    """알림 쿨다운 상태(`data/alert_dedup.json`)도 db-data를 왕복해야 한다.

    `send_alert_once(cooldown_min=60)`은 마지막 발송 시각을 이 파일에 적는다.
    us_trading은 태스커 경로로 **2분마다** 새 컨테이너에서 도는데, 이 파일이
    안 올라가면 매 런이 빈 상태로 시작해 쿨다운이 한 번도 적용되지 않는다 —
    2026-09-01에 워치리스트 결손 알림이 세션 내내 2분 간격으로 나갔다.

    도배는 침묵과 같다: 사람이 알림을 꺼버리면 다음 장애는 아무도 못 본다.
    """
    with open(WF, encoding='utf-8') as f:
        deploy = f.read().split('Deploy state (db-data)', 1)[1]

    assert 'alert_dedup.json' in deploy, (
        'alert_dedup.json이 us_trading.yml 배포 스텝에 없다 — 알림 쿨다운이 '
        '매 런 초기화되어 같은 장애가 2분마다 발송된다')
