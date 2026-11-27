"""장중 루프의 잡 타임아웃이 워치리스트 상한을 감당하는지 검증한다.

이 둘은 서로 다른 파일에 있으면서 묶여 있다 — MAX_WATCHLIST를 올리면 한 사이클
조회 시간이 늘고, 타임아웃을 안 올리면 잡이 취소된다. 배포 스텝이 마지막이라
취소되면 그 사이클의 판단이 통째로 db-data에 안 올라간다(매수를 결정했든 말든).

2026-08-26에 실제로 걸렸다: 워치리스트가 처음 만들어져 930종목이 되자 조회만
4분이 됐다. 상한 300으로 줄인 뒤에도 배포 충돌(push 실패 → unshallow → rebase,
실측 142초)과 겹치면 4분을 넘겼다.

숫자는 전부 실측이다(추정이 아니다):
  - 종목당 0.26초: 2026-08-26 EOD 런 998종목 406초 중 슬립 150초 제외
  - 셋업 23초: 같은 날 run 32980165050 스텝별 소요

2026-11-27: 배포 충돌 경로가 **142초에서 바뀌었다.** `fetch --unshallow` + rebase를
걷어내고 부분 clone 재시도(최대 3회)로 바꿨다 — unshallow는 부분 clone을 되돌려
130MB를 다시 받으므로 그 자리에 둘 수 없다. 아래 상수는 그래서 **로컬 실측 기반의
보수적인 값**이다(부분 clone 약 2초 × 3회 + 커밋·푸시). 병합 후 첫 충돌 런의
스텝 소요로 바꿀 것.
"""
import math
import os

import yaml

from src.strategy.simulators.us_sim2_donchian import MAX_WATCHLIST

WF = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows', 'us_trading.yml')

SEC_PER_SYMBOL = 0.26
SETUP_SEC = 23            # checkout + setup-python + pip + db-data fetch
DEPLOY_WORST_SEC = 60     # 부분 clone 재시도 3회(로컬 실측 약 2초/회) + 커밋·푸시
                          # 셋업 23초에도 db-data fetch가 끼어 있었다(42초 → 2초).
                          # 그 쪽은 실측이 나올 때까지 23초를 그대로 둔다 — 줄여 적으면
                          # 타임아웃을 낮출 근거가 되는데, 아직 CI에서 재지 않았다.
# run_cycle은 심마다 따로 조회한다(심 간 중복 제거 없음).
# US Sim1 ~18 + US Sim3 20 + 보유 ~15 = 55, 여기에 US Sim4의 최악(월 1회 교체
# 사이클): 감시목록 80 + 보유 40 = 120. 평소에는 보유 40만 조회한다.
OTHER_SIM_SYMBOLS = 175


def test_job_timeout_covers_watchlist_worst_case():
    with open(WF, encoding='utf-8') as f:
        wf = yaml.safe_load(f)
    timeout_min = next(iter(wf['jobs'].values()))['timeout-minutes']

    symbols = MAX_WATCHLIST + OTHER_SIM_SYMBOLS
    worst_sec = symbols * SEC_PER_SYMBOL + SETUP_SEC + DEPLOY_WORST_SEC
    need_min = math.ceil(worst_sec / 60)

    assert timeout_min >= need_min, (
        f'MAX_WATCHLIST={MAX_WATCHLIST}면 최악 {worst_sec:.0f}초({need_min}분)가 드는데 '
        f'타임아웃이 {timeout_min}분이다 — 사이클이 통째로 유실된다')
