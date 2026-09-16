# -*- coding: utf-8 -*-
"""그림자 운전(이관 3단계) 판단 일치율 계산기.

이 계산기가 없으면 "결정 불일치 0"을 **잴 수가 없고**, 잴 수 없는 게이트는
게이트가 아니다(`src/data/decision_log.py` 모듈 독스트링과 같은 이유).

여기서 고정하는 것은 세 가지다.
  1. `input_hash`가 같은 쌍만 판단 비교에 넣는다 — 다르면 시세가 달랐던 것이고
     그건 판단 불일치가 아니다.
  2. 평가에 도달하지 못한 행(`seen`)은 일치율에 넣지 않는다 — 아무도 판단하지
     않은 쌍으로 일치율을 채우면 100%가 만들어진다.
  3. 비교할 게 없으면 **0도 100%도 말하지 않는다.** "비교 불가"를 말한다.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.compare_shadow_decisions import (  # noqa: E402
    compare, format_report, load_rows, runners_present)


def _row(code, decision, *, sim='Sim1', cycle_id='7', ih='aaa', reason=''):
    return {'cycle_id': cycle_id, 'ts': '2026-09-16 10:00:00', 'runner': 'x',
            'sim': sim, 'code': code, 'decision': decision, 'reason': reason,
            'input_hash': ih}


# ── 일치/불일치 판정 ──────────────────────────────────────────────

def test_같은_입력_같은_결정은_일치다():
    base = [_row('000660', 'entry'), _row('005930', 'skip', reason='low_amount')]
    rep = compare(base, list(base))
    assert rep['comparable'] == 2
    assert rep['agree'] == 2 and rep['disagree'] == 0
    assert rep['rate'] == 1.0


def test_같은_입력_다른_결정은_불일치다():
    base = [_row('000660', 'entry'), _row('005930', 'skip', reason='low_amount')]
    shadow = [_row('000660', 'entry'), _row('005930', 'entry', reason='entry')]
    rep = compare(base, shadow)
    assert rep['comparable'] == 2
    assert rep['disagree'] == 1
    assert rep['rate'] == 0.5


def test_불일치를_심별로_센다():
    base = [_row('A', 'entry', sim='Sim1'), _row('B', 'entry', sim='Sim4')]
    shadow = [_row('A', 'skip', sim='Sim1'), _row('B', 'entry', sim='Sim4')]
    rep = compare(base, shadow)
    assert rep['by_sim']['Sim1']['disagree'] == 1
    assert rep['by_sim']['Sim4']['disagree'] == 0
    assert rep['by_sim']['Sim4']['agree'] == 1


def test_불일치를_사유별로_센다():
    """어떤 사유에서 갈리는지가 고칠 곳을 가리킨다."""
    base = [_row('A', 'entry', reason='entry'), _row('B', 'entry', reason='entry')]
    shadow = [_row('A', 'skip', reason='low_tick'), _row('B', 'skip', reason='low_tick')]
    rep = compare(base, shadow)
    assert rep['by_reason']['entry:entry → skip:low_tick'] == 2


# ── input_hash: 판단 불일치와 입력 불일치를 가른다 ────────────────

def test_입력_해시가_다르면_판단_비교에서_뺀다():
    """둘이 다른 시세를 봤다는 뜻이라 판단 불일치가 아니다. 다만 **따로 센다** —
    이게 0이 아니면 그림자 비교 자체가 성립하지 않는다."""
    base = [_row('000660', 'entry', ih='aaa')]
    shadow = [_row('000660', 'skip', ih='bbb')]
    rep = compare(base, shadow)
    assert rep['input_mismatch'] == 1
    assert rep['comparable'] == 0
    assert rep['disagree'] == 0
    assert rep['rate'] is None, '비교한 쌍이 없으면 일치율은 측정 불가다'


# ── 평가 미도달(seen)은 일치율을 부풀린다 ────────────────────────

def test_평가_미도달은_일치율에서_빠진다():
    """`seen`은 '판단했다'가 아니라 '평가에 도달하지 못했다'다(조기종료).
    양쪽 다 seen인 쌍을 일치로 세면 아무도 판단하지 않은 행으로 100%가 만들어진다."""
    base = [_row('A', 'seen'), _row('B', 'entry')]
    shadow = [_row('A', 'seen'), _row('B', 'entry')]
    rep = compare(base, shadow)
    assert rep['not_evaluated'] == 1
    assert rep['comparable'] == 1, 'seen 쌍은 분모에서 빠진다'
    assert rep['rate'] == 1.0


def test_한쪽만_seen이어도_불일치로_세지_않는다():
    base = [_row('A', 'seen')]
    shadow = [_row('A', 'skip', reason='low_amount')]
    rep = compare(base, shadow)
    assert rep['not_evaluated'] == 1
    assert rep['disagree'] == 0
    assert rep['rate'] is None


# ── 조인 결손 ────────────────────────────────────────────────────

def test_한쪽에만_있는_결정은_따로_센다():
    base = [_row('A', 'entry'), _row('B', 'skip')]
    shadow = [_row('A', 'entry'), _row('C', 'skip')]
    rep = compare(base, shadow)
    assert rep['base_only'] == 1 and rep['shadow_only'] == 1
    assert rep['comparable'] == 1


def test_cycle_id가_비면_키가_겹쳐_비교하지_않는다():
    """cycle_id 결손은 실제로 있다(격자 밖 경로는 빈칸으로 남긴다). 그때
    (cycle_id, sim, code)가 사이클마다 충돌하므로 **아무 행이나 골라 비교하면
    안 된다** — 모호로 빼내고 그 건수를 보고한다."""
    base = [_row('A', 'entry', cycle_id=''), _row('A', 'skip', cycle_id='')]
    shadow = [_row('A', 'entry', cycle_id=''), _row('A', 'skip', cycle_id='')]
    rep = compare(base, shadow)
    assert rep['ambiguous'] == 1
    assert rep['comparable'] == 0
    assert rep['rate'] is None


# ── 데이터가 없을 때: 0도 100%도 말하지 않는다 ───────────────────

def test_데이터가_없으면_일치율은_측정_불가다():
    rep = compare([], [])
    assert rep['rate'] is None
    assert rep['base_n'] == 0 and rep['shadow_n'] == 0


def test_리포트는_0건을_100퍼센트로_말하지_않는다():
    rep = compare([_row('A', 'entry')], [])
    text = format_report('20260916', rep, 'actions-trading', 'phone')
    assert '비교 불가' in text
    assert '0건' in text
    assert '100' not in text.replace('100.', 'X'), '0건을 100%로 채우면 안 된다'
    assert '%' not in text.split('일치율')[1].split('\n')[0]


def test_리포트는_폰_스냅샷_건수를_말한다():
    rep = compare([_row('A', 'entry')], [])
    text = format_report('20260916', rep, 'actions-trading', 'phone')
    assert 'phone' in text and '0건' in text


def test_리포트는_입력_불일치를_따로_보고한다():
    rep = compare([_row('A', 'entry', ih='aaa')], [_row('A', 'entry', ih='bbb')])
    text = format_report('20260916', rep, 'actions-trading', 'phone')
    assert 'input_hash' in text


# ── 파일 읽기: 시간별 분할을 모두 모은다 ─────────────────────────

def _write(path, rows):
    import csv
    from src.data.decision_log import COLUMNS
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, '') for c in COLUMNS})


def test_시간별로_쪼개진_파일을_모두_읽는다(tmp_path):
    """읽는 쪽이 파일명을 짚으면 분할 규칙이 바뀌는 순간 조용히 죽는다."""
    d = str(tmp_path)
    _write(os.path.join(d, 'decisions_20260916_10_phone.csv'), [_row('A', 'entry')])
    _write(os.path.join(d, 'decisions_20260916_11_phone.csv'), [_row('B', 'skip')])
    _write(os.path.join(d, 'decisions_20260916_11_actions-trading.csv'), [_row('C', 'skip')])
    rows = load_rows('20260916', d, 'phone')
    assert {r['code'] for r in rows} == {'A', 'B'}, '다른 러너 파일이 섞이면 안 된다'


def test_그날_존재하는_러너를_알려준다(tmp_path):
    """러너 이름을 잘못 주면 0건이 '불일치 0'처럼 보인다 — 실제 이름을 보여준다."""
    d = str(tmp_path)
    _write(os.path.join(d, 'decisions_20260916_10_phone.csv'), [_row('A', 'entry')])
    _write(os.path.join(d, 'decisions_20260916_10_actions-trading.csv'), [_row('A', 'entry')])
    assert runners_present('20260916', d) == ['actions-trading', 'phone']
