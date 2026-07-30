# -*- coding: utf-8 -*-
"""관측 append가 파이프라인에 배선됐는가.

trade_engine을 import하면 네트워크 의존이 따라오므로 소스를 읽어 검사한다
(tests/test_sim_registry_consistency.py의 '소비자가 자기 목록을 다시 만들지 않았는가'와
같은 방식). 배선이 빠지면 이력이 안 쌓이고, 그러면 라벨러·하네스·필터가 전부 무의미하다.
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with io.open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def test_경로가_data_아래_csv다():
    # scraper.yml의 배포 스텝이 data/*.csv를 db-data로 복사한다. 이 규칙을 벗어나면
    # 이력이 런 사이에 이어지지 않는다.
    from src.strategy.regime_observations import OBS_PATH_REL
    assert OBS_PATH_REL.startswith('data/')
    assert OBS_PATH_REL.endswith('.csv')


def test_trade_engine이_append를_부른다():
    src = _read('src/pipeline/workers/trade_engine.py')
    assert 'append_observation' in src, '관측을 쌓지 않으면 이 계획의 나머지가 전부 무의미하다'


def test_trade_engine이_분_단위_시각을_넘긴다():
    src = _read('src/pipeline/workers/trade_engine.py')
    # '%H:00'으로 깎은 값을 넘기면 다시 5/6을 버린다.
    m = re.search(r'append_observation\((.{0,400}?)\)', src, re.S)
    assert m, 'append_observation 호출을 찾지 못했다'
    call = m.group(1)
    assert "'%H:00'" not in call and '"%H:00"' not in call
    assert '%H:%M' in call, '분까지 기록해야 10분 해상도가 된다'


def test_마감_런에서도_관측을_남긴다():
    """태스커의 마지막 신호(15:30)는 after_close가 먼저 참이라 finalize로 간다.

    거기서 안 쌓으면 하루의 종착점(종가 breadth)이 관측 시계열에서 통째로 빠지고,
    KIS 백필은 당일분봉뿐이라 나중에 메울 수도 없다.
    """
    src = _read('src/pipeline/workers/trade_engine.py')
    fin = src.index("if action == 'finalize':")
    now = src.index("elif action == 'nowcast'")
    assert fin < now, 'finalize 분기가 nowcast보다 앞에 있어야 이 테스트의 구간이 맞다'
    assert '_append_regime_observation' in src[fin:now], \
        'finalize 분기에서 관측을 남기지 않으면 종가가 이력에 빠진다'
    assert '_append_regime_observation' in src[now:now + 800], \
        'nowcast 분기에서도 남겨야 장중 10분 해상도가 된다'


def test_기록_실패가_매매를_막지_않는다():
    src = _read('src/pipeline/workers/trade_engine.py')
    # append 호출은 try로 감싸고, 그렇다고 조용히 넘기지도 않는다(log_error).
    idx = src.index('def _append_regime_observation')
    window = src[idx:idx + 1400]
    assert 'try:' in window
    assert 'log_error' in window, '조용한 실패는 이 레포에서 금지다'
    assert 'if not live_breadth:' in window, '없는 관측을 지어내지 않는다'


def test_배포_스텝이_data_csv를_복사한다():
    wf = _read('.github/workflows/scraper.yml')
    assert 'data/*.csv' in wf, '이 글롭이 사라지면 관측 이력이 런 사이에 끊긴다'
