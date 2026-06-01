import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data.sector_cache import SectorCache


def test_get_sector_avg_exact_match():
    cache = SectorCache()
    result = cache.get_sector_avg("소프트웨어")
    assert result is not None
    assert result["avg_per"] == 35.0
    assert result["avg_pbr"] == 4.2


def test_get_sector_avg_partial_match():
    cache = SectorCache()
    # KIS가 "IT소프트웨어"라고 보낼 때도 매칭되어야 함
    result = cache.get_sector_avg("IT소프트웨어")
    assert result is not None
    assert "avg_per" in result


def test_get_sector_avg_unknown_returns_none():
    cache = SectorCache()
    assert cache.get_sector_avg("존재하지않는업종XYZ") is None


def test_get_sector_avg_empty_returns_none():
    cache = SectorCache()
    assert cache.get_sector_avg("") is None


def test_ensure_fresh_is_noop():
    cache = SectorCache()
    cache.ensure_fresh()  # 예외 없이 통과해야 함


def test_major_sectors_all_present():
    cache = SectorCache()
    for sector in ["반도체", "제약", "은행", "자동차", "게임소프트웨어"]:
        assert cache.get_sector_avg(sector) is not None, f"{sector} 없음"
