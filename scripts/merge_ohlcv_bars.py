"""EOD가 하루 두 번 쓰는 일봉을, 필드마다 확정되는 쪽으로 합친다.

EOD는 매 거래일 두 번 돈다(16:00 태스커 dispatch + 21~23시 지연 cron). 예전엔
늦은 쪽이 파일을 통째로 덮었다. 2026-09-16에 같은 날을 여러 스냅샷에 걸쳐
추적해 보니 **가격과 거래량이 정반대로 움직였다.**

  가격 — 삼성전자 20260914: 이른 249000 → 늦은 248500 → **다음 날 확정 249000**.
         SK하이닉스: 1698000 → 1683000 → **1697000**. 20260911 행은 여섯 스냅샷
         전부 동일하다(이틀 지나면 고정). 즉 **늦은 런의 종가가 이상치이고 다음
         날 정정된다.** 확정값은 이른 값에 훨씬 가깝다(거리 중앙 0.44% vs 1.02%).
  거래량 — 20260914 거래량은 늦은 커밋 값에서 그 뒤 **0/99 종목**만 바뀌었다.
         장 마감 뒤에도 체결이 실제로 쌓이므로 **늦은 값이 확정**이다.

그래서 오늘 행은 이렇게 합친다:
  - open·high·low·close: **먼저 쓴 값**(선착순)
  - volume·amount: **큰 값**(늦게 쌓인 쪽이 확정, 다만 뒤로 가지는 않는다)
과거 행은 통째로 최신을 받는다 — 이틀 지나면 값이 고정되고, 그 전에는 KIS가
정정한 값이 더 정확하다.

⚠ 왜 늦은 종가가 이상치인지는 **미확정**이다. 수집 시각이 16:01~16:02 KST(시간외
단일가 16~18시·NXT 애프터마켓 15:40~20:00 한복판)라는 정황은 있지만, 어느 스냅샷이
KRX 공식 정규장 종가와 일치하는지는 외부 기준으로 대조하지 않았다. 여기서 쓰는
근거는 "며칠 뒤 KIS가 무엇으로 확정하는가" 하나다.

배포 스텝은 PYTHONPATH를 안 주므로 sys.path를 직접 세운다(scripts/의 다른 도구와 같은 방식).
KST는 src.core.clock 하나만 정의한다 — 13곳으로 갈라졌던 것이 aware/naive 혼용을 만들었다.
"""
import argparse
import codecs
import csv
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from src.core import clock


def kst_today(now: dt.datetime = None) -> str:
    """YYYYMMDD(KST). 러너는 UTC라 여기서 고정하지 않으면 자정 근처에 하루가 밀린다."""
    return clock.date_compact(clock.to_kst(now) if now is not None else None)


def _key(row):
    # 첫 컬럼명이 BOM을 달고 오는 파일이 있다(utf-8-sig로 읽어도 writer가 다시 붙인다).
    date = row.get('date') or row.get('﻿date') or ''
    return date, row.get('code', '')


# 거래량 계열만 규칙이 반대다. 2026-09-16에 같은 날을 여러 스냅샷으로 추적한 결과:
#   가격 — 삼성전자 20260914 이른 249000 → 늦은 248500 → **다음 날 확정 249000**.
#          SK하이닉스 1698000 → 1683000 → 1697000. 늦은 런의 종가가 이상치이고
#          다음 날 정정된다. 확정값은 이른 값에 훨씬 가깝다(거리 중앙 0.44% vs 1.02%).
#   거래량 — 20260914 거래량은 늦은 커밋 값에서 그 뒤 **0/99 종목**만 바뀌었다.
#          장 마감 뒤에도 체결이 실제로 쌓이므로 늦은 값이 확정이다.
# 그래서 선착순을 전 필드에 걸면 거래량이 3~4.5% 낮은 채로 하룻밤 남는다.
VOLUME_FIELDS = ('volume', 'amount')


def _merge_row(earlier: dict, later: dict) -> dict:
    """오늘 행 하나를 **필드 단위**로 합친다 — 가격은 먼저 쓴 값, 거래량은 큰 값.

    행을 통째로 바꾸지 않는 이유: 종가 CSV(kospi_top100_close.csv)는 열이 종목이라
    런마다 열 집합이 달라질 수 있다(2026-09-11 이른 런은 93종목, 늦은 런은 100종목).
    통째로 바꾸면 헤더에 없는 열이 섞이거나 있어야 할 열이 빈다.

    빈 값은 선착순에서 빼놓는다 — 결손은 측정이 아니다. 먼저 쓴 쪽이 비어 있고
    나중 쪽에 실제 값이 있으면 그 값을 쓴다.
    """
    out = dict(later)
    for k, v in earlier.items():
        if k not in out or v in (None, ''):
            continue
        if k in VOLUME_FIELDS:
            # 거래량은 늦은 값이 확정이다. 다만 뒤로 가지는 않는다 —
            # 있을 수 없는 일이지만, 그때 작은 쪽을 쓰면 조용히 틀린 값이 남는다.
            try:
                if float(v) > float(out[k]):
                    out[k] = v
            except (TypeError, ValueError):
                pass   # 숫자가 아니면 늦은 값을 그대로 둔다
            continue
        out[k] = v
    return out


def merge_rows(existing: list[dict], fresh: list[dict], today: str) -> list[dict]:
    """오늘 행은 existing 우선(필드 단위), 나머지는 fresh 우선. 순서는 fresh를 따른다."""
    kept = {_key(r): r for r in existing if _key(r)[0] == today}
    if not kept:
        return list(fresh)

    out, seen = [], set()
    for r in fresh:
        k = _key(r)
        if k[0] == today and k in kept:
            out.append(_merge_row(kept[k], r))
        else:
            out.append(r)
        seen.add(k)
    # fresh가 놓친 오늘 행(유니버스가 줄어든 날)은 버리지 않고 뒤에 붙인다.
    out.extend(r for k, r in kept.items() if k not in seen)
    return out


def _read(path):
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def _has_bom(path) -> bool:
    """읽는 쪽은 둘 다 utf-8-sig라 BOM 유무를 안 타지만, 벗기면 db-data에
    파일 전체가 바뀐 diff가 한 번 뜬다. 쓰던 대로 유지한다."""
    try:
        with open(path, 'rb') as f:
            return f.read(3) == codecs.BOM_UTF8
    except OSError:
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('fresh', help='이번 런이 모은 CSV (여기에 덮어쓴다)')
    ap.add_argument('existing', help='db-data에 이미 있는 CSV (없어도 된다)')
    ap.add_argument('--today', default=None, help='YYYYMMDD. 생략하면 KST 오늘')
    a = ap.parse_args(argv)

    today = a.today or kst_today()
    fresh = _read(a.fresh)
    if not fresh:
        # 빈 걸 병합해서 기존 파일을 망가뜨리지 않는다. 0행 판정은 호출부의 몫이다.
        print(f'[병합] {a.fresh}에 데이터 행이 없다 — 병합하지 않는다')
        return 0

    existing = _read(a.existing)
    merged = merge_rows(existing, fresh, today)

    kept = sum(1 for r in existing if _key(r)[0] == today)
    if kept:
        print(f'[병합] 오늘({today}) 봉 {kept}행 — 가격은 먼저 쓴 값을 보존하고(선착순) '
              f'거래량·거래대금은 큰 값을 쓴다. 늦은 런의 종가는 다음 날 정정되는 이상치다')
    else:
        print(f'[병합] 오늘({today}) 봉이 기존 파일에 없다 — 이번 런이 첫 기록이다')

    enc = 'utf-8-sig' if _has_bom(a.fresh) else 'utf-8'
    with open(a.fresh, 'w', encoding=enc, newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(fresh[0].keys()))
        w.writeheader()
        w.writerows(merged)
    print(f'[병합] {len(merged)}행 기록 ({a.fresh})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
