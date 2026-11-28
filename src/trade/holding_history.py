"""보유 종목 가격 이력 공급.

청산 로직은 '그날 후보 목록'에서 보유 종목의 이력을 찾는다. 그런데 엔진은 심마다
방향성 유니버스(예: 오늘의 상승률 상위 30)만 넘기므로, 손실 중인 보유 종목은
구조적으로 목록에 없다. 그러면 적응형 손절이 조용히 고정 퍼센트로 퇴화한다.
그래서 보유 종목은 후보 유무와 상관없이 KIS 일봉으로 이력을 반드시 채운다.
"""
import time

from src.core import clock

# 소비자 중 최대 필요량이 직전 종가 20개(심5 MIN_HISTORY). 휴장·결손 여유 5일.
# KIS는 한 번 호출에 최대 100행을 주므로 종목당 1콜이면 충분하다.
HISTORY_DAYS = 25

# 같은 종목의 공급 실패 알림 반복 억제(분). 사이클이 2분이라 억제가 없으면 한 종목이
# 하루 수백 건을 쏟고, 그 도배는 알림이 없는 것과 같다. 별도 상태 파일을 만들지 않고
# src/alerts.py의 기존 alert_dedup.json(배포 배선이 있는 것)을 쓴다.
SUPPLY_ALERT_COOLDOWN_MIN = 60

# 후보가 이미 가진 이력이 MIN_CAND_HISTORY행보다 짧으면 조회한다. 존재 여부만 보면
# 2행짜리 이력이 공급을 막아 prior_closes가 None을 주고 적응형 청산이 다시 퇴화한다.
# 상수는 소비자 쪽(history_of)과 공유해야 해서 base_simulator에 정의하고 가져온다.
from src.strategy.simulators.base_simulator import MIN_CAND_HISTORY  # noqa: E402


def make_kis_provider():
    """공급자 생성 지점. 생성 시 인증·네트워크를 건드리므로 테스트가 여기를 막는다."""
    from src.trade.kis_data_provider import KISDataProvider
    # 디스크 캐시는 런 사이에 살아남지 않는다(어떤 워크플로도 kis_financial_cache.json을
    # 복원·배포하지 않는다). 그런데 persist면 조회마다 전체 파일을 다시 쓴다
    # (최대 15회/사이클). 같은 런 안의 중복 조회는 클래스 레벨 _disk_cache가 막는다.
    return KISDataProvider(persist_disk_cache=False)


def _alert_supply_failed(codes, log):
    """(a) 공급 실패 — KIS가 이 보유 종목들의 일봉을 주지 않았다 — 만 알린다.

    종목 루프가 끝난 뒤 **한 통**으로만 보낸다(키 하나, 본문에 종목 목록). 루프 안에서
    종목마다 동기 발송하면 텔레그램 장애 때 종목당 최대 ~30초(타임아웃 15초 x 재시도)가
    쌓이고, 발송 실패는 쿨다운을 기록하지 않아 매 사이클 반복된다. 매매 루프 안에서
    잘리면 주문은 나가고 심 상태가 안 올라간다. 키를 하나로 두면 종목별 키가
    alert_dedup.json에 쌓이는 문제도 같이 사라진다.

    (b) 공급은 됐으나 이력이 짧아 prior_closes_for가 None을 주는 경우는 여기서 알리지
    않는다(심1·심4가 로그 한 줄만 남긴다). 문구에 그 구분을 박아 두어, 무음 심을
    진단하는 사람이 이 알림이 없다고 (b)까지 없다고 읽지 않게 한다.
    알림 경로의 어떤 실패도 매매 경로로 올리지 않는다 — 알리려던 문제보다 나빠진다.
    """
    try:
        from src import alerts
        alerts.send_alert_once(
            key='hist_missing',
            text=(f"보유 종목 {len(codes)}개({', '.join(codes)})의 일봉 공급 실패 — KIS가 "
                  f"이력을 주지 않아 적응형 청산이 고정 %로 퇴화합니다.\n"
                  f"참고: 공급은 됐지만 이력이 짧아 못 쓰는 경우는 이 알림과 별개이며 "
                  f"여기서 알리지 않습니다(심1·심4 로그 확인)."),
            now=clock.now(), cooldown_min=SUPPLY_ALERT_COOLDOWN_MIN, log=log)
    except Exception as e:
        log(f"  [계측] 보유 이력 공급 실패 알림 자체가 실패 {type(e).__name__}: {e!r}")


def supply_holding_history(codes, cand_by_code, provider, *, log=print, label=''):
    """후보에 이력이 없는 보유 종목만 KIS 일봉으로 받아 {code: [{date, close}]}로 돌려준다.

    조회에 실패한 종목은 결과에 키 자체가 없다. 빈 리스트로 채우면 '측정 불가'가
    '이력 없음'으로 읽혀 값이 위조되기 때문이다.
    """
    t0 = time.monotonic()
    out = {}
    failed_codes = []
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
            failed_codes.append(code)  # 루프 안에서는 모으기만 한다 — 발송은 루프 뒤
    if failed_codes:
        _alert_supply_failed(failed_codes, log)
    elapsed = time.monotonic() - t0  # 알림 소요도 포함해 잰다
    # 이 줄은 사이클당 한 번이 아니라 심마다 한 번 나온다. 첫 심이 조회를 전부 떠안고
    # 나머지는 ≈0초라, 어느 심 줄인지 알아야 최댓값을 고를 수 있다.
    log(f"  [계측] 보유 이력 공급{f'({label})' if label else ''} {len(out)}종목 · "
        f"실패 {len(failed_codes)} · {elapsed:.1f}초 (조회 {fetched})")
    return out


def attach_holding_history(sim, sim_candidates, get_provider, *, log=print, log_error=print):
    """sim.price_history를 채운다. 페이퍼·실전 두 경로가 이 함수 하나를 쓴다.

    실패 정책도 한 곳에 둔다: 이력은 보조 입력이라 인프라 실패(import·공급자 생성)는
    삼키고 이력 없이 sim.run을 계속한다 — 심을 건너뛰면 손실 포지션이 방치된다.
    단 TypeError·AttributeError·KeyError는 프로그래밍 오류라 그대로 올려 상위
    핸들러가 기록하게 한다. 삼키면 모든 적응형 청산이 조용히 고정 %로 퇴화한다.
    **재던지기는 공급 호출에만 적용된다.** 공급자 조달은 KeyError를 포함해 모든 예외를
    삼킨다(토큰 응답에 키가 없어도 이력 없이 진행). 조달 구간은 재던지지 않는다.
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
            provider, log=log, label=sim.__class__.__name__)
    except (TypeError, AttributeError, KeyError):
        raise
    except Exception as e:
        sim.price_history = {}
        log_error(f"보유 이력 공급 실패(이력 없이 진행) {type(e).__name__}: {e!r}")
