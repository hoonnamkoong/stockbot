"""KIS를 쓰는 워크플로가 토큰의 유일 발급자 경로에 붙어 있는지 검증한다.

토큰 발급자는 scripts/token_manager.py 하나다(kis-token-pipeline). 그런데 발급자를
안 거쳐도 KIS 호출은 성공한다 — src/trade/auth.py에 자가발급 안전망이 있기 때문이다.
GH_PAT까지 없으면 그 안전망은 비공개 레포를 **읽지도 쓰지도** 않고 매 런 새 토큰을
발급한다. 흔적이 stockbot-secret에 안 남아서 커밋 이력을 봐도 안 보인다.

2026-09-04 실측: premarket_data.yml의 collect·intraday 두 잡이 이 상태였고,
하루 4~5회 추가 발급이 있었다(07:20·07:46·09:00·09:10 KST). 로그:
  [Auth] ⚠️ 경고: GH_PAT 환경 변수가 없어 GitHub 연동 캐시를 사용할 수 없습니다.
  [Auth] KIS로부터 새 토큰 발급 시도 (실전)...
  [Auth] Skip: GH_PAT가 없어 원격 동기화를 수행하지 않습니다.

한 워크플로만 고치면 다음에 KIS를 쓰는 워크플로가 생길 때 또 조용히 뚫린다
(sync-files-list-stale-hardcode와 같은 모양). 그래서 파일 목록이 아니라 **규칙**으로
검사한다.
"""
import os

import yaml

WF_DIR = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows')
TOKEN_MANAGER = 'scripts/token_manager.py'


def _effective_env(job: dict, step: dict) -> dict:
    """잡 레벨 env는 스텝에 상속된다."""
    return {**(job.get('env') or {}), **(step.get('env') or {})}


def _kis_jobs():
    """KIS 자격증명을 스텝에 넘기는 (파일, 잡 이름, 잡) 목록."""
    for name in sorted(os.listdir(WF_DIR)):
        if not name.endswith('.yml'):
            continue
        with open(os.path.join(WF_DIR, name), encoding='utf-8') as f:
            wf = yaml.safe_load(f)
        for job_name, job in (wf.get('jobs') or {}).items():
            steps = job.get('steps') or []
            if any('KIS_APP_KEY' in _effective_env(job, s) for s in steps):
                yield name, job_name, job


def test_kis_jobs_run_the_single_token_issuer():
    """KIS를 쓰는 잡은 token_manager를 먼저 돌려 유효 토큰을 내려받아야 한다."""
    missing = []
    for name, job_name, job in _kis_jobs():
        steps = job.get('steps') or []
        if not any(TOKEN_MANAGER in (st.get('run') or '') for st in steps):
            missing.append(f'{name}:{job_name}')
    assert not missing, (
        f'{missing} 잡이 token_manager 없이 KIS를 쓴다 — '
        'auth.py 자가발급 안전망이 매 런 새 토큰을 발급한다')


def test_token_manager_step_receives_gh_pat():
    """발급자 스텝에 GH_PAT가 없으면 비공개 레포를 못 읽어 결국 새로 발급한다.

    뒤따르는 KIS 호출 스텝에는 GH_PAT가 필요 없다 — token_manager가 이미 유효
    토큰을 data/kis_token_cache.json에 내려놓았고, auth.py는 로컬 캐시를 먼저 본다.
    """
    for name, job_name, job in _kis_jobs():
        for step in job.get('steps') or []:
            if TOKEN_MANAGER not in (step.get('run') or ''):
                continue
            env = _effective_env(job, step)
            assert 'GH_PAT' in env, (
                f'{name}:{job_name}의 token_manager 스텝에 GH_PAT가 없다 — '
                '비공개 레포를 못 읽어 새 토큰을 발급한다')
            assert 'secrets.GH_PAT' in env['GH_PAT'], (
                f'{name}:{job_name}의 GH_PAT가 시크릿에서 오지 않는다: {env["GH_PAT"]!r}')
