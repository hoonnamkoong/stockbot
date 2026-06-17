"""
[백테스트] 2026-01 ~ 최신 trending_integrated 스냅샷으로 Sim1~7 수익률 계산.

[데이터 한계 & 가정]
- 과거 스냅샷에는 거래대금(amount)/거래량/체결강도(tick_power)가 없음.
- 7개 시뮬 모두 amount 유동성 게이트 + 일부는 체결강도 검증을 요구 → 원본 그대로면 진입 0건.
- 가정: '화제성(게시글 급증) 필터를 통과한 종목은 유동성·수급 충분'으로 보고
  amount를 30B(=tick_power fallback 통과값)로 설정. 즉 유동성/체결강도 필터는 '통과'로 두고
  가격·sparkline 기반 모멘텀/청산 로직만으로 상대 비교한다.
- sparkline_price는 코드별 가격 시퀀스(스냅샷 누적)로 역산. (일봉이 아닌 스냅샷 틱 기준)
"""
import os
import re
import sys
import glob
import collections
import pandas as pd

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.strategy.simulators.sim1_psych import PsychDivergenceSimulator
from src.strategy.simulators.sim2_spillover import SectorSpilloverSimulator
from src.strategy.simulators.sim3_risk import SmartRiskSimulator
from src.strategy.simulators.sim4_bull_momentum import BullMomentumSimulator
from src.strategy.simulators.sim5_sideways_swing import SidewaysSwingSimulator
from src.strategy.simulators.sim6_bear_hedge import BearHedgeSimulator
from src.strategy.simulators.sim0_libero import LiberoSimulator

ASSUMED_AMOUNT = 30_000_000_000  # 유동성/체결강도 게이트 통과용 (데이터 부재 가정)

COL_MAP = {
    '종목명': 'name', '현재가': 'price', '등락률': 'change_rate',
    '당일_게시글수': 'recent_posts_count', '게시물': 'recent_posts_count', '게시글수': 'recent_posts_count',
    '현재_외국인비중': 'foreign_rate', '외인비중': 'foreign_rate', '외인소진율': 'foreign_rate',
    '어제_종가': 'prev_close', '전일종가': 'prev_close',
    '어제_외국인비중': 'prev_foreign_rate', '전일외인': 'prev_foreign_rate',
    '외인변화': 'foreign_change', '연속_등록': 'consecutive_days', '연속': 'consecutive_days',
    '시장구분': 'market', '감정분석': 'sentiment', '감정': 'sentiment',
}


def to_float(v, default=0.0):
    if v is None:
        return default
    try:
        return float(str(v).replace('%', '').replace(',', '').replace('+', '').strip())
    except (ValueError, TypeError):
        return default


def make_sims():
    return {
        'Sim1_심리괴리': PsychDivergenceSimulator(3000000),
        'Sim2_수급동승': SectorSpilloverSimulator(3000000),
        'Sim3_스마트리스크': SmartRiskSimulator(3000000),
        'Sim4_상승모멘텀': BullMomentumSimulator(3000000),
        'Sim5_추세눌림목': SidewaysSwingSimulator(3000000),
        'Sim6_하락줍줍': BearHedgeSimulator(3000000),
        'Sim0_리베로': LiberoSimulator(0),
    }


def isolate(sim, tag):
    """state/log/csv를 임시 파일로 격리하고 클린 리셋."""
    sim.state_file = os.path.join(_REPO_ROOT, 'data', f'_bt_{tag}_state.json')
    sim.log_file = os.path.join(_REPO_ROOT, 'data', f'_bt_{tag}_log.json')
    sim.csv_file = os.path.join(_REPO_ROOT, 'data', f'_bt_{tag}_hist.csv')
    sim.reset_state()


def main():
    files = glob.glob(os.path.join(_REPO_ROOT, 'data', 'trending_integrated_*.xlsx'))
    # YYYYMMDD 타임스탬프 스냅샷만 (월별 집계/bare 파일 제외, 중복 방지)
    snaps = sorted([f for f in files if re.search(r'trending_integrated_\d{8}', os.path.basename(f))])
    print(f'스냅샷 파일 {len(snaps)}개 (기간: {os.path.basename(snaps[0])} ~ {os.path.basename(snaps[-1])})')

    sims = make_sims()
    for name, s in sims.items():
        isolate(s, name)

    price_history = collections.defaultdict(list)
    buzz_history = collections.defaultdict(list)
    regime_log = collections.Counter()
    snap_count = 0

    for fp in snaps:
        try:
            df = pd.read_excel(fp)
        except Exception as e:
            print(f'  [skip] {os.path.basename(fp)}: {e}')
            continue
        df = df.rename(columns=COL_MAP)
        if 'code' not in df.columns or 'price' not in df.columns:
            continue
        df['code'] = df['code'].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(6)

        candidates = []
        for _, row in df.iterrows():
            code = row['code']
            price = to_float(row.get('price'))
            if price <= 0:
                continue
            buzz = to_float(row.get('recent_posts_count'))
            price_history[code].append(price)
            buzz_history[code].append(buzz)

            # 외인변화: 직접 컬럼 없으면 현재-전일 외인비중으로 계산
            fc = row.get('foreign_change')
            if fc is None or (isinstance(fc, float) and pd.isna(fc)):
                fc = to_float(row.get('foreign_rate')) - to_float(row.get('prev_foreign_rate'))
            else:
                fc = to_float(fc)

            cr = row.get('change_rate', 0)
            cr = cr if isinstance(cr, str) else f'{to_float(cr):+.2f}%'

            candidates.append({
                'code': code,
                'name': str(row.get('name', code)),
                'price': price,
                'amount': ASSUMED_AMOUNT,          # [가정] 유동성/체결강도 게이트 통과
                'change_rate': cr,
                'foreign_change': fc,
                'recent_posts_count': int(buzz),
                'avg_posts': sum(buzz_history[code]) / len(buzz_history[code]),
                'sparkline_price': price_history[code][-5:],
                'consecutive_days': int(to_float(row.get('consecutive_days'), 1)) or 1,
                'sentiment': str(row.get('sentiment', '')),
                'tick_power': 0.0,                 # 부재 → validate는 amount fallback으로 통과
            })

        if not candidates:
            continue
        prices = {c['code']: c['price'] for c in candidates}
        for s in sims.values():
            s.state['market_index_healthy'] = True
            s.run(candidates, current_prices=prices)
        regime_log[sims['Sim7_리베로'].state.get('current_regime', '-')] += 1
        snap_count += 1

    # 결과 집계
    last_prices = {}
    for code, hist in price_history.items():
        last_prices[code] = hist[-1]

    print(f'\n처리 스냅샷 {snap_count}개 | 추적 종목 {len(price_history)}개')
    print(f'리베로 국면 분포: {dict(regime_log)}')
    print('\n=== 백테스트 수익률 (초기자본 300만원, 유동성/체결강도 게이트 통과 가정) ===')
    rows = []
    for name, s in sims.items():
        if name.startswith('Sim7'):
            continue
        st = s.calculate_stats(last_prices)
        rows.append({
            '전략': name,
            '최종자산': round(st['total_asset']),
            '수익률(%)': round(st['profit_rate'], 2),
            '승률(%)': round(st['win_rate'], 1),
            '수익팩터': round(st['profit_factor'], 2),
            'MDD(%)': round(st['mdd'], 2),
            '거래수': len(s._load_trade_logs()),
            '보유': st['holdings_count'],
        })
    rows.sort(key=lambda r: r['수익률(%)'], reverse=True)
    print(pd.DataFrame(rows).to_string(index=False))

    # 임시 파일 정리
    for s in sims.values():
        for f in [s.state_file, s.log_file, s.csv_file]:
            if os.path.exists(f):
                os.remove(f)


if __name__ == '__main__':
    main()
