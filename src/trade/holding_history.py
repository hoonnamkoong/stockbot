"""보유 종목 가격 이력 공급.

청산 로직은 '그날 후보 목록'에서 보유 종목의 이력을 찾는다. 그런데 엔진은 심마다
방향성 유니버스(예: 오늘의 상승률 상위 30)만 넘기므로, 손실 중인 보유 종목은
구조적으로 목록에 없다. 그러면 적응형 손절이 조용히 고정 퍼센트로 퇴화한다.
그래서 보유 종목은 후보 유무와 상관없이 KIS 일봉으로 이력을 반드시 채운다.
"""
import time

# 소비자 중 최대 필요량이 직전 종가 20개(심5 MIN_HISTORY). 휴장·결손 여유 5일.
# KIS는 한 번 호출에 최대 100행을 주므로 종목당 1콜이면 충분하다.
HISTORY_DAYS = 25

# 후보가 이미 가진 이력이 이보다 짧으면 조회한다. 소비자 최대 요구는 심5의 직전
# 종가 20개이고 당일 행이 하나 더 붙으므로 21행이다. 존재 여부만 보면 2행짜리
# 이력이 공급을 막아 prior_closes가 None을 주고 적응형 청산이 다시 퇴화한다.
MIN_CAND_HISTORY = 21


def make_kis_provider():
    """공급자 생성 지점. 생성 시 인증·네트워크를 건드리므로 테스트가 여기를 막는다."""
    from src.trade.kis_data_provider import KISDataProvider
    return KISDataProvider()


def supply_holding_history(codes, cand_by_code, provider, *, log=print):
    """후보에 이력이 없는 보유 종목만 KIS 일봉으로 받아 {code: [{date, close}]}로 돌려준다.

    조회에 실패한 종목은 결과에 키 자체가 없다. 빈 리스트로 채우면 '측정 불가'가
    '이력 없음'으로 읽혀 값이 위조되기 때문이다.
    """
    t0 = time.monotonic()
    out = {}
    failed = 0
    fetched = 0
    cand_by_code = cand_by_code or {}
    for code in list(codes or []):
        if len((cand_by_code.get(code) or {}).get('price_history') or []) >= MIN_CAND_HISTORY:
            continue  # 후보 이력이 충분하면 콜을 쓰지 않는다
        fetched += 1
        try:
            rows = provider.get_daily_history(code, days=HISTORY_DAYS)
            hist = [{'date': r['date'], 'close': r['close']}
                    for r in (rows or []) if r.get('date') and r.get('close')]
        except Exception:
            hist = []  # 한 종목의 실패(상폐·ETF 등)가 다른 종목을 막지 않는다
        if hist:
            out[code] = hist
        else:
            failed += 1
    log(f"  [계측] 보유 이력 공급 {len(out)}종목 · 실패 {failed} · "
        f"{time.monotonic() - t0:.1f}초 (조회 {fetched})")
    return out


def attach_holding_history(sim, sim_candidates, get_provider, *, log=print, log_error=print):
    """sim.price_history를 채운다. 페이퍼·실전 두 경로가 이 함수 하나를 쓴다.

    실패 정책도 한 곳에 둔다: 이력은 보조 입력이라 인프라 실패(import·공급자 생성)는
    삼키고 이력 없이 sim.run을 계속한다 — 심을 건너뛰면 손실 포지션이 방치된다.
    단 TypeError·AttributeError·KeyError는 프로그래밍 오류라 그대로 올려 상위
    핸들러가 기록하게 한다. 삼키면 모든 적응형 청산이 조용히 고정 %로 퇴화한다.
    """
    sim.price_history = {}  # 이전 값 승계에 기대지 않고 매번 명시한다
    portfolio = sim.state.get('portfolio')
    if not portfolio:
        return  # 공급할 것도, 공급자를 만들 이유도 없다
    # 두 구간을 일부러 다르게 다룬다. 합치지 말 것.
    # 1) 공급자 조달은 인증·네트워크를 건드리는 인프라 작업이다. 토큰 응답에 키가
    #    없는 경우처럼 KeyError 등으로도 터질 수 있으므로 모든 예외를 삼키고 이력
    #    없이 진행한다 — 이력이 없어도 하드손절·타임스탑은 돌아야 한다.
    try:
        provider = get_provider()
    except Exception as e:
        sim.price_history = {}
        log_error(f"보유 이력 공급자 조달 실패(이력 없이 진행) {type(e).__name__}: {e!r}")
        return
    # 2) supply_holding_history 호출은 우리 코드다. 여기서 나는 TypeError 등은
    #    프로그래밍 오류이고, 삼키면 모든 적응형 청산이 조용히 고정 %로 퇴화하므로
    #    올려서 상위 핸들러가 기록하게 한다.
    try:
        sim.price_history = supply_holding_history(
            portfolio, {s['code']: s for s in sim_candidates if s.get('code')},
            provider, log=log)
    except (TypeError, AttributeError, KeyError):
        raise
    except Exception as e:
        sim.price_history = {}
        log_error(f"보유 이력 공급 실패(이력 없이 진행) {type(e).__name__}: {e!r}")
