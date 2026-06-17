"""
KOSPI top100 종가 CSV → Sim1~7 월별 백테스트
==============================================
입력: output/kospi_top100_close.csv  (행=날짜, 열=종목코드_종목명)
출력: 콘솔 월별 NAV 표 + output/bt_monthly_result.csv

[가정]
- amount=30B  : 모든 유동성 필터 통과
- tick_power=0: 체결강도 조건 면제 (KIS 데이터 없음 처리와 동일)
- buzz=500     : Sim1 화제성 필터 통과 (buzz_count>=500 분기)
- foreign=0   : 외인 중립 (Sim2/6 외인 조건 무력화)
- market_index_healthy=True
이 가정 하에서 각 sim의 가격/ATR/ADX 기반 진입·청산 로직만 비교.
"""
import os, sys, csv, io, contextlib, shutil

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, _ROOT)

from src.strategy.simulators.sim1_psych       import PsychDivergenceSimulator
from src.strategy.simulators.sim2_spillover   import SectorSpilloverSimulator
from src.strategy.simulators.sim3_risk        import SmartRiskSimulator
from src.strategy.simulators.sim4_bull_momentum import BullMomentumSimulator
from src.strategy.simulators.sim5_sideways_swing import SidewaysSwingSimulator
from src.strategy.simulators.sim6_bear_hedge  import BearHedgeSimulator
from src.strategy.simulators.sim0_libero      import LiberoSimulator

INITIAL_CASH   = 3_000_000
ASSUMED_AMOUNT = 30_000_000_000
CSV_PATH       = os.path.join(_ROOT, 'output', 'kospi_top100_close.csv')
OUT_CSV        = os.path.join(_ROOT, 'output', 'bt_monthly_result.csv')
TMP_DIR        = os.path.join(_ROOT, 'data', '_bt_csv_tmp')


# ── 데이터 로드 ───────────────────────────────────────
def load_csv(path: str):
    """Returns (dates: list[str], stocks: list[dict{code,name}], prices: dict{code: list[float]})"""
    with open(path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    dates = [r['date'] for r in rows]
    cols = [c for c in rows[0].keys() if c != 'date']

    stocks = []
    for col in cols:
        parts = col.split('_', 1)
        stocks.append({'code': parts[0], 'name': parts[1] if len(parts) > 1 else parts[0], 'col': col})

    prices = {s['code']: [] for s in stocks}
    for row in rows:
        for s in stocks:
            val = row.get(s['col'], '').strip()
            prices[s['code']].append(float(val) if val else None)

    return dates, stocks, prices


# ── 시뮬레이터 초기화 ─────────────────────────────────
def make_sims():
    os.makedirs(TMP_DIR, exist_ok=True)
    sims = {
        'Sim1_심리괴리':   PsychDivergenceSimulator(INITIAL_CASH),
        'Sim2_수급동승':   SectorSpilloverSimulator(INITIAL_CASH),
        'Sim3_스마트리스크': SmartRiskSimulator(INITIAL_CASH),
        'Sim4_상승모멘텀': BullMomentumSimulator(INITIAL_CASH),
        'Sim5_추세눌림목': SidewaysSwingSimulator(INITIAL_CASH),
        'Sim6_하락줍줍':   BearHedgeSimulator(INITIAL_CASH),
        'Sim0_리베로':     LiberoSimulator(0),
    }
    for tag, s in sims.items():
        s.state_file = os.path.join(TMP_DIR, f'{tag}_state.json')
        s.log_file   = os.path.join(TMP_DIR, f'{tag}_log.json')
        s.csv_file   = os.path.join(TMP_DIR, f'{tag}_hist.csv')
        s.reset_state()
    return sims


# ── candidates 빌드 ───────────────────────────────────
def build_candidates(stocks, prices, day_idx):
    candidates = []
    for s in stocks:
        code = s['code']
        hist = prices[code]

        cur = hist[day_idx]
        if cur is None:
            continue

        prev = next((hist[i] for i in range(day_idx - 1, -1, -1) if hist[i] is not None), None)
        change_rate = ((cur - prev) / prev * 100) if prev else 0.0

        sparkline = [h for h in hist[max(0, day_idx - 19):day_idx + 1] if h is not None]

        # period_change_rate: sparkline 전체 기간 등락
        period_change = ((sparkline[-1] - sparkline[0]) / sparkline[0] * 100) if len(sparkline) >= 2 else 0.0

        candidates.append({
            'code':                code,
            'name':                s['name'],
            'price':               cur,
            'amount':              ASSUMED_AMOUNT,
            'tick_power':          0.0,       # 조건 면제
            'change_rate':         f'{change_rate:+.2f}%',
            'period_change_rate':  period_change,
            'recent_posts_count':  500,        # Sim1 buzz 통과
            'avg_posts':           1,
            'foreign_change':      0.0,
            'foreign_rate':        0.0,
            'prev_foreign_rate':   0.0,
            'consecutive_days':    1,
            'sentiment':           '',
            'sparkline_price':     sparkline,
        })
    return candidates


# ── 메인 ─────────────────────────────────────────────
def main():
    print(f'[1] CSV 로드: {CSV_PATH}')
    dates, stocks, prices = load_csv(CSV_PATH)
    print(f'    {len(dates)}일 × {len(stocks)}종목')

    sims = make_sims()
    sim_names = list(sims.keys())

    # 월별 NAV 기록: {sim_name: {yyyymm: nav}}
    monthly_nav: dict[str, dict[str, float]] = {n: {} for n in sim_names}
    cur_month = ''

    print(f'[2] 시뮬레이션 실행 중...')
    for day_idx, date_str in enumerate(dates):
        candidates = build_candidates(stocks, prices, day_idx)
        if not candidates:
            continue
        current_prices = {c['code']: c['price'] for c in candidates}

        ym = date_str[:6]  # YYYYMM
        prev_ym = cur_month
        cur_month = ym

        for name, sim in sims.items():
            sim.state['market_index_healthy'] = True
            with contextlib.redirect_stdout(io.StringIO()):
                sim.run(candidates, current_prices=current_prices)
            stats = sim.calculate_stats(current_prices)
            nav = stats['total_asset']

            # 월 마지막 날 NAV 기록 (다음 날이 다른 달이거나 마지막 날)
            is_last_of_month = (
                day_idx == len(dates) - 1 or
                dates[day_idx + 1][:6] != ym
            )
            if is_last_of_month:
                monthly_nav[name][ym] = nav

        if day_idx % 20 == 0:
            print(f'  {date_str} ({day_idx+1}/{len(dates)}) ...')

    # ── 월별 수익률 계산 ──────────────────────────────
    all_months = sorted({ym for nav in monthly_nav.values() for ym in nav})

    print('\n[3] 결과\n')

    # 헤더 출력
    col_w = 18
    month_w = 9
    header = f"{'전략':<{col_w}}" + ''.join(f"{m:>{month_w}}" for m in all_months) + f"{'누적수익률':>{month_w+2}}"
    print(header)
    print('-' * len(header))

    result_rows = []
    for name in sim_names:
        if name.startswith('Sim7'):
            continue
        nav_map = monthly_nav[name]
        row_vals = []
        prev_nav = INITIAL_CASH
        for ym in all_months:
            nav = nav_map.get(ym, prev_nav)
            ret = (nav / prev_nav - 1) * 100 if prev_nav else 0.0
            row_vals.append(ret)
            prev_nav = nav

        final_nav = nav_map.get(all_months[-1], INITIAL_CASH)
        total_ret = (final_nav / INITIAL_CASH - 1) * 100

        row_str = f"{name:<{col_w}}" + ''.join(f"{v:>+{month_w}.1f}%" for v in row_vals) + f"{total_ret:>+{month_w+1}.1f}%"
        print(row_str)
        result_rows.append([name] + [f'{v:+.2f}%' for v in row_vals] + [f'{total_ret:+.2f}%'])

    # CSV 저장
    with open(OUT_CSV, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['전략'] + all_months + ['누적수익률'])
        w.writerows(result_rows)
    print(f'\n→ {OUT_CSV} 저장 완료')

    # 임시 파일 정리
    shutil.rmtree(TMP_DIR, ignore_errors=True)


if __name__ == '__main__':
    main()
