"""Sim11(미너비니)의 EOD 러너 배선 — ohlcv_top100.csv에서 유니버스 시드를
뽑고, 값 자체는 KIS 실시간 조회로 채운다(150/200일선·분기 실적은 CSV에 없다).
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.run_eod_sims import codes_and_names_from_ohlcv, candidates_from_kis_live


def _csv(tmp_path, rows):
    p = tmp_path / 'ohlcv.csv'
    p.write_text('date,code,name,open,high,low,close,volume,amount\n' + '\n'.join(rows) + '\n',
                 encoding='utf-8')
    return str(p)


def _row(code, name, close=1000):
    return f'20260819,{code},{name},{close},{close},{close},{close},1000,5000000000'


# ── codes_and_names_from_ohlcv ──────────────────────────
def test_extracts_unique_codes_and_names(tmp_path):
    path = _csv(tmp_path, [_row('005930', '삼성전자'), _row('005930', '삼성전자'),
                           _row('000660', 'SK하이닉스')])
    assert codes_and_names_from_ohlcv(path) == [('000660', 'SK하이닉스'), ('005930', '삼성전자')]


def test_excludes_etfs(tmp_path):
    path = _csv(tmp_path, [_row('069500', 'KODEX 200'), _row('005930', '삼성전자')])
    assert codes_and_names_from_ohlcv(path) == [('005930', '삼성전자')]


def test_missing_file_returns_empty(tmp_path):
    assert codes_and_names_from_ohlcv(str(tmp_path / 'x.csv')) == []


# ── candidates_from_kis_live ────────────────────────────
def _hist(n=230, today=None):
    """n일치 종가열(오래된→최신). 날짜는 비교용 임의 문자열이라 실제 달력일
    필요 없다 — 정렬 순서만 지킨다. today가 주어지면 마지막 봉의 날짜를 맞춘다."""
    out = [{'date': f'2020{i:05d}', 'close': 100.0 + i, 'amount': 1_000_000_000}
           for i in range(n)]
    if today:
        out[-1] = dict(out[-1], date=today)
    return out


class _FakeKis:
    def __init__(self, hist, quote=None, growth=None, fail_codes=()):
        self._hist = hist
        self._quote = quote if quote is not None else {
            'price': 500.0, 'amount': 2_000_000_000, 'w52_hgpr': 600, 'w52_lwpr': 300}
        self._growth = growth if growth is not None else {
            'eps_growth_yoy': 25.0, 'revenue_growth_yoy': 20.0}
        self._fail_codes = set(fail_codes)
        self.calls = []

    def get_daily_history(self, code, days=230):
        self.calls.append(('hist', code))
        if code in self._fail_codes:
            raise RuntimeError('네트워크 실패')
        return self._hist

    def get_price_quote(self, code):
        self.calls.append(('quote', code))
        return self._quote

    def get_earnings_growth(self, code):
        self.calls.append(('growth', code))
        return self._growth


TODAY = time.strftime('%Y%m%d')


def test_builds_candidate_with_all_fields():
    kis = _FakeKis(_hist(230, today=TODAY))
    out = candidates_from_kis_live([('005930', '삼성전자')], kis, pace_interval=0)
    assert len(out) == 1
    c = out[0]
    assert c['code'] == '005930' and c['name'] == '삼성전자'
    assert c['w52_hgpr'] == 600 and c['w52_lwpr'] == 300
    assert c['eps_growth_yoy'] == 25.0 and c['revenue_growth_yoy'] == 20.0


def test_strips_todays_bar_from_daily_closes():
    """당일 종가가 daily_closes에 섞이면 돌파 판정이 정의상 불가능해진다."""
    hist = _hist(230, today=TODAY)
    kis = _FakeKis(hist)
    out = candidates_from_kis_live([('005930', '삼성전자')], kis, pace_interval=0)
    c = out[0]
    assert c['price'] == hist[-1]['close']              # 당일 종가는 price로
    assert hist[-1]['close'] not in c['daily_closes']    # daily_closes에는 없어야
    assert len(c['daily_closes']) == 229


def test_uses_live_quote_when_todays_bar_not_yet_posted():
    """일봉 TR이 아직 당일 봉을 안 줬으면(장중 실행 등) 실시간 시세로 대체한다."""
    hist = _hist(230, today='20250101')   # 마지막 봉이 오늘이 아님
    quote = {'price': 777.0, 'amount': 3_000_000_000, 'w52_hgpr': 900, 'w52_lwpr': 400}
    kis = _FakeKis(hist, quote=quote)
    out = candidates_from_kis_live([('005930', '삼성전자')], kis, pace_interval=0)
    c = out[0]
    assert c['price'] == 777.0
    assert len(c['daily_closes']) == 230   # 이번엔 아무것도 안 뗐다


def test_skips_stocks_with_short_history():
    kis = _FakeKis(_hist(100, today=TODAY))   # 220 미만
    out = candidates_from_kis_live([('005930', '삼성전자')], kis, pace_interval=0)
    assert out == []


def test_one_failing_stock_does_not_stop_the_batch():
    kis = _FakeKis(_hist(230, today=TODAY), fail_codes={'000660'})
    out = candidates_from_kis_live(
        [('000660', '실패주'), ('005930', '삼성전자')], kis, pace_interval=0)
    assert [c['code'] for c in out] == ['005930']


def test_missing_growth_fields_are_not_fabricated():
    """실적 조회가 결손을 주면(빈 dict) 필드를 안 채운다 — 심11의 게이트가
    None으로 읽어 진입을 막게 한다."""
    kis = _FakeKis(_hist(230, today=TODAY), growth={})
    out = candidates_from_kis_live([('005930', '삼성전자')], kis, pace_interval=0)
    c = out[0]
    assert 'eps_growth_yoy' not in c
    assert 'revenue_growth_yoy' not in c


def test_zero_price_is_skipped():
    kis = _FakeKis(_hist(230, today=TODAY), quote={'price': 0, 'amount': 0,
                                                    'w52_hgpr': 0, 'w52_lwpr': 0})
    hist_no_today = _hist(230, today='20250101')
    kis._hist = hist_no_today
    out = candidates_from_kis_live([('005930', '삼성전자')], kis, pace_interval=0)
    assert out == []
