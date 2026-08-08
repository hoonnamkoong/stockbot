"""
[V50.1] 파이프라인 오케스트레이터 (Orchestrator)
=======================================================
4개의 Worker를 순서대로 호출합니다.
비즈니스 로직이 없으며, 흐름 제어만 담당합니다.
Worker 인터페이스가 실제 코드와 일치하도록 수정됨.
"""

import os

from src import alerts
from src.strategy.regime_state import read_regime
from src.strategy.registry import needs_buzz as sim_needs_buzz
from src.pipeline import scrape_gate
from src.pipeline.context import PipelineContext
from src.data import sim_diag
from src.data.storage_manager import StorageManager
from src.pipeline.workers.data_fetcher import DataFetcherWorker
from src.pipeline.workers.llm_analyzer import LLMAnalyzerWorker
from src.pipeline.workers.trade_engine import TradeEngineWorker
from src.pipeline.workers.program_trader import run_program_trading, peek_selected_sim
from src.pipeline.workers.notifier import NotifierWorker


def _status_of(item) -> str:
    """Stage 1은 StockData, Stage 2 이후는 dict를 넘긴다."""
    if isinstance(item, dict):
        return item.get('status', '활성')
    return getattr(item, 'status', '활성')


SIM7_BULL_SCORE_MIN = 45.0

# 휴장 판정 실패 알림의 반복 억제 간격(분). 트리거가 2분이라 억제가 없으면
# 하루 195건이 된다. 장중(6.5시간)에 6~7번 울리는 셈이라 무시하기는 어렵다.
HOLIDAY_ALERT_COOLDOWN_MIN = 60


def sim7_should_buy(strong_picks: list, bull_score) -> bool:
    """Stage 3.6 게이트 — '강력 매수'가 있고 장이 죽지 않았을 때만 산다.

    bull_score가 None이면 사지 않는다. 예전에는 국면 파일 조회에 실패하면
    50.0으로 폴백했고, 그 지어낸 점수가 45 게이트를 그대로 통과해 실제 매수가
    나갔다. 모르는 것은 '보통 장'이 아니다.
    """
    return bool(strong_picks) and bull_score is not None and bull_score >= SIM7_BULL_SCORE_MIN


def active_only(items: list) -> list:
    """추적 종목은 기록(엑셀·대시보드)용이다.

    매매·시뮬레이터·텔레그램 리포트·누적 보드에는 활성 종목만 넘긴다.
    """
    return [x for x in items if _status_of(x) == '활성']


def _notify_holiday_check_failed(ctx: PipelineContext) -> None:
    """거래일 판정 불가를 알린다.

    should_notify()의 정각(0~2분) 제한을 일부러 우회한다 — 이건 리포트가
    아니라 "봇이 멈췄다"는 장애 신호이고, 15/30/45분 런에서 침묵하면
    장애를 놓친다.

    다만 태스커가 2분 주기가 되면서 우회만으로는 안 된다. chk-holiday가 하루
    종일 죽으면 같은 알림이 195건 나가고, 그러면 텔레그램 rate limit에 걸리거나
    사람이 둔감해진다 — 어느 쪽이든 알림이 없는 것과 같아진다. 60분 쿨다운을
    두어 "장중에 몇 번"으로 줄인다(끄지는 않는다: 복구 여부를 계속 알려야 한다).
    """
    alerts.send_alert_once(
        'holiday_check_failed',
        f"<b>휴장 판정 실패</b>\n\n"
        f"{ctx.today_display} — 거래일 여부를 확인하지 못해 봇을 정지했습니다.\n"
        f"KIS chk-holiday 조회에 실패했습니다.\n\n"
        f"수동 실행: scraper.yml → Run workflow → force_run 체크\n"
        f"⚠️ <b>먼저 오늘이 휴장일이 아님을 직접 확인한 뒤에만 사용하세요.</b>\n"
        f"이 옵션은 휴장일 게이트를 완전히 우회하며, 켜면 실매수 주문이 나갑니다.",
        now=ctx.now_kst,
        cooldown_min=HOLIDAY_ALERT_COOLDOWN_MIN,
        log=ctx.log,
    )


def trade_if_buzz_free(ctx: PipelineContext, trade_worker,
                       regime: str | None) -> tuple[str | None, list | None]:
    """실전 선택 심이 버즈를 안 쓰면 스크래핑을 기다리지 않고 매매를 낸다(E3).

    스크래퍼(10분)의 Stage 0.5와 trade_lite(2분)가 같은 코드를 쓴다 — 갈리면
    두 경로의 동작이 어긋나고, 그건 program-trading-parity를 깨는 방식이다.

    반환: (매매한 심 id, 그 매매가 쓴 후보 목록). 매매를 안 했으면 (None, None).

    bool이 아니라 sim_id를 돌려주는 이유: 호출부가 "방금 무엇을 매매했는지" 알아야
    할 때(예: trade_lite의 페이퍼 동기화) config를 다시 조회하면 안 된다 — 매매
    실행 중(수초~수십초) config가 바뀌면 다른 심을 조회하게 되는 레이스가 생긴다.
    이 함수가 실제로 매매를 결정한 그 값을 그대로 넘겨준다.

    후보 목록을 함께 돌려주는 이유도 같은 계열이다. 페이퍼 쌍둥이가 유니버스를
    다시 조회하면 수십 초 뒤의 라이브 랭킹이라 다른 종목 집합이 나올 수 있고,
    그러면 실전과 페이퍼가 다른 입력으로 판단한다.
    """
    selected_sim = None
    try:
        selected_sim = peek_selected_sim(log=ctx.log)
    except Exception as e:
        ctx.log(f"[경고] 선택 심 조회 실패 — 스크래핑 후 매매(느린 경로)로 진행: {e}")
        return None, None

    if not selected_sim:
        ctx.log("[Program] 선택된 심 없음(OFF) — 순서 변경 없음")
        return None, None

    try:
        buzz_free = not sim_needs_buzz(selected_sim, regime)
    except Exception as e:
        # registry.needs_buzz()는 매니페스트에 없는 심이나 dynamic 심에
        # classmethod가 없으면 예외를 던진다. 모르는 것을 "버즈 불필요"로 읽으면
        # 스크래핑 없이 잘못된 유니버스로 매매가 나갈 수 있다 — 느린 경로로 미룬다.
        ctx.log(f"[경고] needs_buzz 판정 실패 — 스크래핑 후 매매(느린 경로)로 진행: {e}")
        return None, None

    if buzz_free:
        ctx.log(f"[Program] '{selected_sim}' 버즈 불필요(국면={regime}) — 스크래핑 전에 매매 실행")
        try:
            used_candidates = run_program_trading(
                [], is_market_hours=ctx.is_market_hours(), now_kst=ctx.now_kst,
                log=trade_worker.log, log_error=trade_worker.log_error,
                enrich=trade_worker._enrich_universe,
            )
            return selected_sim, used_candidates
        except Exception as e:
            ctx.log(f"[경고] 조기 프로그램 매매 실패 — Stage 3에서 재시도: {e}")
            return None, None

    ctx.log(f"[Program] '{selected_sim}' 버즈 필요(국면={regime}) — 스크래핑 후 매매")
    return None, None


def run_trade_only_cycle(ctx: PipelineContext, storage: StorageManager) -> str | None:
    """스크래핑 없이 매매 + 선택 심 페이퍼 동기화만 하고 끝나는 사이클.

    scraper.yml의 오프틱 호출과 trading_lite.yml이 이 함수를 공유한다 — 갈리면
    두 경로의 동작이 어긋나고, 그건 program-trading-parity를 깨는 방식이다.
    휴장일 판정은 호출자가 이미 했다고 본다(중복 호출 = KIS 콜 낭비).

    국면은 **읽기만** 한다. run_regime_stage()는 사이클당 한 번만 돌아야 하고
    (regime_history가 호출마다 누적돼 평활이 왜곡된다), top100 breadth가 종목당
    1콜이라 오프틱마다 돌리면 하루 수천 콜이 된다. writer는 스크래핑 사이클뿐이다.

    반환: 실제로 매매한 심 id, 안 했으면 None.
    """
    # run_pipeline 안에서 불릴 때는 이미 세팅돼 있다(같은 값). trade_lite가
    # 단독 진입점으로 부를 때를 위해 여기서도 세운다 — 두 경로 중 하나만
    # 덮으면 그 경로의 로그만 조인 키가 빈다.
    sim_diag.set_cycle(ctx.cycle_id)

    regime, bull_score = read_regime('data')
    score_txt = '측정 불가' if bull_score is None else f'{bull_score:.1f}'
    ctx.log(f"국면(읽기 전용): {regime or '측정 불가'} / bull_score={score_txt}")

    trade_worker = TradeEngineWorker(ctx, storage)

    with ctx.stage("매매(스크래핑 없음)"):
        traded_sim_id, used_candidates = trade_if_buzz_free(ctx, trade_worker, regime)

    # 실전이 돈 심의 페이퍼 쌍둥이만 같은 주기로 갱신한다. 실전만 2분으로 옮기고
    # 페이퍼를 10분에 두면 대시보드의 페이퍼 성과가 실제 계좌와 갈라져서,
    # '승자를 뽑아 실전에 올린다'는 방식의 근거가 무너진다.
    #
    # trade_if_buzz_free가 돌려준 sim_id를 그대로 쓴다 — peek_selected_sim()을
    # 여기서 다시 부르지 않는다. 매매 실행 중(수초~수십초) config의 selected_sim이
    # 바뀌면, 다시 조회한 값이 방금 매매한 심과 다를 수 있다.
    #
    # 유니버스도 마찬가지로 실전이 쓴 그 목록을 그대로 넘긴다. 여기서 다시
    # get_universe()를 부르면 수십 초 뒤의 라이브 랭킹이라 다른 종목 집합이
    # 나올 수 있고, 그러면 실전과 페이퍼 쌍둥이가 다른 입력으로 판단한다.
    if traded_sim_id:
        with ctx.stage("선택 심 페이퍼 동기화"):
            try:
                trade_worker._run_simulators(
                    [], only_sim_id=traded_sim_id, allow_price_fallback=False,
                    universe_override=used_candidates)
            except Exception as e:
                ctx.log(f"[경고] 선택 심 페이퍼 동기화 실패(매매는 완료됨): {e}")

    return traded_sim_id


def run_pipeline(ctx: PipelineContext) -> None:
    """
    StockBot 메인 파이프라인을 실행합니다.
    Stage 1 → 2 → 3 → 4 순서로 Worker를 호출합니다.
    """
    storage = StorageManager()

    # 이번 사이클의 격자 번호를 진단 로거에 알린다. 이게 없으면 각 심이 각자
    # datetime.now()를 찍어 수 초씩 어긋나고, 심끼리의 (cycle_id, code) 조인과
    # forward return용 t+N 조인이 둘 다 성립하지 않는다.
    sim_diag.set_cycle(ctx.cycle_id)

    ctx.log("=" * 50)
    ctx.log(f"StockBot Pipeline V{PipelineContext.VERSION} 시작")
    ctx.log("=" * 50)

    # ── 휴장일 체크 ──────────────────────────────────────────
    # is_trading_day()는 3값이다. None(판정 불가)을 휴장과 뭉뚱그리면
    # 조용히 멈추고, True로 폴백하면 휴장일에 돈다. 둘 다 갈라서 처리한다.
    trading = ctx.is_trading_day()
    if trading is None:
        ctx.log(f"[중단] 거래일 여부를 판정할 수 없습니다({ctx.today_display}).")
        _notify_holiday_check_failed(ctx)
        return
    if not trading:
        ctx.log(f"오늘은 휴장일({ctx.today_display})입니다. 파이프라인을 종료합니다.")
        return

    # ── 스크래핑 게이트 ─────────────────────────────────────────
    # 태스커가 2분마다 이 워크플로를 부르지만 스크래핑은 10분에 한 번만 한다
    # (네이버 부하). 아직 차례가 아니면 매매만 하고 끝낸다 — Stage 0(국면 갱신)은
    # 하지 않는다. 국면은 사이클당 한 번만 갱신돼야 하고(아래 Stage 0 주석), 호출
    # 주기가 곧 국면의 평활 시간상수라 2분마다 돌리면 국면이 10배 예민해진다.
    #
    # [2026-08-08] 여기서 곧바로 return 하던 것을 되돌렸다. 08-07에 오프틱 매매를
    # trading_lite.yml에 위임했는데, **그 워크플로는 한 번도 불린 적이 없다** —
    # 태스커가 보내는 건 repository_dispatch가 아니라 workflow_dispatch이고,
    # workflow_dispatch는 지정한 워크플로 하나에만 도달한다(7일치 400런 실측:
    # repository_dispatch 0건). 그래서 오프틱 5/6이 인프라만 태우고 아무것도 하지
    # 않았고, 실전 매매 간격이 10분에서 12분으로 오히려 늘어났다.
    #
    # 여기서 매매하는 것이 안전한 이유: 오프틱 런과 스크래핑 런은 같은 워크플로,
    # 같은 concurrency 그룹(stockbot-scraper)이라 직렬화된다 — 배포 스텝이
    # 서로의 산출물을 되돌리는 lost update가 생길 수 없다.
    #
    # FORCE_RUN은 휴장일 게이트뿐 아니라 이 게이트도 우회한다 — 수동으로
    # "지금 당장 스크래핑"을 원해서 켠 옵션인데, 10분 게이트에 막히면 의도와
    # 반대로 동작한다.
    force_run = os.environ.get('FORCE_RUN', '').strip().lower() == 'true'
    if not force_run and not scrape_gate.is_scrape_due(ctx.now_kst):
        ctx.log("스크래핑 아직 아님(오프틱) — 매매만 수행합니다.")
        run_trade_only_cycle(ctx, storage)
        return

    # ── Stage 0: 국면 판단 + 순서 가변 분기(E3) ───────────────────
    # 실전 계좌가 선택한 심이 네이버 게시글(버즈)을 안 쓰면(needs_buzz=False),
    # 스크래핑(Stage 1)을 기다리지 않고 매매부터 낸다. Sim0(리베로) 국면 갱신은
    # top100 라이브 실측만으로 가능해졌다(E2) — 이게 이 분기의 유일한 입력이라
    # 스크래핑보다 먼저 돈다. Sim10처럼 국면에 따라 필요 여부가 바뀌는 심도
    # registry.needs_buzz()가 국면을 받아 판단한다.
    trade_worker = TradeEngineWorker(ctx, storage)
    with ctx.stage("Stage 0: 국면 판단"):
        regime = trade_worker.run_regime_stage()

    with ctx.stage("Stage 0.5: 매매 순서 분기"):
        # trade_if_buzz_free는 (sim_id, 쓴 후보)를 돌려준다(오프틱 경로가 재조회
        # 없이 쓰려고). 스크래핑 사이클은 뒤에서 Stage 1이 후보를 새로 만들고
        # Stage 3이 전 심을 돌리므로 여기서는 "매매했는가"만 필요하다.
        program_traded_early = trade_if_buzz_free(ctx, trade_worker, regime)[0] is not None

    # ── Stage 1: 데이터 수집 및 1차 필터링 ───────────────────────
    with ctx.stage("Stage 1: 데이터 수집"):
        stocks = DataFetcherWorker(ctx, storage).run()

    # ── Stage 2: AI 분석 ──────────────────────────────────────────
    analyzer_worker = LLMAnalyzerWorker(ctx, storage)
    with ctx.stage("Stage 2: AI 분석"):
        if not stocks:
            ctx.log("신규 수집 종목 없음 (Buzz 임계값 미달). 기존 포트폴리오 관리 모드로 진입합니다.")
            # [V50.2] 신규 종목이 없어도 Stage 3(시뮬레이터)를 실행하기 위해 빈 리스트로 계속 진행
            stocks = []
            candidates = []
        else:
            stocks, candidates = analyzer_worker.run(stocks)

    # ── Stage 3: 전략 판단 + 시뮬레이터 동기화 ───────────────────
    # trade_worker는 Stage 0에서 만든 것을 그대로 쓴다(새로 만들면 _kis_provider
    # 캐시가 갈리고, sim0_libero를 다시 도는 실수를 하기도 쉽다).
    with ctx.stage("Stage 3: 전략 판단 + 시뮬레이터"):
        sync_state, _ = storage.load_sync_state(ctx.today_str)
        final_picks, simulation_results, sell_candidate = trade_worker.run(
            active_only(stocks), sync_state, skip_program_trading=program_traded_early)

    # ── Stage 3.5: 딥다이브 리포트 생성 ──────────────────────────
    deep_dive_report = ""
    if ctx.should_notify():
        # [User V50.8] 상세 리포트 대상: 추천 상위 2개 + 매도 후보 1개
        if final_picks or sell_candidate:
            ctx.log(f"▶ Stage 3.5: 딥다이브 리포트 생성 (추천:{len(final_picks[:2])}개, 매도:{1 if sell_candidate else 0}개)")
            deep_dive_report = analyzer_worker.generate_deep_dive(final_picks[:2], candidates, sell_candidate=sell_candidate)
            # 월별 리서치 엑셀에도 기록
            if final_picks:
                storage.update_monthly_excel(final_picks[:2], ctx.now_kst)
        else:
            # 오늘 이미 보고된 종목들만 있는 경우
            daily_info = sync_state.daily_reported_info
            if simulation_results and any(r.get('signal') in ['BUY', 'WATCH'] for r in simulation_results):
                names_str = ", ".join(item['name'] for item in daily_info)
                dashboard_url = "https://stockbot-phi.vercel.app/api/download/excel"
                deep_dive_report = (
                    f"[안내] 이번 회차의 모든 종목은 오늘 이미 보고되었습니다.\n"
                    f"오늘 보고 종목: {names_str}\n\n"
                    f"리포트 다운로드: {dashboard_url}"
                )
    else:
        ctx.log("▶ Stage 3.5: 정각 발송 타이밍 아님 (딥다이브 생성 생략)")

    if not final_picks:
        # [Bug 1 Fix] 신규 picks 없어도 reports.json 항상 재생성
        storage.rebuild_reports_index(ctx.now_kst)

    # ── Stage 3.6: Sim7 신규 매수 ────────────────────────────────
    # rank_and_recommendation이 final_picks에 역전파된 이후 실행
    try:
        strong_picks = [
            p for p in final_picks
            if '강력 매수' in (p.get('rank_and_recommendation') or '')
        ]
        _, bull_score = read_regime('data')

        if sim7_should_buy(strong_picks, bull_score):
            from src.strategy.simulators.sim7_report_follower import ReportFollowerSimulator
            ctx.log(f"▶ Stage 3.6: Sim7 강력 매수 처리 ({len(strong_picks)}개 / bull_score={bull_score:.1f})")
            ReportFollowerSimulator().buy_from_report(strong_picks, bull_score=bull_score)
        else:
            score_txt = '측정 불가' if bull_score is None else f'{bull_score:.1f}'
            ctx.log(f"▶ Stage 3.6: Sim7 스킵 (강력매수={len(strong_picks)}개 / bull_score={score_txt})")
    except Exception as _e:
        ctx.log(f"[Warn] Stage 3.6 Sim7 실패: {_e}")

    # ── Stage 4: 텔레그램 발송 + 최종 저장 ───────────────────────
    ctx.log("▶ Stage 4: 리포트 발송 + 저장")
    # 최신 sync_state 재로드 (Stage 3에서 업데이트됐을 수 있음)
    sync_state, _ = storage.load_sync_state(ctx.today_str)
    # 추적 종목은 5일/3일 누적 보드(_aggregate_multi_day), 텔레그램 종목 수,
    # reported_codes에 섞이면 안 된다. 이 인자가 그 넷의 유일한 입구다.
    NotifierWorker(ctx, storage).run(
        all_stocks=active_only(candidates),
        simulation_results=simulation_results,
        final_picks=final_picks,
        deep_dive_report=deep_dive_report,
        sync_state=sync_state,
    )

    # 성공적으로 끝까지 돈 사이클만 "방금 스크래핑했다"로 기록한다. 여기 도달하기
    # 전에 예외로 죽으면 기록하지 않는다 — 그래야 다음 오프틱 판정이 "아직 신선함"
    # 으로 잘못 착각하지 않고, 다음 틱에 바로 재시도한다.
    scrape_gate.mark_scraped(ctx.now_kst)

    ctx.log("=" * 50)
    ctx.log("Pipeline 완료")
    ctx.log("=" * 50)
