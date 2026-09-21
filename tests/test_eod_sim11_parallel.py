"""심11 EOD 후보 조회를 병렬로 한다 — 315종목이 600초 예산 안에 들어가야 한다.

2026-09-21 실측: 종목당 ~4초(순차 5콜 × 미국 러너→KIS 왕복 ~0.8초). S1 커밋의 근거
"100종목 109초"는 틀린 측정이었고(09-15 스텝 소요 385~413초), 315종목은 ~21분이라
20분 잡에 못 들어갔다. 600초 예산은 매일 같은 코드순 뒤쪽 절반을 버렸다.

비용이 페이싱이 아니라 왕복 지연이라 병렬화가 맞다. 4스레드 × 5콜/4초 ≈ 초당 5콜로
KIS 유량제한(20건/초)의 1/4이다.

일봉·실적 조회는 디스크 캐시 **전체**를 매번 같은 파일에 다시 쓴다(315종목이면 9MB,
누적 ~169초). EOD는 그 파일을 다시 안 읽으므로 저장을 끈 제공자를 쓴다 — 그러면 병렬
경합도 없다. 공유 제공자의 기본 동작(실전 경로)은 그대로다.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.run_eod_sims import candidates_from_kis_live  # noqa: E402

TODAY = time.strftime('%Y%m%d')
HIST = [{'date': f'2020{i:05d}', 'close': 100.0 + i, 'amount': 1_000_000_000} for i in range(230)]


class _SlowKis:
    """호출마다 지연 — 왕복 지연을 흉내낸다."""

    def __init__(self, delay=0.05):
        self.delay = delay

    def get_daily_history(self, code, days=230):
        time.sleep(self.delay)
        return HIST

    def get_price_quote(self, code):
        time.sleep(self.delay)
        return {'price': 500.0, 'amount': 2e9, 'w52_hgpr': 600, 'w52_lwpr': 300}

    def get_earnings_growth(self, code):
        time.sleep(self.delay)
        return {'eps_growth_yoy': 25.0}


PAIRS = [(f'{i:06d}', f'종목{i}') for i in range(12)]


def test_병렬이면_전_종목을_입력_순서대로_돌려준다():
    out = candidates_from_kis_live(PAIRS, _SlowKis(), log=lambda *_: None,
                                   pace_interval=0, workers=4)
    assert [c['code'] for c in out] == [c for c, _ in PAIRS]


def test_병렬이_순차보다_빠르다():
    t0 = time.monotonic()
    candidates_from_kis_live(PAIRS, _SlowKis(), log=lambda *_: None, pace_interval=0, workers=1)
    serial = time.monotonic() - t0
    t0 = time.monotonic()
    candidates_from_kis_live(PAIRS, _SlowKis(), log=lambda *_: None, pace_interval=0, workers=4)
    parallel = time.monotonic() - t0
    assert parallel < serial / 2, f'순차 {serial:.2f}초 vs 병렬 {parallel:.2f}초'


def test_배치는_파일_저장을_끈_제공자로_병렬_조회한다(monkeypatch):
    """저장을 켠 채 병렬로 돌면 스레드들이 같은 캐시 파일을 동시에 다시 쓴다."""
    import scripts.run_eod_sims as eod
    from src.trade import kis_data_provider
    made, seen = {}, {}

    class _Provider:
        def __init__(self, **kw):
            made.update(kw)

    def fake_live(pairs, kis, log=print, **kw):
        seen.update(kw)
        return []

    monkeypatch.setattr(eod, 'sim11_universe', lambda seed_path: PAIRS)
    monkeypatch.setattr(eod, 'load_sim11_holdings', lambda: {})
    monkeypatch.setattr(eod, 'load_previous_sim11_watchlist', lambda: [])
    monkeypatch.setattr(kis_data_provider, 'KISDataProvider', _Provider)
    monkeypatch.setattr(eod, 'candidates_from_kis_live', fake_live)
    eod._run_sim11('없음.csv')
    assert made == {'persist_disk_cache': False}
    assert seen.get('workers', 1) > 1


def test_예산이_다하면_남은_종목을_건너뛴다():
    logs = []
    out = candidates_from_kis_live(PAIRS, _SlowKis(delay=0.1), log=logs.append,
                                   pace_interval=0, workers=2, budget_sec=0.25)
    assert 0 < len(out) < len(PAIRS)
    assert any('예산' in m for m in logs)
