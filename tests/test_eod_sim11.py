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


# ── build_sim11_watchlist ────────────────────────────────
# 자격 판정 로직 자체(추세 템플릿·실적 가속·VCP 압축)는
# tests/test_sim11_minervini.py가 이미 촘촘히 덮는다. 여기서는 이 함수가
# 후보 목록을 build_watchlist_entry에 하나씩 넘기고 통과한 것만 code로
# 모으는 '배선'만 확인한다.
from scripts.run_eod_sims import build_sim11_watchlist
from unittest import mock


def test_watchlist_collects_only_qualifying_codes():
    cands = [{'code': 'A'}, {'code': 'B'}, {'code': 'C'}]

    def fake_entry(stock, funnel=None):
        return {'name': stock['code'], 'pivot_price': 1.0, 'ma50': 1.0} if stock['code'] != 'B' else None

    with mock.patch('src.strategy.simulators.sim11_minervini.build_watchlist_entry',
                    side_effect=fake_entry):
        entries = build_sim11_watchlist(cands)

    assert set(entries.keys()) == {'A', 'C'}


def test_watchlist_is_empty_when_nothing_qualifies():
    cands = [{'code': 'A'}, {'code': 'B'}]
    with mock.patch('src.strategy.simulators.sim11_minervini.build_watchlist_entry',
                    return_value=None):
        assert build_sim11_watchlist(cands) == {}


# ── 감시 목록 날짜 키 (2026-08-27) ─────────────────────
# _run_sim11이 `time.strftime('%Y%m%d')`로 **배치를 돌린 날**을 찍고 있었다.
# 배치는 마감 뒤 16시에 도는데 장중 로더는 오늘 날짜로만 읽으니(fail-closed)
# 그 키가 맞는 사이클이 존재하지 않았다 — 심11은 배포 이래 매수 0건이었다.
# 이제 kr_calendar.watchlist_target_date()가 "아직 안 끝난 가장 가까운 세션"을 준다.

def test_watchlist_is_stamped_with_next_session_not_batch_day(tmp_path, monkeypatch):
    """마감 뒤 배치는 다음 거래일 키를 찍는다 — 그날 장중 루프가 읽을 수 있게."""
    import scripts.run_eod_sims as r
    from src.strategy.simulators import sim11_minervini as m

    monkeypatch.setattr(m, 'WATCHLIST_PATH', str(tmp_path / 'wl.json'))
    monkeypatch.setattr(r, 'codes_and_names_from_ohlcv', lambda p: [('005930', '삼성전자')])
    monkeypatch.setattr(r, 'candidates_from_kis_live', lambda pairs, kis, log=None: [
        {'code': '005930', 'name': '삼성전자'}])
    monkeypatch.setattr(r, 'build_sim11_watchlist', lambda c, log=None, held_codes=(): {
        '005930': {'name': '삼성전자', 'pivot_price': 1000.0, 'ma50': 900.0}})
    monkeypatch.setattr(r, 'KISDataProvider', object, raising=False)
    monkeypatch.setattr('src.trade.kis_data_provider.KISDataProvider', lambda: object())
    monkeypatch.setattr(r, 'watchlist_target_date', lambda: '20260828')

    assert r._run_sim11('irrelevant.csv') == 0
    # 로더는 그 키로만 열어 준다. 배치를 돌린 날(08-27)로는 안 열린다.
    assert m.load_watchlist('20260828') != {}
    assert m.load_watchlist('20260827') == {}


# ── 보유 종목의 청산 지표(ma50)는 자격을 잃어도 남긴다 ─────
# 심11의 50일선 이탈 청산(sim11_minervini.py:215)은 **오늘 감시목록**에서 ma50을
# 읽는다. 그런데 감시목록 등재 자격인 _trend_template_ok가 `price > ma50`을
# 요구한다(sim11_minervini.py:81) — 50일선을 깬 종목은 정의상 감시목록에 못
# 오른다. 즉 청산이 필요한 바로 그 순간에 ma50이 None이 되어 청산이 조용히
# 건너뛰어진다. 남는 청산은 하드손절(-7.5%)뿐이고, 실제로 이 심의 SELL 3건은
# 전부 하드손절이었다(50일선 이탈 0건).
# 미국판 US Sim1에서 먼저 확정된 것과 같은 구조다.
def _below_ma_holding(code='T001', name='보유주'):
    """50일선 아래로 내려온 보유 종목 — 추세 템플릿을 통과하지 못한다."""
    return {'code': code, 'name': name, 'price': 50.0, 'amount': 5_000_000_000,
            'daily_closes': [100.0] * 229, 'w52_hgpr': 120.0, 'w52_lwpr': 40.0,
            'eps_growth_yoy': 30.0, 'revenue_growth_yoy': 30.0}


def test_below_ma_holding_still_gets_exit_indicator():
    """자격은 잃었어도 ma50은 실어야 50일선 이탈 청산이 발화한다."""
    entries = build_sim11_watchlist([_below_ma_holding()], held_codes={'T001'})
    assert 'T001' in entries
    # closes_through_today 마지막 50개 = 100×49 + 50 → 99.0
    assert entries['T001']['ma50'] == 99.0


def test_exit_only_entry_cannot_be_re_bought():
    """pivot_price가 없으면 decide_minervini가 no_pivot으로 진입을 막는다."""
    entries = build_sim11_watchlist([_below_ma_holding()], held_codes={'T001'})
    assert entries['T001']['pivot_price'] is None


def test_non_held_failing_candidate_stays_out():
    """보유 중이 아니면 종전대로 감시목록에서 빠진다 — 자격 판정을 우회하지 않는다."""
    assert build_sim11_watchlist([_below_ma_holding()], held_codes=set()) == {}


def test_qualifying_holding_keeps_its_real_pivot():
    """자격을 유지한 보유 종목은 정상 항목 그대로 — 청산 전용으로 덮지 않는다."""
    def fake_entry(stock, funnel=None):
        return {'name': '추세주', 'pivot_price': 200.0, 'ma50': 150.0}

    with mock.patch('src.strategy.simulators.sim11_minervini.build_watchlist_entry',
                    side_effect=fake_entry):
        entries = build_sim11_watchlist([{'code': 'T001'}], held_codes={'T001'})
    assert entries['T001']['pivot_price'] == 200.0


def test_holdings_are_read_from_state_file(tmp_path):
    """상태 파일의 portfolio 키가 보유 종목이다. 심을 인스턴스화하지 않는다 —
    BaseSimulator.load_state는 파일이 없으면 reset_state로 넘어가 거래 이력을 지운다."""
    import json as _json
    from scripts.run_eod_sims import load_sim11_holdings

    (tmp_path / 'sim_minervini_state.json').write_text(
        _json.dumps({'portfolio': {'078930': {'name': 'GS', 'quantity': 4}}}),
        encoding='utf-8')
    assert load_sim11_holdings(str(tmp_path)) == {'078930': 'GS'}


def test_missing_state_file_is_loud_not_silent(tmp_path, capsys):
    """못 읽으면 빈 집합으로 넘어가되 로그를 남긴다 — 청산 지표가 빠진 채
    초록으로 끝나면 아무도 모른다."""
    from scripts.run_eod_sims import load_sim11_holdings

    assert load_sim11_holdings(str(tmp_path / '없음')) == {}
    assert '상태' in capsys.readouterr().out


# ── 감시목록 깔때기 배선 (2026-09-15) ────────────────────
# 심11은 후보 100 → 감시목록 1이 평상시 값인데, 그 99가 어디서 떨어졌는지
# 로그에도 db-data에도 남지 않았다. 다른 심이 전부 쓰는 log_funnel 형식이
# 이 경로에만 없어서, "EPS 결손(KIS 미응답)"과 "EPS 미달(전략)"을 밖에서
# 구분할 수 없었다 — 임계값을 건드리기 전에 이 분포부터 있어야 한다.
def test_watchlist_logs_why_candidates_were_rejected(capsys):
    cands = [{'code': 'A'}, {'code': 'B'}, {'code': 'C'}]

    def fake_entry(stock, funnel=None):
        if stock['code'] == 'A':
            return {'name': 'A', 'pivot_price': 1.0, 'ma50': 1.0}
        funnel.append({'code': stock['code'],
                       'reason': 'no_eps' if stock['code'] == 'B' else 'eps_low'})
        return None

    # log_funnel은 다른 심과 똑같이 stdout으로 찍는다(Actions가 그걸 담는다).
    with mock.patch('src.strategy.simulators.sim11_minervini.build_watchlist_entry',
                    side_effect=fake_entry):
        build_sim11_watchlist(cands)

    out = capsys.readouterr().out
    assert '깔때기' in out, f'깔때기 줄이 없다: {out!r}'
    assert 'no_eps' in out and 'eps_low' in out, (
        f'결손과 미달이 구분돼 찍히지 않는다: {out!r}')
