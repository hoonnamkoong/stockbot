# -*- coding: utf-8 -*-
"""추적되는 파일에 시크릿이 들어가는 것을 CI가 막는다.

## 왜 생겼나 (2026-09-10 실측)

`.env.production`이 **public 레포의 살아있는 브랜치에 6개월간** 있었다.
커밋 2026-03-21, `raw.githubusercontent.com`에서 HTTP 200으로 누구나 받을 수 있었다.
들어 있던 것: `KIS_APP_SECRET`(180자)·`KIS_APP_KEY`·`GITHUB_PAT`·`ADMIN_PASSWORD`·
`TRADE_PIN`·`NEXTAUTH_SECRET` — 전부 실제값이다.

**규칙은 있었다.** "시크릿은 env 전용, 절대 커밋 금지"가 문서에 있었고 `.gitignore`에
`.env`도 있었다. 그런데 `.env.production`은 그 패턴에 안 걸렸고, 무엇보다
**규칙을 어겼을 때 실패하는 곳이 없었다.** 이 레포의 다른 불변식들이 그렇듯
(토큰 단일 발급자, 파일 소유권, net 이관) 자원을 고정하는 것은 문서가 아니라 게이트다.

## 무엇을 막고 무엇을 못 막나

막는 것: **새로** 추적되는 파일에 시크릿 값이나 시크릿 파일명이 들어오는 것.
못 막는 것: 이미 이력에 있는 것(그건 재발급으로만 해결된다),
그리고 여기 없는 형태의 새 자격증명(패턴은 목록이라 늘 뒤따라간다).
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# 값의 '모양'으로 잡는다. 키 이름으로 잡으면 `KIS_APP_KEY=` 같은 문서·테스트가
# 전부 걸려 게이트가 소음이 되고, 소음이 되면 꺼진다.
VALUE_PATTERNS = {
    'GitHub PAT': re.compile(r'gh[pousr]_[A-Za-z0-9]{36}'),
    'Google/Gemini API key': re.compile(r'AIza[0-9A-Za-z_-]{35}'),
    'Telegram bot token': re.compile(r'[0-9]{9,10}:AA[0-9A-Za-z_-]{33}'),
    'JWT (KIS 액세스 토큰 등)': re.compile(r'eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.'),
    'KIS appkey': re.compile(r'\bPS[A-Za-z0-9]{34}\b'),
    'PEM 개인키': re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
}

# 값이 없어도 **이름만으로** 커밋하면 안 되는 파일.
# `.env.production`이 `.gitignore`의 `.env`에 안 걸렸던 것이 이 사고의 시작이다.
FILENAME_PATTERNS = (
    re.compile(r'(^|/)\.env(\.|$)'),
    re.compile(r'(^|/)env[^/]*\.env$'),
    re.compile(r'(^|/)(kis_)?token[^/]*\.json$'),
    re.compile(r'(^|/)[^/]*credential[^/]*$', re.I),
    re.compile(r'\.(pem|p12|pfx|key)$'),
    re.compile(r'(^|/)id_(rsa|ed25519)$'),
)

# 예시 파일은 값이 없다는 뜻으로 통용되는 이름이라 통과시킨다.
FILENAME_ALLOW = re.compile(r'\.(example|sample|template)$|(^|/)\.env\.example$')

# 값 패턴 예외. **비우고 시작한다** — 넣을 때는 왜 안전한지 여기 적을 것.
# 파일 단위 예외는 그 파일 전체를 검사에서 빼므로 구멍이다. 아래
# `test_게이트가_...`의 표본을 전부 **조립해서** 만드는 이유가 그것이다 —
# 리터럴로 두면 이 파일이 자기 게이트에 걸려 예외를 넣게 되고, 그 예외가
# 나중에 진짜 시크릿을 가린다. (커밋한 순간 실제로 빨개져서 알았다.)
VALUE_ALLOW: dict[str, str] = {}


def _tracked_files() -> list[str]:
    """`text=True`를 쓰지 않는다 — 레포에 한글 파일명이 있어 Windows 로케일로
    디코딩하면 **stdout이 통째로 None**이 된다(실제로 그랬다). 조용히 빈 목록이
    되면 게이트가 아무것도 검사하지 않는다."""
    out = subprocess.run(['git', 'ls-files', '-z'], cwd=REPO,
                         capture_output=True, timeout=120)
    raw = (out.stdout or b'').decode('utf-8', 'surrogateescape')
    return [p for p in raw.split(chr(0)) if p]


def test_시크릿_값이_추적되는_파일에_없다():
    """값의 모양으로 잡는다. 걸리면 **파일과 종류만** 보고한다 —
    실패 메시지에 값을 실으면 CI 로그가 새 유출 지점이 된다."""
    offenders = []
    for rel in _tracked_files():
        if rel in VALUE_ALLOW:
            continue
        path = os.path.join(REPO, rel)
        if not os.path.isfile(path) or os.path.getsize(path) > 2_000_000:
            continue
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                body = f.read()
        except OSError:
            continue
        for kind, pat in VALUE_PATTERNS.items():
            if pat.search(body):
                offenders.append(f'{rel}  ← {kind}')
    assert not offenders, (
        '추적되는 파일에 시크릿으로 보이는 값이 있다. **값은 여기 찍지 않는다** — '
        '해당 파일을 직접 열어 확인하고, 진짜면 자격증명을 먼저 재발급할 것:\n  '
        + '\n  '.join(offenders))


def test_시크릿_파일명이_추적되지_않는다():
    """`.gitignore`가 있어도 `git add -f`는 통과한다. 그리고 `.env`만 무시하면
    `.env.production`은 안 걸린다 — 2026-03-21에 실제로 그렇게 들어왔다."""
    offenders = []
    for rel in _tracked_files():
        if FILENAME_ALLOW.search(rel):
            continue
        if any(p.search(rel) for p in FILENAME_PATTERNS):
            offenders.append(rel)
    assert not offenders, (
        '시크릿을 담기 쉬운 파일명이 추적되고 있다:\n  ' + '\n  '.join(offenders))


def test_게이트가_실제로_무언가를_잡는다():
    """**헛통과를 막는다.** 2026-09-09에 `net` 가드가 정규식에 리터럴 백스페이스가
    박혀 아무것도 검사하지 않은 채 초록이었다. 패턴이 죽으면 여기서 빨개진다."""
    samples = {
        'GitHub PAT': 'ghp_' + 'a' * 36,
        'Google/Gemini API key': 'AIza' + 'b' * 35,
        'Telegram bot token': '1234567890:AA' + 'c' * 33,
        'JWT (KIS 액세스 토큰 등)': 'eyJ' + 'd' * 20 + '.' + 'e' * 20 + '.sig',
        'KIS appkey': 'PS' + 'F' * 34,
        'PEM 개인키': '-----BEGIN RSA PRIVATE ' + 'KEY-----',
    }
    for kind, sample in samples.items():
        assert VALUE_PATTERNS[kind].search(sample), f'{kind} 패턴이 죽었다'

    # 평범한 코드가 걸리면 게이트가 소음이 되고, 소음이 되면 꺼진다.
    benign = ('KIS_APP_KEY = os.environ["KIS_APP_KEY"]',
              'token = get_access_token()',
              'ghp_is_not_a_token', 'AIzaSHORT')
    for text in benign:
        for kind, pat in VALUE_PATTERNS.items():
            assert not pat.search(text), f'{kind}가 평범한 코드를 잡는다: {text!r}'

    for name in ('.env.production', 'config/.env.vercel', 'data/token.json',
                 'certs/server.pem', '.ssh/id_rsa'):
        assert any(p.search(name) for p in FILENAME_PATTERNS), f'{name}을 못 잡는다'
    for name in ('.env.example', 'src/env_utils.py', 'docs/tokens.md'):
        assert not (any(p.search(name) for p in FILENAME_PATTERNS)
                    and not FILENAME_ALLOW.search(name)), f'{name}을 헛잡는다'
