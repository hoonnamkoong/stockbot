"""Sim9-1을 장중 루프에서 빼고 EOD 배치로 옮긴다.

심9-1은 top100 일봉으로 검증된 전략인데 장중 버즈 유니버스에서 돌고 있었다.
2026-07-29 실측: 거래대금 z>0을 통과하는 종목이 28개 중 3개뿐이고 전부
초대형주(삼성전자·SK하이닉스·삼성전자우)인데, 그 종목들은 20일 채널을 안
뚫는다(0.53~0.72). 채널 돌파는 소형주에서 나오므로 두 조건의 교집합이
구조적으로 비어 있었다.

게이트를 스케일 무관 지표로 바꾸는 안은 백테스트가 반증했다(top100 100거래일,
자기 20일평균 대비 거래량 배율 1.0/1.5/2.0 전부 게이트 없음과 동급이거나 나쁨).
절대 거래대금 z가 하던 일은 '거래량 급증 탐지'가 아니라 '유동성 큰 종목 선호'
였다. 따라서 고칠 것은 게이트가 아니라 유니버스다.

돈치안은 일봉 전략이라 장중 10분 루프가 필요 없다. ohlcv_top100.csv가 이미
매일 16:00에 생성되므로 그것으로 EOD 1회 실행한다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.run_eod_sims import candidates_from_ohlcv
from src.strategy.simulators.sim9_1_donchian import DonchianBreakoutSimulator, CHANNEL_DAYS
from src.strategy.simulators.sim1_psych import PsychDivergenceSimulator


def _csv(tmp_path, rows):
    p = tmp_path / 'ohlcv.csv'
    p.write_text('date,code,name,open,high,low,close,volume,amount\n' + '\n'.join(rows) + '\n',
                 encoding='utf-8')
    return str(p)


def _series(code, name, closes, amount=5_000_000_000):
    return [f'2026{i+301:04d},{code},{name},{c},{c},{c},{c},1000,{amount}'
            for i, c in enumerate(closes)]


# ── CSV → 후보 변환 ───────────────────────────────────────
def test_candidates_carry_latest_bar_and_channel_history(tmp_path):
    closes = list(range(1000, 1000 + CHANNEL_DAYS + 1))
    path = _csv(tmp_path, _series('005930', '삼성전자', closes))
    cands = candidates_from_ohlcv(path)
    assert len(cands) == 1
    c = cands[0]
    assert c['code'] == '005930' and c['name'] == '삼성전자'
    assert c['price'] == closes[-1]          # 최신 종가가 현재가
    assert c['amount'] == 5_000_000_000
    # 채널은 '직전' 20일이다 — 당일을 넣으면 max(채널) >= 당일종가라 돌파가
    # 정의상 불가능해진다. 백테스트도 dates[t-n:t]로 당일을 뺀다.
    assert c['range_history'] == closes[-CHANNEL_DAYS - 1:-1]
    assert closes[-1] not in c['range_history'][-1:]


def test_candidates_skip_codes_without_enough_history(tmp_path):
    """채널 산출에 20일이 필요하다 — 모자란 종목은 신호를 만들 수 없다."""
    path = _csv(tmp_path, _series('000660', 'SK하이닉스', [1000, 1010, 1020]))
    assert candidates_from_ohlcv(path) == []


def test_candidates_sorted_deterministically(tmp_path):
    closes = list(range(1000, 1000 + CHANNEL_DAYS + 1))
    rows = _series('000660', 'B', closes) + _series('005930', 'A', closes)
    assert [c['code'] for c in candidates_from_ohlcv(_csv(tmp_path, rows))] == ['000660', '005930']


def test_missing_file_returns_empty(tmp_path):
    """CSV가 없으면 빈 후보다 — 없는 데이터로 매매하지 않는다."""
    assert candidates_from_ohlcv(str(tmp_path / '없음.csv')) == []


# ── ETF 배제 ─────────────────────────────────────────────
def test_etfs_are_excluded(tmp_path):
    """지수 추종 ETF는 변동성이 낮아 2*ATR 손절선이 진입가에 바짝 붙는다.

    실측(top100 100거래일): 혼합 유니버스에서 산 ETF 12건 중 10건 손실, 그중
    9건이 ATR손절이고 보유일수는 1~8일이 대부분이었다. 추세를 타면 ETF도 벌지만
    (TIGER 미국S&P500 +11.81%, 39일) 그 전에 잡음으로 털린다. 6개뿐인 슬롯을
    낭비하며 개별주를 밀어내므로 뺀다(전체 NAV +2.37% → ETF 제외 +20.46%).
    """
    closes = list(range(1000, 1000 + CHANNEL_DAYS + 1))
    rows = (_series('069500', 'KODEX 200', closes)
            + _series('102110', 'TIGER 200', closes)
            + _series('459580', 'KODEX CD금리액티브(합성)', closes)
            + _series('005930', '삼성전자', closes))
    assert [c['code'] for c in candidates_from_ohlcv(_csv(tmp_path, rows))] == ['005930']


def test_brand_lookalikes_are_not_excluded(tmp_path):
    """이름에 브랜드 문자열이 들어간 일반 종목까지 걸러내면 안 된다.

    '미래에셋증권'은 증권사지 ETF가 아니고, 'SOLUS첨단소재'는 SOL 브랜드가
    아니다. 브랜드는 이름 맨 앞에서 공백으로 끊길 때만 ETF로 본다.
    """
    closes = list(range(1000, 1000 + CHANNEL_DAYS + 1))
    rows = (_series('006800', '미래에셋증권', closes)
            + _series('336370', 'SOLUS첨단소재', closes)
            + _series('008930', '한미사이언스', closes))
    got = [c['code'] for c in candidates_from_ohlcv(_csv(tmp_path, rows))]
    assert got == ['006800', '336370', '008930']


# ── 장중 루프에서 제외 ────────────────────────────────────
def test_donchian_is_marked_eod():
    assert DonchianBreakoutSimulator.IS_EOD is True


def test_intraday_sims_are_not_marked_eod():
    """기본값이 False라 나머지 심은 장중 루프에 그대로 남는다."""
    assert PsychDivergenceSimulator.IS_EOD is False


# ── EOD 러너가 실제로 매수를 낸다 ──────────────────────────
def test_eod_run_enters_on_channel_breakout(tmp_path):
    """20일 채널을 뚫고 거래대금 z가 양수면 산다 (top100 조건 재현)."""
    from scripts.run_eod_sims import run_donchian
    rows = []
    # 19종목은 평탄(거래대금 작음), 1종목만 돌파 + 거래대금 큼
    for i in range(19):
        rows += _series(f'{i:06d}', f'평탄{i}', [1000] * (CHANNEL_DAYS + 1), amount=1_500_000_000)
    rows += _series('005930', '돌파주', list(range(1000, 1000 + CHANNEL_DAYS)) + [2000],
                    amount=90_000_000_000)
    sim = DonchianBreakoutSimulator(initial_cash=3_000_000)
    sim.state_file = str(tmp_path / 's.json')
    sim.log_file = str(tmp_path / 'l.json')
    sim.csv_file = str(tmp_path / 't.csv')
    sim.reset_state()
    run_donchian(sim, candidates_from_ohlcv(_csv(tmp_path, rows)))
    assert '005930' in sim.state['portfolio']
