"""scraper.yml이 매 호출마다 스크래핑(Stage 1~4)을 할지 자체 판단하는 게이트.

2026-08-06에 태스커 주기를 2분으로 낮추면서 trading_lite.yml(2분, 매매 전용)과
scraper.yml(10분, 스크래핑 포함)을 물리적으로 분리했는데, 2026-08-07에 태스커가
`tasker_trigger` 이벤트 **하나만** 2분마다 보낸다는 게 드러났다 —
`tasker_trigger_trade`(trading_lite 전용)를 별도로 보낼 방법이 실전 태스커 설정에는
없었다. 그래서 두 워크플로가 같은 이벤트를 듣게 하고, scraper.yml이 매 호출(2분)
받되 내부에서 "지금이 스크래핑할 차례인가"를 판정해 아닐 때는 곧바로 종료한다.

Stage 0(국면 갱신)도 이 게이트 뒤에 둔다 — 국면은 사이클당 한 번만 갱신돼야
하고(trade_engine.run_regime_stage docstring 참고, top100 breadth가 종목당 1콜),
매매(Stage 0.5)는 trading_lite.yml이 같은 이벤트로 독립적으로 이미 처리하므로
scraper.yml이 오프틱에 다시 시도할 이유가 없다.

판정은 순수 함수로 뺐다 — GH Actions 없이, 시간만 바꿔가며 테스트한다.
"""
import json
import os
from datetime import datetime

SCRAPE_INTERVAL_MIN = 10   # 2026-08-06 합의 — 버즈 필요 심 신선도를 여기서 지킨다.
MIN_GAP_MIN = SCRAPE_INTERVAL_MIN / 2   # 연속 스크래핑 바닥(is_scrape_due 주석 참고)

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data')
_STATE_FILENAME = 'scrape_gate_state.json'


def _state_path(data_dir: str | None) -> str:
    return os.path.join(data_dir or DEFAULT_DATA_DIR, _STATE_FILENAME)


def _slot(now_kst: datetime) -> int:
    """벽시계를 SCRAPE_INTERVAL_MIN 폭으로 자른 격자 번호.

    경과 시간이 아니라 격자로 판정하는 이유(2026-08-08 실측 회귀):
    "직전 스크래핑으로부터 10분"으로 재면 기준점이 런 시작 시각인데, 그건
    디스패치 시각 + 워크플로 셋업(체크아웃·pip·토큰, 실측 약 52초)이고 이 셋업
    시간이 런마다 몇 초씩 흔들린다. 트리거가 2분 격자라 경과가 9분 5x초로
    계산되는 순간 다음 스크래핑이 12분 뒤로 밀리고, **한 번 밀리면 정각으로
    영영 돌아오지 못한다**. 08-07에 실제로 :04 :15 :27 :40 :50 :01 … 로 흘렀다
    (08-04·08-05는 :04 :13 :23 :33 :43 :53 정확히 10분).

    격자로 재면 셋업 지터가 얼마든 각 10분 구간의 첫 트리거 하나만 통과하므로
    :00 :10 :20 … 에 고정된다. 스크래핑을 몇 번 건너뛰어도 위상이 밀리지 않는다.

    epoch를 쓰지 않는다 — naive KST datetime에 .timestamp()를 쓰면 실행 머신의
    로컬 타임존으로 해석되어 어긋난다(PipelineContext.cycle_id 주석과 같은 함정).
    날짜 서수에서 직접 분을 세면 타임존이 개입할 곳이 없다.
    """
    minutes = now_kst.toordinal() * 1440 + now_kst.hour * 60 + now_kst.minute
    return minutes // SCRAPE_INTERVAL_MIN


def is_scrape_due(now_kst: datetime, data_dir: str | None = None) -> bool:
    """지금 스크래핑(Stage 0~4 전체)을 돌 차례인가.

    상태를 못 읽으면(최초 실행, 파일 손상) 스크래핑 쪽으로 fail한다 — 여기서
    "모른다"를 "아직 아니다"로 읽으면 버즈 필요 심이 영영 갱신을 못 받을 수 있다.
    """
    try:
        with open(_state_path(data_dir), 'r', encoding='utf-8') as f:
            raw = json.load(f)
        # slot이 없는 상태 파일은 이 방식 도입 전(2026-08-08 이전) 것이다.
        # 시각에서 격자를 되계산해 이어간다 — '모른다'로 읽고 매 틱 스크래핑하면
        # 네이버 부하가 5배가 된다.
        last_at = datetime.fromisoformat(raw['last_scrape_at'])
        last_slot = raw.get('last_scrape_slot')
        if last_slot is None:
            last_slot = _slot(last_at)
    except Exception:
        return True

    # 부등호가 아니라 '다른 격자인가'로 묻지 않는다. 시계가 뒤로 간 경우(미래
    # 타임스탬프)에 무리하게 스크래핑을 강제하지 않으려면 전진만 허용해야 한다.
    if _slot(now_kst) <= int(last_slot):
        return False

    # 격자만으로는 경계 직전에 시작한 런을 못 막는다. 셋업이 평소보다 오래 걸려
    # 파이썬이 09:09:58에 시작하면, 6초 뒤 :10 트리거가 다음 격자라 곧바로 또
    # 스크래핑한다 — 네이버를 연달아 두드리는 건 이 게이트가 막으려던 바로 그
    # 동작이다. 격자 폭의 절반을 바닥으로 깐다. 이 값은 트리거 격자(2분) 근처가
    # 아니므로 셋업 지터가 판정을 뒤집지 못한다(그게 예전 방식의 실패 원인이었다).
    return (now_kst - last_at).total_seconds() / 60 >= MIN_GAP_MIN


def mark_scraped(now_kst: datetime, data_dir: str | None = None) -> None:
    """방금 스크래핑을 돌았다고 기록한다. 스크래핑 사이클 끝에서만 부른다."""
    path = _state_path(data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        # last_scrape_at은 판정에 쓰지 않는다 — 사람이 로그·db-data에서 "마지막
        # 스크래핑이 언제였나"를 읽을 수 있게 남긴다.
        json.dump({'last_scrape_slot': _slot(now_kst),
                   'last_scrape_at': now_kst.isoformat()}, f, ensure_ascii=False)
