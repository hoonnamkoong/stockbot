"""장 마감 후 1회 실행하는 시뮬레이터 러너 (현재 Sim9-1 돈치안).

왜 장중 루프에서 뺐는가
-----------------------
심9-1은 KOSPI top100 일봉으로 검증된 전략인데 장중 버즈 유니버스에서 돌고
있었다. 2026-07-29 실측: 거래대금 z>0을 통과하는 종목이 28개 중 3개뿐이고
전부 초대형주(삼성전자·SK하이닉스·삼성전자우)인데 그 종목들은 20일 채널을
안 뚫는다(0.53~0.72). 채널 돌파는 소형주에서 나오므로 두 조건의 교집합이
구조적으로 비어 있었다.

게이트를 스케일 무관 지표로 바꾸는 안은 백테스트가 반증했다(top100 100거래일):
자기 20일평균 대비 거래량 배율 1.0/1.5/2.0이 전부 게이트 없음과 동급이거나
더 나빴다. 절대 거래대금 z가 하던 일은 '거래량 급증 탐지'가 아니라 '유동성
큰 종목 선호'였다. 그러므로 고칠 것은 게이트가 아니라 유니버스다.

돈치안은 일봉 전략이라 장중 10분 루프가 필요 없다. eod_data.yml이 16:00에
만드는 ohlcv_top100.csv로 하루 1회 돌린다 — 백테스트와 같은 유니버스, 같은
데이터, 추가 네트워크 콜 0.

실행: PYTHONPATH=. python scripts/run_eod_sims.py [ohlcv_csv_경로]
"""
import csv
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from src.strategy.simulators.sim9_1_donchian import CHANNEL_DAYS  # noqa: E402

DEFAULT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                           'output', 'ohlcv_top100.csv')

# ETF는 유니버스에서 뺀다. ETF라서가 아니라 손절 규격이 안 맞아서다 —
# 지수 추종 ETF는 변동성이 개별주보다 훨씬 낮아 진입가 - 2*ATR 손절선이
# 진입가에 바짝 붙고, 정상적인 잡음에도 1~2일 만에 털린다.
# 실측(top100 100거래일): 혼합 유니버스에서 산 ETF 12건 중 10건이 손실이고
# 그중 9건이 ATR손절이었다. 추세를 타면 ETF도 번다(TIGER 미국S&P500 +11.81%,
# 39일). 다만 그 전에 털리면서 6개뿐인 슬롯을 낭비해 개별주를 밀어낸다.
# NAV: 전체 100종목 +2.37% → ETF 제외 89종목 +20.46%.
# 손절을 변동성 상대화(ATR%)로 바꾸면 다시 볼 여지가 있다.
_ETF_BRANDS = ('KODEX', 'TIGER', 'KBSTAR', 'ARIRANG', 'HANARO', 'SOL', 'ACE',
               'PLUS', 'RISE', 'KIWOOM', 'TIMEFOLIO', 'WOORI', '마이티', '파워')
# 브랜드가 이름 맨 앞에서 공백으로 끊길 때만 ETF로 본다. 부분 문자열로 보면
# '미래에셋증권'·'SOLUS첨단소재' 같은 일반 종목까지 걸러낸다.
_ETF_RE = re.compile(r'^(' + '|'.join(_ETF_BRANDS) + r')(\s|$)')


def is_etf(name: str) -> bool:
    return bool(_ETF_RE.match((name or '').strip()))


def candidates_from_ohlcv(path: str) -> list[dict]:
    """일봉 CSV → 심이 받는 후보 리스트.

    range_history는 **직전** CHANNEL_DAYS일이다. 당일을 넣으면
    max(채널) >= 당일종가라 돌파가 정의상 불가능해진다(백테스트도 dates[t-n:t]).
    이력이 모자란 종목은 채널을 만들 수 없으므로 후보에서 뺀다 — 없는 근거로
    사지 않는다.
    """
    if not os.path.exists(path):
        return []
    order: list[str] = []
    bars: dict[str, list[tuple]] = {}
    names: dict[str, str] = {}
    try:
        with open(path, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                code = (r.get('code') or '').strip()
                if not code:
                    continue
                try:
                    close = float(r['close'])
                    amount = float(r['amount'])
                except (KeyError, TypeError, ValueError):
                    continue
                if code not in bars:
                    bars[code] = []
                    order.append(code)
                names[code] = (r.get('name') or code).strip()
                bars[code].append((r.get('date', ''), close, amount))
    except OSError:
        return []

    out = []
    for code in order:
        if is_etf(names[code]):
            continue
        rows = sorted(bars[code], key=lambda x: x[0])
        if len(rows) < CHANNEL_DAYS + 1:
            continue
        closes = [x[1] for x in rows]
        out.append({
            'code': code,
            'name': names[code],
            'price': closes[-1],
            'current_price': closes[-1],
            'amount': rows[-1][2],
            'range_history': closes[-CHANNEL_DAYS - 1:-1],
        })
    return out


def run_donchian(sim, candidates: list[dict]):
    """심9-1을 1회 실행하고 결과 통계를 돌려준다."""
    prices = {c['code']: c['price'] for c in candidates}
    return sim.run(candidates, current_prices=prices)


def codes_and_names_from_ohlcv(path: str) -> list[tuple[str, str]]:
    """ohlcv_top100.csv의 고유 (code, name), ETF 제외 — Sim11 유니버스 시드.

    이 CSV 자체(종가만)로는 Sim11이 부족하다(150/200일선·분기 실적이 없다).
    이미 쌓인 종목 풀만 재사용하고, 값은 candidates_from_kis_live가 KIS로
    직접 채운다.
    """
    if not os.path.exists(path):
        return []
    seen: dict[str, str] = {}
    try:
        with open(path, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                code = (r.get('code') or '').strip()
                name = (r.get('name') or '').strip()
                if not code or code in seen or is_etf(name):
                    continue
                seen[code] = name
    except OSError:
        return []
    return sorted(seen.items())


def candidates_from_kis_live(pairs: list[tuple[str, str]], kis, log=print,
                             history_days: int = 230,
                             pace_interval: float = 0.1) -> list[dict]:
    """Sim11(미너비니) 후보를 KIS 실시간 조회로 만든다.

    종목당 최대 3콜(일봉 페이지네이션 포함 시 더 늘 수 있음)이 필요해
    ohlcv_top100.csv만으로는 못 만든다. `_enrich_universe`(trade_engine.py)의
    페이싱과 같은 이유로 초당 호출을 눌러 유량제한(20건/초)을 지킨다 — 여긴
    하루 1회 배치라 예산이 넉넉해 10건/초보다 느슨한 기본값을 쓴다.

    daily_closes는 **당일을 뺀** 과거 종가다(Sim9-1의 range_history와 같은
    전제 — 당일이 섞이면 돌파 판정이 정의상 성립하지 않는다). 조회 실패·
    이력 부족 종목은 건너뛴다 — 없는 근거로 사지 않는다.
    """
    import time as _time
    out = []
    last_call = 0.0
    today = _time.strftime('%Y%m%d')

    def _pace():
        nonlocal last_call
        wait = last_call + pace_interval - _time.monotonic()
        if wait > 0:
            _time.sleep(wait)
        last_call = _time.monotonic()

    for code, name in pairs:
        try:
            _pace()
            hist = kis.get_daily_history(code, days=history_days)
            today_bar = hist[-1] if hist and hist[-1].get('date') == today else None
            closes_before_today = [h['close'] for h in (hist[:-1] if today_bar else hist)]
            if len(closes_before_today) < 220:
                continue

            _pace()
            quote = kis.get_price_quote(code) or {}
            _pace()
            growth = kis.get_earnings_growth(code) or {}

            price = today_bar['close'] if today_bar else quote.get('price', 0)
            amount = today_bar['amount'] if today_bar else quote.get('amount', 0)
            if not price:
                continue

            cand = {
                'code': code, 'name': name, 'price': price, 'amount': amount,
                'daily_closes': closes_before_today,
                'w52_hgpr': quote.get('w52_hgpr', 0), 'w52_lwpr': quote.get('w52_lwpr', 0),
            }
            if 'eps_growth_yoy' in growth:
                cand['eps_growth_yoy'] = growth['eps_growth_yoy']
            if 'revenue_growth_yoy' in growth:
                cand['revenue_growth_yoy'] = growth['revenue_growth_yoy']
            out.append(cand)
        except Exception as e:
            log(f'[EOD][Sim11] {code} 조회 실패(건너뜀): {e}')
            continue
    return out


def run_minervini(sim, candidates: list[dict]):
    """심11을 1회 실행하고 결과 통계를 돌려준다."""
    prices = {c['code']: c['price'] for c in candidates}
    return sim.run(candidates, current_prices=prices)


def _run_sim9_1(path: str) -> int:
    candidates = candidates_from_ohlcv(path)
    if not candidates:
        # 데이터가 없으면 아무것도 하지 않는다. 빈 후보로 run()을 돌리면
        # 보유분이 청산 판단 없이 방치되는 것과 같아 오해를 부른다.
        print(f'[EOD] 심9-1 후보 0건 ({path}) — 실행하지 않는다')
        return 1
    # registry를 거치지 않는다: 심9-1은 tradeable=false라 get_simulator_by_id가
    # 항상 None을 주고, registry는 yaml에 의존해 EOD 워크플로의 최소 의존성
    # (requests·beautifulsoup4)을 넘어선다.
    from src.strategy.simulators.sim9_1_donchian import DonchianBreakoutSimulator
    sim = DonchianBreakoutSimulator(initial_cash=3_000_000)
    before = len(sim.state.get('portfolio', {}))
    stats = run_donchian(sim, candidates)
    after = len(sim.state.get('portfolio', {}))
    print(f'[EOD] 심9-1 실행: 후보 {len(candidates)}종목, 보유 {before} → {after}, '
          f'현금 {sim.state.get("cash", 0):,.0f}')
    return 0 if stats is not None else 1


def _run_sim11(path: str) -> int:
    pairs = codes_and_names_from_ohlcv(path)
    if not pairs:
        print(f'[EOD] 심11 유니버스 0건 ({path}) — 실행하지 않는다')
        return 1
    try:
        from src.trade.kis_data_provider import KISDataProvider
        kis = KISDataProvider()
    except Exception as e:
        print(f'[EOD] 심11 KIS 초기화 실패 — 실행하지 않는다: {e}')
        return 1
    candidates = candidates_from_kis_live(pairs, kis, log=print)
    if not candidates:
        print('[EOD] 심11 후보 0건(전부 조회 실패·이력 부족) — 실행하지 않는다')
        return 1
    from src.strategy.simulators.sim11_minervini import MinerviniTrendSimulator
    sim = MinerviniTrendSimulator(initial_cash=3_000_000)
    before = len(sim.state.get('portfolio', {}))
    stats = run_minervini(sim, candidates)
    after = len(sim.state.get('portfolio', {}))
    print(f'[EOD] 심11 실행: 유니버스 {len(pairs)}종목, 후보 {len(candidates)}종목, '
          f'보유 {before} → {after}, 현금 {sim.state.get("cash", 0):,.0f}')
    return 0 if stats is not None else 1


def main() -> int:
    """심9-1·심11을 각각 독립적으로 돈다 — 한쪽이 실패해도 다른 쪽은 그대로 돈다.
    둘 다 실패해야 워크플로 스텝이 실패로 표시된다(호출부가 `|| echo`로
    감싸므로 EOD 배포 자체는 이 실패와 무관하게 계속된다)."""
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    r1 = _run_sim9_1(path)
    r2 = _run_sim11(path)
    return 0 if (r1 == 0 or r2 == 0) else 1


if __name__ == '__main__':
    raise SystemExit(main())
