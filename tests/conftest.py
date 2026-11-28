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


@pytest.fixture(autouse=True)
def _no_real_telegram(monkeypatch):
    """실제 텔레그램 발송을 전 테스트에서 막는다.

    attach_holding_history가 보유 종목이 있는 모든 비-EOD 심에서 돌고, 공급 실패 시
    알림을 보낸다. 이 개발 머신에는 운영 환경변수가 있을 수 있어서, 막지 않으면
    엔진 경로를 타는 테스트 하나가 진짜 메시지를 쏜다(CI는 시크릿이 없어 조용히
    통과하므로 초록이어도 안전하다는 증거가 못 된다).

    `src.alerts._telegram_manager`가 아니라 그 안에서 import하는 **클래스**를 바꾼다 —
    휴장 판정 알림 테스트들이 `src.telegram_manager.TelegramManager`를 직접 갈아끼우는데,
    `_telegram_manager`를 통째로 바꾸면 그 테스트들의 fake가 우회돼 깨진다.
    **범위**: 이 클래스 교체는 alerts 경로(함수 안 import)만 막는다. `notifier.py`처럼
    TelegramManager를 모듈 레벨로 바인딩한 곳은 못 막으므로, 모든 발송의 단일 HTTP 관문인
    `src.core.notify._post`도 같이 막는다(아래 `_no_real_http_post`).
    기본 동작은 자격증명이 없는 CI와 같다: send_message가 False를 돌려준다(True면
    "알림이 나갔다"가 기록돼 쿨다운 파일이 배포 목록에 들어간다). 개별 테스트가
    자기 fake를 setattr하면 이 기본값을 덮어쓴다.
    """
    class _NullTelegramManager:
        def __init__(self, *a, **k):
            pass

        def send_message(self, *a, **k):
            return False

    monkeypatch.setattr('src.telegram_manager.TelegramManager', _NullTelegramManager)


@pytest.fixture(autouse=True)
def _no_real_http_post(monkeypatch):
    """텔레그램 발송의 단일 HTTP 관문을 막는다. 연결 실패와 같은 OSError라 send는 False를
    돌려주고(자격증명 없는 CI와 동일), 알림은 예외를 올리지 않는다. notify 자체 테스트는
    `_post`를 스스로 덮으므로 영향이 없다."""
    def _blocked(*a, **k):
        raise OSError('테스트에서 실제 HTTP 발송 차단')
    monkeypatch.setattr('src.core.notify._post', _blocked)


@pytest.fixture(autouse=True)
def _reset_holding_alert_flag(monkeypatch):
    """보유 이력 공급 실패 알림의 '프로세스당 한 번' 플래그도 프로세스 상태다 — 앞 테스트가
    켜 두면 뒤 테스트의 알림이 억제된다."""
    monkeypatch.setattr('src.trade.holding_history._alert_attempted', False)


@pytest.fixture(autouse=True)
def _no_real_kis_provider(monkeypatch):
    """보유 이력 공급자 생성 지점에서 실제 KISDataProvider(인증·토큰 호출)를 막는다.

    엔진 경로 테스트가 보유 종목을 가진 fake 심을 돌리면 make_kis_provider가
    실제 공급자를 만들어 get_access_token까지 간다. 개별 테스트가 덮어쓸 수 있다.
    """
    class _NullProvider:
        def get_daily_history(self, code, days=25):
            return []

    monkeypatch.setattr('src.trade.holding_history.make_kis_provider',
                        lambda: _NullProvider())
