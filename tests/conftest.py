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
