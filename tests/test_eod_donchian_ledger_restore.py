"""심9-1 매매기록은 복원한 뒤에 쓰고 배포해야 한다.

2026-09-16 실측으로 드러난 소실: `eod_data.yml`의 상태 복원 스텝은 db-data에서
`sim_donchian_state.json`과 `market_calendar.json`만 가져오는데, 배포 스텝은
`trade_history_sim_donchian.csv`를 db-data에 **덮어쓴다.** 러너의 그 CSV는 매 런
백지에서 시작하므로, 거래가 난 런마다 db-data의 누적 이력이 **그 런의 거래만
남기고 초기화**된다.

증거(db-data `461a04f85` 기준):
  - `sim_donchian_state.json`의 `daily_trades` 8건(08-19×2, 08-21, 08-31, 09-04×3, 09-08)
  - `trade_history_sim_donchian.csv`는 데이터 **2행**, 전부 09-08 16:02
  - 보유 5종목의 entry_date(08-25, 08-31, 09-04×2, 09-08) 중 09-08 건만 CSV에 있다

심11이 멀쩡한 이유는 장중 루프에서 돌고 `trading.yml`이 `git checkout db-data -- data/`로
data/ 전체를 복원하기 때문이다. EOD 배치만 파일을 골라 복원해서 이 비대칭이 생겼다.

이건 [[eod-deploy-git-add-atomicity]]와 같은 자리다 — 그때는 배포가 안 됐고
이번엔 배포는 되는데 **복원이 빠져서** 덮어쓴다. 배포 목록과 복원 목록이 갈리면
누적 파일은 조용히 잘린다.
"""
import os
import re

WF = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows', 'eod_data.yml')


def _wf():
    with open(WF, encoding='utf-8') as f:
        return f.read()


def _restore_block(wf):
    """상태 복원 스텝(db-data clone → cp) 본문."""
    m = re.search(r'Run EOD simulators.+?(?=\n      - name: )', wf, re.S)
    assert m, '상태 복원 스텝을 못 찾았다 — 워크플로 구조가 바뀌었다'
    return m.group(0)


def _deploy_block(wf):
    m = re.search(r'Deploy CSV to db-data.+?(?=\n      - name: )', wf, re.S)
    assert m, '배포 스텝을 못 찾았다 — 워크플로 구조가 바뀌었다'
    return m.group(0)


def test_the_donchian_ledger_is_restored_before_the_sim_runs():
    """복원하지 않으면 심이 백지 CSV에 쓰고, 배포가 그걸로 db-data를 덮는다."""
    restore = _restore_block(_wf())
    assert 'trade_history_sim_donchian.csv' in restore, (
        '심9-1 매매기록을 복원하지 않는다 — 거래가 난 런마다 db-data의 누적 이력이 '
        '그 런의 거래만 남기고 초기화된다')


def test_every_accumulating_file_the_deploy_writes_is_also_restored():
    """배포 목록과 복원 목록이 갈리면 누적 파일이 잘린다.

    상태 JSON은 심이 통째로 다시 쓰므로 복원만 하면 되고(이미 한다), 매매기록
    CSV는 **append**라 복원이 빠지면 잘린다. 여기서는 배포가 건드리는 누적
    파일(매매기록 CSV)만 본다 — 감시목록처럼 매번 새로 만드는 산출물은 대상이 아니다.
    """
    wf = _wf()
    deploy, restore = _deploy_block(wf), _restore_block(wf)

    accumulating = sorted(set(re.findall(r'trade_history_\w+\.csv', deploy)))
    assert accumulating, '배포 스텝에서 매매기록 CSV를 하나도 못 찾았다 — 추출이 깨졌다'

    missing = [f for f in accumulating if f not in restore]
    assert not missing, (
        f'{missing}는 배포되는데 복원되지 않는다 — 러너의 백지 사본이 db-data의 '
        f'누적 이력을 덮는다')
