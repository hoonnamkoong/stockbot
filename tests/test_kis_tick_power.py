"""체결강도는 inquire-ccnl(FHKST01010300)이고, output은 체결 30행 리스트다."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.trade.kis_data_provider import KISDataProvider

CCNL_ROWS = [
    {'stck_cntg_hour': '155954', 'stck_prpr': '255500', 'cntg_vol': '19',
     'tday_rltv': '128.92', 'prdy_ctrt': '6.68'},
    {'stck_cntg_hour': '155747', 'stck_prpr': '255500', 'cntg_vol': '1',
     'tday_rltv': '128.92', 'prdy_ctrt': '6.68'},
]


def _provider(monkeypatch, body):
    p = object.__new__(KISDataProvider)
    p._token, p._base_url = 'tok', 'https://x'
    p._cache = {}
    monkeypatch.setattr(KISDataProvider, '_get', lambda self, *a, **k: body)
    return p


def test_reads_tick_power_from_the_latest_row(monkeypatch):
    p = _provider(monkeypatch, {'rt_cd': '0', 'output': CCNL_ROWS})
    assert p.get_tick_power('005930') == 128.92


def test_empty_output_is_zero_not_a_crash(monkeypatch):
    """장 시작 전엔 체결이 없다. 0으로 떨어지되 죽지 않아야 한다."""
    p = _provider(monkeypatch, {'rt_cd': '0', 'output': []})
    assert p.get_tick_power('005930') == 0.0


def test_failed_call_is_zero(monkeypatch):
    """_get은 실패 시 {}를 준다(예외 아님)."""
    p = _provider(monkeypatch, {})
    assert p.get_tick_power('005930') == 0.0
