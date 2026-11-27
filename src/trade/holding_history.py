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
        if (cand_by_code.get(code) or {}).get('price_history'):
            continue  # 후보가 이미 이력을 갖고 있으면 콜을 쓰지 않는다
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
