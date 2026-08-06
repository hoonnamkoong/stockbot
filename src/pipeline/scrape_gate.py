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

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data')
_STATE_FILENAME = 'scrape_gate_state.json'


def _state_path(data_dir: str | None) -> str:
    return os.path.join(data_dir or DEFAULT_DATA_DIR, _STATE_FILENAME)


def is_scrape_due(now_kst: datetime, data_dir: str | None = None) -> bool:
    """지금 스크래핑(Stage 0~4 전체)을 돌 차례인가.

    상태를 못 읽으면(최초 실행, 파일 손상) 스크래핑 쪽으로 fail한다 — 여기서
    "모른다"를 "아직 아니다"로 읽으면 버즈 필요 심이 영영 갱신을 못 받을 수 있다.
    """
    try:
        with open(_state_path(data_dir), 'r', encoding='utf-8') as f:
            raw = json.load(f)
        last = datetime.fromisoformat(raw['last_scrape_at'])
    except Exception:
        return True

    elapsed_min = (now_kst - last).total_seconds() / 60
    return elapsed_min >= SCRAPE_INTERVAL_MIN


def mark_scraped(now_kst: datetime, data_dir: str | None = None) -> None:
    """방금 스크래핑을 돌았다고 기록한다. 스크래핑 사이클 끝에서만 부른다."""
    path = _state_path(data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'last_scrape_at': now_kst.isoformat()}, f, ensure_ascii=False)
