"""워크플로 사이의 파일 소유권 — 같은 파일을 둘이 배포하면 조용히 되돌아간다.

2026-08-08 구조 변경으로 국면(리베로)의 writer가 trading.yml로 옮겨갔다.
그런데 scraper.yml의 배포 스텝은 `data/*.json`·`data/*.csv`를 통째로 밀기 때문에,
제외하지 않으면 이 런이 **시작할 때 받아온 사본**으로 국면을 되돌린다.
두 워크플로는 concurrency 그룹이 달라 실제로 동시에 도므로 상시 일어난다.

되돌림은 실패로 안 보인다 — 워크플로는 초록색이고 국면 값만 몇 분 과거다.
그래서 코드가 아니라 배포 규칙 자체를 테스트한다.
"""
import fnmatch
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

WF = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows')


def _text(name: str) -> str:
    with open(os.path.join(WF, name), encoding='utf-8') as f:
        return f.read()


def _regime_files() -> list[str]:
    """국면 갱신이 쓰는 파일 — 매니페스트에서 파생한다(심 이름이 바뀌어도 따라간다)."""
    from scripts.trade_loop import regime_output_files
    return regime_output_files(__import__('datetime').datetime(2026, 8, 10, 11, 0))


def test_scraper_does_not_deploy_regime_files():
    scraper = _text('scraper.yml')
    # 배포 스텝의 case 문에 제외로 등장해야 한다.
    deploy = scraper.split('Deploy Data to db-data branch', 1)[1]
    # case 문의 제외 arm은 `a.json|b.csv) continue ;;` 처럼 묶여 있을 수 있다.
    # 파일명이 있는 줄에 continue가 함께 있으면 제외된 것으로 본다.
    skipped = {line for line in deploy.splitlines() if 'continue' in line}
    # regime_observations*.csv 처럼 case arm이 글롭일 수 있다(월별 파일명이라
    # 정적 텍스트가 정확한 이름을 담을 수 없다) — 문자열 포함이 아니라 글롭으로 맞춘다.
    patterns = [p.strip() for line in skipped
                for p in line.strip().split(')', 1)[0].split('|')]
    for name in _regime_files():
        assert any(fnmatch.fnmatch(name, p) for p in patterns), (
            f'{name}이 scraper.yml 배포 제외 목록에 없다. trading.yml이 유일 '
            f'writer인데 여기서 올리면 런 시작 시점 사본으로 국면이 되돌아간다.')


def test_trading_deploys_only_what_the_manifest_lists():
    """trading.yml은 data/ 전체가 아니라 매니페스트에 적힌 것만 올려야 한다 —
    전체를 밀면 스크래퍼가 방금 갱신한 산출물을 낡은 사본으로 되돌린다."""
    trading = _text('trading.yml')
    assert '.lite_deploy_manifest' in trading
    assert 'cp -r data/' not in trading, 'data/ 전체 복사가 있으면 스크래퍼 산출물을 되돌린다'


def test_the_two_workflows_do_not_share_a_concurrency_group():
    """그룹을 공유하면 매매의 대기 트리거가 새 디스패치에 밀려 취소된다 —
    GitHub concurrency는 FIFO 큐가 아니라 '실행 중 1개 + 대기 1개'만 유지한다."""
    def group(name):
        m = re.search(r'concurrency:\s*\n\s*group:\s*(\S+)', _text(name))
        assert m, f'{name}에 concurrency 그룹이 없다'
        return m.group(1)

    assert group('scraper.yml') != group('trading.yml')


def test_trading_can_dispatch_the_scraper():
    """actions: write가 없으면 dispatch가 403으로 조용히 실패하고, 스크래핑이
    영영 안 돈다(매매는 계속 돌아서 알아채기 어렵다)."""
    trading = _text('trading.yml')
    assert re.search(r'permissions:.*?\n(?:\s+\w+:\s*\w+\n)*?\s+actions:\s*write',
                     trading, re.S), 'trading.yml에 actions: write 권한이 필요하다'


def test_scraper_is_not_wired_to_the_tasker_event_anymore():
    """태스커는 trading.yml을 부른다. scraper.yml이 같은 이벤트를 계속 듣고
    있으면 두 워크플로가 모두 2분마다 떠서 분리한 의미가 사라진다."""
    scraper = _text('scraper.yml')
    on_block = scraper.split('jobs:', 1)[0]
    assert 'tasker_trigger]' not in on_block
    assert re.search(r'types:\s*\[tasker_trigger\b(?!_)', on_block) is None


def test_both_workflows_notify_on_failure():
    """조용히 죽으면 안 된다. 매매는 돈이 걸려 있고, 스크래퍼는 죽어도 매매가
    계속 돌기 때문에 오히려 알아채기 어렵다."""
    for name in ('scraper.yml', 'trading.yml'):
        assert 'if: failure()' in _text(name), f'{name}에 실패 알림이 없다'


def test_trading_has_a_manual_holiday_bypass():
    """휴장 판정 실패 알림이 안내하는 복구 경로다. trading.yml에 force_run이
    없으면 실전 매매를 수동으로 되살릴 방법이 없다 — 스크래퍼의 force_run은
    스크래핑만 되살리고, 버즈 불필요 심의 주문은 trading.yml에만 있다."""
    trading = _text('trading.yml')
    assert 'force_run' in trading, 'trading.yml에 force_run 입력이 없다'
    assert 'FORCE_RUN:' in trading, 'force_run 입력이 파이썬에 전달되지 않는다'


def test_scraper_accepts_and_forwards_the_regime_handed_to_it():
    """trade_loop가 dispatch inputs로 국면을 실어 보낸다. 입력이 선언돼 있지
    않으면 GitHub이 422로 거절하고, dispatch 자체가 실패해 **스크래핑이 통째로
    멈춘다** — 로그에만 남는 조용한 실패다."""
    scraper = _text('scraper.yml')
    on_block = scraper.split('jobs:', 1)[0]
    assert re.search(r'^\s+regime:\s*$', on_block, re.M), \
        'scraper.yml에 regime 입력이 선언돼 있지 않다'
    assert 'REGIME_HINT:' in scraper, 'regime 입력이 파이썬에 전달되지 않는다'


def test_scraper_deploy_consults_the_runtime_exclude_list():
    """선택 심의 페이퍼 쌍둥이는 정적 case문으로 못 막는다 — 어느 심인지는
    program_trading.json이 정하므로 런타임에만 안다. Stage 3에서 안 돌리는 것만으로는
    부족하다: 배포 스텝의 cp는 심을 돌렸는지와 무관하게 **런 시작 시점 사본**을
    올려 그 사이 trading.yml이 push한 4~5분치를 되돌린다(2026-08-09)."""
    from src.pipeline.orchestrator import DEPLOY_EXCLUDE_REL
    name = os.path.basename(DEPLOY_EXCLUDE_REL)
    deploy = _text('scraper.yml').split('Deploy Data to db-data branch', 1)[1]

    assert name in deploy, f'배포 스텝이 {name}을 읽지 않는다'
    # json·csv 두 루프 모두에 걸려야 한다. 상태 파일만 막고 거래 이력을 되돌리면
    # 대시보드의 페이퍼 성과가 실계좌와 갈라진다.
    json_loop, csv_loop = deploy.split('for f in data/*.csv', 1)
    assert 'owned_by_trading' in json_loop.split('for f in data/*.json', 1)[1]
    assert 'owned_by_trading' in csv_loop


def test_scraper_deploys_the_report_gate_state():
    """리포트 슬롯 상태의 writer는 scraper.yml이다(리포트가 그쪽 소관이다).

    **이게 db-data를 왕복하지 못하면 슬롯이 영원히 안 닫힌다.** 매 런이 새
    컨테이너라 "아직 안 보냈다"로 읽고, 40분 창 안의 스크래핑 네 번이 전부
    리포트를 발송한다 — 하루 2회 합의가 하루 8회가 된다.

    별도 조치가 필요한 게 아니라 `data/*.json` 기본 경로에 걸리면 된다.
    여기서 지키는 건 "누가 실수로 제외 목록에 넣지 않았는가"다.
    """
    from src.report.gate import STATE_FILENAME
    deploy = _text('scraper.yml').split('Deploy Data to db-data branch', 1)[1]
    skipped = {line for line in deploy.splitlines() if 'continue' in line}

    assert 'for f in data/*.json' in deploy, 'json 배포 루프가 사라졌다'
    assert not any(STATE_FILENAME in line for line in skipped), (
        f'{STATE_FILENAME}이 배포 제외에 들어갔다 — 슬롯이 영원히 안 닫힌다')


def test_trading_does_not_deploy_the_report_gate_state():
    """writer는 하나여야 한다. trading.yml이 런 시작 시점 사본을 올리면
    스크래퍼가 방금 닫은 슬롯이 다시 열린다(lost update)."""
    from src.report.gate import STATE_FILENAME
    import scripts.trade_loop as trade_loop

    now = __import__('datetime').datetime(2026, 8, 10, 11, 0)
    names = trade_loop.regime_output_files(now) + trade_loop.money_output_files(now)
    assert STATE_FILENAME not in names


def test_scraper_deploys_the_sim_diag_logs():
    """진단 CSV(`sim1_diag_YYYY-MM.csv`)는 scraper.yml의 `data/*.csv` 기본 경로로
    나간다. 2026-08-09에 db-data의 diag 파일이 0개인 것이 드러났는데, 원인이
    '쓰기 실패'인지 '배포 누락'인지 가르려면 배포 쪽을 먼저 고정해야 한다.

    여기가 통과하는데도 파일이 없으면 원인은 쓰기 쪽이다(로그가 이제 말해준다).

    sim1은 이 목록에 없다 — 여전히 이 기본 경로가 유일 배포자다."""
    from scripts.trade_loop import DIAG_LOG_SIM_IDS

    deploy = _text('scraper.yml').split('Deploy Data to db-data branch', 1)[1]
    skipped = {line for line in deploy.splitlines() if 'continue' in line}

    assert 'for f in data/*.csv' in deploy, 'csv 배포 루프가 사라졌다'
    assert not any('sim1_diag' in line for line in skipped), (
        'sim1_diag CSV가 배포 제외에 들어갔다 — 진단이 db-data에 영영 도달하지 못한다')


def test_scraper_does_not_deploy_the_diag_logs_owned_by_trading():
    """sim6/9/12/13은 버즈 불필요 심이라 trading.yml의 60초 루프로 옮겨갔고,
    그 diag는 거기서 매 사이클 배포한다(DIAG_LOG_SIM_IDS). scraper.yml도 같은
    파일을 밀면 두 writer가 경합해 push가 non-fast-forward로 계속 실패한다
    (2026-08-24, 하루 4번 실패 알림)."""
    from scripts.trade_loop import DIAG_LOG_SIM_IDS

    deploy = _text('scraper.yml').split('Deploy Data to db-data branch', 1)[1]
    skipped = {line for line in deploy.splitlines() if 'continue' in line}
    patterns = [p.strip() for line in skipped
                for p in line.strip().split(')', 1)[0].split('|')]

    for diag_prefix in DIAG_LOG_SIM_IDS.values():
        name = f'{diag_prefix}_diag_2026-08.csv'
        assert any(fnmatch.fnmatch(name, p) for p in patterns), (
            f'{name}이 scraper.yml 배포 제외 목록에 없다. trading.yml이 유일 '
            f'writer인데 여기서 올리면 push 충돌이 반복된다.')


def test_scraper_does_not_deploy_money_files():
    """순위 스냅샷의 writer는 trading.yml이다. scraper가 `data/*.json`·`*.csv`를
    통째로 밀면 `rank_state.json`이 런 시작 시점 사본으로 되돌아가고, 그러면
    **매 사이클이 warmup이 되어 delta가 영원히 빈다** — 신호가 통째로 사라진다.
    2026-08-08 국면 파일에서 똑같은 함정을 겪었다."""
    deploy = _text('scraper.yml').split('Deploy Data to db-data branch', 1)[1]
    skipped = {line for line in deploy.splitlines() if 'continue' in line}
    for pat in ('rank_state.json', 'money_'):
        assert any(pat in line for line in skipped), (
            f'{pat}가 scraper.yml 배포 제외에 없다')


# ── 미국장 마감 브리핑(09:00 KST) 슬롯 상태 ──────────────────────────

def test_us_brief_gate_state_is_not_a_regime_file():
    """브리핑 게이트는 국면 파일이 아니다 — 국면 목록에 얹으면 안 된다.

    `_write_deploy_manifest`는 `regime_output_files()`를 `include_regime`
    (=그 사이클에 국면을 갱신했는가)일 때만 매니페스트에 넣는다. 국면 갱신은
    10분 격자이고 브리핑 창은 40분·2분 간격(20 트리거)이라, 브리핑을 보낸
    사이클이 마침 국면도 갱신한 사이클일 확률은 5분의 1이다. 나머지에서는
    게이트 상태가 db-data에 도달하지 못해 다음 트리거가 '아직 안 보냈다'로
    읽고 브리핑이 반복 발송된다 — 이 배선이 막으려던 실패를 이 배선이 만든다.
    """
    from src.report.gate import US_BRIEF_STATE_FILENAME
    import scripts.trade_loop as trade_loop

    now = __import__('datetime').datetime(2026, 9, 1, 9, 5)
    assert US_BRIEF_STATE_FILENAME not in trade_loop.regime_output_files(now)


def test_trading_deploys_the_us_brief_gate_state_on_a_send_only_cycle(tmp_path, monkeypatch):
    """국면·매매·순위가 전부 없고 브리핑만 보낸 사이클에서도 올라가야 한다.

    db-data를 왕복하지 못하면 매 런이 새 컨테이너라 '아직 안 보냈다'로 읽고
    09:00~09:40 창의 20번 트리거가 전부 브리핑을 보낸다.
    """
    from src.report.gate import US_BRIEF_STATE_FILENAME
    import scripts.trade_loop as trade_loop

    monkeypatch.chdir(tmp_path)
    now = __import__('datetime').datetime(2026, 9, 1, 9, 5)
    trade_loop._write_deploy_manifest(None, log=lambda *_: None, now=now,
                                      include_us_brief=True)

    written = (tmp_path / 'data' / '.lite_deploy_manifest').read_text(encoding='utf-8')
    assert US_BRIEF_STATE_FILENAME in written.split()


def test_scraper_excludes_the_us_brief_gate_state():
    """국내 리포트 게이트와 **반대 방향**의 소유권이다.

    report_gate_state.json은 scraper.yml이 배포하고 trading.yml이 안 한다.
    us_brief_gate_state.json은 그 반대다 — 그래서 scraper.yml의 `data/*.json`
    루프가 이 파일을 명시적으로 건너뛰어야 한다. 안 그러면 스크래퍼가 런 시작
    시점 사본을 올려 trading.yml이 방금 닫은 슬롯이 다시 열린다.
    """
    from src.report.gate import US_BRIEF_STATE_FILENAME
    deploy = _text('scraper.yml').split('Deploy Data to db-data branch', 1)[1]
    skipped = {line for line in deploy.splitlines() if 'continue' in line}
    patterns = [p.strip() for line in skipped
                for p in line.strip().split(')', 1)[0].split('|')]
    assert any(fnmatch.fnmatch(US_BRIEF_STATE_FILENAME, p) for p in patterns), (
        f'{US_BRIEF_STATE_FILENAME}이 scraper.yml 배포 제외 목록에 없다 — '
        f'writer가 둘이 되어 09:00~09:40에 브리핑이 반복 발송된다.')


# ── premarket_data.yml intraday 잡: gzip 커밋 ─────────────────────────

def _intraday_commit_step() -> str:
    """intraday 잡의 **커밋 스텝만** 잘라낸다.

    같은 잡의 `Restore universe (db-data)`는 db-data를 읽는 게 맞다(유니버스는
    거기 있다). 잡 전체를 훑으면 그 정상 참조까지 걸리므로 스텝 단위로 자른다.
    """
    intraday = _text('premarket_data.yml').split('  intraday:', 1)[1]
    step = intraday.split('- name: 커밋 (intraday-data)', 1)[1]
    return step.split('- name: Notify on failure', 1)[0]


def test_intraday_is_committed_compressed():
    """원시 CSV는 100MB 한도를 넘는다(2026-08-31 실측 115.14MB).

    첫 실행에서 push가 거부됐고, rebase 재시도는 크기를 안 바꾸므로 3회가
    전부 같은 이유로 죽었다.
    """
    step = _intraday_commit_step()
    assert 'gzip' in step, 'intraday 커밋이 압축하지 않는다'
    assert 'rt_intraday_*.csv.gz' in step


def test_intraday_fails_loudly_when_still_too_large():
    """압축 후에도 한도를 넘으면 조용히 잘리지 않고 실패해야 한다."""
    assert '104857600' in _intraday_commit_step(), '압축 후 크기 검사가 없다'


def test_intraday_archive_never_lands_on_db_data():
    """장중 아카이브는 **db-data에 쌓으면 안 된다.**

    세션당 ~14MB가 보존정책 없이 누적되는데, trading.yml은 2분마다
    `git fetch --depth 1 origin db-data`를 하고 잡 타임아웃이 3분이다(주문 락
    리스 4분보다 일부러 짧다). 몇 주면 클론만으로 예산을 먹고 주문 루프
    한가운데서 타임아웃 → 리스가 만료될 때까지 살아 있는 런이 생긴다.
    누군가 이 커밋을 db-data로 되돌리면 여기서 걸려야 한다.
    """
    # 주석에는 'db-data'가 나온다(왜 분리했는지를 적은 문단이다). 실행되는
    # 줄만 본다.
    code = ' '.join(ln for ln in _intraday_commit_step().splitlines()
                    if not ln.strip().startswith('#'))
    assert 'db-data' not in code, (
        'intraday 아카이브가 db-data를 향하고 있다 — 매매 핫 패스의 클론이 '
        '무한히 무거워져 주문 루프가 타임아웃한다.')
    assert 'intraday-data' in code, 'intraday 아카이브의 대상 브랜치가 없다'


def test_intraday_branch_is_created_as_orphan_when_missing():
    """intraday-data는 아직 없다. db-data/main에서 갈라내면 그 트리를 통째로
    끌고 오므로 분리한 의미가 사라진다 — 고아 브랜치여야 한다."""
    step = _intraday_commit_step()
    assert 'git -C intraday_repo init' in step, (
        'intraday-data가 없을 때의 생성 경로가 없다 — 첫 실행이 클론 실패로 죽는다.')
    assert '--orphan' not in step, (
        'checkout --orphan은 기존 워킹트리를 물고 온다. 빈 init이어야 한다.')
