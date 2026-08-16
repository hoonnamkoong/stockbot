"""각 심이 읽는 필드가 실제로 채워지는지 라이브로 감사한다.

왜 만드는가 (2026-08-17): 심3이 후보의 **39%를 조용히 버리고** 있었다. KIS 업종명은
`전기·전자`인데 `sector_cache` 테이블은 `전기전자`라 매칭이 어긋났고, 심3은 섹터
평균이 없으면 그냥 `continue`라 로그에도 안 남았다. 같은 자리에서 PER도 기준이
어긋나 있었다(KIS는 연간 결산, 섹터 평균은 TTM).

**이 유형은 "신호가 약해서"가 아니라 "코드가 읽는 값이 안 채워져서" 생긴다.**
백테스트로는 절대 안 잡히고, 수익률만 보면 "전략이 별로네"로 오진한다.

무엇을 재는가: 심별로 `stock.get('X')`를 정적 추출 → 그 심의 유니버스를 실제로
받아 보강까지 태움 → 각 필드가 **몇 %나 실제 값을 갖는지** 센다.
결손(키 없음)과 0값을 구분한다 — 0은 정상일 수도 있지만 전량 0이면 죽은 필드다.

    PYTHONPATH=. python scripts/audit_sim_fields.py           # 전 심
    PYTHONPATH=. python scripts/audit_sim_fields.py sim3_risk # 하나만

장중에 돌려야 의미 있는 필드가 있다(tick_power, frgn_fake_ntby_qty 등).
"""
import collections
import glob
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

FIELD_RE = re.compile(r"(?:stock|s|cand|c|item)\.get\(\s*['\"]([a-z_0-9]+)['\"]")

# 후보 dict가 아니라 **보유 포지션**에서 읽는 키. 유니버스 감사 대상이 아니다.
PORTFOLIO_KEYS = {'avg_price', 'entry_date', 'buy_date', 'peak_price', 'pyramided',
                  'is_scaled_out', 'partial_sold_date', 'quantity', 'name'}
# 심0은 후보가 아니라 국면 관측치를 읽는다.
SKIP_SIMS = {'sim0_libero', 'sim10_orchestrator', 'sim7_report_follower'}
# 심이 **스스로 조회해 채우는** 필드. 보강이 안 넣는 게 정상이다.
SELF_FILLED = {('sim3_risk', 'per_ttm'), ('sim3_risk', 'pbr_ttm')}
# 없는 게 **정상이고 코드가 대비하고 있는** 필드. 근거를 같이 적는다.
KNOWN_ABSENT = {
    ('sim8_accumulation', 'unique_posters'):
        '유니버스가 외인·기관 순매수 상위라 버즈 필드가 없다. '
        '_crowd_baseline()이 버즈 기준선으로 폴백한다(설계상 의도).',
}


def fields_read(path):
    src = open(path, encoding='utf-8').read()
    return sorted(set(FIELD_RE.findall(src)) - PORTFOLIO_KEYS)


def load_sim(module_name):
    import importlib
    mod = importlib.import_module(f'src.strategy.simulators.{module_name}')
    from src.strategy.simulators.base_simulator import BaseSimulator
    for obj in vars(mod).values():
        if isinstance(obj, type) and issubclass(obj, BaseSimulator) and obj is not BaseSimulator:
            return obj
    return None


def coverage(rows, keys):
    """키별 (값 있음, 0/빈값, 키 없음)."""
    out = {}
    for k in keys:
        have = zero = missing = 0
        for r in rows:
            if k not in r:
                missing += 1
            elif r[k] in (None, '', 0, 0.0, [], '0'):
                zero += 1
            else:
                have += 1
        out[k] = (have, zero, missing)
    return out


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    from src.pipeline.context import PipelineContext
    from src.pipeline.workers.trade_engine import TradeEngineWorker

    ctx = PipelineContext.from_env()
    worker = TradeEngineWorker(ctx, None)

    problems = []
    for path in sorted(glob.glob('src/strategy/simulators/sim*.py')):
        name = os.path.basename(path)[:-3]
        if name in SKIP_SIMS or (only and name != only):
            continue
        keys = fields_read(path)
        if not keys:
            continue
        cls = load_sim(name)
        if cls is None:
            continue
        sim = cls()
        try:
            univ = sim.get_universe()
        except Exception as e:
            print(f'{name:26} 유니버스 조회 실패: {type(e).__name__} {e}')
            continue
        if not univ:
            print(f'{name:26} 유니버스 없음(자체 후보를 쓰는 심일 수 있다)')
            continue
        try:
            rows = worker._enrich_universe([dict(x) for x in univ])
        except Exception as e:
            print(f'{name:26} 보강 실패: {type(e).__name__} {e}')
            rows = univ

        n = len(rows)
        cov = coverage(rows, keys)
        print(f'\n=== {name}  (후보 {n}종목) ===')
        for k, (have, zero, missing) in sorted(cov.items()):
            pct = 100 * have / n if n else 0
            flag = ''
            if (name, k) in SELF_FILLED:
                print(f'  {k:22} (심이 직접 조회 — 보강 대상 아님)')
                continue
            if (name, k) in KNOWN_ABSENT:
                print(f'  {k:22} (결손이 정상) {KNOWN_ABSENT[(name, k)]}')
                continue
            if missing == n:
                flag = '  ← 키가 아예 없다'
                problems.append((name, k, '키 없음'))
            elif have == 0:
                flag = '  ← 전량 0/빈값 (죽은 필드일 수 있다)'
                problems.append((name, k, '전량 0'))
            elif pct < 60:
                flag = '  ← 절반 이상 결손'
                problems.append((name, k, f'{pct:.0f}%만 채워짐'))
            print(f'  {k:22} 값있음 {have:3} / 0·빈값 {zero:3} / 키없음 {missing:3}  ({pct:3.0f}%){flag}')

    if problems:
        print('\n\n===== 확인 필요 =====')
        for s, k, why in problems:
            print(f'  {s:26} {k:22} {why}')
    else:
        print('\n전 심 필드 정상.')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
