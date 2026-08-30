# -*- coding: utf-8 -*-
"""산출물 신선도 감사.

2026-08-30에 하루 만에 네 건이 나왔는데(프리마켓 2주 결손, 미국 워치리스트 2일
결손, EOD 11~12시간 지연, 미국 심 상태 정지) 전부 **사람이 증상을 보고 물어서**
찾았다. 감시가 워크플로 단위(실패했나)로만 있고 산출물 단위(나와야 할 게 나왔나)로는
없었기 때문이다.

고장은 세 종류인데 실패 알림은 첫 번째만 잡는다:
  ① 런이 빨갛다                     → 실패 알림
  ② 런이 초록인데 안 돌았다          → cron 미발화. 빨간 X조차 안 남는다
  ③ 돌았는데 산출물이 없다/낡았다     → 아무도 안 봤다

이 감사는 ②③을 산출물 쪽에서 잡는다.

**세션 단위로 잰다.** "몇 시간 지났나"로 재면 월요일 아침에 전부 결손으로 뜬다.
"마지막 갱신 뒤에 마감된 거래일이 몇 개인가"를 센다 — 주말·공휴일이 자동으로
빠진다.

**심 상태 파일은 대상이 아니다.** 값이 바뀔 때만 커밋되므로, 안 사고 안 판 심은
정상인데도 정지처럼 보인다. 결정과 무관하게 매번 나와야 하는 산출물만 본다.
"""
import datetime as dt

import pytest

from src import data_freshness as fresh

KST = dt.timezone(dt.timedelta(hours=9))


def _kst(y, mo, d, h=0, mi=0):
    return dt.datetime(y, mo, d, h, mi, tzinfo=KST)


# 2026-08-28(금) 개장, 29~30 주말, 31(월) 개장
CAL = {'20260827': 'Y', '20260828': 'Y', '20260829': 'N',
       '20260830': 'N', '20260831': 'Y'}


# ── 세션 계산 ───────────────────────────────────────────────────────
def test_주말은_세션으로_세지_않는다():
    """월요일 아침 감사: 금요일 장중에 갱신됐으면 마감된 세션은 금요일 하나뿐."""
    assert fresh.sessions_closed_since(
        _kst(2026, 8, 28, 14, 0), _kst(2026, 8, 31, 8, 30), CAL) == (1, False)


def test_하루_더_묵으면_세션이_늘어난다():
    assert fresh.sessions_closed_since(
        _kst(2026, 8, 27, 14, 0), _kst(2026, 8, 31, 8, 30), CAL) == (2, False)


def test_마감_전_갱신은_그날_세션을_포함한다():
    """15:30 전에 갱신됐으면 그날 마감은 아직 안 지났다."""
    assert fresh.sessions_closed_since(
        _kst(2026, 8, 28, 9, 0), _kst(2026, 8, 28, 12, 0), CAL) == (0, False)
    assert fresh.sessions_closed_since(
        _kst(2026, 8, 28, 9, 0), _kst(2026, 8, 28, 16, 0), CAL) == (1, False)


def test_달력_밖_구간은_평일근사이고_그_사실을_알린다():
    """KIS 달력은 앞으로 한 달치만 들고 있어 과거 구간은 모른다.

    전부 '측정 불가'로 뭉개면 아무것도 안 보인다(초안이 그랬다 — 7건 중 6건이
    측정 불가였다). 평일 근사로 세되 근사였다는 사실을 같이 넘긴다. 공휴일이
    끼면 세션 수가 과대(=더 엄격)라 놓치는 쪽으로는 안 틀린다.
    """
    n, approx = fresh.sessions_closed_since(_kst(2026, 12, 1), _kst(2026, 12, 5), CAL)
    assert (n, approx) == (4, True)      # 12/1~12/4 마감 (평일)


# ── 감사 ────────────────────────────────────────────────────────────
ENTRY = {'path': 'data/x.csv', 'producer': 'eod_data.yml',
         'max_age_sessions': 1, 'why': '테스트'}


def _audit(last_updated, entries=(ENTRY,), cal=CAL):
    return fresh.audit(list(entries), lambda p: last_updated,
                       now_kst=_kst(2026, 8, 31, 8, 30), calendar=cal)


def test_신선하면_아무_findings도_없다():
    assert _audit(_kst(2026, 8, 28, 16, 0)) == []


def test_기대_주기를_넘기면_결손이다():
    f = _audit(_kst(2026, 8, 27, 14, 0))
    assert len(f) == 1 and f[0]['kind'] == 'stale'
    assert f[0]['sessions'] == 2


def test_파일이_아예_없으면_결손이다():
    f = _audit(None)
    assert len(f) == 1 and f[0]['kind'] == 'missing'


def test_근사로_판정했으면_그_사실이_findings에_남는다():
    f = fresh.audit([ENTRY], lambda p: _kst(2026, 12, 1),
                    now_kst=_kst(2026, 12, 5), calendar=CAL)
    assert len(f) == 1 and f[0]['kind'] == 'stale' and f[0]['approx'] is True


def test_달력이_아는_구간이면_근사가_아니다():
    f = fresh.audit([ENTRY], lambda p: _kst(2026, 8, 27, 14, 0),
                    now_kst=_kst(2026, 8, 31, 8, 30), calendar=CAL)
    assert len(f) == 1 and f[0]['approx'] is False


def test_db_data에_쓰는_워크플로는_전부_감시된다():
    """워크플로 하나가 조용히 산출을 멈춰도 걸리도록, 생산자마다 최소 하나.

    db-data에 파일을 안 남기는 워크플로(weekly_report)는 뺀다 — 신선도로 잴 게
    없고 실패 알림이 덮는다. tests.yml은 CI다.
    """
    import os
    d = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows')
    deploying = set()
    for f in os.listdir(d):
        if not f.endswith('.yml') or f in ('tests.yml', 'pr_checklist.yml'):
            continue
        with open(os.path.join(d, f), encoding='utf-8') as fh:
            if 'db_data_repo' in fh.read() or f in ('scraper.yml', 'token_refresh.yml'):
                deploying.add(f)
    producers = {e['producer'] for e in fresh.load_manifest()}
    assert not (deploying - producers), (
        f'감시되지 않는 워크플로: {sorted(deploying - producers)}')


def test_매니페스트_항목이_형식을_지킨다():
    for e in fresh.load_manifest():
        assert e['path'].startswith('data/'), e
        assert e['max_age_sessions'] >= 1, e
        assert e.get('why'), f'{e["path"]}: why가 없다 — 왜 봐야 하는지 모르면 못 고친다'
        assert e.get('calendar') in ('kr', 'us'), e
