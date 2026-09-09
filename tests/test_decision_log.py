# -*- coding: utf-8 -*-
"""결정 스냅샷 — 폰 워커와 옛 경로를 비교할 유일한 재료.

이 파일이 없으면 3단계(그림자 운전)의 "결정 불일치 0"을 **잴 수가 없다.**
그리고 잴 수 없는 게이트는 게이트가 아니다.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data import decision_log as dl


# ── input_hash: "같은 입력이었나"를 판정하는 근거 ──────────────────

def test_같은_입력은_같은_지문이다():
    a = {'code': '005930', 'price': 70000, 'tick_power': 103.4}
    b = {'code': '005930', 'price': 70000, 'tick_power': 103.4}
    assert dl.input_hash(a) == dl.input_hash(b)


def test_결정에_쓰이는_값이_바뀌면_지문이_바뀐다():
    a = {'price': 70000, 'tick_power': 103.4}
    b = {'price': 70100, 'tick_power': 103.4}
    assert dl.input_hash(a) != dl.input_hash(b)


def test_무관한_필드는_지문을_바꾸지_않는다():
    """**전체 키를 해싱하면 안 되는 이유.** 이름이나 섹터가 달라졌다고
    '입력이 달랐다'가 되면 게이트가 모든 불일치를 면제해 버린다."""
    a = {'price': 70000, 'name': '삼성전자', 'sector_name': '반도체'}
    b = {'price': 70000, 'name': 'SAMSUNG', 'sector_name': 'semi'}
    assert dl.input_hash(a) == dl.input_hash(b)


def test_결손과_0은_다른_입력이다():
    """이 레포가 반복해서 당한 혼동이라 해시에서도 가른다."""
    missing = {'price': 70000}
    zero = {'price': 70000, 'tick_power': 0}
    assert dl.input_hash(missing) != dl.input_hash(zero)


# ── build_rows: 결정 셋을 가른다 ─────────────────────────────────

CANDS = [{'code': 'A', 'price': 100}, {'code': 'B', 'price': 200},
         {'code': 'C', 'price': 300}]


def _rows(**kw):
    kw.setdefault('runner', 'actions')
    return {r['code']: r for r in dl.build_rows('Sim4-1', CANDS, **kw)}


def test_산_종목은_entry다():
    r = _rows(funnel=[], orders=[{'code': 'A', 'action': 'BUY'}])
    assert r['A']['decision'] == 'entry'


def test_탈락한_종목은_이유와_함께_skip이다():
    r = _rows(funnel=[{'code': 'B', 'reason': 'adx_high'}], orders=[])
    assert r['B']['decision'] == 'skip'
    assert r['B']['reason'] == 'adx_high'


def test_기록이_없는_후보는_seen이다():
    """조기종료(max_holdings에서 break)로 평가에 도달하지 못한 후보다.
    skip에 섞으면 '탈락했다'가 되어 불일치 판정이 오염된다."""
    r = _rows(funnel=[{'code': 'B', 'reason': 'adx_high'}],
              orders=[{'code': 'A', 'action': 'BUY'}])
    assert r['C']['decision'] == 'seen'
    assert r['C']['reason'] == ''


def test_한_종목은_한_행만_받는다():
    """탈락 기록과 매수가 함께 있으면 매수가 이긴다 — 실제로 일어난 일이다."""
    rows = dl.build_rows('Sim4-1', CANDS, [{'code': 'A', 'reason': 'x'}],
                         [{'code': 'A', 'action': 'BUY'}], runner='actions')
    a = [r for r in rows if r['code'] == 'A']
    assert len(a) == 1 and a[0]['decision'] == 'entry'


def test_매도는_결정으로_세지_않는다():
    """이 스냅샷이 재는 것은 **진입 판단**이다. 청산은 보유분에서 나오므로
    후보 목록과 축이 다르고, 섞으면 같은 code가 두 축에서 비교된다."""
    r = _rows(funnel=[], orders=[{'code': 'A', 'action': 'SELL'}])
    assert r['A']['decision'] == 'seen'


def test_모든_행이_같은_사이클과_runner를_받는다():
    rows = dl.build_rows('Sim4-1', CANDS, [], [], runner='phone', cycle_id=42)
    assert {r['cycle_id'] for r in rows} == {42}
    assert {r['runner'] for r in rows} == {'phone'}


def test_후보가_없으면_행도_없다():
    assert dl.build_rows('Sim4-1', [], [], [], runner='actions') == []


# ── runner ──────────────────────────────────────────────────────

def test_runner는_환경변수로_정해지고_기본은_actions(monkeypatch):
    monkeypatch.delenv('STOCKBOT_RUNNER', raising=False)
    assert dl.runner_name() == 'actions'
    monkeypatch.setenv('STOCKBOT_RUNNER', 'phone')
    assert dl.runner_name() == 'phone'


def test_빈_문자열도_actions로_떨어진다(monkeypatch):
    """폰에서 `export STOCKBOT_RUNNER=`로 비워두면 빈 값이 온다. 그대로 쓰면
    runner 열이 비어 비교가 안 된다."""
    monkeypatch.setenv('STOCKBOT_RUNNER', '  ')
    assert dl.runner_name() == 'actions'


# ── 파일 이름이 소유권이다 ──────────────────────────────────────

def test_파일이_runner별로_갈린다():
    """심은 두 워크플로에 나뉘어 돈다. 파일이 하나면 뒤에 끝난 쪽이 앞의 것을
    db-data에서 되돌린다 — 워크플로가 초록인 채로 일어나는 고장이다."""
    a = dl.log_path('20260909', runner='actions-trading', hour_='11')
    b = dl.log_path('20260909', runner='actions-scraper', hour_='11')
    c = dl.log_path('20260909', runner='phone', hour_='11')
    assert len({a, b, c}) == 3
    assert a.endswith('decisions_20260909_11_actions-trading.csv')


def test_시간별로_갈려_한_푸시가_하루치가_되지_않는다():
    """2분 격자가 매 사이클 이 파일을 통째로 db-data에 민다. 일별이면 마감
    무렵 한 푸시가 하루치 전체(~3.6MB 추정)가 되고, 배포 스텝이 3분 잡 예산에
    잘리면 그 사이클의 심 상태가 통째로 안 올라간다."""
    h10 = dl.log_path('20260909', runner='phone', hour_='10')
    h11 = dl.log_path('20260909', runner='phone', hour_='11')
    assert h10 != h11


def test_읽는_쪽은_글롭으로_찾는다(tmp_path):
    """리터럴 파일명이 든 목록은 분할 규칙이 바뀌는 순간 조용히 죽는다."""
    d = str(tmp_path)
    for h in ('09', '10', '11'):
        open(dl.log_path('20260909', data_dir=d, runner='phone', hour_=h), 'w').close()
    open(dl.log_path('20260909', data_dir=d, runner='actions-trading', hour_='09'), 'w').close()
    got = dl.files_for('20260909', data_dir=d, runner='phone')
    assert len(got) == 3, got
    assert all('phone' in g for g in got)


# ── 파일 ────────────────────────────────────────────────────────

def test_헤더는_한_번만_쓴다(tmp_path):
    p = str(tmp_path / 'decisions.csv')
    rows = dl.build_rows('Sim4-1', CANDS, [], [], runner='actions')
    assert dl.append(rows, path=p) == 3
    assert dl.append(rows, path=p) == 3
    with open(p, encoding='utf-8') as f:
        body = f.read()
    assert body.count('cycle_id,ts,runner') == 1


def test_기록_실패는_심을_죽이지_않는다(tmp_path):
    """진단이 매매를 죽이면 그건 진단이 아니다."""
    said = []
    n = dl.append([{'code': 'A'}], path=str(tmp_path / 'no' / 'x' / '\0bad'),
                  log=said.append)
    assert n == 0
    assert said, '조용히 삼켰다 — 실패가 안 보이면 파일 0개를 못 찾는다'
