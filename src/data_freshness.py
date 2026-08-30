# -*- coding: utf-8 -*-
"""산출물 신선도 감사 — "나와야 할 게 나왔나".

2026-08-30에 하루 만에 네 건이 나왔는데(프리마켓 2주 결손, 미국 워치리스트 2일
결손, EOD 11~12시간 지연, 미국 심 상태 정지) 전부 **사람이 증상을 보고 물어서**
찾았다. 감시가 워크플로 단위(실패했나)로만 있고 산출물 단위로는 없었다.

고장은 세 종류인데 실패 알림은 첫 번째만 잡는다:
  ① 런이 빨갛다                  → 실패 알림(2026-08-30 도입)
  ② 런이 초록인데 안 돌았다       → cron 미발화. 빨간 X조차 안 남는다
  ③ 돌았는데 산출물이 없다/낡았다  → 아무도 안 봤다

**세션 단위로 잰다.** "몇 시간 지났나"로 재면 월요일 아침에 전부 결손으로 뜬다.
"마지막 갱신 뒤에 마감된 거래일이 몇 개인가"를 세면 주말·공휴일이 자동으로 빠진다.

**심 상태 파일은 대상이 아니다.** 값이 바뀔 때만 커밋되므로 안 사고 안 판 심은
정상인데도 정지처럼 보인다. 결정과 무관하게 매번 나와야 하는 산출물만 본다.
"""
import datetime as dt
import os

import yaml

_KST = dt.timezone(dt.timedelta(hours=9))
MANIFEST_PATH = os.path.join(os.path.dirname(__file__), '..',
                             'config', 'data_freshness.yaml')

# 마감 시각(현지). 이 시각을 지나야 그 세션이 '마감됐다'.
KR_CLOSE_HHMM = (15, 30)
US_CLOSE_HHMM = (16, 0)


def load_manifest(path: str = MANIFEST_PATH) -> list[dict]:
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)['outputs']


def sessions_closed_since(last_kst: dt.datetime, now_kst: dt.datetime,
                          calendar: dict) -> tuple[int, bool]:
    """last_kst 이후 now_kst까지 **마감을 지난** 국내 거래일 수와 근사 여부.

    KIS 달력(data/market_calendar.json)은 **앞으로 한 달치**만 들고 있다
    (2026-08-30 기준 20260830~20260922, 24일). 과거 구간은 달력이 모른다.
    그래서 평일 규칙을 바탕으로 세고, 달력이 '휴장(N)'이라고 명시한 날만 뺀다.

    두 번째 값은 "구간에 달력이 모르는 날이 있었나"다. 공휴일이 끼었다면 세션
    수가 **과대**로 나온다(=더 엄격) — 결손 보고에 그 사실을 같이 적어서
    사람이 판단하게 한다. 전부 '측정 불가'로 뭉개면 아무것도 못 본다.
    """
    n, approx = 0, False
    day = last_kst.date()
    while day <= now_kst.date():
        state = calendar.get(day.strftime('%Y%m%d'))
        if state is None:
            approx = True
            open_day = day.weekday() < 5      # 평일 근사
        else:
            open_day = state == 'Y'
        if open_day:
            close = dt.datetime.combine(
                day, dt.time(*KR_CLOSE_HHMM), tzinfo=_KST)
            if last_kst < close <= now_kst:
                n += 1
        day += dt.timedelta(days=1)
    return n, approx


def _us_sessions_closed_since(last_kst, now_kst) -> int:
    """미국 세션은 휴일 달력이 없어 평일 근사다. 결손 판정이 하루 늦어질 뿐,
    거짓 경보는 안 난다(휴일에 세션을 세면 더 엄격해지므로 max_age에 여유를 둔다)."""
    n = 0
    day = last_kst.date()
    while day <= now_kst.date():
        if day.weekday() < 5:
            # 16:00 ET ≈ 05:00~06:00 KST 다음날. 보수적으로 06:00을 쓴다.
            close = dt.datetime.combine(
                day + dt.timedelta(days=1), dt.time(6, 0), tzinfo=_KST)
            if last_kst < close <= now_kst:
                n += 1
        day += dt.timedelta(days=1)
    return n


def audit(entries: list[dict], last_updated, now_kst: dt.datetime,
          calendar: dict) -> list[dict]:
    """결손 목록. last_updated(path) → 마지막 갱신 시각(KST) 또는 None."""
    findings = []
    for e in entries:
        last = last_updated(e['path'])
        if last is None:
            findings.append({**e, 'kind': 'missing', 'sessions': None})
            continue
        if e.get('calendar') == 'us':
            n, approx = _us_sessions_closed_since(last, now_kst), True
        else:
            n, approx = sessions_closed_since(last, now_kst, calendar)
        if n > e['max_age_sessions']:
            findings.append({**e, 'kind': 'stale', 'sessions': n,
                             'last': last, 'approx': approx})
    return findings
