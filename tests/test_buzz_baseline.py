"""버즈 기준선 누적 저장소.

2026-11-24: 심1의 "평상시 대비 2.2배" 게이트는 배포 이래 죽어 있었다 —
`avg_posts`가 라이브 diag 37,032행 전부 1.0이라 `buzz_ratio == posts`였고,
남은 절대 개수 조건이 대형주 필터가 돼 진입 18건 중 12건이 삼성전자였다.
원인은 **단계 순서**다: Stage 3이 심을 돌리고 Stage 4의 notifier가 그 키를 만든다.

이 저장소는 그 순서 함정을 **설계로 제거한다** — 기준선은 항상 **오늘을 뺀**
이전 거래일들에서 계산되므로, 쓰기와 읽기의 순서가 결과를 바꾸지 않는다
(test_order_of_record_and_apply_does_not_matter).
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data import buzz_baseline as bb


def _cand(code, posts):
    return {'code': code, 'name': f'종목{code}', 'recent_posts_count': posts}


def _seed(tmp_path, code, pairs):
    """{날짜: 글수} 이력을 직접 심는다."""
    (tmp_path / bb.FILENAME).write_text(
        json.dumps({'codes': {code: dict(pairs)}}), encoding='utf-8')


# ── 오늘을 뺀다 ────────────────────────────────────────────
def test_today_is_excluded_from_the_baseline(tmp_path):
    """오늘의 폭발이 자기 기준선을 희석하면 비율이 1에 수렴한다.

    notifier의 `avg_posts`가 정확히 그 모양이었다 — sparkline_posts에 오늘을
    append한 뒤 평균을 냈다. 삼성전자는 [800,800,800,800,800]이라 평균 800,
    글 800 → 배수 1.0이다. 폭발 탐지기는 '전'을 기준으로 재야 한다.
    """
    _seed(tmp_path, '005930', [(f'2026-11-1{d}', 100) for d in range(5)])
    cands = [_cand('005930', 800)]
    bb.record(cands, '2026-11-20', str(tmp_path))
    bb.apply(cands, '2026-11-20', str(tmp_path))
    assert cands[0]['avg_posts'] == 100.0


def test_fewer_than_min_days_gives_no_baseline(tmp_path):
    """표본이 얇으면 기준선을 **주지 않는다**. 지어낸 값보다 '측정 불가'가 낫다."""
    _seed(tmp_path, 'A', [('2026-11-18', 10), ('2026-11-19', 20)])
    cands = [_cand('A', 500)]
    bb.apply(cands, '2026-11-20', str(tmp_path))
    assert 'avg_posts' not in cands[0]


def test_only_the_window_is_averaged(tmp_path):
    """창 밖의 오래된 날은 평균에 들어가지 않는다 — '평상시'는 최근이다."""
    old = [(f'2026-10-0{d}', 1000) for d in range(1, 6)]
    recent = [(f'2026-11-1{d}', 10) for d in range(5)]
    _seed(tmp_path, 'A', old + recent)
    cands = [_cand('A', 100)]
    bb.apply(cands, '2026-11-20', str(tmp_path))
    assert cands[0]['avg_posts'] == 10.0


# ── 누적 파일의 안전성 ──────────────────────────────────────
def test_same_day_rewrite_keeps_one_value_per_day(tmp_path):
    """사이클마다 불린다. 하루에 한 칸이어야 하고, 글 수는 장중 누적이므로
    마지막 값(그 날 총계에 가장 가까운 값)이 남는다."""
    cands = [_cand('A', 10)]
    bb.record(cands, '2026-11-20', str(tmp_path))
    bb.record([_cand('A', 55)], '2026-11-20', str(tmp_path))
    store = bb.load(str(tmp_path))
    assert store['codes']['A'] == {'2026-11-20': 55.0}


def test_record_merges_into_existing_file(tmp_path):
    """누적 파일은 **먼저 읽고** 써야 한다. 새로 시작하면 매 런 잘린다
    (배포 목록과 복원 목록이 갈렸을 때 심9-1 매매기록 8건이 2행으로 줄었던
    그 사고와 같은 모양이다)."""
    _seed(tmp_path, 'A', [('2026-11-18', 7)])
    bb.record([_cand('B', 3)], '2026-11-20', str(tmp_path))
    store = bb.load(str(tmp_path))
    assert store['codes']['A'] == {'2026-11-18': 7}
    assert store['codes']['B'] == {'2026-11-20': 3.0}


def test_old_dates_and_empty_codes_are_pruned(tmp_path):
    """후보 유니버스는 매일 바뀐다. 쌓이는 걸 안 걷으면 파일이 무한 증식한다."""
    _seed(tmp_path, 'STALE', [('2026-01-02', 5)])
    bb.record([_cand('A', 1)], '2026-11-20', str(tmp_path))
    store = bb.load(str(tmp_path))
    assert 'STALE' not in store['codes'], '창을 완전히 벗어난 코드는 사라져야 한다'
    assert len(store['codes']['A']) == 1


def test_corrupted_file_is_treated_as_empty(tmp_path):
    """깨진 파일에 죽지 않는다 — 기준선이 없는 것과 같게 다룬다(fail-closed)."""
    (tmp_path / bb.FILENAME).write_text('{{{ not json', encoding='utf-8')
    cands = [_cand('A', 100)]
    bb.record(cands, '2026-11-20', str(tmp_path))
    bb.apply(cands, '2026-11-20', str(tmp_path))
    assert 'avg_posts' not in cands[0]


def test_missing_file_is_treated_as_empty(tmp_path):
    assert bb.load(str(tmp_path)) == {'codes': {}}


# ── 구조적 성질: 순서가 결과를 바꾸지 않는다 ──────────────────
def test_order_of_record_and_apply_does_not_matter(tmp_path):
    """원래 버그는 '생산자가 소비자보다 뒤 단계'였다. 오늘을 빼고 계산하면
    그 순서가 무의미해진다 — 같은 자리에서 둘을 불러도 안전하다."""
    hist = [(f'2026-11-1{d}', 40) for d in range(5)]

    _seed(tmp_path, 'A', hist)
    a = [_cand('A', 900)]
    bb.record(a, '2026-11-20', str(tmp_path))
    bb.apply(a, '2026-11-20', str(tmp_path))

    d2 = tmp_path / 'other'
    d2.mkdir()
    _seed(d2, 'A', hist)
    b = [_cand('A', 900)]
    bb.apply(b, '2026-11-20', str(d2))
    bb.record(b, '2026-11-20', str(d2))

    assert a[0]['avg_posts'] == b[0]['avg_posts'] == 40.0
    assert bb.load(str(tmp_path)) == bb.load(str(d2))


def test_apply_reports_how_many_got_a_baseline(tmp_path):
    """몇 개가 측정 가능했는지는 로그로 보여야 한다 — 0이면 심1이 전량 스킵한다."""
    _seed(tmp_path, 'A', [(f'2026-11-1{d}', 10) for d in range(5)])
    cands = [_cand('A', 1), _cand('NEW', 1)]
    applied, total = bb.apply(cands, '2026-11-20', str(tmp_path))
    assert (applied, total) == (1, 2)


# ── 심1과의 접점 ────────────────────────────────────────────
def test_constant_large_cap_buzz_fails_the_ratio_gate(tmp_path):
    """삼성전자 재현: 평소에도 800개면 800개는 폭발이 아니다.

    진입 18건 중 12건이 이 종목이었던 이유가 이 배수가 계산되지 않았기
    때문이다. 기준선이 들어오면 배수는 1.0이고 심1의 문턱 밑이다.
    """
    from src.strategy.simulators.sim1_psych import BUZZ_RATIO_MIN
    _seed(tmp_path, '005930', [(f'2026-11-1{d}', 800) for d in range(5)])
    cands = [_cand('005930', 800)]
    bb.apply(cands, '2026-11-20', str(tmp_path))
    ratio = cands[0]['recent_posts_count'] / cands[0]['avg_posts']
    assert ratio == 1.0
    assert ratio < BUZZ_RATIO_MIN


def test_all_zero_history_is_unmeasurable_not_infinite(tmp_path):
    """평소 글이 0인 판에 오늘 500개 — 배수로는 무한이다.

    이게 심1이 노리는 가장 순수한 '관심 폭발'인데, 비율로는 표현할 수 없다.
    여기에 1.0 같은 바닥값을 두면 방금 제거한 `or 1` 폴백이 그대로 돌아온다
    (글 수가 곧 배수가 되고 대형주 필터가 된다). 그래서 **측정 불가**로 둔다 —
    문턱이 아니라 전략 결정이므로 사용자 판단 전까지 지어내지 않는다.
    """
    _seed(tmp_path, 'DEAD', [(f'2026-11-1{d}', 0) for d in range(5)])
    cands = [_cand('DEAD', 500)]
    applied, total = bb.apply(cands, '2026-11-20', str(tmp_path))
    assert 'avg_posts' not in cands[0]
    assert (applied, total) == (0, 1)


# ── Stage 3 배선 ────────────────────────────────────────────
class _Ctx:
    cycle_id = 777

    def __init__(self, now, data_dir):
        self.now_kst = now
        self._report_data_dir = data_dir
        self.logs = []

    def is_buy_window(self):
        return True

    def is_market_hours(self):
        return False

    def log(self, msg):
        self.logs.append(msg)


def test_stage3_hands_the_baseline_to_both_paths(tmp_path, monkeypatch):
    """배선이 사라지면 이 테스트가 잡는다. 그리고 **실전·페이퍼가 같은 리스트**를
    받는지도 본다 — `apply`가 제자리 보강이라 그 동일성이 파리티의 근거다.

    심1은 `tradeable: true`다. 페이퍼만 기준선을 받고 실전이 못 받으면
    "심 선택 = 실전 정확히 동일 동작"이 깨진다.
    """
    from datetime import datetime
    from unittest import mock

    from src.data.schemas import StockData
    from src.pipeline.workers.trade_engine import TradeEngineWorker

    monkeypatch.chdir(tmp_path)
    bb.save({'codes': {'005930': {f'2026-11-1{d}': 50 for d in range(5)}}},
            str(tmp_path / 'data'))

    ctx = _Ctx(datetime(2026, 11, 20, 13, 0), str(tmp_path))
    w = TradeEngineWorker(ctx, mock.MagicMock())
    stocks = [StockData(code='005930', name='삼성전자', price=10000,
                        recent_posts_count=800, fact_score=0.9, tick_power=150.0)]
    sync_state = mock.MagicMock(daily_deep_dive_codes=[], daily_reported_info=[],
                                morning_reported_info=[], afternoon_reported_info=[])

    with mock.patch('src.strategy.engine.StrategyEngine') as MockEngine, \
         mock.patch.object(w, '_run_simulators') as run_sims, \
         mock.patch('src.pipeline.workers.program_trader.run_program_trading') as prog:
        MockEngine.return_value.execute_simulation.return_value = [
            {'code': '005930', 'name': '삼성전자', 'signal': 'BUY', 'reason': 't'}]
        w.run(stocks, sync_state, skip_program_trading=False)

    paper = run_sims.call_args.args[0]
    assert paper[0]['avg_posts'] == 50.0, '후보에 기준선이 붙어야 한다'
    assert prog.call_args.args[0] is paper, '실전 경로가 같은 리스트를 받아야 한다'


def test_stage3_records_todays_count(tmp_path, monkeypatch):
    """내일의 기준선은 오늘 적어두지 않으면 생기지 않는다."""
    from datetime import datetime
    from unittest import mock

    from src.data.schemas import StockData
    from src.pipeline.workers.trade_engine import TradeEngineWorker

    monkeypatch.chdir(tmp_path)
    ctx = _Ctx(datetime(2026, 11, 20, 13, 0), str(tmp_path))
    w = TradeEngineWorker(ctx, mock.MagicMock())
    stocks = [StockData(code='005930', name='삼성전자', price=10000,
                        recent_posts_count=800)]
    sync_state = mock.MagicMock(daily_deep_dive_codes=[], daily_reported_info=[],
                                morning_reported_info=[], afternoon_reported_info=[])

    with mock.patch('src.strategy.engine.StrategyEngine') as MockEngine, \
         mock.patch.object(w, '_run_simulators'):
        MockEngine.return_value.execute_simulation.return_value = []
        w.run(stocks, sync_state, skip_program_trading=True)

    assert bb.load(str(tmp_path / 'data'))['codes']['005930'] == {'2026-11-20': 800.0}
