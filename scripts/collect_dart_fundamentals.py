"""OpenDART 재무 수집기 — 심3 TTM 밸류·심11 성장률의 분기 갱신.

KIS 종목분석 7종이 2026-11-11 16:00에 막혀(FHKST66430300 → 404) 심3은 판정 전부
`no_ttm_val`, 심11은 100% `no_eps`가 됐다. 분기 보고서는 **분기당 한 번만** 바뀌니
매 사이클 조회할 이유가 없다 — 여기서 한 번 모아 `data/dart_fundamentals.json`에
캐시하고, 심은 그 파일만 읽는다(사이클당 API 호출 0).

쓰는 법:

    DART_API_KEY=... python scripts/collect_dart_fundamentals.py

이미 목표 보고서로 채워진 종목은 건너뛴다 — 그래서 **다시 돌려도 거의 0회**이고,
예산이 소진돼 중간에 멈췄어도 다음 실행이 이어받는다. 종목당 호출은 최대 4회다
(해당 분기 CFS/OFS + 직전 사업보고서 CFS/OFS). 인증키 한도가 일일 20,000회라
한 번에 `MAX_REQUESTS`까지만 쓰고 남은 수를 보고한다.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.core import clock  # noqa: E402
from src.data import dart_fundamentals as df  # noqa: E402

# 인증키 한도는 일일 20,000회다. 넘기면 020(요청 제한 초과)이 와서 그 뒤 전부가
# 조용히 빈다. 종목당 최악 4회(분기 CFS/OFS + 직전연간 CFS/OFS)이므로 상장사
# 4,020개 전부를 한 번에 돌려도 최악 16,080회로 한도 안이다 — 예산을 4,500개로
# 두어 **첫 채움이 한 런에 끝나게** 한다(분기마다 1회, 그 뒤로는 건너뛰기라 0회).
MAX_REQUESTS = 18_000
REQUESTS_PER_CODE = 4
# 분당 한도는 공개 가이드에 없다. 보수적으로 둔다.
SLEEP_SEC = 0.12
SAVE_EVERY = 50


def main() -> int:
    ap = argparse.ArgumentParser(description='OpenDART 재무 수집 (분기 1회)')
    ap.add_argument('--limit', type=int, default=0, help='이만큼만 처리(0=전부)')
    ap.add_argument('--refresh-codes', action='store_true',
                    help='법인코드 매핑을 다시 받는다(신규 상장 반영)')
    ap.add_argument('--data-dir', default='data')
    args = ap.parse_args()

    key = df.api_key()
    if not key:
        print('[dart] DART_API_KEY가 없다 — 수집하지 않는다. '
              '값은 GitHub Secrets/Vercel env에만 둔다(public 레포).')
        return 1

    codes = df.load_corp_codes(args.data_dir)
    if args.refresh_codes or not codes:
        print('[dart] 법인코드 매핑 조회 중...')
        codes = df.build_corp_code_map(key)
        if not codes:
            print('[dart] 법인코드 매핑 실패 — 중단한다(빈 매핑으로 덮어쓰지 않는다)')
            return 2
        df.save_corp_codes(codes, args.data_dir)
    print(f'[dart] 상장사 {len(codes)}개')

    # KST를 직접 만들지 않는다 — 단일 시계(src.core.clock)만 쓴다.
    today = clock.now().date()
    year, quarter = df.latest_report(today)
    target = f'{year}-{df.reprt_code(quarter)}'
    print(f'[dart] 목표 보고서 {target} ({year}년 {quarter}분기, 기준일 {today})')

    cache = df.load_cache(args.data_dir)
    todo = [(c, cc) for c, cc in sorted(codes.items())
            if (cache.get(c) or {}).get('report') != target]
    if args.limit:
        todo = todo[:args.limit]
    budget = MAX_REQUESTS // REQUESTS_PER_CODE
    print(f'[dart] 갱신 대상 {len(todo)}개 (이번 실행 예산 {budget}개)')

    ok = empty = 0
    started = time.time()
    for i, (code, corp_code) in enumerate(todo[:budget], 1):
        try:
            out = df.fetch(corp_code, year, quarter, key=key)
        except Exception as e:
            print(f'[dart] {code} 조회 실패: {e}')
            out = {}
        if out:
            cache[code] = out
            ok += 1
        else:
            # 캐시를 지우지 않는다 — 지난 분기 값이 지어낸 값보다 낫고,
            # `report`가 낡은 채로 남아 다음 실행이 다시 시도한다.
            empty += 1
        if i % SAVE_EVERY == 0:
            df.save_cache(cache, args.data_dir)
            print(f'[dart] {i}/{min(len(todo), budget)} '
                  f'(수집 {ok} · 자료없음 {empty} · {time.time() - started:.0f}초)')
        time.sleep(SLEEP_SEC)

    df.save_cache(cache, args.data_dir)
    left = max(0, len(todo) - budget)
    print(f'[dart] 완료 — 수집 {ok} · 자료없음 {empty} · 캐시 {len(cache)}종목 '
          f'· {time.time() - started:.0f}초')
    if left:
        print(f'[dart] 예산 소진 — 남은 {left}개는 다음 실행이 이어받는다')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
