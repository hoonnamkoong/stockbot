# -*- coding: utf-8 -*-
"""스크리너가 죽어도 직전 유니버스로 워치리스트는 만든다.

2026-08-24·25에 나스닥 스크리너 소프트 차단으로 us_eod_watchlist가 예외로 죽었고,
미국 심 3개가 그 세션에 워치리스트 없이 들어갔다 — 매매도 손절도 0건.

유니버스는 **상장 종목 목록**이라 하루 이틀 낡아도 거의 안 변한다. 워치리스트가
아예 없는 것보다 하루 묵은 유니버스로 만드는 쪽이 낫다. 다만 조용히 넘어가면
안 된다 — 알림을 보내고, 파일 자체는 config/data_freshness.yaml이 계속 지적한다.

**폴백도 비면 실패다.** 빈 유니버스로 "정상 종료"하면 워치리스트 0종목이
정상처럼 보인다([[no-fabricated-financial-values]]).
"""
from unittest import mock

import pytest

from scripts import run_eod_sim_us as r


def test_스크리너가_죽으면_직전_유니버스를_쓴다():
    prev = [{'symbol': 'AAPL', 'name': 'Apple', 'market_cap': 1.0}]
    alerts = []
    with mock.patch.object(r, 'fetch_us_universe', side_effect=RuntimeError('소프트 차단')), \
         mock.patch.object(r, 'load_universe', return_value=prev), \
         mock.patch.object(r.alerts, 'send_alert', side_effect=lambda t, **k: alerts.append(t)):
        rows, stale = r.resolve_universe('data/us_universe.json')
    assert rows == prev and stale is True
    assert len(alerts) == 1 and '직전' in alerts[0]


def test_스크리너가_살아있으면_그걸_쓴다():
    fresh = [{'symbol': 'NVDA', 'name': 'NVIDIA', 'market_cap': 2.0}]
    with mock.patch.object(r, 'fetch_us_universe', return_value=fresh), \
         mock.patch.object(r, 'filter_universe', side_effect=lambda x: x), \
         mock.patch.object(r, 'load_universe') as lu:
        rows, stale = r.resolve_universe('data/us_universe.json')
    assert rows == fresh and stale is False
    lu.assert_not_called()


def test_폴백도_비면_실패다():
    """빈 유니버스로 정상 종료하면 워치리스트 0종목이 정상처럼 보인다."""
    with mock.patch.object(r, 'fetch_us_universe', side_effect=RuntimeError('소프트 차단')), \
         mock.patch.object(r, 'load_universe', return_value=[]), \
         mock.patch.object(r.alerts, 'send_alert'):
        with pytest.raises(RuntimeError):
            r.resolve_universe('data/us_universe.json')


def test_폴백을_썼으면_유니버스_파일을_덮어쓰지_않는다():
    """직전 파일을 그대로 다시 저장하면 커밋 시각이 갱신돼 신선도 감사가 속는다."""
    prev = [{'symbol': 'AAPL', 'name': 'Apple', 'market_cap': 1.0}]
    with mock.patch.object(r, 'fetch_us_universe', side_effect=RuntimeError('x')), \
         mock.patch.object(r, 'load_universe', return_value=prev), \
         mock.patch.object(r.alerts, 'send_alert'), \
         mock.patch.object(r, 'save_universe') as save:
        rows, stale = r.resolve_universe('data/us_universe.json')
        if not stale:
            r.save_universe(rows, 'data/us_universe.json')
    save.assert_not_called()
