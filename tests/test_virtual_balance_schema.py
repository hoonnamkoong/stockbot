# -*- coding: utf-8 -*-
"""가상 잔고 파일의 옛 스키마가 매 사이클 전략 판단을 죽이고 있었다.

2026-09-08 실측: 스크래퍼 런 42개 중 약 35개에서
`[TradeEngineWorker] ❌ ERROR: StrategyEngine 실패: 'invested'`가 났다.

data/virtual_balance.json은 2026-04-06 이후 그대로이고 키가 `invested_amount`다.
코드는 `balance['invested']`를 쓴다(virtual_portfolio.py의 buy_stock/sell_stock).
파일이 **이미 있으므로** init_portfolio()가 새 스키마로 다시 쓰지 않는다 —
그래서 샌드박스가 매수를 시도하는 순간 KeyError가 나고, trade_engine의
except가 그걸 받아 그 사이클 전 종목을 'WATCH' 폴백으로 만든다.

피해는 가상 잔고가 아니다(그 상태 파일은 배포 목록에 없어 런이 끝나면 버려진다).
**pick_features의 신호 관측이 오염된다** — 폴백이 걸린 사이클은 BUY가 하나도
없는 것처럼 기록된다. 약 5개월치가 그렇다.

`invested_amount`는 코드 어디에도 없다(2026-09-08 grep). 읽는 쪽이 옛 키를
흡수하고 새 키로 정규화한다 — 값은 보존한다.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy.virtual_portfolio import VirtualPortfolioManager


@pytest.fixture
def vpm(tmp_path, monkeypatch):
    monkeypatch.setattr('src.strategy.virtual_portfolio.PORTFOLIO_FILE',
                        str(tmp_path / 'virtual_portfolio.json'))
    monkeypatch.setattr('src.strategy.virtual_portfolio.BALANCE_FILE',
                        str(tmp_path / 'virtual_balance.json'))
    return VirtualPortfolioManager()


def _write_balance(vpm, payload):
    with open(vpm.balance_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f)


def test_옛_키를_새_키로_읽어들인다(vpm):
    """레포에 실제로 들어 있던 모양 그대로."""
    _write_balance(vpm, {'total_balance': 3000000, 'cash': 2500000,
                         'invested_amount': 500000,
                         'last_updated': '2026-04-06 00:00:00'})

    b = vpm.get_balance()

    assert b['invested'] == 500000, '옛 키의 값이 버려졌다'
    assert b['cash'] == 2500000


def test_옛_스키마에서도_매수가_터지지_않는다(vpm):
    """이게 5개월간 매 사이클 StrategyEngine을 죽인 그 경로다."""
    _write_balance(vpm, {'total_balance': 3000000, 'cash': 3000000,
                         'invested_amount': 0,
                         'last_updated': '2026-04-06 00:00:00'})

    res = vpm.buy_stock('005930', '삼성전자', 70000, 10)

    assert res is not None, '매수가 KeyError로 죽었다'
    assert vpm.get_balance()['invested'] > 0


def test_옛_스키마에서도_매도가_터지지_않는다(vpm):
    _write_balance(vpm, {'cash': 3000000, 'invested_amount': 0})
    vpm.buy_stock('005930', '삼성전자', 70000, 10)

    assert vpm.sell_stock('005930', 71000) is not None


def test_새_키가_있으면_그대로_쓴다(vpm):
    """마이그레이션이 정상 파일을 덮어쓰면 안 된다."""
    _write_balance(vpm, {'cash': 1000, 'invested': 999})

    assert vpm.get_balance()['invested'] == 999


def test_둘_다_있으면_새_키가_이긴다(vpm):
    """정규화 뒤 저장되면 한동안 두 키가 공존한다. 그때 옛 값을 읽으면 퇴행이다."""
    _write_balance(vpm, {'cash': 1000, 'invested': 700, 'invested_amount': 111})

    assert vpm.get_balance()['invested'] == 700


def test_둘_다_없으면_0이지_예외가_아니다(vpm):
    _write_balance(vpm, {'cash': 1000})

    assert vpm.get_balance()['invested'] == 0


def test_옛_키는_정규화_뒤_남지_않는다(vpm):
    """두 키가 계속 공존하면 다음 사람이 어느 쪽이 진짜인지 다시 묻게 된다."""
    _write_balance(vpm, {'cash': 1000, 'invested_amount': 222})

    assert 'invested_amount' not in vpm.get_balance()
