"""US 워크플로가 텔레그램 시크릿을 실행 스텝에 넘기는지 검증한다.

scripts/run_eod_sim_us.py와 scripts/us_trade_loop.py는 실패·결손을 alerts.send_alert로
사람에게 보낸다. 그런데 TelegramManager는 TELEGRAM_BOT_TOKEN/CHAT_ID를 **환경변수에서만**
읽는다 — 워크플로가 안 넘기면 알림 코드는 있는데 한 통도 안 나가고, 실패는 예전처럼
Actions 로그에만 남는다. 그러면 알림을 넣은 의미가 없다.

2026-08-26 확인: 두 워크플로 다 이 배선이 없었다(국내 trading.yml에는 있다).
"""
import os

import yaml

WF_DIR = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows')
REQUIRED = {'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'}

# (워크플로 파일, 알림을 내는 스크립트를 실행하는 스텝의 run 문자열 일부)
CASES = [
    ('us_trading.yml', 'scripts/us_trade_loop.py'),
    ('us_eod_watchlist.yml', 'scripts/run_eod_sim_us.py'),
]


def _run_step_env(workflow: str, run_contains: str) -> dict:
    with open(os.path.join(WF_DIR, workflow), encoding='utf-8') as f:
        wf = yaml.safe_load(f)
    for job in wf['jobs'].values():
        for step in job.get('steps', []):
            if run_contains in (step.get('run') or ''):
                # 잡 레벨 env도 스텝에 상속된다.
                return {**(job.get('env') or {}), **(step.get('env') or {})}
    raise AssertionError(f'{workflow}에서 `{run_contains}` 실행 스텝을 못 찾았다')


def test_alerting_scripts_receive_telegram_secrets():
    for workflow, run_contains in CASES:
        env = _run_step_env(workflow, run_contains)
        missing = REQUIRED - set(env)
        assert not missing, (
            f'{workflow}의 {run_contains} 스텝에 {sorted(missing)}가 없다 — '
            '장애 알림이 한 통도 안 나간다')
        for key in REQUIRED:
            assert f'secrets.{key}' in env[key], (
                f'{workflow}의 {key}가 시크릿에서 오지 않는다: {env[key]!r}')
