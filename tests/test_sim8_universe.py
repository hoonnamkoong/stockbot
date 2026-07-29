"""Sim8 유니버스 교체 — 버즈 유니버스에는 52주 앵커 종목이 없다.

2026-07-29 실측: 버즈 후보 28종목 중 52주 고점 85% 이상이 0개(최고 0.714).
심8은 '52주 고점 근처에서 정보거래자가 먼저 사는 구간'을 노리는데, 버즈
유니버스(급등·화제 종목)는 그 구간에 거의 없다. 파라미터가 아니라 유니버스
불일치다. 그래서 심8은 자기 가설과 같은 집단 — 외인·기관 순매수 상위 —
을 직접 본다.

교체에는 두 필드가 따라와야 한다. 둘 다 이미 받고 있는 응답에서 나온다:
  · w52_hgpr/w52_lwpr : 앵커 판정(_nearness)의 재료. KIS inquire-price 응답에
    이미 들어 있는데 get_price_quote가 버리고 있었다.
  · foreign_change    : info 축의 세 항 중 하나. 없으면 z가 퇴화해(_zmap이 빈
    dict) info가 전 종목 비어 진입이 원천 차단된다. 네이버 frgn 표의 오늘/어제
    외국인 보유율 두 행에서 나온다.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.trade_engine import TradeEngineWorker
from src.strategy.simulators.sim8_accumulation import AccumulationSimulator, _features, _nearness

_QUOTE = {'price': 6000, 'change_rate_pct': 1.0, 'per': 10.0, 'pbr': 1.0,
          'sector_name': '전기전자', 'w52_hgpr': 9000, 'w52_lwpr': 4000}


def _enrich(stocks, quote=None, naver_html=None):
    kis = mock.MagicMock()
    kis.get_price_quote.return_value = quote if quote is not None else _QUOTE
    kis.get_investor_trend_estimate.return_value = {}
    res = mock.MagicMock()
    res.content = (naver_html or '').encode('utf-8')
    ctx = mock.patch('requests.get', return_value=res) if naver_html else \
        mock.patch('requests.get', side_effect=OSError('네트워크 차단'))
    with ctx, mock.patch('src.trade.kis_data_provider.KISDataProvider', return_value=kis):
        return TradeEngineWorker._enrich_universe(None, stocks)


# ── w52: 앵커 판정의 재료 ──────────────────────────────────
def test_enrich_attaches_w52_from_kis():
    out = _enrich([{'code': '005930', 'name': '삼성전자'}])
    assert out[0]['w52_hgpr'] == 9000
    assert out[0]['w52_lwpr'] == 4000


def test_enrich_does_not_fabricate_w52_when_quote_fails():
    """0으로 채우면 _nearness가 0으로 나눌 값을 받는다 — 없으면 없는 채로 둔다."""
    out = _enrich([{'code': '005930', 'name': '삼성전자'}],
                  quote={'price': 0, 'change_rate_pct': 0.0, 'per': 0, 'pbr': 0,
                         'sector_name': '', 'w52_hgpr': 0, 'w52_lwpr': 0})
    assert 'w52_hgpr' not in out[0]


def test_enrich_does_not_overwrite_existing_w52():
    out = _enrich([{'code': '005930', 'name': '삼성전자', 'w52_hgpr': 111, 'w52_lwpr': 22}])
    assert (out[0]['w52_hgpr'], out[0]['w52_lwpr']) == (111, 22)


def test_w52_enables_nearness():
    """배선의 목적 — 앵커 판정이 None이 아니게 된다."""
    out = _enrich([{'code': '005930', 'name': '삼성전자'}])
    out[0]['price'] = 8100
    assert _nearness(out[0]) == 8100 / 9000


# ── foreign_change: info 축이 살아나는 조건 ─────────────────
_ROW = ('<tr>' + ''.join(f'<td>{v}</td>' for v in
        ('2026.07.29', '6,000', '+100', '+1.5%', '1,000,000', '+5,000', '+3,000', '100', '{fr}%')) + '</tr>')


def _naver_table(rates):
    rows = ''.join(_ROW.format(fr=r) for r in rates)
    return f'<table class="type2">{rows}</table>'


def test_enrich_computes_foreign_change_from_two_rows():
    out = _enrich([{'code': '005930', 'name': '삼성전자'}],
                  naver_html=_naver_table(['12.50', '12.10']))
    assert out[0]['foreign_change'] == 0.4


def test_foreign_change_missing_kills_info_axis():
    """왜 이 필드가 필수인지 못 박는다 — 전부 0이면 z가 퇴화해 info가 빈다."""
    cands = [{'code': f'{i:06d}', 'price': 1000, 'amount': 5e9,
              'frgn_fake_ntby_qty': 100 * i, 'orgn_fake_ntby_qty': 50 * i,
              'unique_posters': i, 'foreign_change': 0} for i in range(1, 16)]
    info, _ = _features(cands)
    assert info == {}


def test_info_axis_lives_when_foreign_change_varies():
    cands = [{'code': f'{i:06d}', 'price': 1000, 'amount': 5e9,
              'frgn_fake_ntby_qty': 100 * i, 'orgn_fake_ntby_qty': 50 * i,
              'unique_posters': i, 'foreign_change': i * 0.1} for i in range(1, 16)]
    info, _ = _features(cands)
    assert len(info) == 15


# ── 유니버스 교체 ─────────────────────────────────────────
def test_sim8_universe_is_foreign_institution_rank():
    kis = mock.MagicMock()
    kis.get_foreign_institution_rank.return_value = [{'code': '005930', 'name': '삼성전자'}]
    with mock.patch('src.trade.kis_data_provider.KISDataProvider', return_value=kis):
        universe = AccumulationSimulator(initial_cash=3_000_000).get_universe()
    assert universe == [{'code': '005930', 'name': '삼성전자'}]
    assert kis.get_foreign_institution_rank.call_args.kwargs['market'] == '0001'


def test_sim8_universe_returns_none_on_failure():
    """조회 실패 시 None → _resolve_candidates가 파이프라인 후보를 유지한다."""
    with mock.patch('src.trade.kis_data_provider.KISDataProvider', side_effect=OSError('실패')):
        assert AccumulationSimulator(initial_cash=3_000_000).get_universe() is None
