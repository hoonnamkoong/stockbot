"""us_trading.yml의 배포 목록이 등록된 US 심 전원을 담는지.

예전에는 배포 스텝이 심마다 상태·CSV **파일명을 정적으로 나열**했다. US Sim2를
추가하면서 그 목록에 없어 db-data로 안 나가는 걸 직접 겪었고, 그래서 이 테스트가
워크플로 본문에서 파일명을 찾았다.

2026-11-27에 그 나열을 없앴다 — 목록을 등록부에서 파생시킨다
(`scripts/us_db_data_files.py --deploy`). 그러니 본문에서 파일명을 찾는 검사는
의미가 없어졌다(찾을 이름이 없는 게 정상이다). 같은 보장은
`tests/test_us_trading_db_data_scope.py`가 **생성기 출력**으로 지킨다 — 워크플로가
실제로 소비하는 것이 그쪽이라 더 가깝다.

여기 남긴 것은 **배선** 검사다: 워크플로가 그 생성기를 부르고 있는가.
생성기가 옳아도 워크플로가 안 부르면 아무 보장이 없다.
"""
import os

WF = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows',
                  'us_trading.yml')


def _deploy_step() -> str:
    with open(WF, encoding='utf-8') as f:
        return f.read().split('Deploy state (db-data)', 1)[1]


def test_us_trading_derives_its_deploy_list_from_the_registry():
    deploy = _deploy_step()
    assert 'us_db_data_files.py --deploy' in deploy, (
        '배포 목록을 등록부에서 파생하지 않는다 — 심을 추가하면 그 심의 상태만 '
        '조용히 안 올라간다(US Sim2에서 겪은 그 자리다)')
    assert 'cp data/sim_us1minervini_state.json' not in deploy, (
        '파일명을 박은 cp가 돌아왔다 — 심 추가 때 같이 갱신해야 하는 자리가 '
        '다시 생긴다')


def test_us_trading_deploys_the_alert_dedup_state():
    """알림 쿨다운 상태(`data/alert_dedup.json`)도 db-data를 왕복해야 한다.

    `send_alert_once(cooldown_min=60)`은 마지막 발송 시각을 이 파일에 적는다.
    us_trading은 태스커 경로로 **2분마다** 새 컨테이너에서 도는데, 이 파일이
    안 올라가면 매 런이 빈 상태로 시작해 쿨다운이 한 번도 적용되지 않는다 —
    2026-09-01에 워치리스트 결손 알림이 세션 내내 2분 간격으로 나갔다.

    도배는 침묵과 같다: 사람이 알림을 꺼버리면 다음 장애는 아무도 못 본다.

    이름이 생성기 출력에 있는지는 scope 테스트가 보고, 여기서는 **병합으로**
    올리는지를 본다 — 덮어쓰면 KR·스크래퍼의 억제 기록이 사라진다.
    """
    deploy = _deploy_step()
    assert 'merge_alert_dedup.py' in deploy, (
        '쿨다운을 병합이 아니라 덮어쓰면 다른 writer의 억제 기록이 사라진다')
