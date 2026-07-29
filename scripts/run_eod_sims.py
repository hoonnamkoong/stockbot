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


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    candidates = candidates_from_ohlcv(path)
    if not candidates:
        # 데이터가 없으면 아무것도 하지 않는다. 빈 후보로 run()을 돌리면
        # 보유분이 청산 판단 없이 방치되는 것과 같아 오해를 부른다.
        print(f'[EOD] 후보 0건 ({path}) — 실행하지 않는다')
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


if __name__ == '__main__':
    raise SystemExit(main())
