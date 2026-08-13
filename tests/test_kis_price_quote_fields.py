"""data_fetcher가 쓰던 필드를 get_price_quote가 마저 돌려줘야 사본을 지울 수 있다."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.trade.kis_data_provider import KISDataProvider

OUT = {
    'stck_prpr': '18000', 'prdy_ctrt': '3.6', 'per': '11.2', 'pbr': '0.9',
    'bstp_kor_isnm': '건설 ', 'w52_hgpr': '20000', 'w52_lwpr': '9000',
    'stck_oprc': '17000', 'stck_hgpr': '18500', 'stck_lwpr': '16800',
    'stck_sdpr': '17310',
    'hts_frgn_ehrt': '3.47', 'eps': '1500', 'bps': '20000',
    'hts_avls': '1234', 'acml_tr_pbmn': '1234567890', 'acml_vol': '4321',
}


def _provider(monkeypatch, body):
    p = object.__new__(KISDataProvider)
    p._token, p._base_url = 'tok', 'https://x'
    p._cache = {}
    monkeypatch.setattr(KISDataProvider, '_get', lambda self, *a, **k: body)
    return p


def test_returns_the_fields_data_fetcher_parsed_by_hand(monkeypatch):
    q = _provider(monkeypatch, {'rt_cd': '0', 'output': OUT}).get_price_quote('002990')
    assert q['foreign_rate'] == 3.47
    assert q['eps'] == 1500
    assert q['bps'] == 20000
    assert q['mkt_cap'] == 1234
    assert q['amount'] == 1234567890
    assert q['volume'] == 4321


def test_existing_keys_are_unchanged(monkeypatch):
    """회귀 방지 — program_trader·trade_engine이 이미 이 키들을 쓴다."""
    q = _provider(monkeypatch, {'rt_cd': '0', 'output': OUT}).get_price_quote('002990')
    assert q['price'] == 18000 and q['per'] == 11.2 and q['open_price'] == 17000
    assert q['sector_name'] == '건설'


def test_empty_response_still_carries_every_key(monkeypatch):
    """폴백에 키가 빠지면 호출부가 KeyError로 죽는다."""
    q = _provider(monkeypatch, {}).get_price_quote('002990')
    for k in ('foreign_rate', 'eps', 'bps', 'mkt_cap', 'amount', 'volume'):
        assert q[k] == 0
