"""심3의 7일 타임스탑은 배포 이래 한 번도 발동하지 않았다.

2026-08-13 심 전체 감사에서 드러났다. 청산 블록이 `date.fromisoformat()`을
부르는데 `date`가 import돼 있지 않았고, 그 자리를 감싼 `except Exception: pass`가
NameError를 통째로 삼켰다.

    entry_date = date.fromisoformat(entry_date_str)   # NameError
    ...
    except Exception:
        pass                                          # 조용히 사라진다

조용한 실패는 없는 기능과 같다. 로그에도 안 남으니 "타임스탑이 안 걸리는 날이
많네"와 "타임스탑이 아예 없다"가 구분되지 않았다.

같이 넣는 진입 깔때기는 심5·심9와 같은 목적이다 — 심3은 8월 매수가 1건뿐인데
이유가 로그에 없었다. 의심은 유니버스(get_finance_ratio_rank = ROE 수익성 상위)와
진입 조건(섹터 평균 대비 20% 저평가)이 서로 밀어낸다는 것이다. 고ROE는 대개
고PER/PBR이다. 추측으로 유니버스를 바꾸지 않고 먼저 센다.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy.simulators.sim3_risk import SmartRiskSimulator


def _sim():
    s = SmartRiskSimulator(initial_cash=3_000_000)
    s.save_state = lambda *a, **k: None
    return s


def test_timestop_fires_after_seven_days():
    """이게 배포 이래 죽어 있던 경로다."""
    sim = _sim()
    sim.state['portfolio']['005930'] = {
        'name': '삼성전자', 'quantity': 10, 'avg_price': 1000,
        'peak_price': 1000, 'entry_date': '2026-01-01', 'is_scaled_out': False,
    }

    sim.run([], current_prices={'005930': 1010})   # 손익 +1% — 익절·손절 미해당

    assert '005930' not in sim.state['portfolio'], '7일 지난 포지션은 타임스탑으로 청산돼야 한다'


def test_recent_entry_is_not_timestopped():
    from src.strategy.simulators.base_simulator import get_kst_date

    sim = _sim()
    sim.state['portfolio']['005930'] = {
        'name': '삼성전자', 'quantity': 10, 'avg_price': 1000,
        'peak_price': 1000, 'entry_date': get_kst_date().isoformat(),
        'is_scaled_out': False,
    }

    sim.run([], current_prices={'005930': 1010})

    assert '005930' in sim.state['portfolio']


def test_unparsable_entry_date_is_reported_not_swallowed(capsys):
    """모르는 것을 조용히 넘기면 그 기능이 죽은 걸 아무도 모른다."""
    sim = _sim()
    sim.state['portfolio']['005930'] = {
        'name': '삼성전자', 'quantity': 10, 'avg_price': 1000,
        'peak_price': 1000, 'entry_date': '(없음)', 'is_scaled_out': False,
    }

    sim.run([], current_prices={'005930': 1010})

    assert '타임스탑 판정 실패' in capsys.readouterr().out
    assert '005930' in sim.state['portfolio'], '판정 실패로 포지션을 잃으면 안 된다'


def test_funnel_reports_the_gate_that_blocked(capsys):
    """거래대금 문턱(50억)에서 전량 걸리는지, 저평가에서 걸리는지 갈라야
    유니버스를 바꿀지 조건을 바꿀지 정할 수 있다."""
    sim = _sim()
    cheap_but_thin = {'code': '000001', 'name': '얇은주', 'price': 1000,
                      'amount': 1_000_000, 'per': 1.0, 'pbr': 0.1,
                      'sector_name': '반도체'}

    sim.run([cheap_but_thin], current_prices={})

    out = capsys.readouterr().out
    assert '[Sim3 깔때기]' in out
    assert 'amount' in out
