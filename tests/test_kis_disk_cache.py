"""E7 (2026-08-04 스크래퍼 지연 재설계): 재무비율·투자의견 디스크 캐시.

TTL_FINANCIAL(7일)·TTL_DAILY(1일) 캐시가 인메모리(인스턴스 단위)라 파이프라인
런(프로세스, ~6분)이 끝나면 같이 죽었다. 10분마다 새 프로세스가 같은 17종목의
재무비율을 다시 조회했다(하루 2,000+ 콜). data/kis_financial_cache.json에
써서 다음 프로세스도 읽게 한다.

get_price_quote(드리프트 가드용, "새 인스턴스 = 캐시 무시"에 기대는 경로)는
여전히 인스턴스 캐시라 건드리지 않는다 — 여기서 회귀를 같이 확인한다.
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
    path = str(tmp_path / "kis_financial_cache.json")
    return mock.patch.object(kis_data_provider, '_DISK_CACHE_PATH', path)


def _fake_profit_ratio_get(url, tr_id, params, timeout=5):
    return {"output": [{"self_cptl_ntin_inrt": "12.3", "sale_ntin_rate": "8.1"}]}


def test_second_process_reuses_disk_cache(tmp_path):
    """같은 프로세스든 아니든(=새 인스턴스 + 인메모리 캐시 리셋) 디스크에 있으면
    API를 다시 안 부른다 — 오늘의 실제 상황(매 10분 새 프로세스)을 흉내낸다."""
    with _redirect_cache_file(tmp_path), \
         mock.patch.object(KISDataProvider, '_get', side_effect=_fake_profit_ratio_get) as get_mock:
        p1 = KISDataProvider()
        r1 = p1.get_finance_profit_ratio('005930')
        assert get_mock.call_count == 1

        # "다음 프로세스" 흉내: 인메모리 상태를 전부 지운다(디스크 파일만 남긴다).
        KISDataProvider._disk_cache.clear()
        KISDataProvider._disk_cache_loaded = False

        p2 = KISDataProvider()
        r2 = p2.get_finance_profit_ratio('005930')
        assert get_mock.call_count == 1  # 늘지 않아야 한다 — 디스크에서 왔다
        assert r1 == r2


def test_cache_file_is_written_to_disk(tmp_path):
    with _redirect_cache_file(tmp_path), \
         mock.patch.object(KISDataProvider, '_get', side_effect=_fake_profit_ratio_get):
        KISDataProvider().get_finance_profit_ratio('005930')

    cache_file = tmp_path / "kis_financial_cache.json"
    assert cache_file.exists()
    content = cache_file.read_text(encoding='utf-8')
    assert 'profit_ratio_005930' in content


def test_missing_or_corrupt_cache_file_falls_back_to_empty(tmp_path):
    """캐시 파일이 없거나 깨져 있어도 죽지 않고 그냥 API로 간다(fail-open — 성능
    최적화지 정합성 근거가 아니다)."""
    bad_path = str(tmp_path / "does_not_exist.json")
    with mock.patch.object(kis_data_provider, '_DISK_CACHE_PATH', bad_path), \
         mock.patch.object(KISDataProvider, '_get', side_effect=_fake_profit_ratio_get) as get_mock:
        result = KISDataProvider().get_finance_profit_ratio('005930')
        assert result['roe'] == 12.3
        assert get_mock.call_count == 1


def test_expired_disk_entry_is_refetched(tmp_path):
    with _redirect_cache_file(tmp_path), \
         mock.patch.object(KISDataProvider, '_get', side_effect=_fake_profit_ratio_get) as get_mock:
        p = KISDataProvider()
        p.get_finance_profit_ratio('005930')
        # 저장된 타임스탬프를 과거로 돌려 TTL을 강제로 만료시킨다.
        key = 'profit_ratio_005930'
        ts, data = KISDataProvider._disk_cache[key]
        KISDataProvider._disk_cache[key] = (ts - KISDataProvider.TTL_FINANCIAL - 1, data)
        p.get_finance_profit_ratio('005930')
        assert get_mock.call_count == 2


def test_disk_cache_rows_are_independent_copies(tmp_path):
    """finance_ratio_rank도 이제 디스크 캐시를 쓴다 — 사본 오염 방지는 여전히 유효해야 한다."""
    def fake_rank_get(url, tr_id, params, timeout=5):
        return {"output": [{"mksc_shrn_iscd": "005930", "hts_kor_isnm": "삼성전자",
                            "stck_prpr": "70000", "acml_vol": "100", "prdy_ctrt": "1.0"}]}

    with _redirect_cache_file(tmp_path), \
         mock.patch.object(KISDataProvider, '_get', side_effect=fake_rank_get) as get_mock:
        p1 = KISDataProvider()
        r1 = p1.get_finance_ratio_rank(market='0001', limit=30)
        r1[0]['price'] = 999999

        p2 = KISDataProvider()
        r2 = p2.get_finance_ratio_rank(market='0001', limit=30)
        assert r2[0]['price'] != 999999
        assert get_mock.call_count == 1  # 두 번째는 디스크 캐시에서 왔다


def test_price_quote_unaffected_still_instance_scoped(tmp_path):
    """회귀 확인 — get_price_quote는 이번 변경과 무관하게 인스턴스 캐시 그대로."""
    def fake_quote_get(url, tr_id, params, timeout=5):
        return {"output": {"stck_prpr": "10000", "prdy_ctrt": "1.0"}}

    with _redirect_cache_file(tmp_path), \
         mock.patch.object(KISDataProvider, '_get', side_effect=fake_quote_get) as get_mock:
        KISDataProvider().get_price_quote('005930')
        KISDataProvider().get_price_quote('005930')
        assert get_mock.call_count == 2
