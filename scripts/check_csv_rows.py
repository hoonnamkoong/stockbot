# -*- coding: utf-8 -*-
"""CSV에 데이터 행이 최소 N개 있는지 확인한다. 모자라면 비0으로 끝난다.

    python scripts/check_csv_rows.py output/kospi_top100_close.csv --min 1

왜 필요한가 (2026-09-10): EOD 배포 가드가 "파일이 있는가"만 봐서, 네이버 이관으로
0행이 된 종가 CSV(헤더만, 2,201B)가 db-data를 덮었다. 런은 초록이었고 다음 날 하루
리베로 trend가 통째로 비었다. **빈 산출물을 덮어쓰느니 직전 파일을 지키는 게 낫다.**
"""
import argparse
import csv
import sys


def data_rows(path: str) -> int:
    with open(path, encoding='utf-8-sig', newline='') as f:
        r = csv.reader(f)
        next(r, None)                       # 헤더
        return sum(1 for row in r if any((c or '').strip() for c in row))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('--min', type=int, default=1, help='최소 데이터 행 수')
    a = ap.parse_args()
    try:
        n = data_rows(a.path)
    except OSError as e:
        print(f'[행수] 읽을 수 없다: {e}')
        return 1
    print(f'[행수] {a.path}: {n}행 (하한 {a.min})')
    return 0 if n >= a.min else 1


if __name__ == '__main__':
    sys.exit(main())
