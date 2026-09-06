# -*- coding: utf-8 -*-
"""폰이 상주 프로세스를 며칠씩 죽이지 않는지 실측한다 (이관 2단계 게이트).

    python3 scripts/phone_soak.py --run              # 폰에서 계속 돌린다
    python3 scripts/phone_soak.py --report           # 아무 데서나 판정을 본다

**이 게이트를 통과 못 하면 폰 워커로 가지 않는다.** 월 ₩400~2,000을 아끼려고
돈 경로를 불안정한 런타임에 올릴 이유가 없다 — 그 판단을 미리 정해 두는 것이
2단계의 요점이다.

재는 것은 "프로세스가 살아 있나"가 아니라 **"틱이 연속이었나"**다.
Termux:Boot이 다시 띄우면 프로세스는 살아 있지만 그 사이 매매는 없었다.
그 공백이 정확히 상주 구조의 위험이므로, 로그의 구멍으로 잰다.

표준 라이브러리만 쓴다 — 폰에 pip 의존성을 깔기 전에 이 게이트가 먼저다.
"""
import argparse
import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src import soak  # noqa: E402

_KST = dt.timezone(dt.timedelta(hours=9))

DEFAULT_LOG = os.path.expanduser('~/stockbot_soak.log')
DEFAULT_INTERVAL_SEC = 60
DEFAULT_REQUIRED_HOURS = 72


def run(path: str, interval: int) -> None:
    """틱을 append한다. 중단되면 그 자리가 로그의 구멍으로 남는다.

    매 줄 flush한다 — 버퍼에 남은 채 프로세스가 죽으면 마지막 몇 분이
    사라져서, 죽은 시각이 실제보다 이르게 보인다.
    """
    print(f'[Soak] 시작 interval={interval}s log={path}', flush=True)
    print('[Soak] 중단하지 말 것. 화면을 꺼도 되지만 충전은 계속 유지한다.',
          flush=True)
    while True:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(dt.datetime.now(_KST).isoformat() + '\n')
            f.flush()
            os.fsync(f.fileno())
        time.sleep(interval)


def read_ticks(path: str) -> list[dt.datetime]:
    """읽을 수 없는 줄은 버린다 — 킬 당시 잘린 줄이 있을 수 있다."""
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                out.append(dt.datetime.fromisoformat(line.strip()))
            except ValueError:
                continue
    return out


def report(path: str, interval: int, required_hours: float) -> int:
    ticks = read_ticks(path)
    v = soak.verdict(ticks, expected_sec=interval, required_hours=required_hours)

    print(f'로그      : {path}')
    print(f'틱        : {v["ticks"]}개')
    if v['first']:
        print(f'구간      : {v["first"]:%Y-%m-%d %H:%M} ~ {v["last"]:%Y-%m-%d %H:%M} KST')
    print(f'커버      : {v["covered_hours"]}시간 (요구 {required_hours}시간)')
    print(f'구멍      : {v["gaps"]}개  가장 긴 것 {int(v["longest_gap_sec"])}초')
    for g in v['detail']:
        print(f'   - {g["from"]:%m-%d %H:%M} → {g["to"]:%m-%d %H:%M}  '
              f'{int(g["seconds"])}초 비었다')

    if v['passed']:
        print('\n판정: 통과 — 폰이 상주 프로세스를 끊지 않았다. 3단계로 간다.')
        return 0
    print('\n판정: 미통과 — 폰 워커로 가지 않는다. e2-micro로 전환한다.')
    if v['gaps']:
        print('       구멍이 있다: 배터리 최적화 예외·wake-lock을 다시 확인할 것.')
    elif v['covered_hours'] < required_hours:
        print('       아직 기간이 모자란다. 계속 돌릴 것.')
    return 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--run', action='store_true', help='폰에서 틱을 남긴다')
    p.add_argument('--report', action='store_true', help='판정을 본다')
    p.add_argument('--log', default=DEFAULT_LOG)
    p.add_argument('--interval', type=int, default=DEFAULT_INTERVAL_SEC)
    p.add_argument('--hours', type=float, default=DEFAULT_REQUIRED_HOURS)
    a = p.parse_args(argv)

    if a.run:
        run(a.log, a.interval)
        return 0
    if a.report:
        return report(a.log, a.interval, a.hours)
    p.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
