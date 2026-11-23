# -*- coding: utf-8 -*-
"""국면 판정의 채점표 — "이 국면이 무엇을 맞히는가"를 숫자로 남긴다.

2026-11-23에 사용자가 "시장 판단 정확도는 확인했어?"라고 물었고 답은 '아니오'였다.
손으로 79일을 재생해서야 "단계가 이후 수익률을 가르지 못한다"를 알았다. 그걸
재는 루틴이 **없었기 때문**이다. `calibration_log`는 breadth만 쟀고 그 값은 이제
국면 결정에 쓰이지 않으며, `regime_observations_*.csv`는 옛 3단계 필드만 적는다.

루틴이 없으면 다섯 달 뒤에 같은 질문이 또 손계산으로 돌아온다.

**왜 그날의 일간수익률(ret1)을 같이 적나**: 종가 CSV(`kospi_top100_close.csv`)는
100행 롤링이라 지난 날의 수익률을 나중에 되계산할 수 없다. 하루치 등가중
수익률 한 숫자만 있으면 임의 구간의 누적수익률도 실현변동성도 전부 복원된다.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy.regime_scorecard import HEADER, append_row, build_row


def _base(date='2026-11-20', level=-1, **m):
    metrics = {'D': -0.853, 'ab20': 23.0, 'ret10': -0.0375,
               'vol10': 2.273, 'ret1': -0.0042}
    metrics.update(m)
    return {'date': date, 'level': level, 'confirmed_since': '2026-11-05',
            'metrics': metrics}


# ── 한 줄 만들기 ───────────────────────────────────────────────────

def test_확정된_하루를_한_줄로_적는다():
    row = build_row(_base(), 'BEAR')
    assert row == '2026-11-20,-1,BEAR,-0.853,23.0,-0.0375,2.273,-0.0042,2026-11-05'


def test_헤더와_열_수가_맞는다():
    """열이 어긋나면 채점기가 조용히 엉뚱한 칸을 읽는다."""
    row = build_row(_base(), 'BEAR')
    assert len(row.split(',')) == len(HEADER.split(','))


def test_판정_불가일은_단계만_적고_지표는_비운다():
    """0으로 채우면 '변동성 0인 날'이 되어 채점이 거짓말을 한다."""
    b = _base()
    b['metrics'] = None
    row = build_row(b, 'BEAR')
    assert row.startswith('2026-11-20,-1,BEAR,,,,,')
    assert ',0,' not in row and ',0.0,' not in row


def test_ret1이_없으면_그_칸만_비운다():
    """옛 base와 테스트 대역에는 ret1이 없다. 나머지는 살린다."""
    b = _base()
    del b['metrics']['ret1']
    row = build_row(b, 'BEAR')
    cells = row.split(',')
    assert cells[7] == '', 'ret1 칸이 비어야 한다'
    assert cells[6] == '2.273', 'vol10은 살아 있어야 한다'


def test_날짜가_없으면_줄을_만들지_않는다():
    assert build_row({'level': -1}, 'BEAR') is None
    assert build_row(None, 'BEAR') is None
    assert build_row({}, None) is None


def test_라벨을_모르면_비워두고_단계는_적는다():
    """라벨은 vol10을 모르면 None이 된다. 그래도 단계는 남길 가치가 있다."""
    row = build_row(_base(), None)
    assert row.split(',')[2] == ''
    assert row.split(',')[1] == '-1'


# ── 파일에 쌓기 ────────────────────────────────────────────────────

def test_새_파일이면_헤더부터_쓴다(tmp_path):
    p = str(tmp_path / 'sc.csv')
    assert append_row(p, build_row(_base(), 'BEAR')) is True
    lines = open(p, encoding='utf-8').read().splitlines()
    assert lines[0] == HEADER
    assert lines[1].startswith('2026-11-20,')


def test_같은_날짜는_두_번_쌓이지_않는다(tmp_path):
    """루프는 2분마다 돈다. 하루 한 줄이 아니면 채점이 그날에 가중된다."""
    p = str(tmp_path / 'sc.csv')
    append_row(p, build_row(_base(), 'BEAR'))
    assert append_row(p, build_row(_base(), 'BEAR')) is False
    assert append_row(p, build_row(_base(level=-2), 'STRONG_BEAR')) is False
    assert len(open(p, encoding='utf-8').read().splitlines()) == 2


def test_다음_날은_쌓인다(tmp_path):
    p = str(tmp_path / 'sc.csv')
    append_row(p, build_row(_base('2026-11-19'), 'BEAR'))
    append_row(p, build_row(_base('2026-11-20'), 'BEAR'))
    assert len(open(p, encoding='utf-8').read().splitlines()) == 3


def test_빈_줄은_쓰지_않는다(tmp_path):
    p = str(tmp_path / 'sc.csv')
    assert append_row(p, None) is False
    assert not os.path.exists(p)


def test_파일이_깨져_있어도_죽지_않는다(tmp_path):
    """국면 갱신 경로에서 도는 코드다. 여기서 예외가 나면 국면이 멈춘다."""
    p = str(tmp_path / 'sc.csv')
    with open(p, 'w', encoding='utf-8') as f:
        f.write('\x00garbage\n')
    assert append_row(p, build_row(_base(), 'BEAR')) in (True, False)


def test_읽기_전용_경로여도_국면을_멈추지_않는다(tmp_path):
    """없는 디렉터리를 줘도 예외를 올리지 않는다."""
    p = str(tmp_path / 'no' / 'such' / 'dir' / 'sc.csv')
    assert append_row(p, build_row(_base(), 'BEAR')) is False


# ── 채점기 ─────────────────────────────────────────────────────────
# 어제(2026-11-23) 손으로 낸 79일 재생 결과를 이 스크립트가 재현해야 한다.
# 재현 못 하면 자동화한 의미가 없다.

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import score_regime as sr  # noqa: E402


def test_판정일_자신의_수익률은_넣지_않는다():
    """국면은 그날 종가로 확정된다. 그날 수익률을 넣으면 룩어헤드다."""
    rets = [0.10, 0.01, 0.02, 0.03]
    assert sr.forward(rets, 0, 1) == pytest.approx(1.0)
    assert sr.forward(rets, 0, 2) == pytest.approx((1.01 * 1.02 - 1) * 100)


def test_구간이_모자라면_None():
    """표본이 없는 칸을 0으로 채우면 채점이 거짓말을 한다."""
    assert sr.forward([0.01, 0.02], 1, 1) is None
    assert sr.realized_vol([0.01, 0.02], 0, 10) is None


def test_실현변동성은_다음날부터_잰다():
    rets = [0.0, 0.01, -0.01, 0.01, -0.01]
    v = sr.realized_vol(rets, 0, 4)
    assert v is not None and v > 0


def test_ret1이_없는_줄은_버린다(tmp_path):
    """지어내지 않는다 — 판정 불가일을 0% 수익률로 세면 안 된다."""
    p = tmp_path / 'sc.csv'
    p.write_text(HEADER + '\n'
                 '2026-11-19,-1,BEAR,-0.5,30.0,-0.01,2.0,-0.004,2026-11-05\n'
                 '2026-11-20,-1,BEAR,,,,,,2026-11-05\n', encoding='utf-8')
    rows = sr.load(str(p))
    assert [r[0] for r in rows] == ['2026-11-19']
