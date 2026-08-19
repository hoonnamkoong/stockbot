"""Sim11(미너비니) 재료 — KIS 일별시세 페이지네이션과 분기 실적 성장률.

get_daily_history: FHKST03010100은 요청 구간과 무관하게 콜당 최신 100건만
준다(2026-08-20 실측). 200일 이상을 모으려면 직전 콜의 가장 오래된 날짜
전날로 FID_INPUT_DATE_2를 옮겨가며 이어 붙여야 한다.

get_earnings_growth: FHKST66430300(get_ttm_valuation과 같은 TR)이 분기
30개(7년+)를 주는데, 그 안의 grs(매출증가율)와 전년동기 EPS 비교로
미너비니 SEPA의 실적 가속 필터 재료를 만든다.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.trade import kis_data_provider
from src.trade.kis_data_provider import KISDataProvider


def setup_function(_):
    KISDataProvider._disk_cache.clear()
    KISDataProvider._disk_cache_loaded = False


def _redirect_cache_file(tmp_path):
    return mock.patch.object(kis_data_provider, '_DISK_CACHE_PATH',
                             str(tmp_path / "kis_financial_cache.json"))


def _bar(date, close, o=None, h=None, l=None, vol=1000, amt=1_000_000):
    return {'stck_bsop_date': date, 'stck_clpr': str(close),
            'stck_oprc': str(o if o is not None else close),
            'stck_hgpr': str(h if h is not None else close),
            'stck_lwpr': str(l if l is not None else close),
            'acml_vol': str(vol), 'acml_tr_pbmn': str(amt)}


# ── get_daily_history ────────────────────────────────────
def test_parses_bars_into_expected_shape(tmp_path):
    rows = [_bar('20260819', 100), _bar('20260818', 99)]
    with _redirect_cache_file(tmp_path), \
         mock.patch.object(KISDataProvider, '_get', return_value={'output2': rows}):
        hist = KISDataProvider().get_daily_history('005930', days=250)
    assert len(hist) == 2
    assert hist[0]['date'] == '20260818' and hist[0]['close'] == 99.0
    assert hist[1]['date'] == '20260819' and hist[1]['close'] == 100.0


def test_sorted_oldest_to_newest(tmp_path):
    rows = [_bar('20260819', 3), _bar('20260817', 1), _bar('20260818', 2)]
    with _redirect_cache_file(tmp_path), \
         mock.patch.object(KISDataProvider, '_get', return_value={'output2': rows}):
        hist = KISDataProvider().get_daily_history('005930', days=250)
    assert [h['date'] for h in hist] == ['20260817', '20260818', '20260819']


def test_paginates_when_first_page_is_full(tmp_path):
    """콜당 100건만 오면 두 번째 콜로 더 오래된 구간을 이어 붙여야 한다."""
    page1 = [_bar(f'202608{19-i:02d}', 100 - i) for i in range(19)]  # 19건(가짜 '가득 참')
    page2 = [_bar(f'202607{31-i:02d}', 50 - i) for i in range(5)]
    calls = {'n': 0}

    def fake_get(url, tr_id, params, timeout=5):
        calls['n'] += 1
        return {'output2': page1} if calls['n'] == 1 else {'output2': page2}

    with _redirect_cache_file(tmp_path), \
         mock.patch.object(KISDataProvider, '_get', side_effect=fake_get):
        hist = KISDataProvider().get_daily_history('005930', days=24)

    assert calls['n'] == 2
    assert len(hist) == 24
    assert hist == sorted(hist, key=lambda h: h['date'])


def test_dedupes_overlapping_dates_across_pages(tmp_path):
    """페이지 경계가 겹쳐도 같은 날짜가 두 번 들어가면 안 된다."""
    page1 = [_bar('20260819', 100), _bar('20260818', 99)]
    page2 = [_bar('20260818', 99), _bar('20260817', 98)]  # 20260818 중복
    calls = {'n': 0}

    def fake_get(url, tr_id, params, timeout=5):
        calls['n'] += 1
        if calls['n'] == 1:
            return {'output2': page1}
        if calls['n'] == 2:
            return {'output2': page2}
        return {'output2': []}

    with _redirect_cache_file(tmp_path), \
         mock.patch.object(KISDataProvider, '_get', side_effect=fake_get):
        hist = KISDataProvider().get_daily_history('005930', days=250)

    dates = [h['date'] for h in hist]
    assert len(dates) == len(set(dates))


def test_stops_when_no_new_rows_come_back(tmp_path):
    """더 못 주면(빈 응답) 무한 재시도하지 않고 있는 만큼만 돌려준다."""
    calls = {'n': 0}

    def fake_get(url, tr_id, params, timeout=5):
        calls['n'] += 1
        return {'output2': [_bar('20260819', 100)]} if calls['n'] == 1 else {'output2': []}

    with _redirect_cache_file(tmp_path), \
         mock.patch.object(KISDataProvider, '_get', side_effect=fake_get):
        hist = KISDataProvider().get_daily_history('005930', days=250)

    assert calls['n'] == 2
    assert len(hist) == 1


def test_empty_response_returns_empty_list_not_fabricated(tmp_path):
    with _redirect_cache_file(tmp_path), \
         mock.patch.object(KISDataProvider, '_get', return_value={}):
        hist = KISDataProvider().get_daily_history('005930', days=250)
    assert hist == []


def test_result_is_cached_across_instances(tmp_path):
    rows = [_bar('20260819', 100)]
    with _redirect_cache_file(tmp_path), \
         mock.patch.object(KISDataProvider, '_get', return_value={'output2': rows}) as get_mock:
        KISDataProvider().get_daily_history('005930', days=250)
        # 첫 콜로 1건 확보 후, 다음 페이지 요청도 같은 날짜만 돌려주므로
        # '새 날짜 없음'으로 두 번째 콜에서 멈춘다.
        assert get_mock.call_count == 2

        KISDataProvider._disk_cache.clear()
        KISDataProvider._disk_cache_loaded = False
        KISDataProvider().get_daily_history('005930', days=250)
        assert get_mock.call_count == 2   # 디스크 캐시에서 왔으니 늘지 않는다


# ── get_earnings_growth ───────────────────────────────────
def _quarter(yymm, eps, grs=0.0):
    return {'stac_yymm': yymm, 'eps': str(eps), 'grs': str(grs)}


def test_computes_eps_and_revenue_growth_yoy(tmp_path):
    rows = [_quarter('202603', 6993, grs=69.16), _quarter('202503', 1186, grs=10.05)]
    with _redirect_cache_file(tmp_path), \
         mock.patch.object(KISDataProvider, '_get', return_value={'output': rows}):
        g = KISDataProvider().get_earnings_growth('005930')
    assert g['period'] == '202603'
    assert g['revenue_growth_yoy'] == 69.16
    assert g['eps_growth_yoy'] == round((6993 - 1186) / 1186 * 100, 2)


def test_missing_prior_year_quarter_omits_eps_growth(tmp_path):
    """전년동기 조각이 없으면 성장률을 지어내지 않는다 — 매출증가율만 남는다."""
    rows = [_quarter('202603', 6993, grs=69.16)]
    with _redirect_cache_file(tmp_path), \
         mock.patch.object(KISDataProvider, '_get', return_value={'output': rows}):
        g = KISDataProvider().get_earnings_growth('005930')
    assert 'eps_growth_yoy' not in g
    assert g['revenue_growth_yoy'] == 69.16


def test_negative_prior_year_eps_omits_growth_rate(tmp_path):
    """전년동기가 적자(EPS<=0)면 성장률 분모가 나쁘다 — 지어내지 않는다."""
    rows = [_quarter('202603', 6993, grs=69.16), _quarter('202503', -500)]
    with _redirect_cache_file(tmp_path), \
         mock.patch.object(KISDataProvider, '_get', return_value={'output': rows}):
        g = KISDataProvider().get_earnings_growth('005930')
    assert 'eps_growth_yoy' not in g


def test_empty_response_returns_empty_dict(tmp_path):
    with _redirect_cache_file(tmp_path), \
         mock.patch.object(KISDataProvider, '_get', return_value={}):
        g = KISDataProvider().get_earnings_growth('005930')
    assert g == {}
