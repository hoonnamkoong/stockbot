"""심11 유니버스를 시총 상위 100 대형주에서 넓힌다.

2026-09-16 깔때기 실측(후보 100 → 감시목록 1):

    -74 not_stacked         →  26 남음   (추세가 아님 — 정상 동작이다)
    - 4 below_ma50          →  22
    - 6 far_below_52w_high  →  16
    - 1 near_52w_low        →  15        ← 추세 템플릿 완주 15/100
    - 8 eps_low             →   7
    - 3 no_eps              →   4        ← 수집 문제가 아니다(3건뿐)
    - 2 revenue_low         →   2        ← 실적 게이트가 15 → 2, **87% 컷**
    - 1 no_vcp              →   1

읽는 법: 대형주는 ① 추세 자격이 **15%**뿐이고 ② 그중 **87%가 실적 미달**이다.
둘 다 "조건이 과해서"가 아니라 **성숙 기업이라서**다 — 미너비니가 노리는 것은
실적 가속 중인 성장 주도주이고, 시총 상위 100은 그 못이 아니다.

그래서 임계값을 낮추지 않고 **못을 바꾼다.** EPS +20%·매출 +15%는 성장주에서는
드문 조건이 아니라 성장주의 정의다.

필요한 것은 CSV가 아니라 **코드 목록**이다 — `candidates_from_kis_live`가 종목별
230일을 KIS로 직접 받으므로 `ohlcv_top100.csv`는 씨앗으로만 쓰인다.

**`ohlcv_top100.csv`는 건드리지 않는다.** 리베로 `trend`·`breadth`와 심9-1이 그
파일을 먹어서, 유니버스를 바꾸면 국면 판정이 딸려 온다.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.run_eod_sims import sim11_universe


def _row(code, name, amount, cap=1e12):
    return {'code': code, 'name': name, 'price': 10000, 'amount': amount,
            'change_rate': '+1.00%', 'volume': 100, 'market_cap': cap}


def test_universe_comes_from_the_kospi_market_cap_ranking():
    rows = [_row(f'{i:06d}', f'종목{i}', 5_000_000_000) for i in range(3)]
    with mock.patch('src.data.naver_api.stock_list', return_value=rows) as sl:
        pairs = sim11_universe(seed_path='/없는/경로.csv')

    assert [c for c, _ in pairs] == ['000000', '000001', '000002']
    kind, market, limit = sl.call_args.args[:3]
    assert (kind, market) == ('marketValue', 'KOSPI'), '시총 순위·코스피여야 한다'
    assert limit >= 300, f'시총 상위 {limit}은 너무 좁다 — 못을 넓히는 것이 목적이다'


def test_illiquid_names_are_dropped_before_any_kis_call():
    """비용이 드는 건 KIS 일봉이지 목록이 아니다. 유동성 미달은 먼저 버린다."""
    rows = [_row('000001', '유동', 5_000_000_000),
            _row('000002', '비유동', 100_000_000)]
    with mock.patch('src.data.naver_api.stock_list', return_value=rows):
        pairs = sim11_universe(seed_path='/없는/경로.csv')

    assert [c for c, _ in pairs] == ['000001'], '거래대금 미달 종목이 남았다'


def test_naver_failure_falls_back_to_the_existing_seed(tmp_path):
    """2026-09-10에 네이버가 302로 옮겨가 EOD가 통째로 죽었다.

    목록을 못 받았다고 심11을 쉬게 하면, 못을 넓히려다 있던 것도 잃는다.
    """
    seed = tmp_path / 'ohlcv.csv'
    seed.write_text('date,code,name,close\n20260916,005930,삼성전자,70000\n',
                    encoding='utf-8')

    with mock.patch('src.data.naver_api.stock_list', return_value=None):
        pairs = sim11_universe(seed_path=str(seed))

    assert pairs == [('005930', '삼성전자')], '네이버 실패 시 씨앗으로 안 떨어진다'


def test_the_top100_file_is_not_the_source_anymore(tmp_path):
    """씨앗 파일이 있어도 네이버가 응답하면 그쪽이 이긴다 — 그게 이 변경의 요점이다."""
    seed = tmp_path / 'ohlcv.csv'
    seed.write_text('date,code,name,close\n20260916,005930,삼성전자,70000\n',
                    encoding='utf-8')
    rows = [_row('999999', '새종목', 5_000_000_000)]

    with mock.patch('src.data.naver_api.stock_list', return_value=rows):
        pairs = sim11_universe(seed_path=str(seed))

    assert [c for c, _ in pairs] == ['999999']


def test_etfs_are_excluded_by_the_shared_fetcher():
    """ETF 제외는 naver_api가 한다(stock_only). 여기서 또 거르면 규칙이 둘로 갈린다."""
    with mock.patch('src.data.naver_api.stock_list', return_value=[]) as sl:
        sim11_universe(seed_path='/없는/경로.csv')
    assert sl.call_args.kwargs.get('stock_only', True) is not False


def test_sim11_runner_uses_the_new_universe():
    """함수를 만들어 놓고 _run_sim11이 안 부르면 아무 일도 안 일어난다."""
    import inspect

    from scripts import run_eod_sims
    src = inspect.getsource(run_eod_sims._run_sim11)
    assert 'sim11_universe' in src, '_run_sim11이 여전히 옛 씨앗만 쓴다'
