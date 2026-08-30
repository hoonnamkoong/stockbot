# -*- coding: utf-8 -*-
"""매 거래일 아침, 산출물이 기대 주기 안에 갱신됐는지 훑는다.

    python3 scripts/audit_data_freshness.py

trading.yml의 audit 창(평일 08:30~09:00 KST)에서 태스커 트리거로 돈다. 장이
열리기 전에 "어젯밤 뭐가 안 돌았나"를 받는 게 목적이다.

**갱신 시각은 GitHub API로 읽는다.** 러너의 db-data 체크아웃은 얕고(--depth 1),
얕은 클론에서 `git log`를 돌리면 모든 파일이 그 바닥 날짜로 보인다 — 조사 중에
실제로 이 함정에 빠졌다. commits API는 깊이와 무관하다.

한계: 태스커가 죽으면 이 감사기도 안 돈다. 다만 태스커가 죽으면 국내 매매가
통째로 멈춰서 사람이 즉시 안다 — 조용히 지나갈 수 있는 고장은 아니다.
"""
import datetime as dt
import fnmatch
import json
import os
import sys
from urllib import error, parse, request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data_freshness import audit, load_manifest  # noqa: E402

_KST = dt.timezone(dt.timedelta(hours=9))
_BRANCH = 'db-data'


def _repo():
    return os.environ.get('GITHUB_REPOSITORY') or 'hoonnamkoong/stockbot'


def _api(url: str):
    tok = os.environ.get('GH_PAT') or os.environ.get('GITHUB_TOKEN')
    req = request.Request(url, headers={
        'Authorization': f'token {tok}',
        'Accept': 'application/vnd.github.v3+json'})
    with request.urlopen(req, timeout=20) as res:
        return json.loads(res.read().decode())


def list_tree(log=print) -> list[str] | None:
    """db-data의 현재 파일 목록. 글롭 항목을 풀 때 쓴다."""
    try:
        sha = _api(f'https://api.github.com/repos/{_repo()}/branches/{_BRANCH}'
                   )['commit']['sha']
        tree = _api(f'https://api.github.com/repos/{_repo()}/git/trees/{sha}'
                    '?recursive=1')
        return [t['path'] for t in tree.get('tree', []) if t['type'] == 'blob']
    except (error.URLError, OSError, ValueError, KeyError) as e:
        log(f'[Audit] 파일 목록 조회 실패: {e}')
        return None


def make_last_updated(tree: list[str] | None, log=print):
    """path(글롭 가능) → 마지막 커밋 시각(KST). 없으면 None."""
    def last_updated(pattern: str):
        paths = ([p for p in tree if fnmatch.fnmatch(p, pattern)]
                 if tree is not None else [])
        if '*' not in pattern:
            paths = [pattern] if (tree is None or pattern in tree) else []
        if not paths:
            return None
        newest = None
        for p in paths:
            try:
                commits = _api(
                    f'https://api.github.com/repos/{_repo()}/commits'
                    f'?sha={_BRANCH}&path={parse.quote(p)}&per_page=1')
            except (error.URLError, OSError, ValueError) as e:
                log(f'[Audit] {p} 커밋 조회 실패: {e}')
                continue
            if not commits:
                continue
            ts = dt.datetime.fromisoformat(
                commits[0]['commit']['committer']['date'].replace('Z', '+00:00'))
            ts = ts.astimezone(_KST)
            newest = ts if newest is None or ts > newest else newest
        return newest
    return last_updated


def _calendar(log=print) -> dict:
    """KIS chk-holiday 달력. 없으면 빈 맵 → 국내 항목은 '측정 불가'가 된다."""
    try:
        raw = _api(f'https://api.github.com/repos/{_repo()}/contents/'
                   f'data/market_calendar.json?ref={_BRANCH}')
        import base64
        return json.loads(base64.b64decode(raw['content'])).get('days', {})
    except Exception as e:
        log(f'[Audit] 달력 조회 실패(국내 항목은 측정 불가로 보고): {e}')
        return {}


def format_report(findings: list[dict]) -> str:
    order = {'missing': 0, 'stale': 1}
    label = {'missing': '없음', 'stale': '낡음'}
    lines = ['<b>산출물 신선도 결손</b>', '']
    approx_used = False
    for f in sorted(findings, key=lambda x: order[x['kind']]):
        age = f' ({f["sessions"]}세션)' if f.get('sessions') is not None else ''
        star = '*' if f.get('approx') else ''
        lines.append(f'• <code>{f["path"]}</code> — {label[f["kind"]]}{age}{star}')
        lines.append(f'  생산자: {f["producer"]} / {f["why"].strip()}')
        approx_used |= bool(f.get('approx'))
    if approx_used:
        lines.append('')
        lines.append('* 달력이 모르는 구간을 평일로 근사했다(KIS 달력은 앞으로 '
                     '한 달치만 있다). 공휴일이 끼었다면 세션 수가 과대일 수 있다.')
    return chr(10).join(lines)


def _send(text: str, log=print) -> bool:
    tok = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat = os.environ.get('TELEGRAM_CHAT_ID')
    if not (tok and chat):
        log('[Audit] 텔레그램 시크릿 없음 — 발송 생략')
        return False
    data = parse.urlencode({'chat_id': chat, 'text': text,
                            'parse_mode': 'HTML'}).encode()
    try:
        with request.urlopen(
                request.Request(f'https://api.telegram.org/bot{tok}/sendMessage',
                                data=data, method='POST'), timeout=15):
            pass
        return True
    except (error.URLError, OSError) as e:
        log(f'[Audit] 텔레그램 발송 실패: {e}')
        return False


def main(log=print) -> list[dict]:
    entries = load_manifest()
    tree = list_tree(log)
    findings = audit(entries, make_last_updated(tree, log),
                     now_kst=dt.datetime.now(_KST), calendar=_calendar(log))
    log(f'[Audit] 항목 {len(entries)}개 중 결손 {len(findings)}개')
    for f in findings:
        log(f'  - {f["path"]} [{f["kind"]}] {f.get("sessions", "")}')
    if findings:
        _send(format_report(findings), log)
    return findings


if __name__ == '__main__':
    main()
