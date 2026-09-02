# -*- coding: utf-8 -*-
"""db-data에 쓰는 워크플로가 서로의 산출물을 되돌리지 않는가 — **자동 감사**.

`scraper.yml`은 런 시작에 db-data의 `data/` 전체를 체크아웃하고(Fetch 스텝),
배포 스텝에서 `data/*.json`·`data/*.csv`를 통째로 밀어 올린다. 즉 **다른
워크플로가 소유한 파일을 제외 목록에 넣지 않으면, 그 파일은 런 시작 시점
사본으로 상시 되돌아간다**(lost update).

되돌림은 실패로 안 보인다 — 두 워크플로 모두 초록이고 데이터만 과거다.

2026-09-01에 실제로 터졌다: `us_eod_watchlist.yml`이 10:14 KST에 워치리스트를
`20260901`로 갱신했는데(48cb7f133) 10:17 KST에 이 cp가 `20260831`로 되돌렸다
(6678f04b3). `load_watchlist`는 날짜 불일치에 fail-closed라 US 심 3개가 그
세션 내내 후보 0이었고, 결손 알림이 2분마다 나갔다.

**"시간대가 안 겹치니 괜찮다"는 전제는 이미 깨졌다.** 그 배치는 22:00 UTC cron인데
스케줄이 밀려 01:06 UTC에 돌았고, 그 지연이 scraper 창 안으로 배치를 밀어 넣었다.
고빈도 cron이 드롭·지연되는 건 이 레포에서 반복 관측된 현상이다.

그래서 개별 파일을 하나씩 고치는 대신, **워크플로 파일을 파싱해 소유권을 도출하고
제외 목록의 누락을 자동으로 잡는다.** 새 워크플로가 `data/`에 쓰기 시작하면 여기서
먼저 죽는다.
"""
import fnmatch
import os
import re

WF_DIR = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows')

# 두 writer가 공유하는 파일 — 제외하면 **안 되는** 것들. 여기 있다는 건
# "lost update 위험을 알고 감수한다"는 뜻이지, 안전하다는 뜻이 아니다.
SHARED_WRITERS = {
    # src/pipeline/context.py의 refresh_calendar가 이 런 안에서 갱신한다.
    # token_refresh.yml과 공유 writer라 제외하면 스크래퍼의 갱신이 안 나간다.
    'market_calendar.json': 'src/pipeline/context.py가 refresh_calendar를 부른다',
    # data_fetcher의 field_outage 알림이 이 런 안에서 쿨다운을 기록한다.
    # writer가 셋이라 통짜 cp로는 서로를 지운다. 벌크 루프에서는 빼되
    # scripts/merge_alert_dedup.py로 **키별 병합**해서 올린다 — 제외됐지만
    # 도달한다. 아래 단언이 "제외 안 됨"이 아니라 "도달함"을 보는 이유다.
    'alert_dedup.json': 'src/pipeline/workers/data_fetcher.py가 send_alert_once를 쓴다',
}

# 파싱이 조용히 깨지는 걸 막는 하한. 워크플로 문법이 바뀌어 추출이 0건이 되면
# 이 파일은 아무것도 검사하지 않으면서 초록이 된다 — 그게 이 테스트가 막으려는
# 실패와 똑같은 모양이다.
MIN_WRITES = {
    'eod_data.yml': 7,
    'premarket_data.yml': 7,
    'token_refresh.yml': 1,
    'us_eod_watchlist.yml': 4,
    'us_trading.yml': 7,
}


def _source(name: str) -> str:
    """주석을 걷어낸 워크플로 본문. 주석에는 파일명이 설명으로 등장한다."""
    with open(os.path.join(WF_DIR, name), encoding='utf-8') as f:
        return '\n'.join(l for l in f.read().splitlines()
                         if not l.strip().startswith('#'))


def db_data_writes(name: str) -> set[str]:
    """이 워크플로가 db-data에 쓰는 `data/` 파일명(글롭 포함).

    세 가지 배선을 본다 — `cp data/X db_data_repo/`, `for f in ...; do` 목록,
    `git add data/X`. 레포에 실제로 쓰이는 형태가 이 셋이다.
    """
    s = _source(name)
    out: set[str] = set()
    for m in re.finditer(r'cp\s+(?:-r\s+)?(?:"?[.][.]/)?data/([A-Za-z0-9_.*-]+)', s):
        out.add(m.group(1))
    for m in re.finditer(r'for\s+f\s+in\s+([^;]+?);\s*do', s, re.S):
        for tok in m.group(1).split():
            tok = tok.strip('"' + "'")
            if 'data/' in tok:
                out.add(tok.split('data/', 1)[1])
            elif re.fullmatch(r'[A-Za-z0-9_.*-]+[.](json|csv)', tok):
                out.add(tok)
    # 병합 배선: `... db_data_repo/data/X data/X`. cp만 보던 시절 문법이 바뀌자
    # us_trading의 쓰기가 7개에서 6개로 줄어 이 파일이 조용해질 뻔했다.
    # 스크립트 이름이 아니라 **쓰기 대상 경로**를 본다 — 다음 도구가 와도 잡힌다.
    for m in re.finditer(r'db_data_repo/data/([A-Za-z0-9_.*-]+)', s):
        out.add(m.group(1))
    for m in re.finditer(r'git add\s+((?:data/[A-Za-z0-9_.*-]+\s*)+)', s):
        for tok in m.group(1).split():
            out.add(tok.split('data/', 1)[1])
    # 스크래퍼의 벌크 루프가 집는 건 json·csv 둘뿐이다.
    return {n for n in out if n.endswith(('.json', '.csv'))}


def scraper_skip_patterns() -> list[str]:
    """배포 스텝 `case`문의 제외 arm. `a.json|b_*.csv) continue ;;` 형태."""
    deploy = _source('scraper.yml').split('Deploy Data to db-data branch', 1)[1]
    return [p.strip() for line in deploy.splitlines() if 'continue' in line
            for p in line.strip().split(')', 1)[0].split('|')]


def _covered(name: str, patterns: list[str]) -> bool:
    """글롭 이름은 그 자체가 제외 arm으로 들어가므로 문자열 일치도 인정한다."""
    return name in patterns or any(fnmatch.fnmatch(name, p) for p in patterns)


# ── 파서가 살아 있는가 ──────────────────────────────────────────────

def test_the_parser_still_finds_what_each_workflow_writes():
    """추출이 0건이 되면 아래 감사가 통째로 무의미해진다 — 여기서 먼저 죽는다."""
    for wf, minimum in MIN_WRITES.items():
        found = db_data_writes(wf)
        assert len(found) >= minimum, (
            f'{wf}에서 db-data 쓰기를 {len(found)}개만 찾았다(최소 {minimum}). '
            f'배포 스텝 문법이 바뀌었으면 db_data_writes()를 같이 고쳐야 한다 — '
            f'안 고치면 소유권 감사가 아무것도 검사하지 않으면서 초록이 된다. '
            f'찾은 것: {sorted(found)}')


# ── 소유권 감사 ────────────────────────────────────────────────────

def test_scraper_excludes_every_file_another_workflow_owns():
    """이 테스트가 이 파일의 존재 이유다.

    새 워크플로가 `data/`에 쓰기 시작하면, 아무도 손대지 않아도 여기서 잡힌다.
    """
    patterns = scraper_skip_patterns()
    gaps: dict[str, list[str]] = {}
    for wf in sorted(os.listdir(WF_DIR)):
        if not wf.endswith('.yml') or wf == 'scraper.yml':
            continue
        missing = [n for n in sorted(db_data_writes(wf))
                   if n not in SHARED_WRITERS and not _covered(n, patterns)]
        if missing:
            gaps[wf] = missing

    assert not gaps, (
        '아래 파일은 다른 워크플로가 소유하는데 scraper.yml 배포 제외 목록에 없다. '
        '스크래퍼가 런 시작 시점 사본으로 되돌린다(조용한 lost update).\n' +
        '\n'.join(f'  {wf}: {", ".join(names)}' for wf, names in gaps.items()))


def test_shared_writers_are_deliberately_not_excluded():
    """공유 writer를 제외 목록에 넣으면 **반대 방향 사고**가 난다 —
    스크래퍼가 갱신한 값이 db-data에 영영 도달하지 못한다.

    이 단언이 깨지면, 넣기 전에 그 파일의 writer가 정말 하나로 줄었는지
    확인해야 한다.
    """
    patterns = scraper_skip_patterns()
    reached = db_data_writes('scraper.yml')
    for name, why in SHARED_WRITERS.items():
        assert not _covered(name, patterns) or name in reached, (
            f'{name}이 scraper.yml 배포 제외에 들어갔는데 다른 배선으로도 '
            f'db-data에 안 올라간다 — {why}. 스크래퍼가 쓴 값이 도달하지 못한다.')


def test_the_us_watchlists_are_the_case_this_file_was_written_for():
    """2026-09-01 사고의 회귀 테스트. 위 감사가 일반형이고 이건 그 구체형이다 —
    감사 로직이 리팩터링으로 헐거워져도 이 사고만은 다시 안 나게 못박는다."""
    patterns = scraper_skip_patterns()
    for name in ('sim_us1_minervini_watchlist.json',
                 'sim_us2_donchian_watchlist.json',
                 'sim_us3_liquidity_watchlist.json',
                 'us_universe.json'):
        assert _covered(name, patterns), f'{name}이 제외 목록에서 빠졌다'


def test_the_kr_watchlist_has_the_same_protection():
    """심11(국내 미너비니)의 워치리스트도 날짜 fail-closed다 — 되돌리면 US와
    똑같이 그 심이 조용히 하루를 통째로 잃는다. writer는 eod_data.yml이다."""
    assert _covered('sim11_watchlist.json', scraper_skip_patterns())
