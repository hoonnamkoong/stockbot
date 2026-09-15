"""심11 감시목록 깔때기(diag)가 db-data까지 실제로 나가는지 지킨다.

2026-09-15에 심11 감시목록 생성 경로(build_sim11_watchlist)에 깔때기를 붙였다.
후보 100 → 감시목록 1이 평상시 값인 심인데 그 99가 어느 게이트에서 떨어졌는지
아무 데도 안 남아서, "KIS가 실적을 안 줬다(결손)"와 "실적이 기준 미달(전략)"을
구분할 수 없었기 때문이다.

그런데 깔때기를 붙이는 것과 그 파일이 db-data에 도착하는 것은 다른 축이다.
Actions 로그는 며칠이면 사라지므로, 파일이 안 나가면 분포를 소급할 수 없다 —
계측을 붙여 놓고 결과를 못 보는 상태가 된다. 그리고 이 레포의 배포 목록은
리터럴 파일명을 손으로 나열하는 구조라(2026-08-05 심9-1이 한 줄 git add의
원자성 때문에 db-data에 한 번도 반영되지 못했던 자리와 같다) 새 파일은
조용히 빠진다.
"""
import os
import re

from src.data.sim_diag import day_path

WF_DIR = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows')
DIAG_SIM = 'sim11_watchlist'


def _read(name):
    with open(os.path.join(WF_DIR, name), encoding='utf-8') as f:
        return f.read()


def test_diag_filename_is_what_we_think_it_is():
    """배포 목록이 맞는지 보려면 파일명 규칙이 먼저 고정돼야 한다."""
    name = os.path.basename(day_path(DIAG_SIM, '20260915'))
    assert name == 'sim11_watchlist_diag_2026-09-15.csv'


def test_eod_workflow_deploys_the_watchlist_funnel():
    """쓰는 쪽(eod_data.yml)이 db-data로 밀어야 한다.

    감시목록 자체(sim11_watchlist.json)와 같은 배포 루프에 있어야 한다 —
    둘은 같은 배치가 같은 순간에 만드는 한 쌍이다.
    """
    wf = _read('eod_data.yml')
    assert re.search(r'sim11_watchlist_diag_\*\.csv', wf), (
        'eod_data.yml 배포 목록에 심11 감시목록 깔때기가 없다 — '
        '계측은 도는데 결과가 db-data에 도착하지 않는다')


def test_scraper_does_not_race_the_eod_writer_for_it():
    """읽기만 하는 쪽(scraper.yml)은 되밀지 않아야 한다.

    scraper.yml은 db-data의 data/를 러너로 체크아웃한 뒤 `data/*.csv`를
    통째로 되민다(제외 목록에 없으면 전부 나간다 — fail-open). 이 파일의
    writer는 eod_data.yml인데, 마감 직후 두 워크플로가 겹치면 scraper가
    들고 있던 옛 사본이 갓 쓰인 파일을 덮는다. sim6/9/12/13 diag가 이미
    같은 이유로 제외돼 있다(2026-08-24 non-fast-forward 사고).
    """
    wf = _read('scraper.yml')
    # case문이 둘이다(.json 루프와 .csv 루프). 이미 제외돼 있는 sim6 diag를
    # 표지 삼아 CSV 쪽 블록을 고른다.
    blocks = [b for b in re.findall(r'case "\$\(basename "\$f"\)" in(.+?)esac', wf, re.S)
              if 'sim6_diag_*.csv' in b]
    assert len(blocks) == 1, (
        f'scraper.yml의 CSV 제외 case문을 하나로 특정하지 못했다({len(blocks)}개) — '
        '배포 구조가 바뀌었다')
    assert 'sim11_watchlist_diag_*.csv' in blocks[0], (
        'scraper.yml 제외 목록에 심11 감시목록 깔때기가 없다 — '
        'eod_data.yml이 쓴 파일을 옛 사본으로 덮을 수 있다')


def test_the_funnel_output_is_watched_for_freshness():
    """계측은 조용히 멈출 수 있다 — 멈춘 걸 알려주는 경로가 있어야 한다.

    이 파일은 db-data까지 배포되게 배선했지만(위 두 테스트), 배포가 되는 것과
    '안 나오면 누가 알려주나'는 다른 축이다. 신선도 매니페스트는 글롭을
    지원한다(`data/regime_observations_*.csv` 선례) — 날짜별 파일이어도 들어간다.
    """
    import yaml
    cfg = os.path.join(os.path.dirname(__file__), '..', 'config', 'data_freshness.yaml')
    with open(cfg, encoding='utf-8') as f:
        outputs = yaml.safe_load(f)['outputs']

    paths = [e['path'] for e in outputs]
    assert 'data/sim11_watchlist_diag_*.csv' in paths, (
        '심11 감시목록 깔때기가 신선도 감시 대상이 아니다 — '
        '조용히 안 나와도 아무도 안 알려준다')
