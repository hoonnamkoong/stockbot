"""_apply가 BUY 주문의 playbook 메타데이터를 포트폴리오에 남긴다 — SELL의
mark_partial과 같은 패턴. Sim12가 '이 포지션이 어느 플레이북으로 들어왔는지'
청산 시점에 알아야 한다(플레이북2만 5일 타임스탑 대상)."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy.simulators.base_simulator import BaseSimulator


def _sim(tmp_path):
    s = BaseSimulator("PlaybookTagTest", initial_cash=3_000_000)
    s.state_file = str(tmp_path / "s.json")
    s.csv_file = str(tmp_path / "s.csv")
    s.log_file = str(tmp_path / "s.log")
    s.state = {'initial_cash': 3_000_000, 'cash': 3_000_000, 'invested': 0,
               'portfolio': {}, 'peak_nav': 3_000_000, 'total_fees': 0,
               'history': [3_000_000], 'daily_trades': [], 'cooldown_codes': {}}
    return s


def test_buy_order_with_playbook_tags_the_position(tmp_path):
    s = _sim(tmp_path)
    order = {'action': 'BUY', 'code': '005930', 'name': '삼성전자', 'price': 1000,
             'quantity': 10, 'playbook': 2, 'reason': 'test'}

    s._apply([order], {'005930': 1000})

    assert s.state['portfolio']['005930']['playbook'] == 2


def test_buy_order_without_playbook_does_not_add_the_key(tmp_path):
    """다른 심들의 기존 BUY 주문(playbook 키가 없음)은 영향받지 않는다."""
    s = _sim(tmp_path)
    order = {'action': 'BUY', 'code': '005930', 'name': '삼성전자', 'price': 1000,
             'quantity': 10, 'reason': 'test'}

    s._apply([order], {'005930': 1000})

    assert 'playbook' not in s.state['portfolio']['005930']
