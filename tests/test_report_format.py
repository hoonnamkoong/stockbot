import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.advisor import StrategyAdvisor


def make_stock(**kwargs):
    base = {
        'code': '035720', 'name': '카카오', 'price': 46050, 'rank': 1,
        'per': 41.5, 'pbr': 1.8, 'w52_hgpr': 62400, 'w52_lwpr': 39800,
        'invest_opinion': '매수', 'target_price': 58000, 'opinion_divergence': 26.0,
        'consensus_summary': '매수 7/9개사, 평균목표가 61,000원',
        'sector_name': '소프트웨어',
        'foreign_change': 0.12,
        'posts_summary': '[분석] 카카오 AI 전환 기대 150건 포착',
    }
    base.update(kwargs)
    return base


def test_format_investment_block_contains_opinion():
    advisor = StrategyAdvisor.__new__(StrategyAdvisor)
    block = advisor._format_investment_block(make_stock(), {'avg_per': 35.0, 'avg_pbr': 4.2})
    assert '매수' in block
    assert '58,000' in block


def test_format_investment_block_per_with_sector():
    advisor = StrategyAdvisor.__new__(StrategyAdvisor)
    block = advisor._format_investment_block(make_stock(), {'avg_per': 35.0, 'avg_pbr': 4.2})
    assert '41.5x' in block
    assert '35.0x' in block


def test_format_investment_block_per_fallback_no_sector():
    advisor = StrategyAdvisor.__new__(StrategyAdvisor)
    block = advisor._format_investment_block(make_stock(per=8.0, pbr=0.7), None)
    assert '8.0x' in block
    assert '저평가' in block
    assert '0.7x' in block
    assert '자산가치' in block


def test_format_investment_block_52week():
    advisor = StrategyAdvisor.__new__(StrategyAdvisor)
    block = advisor._format_investment_block(make_stock(), None)
    assert '62,400' in block
    assert '39,800' in block
    # (46050 - 39800) / (62400 - 39800) * 100 ≈ 28%
    assert '28%' in block


def test_format_investment_block_no_emojis():
    advisor = StrategyAdvisor.__new__(StrategyAdvisor)
    block = advisor._format_investment_block(make_stock(), None)
    for emoji in ['📌', '🏢', '💡', '🎯', '⚠️', '🚀', '📅']:
        assert emoji not in block
