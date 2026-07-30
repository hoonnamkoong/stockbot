# -*- coding: utf-8 -*-
"""매매 기록 CSV의 ROI 두 열 — 기록기와 대시보드가 공유하는 경계.

대시보드 쪽 짝은 src/lib/trade-history-csv.test.ts 다. 열 이름·순서가 어긋나면
화면에서 사유와 ROI가 서로 밀린다.
"""
import csv
import io
import os

from src.strategy.simulators.base_simulator import (
    CSV_HEADER, BaseSimulator, ensure_csv_header,
)

OLD_HEADER = "timestamp,symbol,action,price,quantity,total_amount,reason"
# 사유에 콤마가 들어간 실제 기록. 열이 밀리는지 보려면 이 형태여야 한다.
OLD_ROW = ('2026-07-24 09:14:58,SK이터닉스(475150),SELL,77300,5,386500,'
           '"[레인지] 트레일링 청산 (고점대비 -2%, +38.3%)"')


def _read(path):
    with io.open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.reader(f))


def _sim(tmp_path, cash=3_000_000):
    sim = BaseSimulator.__new__(BaseSimulator)
    sim.name = 'T'
    sim.state_file = str(tmp_path / 'state.json')
    sim.csv_file = str(tmp_path / 'hist.csv')
    sim.state = {
        'initial_cash': cash, 'cash': cash, 'invested': 0, 'portfolio': {},
        'peak_nav': cash, 'total_fees': 0, 'history': [cash], 'daily_trades': [],
        'market_index_healthy': True, 'cooldown_codes': {},
    }
    return sim


# ── 헤더 ────────────────────────────────────────────────────────────

def test_새_파일은_roi_열까지_있는_헤더로_시작한다(tmp_path):
    p = str(tmp_path / 'new.csv')
    ensure_csv_header(p)
    assert _read(p)[0] == CSV_HEADER


def test_roi가_사유_뒤에_있다(tmp_path):
    # 앞에 끼우면 구 포맷 행의 사유가 roi로 읽힌다. 순서가 계약이다.
    assert CSV_HEADER[-3:] == ['reason', 'roi', 'roi_amount']


def test_대시보드_리셋이_쓰는_헤더도_같다(tmp_path):
    """리셋이 만드는 빈 CSV가 구 헤더면 그 심만 ROI를 못 기록한다.

    TS는 생성물이므로 여기서 실패하면 `python scripts/gen_sim_registry.py`를 돌린다.
    """
    ts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'src', 'lib', 'sim-registry.generated.ts')
    with io.open(ts, encoding='utf-8') as f:
        generated = f.read()
    assert f"export const TRADE_CSV_HEADER = '\\ufeff{','.join(CSV_HEADER)}\\n';" in generated


def test_구_포맷_파일은_헤더만_승급되고_데이터는_그대로다(tmp_path):
    p = str(tmp_path / 'old.csv')
    with io.open(p, 'w', encoding='utf-8-sig', newline='') as f:
        f.write(OLD_HEADER + '\n' + OLD_ROW + '\n')

    ensure_csv_header(p)
    rows = _read(p)
    assert rows[0] == CSV_HEADER
    # 기존 행은 7개 값 그대로 — 사유가 여전히 7번째다(따옴표 안 콤마도 보존).
    assert rows[1][:7] == ['2026-07-24 09:14:58', 'SK이터닉스(475150)', 'SELL',
                           '77300', '5', '386500',
                           '[레인지] 트레일링 청산 (고점대비 -2%, +38.3%)']
    assert len(rows[1]) == 7, '없는 ROI를 빈 칸으로 채우지도 않는다 — 모르는 것은 없는 것이다'


def test_헤더_승급은_두_번_해도_같다(tmp_path):
    p = str(tmp_path / 'idem.csv')
    with io.open(p, 'w', encoding='utf-8-sig', newline='') as f:
        f.write(OLD_HEADER + '\n' + OLD_ROW + '\n')
    ensure_csv_header(p)
    first = io.open(p, encoding='utf-8-sig').read()
    ensure_csv_header(p)
    assert io.open(p, encoding='utf-8-sig').read() == first


def test_승급_중_임시파일이_남지_않는다(tmp_path):
    p = str(tmp_path / 'tmp.csv')
    with io.open(p, 'w', encoding='utf-8-sig', newline='') as f:
        f.write(OLD_HEADER + '\n')
    ensure_csv_header(p)
    assert not os.path.exists(p + '.tmp')


# ── 기록 ────────────────────────────────────────────────────────────

def test_매수는_ROI_칸이_비어_있다(tmp_path):
    sim = _sim(tmp_path)
    sim.buy('005930', '삼성전자', 1000, 10, '[테스트] 매수')
    row = _read(sim.csv_file)[1]
    assert row[2] == 'BUY'
    assert row[7] == '' and row[8] == '', '살 때는 실현손익이 없는 게 정상이다'


def test_매도는_부호가_붙은_수익률과_금액을_쓴다(tmp_path):
    sim = _sim(tmp_path)
    sim.buy('005930', '삼성전자', 1000, 10, 'buy')
    sim.sell('005930', 1200, reason='[테스트] 익절')

    row = _read(sim.csv_file)[2]
    assert row[2] == 'SELL'
    # 원가 10,000 · 실수령 12,000 − 매도비용 → 대시보드가 색을 부호로 정하므로 +가 필수다
    assert row[7].startswith('+'), row[7]
    roi_pct, roi_amount = float(row[7]), int(row[8])
    assert 15.0 < roi_pct < 20.0, f'매도비용 반영 후 +20%보다 조금 작아야 한다: {roi_pct}'
    assert 1500 < roi_amount < 2000, roi_amount
    # 두 값이 같은 사실을 말해야 한다
    assert abs(roi_amount / 10_000 * 100 - roi_pct) < 0.01


def test_손실_매도는_음수로_기록된다(tmp_path):
    sim = _sim(tmp_path)
    sim.buy('005930', '삼성전자', 1000, 10, 'buy')
    sim.sell('005930', 900, reason='[테스트] 손절')
    row = _read(sim.csv_file)[2]
    assert float(row[7]) < 0 and int(row[8]) < 0


def test_사유의_콤마가_ROI_열을_밀지_않는다(tmp_path):
    sim = _sim(tmp_path)
    sim.buy('005930', '삼성전자', 1000, 10, 'buy')
    sim.sell('005930', 1200, reason='[레인지] 청산 (고점대비 -2%, +38.3%)')
    row = _read(sim.csv_file)[2]
    assert row[6] == '[레인지] 청산 (고점대비 -2%, +38.3%)'
    assert row[7].startswith('+') and row[8].lstrip('-').isdigit()


def test_평단을_모르면_ROI를_만들지_않는다(tmp_path):
    # 상태 손상으로 avg_price가 0인 포지션. 0%로 그리면 손익 0원처럼 보인다.
    sim = _sim(tmp_path)
    sim.state['portfolio']['005930'] = {
        'name': '삼성전자', 'quantity': 10, 'avg_price': 0, 'price': 0, 'peak_price': 0,
    }
    sim.sell('005930', 1200, reason='[테스트] 원가 불명')
    row = _read(sim.csv_file)[1]
    assert row[7] == '' and row[8] == ''


def test_부분_매도는_매도한_수량만큼만_계산한다(tmp_path):
    sim = _sim(tmp_path)
    sim.buy('005930', '삼성전자', 1000, 10, 'buy')
    sim.sell('005930', 1200, quantity=4, reason='[테스트] 분할 익절')
    row = _read(sim.csv_file)[2]
    assert row[4] == '4'
    # 원가는 4주분(4,000원)이다 — 10주분으로 나누면 수익률이 40%로 줄어든다
    assert 15.0 < float(row[7]) < 20.0, row[7]
    assert 600 < int(row[8]) < 800, row[8]
