"""DART(OpenDART) 재무 — 심3 TTM 밸류·심11 성장률의 새 원천.

KIS 종목분석 7종이 2026-11-11 16:00에 막혀(FHKST66430300 → 404) 심3은 25,380
판정 전부 skip(`no_ttm_val`), 심11은 추세템플릿 통과분 100%가 `no_eps`가 됐다.

아래 숫자는 **합성이 아니다** — 2026-11-25에 OpenDART에서 실제로 받은 삼성전자
응답이다(2026 3분기 11014 / 2025 사업보고서 11011). 계산식은 기존 KIS 메서드가
쓰던 것과 같다: TTM = 최근분기누적 + (직전연간 − 직전년도 같은분기 누적).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data import dart_fundamentals as df


def _is(account_id, thstrm, add=None, frmtrm_q=None, frmtrm_add=None):
    row = {'sj_div': 'IS', 'account_id': account_id, 'thstrm_amount': thstrm}
    if add is not None:
        row['thstrm_add_amount'] = add
    if frmtrm_q is not None:
        row['frmtrm_q_amount'] = frmtrm_q
    if frmtrm_add is not None:
        row['frmtrm_add_amount'] = frmtrm_add
    return row


def _bs(account_id, thstrm):
    return {'sj_div': 'BS', 'account_id': account_id, 'thstrm_amount': thstrm}


# ── 삼성전자 2026 3분기 (실제 응답) ────────────────────────────
Q3_2026 = [
    _is('ifrs-full_BasicEarningsLossPerShare', '11462', add='29381',
        frmtrm_q='1802', frmtrm_add='3724'),
    _is('ifrs-full_Revenue', '195253209000000', add='500626123000000',
        frmtrm_q='', frmtrm_add='164148387000000'),
    _is('ifrs-full_ProfitLossAttributableToOwnersOfParent', '75208134000000',
        add='193578792000000'),
    _bs('ifrs-full_EquityAttributableToOwnersOfParent', '605443984000000'),
]

# ── 삼성전자 2025 사업보고서 (실제 응답) ───────────────────────
ANNUAL_2025 = [
    _is('ifrs-full_BasicEarningsLossPerShare', '6605'),
    _is('ifrs-full_Revenue', '333605938000000'),
    _is('ifrs-full_ProfitLossAttributableToOwnersOfParent', '44260956000000'),
    _bs('ifrs-full_EquityAttributableToOwnersOfParent', '424313255000000'),
]


# ── 핵심 계산 ────────────────────────────────────────────────
def test_eps_ttm_uses_the_prior_annual_to_close_the_year():
    """TTM = 최근분기누적 + (직전연간 − 직전년도 같은분기 누적).

    29,381 + (6,605 − 3,724) = 32,262. 누적만 쓰면 3분기치(29,381)를 1년으로
    오인하고, 직전연간만 쓰면 실적 개선이 반영되지 않아 **비싸 보여 걸러진다** —
    심3의 저평가 필터가 정확히 반대로 작동하는 그 편향이다.
    """
    out = df.derive(Q3_2026, ANNUAL_2025)
    assert out['eps_ttm'] == 32262.0


def test_growth_is_cumulative_versus_the_same_period_last_year():
    """성장률은 분기 단독이 아니라 누적 대 전년동기누적이다 — 계절성이 섞이지 않는다."""
    out = df.derive(Q3_2026, ANNUAL_2025)
    assert round(out['eps_growth_yoy'], 1) == 689.0      # 29381/3724
    assert round(out['revenue_growth_yoy'], 1) == 205.0  # 500626/164148


def test_bps_is_derived_without_a_share_count_call():
    """주식수를 따로 조회하지 않는다 — 같은 보고서 안에서 역산한다.

    주식수 = 지배주주순이익누적 / EPS누적 이므로
    BPS = 지배주주자본 × (EPS누적 / 지배주주순이익누적).

    ⚠ 근사다. EPS는 가중평균 보통주, 자본은 기말 지배주주지분이라 우선주·기중
    변동만큼 어긋난다(삼성전자에서 약 3%). 밸류 **필터**용으로만 쓴다 —
    가격 산정에 쓰지 않는다.
    """
    out = df.derive(Q3_2026, ANNUAL_2025)
    assert 85_000 < out['bps'] < 95_000


# ── 측정 불가를 지어내지 않는다 ──────────────────────────────
def test_missing_prior_annual_gives_no_eps_ttm():
    """연을 닫을 조각이 없으면 TTM을 만들지 않는다. 누적을 TTM으로 적으면
    3분기치가 1년으로 둔갑해 PER이 1/4로 보인다 — '싸다'는 오판이다."""
    out = df.derive(Q3_2026, [])
    assert 'eps_ttm' not in out
    assert 'eps_growth_yoy' in out, '성장률은 직전연간 없이도 낼 수 있다'


def test_zero_prior_period_gives_no_growth():
    """전년동기가 0이나 적자면 배수가 의미를 잃는다 → 측정 불가."""
    rows = [_is('ifrs-full_BasicEarningsLossPerShare', '100', add='300',
                frmtrm_add='0')]
    assert 'eps_growth_yoy' not in df.derive(rows, ANNUAL_2025)


def test_empty_response_yields_nothing():
    assert df.derive([], []) == {}


def test_annual_report_needs_no_prior_annual():
    """사업보고서(11011)에는 누적 필드가 없다 — 당기 금액이 곧 1년이다."""
    out = df.derive(ANNUAL_2025, [])
    assert out['eps_ttm'] == 6605.0


# ── 캐시와 후보 보강 ────────────────────────────────────────
def test_apply_sets_the_keys_sim3_and_sim11_actually_read(tmp_path):
    """심3·심11의 코드는 한 줄도 바꾸지 않는다. 심3은 후보에 실린
    `per_ttm`/`pbr_ttm`을 우선 쓰고, 심11은 `eps_growth_yoy`를 읽는다."""
    df.save_cache({'005930': {'eps_ttm': 32262.0, 'bps': 91892.0,
                              'eps_growth_yoy': 689.0,
                              'revenue_growth_yoy': 205.0}}, str(tmp_path))
    cands = [{'code': '005930', 'price': 100000}]
    applied, total = df.apply(cands, str(tmp_path))
    s = cands[0]
    assert (applied, total) == (1, 1)
    assert s['per_ttm'] == round(100000 / 32262.0, 2)
    assert s['pbr_ttm'] == round(100000 / 91892.0, 2)
    assert s['eps_growth_yoy'] == 689.0
    assert s['revenue_growth_yoy'] == 205.0


def test_apply_leaves_unknown_codes_alone(tmp_path):
    """캐시에 없는 종목은 건드리지 않는다 — 0을 넣으면 심3이 '싸다'로 읽는다."""
    df.save_cache({}, str(tmp_path))
    cands = [{'code': '000660', 'price': 200000}]
    applied, total = df.apply(cands, str(tmp_path))
    assert (applied, total) == (0, 1)
    assert 'per_ttm' not in cands[0] and 'eps_growth_yoy' not in cands[0]


def test_negative_eps_does_not_become_a_cheap_per(tmp_path):
    """적자 종목의 PER은 음수다. 그 값을 적으면 비교축이 깨지므로 넣지 않는다."""
    df.save_cache({'A': {'eps_ttm': -500.0, 'bps': 10000.0}}, str(tmp_path))
    cands = [{'code': 'A', 'price': 5000}]
    df.apply(cands, str(tmp_path))
    assert 'per_ttm' not in cands[0]
    assert cands[0]['pbr_ttm'] == 0.5, 'PBR은 자본 기준이라 적자와 무관하다'


def test_zero_price_yields_no_valuation(tmp_path):
    df.save_cache({'A': {'eps_ttm': 100.0, 'bps': 1000.0}}, str(tmp_path))
    cands = [{'code': 'A', 'price': 0}]
    df.apply(cands, str(tmp_path))
    assert 'per_ttm' not in cands[0] and 'pbr_ttm' not in cands[0]


def test_corrupted_cache_is_treated_as_empty(tmp_path):
    (tmp_path / df.CACHE_FILE).write_text('nope', encoding='utf-8')
    assert df.load_cache(str(tmp_path)) == {}


def test_growth_only_entry_still_serves_sim11(tmp_path):
    """직전연간을 못 받아 TTM이 없어도 심11은 성장률만으로 돈다."""
    df.save_cache({'A': {'eps_growth_yoy': 40.0, 'revenue_growth_yoy': 30.0}},
                  str(tmp_path))
    cands = [{'code': 'A', 'price': 1000}]
    applied, _ = df.apply(cands, str(tmp_path))
    assert applied == 1
    assert cands[0]['eps_growth_yoy'] == 40.0
    assert 'per_ttm' not in cands[0]


# ── 키는 레포에 두지 않는다 ─────────────────────────────────
def test_api_key_comes_from_the_environment(monkeypatch):
    """public 레포다 — 인증키는 GitHub Secrets·Vercel env에만 둔다."""
    monkeypatch.delenv('DART_API_KEY', raising=False)
    assert df.api_key() is None
    monkeypatch.setenv('DART_API_KEY', 'x' * 40)
    assert df.api_key() == 'x' * 40


def test_report_code_for_a_quarter():
    """분기 → reprt_code. 1Q 11013 / 2Q 11012 / 3Q 11014 / 4Q(연간) 11011."""
    assert df.reprt_code(1) == '11013'
    assert df.reprt_code(2) == '11012'
    assert df.reprt_code(3) == '11014'
    assert df.reprt_code(4) == '11011'


# ── 조회 ────────────────────────────────────────────────────
class _Res:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def test_fetch_without_a_key_makes_no_request(monkeypatch):
    """키가 없으면 네트워크를 건드리지 않는다 — 조용히 0을 만들지도 않는다."""
    calls = []
    monkeypatch.setattr(df.net, 'get', lambda *a, **k: calls.append(a) or None)
    monkeypatch.delenv('DART_API_KEY', raising=False)
    assert df.fetch('00126380', 2026, 3) == {}
    assert calls == []


def test_fetch_falls_back_to_separate_statements(monkeypatch):
    """연결재무제표(CFS)가 없는 회사는 개별(OFS)로 받는다 — 소형주에서 흔하다."""
    seen = []

    def fake_get(url, **kw):
        fs = kw['params']['fs_div']
        seen.append((kw['params']['bsns_year'], fs))
        if fs == 'CFS':
            return _Res({'status': '013', 'message': '조회된 데이타가 없습니다.'})
        return _Res({'status': '000', 'list': ANNUAL_2025})

    monkeypatch.setattr(df.net, 'get', fake_get)
    out = df.fetch('00126380', 2026, 4, key='k' * 40)
    assert out['eps_ttm'] == 6605.0
    assert ('2026', 'CFS') in seen and ('2026', 'OFS') in seen


def test_fetch_returns_nothing_when_the_report_is_missing(monkeypatch):
    monkeypatch.setattr(df.net, 'get', lambda url, **kw: _Res({'status': '013'}))
    assert df.fetch('00126380', 2026, 3, key='k' * 40) == {}


def test_fetch_tags_which_report_it_came_from(monkeypatch):
    """캐시가 낡았는지는 사람이 봐야 한다 — 출처 보고서를 같이 적는다."""
    def fake_get(url, **kw):
        year, rc = kw['params']['bsns_year'], kw['params']['reprt_code']
        if year == '2026' and rc == '11014':
            return _Res({'status': '000', 'list': Q3_2026})
        return _Res({'status': '000', 'list': ANNUAL_2025})

    monkeypatch.setattr(df.net, 'get', fake_get)
    out = df.fetch('00126380', 2026, 3, key='k' * 40)
    assert out['report'] == '2026-11014'
    assert out['eps_ttm'] == 32262.0


# ── 법인코드 매핑 ───────────────────────────────────────────
_XML = """<result>
<list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>
<stock_code>005930</stock_code><modify_date>20260101</modify_date></list>
<list><corp_code>00164779</corp_code><corp_name>SK하이닉스</corp_name>
<stock_code>000660</stock_code><modify_date>20260101</modify_date></list>
<list><corp_code>00999999</corp_code><corp_name>비상장법인</corp_name>
<stock_code> </stock_code><modify_date>20260101</modify_date></list>
</result>"""


def test_only_listed_companies_are_kept():
    """전체 12만 법인 중 상장사는 4천여 개다. stock_code 없는 것은 조회할
    종목코드가 없으므로 버린다 — 캐시가 30배로 불어나는 것을 막는다."""
    m = df.parse_corp_codes(_XML)
    assert m == {'005930': '00126380', '000660': '00164779'}


def test_corp_code_map_round_trips(tmp_path):
    df.save_corp_codes({'005930': '00126380'}, str(tmp_path))
    assert df.load_corp_codes(str(tmp_path)) == {'005930': '00126380'}


def test_missing_corp_code_map_is_empty_not_a_crash(tmp_path):
    assert df.load_corp_codes(str(tmp_path)) == {}


# ── 어느 보고서를 받을지 ────────────────────────────────────
def test_latest_report_follows_the_filing_deadlines():
    """분기보고서는 분기말 +45일, 사업보고서는 +90일까지 제출된다. 제출 전에
    조회하면 전 분기 자료를 '최신'으로 캐시해 분기 하나가 통째로 밀린다."""
    from datetime import date
    assert df.latest_report(date(2026, 11, 25)) == (2026, 3)   # 3Q 제출 직후
    assert df.latest_report(date(2026, 11, 1)) == (2026, 2)    # 아직 3Q 전
    assert df.latest_report(date(2026, 8, 20)) == (2026, 2)
    assert df.latest_report(date(2026, 6, 1)) == (2026, 1)
    assert df.latest_report(date(2026, 4, 10)) == (2025, 4)    # 사업보고서
    assert df.latest_report(date(2026, 2, 1)) == (2025, 3)     # 사업보고서 전


def test_apply_does_not_overwrite_values_already_on_the_candidate(tmp_path):
    """유니버스에 이미 값이 있으면 덮어쓰지 않는다 — `_enrich_universe`의 관례다.
    KIS 종목분석이 되살아나면 그 값이 이기고, 이 커밋이 동작을 조용히 바꾸지 않는다."""
    df.save_cache({'A': {'eps_ttm': 100.0, 'bps': 1000.0, 'eps_growth_yoy': 10.0}},
                  str(tmp_path))
    cands = [{'code': 'A', 'price': 1000, 'per_ttm': 7.77, 'eps_growth_yoy': 55.0}]
    df.apply(cands, str(tmp_path))
    assert cands[0]['per_ttm'] == 7.77
    assert cands[0]['eps_growth_yoy'] == 55.0
    assert cands[0]['pbr_ttm'] == 1.0, '없던 키는 채운다'


# ── 손익계산서를 단일 표시하는 회사 (2026-11-25 실측) ────────
def _cis(account_id, thstrm, add=None, frmtrm_add=None):
    row = {'sj_div': 'CIS', 'account_id': account_id, 'thstrm_amount': thstrm}
    if add is not None:
        row['thstrm_add_amount'] = add
    if frmtrm_add is not None:
        row['frmtrm_add_amount'] = frmtrm_add
    return row


def test_single_statement_companies_are_read_too():
    """SK하이닉스·NAVER·KB금융·신한지주·삼성바이오는 `IS`가 **없고** 포괄손익
    계산서(`CIS`)만 낸다. 삼성전자는 둘 다 내서, 삼성전자 픽스처만으로 만든
    코드는 초록인 채 유니버스의 절반 이상을 놓쳤다(실측 적중 5/12).
    """
    rows = [
        _cis('ifrs-full_BasicEarningsLossPerShare', '81000', add='243776',
             frmtrm_add='120000'),
        _cis('ifrs-full_Revenue', '80000000000000', add='236510516000000',
             frmtrm_add='150000000000000'),
        _cis('ifrs-full_ProfitLossAttributableToOwnersOfParent', '60000000000000',
             add='173684804000000'),
        _bs('ifrs-full_EquityAttributableToOwnersOfParent', '308494939000000'),
    ]
    out = df.derive(rows, [_cis('ifrs-full_BasicEarningsLossPerShare', '200000')])
    assert out['eps_ttm'] == 243776 + (200000 - 120000)
    assert round(out['eps_growth_yoy'], 1) == 103.1
    # 주식수 역산 = 173,684,804,000,000 / 243,776 ≒ 7.12억주 → BPS ≒ 43만원대
    assert 400_000 < out['bps'] < 450_000


def test_financial_holdings_have_no_revenue_tag():
    """은행·지주는 `ifrs-full_Revenue`를 안 쓴다(영업수익). 매출 성장률은
    측정 불가로 남고 심11이 `no_revenue`로 거른다 — 0을 넣지 않는다."""
    rows = [_cis('ifrs-full_BasicEarningsLossPerShare', '5000', add='15563',
                 frmtrm_add='12000')]
    out = df.derive(rows, [])
    assert 'revenue_growth_yoy' not in out
    assert 'eps_growth_yoy' in out


# ── 캐시 영속화의 원자성 (2026-11-27) ──────────────────────────────
# 첫 채움 런(45655655366)은 수집 119분 뒤 잡 타임아웃으로 취소됐다. 지금은 배포
# 스텝이 `git config`에 `--global`이 없어 exit 128로 죽기 때문에 그 결과가 db-data에
# 도달하지 못하는데, **그 한 줄을 고치는 순간** 다른 위험이 실현된다:
# `save_cache`가 `open(...,'w')`로 **먼저 잘라낸 뒤** `json.dump`하므로, 취소 신호가
# 그 창에 떨어지면 **잘린 JSON**이 남고 그게 push된다. `load_cache`는 예외를 삼켜
# `{}`를 돌려주므로(위 test_corrupted_cache_is_treated_as_empty) 다음 런은 조용히
# 0에서 다시 시작한다 — 한 분기의 수집이 통째로 사라진다.

def _boom(*a, **k):
    raise RuntimeError('쓰기 도중 죽는다')


def test_save_cache_does_not_destroy_the_previous_file_on_failure(tmp_path, monkeypatch):
    """쓰기가 실패해도 **이전 값이 그대로** 남아야 한다.

    잘린 파일보다 지난 분기 값이 낫다 — `report`가 낡은 채로 남으면 다음 런이
    다시 시도한다. 빈 `{}`는 그 재시도 경로마저 지운다.
    """
    df.save_cache({'005930': {'eps_ttm': 12372, 'report': '2026-11014'}},
                  str(tmp_path))
    before = (tmp_path / df.CACHE_FILE).read_bytes()
    monkeypatch.setattr(df.json, 'dump', _boom)
    try:
        df.save_cache({'005930': {'eps_ttm': 1}}, str(tmp_path))
    except RuntimeError:
        pass
    assert (tmp_path / df.CACHE_FILE).read_bytes() == before, '이전 캐시가 깨졌다'
    assert df.load_cache(str(tmp_path)), 'load_cache가 {}를 돌려주면 다음 런이 0에서 시작한다'


def test_save_corp_codes_does_not_destroy_the_previous_file_on_failure(tmp_path, monkeypatch):
    """법인코드 매핑도 같은 패턴이다 — 둘 다 db-data로 push된다."""
    df.save_corp_codes({'005930': '00126380'}, str(tmp_path))
    before = (tmp_path / df.CORP_CODES_FILE).read_bytes()
    monkeypatch.setattr(df.json, 'dump', _boom)
    try:
        df.save_corp_codes({'005930': 'X'}, str(tmp_path))
    except RuntimeError:
        pass
    assert (tmp_path / df.CORP_CODES_FILE).read_bytes() == before


def test_no_temp_file_is_left_behind(tmp_path):
    """임시 파일이 남으면 `git add -A data/`가 그걸 db-data에 올린다."""
    df.save_cache({'005930': {'report': 'x'}}, str(tmp_path))
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == [df.CACHE_FILE], f'군더더기 파일: {names}'


# ── 취소가 마지막 저장을 건너뛴다 ─────────────────────────────────
# 잡 타임아웃의 취소 신호는 `KeyboardInterrupt`(BaseException)로 들어온다. 수집
# 루프의 `except Exception`은 그걸 안 잡고, 그래서 루프 **뒤**의 최종
# `save_cache`(scripts/collect_dart_fundamentals.py)를 건너뛴다. 중간 저장이
# 50종목마다이므로 **최대 49종목이 매 런 버려진다**.

def test_cancellation_still_saves_what_was_collected(tmp_path, monkeypatch):
    import scripts.collect_dart_fundamentals as collect

    monkeypatch.chdir(tmp_path)
    (tmp_path / 'data').mkdir()
    # main()이 argparse를 쓰므로 pytest의 argv가 새어들면 SystemExit 2가 난다.
    monkeypatch.setattr(sys, 'argv', ['collect_dart_fundamentals.py'])
    monkeypatch.setattr(df, 'api_key', lambda: 'KEY')
    monkeypatch.setattr(df, 'load_corp_codes',
                        lambda d: {f'{i:06d}': f'c{i}' for i in range(5)})
    monkeypatch.setattr(collect, 'SLEEP_SEC', 0)

    seen = []

    def fetch(corp_code, year, quarter, key=None, **kw):
        seen.append(corp_code)
        if len(seen) == 3:            # 세 번째 종목에서 취소 신호가 온다
            raise KeyboardInterrupt
        return {'eps_ttm': 100, 'report': f'{year}-11014'}

    monkeypatch.setattr(df, 'fetch', fetch)
    try:
        collect.main()
    except (KeyboardInterrupt, SystemExit):
        pass

    cache = df.load_cache('data')
    assert len(cache) == 2, (
        f'취소 전에 모은 2종목이 저장돼야 한다 — 실제 {len(cache)}종목. '
        '중간 저장이 50종목마다이므로 이게 없으면 최대 49종목이 매 런 버려진다')


# ── 워크플로 배선 (돈이 아니라 배달 경로다) ────────────────────────

def _dart_yml() -> str:
    path = os.path.join(os.path.dirname(__file__), '..',
                        '.github', 'workflows', 'dart_fundamentals.yml')
    with open(path, encoding='utf-8') as f:
        return f.read()


def test_git_identity_is_global_so_the_fresh_clone_inherits_it():
    """`git config`가 로컬이면 **새 clone에는 ident가 없다**.

    2026-11-25 첫 채움 런이 `fatal: empty ident name` → exit 128로 죽었다.
    수집이 아무리 성공해도 파일이 db-data에 한 바이트도 올라가지 않는다 —
    심3·심11이 거래 0건인 직접 원인이다. trading.yml·eod_data.yml·
    token_refresh.yml은 전부 `--global`을 쓴다. 이 파일만 어긋나 있었다.
    """
    body = _dart_yml()
    assert 'git config --global user.name' in body
    assert 'git config --global user.email' in body


def test_collector_output_is_unbuffered():
    """버퍼링되면 타임아웃에 잘린 런의 로그가 **한 줄도** 안 남는다.

    진행 출력은 50종목당 1줄(약 60~75B)이라 4,000종목을 돌아도 파이썬 블록
    버퍼 8,192B를 한 번도 못 채운다 — 영원히 flush되지 않는다. 그래서 119분
    동안 몇 종목이 처리됐는지 알 수 없었고, 벽시계 예산을 설계할 근거가
    생기지 않았다. 레포의 다른 워크플로는 전부 `-u`를 쓴다.
    """
    assert 'python -u scripts/collect_dart_fundamentals.py' in _dart_yml()
