# -*- coding: utf-8 -*-
"""프리마켓 유니버스는 **전일** 거래대금 급증배수로 정한다.

`top_by_surge`가 분자로 쓰는 `amts[-1]`은 CSV의 마지막 행인데, 그 파일은
`fetch_kis_history.py daily --to $(date +%Y%m%d)`로 만들어져 **오늘 행을
포함한다.** 그래서 두 가지가 동시에 깨져 있었다(2026-09-04 실측):

1. **개장 전(07:20·07:46 KST)**: 오늘 행의 amount가 0이라 모든 종목이
   `amts[-1] <= 0`에 걸려 걸러진다 → `유니버스가 비었다` → exit 1.
   premarket_data.yml이 그 시각대에 매일 두 번 실패했다.

2. **개장 직후(09:00 KST)**: 오늘 행이 0은 아니지만 **진행 중인 세션**이다.
   45초치 거래대금을 20일 평균으로 나눈 값으로 순위를 매기게 된다. 실패는
   안 하지만 그날 쓰는 유니버스가 통째로 다른 종목이 된다 — 09-04 배포분
   실측에서 상위 5 중 겹치는 건 1종목뿐이었다:

       오늘 포함: 로보티즈, 우리기술투자, 가온전선, NHN KCP, 피노
       전일 기준: 포스코DX, 포스코인터내셔널, 우리금융지주, 한화생명, 피노

   스텝 이름도 함수 docstring도 "전일 ... 장 마감 후에 확정되는 값"이라고
   적혀 있고, 92% 커버리지를 잰 2026-08-16 리콜 실측도 전일 급증배수였다.
   즉 2번은 실패보다 조용해서 더 오래 갔다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.collect_kis_realtime import top_by_surge

TODAY = '20260904'
PREV = '20260903'


def _write(path, today_amount: str):
    """21거래일 + 오늘. 종목마다 전일 거래대금만 다르게 둬 순위가 정해진다."""
    lines = ['date,code,open,high,low,close,volume,amount,name']
    for i, code in enumerate(['000001', '000002', '000003']):
        for d in range(21):
            lines.append(f'2026080{0}{d:02d},{code},1,1,1,1,10,1000,종목{i}')
        # 전일 거래대금: 종목0 < 종목1 < 종목2 (평균 1000 대비 배수)
        lines.append(f'{PREV},{code},1,1,1,1,10,{1000 * (i + 2)},종목{i}')
        lines.append(f'{TODAY},{code},1,1,1,1,10,{today_amount},종목{i}')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return str(path)


def test_개장_전에도_유니버스가_나온다(tmp_path):
    """오늘 행의 amount가 0인 건 '거래가 없다'가 아니라 '아직 안 열렸다'다."""
    p = _write(tmp_path / 'daily.csv', today_amount='0')
    assert top_by_surge(p, 30, lookback=20, today=TODAY), (
        '개장 전에 유니버스가 비면 premarket_data.yml이 exit 1로 죽는다')


def test_진행중인_세션은_분자가_아니다(tmp_path):
    """개장 직후 45초치 거래대금이 순위를 뒤집으면 안 된다."""
    # 종목0의 오늘 거래대금만 폭발시킨다. 전일 기준이면 순위가 안 바뀐다.
    p = tmp_path / 'daily.csv'
    _write(p, today_amount='0')
    text = p.read_text(encoding='utf-8').replace(
        f'{TODAY},000001,1,1,1,1,10,0,종목0',
        f'{TODAY},000001,1,1,1,1,10,999999,종목0')
    p.write_text(text, encoding='utf-8')

    ranked = [c for c, _ in top_by_surge(str(p), 30, lookback=20, today=TODAY)]
    assert ranked[0] == '000003', (
        f'전일 거래대금이 가장 큰 종목이 1위여야 한다 — 실제 {ranked}. '
        '오늘(진행 중) 거래대금이 분자로 들어갔다')
