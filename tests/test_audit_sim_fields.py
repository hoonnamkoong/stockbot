# -*- coding: utf-8 -*-
"""필드 배선 감사기가 **간접 접근**도 잡는가.

이 도구는 "코드가 읽는 값이 실제로 채워지는지"를 재려고 만들었다. 그런데 심6이
6주간 거래 0건이던 원인 필드(change_rate)를 이 도구가 못 봤다 — 두 겹으로 놓쳤다:

  1) 심6은 `_parse_change_rate(stock)`으로 부른다. 필드를 읽는 코드는 심 파일이
     아니라 BaseSimulator.parse_change_rate 안에 있는데, 추출기는 심 파일 텍스트만
     훑었다.
  2) 그 헬퍼의 파라미터 이름은 `stock_data`인데, 추출기 정규식의 수신자 목록은
     (stock|s|cand|c|item)이라 매칭되지 않는다.

잡으라고 만든 도구가 정작 그 사고의 필드를 못 보면 도구가 없는 것과 같다.
"""
from scripts.audit_sim_fields import FIELD_RE, PORTFOLIO_KEYS, fields_read

SIM6 = 'src/strategy/simulators/sim6_bear_hedge.py'


def test_직접_읽는_필드는_그대로_잡는다():
    keys = fields_read(SIM6, 'sim6_bear_hedge')
    assert 'price' in keys
    assert 'sparkline_price' in keys


def test_헬퍼를_통한_간접_접근도_잡는다():
    """심6 거래 0건의 원인 필드다.

    심 파일에 'change_rate' 문자열이 있긴 하다(_log_funnel이 **퍼널 dict**를
    읽는다). 하지만 그건 후보 필드 접근이 아니라 추출기가 안 보는 자리다 —
    파일만 훑는 옛 방식으로는 못 잡았다는 것을 그대로 확인한다.
    """
    file_only = set(FIELD_RE.findall(open(SIM6, encoding='utf-8').read())) - PORTFOLIO_KEYS
    assert 'change_rate' not in file_only, (
        '전제가 깨졌다 — 파일만 훑어도 잡힌다면 이 테스트는 무의미')
    assert 'change_rate' in fields_read(SIM6, 'sim6_bear_hedge')


def test_보유_포지션_키는_후보_감사_대상이_아니다():
    keys = fields_read(SIM6, 'sim6_bear_hedge')
    for k in ('avg_price', 'peak_price', 'quantity'):
        assert k not in keys, f'{k}는 포트폴리오에서 읽는다 — 유니버스 결손이 아니다'


def test_전_심에서_추출이_터지지_않는다():
    """헬퍼 소스를 못 읽는 심이 있어도 감사 전체가 죽으면 안 된다."""
    import glob
    import os
    for path in sorted(glob.glob('src/strategy/simulators/sim*.py')):
        name = os.path.basename(path)[:-3]
        assert isinstance(fields_read(path, name), list), name


def test_감사_대상은_매니페스트에_등재된_심뿐이다():
    """파일 글롭은 은퇴한 심 파일까지 집는다 — 목록의 원천은 매니페스트다.

    `sim1_original.py`·`sim2_conservative.py`·`sim3_aggressive.py`는 매니페스트에
    없는 죽은 파일인데(마지막 거래 2026년 4~5월), `sim*.py` 글롭이 그대로 집어
    감사 대상에 넣고 있었다. 감사는 각 심의 `get_universe()`를 **라이브로** 부르므로
    죽은 심에 KIS 호출을 태우고, 출력에 살아 있는 심과 같은 모양의 줄을 찍는다 —
    읽는 사람에게는 유령이 현역으로 보인다.

    SKIP_SIMS처럼 손으로 적는 목록은 이 레포에서 여러 번 조용히 낡았다.
    매니페스트에서 파생하면 심을 추가·은퇴시킬 때 여기를 고칠 일이 없다.
    """
    import os

    import yaml

    from scripts.audit_sim_fields import sim_paths

    names = {name for _, name in sim_paths()}
    manifest = os.path.join('src', 'strategy', 'strategy_manifest.yaml')
    with open(manifest, encoding='utf-8') as f:
        registered = {e['module'].rsplit('.', 1)[-1]
                      for e in yaml.safe_load(f)['simulators']}

    ghosts = sorted(names - registered)
    assert not ghosts, f'매니페스트에 없는 심이 감사 대상이다: {ghosts}'
    assert 'sim1_psych' in names, '살아 있는 심이 빠지면 안 된다'
