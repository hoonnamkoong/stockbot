"""심11 EOD 조회 결손을 조용히 넘기지 않는다 — 세고, 한 번 되살리고, 넘치면 알린다.

2026-09-21까지 후보 조회는 실패(빈 응답·예외)와 이력 부족(신규 상장)을 똑같이
`continue`로 버렸고, KIS 거부는 (TR, 코드)당 첫 한 번만 찍혀 몇 번 났는지 셀 수
없었다. 09-18 로그의 `[KIS 거부] FHKST03010100 HTTP 500` 한 줄이 몇 종목이었는지
지금도 모른다. #133(4병렬)이 유량제한에 걸려도 똑같이 조용했을 것이다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import scripts.run_eod_sims as eod  # noqa: E402
from scripts.run_eod_sims import candidates_from_kis_live  # noqa: E402

HIST = [{'date': f'2020{i:05d}', 'close': 100.0 + i, 'amount': 1e9} for i in range(230)]
SHORT = HIST[:100]


class _Kis:
    """codes별 일봉 응답 순서를 준다. 목록이 다 떨어지면 마지막 것을 반복한다."""

    def __init__(self, plan):
        self.plan = {c: list(v) for c, v in plan.items()}
        self.hist_calls = {}

    def get_daily_history(self, code, days=230):
        self.hist_calls[code] = self.hist_calls.get(code, 0) + 1
        seq = self.plan.get(code, [HIST])
        got = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(got, Exception):
            raise got
        return got

    def get_price_quote(self, code):
        return {'price': 500.0, 'amount': 2e9, 'w52_hgpr': 600, 'w52_lwpr': 300}

    def get_earnings_growth(self, code):
        return {}


def _run(kis, pairs, **kw):
    stats = {}
    out = candidates_from_kis_live(pairs, kis, log=lambda *_: None, pace_interval=0,
                                   stats=stats, **kw)
    return out, stats


def test_일시적_실패는_한_번_더_조회해_살린다():
    kis = _Kis({'000001': [[], HIST], '000002': [RuntimeError('HTTP 500'), HIST]})
    out, stats = _run(kis, [('000001', 'A'), ('000002', 'B'), ('000003', 'C')], workers=2)
    assert sorted(c['code'] for c in out) == ['000001', '000002', '000003']
    assert stats['failed'] == 0 and stats['recovered'] == 2


def test_재시도_뒤에도_실패면_실패로_센다():
    kis = _Kis({'000001': [[]]})
    out, stats = _run(kis, [('000001', 'A'), ('000002', 'B')])
    assert [c['code'] for c in out] == ['000002']
    assert stats['failed'] == 1 and kis.hist_calls['000001'] == 2


def test_이력_부족은_실패가_아니고_재시도도_안_한다():
    """신규 상장처럼 정상적으로 짧은 이력 — 다시 불러도 똑같다."""
    kis = _Kis({'000001': [SHORT]})
    out, stats = _run(kis, [('000001', 'A')])
    assert out == [] and stats['short_history'] == 1 and stats['failed'] == 0
    assert kis.hist_calls['000001'] == 1


def test_통계는_대상과_후보를_같이_준다():
    out, stats = _run(_Kis({}), [('000001', 'A'), ('000002', 'B')])
    assert stats['target'] == 2 and stats['candidates'] == 2 and stats['skipped_budget'] == 0


# ── KIS 거부 횟수 ─────────────────────────────────────────────────

def test_거부는_출력은_한_번이지만_횟수는_전부_센다(capsys):
    from src.trade.kis_data_provider import KISDataProvider
    KISDataProvider.reject_counts.clear()
    KISDataProvider._logged_rejects.discard(('TR_TEST', 'HTTP 500'))
    for _ in range(3):
        KISDataProvider._log_reject('TR_TEST', 'HTTP 500', '')
    assert KISDataProvider.reject_counts[('TR_TEST', 'HTTP 500')] == 3
    assert capsys.readouterr().out.count('[KIS 거부] TR_TEST') == 1


# ── 알림 판정 ────────────────────────────────────────────────────

def _stats(**kw):
    s = {'target': 300, 'candidates': 290, 'short_history': 10, 'failed': 0,
         'recovered': 0, 'skipped_budget': 0}
    s.update(kw)
    return s


def test_건강하면_알리지_않는다():
    assert eod.sim11_fetch_problems(_stats(), {}) == []


def test_예산_소진은_알린다():
    assert eod.sim11_fetch_problems(_stats(skipped_budget=40), {})


def test_실패가_5퍼센트를_넘으면_알린다():
    assert eod.sim11_fetch_problems(_stats(failed=16), {})
    assert eod.sim11_fetch_problems(_stats(failed=15), {}) == []


def test_유량제한은_한_건이어도_알린다():
    assert eod.sim11_fetch_problems(_stats(), {('FHKST03010100', 'EGW00201'): 1})


def test_심_실행_스텝에_텔레그램_자격증명이_있다():
    """없으면 알림 코드가 돌아도 아무도 못 받는다."""
    import re
    wf = open(os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows',
                           'eod_data.yml'), encoding='utf-8').read()
    step = re.search(r'Run EOD simulators.+?(?=\n      - name: )', wf, re.S).group(0)
    assert 'TELEGRAM_BOT_TOKEN' in step and 'TELEGRAM_CHAT_ID' in step
