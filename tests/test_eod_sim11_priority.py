"""심11 EOD 배치가 예산에 잘려도 보유 종목의 청산 지표는 잃지 않는다.

2026-09-21 실측: S1(d00f61d2e)로 유니버스가 100 → ~315종목이 됐는데 종목당
조회가 예상(1.1초)의 4배(3.8~4.5초)라 600초 예산(abf4974f1)에서 절반이 잘렸다.
유니버스는 코드순이라 **매일 같은 뒤쪽 절반**(09-18: 000070~017800만 처리)이
빠졌고, 그 안에 심11 보유 종목 한화생명(088350)이 있었다 — 감시 목록 0종목,
그 종목의 50일선 이탈 청산 지표 없음.

게다가 EOD 복원 스텝이 `sim_minervini_state.json`을 가져오지 않아, 09-15에 넣은
"자격 잃은 보유 종목에 ma50만 싣기"(ac8b99fee)는 운영에서 한 번도 돌지 않았다
(런마다 `[EOD] 심11 상태를 못 읽었다(FileNotFoundError …)`).
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.run_eod_sims import load_previous_sim11_watchlist, prioritize_sim11_pairs  # noqa: E402

WF = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows', 'eod_data.yml')


# ── 조회 순서 ──────────────────────────────────────────────────────

UNIVERSE = [('000070', '삼양홀딩스'), ('017800', '현대엘리베이'), ('088350', '한화생명'),
            ('352820', '하이브')]


def test_holdings_are_fetched_first():
    pairs = prioritize_sim11_pairs(UNIVERSE, held={'088350': '한화생명'}, previous=[])
    assert pairs[0] == ('088350', '한화생명')
    assert sorted(pairs) == sorted(UNIVERSE), '순서만 바뀌고 종목 구성은 그대로여야 한다'


def test_holding_outside_the_universe_is_still_fetched():
    """유동성·시총 밖으로 밀려난 보유 종목도 청산은 해야 한다."""
    pairs = prioritize_sim11_pairs(UNIVERSE, held={'999990': '밀려난종목'}, previous=[])
    assert pairs[0] == ('999990', '밀려난종목')
    assert len(pairs) == len(UNIVERSE) + 1


def test_previous_watchlist_comes_next_but_only_if_still_in_universe():
    """직전 감시 목록은 매수 후보라 유니버스 필터를 다시 통과해야 한다."""
    pairs = prioritize_sim11_pairs(UNIVERSE, held={'088350': '한화생명'},
                                   previous=['352820', '999990'])
    assert [c for c, _ in pairs[:2]] == ['088350', '352820']
    assert '999990' not in dict(pairs)


def test_no_duplicates_when_held_is_also_on_previous_watchlist():
    pairs = prioritize_sim11_pairs(UNIVERSE, held={'088350': '한화생명'}, previous=['088350'])
    codes = [c for c, _ in pairs]
    assert len(codes) == len(set(codes))


# ── 직전 감시 목록 읽기 ────────────────────────────────────────────

def test_previous_watchlist_codes_are_read(tmp_path):
    p = tmp_path / 'sim11_watchlist.json'
    p.write_text(json.dumps({'date': '20260917',
                             'entries': {'088350': {'name': '한화생명'}}}), encoding='utf-8')
    assert load_previous_sim11_watchlist(str(p)) == ['088350']


def test_missing_previous_watchlist_is_empty(tmp_path):
    """직전 목록은 순서 힌트일 뿐이다 — 없다고 배치를 멈추지 않는다."""
    assert load_previous_sim11_watchlist(str(tmp_path / '없음.json')) == []


# ── 워크플로 배선 ──────────────────────────────────────────────────

def _restore_block():
    with open(WF, encoding='utf-8') as f:
        m = re.search(r'Run EOD simulators.+?(?=\n      - name: )', f.read(), re.S)
    assert m, '상태 복원 스텝을 못 찾았다 — 워크플로 구조가 바뀌었다'
    return m.group(0)


def test_sim11_state_is_restored_before_the_batch():
    assert 'state_repo/data/sim_minervini_state.json' in _restore_block(), (
        '심11 상태를 복원하지 않는다 — 보유 종목을 몰라 50일선 이탈 청산 지표가 안 실린다')


def test_previous_sim11_watchlist_is_restored_before_the_batch():
    assert 'state_repo/data/sim11_watchlist.json' in _restore_block(), (
        '직전 심11 감시 목록을 복원하지 않는다 — 우선 조회 순서를 만들 수 없다')
