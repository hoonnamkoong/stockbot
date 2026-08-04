"""E5 (2026-08-04 스크래퍼 지연 재설계): 유니버스 순위 API 클래스 레벨 캐시.

Sim4·Sim4-1·Sim10(BULL)·프로그램매매가 매 사이클 같은 (market, sort, limit)
조합을 각자 새 KISDataProvider() 인스턴스로 조회했다 — 인스턴스 캐시가 매번
리셋돼 같은 요청이 최대 4번 나갔다(121초). 클래스 레벨 캐시로 승격해 프로세스
(=파이프라인 런) 수명 동안 공유한다.

get_price_quote(드리프트 가드가 "새 인스턴스 = 캐시 무시"에 기대는 경로)는
건드리지 않는다 — 회귀 확인도 여기서 함께 한다.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.trade.kis_data_provider import KISDataProvider


def setup_function(_):
    # 클래스 레벨 캐시라 테스트 간 오염을 막기 위해 매번 비운다.
    KISDataProvider._rank_cache.clear()


def _fake_get(url, tr_id, params, timeout=5):
    return {"output": [
        {"stck_shrn_iscd": "005930", "hts_kor_isnm": "삼성전자",
         "stck_prpr": "70000", "acml_vol": "1000", "prdy_ctrt": "1.5"},
    ]}


def test_fluctuation_rank_shared_across_instances():
    """서로 다른 인스턴스라도 같은 (market, sort)면 두 번째부터는 API를 안 부른다."""
    with mock.patch.object(KISDataProvider, '_get', side_effect=_fake_get) as get_mock:
        p1 = KISDataProvider()
        r1 = p1.get_fluctuation_rank(market='0001', sort='0', limit=30)
        p2 = KISDataProvider()  # 다른 사이드에서 새로 생성 — 오늘의 버그 재현 조건
        r2 = p2.get_fluctuation_rank(market='0001', sort='0', limit=30)
        assert get_mock.call_count == 1
        assert r1 == r2


def test_cached_rows_are_independent_copies():
    """한 심이 받은 유니버스를 수정해도 다른 심이 받은 사본에 새지 않는다."""
    with mock.patch.object(KISDataProvider, '_get', side_effect=_fake_get):
        p1 = KISDataProvider()
        r1 = p1.get_fluctuation_rank(market='0001', sort='0', limit=30)
        r1[0]['price'] = 999999  # Sim4가 enrichment 도중 값을 바꿨다고 가정

        p2 = KISDataProvider()
        r2 = p2.get_fluctuation_rank(market='0001', sort='0', limit=30)
        assert r2[0]['price'] != 999999


def test_different_params_are_not_shared():
    """market/sort가 다르면 별개 캐시 키 — Sim6의 하락률(sort=1)이 Sim4의
    상승률(sort=0) 캐시를 가로채면 안 된다."""
    with mock.patch.object(KISDataProvider, '_get', side_effect=_fake_get) as get_mock:
        p = KISDataProvider()
        p.get_fluctuation_rank(market='0001', sort='0', limit=30)
        p.get_fluctuation_rank(market='0001', sort='1', limit=30)
        assert get_mock.call_count == 2


def test_price_quote_still_bypasses_cache_via_new_instance():
    """회귀 확인 — 드리프트 가드가 쓰는 get_price_quote는 여전히 인스턴스
    캐시라, 새 인스턴스는 캐시를 안 타고 실제 조회로 간다."""
    def fake_quote_get(url, tr_id, params, timeout=5):
        return {"output": {"stck_prpr": "10000", "prdy_ctrt": "1.0"}}

    with mock.patch.object(KISDataProvider, '_get', side_effect=fake_quote_get) as get_mock:
        p1 = KISDataProvider()
        p1.get_price_quote('005930')
        p2 = KISDataProvider()  # 새 인스턴스 — 신선한 값을 다시 조회해야 한다
        p2.get_price_quote('005930')
        assert get_mock.call_count == 2


# get_finance_ratio_rank(TTL_FINANCIAL=7일)은 E7에서 _rank_cache가 아니라 디스크
# 캐시(_disk_cache)로 옮겨졌다 — 공유·사본독립성 테스트는 tests/test_kis_disk_cache.py에 있다.


def test_foreign_institution_rank_also_shared():
    with mock.patch.object(KISDataProvider, '_get', side_effect=_fake_get) as get_mock:
        KISDataProvider().get_foreign_institution_rank(market='0001', etc_cls='0', limit=30)
        KISDataProvider().get_foreign_institution_rank(market='0001', etc_cls='0', limit=30)
        assert get_mock.call_count == 1
