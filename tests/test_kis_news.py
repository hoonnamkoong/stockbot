import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from unittest.mock import patch
from src.trade.kis_data_provider import KISDataProvider


MOCK_NEWS_RESPONSE = {
    "rt_cd": "0",
    "output": [
        {"hts_pbnt_titl_cntt": "카카오, AI 사업 본격화 선언",    "news_ofer_entp_code": "A"},
        {"hts_pbnt_titl_cntt": "카카오페이 실적 개선 기대",      "news_ofer_entp_code": "5"},
        {"hts_pbnt_titl_cntt": "카카오 플랫폼 사용자 역대 최고", "news_ofer_entp_code": "6"},
    ]
}

MOCK_NEWS_DUPLICATE_SRC = {
    "rt_cd": "0",
    "output": [
        {"hts_pbnt_titl_cntt": "카카오 AI 분사 검토",  "news_ofer_entp_code": "A"},
        {"hts_pbnt_titl_cntt": "AI 키우는 카카오",     "news_ofer_entp_code": "A"},  # 같은 출처
        {"hts_pbnt_titl_cntt": "카카오 2분기 실적",    "news_ofer_entp_code": "5"},
    ]
}


def _make_provider():
    provider = KISDataProvider.__new__(KISDataProvider)
    provider._cache = {}
    provider._token = "fake"
    provider._base_url = "https://fake"
    provider._app_key = "key"
    provider._app_secret = "secret"
    return provider


def test_get_news_titles_returns_list():
    provider = _make_provider()
    with patch.object(provider, '_get', return_value=MOCK_NEWS_RESPONSE):
        result = provider.get_news_titles("035720")
    assert isinstance(result, list)
    assert len(result) == 3
    assert result[0] == "카카오, AI 사업 본격화 선언"


def test_get_news_titles_deduplicates_by_source():
    provider = _make_provider()
    with patch.object(provider, '_get', return_value=MOCK_NEWS_DUPLICATE_SRC):
        result = provider.get_news_titles("035720")
    assert len(result) == 2
    assert "카카오 AI 분사 검토" in result
    assert "AI 키우는 카카오" not in result
    assert "카카오 2분기 실적" in result


def test_get_news_titles_returns_empty_on_failure():
    provider = _make_provider()
    with patch.object(provider, '_get', return_value={}):
        result = provider.get_news_titles("035720")
    assert result == []


def test_get_news_titles_uses_cache():
    provider = _make_provider()
    provider._cache = {"news_035720": (time.time(), ["캐시된 뉴스"])}
    with patch.object(provider, '_get') as mock_get:
        result = provider.get_news_titles("035720")
        mock_get.assert_not_called()
    assert result == ["캐시된 뉴스"]
