"""StockBot 실전 매매 진입점 — 태스커가 직접 부르는 워크플로의 본체.

================================================================
왜 매매가 스크래핑의 상위에 있는가
================================================================
예전에는 태스커가 scraper.yml을 부르고 그 안에서 매매가 곁다리로 돌았다.
그래서 스크래핑이 매매를 세 가지 방식으로 방해했다.

  1. concurrency 그룹이 같아, 4분짜리 스크래핑 런이 도는 동안 들어온 트리거가
     대기열에 밀려 취소됐다 — 2026-08-07 실측으로 하루 196런 중 26런(13%)이
     그렇게 사라졌고, 그만큼 매매 사이클이 통째로 없어졌다.
  2. 같은 프로세스라 스크래핑이 느려지면 매매도 같이 늦었다.
  3. 스크래퍼가 죽으면 매매도 죽었다.

이제 방향이 뒤집혔다. 태스커 → **이 워크플로** → (필요할 때만) scraper.yml.
매매가 스크래핑을 기다리지 않고, 스크래퍼가 죽어도 매매와 국면은 살아 있다.

================================================================
2분 트리거로 1분 매매를 얻는 방법
================================================================
태스커 최소 간격이 2분이다. 그런데 새 런을 띄우는 데만 셋업이 든다
(체크아웃·pip·db-data 페치). 그래서 "매분 새 런"은 물리적으로 불가능하다.

대신 런 하나가 셋업을 **한 번만** 내고 안에서 두 바퀴 돈다.

    t=0     런 시작 → 셋업
    t≈20s   1바퀴
    t≈80s   2바퀴          (TRADE_INTERVAL_SEC = 60)
    t≈85s   배포 후 종료    (LOOP_BUDGET_SEC 예산 소진)
    t=120s  다음 태스커 트리거 → 새 런

바퀴 사이 60초, 런 사이(2바퀴↔다음 런 1바퀴)도 약 60초라 간격이 고르다.
LOOP_BUDGET_SEC는 셋업+배포를 더해도 120초를 넘지 않게 잡아야 한다 — 넘으면
다음 트리거와 겹치고, 겹치면 concurrency가 하나를 취소해 사이클이 사라진다.

================================================================
여기서 하지 않는 것
================================================================
  - **스크래핑·AI·텔레그램**: scraper.yml 소관. 이 워크플로는 그걸 깨우기만 한다.
  - **나머지 페이퍼 심**: 전 심을 60초마다 돌리면 예산을 넘긴다. 실전이 돌린 심의
    페이퍼 쌍둥이만 같은 주기로 갱신해 program-trading-parity를 지킨다.
  - **국면을 매 바퀴 갱신**: 국면은 최근 5회 관측의 과반으로 확정되므로 호출
    주기가 곧 평활 시간상수다. 60초마다 갱신하면 50분치 평활이 5분치가 된다.
    그래서 10분 격자에서만 갱신한다(scraper.yml과 같은 격자).
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import requests

from src.data.storage_manager import StorageManager
from src.pipeline import scrape_gate
from src.pipeline.context import PipelineContext
from src.pipeline.trading_cycle import run_trade_only_cycle

# 매매 판단 간격(초). 태스커 2분 트리거 안에서 두 바퀴 도는 값이다.
TRADE_INTERVAL_SEC = 60

# 루프가 쓸 수 있는 총 시간(초). 셋업(약 20초) + 이 예산 + 배포(약 12초)가
# 태스커 간격(120초)보다 확실히 짧아야 한다.
LOOP_BUDGET_SEC = 85

DEPLOY_MANIFEST = os.path.join('data', '.lite_deploy_manifest')

_SCRAPER_WORKFLOW = 'scraper.yml'
_REPO = os.environ.get('GITHUB_REPOSITORY') or 'hoonnamkoong/stockbot'


def has_budget_for_another_turn(elapsed_sec: float) -> bool:
    """지금까지 elapsed_sec를 썼을 때 한 바퀴를 더 돌 여유가 있는가.

    순수 함수로 뺀 이유: "2분 트리거로 1분 매매"가 성립하는지가 전적으로 이
    산수에 달려 있다. 셋업(약 20초) + 예산 + 배포(약 12초) < 태스커 간격(120초)
    이어야 다음 트리거와 겹치지 않고, 겹치면 concurrency가 하나를 취소해
    매매 사이클이 통째로 사라진다(2026-08-07 실측 13%).
    """
    return elapsed_sec + TRADE_INTERVAL_SEC <= LOOP_BUDGET_SEC


def _gh_token() -> str | None:
    return os.environ.get('GH_PAT') or os.environ.get('GITHUB_TOKEN')


def scraper_is_running(log=print) -> bool:
    """스크래퍼가 지금 돌고 있는가(실행 중 또는 대기 중).

    스크래핑 런은 4분쯤 걸리는데 이 워크플로는 2분마다 깨어난다. 그 사이
    게이트 상태 파일은 아직 갱신 전이라 "아직 스크래핑 안 했다"로 보인다 —
    확인 없이 부르면 같은 사이클에 두세 번 dispatch한다. 중복 런은 스크래퍼의
    자체 게이트가 걸러내지만 그때까지 셋업 50초를 태우고 나서다.

    조회에 실패하면 False(=부른다)를 돌려준다. 여기서 True로 닫으면 스크래핑이
    영영 안 도는 쪽으로 실패한다.
    """
    token = _gh_token()
    if not token:
        return False
    url = (f'https://api.github.com/repos/{_REPO}/actions/workflows/'
           f'{_SCRAPER_WORKFLOW}/runs')
    try:
        for status in ('in_progress', 'queued'):
            res = requests.get(url, params={'status': status, 'per_page': 1},
                               headers={'Authorization': f'token {token}',
                                        'Accept': 'application/vnd.github.v3+json'},
                               timeout=10)
            if res.status_code == 200 and (res.json() or {}).get('total_count', 0) > 0:
                return True
        return False
    except Exception as e:
        log(f'[Scraper] 실행 여부 조회 실패(부르는 쪽으로 진행): {e}')
        return False


def dispatch_scraper(ctx, log=print) -> None:
    """scraper.yml을 깨운다. 응답을 기다리지 않는다 — 매매가 스크래핑에 묶이면
    이 구조를 만든 이유가 사라진다.

    GITHUB_TOKEN으로도 된다: workflow_dispatch와 repository_dispatch는 GitHub이
    재귀 방지 규칙에서 명시적으로 예외 처리한 두 이벤트다. 다만 그 경우
    워크플로에 `permissions: actions: write`가 있어야 한다.
    """
    token = _gh_token()
    if not token:
        log('[Scraper] GH 토큰 없음 → dispatch 불가')
        return
    if scraper_is_running(log):
        log('[Scraper] 이미 실행 중 — dispatch 생략')
        return
    url = (f'https://api.github.com/repos/{_REPO}/actions/workflows/'
           f'{_SCRAPER_WORKFLOW}/dispatches')
    res = requests.post(
        url,
        headers={'Authorization': f'token {token}',
                 'Accept': 'application/vnd.github.v3+json'},
        json={'ref': os.environ.get('GITHUB_REF_NAME') or 'main'},
        timeout=10)
    if res.status_code in (204, 201, 200):
        log('[Scraper] dispatch 완료')
    else:
        log(f'[Scraper] dispatch 실패 HTTP {res.status_code}')


def refresh_regime(ctx, storage, log=print) -> None:
    """Sim0(리베로) 국면을 갱신한다. **이 프로세스가 유일 writer다.**

    scraper.yml은 읽기만 한다. 두 곳에서 갱신하면 같은 순간이 regime_history에
    두 번 누적되어 평활이 왜곡된다(sim0_libero._confirm_regime).

    writer를 매매 쪽에 둔 이유: 국면은 매매의 입력이다(소유권 판정과 Sim10의
    하위 전략 선택이 이걸 읽는다). 스크래퍼에 두면 스크래퍼가 죽었을 때 국면이
    굳고, 매매가 굳은 국면으로 계속 돈다.
    """
    from src.pipeline.workers.trade_engine import TradeEngineWorker
    regime = TradeEngineWorker(ctx, storage).run_regime_stage()
    log(f'[국면] 갱신 완료: {regime or "판단 불가"}')


def regime_output_files() -> list[str]:
    """국면 갱신이 쓰는 파일들(data/ 기준 상대 이름).

    이 워크플로가 국면의 유일 writer가 됐으므로, 여기서 빠뜨리면 갱신한 국면이
    db-data에 영영 도달하지 못한다 — 그러면 두 워크플로가 모두 얼어붙은 국면을
    읽게 되고, 그건 실패가 아니라 '조용히 낡은 값으로 매매'다.
    """
    from src.strategy.registry import get_sim_registry
    from src.strategy.regime_observations import OBS_PATH_REL

    out = [os.path.basename(OBS_PATH_REL)]
    for s in get_sim_registry(include_analyzers=True):
        if s['analyzer']:
            out += [s['state_file'], s['csv_file']]
    return out


def _write_deploy_manifest(sim_id: str | None, log=print,
                           include_regime: bool = False) -> None:
    """이번 런이 실제로 갱신한 파일 이름을 적어둔다. 워크플로 배포 스텝이 읽는다.

    "바뀐 파일을 전부 올린다"로는 안 된다. 이 런은 선택 심 하나(+국면)만 갱신하는데
    data/에는 런 시작 시점에 받아온 다른 심들의 사본도 함께 있다. 그 사이
    스크래퍼가 그 심들을 갱신했다면, 파일이 '다르다'는 이유로 낡은 사본을 올려
    스크래퍼의 갱신을 되돌리게 된다(lost update). 두 워크플로는 concurrency
    그룹이 달라 실제로 동시에 돈다.
    """
    try:
        names = []
        if include_regime:
            names += regime_output_files()
        if sim_id:
            from src.strategy.registry import get_sim_registry
            entry = next((s for s in get_sim_registry(include_analyzers=True)
                          if s['id'] == sim_id), None)
            if entry:
                names += [entry['state_file'], entry['csv_file']]
            else:
                log(f"[Deploy] '{sim_id}' 레지스트리에 없음 — 심 파일 생략")
        if not names:
            return
        os.makedirs('data', exist_ok=True)
        with open(DEPLOY_MANIFEST, 'w', encoding='utf-8') as f:
            f.write('\n'.join(dict.fromkeys(names)) + '\n')
        log(f"[Deploy] 배포 대상: {names}")
    except Exception as e:
        log(f"[경고] 배포 목록 기록 실패(배포 생략됨): {e}")


def run_trade_loop(ctx: PipelineContext) -> None:
    storage = StorageManager()

    ctx.log("=" * 50)
    ctx.log(f"StockBot TradeLoop V{PipelineContext.VERSION} 시작")
    ctx.log("=" * 50)

    # 휴장일 판정은 3값 fail-closed다. None(판정 불가)을 휴장으로 뭉뚱그리면
    # 조용히 멈추고, True로 폴백하면 휴장일에 주문이 나간다(2026-07-17 사고).
    trading = ctx.is_trading_day()
    if trading is None:
        ctx.log(f"[중단] 거래일 여부를 판정할 수 없습니다({ctx.today_display}).")
        return
    if not trading:
        ctx.log(f"오늘은 휴장일({ctx.today_display})입니다. 종료합니다.")
        return

    # ── 10분 격자: 국면 갱신 + 스크래퍼 깨우기 ────────────────────
    # 매매보다 먼저 한다. 매매가 국면을 읽어 소유권을 정하므로, 갱신이 뒤에 오면
    # 이번 런 전체가 한 사이클 낡은 국면으로 판단하게 된다.
    #
    # 둘 다 실패해도 매매는 계속한다 — 국면은 직전 값이 남아 있고, 스크래핑은
    # 다음 격자에 다시 시도된다. 매매를 멈출 이유가 아니다.
    regime_refreshed = False
    if scrape_gate.is_scrape_due(ctx.now_kst):
        with ctx.stage("국면 갱신"):
            try:
                refresh_regime(ctx, storage, ctx.log)
                regime_refreshed = True
            except Exception as e:
                ctx.log(f"[경고] 국면 갱신 실패(직전 국면으로 매매 계속): {e}")
        with ctx.stage("스크래퍼 깨우기"):
            try:
                dispatch_scraper(ctx, ctx.log)
            except Exception as e:
                ctx.log(f"[경고] 스크래퍼 dispatch 실패(다음 격자에 재시도): {e}")

    # ── 매매 루프 ─────────────────────────────────────────────────
    started = time.monotonic()
    traded_sim_id = None
    turn = 0
    while True:
        turn += 1
        # 바퀴마다 컨텍스트를 새로 만든다. PipelineContext.now_kst는 생성 시점
        # 고정이라, 재사용하면 15:30 매수 차단선이 첫 바퀴 시각에 얼어붙어
        # 정규장이 닫힌 뒤에도 매수가 나간다.
        turn_ctx = ctx if turn == 1 else PipelineContext.from_env()
        turn_ctx.log(f"── 매매 {turn}바퀴 ──")
        turn_started = time.monotonic()
        traded = run_trade_only_cycle(turn_ctx, storage)
        traded_sim_id = traded or traded_sim_id

        if not traded:
            # OFF·버즈 필요 심(scraper 소관)·조회 실패 — 어느 쪽이든 60초 뒤에
            # 달라질 게 없다. 자며 유휴 컴퓨트를 태우지 않는다. 재시도는 2분 뒤
            # 태스커 하트비트가 한다.
            ctx.log("매매할 것 없음 — 루프를 더 돌지 않고 종료합니다.")
            break

        elapsed = time.monotonic() - started
        if not has_budget_for_another_turn(elapsed):
            ctx.log(f"루프 예산 소진({elapsed:.0f}/{LOOP_BUDGET_SEC}초) — 종료합니다.")
            break
        # 바퀴 '시작' 간격을 TRADE_INTERVAL_SEC로 맞춘다. 종료 기준으로 재우면
        # 매매가 오래 걸린 바퀴만큼 다음 간격이 늘어난다.
        time.sleep(max(0.0, TRADE_INTERVAL_SEC - (time.monotonic() - turn_started)))

    # 배포 목록은 루프가 끝난 뒤 한 번만 쓴다. 바퀴마다 밀면 db-data에 하루
    # 수백 커밋이 쌓인다.
    #
    # 국면 파일은 매매 여부와 무관하게 올려야 한다 — 이 워크플로가 국면의 유일
    # writer이므로, 매매를 안 한 사이클이라고 빼먹으면 갱신한 국면이 db-data에
    # 도달하지 못하고 모두가 얼어붙은 값을 읽게 된다.
    if traded_sim_id or regime_refreshed:
        _write_deploy_manifest(traded_sim_id, ctx.log, include_regime=regime_refreshed)

    ctx.log("=" * 50)
    ctx.log(f"TradeLoop 완료 ({turn}바퀴)")
    ctx.log("=" * 50)


if __name__ == "__main__":
    # [V8.9.9.5 Hotfix] Windows cp949 인코딩 에러 방지 (Emoji 출력 지원).
    # import 시점이 아니라 여기서 한다 — 모듈을 import하는 쪽(테스트 등)의
    # stdout을 가로채면 그쪽 캡처가 깨진다.
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

    run_trade_loop(PipelineContext.from_env())
