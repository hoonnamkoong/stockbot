"""오늘 일봉은 선착순, 과거 일봉은 최신 — 두 EOD 런이 같은 날을 두고 다투지 않게 한다.

EOD는 매 거래일 두 번 돈다(16:00 태스커 dispatch + 21~23시 지연 cron). 지금은
늦은 쪽이 파일을 통째로 덮는데, 늦은 바는 이른 바의 **확장**이다 — 20260914
100종목 전수에서 거래량이 줄어든 종목 0, 고저 범위가 좁아진 종목 0, 이른 종가가
늦은 바 [저,고] 안에 있는 종목 100/100. 이른 런의 수집 시각은 16:01~16:02 KST로
시간외단일가(16~18시)·NXT 애프터마켓(15:40~20:00) 한복판이라, 그 뒤 체결이 계속
붙는다. 20260914에는 95/100 종목의 종가가 바뀌었다(82개 하락, 중앙 -0.71%).

정본은 **정규장 종가**로 정했다(2026-09-15). 그러면 늦게 붙은 시간외·NXT 체결은
일봉에 들어오면 안 되고, 지금 구조에서 정규장 종가에 더 가까운 쪽은 언제나 먼저
쓴 바다. 그래서 오늘 행만 선착순으로 지키고, 과거 행은 최신을 받는다.

⚠ 이건 오염을 **줄이는** 것이지 없애는 게 아니다. 이른 바에도 NXT 애프터마켓
21분이 들어 있다. 깨끗한 정규장 봉은 수집 자체가 15:30~15:40 창에서 일어나거나
KIS 시장구분이 KRX 정규장으로 한정돼야 얻어진다 — 둘 다 이 병합 밖의 일이다.

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


def _merge_row(earlier: dict, later: dict) -> dict:
    """오늘 행 하나를 **필드 단위**로 합친다 — 먼저 쓴 값이 이긴다.

    행을 통째로 바꾸지 않는 이유: 종가 CSV(kospi_top100_close.csv)는 열이 종목이라
    런마다 열 집합이 달라질 수 있다(2026-09-11 이른 런은 93종목, 늦은 런은 100종목).
    통째로 바꾸면 헤더에 없는 열이 섞이거나 있어야 할 열이 빈다.

    빈 값은 선착순에서 빼놓는다 — 결손은 측정이 아니다. 먼저 쓴 쪽이 비어 있고
    나중 쪽에 실제 값이 있으면 그 값을 쓴다.
    """
    out = dict(later)
    for k, v in earlier.items():
        if k in out and v not in (None, ''):
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
        print(f'[병합] 오늘({today}) 봉 {kept}행은 먼저 쓴 값을 보존한다(선착순) — '
              f'시간외·NXT 체결이 정규장 종가를 덮지 않게 한다')
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
