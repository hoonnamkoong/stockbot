"""스크래핑을 돌 차례인지 판정하는 게이트.

**writer는 scraper.yml(성공적으로 끝낸 런), reader는 trade_loop 하나다.**
태스커 → trading.yml → (여기가 due라고 하면) scraper.yml dispatch.

기록을 dispatch 시점이 아니라 **완료 시점**에 하는 것이 중요하다. 실패한
스크래핑은 기록을 남기지 않으므로 다음 틱에 자동으로 재시도된다 — 순서를
뒤집으면 그 재시도가 사라지고, 실패한 사이클이 10분을 통째로 버린다.

국면 갱신도 같은 격자를 쓴다(trade_loop). 이유는 비용이 아니라 **평활 시간상수**다
— 국면은 최근 5회 관측의 과반으로 확정되므로 호출 주기가 곧 국면의 반응 속도다
(trade_engine.run_regime_stage docstring 참고). 10분 주기를 유지해야 50분치 평활이
유지된다. 라이브 breadth 수집 자체는 네이버 시총 페이지 4장·3.7초로 싸다.

판정은 순수 함수로 뺐다 — GH Actions 없이, 시간만 바꿔가며 테스트한다.
"""
import json
import os
from datetime import datetime

SCRAPE_INTERVAL_MIN = 10   # 2026-08-06 합의 — 버즈 필요 심 신선도를 여기서 지킨다.

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data')
_STATE_FILENAME = 'scrape_gate_state.json'

# 국면 갱신은 같은 10분 격자를 쓰지만 **다른 게이트다.** 상태 파일을 나눈 이유는
# writer가 다르기 때문이다: 스크래핑 게이트는 scraper.yml이 완료 시점에 쓰고,
# 국면 게이트는 trading.yml이 갱신 직후에 쓴다. 하나로 합쳐 두면 스크래퍼가
# 끝나 db-data에 반영될 때까지(셋업 50초 + 수행 4분 + 배포) 게이트가 계속 열려
# 있어, 그 사이 2분마다 들어오는 trading 런이 전부 국면을 다시 갱신한다.
# 2026-08-08 실측 재현: 09:00~09:30에 10회(격자당 3회) — 최근 5회 관측의 과반으로
# 국면을 확정하므로 평활 시간상수가 50분에서 14분으로 줄어든다.
# 예전에는 두 판정이 같은 워크플로 안에 있어 concurrency 그룹이 상호배제를
# 대신해줬다. 워크플로를 분리하면서 그 보호막이 사라졌다.
_REGIME_STATE_FILENAME = 'regime_gate_state.json'


def _state_path(data_dir: str | None, filename: str = _STATE_FILENAME) -> str:
    return os.path.join(data_dir or DEFAULT_DATA_DIR, filename)


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
        #
        # last_scrape_at은 **그 폴백일 때만** 읽는다. 판정에 쓰지도 않는 값을 먼저
        # 파싱하면, 그 값만 없는 파일에서 KeyError → except → '스크래핑' 으로 떨어져
        # 매 2분 네이버를 두드리게 된다.
        last_slot = raw.get('last_scrape_slot')
        if last_slot is None:
            last_slot = _slot(datetime.fromisoformat(raw['last_scrape_at']))
    except Exception:
        return True

    # 부등호가 아니라 '다른 격자인가'로 묻지 않는다. 시계가 뒤로 간 경우(미래
    # 타임스탬프)에 무리하게 스크래핑을 강제하지 않으려면 전진만 허용해야 한다.
    #
    # **격자가 판정의 전부다.** 예전에는 여기에 "직전 스크래핑으로부터 5분"이라는
    # 바닥값이 하나 더 있었는데, mark_scraped가 완료 시점에 불린다는 것과 맞물려
    # 오히려 위상을 밀어냈다: 스크래핑이 4~5분 걸리므로 :00 격자 런은 :04~:06에
    # 끝나고, 그러면 :10 격자와의 간격이 4~6분이라 바닥값 5분이 매 사이클 동전
    # 던지기가 된다. 걸리는 순간 :12로 밀리고, 한 번 밀리면 돌아오지 못한다
    # (2026-08-07 회귀와 같은 형태). 연속 스크래핑은 dispatch 쪽의
    # scraper_is_running()이 막는다 — 실행 중이면 애초에 부르지 않는다.
    return _slot(now_kst) > int(last_slot)


def is_regime_due(now_kst: datetime, data_dir: str | None = None) -> bool:
    """지금 국면(Sim0 리베로)을 갱신할 차례인가.

    격자는 스크래핑과 같다(같은 10분). 다른 것은 **누가 기록하는가**뿐이다 —
    이 게이트는 trading.yml이 갱신 직후에 닫으므로, 스크래퍼가 4~5분 뒤에나
    끝나는 것과 무관하게 격자당 한 번만 열린다.

    상태를 못 읽으면 갱신 쪽으로 fail한다. 국면 없이 도는 것보다 한 번 더 도는
    편이 낫다(중복 갱신은 평활을 왜곡하지만, 결측은 매매 소유권 판정 자체를
    막는다).
    """
    try:
        with open(_state_path(data_dir, _REGIME_STATE_FILENAME), 'r', encoding='utf-8') as f:
            last_slot = int(json.load(f)['last_regime_slot'])
    except Exception:
        return True
    return _slot(now_kst) > last_slot


def mark_regime(now_kst: datetime, data_dir: str | None = None) -> None:
    """방금 국면을 갱신했다고 기록한다. 갱신에 성공한 직후에만 부른다 —
    실패한 갱신을 기록하면 다음 격자까지 국면이 낡은 채로 남는다."""
    path = _state_path(data_dir, _REGIME_STATE_FILENAME)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'last_regime_slot': _slot(now_kst),
                   'last_regime_at': now_kst.isoformat()}, f, ensure_ascii=False)


def mark_scraped(now_kst: datetime, data_dir: str | None = None) -> None:
    """방금 스크래핑을 돌았다고 기록한다. 스크래핑 사이클 끝에서만 부른다."""
    path = _state_path(data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        # last_scrape_at은 격자 판정에 직접 쓰이지 않는다. 남기는 이유는 둘이다:
        # slot이 없는 옛 상태 파일에서 격자를 되계산하는 폴백(is_scrape_due), 그리고
        # 사람이 db-data에서 "마지막 스크래핑이 언제였나"를 읽을 수 있게.
        json.dump({'last_scrape_slot': _slot(now_kst),
                   'last_scrape_at': now_kst.isoformat()}, f, ensure_ascii=False)
