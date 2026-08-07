"""StockBot 경량 매매 진입점 (태스커 2분 주기)
================================================

스크래핑과 거래 액션을 분리한 두 워크플로 중 '거래' 쪽이다.
  - trading_lite.yml (2분, 이 파일)  : 실전 매매 + 선택 심 페이퍼 갱신
  - scraper.yml      (10분)          : 스크래핑·AI·국면 갱신·나머지 심·텔레그램

여기서 하지 않는 것과 그 이유:
  - **국면 갱신**: run_regime_stage()는 사이클당 정확히 한 번만 돌아야 한다
    (trade_engine.py 참고 — regime_history가 호출마다 누적돼 평활이 왜곡된다).
    게다가 top100 breadth는 종목당 1콜로 ~100 KIS 콜을 쓴다. 2분 주기로 돌리면
    하루 약 19,500콜이다. 국면은 scraper.yml이 유일 writer이고 여기선 읽기만 한다.
  - **스크래핑/AI/텔레그램**: 네이버 게시글(버즈) 수집이 필요한 일은 전부
    scraper.yml 소관이다. 단, "이 경로가 아예 네이버를 안 두드린다"는 뜻은
    아니다 — 버즈 불필요 심 중 자기 유니버스가 있는 심은 `_enrich_universe()`가
    보유 종목 sparkline/PER·PBR 보강을 위해 `finance.naver.com/item/*` 페이지를
    여전히 조회한다(trade_engine.py, 스크래핑 이전부터 있던 동작). 줄어드는 건
    "게시글 목록 수집"(Stage 1) 빈도이지, 네이버 요청 자체가 0이 되는 게 아니다.
  - **나머지 페이퍼 심**: 전 심을 2분마다 돌리면 런이 ~153초로 120초 창을 넘겨
    매 사이클이 겹친다(2026-08-06 실측). 실전 선택 심의 페이퍼 쌍둥이만 돌려
    program-trading-parity(실전 = 자기 페이퍼와 동일 동작)를 지킨다.

버즈가 필요한 심이 선택돼 있으면 이 경로는 매매하지 않는다 — 그 심의 입력이
스크래핑 결과라서, scraper.yml의 Stage 3이 맡는다.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data.storage_manager import StorageManager
from src.pipeline.context import PipelineContext
from src.pipeline.orchestrator import run_trade_only_cycle


DEPLOY_MANIFEST = os.path.join('data', '.lite_deploy_manifest')


def _write_deploy_manifest(sim_id: str, log=print) -> None:
    """이번 런이 실제로 갱신한 파일 이름을 적어둔다. 워크플로 배포 스텝이 읽는다.

    "바뀐 파일을 전부 올린다"로는 안 된다. lite는 선택 심 하나만 갱신하는데
    data/에는 런 시작 시점에 받아온 다른 심들의 사본도 함께 있다. 그 사이 스크래퍼가
    그 심들을 갱신했다면, 파일이 '다르다'는 이유로 낡은 사본을 올려 스크래퍼의
    갱신을 되돌리게 된다(lost update). 내가 쓴 것만 올린다.
    """
    try:
        from src.strategy.registry import get_sim_registry
        entry = next((s for s in get_sim_registry(include_analyzers=True)
                      if s['id'] == sim_id), None)
        if not entry:
            log(f"[Deploy] '{sim_id}' 레지스트리에 없음 — 배포 목록 생략")
            return
        names = [entry['state_file'], entry['csv_file']]
        os.makedirs('data', exist_ok=True)
        with open(DEPLOY_MANIFEST, 'w', encoding='utf-8') as f:
            f.write('\n'.join(names) + '\n')
        log(f"[Deploy] 배포 대상: {names}")
    except Exception as e:
        log(f"[경고] 배포 목록 기록 실패(배포 생략됨): {e}")


def run_trade_lite(ctx: PipelineContext) -> None:
    storage = StorageManager()

    ctx.log("=" * 50)
    ctx.log(f"StockBot TradeLite V{PipelineContext.VERSION} 시작")
    ctx.log("=" * 50)

    # 휴장일 판정은 스크래퍼와 동일하게 3값 fail-closed다. None(판정 불가)을
    # 휴장으로 뭉뚱그리면 조용히 멈추고, True로 폴백하면 휴장일에 주문이 나간다.
    trading = ctx.is_trading_day()
    if trading is None:
        ctx.log(f"[중단] 거래일 여부를 판정할 수 없습니다({ctx.today_display}).")
        return
    if not trading:
        ctx.log(f"오늘은 휴장일({ctx.today_display})입니다. 종료합니다.")
        return

    # 매매 본체는 scraper.yml의 오프틱 경로와 **같은 함수**를 쓴다. 이 파일에
    # 복사본을 두면 두 경로가 조용히 갈라지고, 그건 program-trading-parity를
    # 깨는 방식이다. 국면 읽기·페이퍼 동기화도 그 안에 있다.
    traded_sim_id = run_trade_only_cycle(ctx, storage)

    # 배포 목록만 이 경로 고유다 — trading_lite.yml은 "내가 쓴 것만" 올리고,
    # scraper.yml은 data/ 전체를 올린다(같은 concurrency 그룹이라 안전).
    if traded_sim_id:
        _write_deploy_manifest(traded_sim_id, ctx.log)

    ctx.log("=" * 50)
    ctx.log("TradeLite 완료")
    ctx.log("=" * 50)


if __name__ == "__main__":
    # [V8.9.9.5 Hotfix] Windows cp949 인코딩 에러 방지 (Emoji 출력 지원).
    # import 시점이 아니라 여기서 한다 — 모듈을 import하는 쪽(테스트 등)의
    # stdout을 가로채면 그쪽 캡처가 깨진다.
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

    run_trade_lite(PipelineContext.from_env())
