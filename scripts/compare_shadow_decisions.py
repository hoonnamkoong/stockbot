# -*- coding: utf-8 -*-
"""그림자 운전(폰 워커 이관 3단계)의 판단 일치율 — "주문을 넘겨도 되나"에 답한다.

    python3 scripts/compare_shadow_decisions.py                       # KST 오늘
    python3 scripts/compare_shadow_decisions.py --date 20260916
    python3 scripts/compare_shadow_decisions.py --date 20260916 --to 20260920
    python3 scripts/compare_shadow_decisions.py --base actions-scraper  # 버즈 심 쪽

읽기 전용이다. 아무 파일도 쓰지 않고 외부 API도 부르지 않는다.

## 판정 규칙은 `src/data/decision_log.py`가 정한다

폰과 옛 경로는 서로 다른 시각에 다른 시세를 본다 — 30초만 어긋나도 체결강도·
현재가가 달라 결정이 갈린다. **문자 그대로의 "불일치 0"은 달성 불가능하다.**
그래서 `input_hash`로 가른다:

    input_hash가 같은 (cycle_id, sim, code)에서 decision이 다르면  → 진짜 불일치
    input_hash가 다르면                                          → 시세가 달랐다

두 번째 건수는 **따로** 낸다. 그게 0이 아니면(정확히는 대부분이면) 그림자 비교
자체가 성립하지 않는다 — 둘이 같은 입력을 본 순간이 없다는 뜻이다.

## 일치율 분모에서 빼는 것들

`seen`은 '판단했다'가 아니라 '평가에 도달하지 못했다'다(max_holdings 조기종료).
양쪽 다 seen인 쌍을 일치로 세면 **아무도 판단하지 않은 행으로 100%가 만들어진다.**
`build_rows`가 seen을 skip에 섞지 않는 이유가 그것이고, 여기서도 섞지 않는다.

키가 겹치는 행도 뺀다. `cycle_id`는 격자 밖 경로에서 빈칸으로 남고(추정하지
않는 것이 `sim_diag._cycle_id`의 결정), 그러면 (cycle_id, sim, code)가 사이클마다
충돌한다. 아무 행이나 골라 비교하면 일치율이 우연에 좌우되므로 모호로 빼내고
건수를 보고한다.

## 없는 건 없다고 말한다

비교할 쌍이 없으면 0도 100%도 말하지 않는다 — "비교 불가"와 그 이유를 말한다.
이 레포에서 제일 중요한 규칙이다([[no-fabricated-financial-values]]).
"""
import argparse
import csv
import datetime as dt
import glob
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core import clock  # noqa: E402
from src.data import decision_log  # noqa: E402

# 폰이 이 이름으로 기록한다(STOCKBOT_RUNNER=phone). 옛 경로는 워크플로가
# actions-trading / actions-scraper로 나눠 쓴다 — 심이 두 워크플로에 나뉘어
# 돌기 때문이다. 폰이 대체하는 것은 60초 루프(trading.yml)이므로 그쪽이 기준선.
DEFAULT_BASE = 'actions-trading'
DEFAULT_SHADOW = 'phone'

_NAME_RE = re.compile(r'^decisions_\d{8}_\w+_(.+)\.csv$')


def load_rows(date: str, data_dir: str, runner: str) -> list:
    """그날 그 러너의 결정 행 전부.

    파일명을 짚지 않고 `decision_log.files_for()`로 찾는다 — 리터럴 파일명이 든
    목록은 분할 규칙이 바뀌는 순간 조용히 죽는다(시간별 분할이 그 선례다).
    """
    rows = []
    for path in decision_log.files_for(date, data_dir, runner):
        with open(path, newline='', encoding='utf-8') as f:
            rows.extend(dict(r) for r in csv.DictReader(f))
    return rows


def runners_present(date: str, data_dir: str) -> list:
    """그날 스냅샷을 남긴 러너 이름들.

    러너 이름을 잘못 주면 0건이 돌아오고, 0건은 '불일치 0'처럼 보인다. 실제로
    있는 이름을 보여주는 것이 그 함정의 유일한 방어다.
    """
    found = set()
    for path in glob.glob(os.path.join(data_dir, f'decisions_{date}_*.csv')):
        m = _NAME_RE.match(os.path.basename(path))
        if m:
            found.add(m.group(1))
    return sorted(found)


def _index(rows):
    """(cycle_id, sim, code) → 행. 키가 겹치는 것은 빼내고 따로 돌려준다."""
    out, dup = {}, set()
    for r in rows:
        key = (r.get('cycle_id', ''), r.get('sim', ''), r.get('code', ''))
        if key in out:
            dup.add(key)
        else:
            out[key] = r
    for key in dup:
        out.pop(key, None)
    return out, dup


def compare(base_rows: list, shadow_rows: list) -> dict:
    """기준선 vs 그림자. 모듈 독스트링의 규칙을 그대로 센다."""
    base, base_dup = _index(base_rows)
    shadow, shadow_dup = _index(shadow_rows)

    rep = {
        'base_n': len(base_rows), 'shadow_n': len(shadow_rows),
        'agree': 0, 'disagree': 0, 'input_mismatch': 0, 'not_evaluated': 0,
        'ambiguous': len(base_dup | shadow_dup),
        'base_only': len(set(base) - set(shadow)),
        'shadow_only': len(set(shadow) - set(base)),
        'by_sim': {}, 'by_reason': Counter(), 'samples': [],
    }

    for key in sorted(set(base) & set(shadow)):
        b, s = base[key], shadow[key]
        if b.get('input_hash', '') != s.get('input_hash', ''):
            rep['input_mismatch'] += 1
            continue
        if b.get('decision') == 'seen' or s.get('decision') == 'seen':
            rep['not_evaluated'] += 1
            continue
        per_sim = rep['by_sim'].setdefault(key[1], {'agree': 0, 'disagree': 0})
        if b.get('decision') == s.get('decision'):
            rep['agree'] += 1
            per_sim['agree'] += 1
        else:
            rep['disagree'] += 1
            per_sim['disagree'] += 1
            label = (f"{b.get('decision')}:{b.get('reason', '')}"
                     f" → {s.get('decision')}:{s.get('reason', '')}")
            rep['by_reason'][label] += 1
            if len(rep['samples']) < 10:
                rep['samples'].append((key, label))

    rep['comparable'] = rep['agree'] + rep['disagree']
    rep['rate'] = (rep['agree'] / rep['comparable']) if rep['comparable'] else None
    return rep


def _why_uncomparable(rep, base, shadow) -> str:
    """왜 못 재는지. 이유가 없으면 사람은 0건을 '통과'로 읽는다."""
    if rep['shadow_n'] == 0:
        return f"그림자({shadow}) 스냅샷 0건 — 3단계가 시작되지 않았다"
    if rep['base_n'] == 0:
        return f"기준선({base}) 스냅샷 0건 — 러너 이름을 확인하라"
    if rep['input_mismatch'] and not rep['base_only'] and not rep['shadow_only']:
        return f"input_hash가 같은 쌍 0건 (입력 불일치 {rep['input_mismatch']}건)"
    if rep['ambiguous']:
        return f"키가 겹쳐 조인 불가 (모호 {rep['ambiguous']}건 — cycle_id 결손을 의심하라)"
    return '입력·평가 조건을 통과한 쌍 0건'


def format_report(date: str, rep: dict, base: str, shadow: str,
                  data_dir: str | None = None) -> str:
    out = []
    add = out.append
    add('=' * 60)
    add(f"{date}  기준선 {base} {rep['base_n']}건  vs  그림자 {shadow} {rep['shadow_n']}건")
    add('-' * 60)

    if rep['rate'] is None:
        add(f"판단 일치율: 비교 불가 — {_why_uncomparable(rep, base, shadow)}")
        if data_dir is not None and (rep['base_n'] == 0 or rep['shadow_n'] == 0):
            names = runners_present(date, data_dir)
            add(f"  그날 실제로 스냅샷을 남긴 러너: {', '.join(names) if names else '없음'}")
    else:
        add(f"판단 일치율: {rep['agree']}/{rep['comparable']} = {rep['rate'] * 100:.2f}%"
            f"   (불일치 {rep['disagree']}건)")

    add('-' * 60)
    add(f"입력 불일치(input_hash 다름, 판단 비교 제외): {rep['input_mismatch']}건")
    add('  둘이 다른 시세를 봤다는 뜻이다. 이게 비교 대상의 대부분이면 그림자')
    add('  비교 자체가 성립하지 않는다 — 같은 입력을 본 순간이 없다.')
    add(f"평가 미도달(seen 포함, 분모 제외): {rep['not_evaluated']}건")
    add(f"키 모호(같은 (cycle_id, sim, code) 중복): {rep['ambiguous']}건")
    add(f"한쪽에만 있는 결정: 기준선만 {rep['base_only']}건 / 그림자만 {rep['shadow_only']}건")

    if rep['disagree']:
        add('-' * 60)
        add('심별 불일치')
        for sim in sorted(rep['by_sim'], key=lambda s: -rep['by_sim'][s]['disagree']):
            c = rep['by_sim'][sim]
            if c['disagree']:
                total = c['agree'] + c['disagree']
                add(f"  {sim:<16} {c['disagree']:>5}/{total:<5} 불일치")
        add('-' * 60)
        add('사유별 불일치 (기준선 → 그림자)')
        for label, n in rep['by_reason'].most_common(15):
            add(f"  {n:>5}  {label}")
        add('-' * 60)
        add('표본 (최대 10건)')
        for (cid, sim, code), label in rep['samples']:
            add(f"  cycle={cid or '(빈칸)'} {sim} {code}  {label}")

    add('=' * 60)
    return '\n'.join(out)


def _dates(start: str, end: str | None) -> list:
    if not end or end == start:
        return [start]
    a = dt.datetime.strptime(start, '%Y%m%d').date()
    b = dt.datetime.strptime(end, '%Y%m%d').date()
    if b < a:
        a, b = b, a
    return [(a + dt.timedelta(days=i)).strftime('%Y%m%d')
            for i in range((b - a).days + 1)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--date', default=None, help='YYYYMMDD. 생략하면 KST 오늘')
    ap.add_argument('--to', default=None, help='YYYYMMDD. 주면 --date부터 이 날까지')
    ap.add_argument('--base', default=DEFAULT_BASE, help=f'기준선 러너 (기본 {DEFAULT_BASE})')
    ap.add_argument('--shadow', default=DEFAULT_SHADOW, help=f'그림자 러너 (기본 {DEFAULT_SHADOW})')
    ap.add_argument('--data-dir', default='data')
    args = ap.parse_args(argv)

    dates = _dates(args.date or clock.now().strftime('%Y%m%d'), args.to)
    reps = []
    for date in dates:
        rep = compare(load_rows(date, args.data_dir, args.base),
                      load_rows(date, args.data_dir, args.shadow))
        reps.append(rep)
        print(format_report(date, rep, args.base, args.shadow, args.data_dir))

    if len(reps) > 1:
        agree = sum(r['agree'] for r in reps)
        cmpable = sum(r['comparable'] for r in reps)
        days = sum(1 for r in reps if r['comparable'])
        print(f"[{len(dates)}일 합계] 비교 가능한 날 {days}일")
        if cmpable:
            print(f"  판단 일치율: {agree}/{cmpable} = {agree / cmpable * 100:.2f}%")
        else:
            print('  판단 일치율: 비교 불가 — 전 기간에 비교 가능한 쌍이 0건')
        print(f"  입력 불일치 {sum(r['input_mismatch'] for r in reps)}건 /"
              f" 평가 미도달 {sum(r['not_evaluated'] for r in reps)}건 /"
              f" 키 모호 {sum(r['ambiguous'] for r in reps)}건")

    # 비교 불가는 실패가 아니다(아직 안 쌓인 것이다). 다만 0으로 끝내면
    # 스크립트를 게이트로 쓰는 쪽이 통과로 읽는다 — 2로 구분한다.
    return 0 if any(r['comparable'] for r in reps) else 2


if __name__ == '__main__':
    raise SystemExit(main())
