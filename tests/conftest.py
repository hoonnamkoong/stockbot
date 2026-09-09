import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture(autouse=True)
def _isolate_alert_dedup(tmp_path, monkeypatch):
    """알림 쿨다운 상태를 테스트마다 격리한다.

    src/alerts.py는 "같은 장애로 2분마다 울리지 않는다"를 data/alert_dedup.json에
    기록해서 지킨다. 격리하지 않으면 두 가지가 깨진다.
      1. 레포의 실제 data/ 에 파일이 생겨 작업 트리를 더럽힌다.
      2. 앞 테스트가 남긴 쿨다운 때문에 뒤 테스트의 알림이 억제되어, 테스트가
         실행 순서에 따라 통과했다 실패했다 한다(2026-08-08에 실제로 겪었다).
    """
    monkeypatch.setattr('src.alerts.DEFAULT_DATA_DIR', str(tmp_path / 'alert_state'))
    # "이 런이 쿨다운을 기록했는가"도 프로세스 상태다. 안 되돌리면 앞 테스트가
    # 켜둔 플래그 때문에 뒤 테스트가 배포 목록에 알림 파일을 넣는다.
    monkeypatch.setattr('src.alerts._state_written', False)


@pytest.fixture(autouse=True)
def _reset_kis_connection_breaker(monkeypatch):
    """KIS 연결 차단기도 프로세스 상태다 — 위 쿨다운과 같은 계열의 누수다.

    KISDataProvider._conn_fail_streak는 클래스 레벨이라(program_trader가 매 호출
    새 인스턴스를 만들기 때문에 그래야 한다) 앞 테스트가 올려둔 값이 남는다.
    임계를 넘긴 채로 넘어오면 뒤 테스트의 KIS 호출이 네트워크를 아예 안 타고
    {}를 받는다 — 실행 순서에 따라 통과했다 실패했다 하게 된다.
    """
    from src.trade.kis_data_provider import KISDataProvider
    monkeypatch.setattr(KISDataProvider, '_conn_fail_streak', 0)


@pytest.fixture(autouse=True)
def _reset_net_breaker(monkeypatch):
    """src.core.net의 대상별 차단기도 프로세스 상태다 — 위 KIS 차단기와 같은 계열.

    2026-09-09에 실제로 겪었다: 네이버 실패를 만드는 테스트가 차단기를 열어 두면
    **다음 테스트의 정상 경로가 0회 호출**이 되고, 성공을 검증하는 테스트에
    `{'breaker_open': 9}`가 찍힌다. 대상 키가 테스트마다 다르므로 통째로 비우는
    것이 맞다 — 남겨서 의미가 있는 상태가 아니다.
    """
    from src.core import net
    monkeypatch.setattr(net, '_STREAKS', {})
    monkeypatch.setattr(net, '_OPENED_AT', {})
