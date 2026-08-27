"""
[V50.1] 파이프라인 오케스트레이터 (Orchestrator)
=======================================================
4개의 Worker를 순서대로 호출합니다.
비즈니스 로직이 없으며, 흐름 제어만 담당합니다.
Worker 인터페이스가 실제 코드와 일치하도록 수정됨.
"""

import os

from src import alerts
from src.strategy.regime_state import read_regime, read_regime_state, regime_hint
from src.pipeline import scrape_gate
from src.pipeline.context import PipelineContext
from src.data import sim_diag
from src.data.storage_manager import StorageManager
from src.pipeline.trading_cycle import selected_sim_and_buzz
from src.strategy.registry import list_buzz_free_sim_ids
from src.pipeline.workers.data_fetcher import DataFetcherWorker
from src.pipeline.workers.llm_analyzer import LLMAnalyzerWorker
from src.pipeline.workers.trade_engine import TradeEngineWorker
from src.pipeline.workers.notifier import NotifierWorker


def _status_of(item) -> str:
    """Stage 1은 StockData, Stage 2 이후는 dict를 넘긴다."""
    if isinstance(item, dict):
        return item.get('status', '활성')
    return getattr(item, 'status', '활성')


# 2026-08-27: 45.0 → 40.0. 그날 14시 슬롯에 딥다이브 강력매수가 2개 있었는데
# bull_score 43.1로 미달해 통째로 스킵됐다. 40~45는 "약한 횡보"이고 리포트
# 강력매수는 국면과 독립된 별도 신호라, 같은 약세를 두 번 세고 있었다.
# 심의 비중 앵커(ReportFollowerSimulator.GATE=45)는 일부러 그대로 둔다 —
# 40~45 구간은 최소 비중(WEIGHT_MIN)으로 클램프돼 가장 약한 확신에 가장
# 작은 포지션이 붙는다.
SIM7_BULL_SCORE_MIN = 40.0


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


DEPLOY_EXCLUDE_REL = os.path.join('data', '.scraper_deploy_exclude')


def write_deploy_exclude(sim_ids: set[str] | str | None, log=print,
                         path: str = DEPLOY_EXCLUDE_REL) -> list[str]:
    """trading.yml이 writer인 파일 이름을 배포 스텝에 넘긴다. 반환은 적어 넣은 이름들.

    **Stage 3에서 그 심을 안 돌리는 것만으로는 부족하다.** 배포 스텝의
    `cp data/*.json`은 심을 돌렸는지와 무관하게 파일을 올리는데, 그 파일은 이 런이
    시작할 때 db-data에서 받아온 4~5분 전 사본이다. db_data_repo는 배포 시점에 새로
    clone하므로 그 사이 trading.yml이 push한 최신 상태가 들어 있고, 위 cp가 그것을
    옛 사본으로 덮어쓴다 — 60초 루프 4~5분치가 통째로 되돌아간다(lost update).
    파일을 안 만드는 것과 파일을 안 올리는 것은 다른 문제다.

    sim_ids: 2026-08-19부터 선택 심 하나가 아니라 **버즈 불필요 심 전체**다
    (trading.yml이 국면·선택 여부와 무관하게 이 집합을 60초마다 돈다 —
    src.strategy.registry.list_buzz_free_sim_ids). 단일 문자열도 받는다
    (호환용 — 과거 호출부·테스트가 남아 있다면 그대로 동작한다).

    정적 case문에 못 넣는 이유: 선택 심은 program_trading.json이 정하므로 런타임에만
    안다. 그래서 이름을 파일로 넘긴다.

    항상 쓴다(제외할 게 없으면 빈 파일) — 남아 있는 옛 목록이 엉뚱한 심을 빼면
    그 심은 스크래퍼가 갱신하고도 db-data에 도달하지 못한다.

    실패는 예외로 올리지 않는다. 여기서 죽으면 스크래핑 산출물 전체가 배포를 못 하는데,
    그건 되돌림보다 나쁘다 — 대신 로그에 남긴다.
    """
    ids = {sim_ids} if isinstance(sim_ids, str) else set(sim_ids or ())
    names: list[str] = []
    if ids:
        try:
            from src.strategy.registry import get_sim_registry
            reg = {s['id']: s for s in get_sim_registry(include_analyzers=True)}
            for sid in sorted(ids):
                entry = reg.get(sid)
                if entry:
                    names += [os.path.basename(entry['state_file']),
                             os.path.basename(entry['csv_file'])]
                else:
                    log(f"[Deploy] '{sid}' 레지스트리에 없음 — 배포 제외 없이 진행")
        except Exception as e:
            log(f"[경고] 배포 제외 목록 작성 실패(되돌림 위험): {e}")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(''.join(f'{n}\n' for n in names))
        if names:
            log(f"[Deploy] 배포 제외(trading.yml 소유): {names}")
    except Exception as e:
        log(f"[경고] 배포 제외 목록 기록 실패(되돌림 위험): {e}")
    return names


def _notify_holiday_check_failed(ctx: PipelineContext) -> None:
    """거래일 판정 불가를 알린다.

    문구·쿨다운은 src/alerts.py에 있다 — trade_loop(매매 경로)도 같은 실패를
    같은 문구로 알려야 하고, 복사본을 두면 두 경로가 갈린다.
    """
    alerts.notify_holiday_check_failed(ctx.today_display, ctx.now_kst, ctx.log)


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

    # ── Stage 0: 국면 읽기 + 매매 소유권 판정 ─────────────────────
    # [2026-08-08] 국면을 여기서 **갱신하지 않는다.** writer는 trade_loop의 10분
    # 격자 한 곳뿐이다. 국면은 최근 5회 관측의 과반으로 확정되므로 호출 주기가 곧
    # 평활 시간상수인데, 두 워크플로가 각자 갱신하면 같은 순간이 두 번 누적되어
    # 평활이 왜곡된다(sim0_libero._confirm_regime).
    #
    # 그리고 이 워크플로는 스크래퍼가 죽어도 매매가 살아야 한다는 이유로
    # trade_loop가 dispatch하는 종속 워크플로가 됐다 — 매매의 입력인 국면을
    # 여기서 만들면 그 종속 방향이 거꾸로 된다.
    #
    # 다만 **파일로 읽으면 정상 경로에서 항상 한 격자 낡은 값**이다. 이 워크플로가
    # db-data를 체크아웃하는 시점(dispatch +30초)이 trade_loop의 배포 시점(+75초)
    # 보다 빠르기 때문이다. 레이스가 아니라 정해진 순서다. 그래서 trade_loop가
    # 방금 계산한 국면을 dispatch inputs로 실어 보내고, 있으면 그걸 우선한다.
    #
    # 인계값의 적용은 read_regime 안에 있다 — 여기서 하지 않는다. 예전에 여기서만
    # 적용했더니 소유권 판정은 인계값을, Sim10·Sim6은 파일값을 보게 되어, 국면 전환
    # 격자에서 "스크래퍼가 매매한다"고 정해놓고 정작 Sim10은 이전 국면의 하위
    # 전략·유니버스로 실주문을 냈다. 창구가 하나면 관문도 하나여야 한다.
    trade_worker = TradeEngineWorker(ctx, storage)
    with ctx.stage("Stage 0: 국면 읽기"):
        regime, _ = read_regime('data')
        if regime_hint():
            on_disk = (read_regime_state('data') or {}).get('current_regime')
            ctx.log(f"국면(trade_loop 인계): {regime} / 파일값 {on_disk or '측정 불가'}")
        else:
            ctx.log(f"국면(파일, 인계값 없음): {regime or '측정 불가'}")

    # 실전 주문의 소유자는 어느 순간에도 하나다(src/pipeline/trading_cycle.py).
    #   needs_buzz == False → trading.yml(60초 루프)이 낸다. 여기서는 손 뗀다.
    #   needs_buzz == True  → 그 심의 입력이 스크래핑 결과이므로 Stage 3이 낸다.
    # 판정 불가(None)면 아무도 내지 않는다 — 모르는 채로 주문하지 않는다.
    with ctx.stage("Stage 0.5: 매매 소유권 판정"):
        selected_sim, buzz_needed = selected_sim_and_buzz(ctx, regime)
        scraper_owns_trading = buzz_needed is True
        # 페이퍼 쌍둥이도 writer가 하나여야 한다. 2026-08-19: 이 집합은 선택 심
        # 하나가 아니라 **버즈 불필요 심 전체**다 — trading.yml이 국면·선택
        # 여부와 무관하게 이 집합을 60초마다 돈다(trading_cycle.py의
        # list_buzz_free_sim_ids 사용과 정확히 같은 계산). 여기서 런 시작
        # 시점 스냅샷으로 같은 심을 다시 돌리면 그 사이 페이퍼 매매가 통째로
        # 되돌아간다(lost update). 프로그램 매매 소유권(selected_sim/
        # buzz_needed)과는 별개 판단이다 — trading.yml의 버즈 불필요 스윕은
        # 프로그램 매매 ON/OFF와 무관하게 돈다.
        paper_owned_elsewhere = list_buzz_free_sim_ids(regime)
        # Stage 3 제외(돌리지 않는다)와 배포 제외(올리지 않는다)는 다른 문제다.
        # 둘 다 같은 값에서 나와야 판정이 갈리지 않는다.
        write_deploy_exclude(paper_owned_elsewhere, ctx.log)
        if scraper_owns_trading:
            ctx.log("[Program] 버즈 필요 심 — 이 워크플로가 Stage 3에서 매매합니다.")
        else:
            ctx.log("[Program] 이 워크플로는 매매하지 않습니다(trading.yml 소관 또는 판정 불가).")

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
            active_only(stocks), sync_state,
            skip_program_trading=not scraper_owns_trading,
            paper_owned_elsewhere=paper_owned_elsewhere)

    # ── Stage 3.5: 딥다이브 리포트 생성 ──────────────────────────
    deep_dive_report = ""
    if ctx.should_notify():
        # [2026-08-11] 상세 리포트 대상: 추천 상위 5개(fact_score·tick_power
        # 순위 결합) + 매도 후보 1개. trade_engine.rank_top()이 이미 5개로
        # 잘라 넘기므로 여기서는 그 값을 그대로 쓴다.
        if final_picks or sell_candidate:
            ctx.log(f"▶ Stage 3.5: 딥다이브 리포트 생성 (추천:{len(final_picks)}개, 매도:{1 if sell_candidate else 0}개)")
            deep_dive_report = analyzer_worker.generate_deep_dive(final_picks, candidates, sell_candidate=sell_candidate)
            # 월별 리서치 엑셀에도 기록
            if final_picks:
                storage.update_monthly_excel(final_picks, ctx.now_kst)
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

    # 성공적으로 끝까지 돈 사이클만 "방금 스크래핑했다"로 기록한다.
    #
    # 이 상태 파일의 writer는 여기 하나, reader는 trade_loop 하나다. trade_loop가
    # "스크래퍼를 부를 차례인가"를 이걸 보고 정한다. 예외로 죽으면 기록하지 않으므로,
    # 실패한 스크래핑은 다음 틱에 자동으로 재시도된다 — 이 순서를 뒤집어
    # (dispatch 시점에 기록) 만들면 그 재시도가 사라진다.
    scrape_gate.mark_scraped(ctx.now_kst)

    ctx.log("=" * 50)
    ctx.log("Pipeline 완료")
    ctx.log("=" * 50)
