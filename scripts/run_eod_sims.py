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
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from src.strategy.simulators.kr_calendar import watchlist_target_date  # noqa: E402
from src.strategy.simulators.sim9_1_donchian import CHANNEL_DAYS  # noqa: E402
from src.strategy.simulators.sim11_minervini import (  # noqa: E402
    MA_EXIT_WINDOW as SIM11_MA_EXIT_WINDOW,
    _sma as _sim11_sma,
)

DEFAULT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                           'output', 'ohlcv_top100.csv')
DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')

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

    amount_history도 같은 구간이다(Sim9-1의 '거래대금 급증' 분모). 이 심의 입력
    경로는 둘이다 — 장중 스크래퍼(data_fetcher)와 여기. 한쪽만 배선하면 다른
    쪽이 조용히 0건이 된다.
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
        amounts = [x[2] for x in rows]
        out.append({
            'code': code,
            'name': names[code],
            'price': closes[-1],
            'current_price': closes[-1],
            'amount': rows[-1][2],
            'range_history': closes[-CHANNEL_DAYS - 1:-1],
            # [Sim9-1] 거래대금 급증의 분모. range_history와 같이 **직전**
            # CHANNEL_DAYS일이다 — 당일이 분모에 섞이면 급증이 스스로 희석된다.
            'amount_history': amounts[-CHANNEL_DAYS - 1:-1],
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
                             pace_interval: float = 0.1,
                             budget_sec: float = 600.0) -> list[dict]:
    """Sim11(미너비니) 후보를 KIS 실시간 조회로 만든다.

    종목당 최대 3콜(일봉 페이지네이션 포함 시 더 늘 수 있음)이 필요해
    ohlcv_top100.csv만으로는 못 만든다. `_enrich_universe`(trade_engine.py)의
    페이싱과 같은 이유로 초당 호출을 눌러 유량제한(20건/초)을 지킨다 — 여긴
    하루 1회 배치라 예산이 넉넉해 10건/초보다 느슨한 기본값을 쓴다.

    daily_closes는 **당일을 뺀** 과거 종가다(Sim9-1의 range_history와 같은
    전제 — 당일이 섞이면 돌파 판정이 정의상 성립하지 않는다). 조회 실패·
    이력 부족 종목은 건너뛴다 — 없는 근거로 사지 않는다.

    budget_sec: 전체 조회에 허용할 최대 초. 초과 시 남은 종목을 건너뛰고
    수집된 후보만 돌려준다. collect 잡의 timeout-minutes(20분)보다 짧게 유지해
    KIS 응답 지연이 반복돼도 잡 타임아웃으로 런이 취소되지 않도록 한다.
    """
    import time as _time
    out = []
    last_call = 0.0
    today = _time.strftime('%Y%m%d')
    deadline = _time.monotonic() + budget_sec

    def _pace():
        nonlocal last_call
        wait = last_call + pace_interval - _time.monotonic()
        if wait > 0:
            _time.sleep(wait)
        last_call = _time.monotonic()

    for i, (code, name) in enumerate(pairs):
        if _time.monotonic() >= deadline:
            remaining = len(pairs) - i
            log(f'[EOD][Sim11] 예산 {budget_sec:.0f}초 소진 — '
                f'남은 {remaining}종목 건너뜀 (수집 완료: {len(out)}종목)')
            break
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


def build_sim11_watchlist(candidates: list[dict], log=print,
                          held_codes=()) -> dict[str, dict]:
    """Sim11 후보들에서 감시 목록(오늘 밤 기준, 내일부터 쓸 pivot_price·ma50)을 만든다.

    2026-08-20 재설계: 예전엔 이 자리에서 바로 sim.run()을 불러 그날 종가로
    매수까지 끝냈다 — 마감 후 배치가 이미 지난 가격으로 "샀다"고 기록하는
    룩어헤드였다(program-trading-parity-mandate 위반, 실전으로 승격해도
    그 가격에 주문을 낼 방법이 없다). 이제 여기서는 자격 판정(추세 템플릿+
    실적 가속+VCP 압축)까지만 하고 결과를 파일로 남긴다 — 실제 매수/매도는
    Sim11이 다른 버즈 불필요 심들과 같은 장중 1분 루프에서 실시간가로 한다.
    """
    from src.strategy.simulators.sim11_minervini import build_watchlist_entry
    entries: dict[str, dict] = {}
    # 후보 100 → 감시목록 1이 평상시 값인 심이다. 그 99가 어느 게이트에서
    # 떨어졌는지 남지 않으면 "KIS가 실적을 안 줬다(결손)"와 "실적이 기준에
    # 못 미친다(전략)"를 밖에서 구분할 수 없다 — 고치는 곳이 서로 다르다.
    funnel: list[dict] = []
    for c in candidates:
        entry = build_watchlist_entry(c, funnel=funnel)
        if entry:
            entries[c['code']] = entry
            continue
        # 자격을 잃은 **보유** 종목은 ma50만 실어 남긴다 — 청산 전용 항목.
        # decide_minervini의 50일선 이탈 청산은 오늘 감시 목록에서 ma50을 읽는데,
        # 등재 자격인 _trend_template_ok가 `price > ma50`을 요구한다. 그래서
        # 50일선을 깬 종목은 정의상 목록에 못 오르고, 청산이 필요한 바로 그
        # 순간에 ma50이 None이 되어 청산이 조용히 건너뛰어졌다(하드손절만 남는다).
        # pivot_price를 None으로 두어 재매수는 막는다(decide_minervini의 no_pivot).
        if c['code'] not in held_codes:
            continue
        closes_through_today = (c.get('daily_closes') or []) + [float(c.get('price', 0) or 0)]
        ma50 = _sim11_sma(closes_through_today, SIM11_MA_EXIT_WINDOW)
        if ma50 is None:
            log(f"[EOD] 심11 보유 {c['code']} — 종가 표본 부족으로 청산 지표(ma50) 측정 불가")
            continue
        entries[c['code']] = {'name': c.get('name', c['code']),
                              'pivot_price': None, 'ma50': ma50}

    # Actions 로그는 며칠 뒤 사라지므로 diag_id로 db-data에도 남긴다.
    from src.strategy.simulators.base_simulator import log_funnel
    log_funnel('미너비니 감시목록', candidates, funnel,
               buys=len(entries), seen=len(candidates),
               diag_id='sim11_watchlist', early_exit_breaks=False)
    return entries


def load_sim11_holdings(data_dir: str = DEFAULT_DATA_DIR, log=print) -> dict[str, str]:
    """심11이 지금 보유 중인 {코드: 이름}. 못 읽으면 빈 dict.

    시뮬레이터를 인스턴스화하지 않는다 — BaseSimulator.load_state는 상태 파일이
    없으면 reset_state로 넘어가 거래 이력 CSV를 지운다. 여기서는 읽기만 한다.
    파일명 규칙은 BaseSimulator.__init__(sim_<name.lower()>_state.json)와 같다.
    """
    path = os.path.join(data_dir, 'sim_minervini_state.json')
    try:
        with open(path, encoding='utf-8-sig') as f:
            portfolio = json.load(f).get('portfolio') or {}
    except Exception as e:
        # 조용히 빈 dict로 넘어가면 청산 지표가 빠진 채 런이 초록으로 끝난다.
        log(f'[EOD] 심11 상태를 못 읽었다({type(e).__name__}: {e}) — '
            '보유 종목 청산 지표(ma50)가 감시 목록에 실리지 않는다')
        return {}
    return {code: (p or {}).get('name', code) for code, p in portfolio.items()}


def load_previous_sim11_watchlist(path: str | None = None) -> list[str]:
    """직전 배치가 만든 감시 목록의 종목코드. 없거나 못 읽으면 빈 목록 —
    조회 순서 힌트일 뿐이라 배치를 멈출 이유가 아니다."""
    if path is None:
        from src.strategy.simulators.sim11_minervini import WATCHLIST_PATH
        path = WATCHLIST_PATH
    try:
        with open(path, encoding='utf-8-sig') as f:
            return list((json.load(f).get('entries') or {}).keys())
    except Exception:
        return []


def prioritize_sim11_pairs(pairs: list[tuple[str, str]], held: dict[str, str],
                           previous: list[str]) -> list[tuple[str, str]]:
    """조회 순서: 보유 종목 → 직전 감시 목록 → 나머지.

    candidates_from_kis_live는 예산이 다하면 뒤쪽을 버린다. 유니버스가 코드순이라
    매일 같은 뒤쪽 절반이 잘렸고 그 안에 보유 종목이 있었다(2026-09-18: 한화생명
    088350 미처리 → 50일선 이탈 청산 지표 없음). 청산 지표가 먼저다.

    보유 종목은 유니버스 밖이어도 넣는다 — 시총·유동성에서 밀려났다고 청산을
    건너뛸 수는 없다. 직전 감시 목록은 매수 후보라 오늘 유니버스에 있을 때만.
    """
    names = dict(pairs)
    head: list[tuple[str, str]] = [(c, names.get(c) or n) for c, n in held.items()]
    head += [(c, names[c]) for c in previous if c in names and c not in held]
    first = {c for c, _ in head}
    return head + [(c, n) for c, n in pairs if c not in first]


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
    # 인자를 명시하지 않는다. 여기서 숫자를 적으면 **이 심만** 다른 초기자본으로
    # 돌아 대시보드와 텔레그램이 서로 다른 수익률을 말한다. 심의 기본값이
    # DEFAULT_INITIAL_CASH를 가리키므로 그냥 비워 두는 것이 단일 원천이다.
    sim = DonchianBreakoutSimulator()
    before = len(sim.state.get('portfolio', {}))
    stats = run_donchian(sim, candidates)
    after = len(sim.state.get('portfolio', {}))
    print(f'[EOD] 심9-1 실행: 후보 {len(candidates)}종목, 보유 {before} → {after}, '
          f'현금 {sim.state.get("cash", 0):,.0f}')
    return 0 if stats is not None else 1


# 심11 유니버스 상한. 코스피 시총 상위 N을 받아 유동성으로 거른다.
#
# 왜 100이 아닌가 — 2026-09-16 깔때기 실측(후보 100 → 감시목록 1):
#   추세 템플릿 완주 15/100, 그중 실적 게이트가 15 → 2로 **87%를 자른다**.
#   둘 다 조건이 과해서가 아니라 **성숙 기업이라서**다. 미너비니가 노리는 것은
#   실적 가속 중인 성장 주도주이고 시총 상위 100은 그 못이 아니다.
#   그래서 임계값을 낮추지 않고 못을 넓힌다.
#
# 왜 400인가 — 2026-09-15 EOD 실측 100종목 109초(약 1.1초/종목). 400이면 7.3분이고
#   collect 잡 타임아웃 20분 중 현재 사용이 ~2분이라 여유가 있다. 코스피 상장이
#   ~950종목이라 시총 상위 400이면 사실상 유의미한 전부다. 그 아래는 유동성
#   필터가 어차피 걸러낸다.
#
# ⚠ 코스닥은 뺀다(2026-09-16 사용자 결정). 한국의 성장 주도주는 코스닥에 많이
#   사는 만큼, 이 제외가 S1의 상한을 낮춘다는 것을 알고 내린 결정이다.
SIM11_UNIVERSE_LIMIT = 400


def sim11_universe(seed_path: str = DEFAULT_CSV,
                   limit: int = SIM11_UNIVERSE_LIMIT,
                   log=print) -> list[tuple[str, str]]:
    """심11이 오늘 들여다볼 (code, name) 목록.

    **CSV가 아니라 코드 목록이 필요하다** — candidates_from_kis_live가 종목별
    230일 이력을 KIS로 직접 받으므로, ohlcv_top100.csv는 씨앗으로만 쓰여 왔다.

    유동성 미달은 **KIS를 부르기 전에** 버린다. 비용이 드는 건 일봉 조회이지
    목록이 아니다(네이버는 한 종목당 추가 호출이 없다).

    ETF 제외는 naver_api가 한다(stock_only) — 여기서 또 거르면 규칙이 둘로 갈린다.

    ⚠ `ohlcv_top100.csv`는 이 함수가 바뀌어도 그대로다. 리베로 trend·breadth와
    심9-1이 그 파일을 먹어서, 그걸 건드리면 국면 판정이 딸려 온다.
    """
    from src.data import naver_api
    from src.strategy.simulators.sim11_minervini import MIN_AMOUNT

    rows = None
    try:
        rows = naver_api.stock_list('marketValue', 'KOSPI', limit)
    except Exception as e:
        log(f'[EOD] 심11 유니버스 조회 예외({type(e).__name__}: {e})')

    if not rows:
        # 2026-09-10에 네이버가 302로 옮겨가 EOD가 통째로 죽었다. 목록을 못 받았다고
        # 심11을 쉬게 하면 못을 넓히려다 있던 것도 잃는다 — 씨앗으로 계속한다.
        log('[EOD] 심11 유니버스 조회 실패 — 직전 종가 CSV의 종목 구성으로 계속한다')
        return codes_and_names_from_ohlcv(seed_path)

    seen: dict[str, str] = {}
    thin = 0
    for r in rows:
        code = (r.get('code') or '').strip()
        if not code or code in seen:
            continue
        if float(r.get('amount') or 0) < MIN_AMOUNT:
            thin += 1
            continue
        seen[code] = (r.get('name') or '').strip()
    log(f'[EOD] 심11 유니버스: 코스피 시총 상위 {len(rows)}종목 중 '
        f'거래대금 통과 {len(seen)}종목 (유동성 미달 {thin})')
    return sorted(seen.items())


def _run_sim11(path: str) -> int:
    """심11 감시 목록을 하루 1회 갱신한다. 실제 매수/매도는 안 한다 —
    Sim11은 더 이상 IS_EOD가 아니라 장중 1분 루프에서 이 감시 목록을 읽어
    실시간가로 산다(build_sim11_watchlist 참고)."""
    pairs = sim11_universe(seed_path=path)
    if not pairs:
        print(f'[EOD] 심11 유니버스 0건 ({path}) — 감시 목록을 만들지 않는다')
        return 1
    held = load_sim11_holdings()
    # 보유 종목은 유니버스 밖이어도 맨 앞에서 조회한다 — 예산에 잘려도, 시총
    # 순위에서 밀려나도 50일선 이탈 청산 지표(ma50)는 만들어야 한다.
    universe_size = len(pairs)
    pairs = prioritize_sim11_pairs(pairs, held, load_previous_sim11_watchlist())
    if held:
        print(f'[EOD] 심11 보유 {list(held)} — 우선 조회')
    try:
        from src.trade.kis_data_provider import KISDataProvider
        kis = KISDataProvider()
    except Exception as e:
        print(f'[EOD] 심11 KIS 초기화 실패 — 실행하지 않는다: {e}')
        return 1
    candidates = candidates_from_kis_live(pairs, kis, log=print)
    if not candidates:
        print('[EOD] 심11 후보 0건(전부 조회 실패·이력 부족) — 감시 목록을 만들지 않는다')
        return 1
    entries = build_sim11_watchlist(candidates, log=print, held_codes=set(held))
    from src.strategy.simulators.sim11_minervini import save_watchlist
    # 배치를 돌린 날이 아니라 **아직 안 끝난 가장 가까운 세션**을 찍는다.
    # 마감 뒤 16시 배치가 '오늘'을 찍으면 그 키를 읽을 장중 사이클이 없다 —
    # 심11이 08-20 배포 이래 매수 0건이던 원인이다(2026-08-27 확인).
    target = watchlist_target_date()
    save_watchlist(entries, target)
    print(f'[EOD] 심11 감시 목록 갱신: 유니버스 {universe_size}종목, 후보 {len(candidates)}종목, '
          f'감시 목록 {len(entries)}종목 (날짜 {target})')
    return 0


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
