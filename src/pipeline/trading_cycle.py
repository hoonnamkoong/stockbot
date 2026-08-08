"""실전 매매 사이클 — 스크래핑 없이 도는 매매 한 바퀴.

orchestrator에서 떼어낸 이유는 두 가지다.

1. **의존성.** 매매 워크플로(trading.yml)는 2분마다 새 컨테이너에서 pip install을
   한다. orchestrator를 import하면 DataFetcher·LLMAnalyzer·Notifier가 딸려오고
   그 뒤로 pandas·numpy·google-genai가 끌려온다 — 매매에는 한 줄도 안 쓰는데
   설치 시간만 매 사이클 낸다. 그 시간이 곧 매매 주기의 하한이다.

2. **소유권.** 실전 주문을 내는 코드는 한 곳에 모여 있어야 한다. scraper.yml의
   버즈 필요 심 경로와 trading.yml의 버즈 불필요 심 경로가 같은 함수를 쓰게
   해서, 두 경로가 조용히 갈라지는 것을 구조로 막는다
   (program-trading-parity: 심 선택 = 실전이 그 심과 정확히 같이 동작).

**소유권 규칙** — 어느 순간에도 실전 주문을 내는 주체는 정확히 하나다.

    needs_buzz(선택 심, 국면) == False  →  trading.yml    (60초 루프)
    needs_buzz(선택 심, 국면) == True   →  scraper.yml    (스크래핑 직후 Stage 3)

양쪽이 같은 registry.needs_buzz()를 부르고 같은 국면 파일을 읽으므로 판정이
갈릴 수 없다. Sim10만 needs_buzz=dynamic이라 국면에 따라 소유자가 바뀌는데,
국면은 10분 격자에서만 갱신되므로 한 런이 사는 동안에는 고정이다.
"""

from src.strategy.regime_state import read_regime
from src.strategy.registry import needs_buzz as sim_needs_buzz
from src.pipeline.context import PipelineContext
from src.data import sim_diag
from src.data.storage_manager import StorageManager
from src.pipeline.workers.trade_engine import TradeEngineWorker
from src.pipeline.workers.program_trader import run_program_trading, peek_selected_sim


def selected_sim_and_buzz(ctx: PipelineContext,
                          regime: str | None) -> tuple[str | None, bool | None]:
    """(선택된 심 id, 그 심이 버즈를 필요로 하는가).

    needs: True(버즈 필요=scraper 소관) / False(불필요=trading 소관) /
           None(선택 심 없음 또는 판정 불가 — 아무도 매매하지 않는다).

    판정 불가를 False로 읽으면 스크래핑 없이 빈 유니버스로 주문이 나가고,
    True로 읽으면 양쪽이 다 자기 소관이 아니라고 판단해 매매가 멈춘다.
    둘 다 나쁘지만 후자가 낫다 — 그래서 모르면 None(아무도 안 함)이다.

    id를 함께 돌려주는 이유: 스크래퍼가 "누구 심인지"를 알아야 그 심의 페이퍼
    쌍둥이를 Stage 3에서 뺄 수 있다. trading.yml이 60초마다 갱신·배포하는 파일을
    스크래퍼가 런 시작 시점 스냅샷으로 다시 쓰면 그 사이 매매가 되돌아간다.
    """
    try:
        selected = peek_selected_sim(log=ctx.log)
    except Exception as e:
        ctx.log(f"[경고] 선택 심 조회 실패 — 이번 사이클 매매 보류: {e}")
        return None, None

    if not selected:
        ctx.log("[Program] 선택된 심 없음(OFF)")
        return None, None

    try:
        return selected, bool(sim_needs_buzz(selected, regime))
    except Exception as e:
        # 매니페스트에 없는 심이거나 dynamic인데 classmethod가 없으면 예외가 난다.
        ctx.log(f"[경고] needs_buzz 판정 실패 — 이번 사이클 매매 보류: {e}")
        return selected, None


def trade_if_buzz_free(ctx: PipelineContext, trade_worker,
                       regime: str | None) -> tuple[str | None, list | None]:
    """선택 심이 버즈를 안 쓰면 매매를 낸다. 쓰면 아무것도 하지 않는다(scraper 소관).

    반환: (매매한 심 id, 그 매매가 쓴 후보 목록). 매매를 안 했으면 (None, None).

    sim_id를 돌려주는 이유: 호출부가 페이퍼 쌍둥이를 갱신할 때 config를 다시
    조회하면 안 된다 — 매매 실행 중(수초~수십초) selected_sim이 바뀌면 방금
    매매한 심과 다른 심을 갱신하게 된다.

    후보 목록도 같은 이유다. 페이퍼가 get_universe()를 다시 부르면 수십 초 뒤의
    라이브 랭킹이라 다른 종목 집합이 나올 수 있고, 그러면 실전과 페이퍼 쌍둥이가
    서로 다른 입력으로 판단한다.
    """
    # 조회는 **한 번뿐이다.** 여기서 다시 부르면 (1) 그 호출은 감싸이지 않아
    # GitHub 조회 실패가 run_trade_loop까지 튀어 런이 죽고(if: success()인 배포
    # 스텝이 통째로 건너뛰어져 그 런의 국면·순위 갱신이 유실된다), (2) 두 호출
    # 사이에 selected_sim이 바뀌면 소유권을 판정한 심과 실제로 매매하는 심이
    # 갈린다. id를 함께 돌려받는 이유가 위 docstring에 있다.
    selected, needs = selected_sim_and_buzz(ctx, regime)
    if needs is None:
        return None, None
    if needs:
        ctx.log(f"[Program] 버즈 필요 심(국면={regime}) — scraper.yml 소관, 여기서는 매매하지 않음")
        return None, None

    ctx.log(f"[Program] '{selected}' 버즈 불필요(국면={regime}) — 매매 실행")
    try:
        used_candidates = run_program_trading(
            [], is_market_hours=ctx.is_market_hours(), now_kst=ctx.now_kst,
            log=trade_worker.log, log_error=trade_worker.log_error,
            enrich=trade_worker._enrich_universe,
        )
        if used_candidates is None:
            # 게이트에 막혀 심을 **돌리지 못했다**(예산·원장·잔고·락). 여기서
            # sim_id를 돌려주면 호출부가 "매매했다"로 읽고 페이퍼 쌍둥이를 돌리는데,
            # 넘길 유니버스가 없으니 페이퍼는 자기 유니버스를 새로 만들어 독자
            # 판단을 한다 — 실전은 아무것도 안 했는데 페이퍼만 사는 상태다.
            # 빈 리스트([])는 다르다: 돌았고 후보가 없었을 뿐이라 보유 종목
            # 관리는 실제로 일어났다.
            ctx.log("[Program] 게이트에 막혀 실행되지 않음 — 페이퍼 동기화도 생략")
            return None, None
        return selected, used_candidates
    except Exception as e:
        ctx.log(f"[경고] 프로그램 매매 실패 — 다음 사이클에 재시도: {e}")
        return None, None


def run_trade_only_cycle(ctx: PipelineContext, storage: StorageManager) -> str | None:
    """스크래핑 없이 매매 + 선택 심 페이퍼 동기화만 하고 끝나는 사이클 한 바퀴.

    국면은 **읽기만** 한다. 갱신은 10분 격자에서 딱 한 번 일어나야 한다 —
    국면은 최근 5회 관측의 과반으로 확정되므로(sim0_libero._confirm_regime)
    호출 주기가 곧 평활 시간상수이고, 60초마다 갱신하면 50분치 평활이 5분치가
    된다. writer는 trade_loop의 10분 격자 한 곳뿐이다.

    휴장일 판정은 호출자가 이미 했다고 본다(중복 호출 = KIS 콜 낭비).

    반환: 실제로 매매한 심 id, 안 했으면 None.
    """
    sim_diag.set_cycle(ctx.cycle_id)

    regime, bull_score = read_regime('data')
    score_txt = '측정 불가' if bull_score is None else f'{bull_score:.1f}'
    ctx.log(f"국면(읽기 전용): {regime or '측정 불가'} / bull_score={score_txt}")

    trade_worker = TradeEngineWorker(ctx, storage)

    with ctx.stage("매매"):
        traded_sim_id, used_candidates = trade_if_buzz_free(ctx, trade_worker, regime)

    # 실전이 돈 심의 페이퍼 쌍둥이만 같은 주기로 갱신한다. 실전만 60초로 옮기고
    # 페이퍼를 10분에 두면 대시보드의 페이퍼 성과가 실제 계좌와 갈라져서,
    # '승자를 뽑아 실전에 올린다'는 방식의 근거가 무너진다.
    if traded_sim_id:
        with ctx.stage("선택 심 페이퍼 동기화"):
            try:
                trade_worker._run_simulators(
                    [], only_sim_id=traded_sim_id, allow_price_fallback=False,
                    universe_override=used_candidates)
            except Exception as e:
                ctx.log(f"[경고] 선택 심 페이퍼 동기화 실패(매매는 완료됨): {e}")

    return traded_sim_id
