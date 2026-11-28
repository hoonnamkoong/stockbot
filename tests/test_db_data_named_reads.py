# -*- coding: utf-8 -*-
"""db-data에서 **이름이 정해진 파일만** 읽는 자리는 713MB를 받지 않는다.

네 워크플로가 db-data에서 파일 한두 개를 읽는데, 쓰던 방식이

    git fetch --depth 1 origin db-data
    git checkout FETCH_HEAD -- data/<파일>

였다. 앞줄이 그 커밋의 **블롭 전부**를 받는다 — 2026-11-27 실측 **42초 / 130MB**
(작업 트리로 펴면 713MB). 달력 1,982바이트를 읽으려고 그걸 낸다.

제일 아픈 자리는 `heartbeat_watch.yml`이다. 예산 5분 중 42초를 여기 쓰고, 이
워크플로가 잘리면 **고장을 알려줄 사람 경로가 사라진다**(2026-11-26 MTTR 6.5시간).
`dart_fundamentals.yml`은 11-25 첫 채움 런이 119분에 잘렸고 다음 보충 런이
11-29 05:00 KST 하나뿐이다.

`git fetch --filter=blob:none`을 그 자리에 붙이는 것으로는 **안 된다**. fetch는
1초로 줄지만 뒤의 `git checkout`이 `unable to read sha1 file`로 깨진다 —
actions/checkout이 만든 저장소는 부분 클론이 아니라서 빠진 블롭을 받아올
promisor가 없다(`extensions.partialClone`을 손으로 넣어도 같았다). 그래서 별도
디렉터리에 부분 클론을 만든다: **2초 / 426KB**.
"""
import glob
import os
import re
import subprocess

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
WF_DIR = os.path.join(ROOT, '.github', 'workflows')
HELPER = os.path.join(ROOT, 'scripts', 'fetch_db_data_files.sh')

# `git checkout <db-data 어딘가> -- data/<파일>` — 끝이 `data/`로 그치는 것은
# 트리 전체 복원이라 여기 해당하지 않는다(trading.yml·scraper.yml이 그 모양이고,
# 그쪽은 sparse 범위로 따로 줄인다).
_NAMED_READ = re.compile(
    r'git\s+checkout\s+(?:FETCH_HEAD|db-data|origin/db-data)\s+--\s+data/\S')

# 이 스크립트를 부르는 것으로 바뀐 자리들. 열거하는 이유: 누가 한 자리를 옛
# 방식으로 되돌리면 위 정규식이 잡지만, **스텝을 통째로 지우면** 아무도 안 잡는다.
_CALLERS = (
    'heartbeat_watch.yml',
    'token_refresh.yml',
    'dart_fundamentals.yml',
    'us_eod_watchlist.yml',
)


def _steps():
    for path in sorted(glob.glob(os.path.join(WF_DIR, '*.yml'))):
        with open(path, encoding='utf-8') as f:
            doc = yaml.safe_load(f)
        for job in (doc.get('jobs') or {}).values():
            for step in job.get('steps') or []:
                if step.get('run'):
                    yield os.path.basename(path), step.get('name') or '(이름 없음)', step['run']


def _code_only(body: str) -> str:
    """주석을 뺀 본문. 주석에 적은 옛 명령 예시가 검사를 깨뜨리면 안 된다."""
    return '\n'.join(ln for ln in body.split('\n')
                     if not ln.lstrip().startswith('#'))


def test_지정_파일_읽기에_트리_전체_체크아웃이_남아_있지_않다():
    """한 파일을 읽으려고 블롭 전부를 받는 자리가 다시 생기면 여기서 잡는다."""
    hits = [(wf, name) for wf, name, body in _steps()
            if _NAMED_READ.search(_code_only(body))]
    assert not hits, (
        f'지정 파일을 읽는데 db-data 전체를 받는 자리: {hits}. '
        'scripts/fetch_db_data_files.sh를 쓸 것(42초/130MB → 2초/426KB)')


def test_네_자리가_모두_헬퍼를_부른다():
    calls = {wf for wf, _, body in _steps()
             if 'fetch_db_data_files.sh' in _code_only(body)}
    missing = set(_CALLERS) - calls
    assert not missing, f'헬퍼를 부르지 않는 워크플로: {missing}'


def test_헬퍼가_부분_클론을_쓴다():
    """`--filter=blob:none`이 빠지면 조용히 130MB로 돌아간다 — 느려질 뿐 결과는
    같아서 아무 알림도 안 난다.

    ⚠ **주석을 세면 안 된다.** 이 검사의 첫 버전은 파일 전체에서 문자열을 찾았고,
    `--filter=blob:none`이 스크립트 주석에도 나오는 탓에 clone 줄에서 플래그를
    지워도 통과했다(2026-11-27 변이 리허설에서 발각). 오늘 같은 함정을 두 번째로
    밟았다 — 앞엣것은 trading.yml 호출 횟수를 세던 테스트였다.
    """
    with open(HELPER, encoding='utf-8') as f:
        code = _code_only(f.read())
    clone = [ln for ln in code.split('\n') if 'git clone' in ln]
    assert len(clone) == 1, f'clone 줄이 {len(clone)}개 — 검사가 모호해진다'
    for flag in ('--filter=blob:none', '--sparse', '--depth 1'):
        assert flag in clone[0], f'clone 줄에 {flag}가 없다: {clone[0].strip()}'
    assert 'sparse-checkout set --no-cone' in code, '범위 설정이 없다'


def test_헬퍼는_인자가_없으면_거부한다():
    """경로를 안 넘기면 아무것도 안 받는다 — 빈 범위로 조용히 성공하면 호출부가
    '없음'으로 읽는다."""
    # errors='replace': 윈도우 로컬에서 기본 코덱(cp949)이 한글 stderr를 못 읽어
    # 리더 스레드가 UnicodeDecodeError로 죽는다(CI는 UTF-8이라 안 난다).
    r = subprocess.run(['bash', HELPER], capture_output=True, text=True,
                       errors='replace', cwd=ROOT)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)


def test_헬퍼가_토큰을_로그에_흘리지_않는다():
    """public 레포다(2026-09-10 .env.production 6개월 노출 사고)."""
    with open(HELPER, encoding='utf-8') as f:
        body = f.read()
    assert 'x-access-token:***@' in body, 'URL 마스킹이 없다'
    # 토큰을 echo하는 줄이 없어야 한다.
    for ln in body.split('\n'):
        if ln.lstrip().startswith('echo') or ln.lstrip().startswith('printf'):
            assert 'GITHUB_TOKEN' not in ln and '$url' not in ln, ln


def test_호출_스텝이_토큰을_받는다():
    """`GITHUB_TOKEN`은 Actions가 자동으로 넣어 주지 않는다. 없으면 비인증
    클론으로 떨어지는데(public이라 되긴 한다) 레이트리밋을 공유한다."""
    missing = []
    for path in sorted(glob.glob(os.path.join(WF_DIR, '*.yml'))):
        with open(path, encoding='utf-8') as f:
            doc = yaml.safe_load(f)
        for job in (doc.get('jobs') or {}).values():
            for step in job.get('steps') or []:
                body = step.get('run') or ''
                if 'fetch_db_data_files.sh' not in _code_only(body):
                    continue
                if 'GITHUB_TOKEN' not in (step.get('env') or {}):
                    missing.append((os.path.basename(path), step.get('name')))
    assert not missing, f'GITHUB_TOKEN을 안 받는 호출 스텝: {missing}'


def test_script_disables_msys_path_translation():
    """`/data/...` sparse 패턴이 Git Bash에서 윈도우 경로로 번역되지 않아야 한다.

    MSYS는 네이티브 git에 넘기는 인자의 선두 `/`를 `C:/Program Files/Git/...`로
    바꾼다. 그러면 sparse 범위가 아무것도 안 집고, **클론은 성공하는데 파일만
    0개**가 되어 스크립트가 "db-data에 없음"을 찍는다 — 2026-11-27에 실제로
    12,098바이트로 존재하는 파일을 그렇게 보고했다.

    CI(리눅스)에서는 생기지 않으므로 이 한 줄이 지우기 쉽고, 지워도 CI는 초록이다.
    고장은 **로컬 리허설만** 거짓 음성이 되는 쪽으로 나타난다. 그래서 테스트로 박는다.
    """
    src = open(os.path.join(ROOT, 'scripts', 'fetch_db_data_files.sh'), encoding='utf-8').read()
    assert 'MSYS_NO_PATHCONV=1' in src
