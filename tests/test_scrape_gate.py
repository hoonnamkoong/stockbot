"""scraper.yml 자체 게이팅 — 태스커가 tasker_trigger 하나만 2분마다 보낸다는 게
2026-08-07에 드러나서(trading_lite.yml의 tasker_trigger_trade는 실전에서 안 쓰임),
scraper.yml도 같은 이벤트로 매 2분 불린다. 스크래핑(Stage 1~4)까지 매번 돌면
신선도 10분 유지·네이버 부하 억제라는 애초 목표가 깨진다. 여기서 "지금이
스크래핑할 차례인가"만 판정한다 — 판정 자체는 순수 함수로 분리해 GH Actions
없이 테스트한다.
"""
import os
import sys
import json
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline import scrape_gate

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 8, 7, 10, 30, 0, tzinfo=KST)


def test_due_when_never_scraped_before(tmp_path):
    """상태 파일이 없으면(최초 실행) 스크래핑 쪽으로 fail — 침묵보다 낫다."""
    assert scrape_gate.is_scrape_due(NOW, data_dir=str(tmp_path)) is True


def test_due_when_corrupt_state_file(tmp_path):
    """파싱 불가한 상태 파일도 '모른다'로 취급해 스크래핑 쪽으로 fail."""
    (tmp_path / 'scrape_gate_state.json').write_text('{{{ not json', encoding='utf-8')
    assert scrape_gate.is_scrape_due(NOW, data_dir=str(tmp_path)) is True


def test_not_due_right_after_scraping(tmp_path):
    scrape_gate.mark_scraped(NOW, data_dir=str(tmp_path))
    just_after = NOW + timedelta(minutes=2)
    assert scrape_gate.is_scrape_due(just_after, data_dir=str(tmp_path)) is False


def test_not_due_at_eight_minutes(tmp_path):
    scrape_gate.mark_scraped(NOW, data_dir=str(tmp_path))
    later = NOW + timedelta(minutes=8)
    assert scrape_gate.is_scrape_due(later, data_dir=str(tmp_path)) is False


def test_due_at_exactly_ten_minutes(tmp_path):
    scrape_gate.mark_scraped(NOW, data_dir=str(tmp_path))
    later = NOW + timedelta(minutes=10)
    assert scrape_gate.is_scrape_due(later, data_dir=str(tmp_path)) is True


def test_due_when_next_tick_starts_a_few_seconds_early(tmp_path):
    """2026-08-07 실측 회귀.

    게이트가 "직전 스크래핑으로부터 10분 경과"를 봤을 때, 런 시작 시각이
    디스패치 + 워크플로 셋업(체크아웃·pip·토큰, 실측 약 52초)이라는 게 문제였다.
    이 셋업 시간이 런마다 몇 초씩 흔들리므로, 10분 뒤 트리거의 파이썬 시작이
    직전보다 조금이라도 빠르면 경과가 9분 5x초로 계산돼 스크래핑이 12분 뒤로
    밀렸다. 한 번 밀리면 정각 격자로 영영 못 돌아온다.

    실제로 08-07 db-data 배포 커밋이 :04 :15 :27 :40 :50 :01 … 로 흘렀고
    (08-04·08-05는 :04 :13 :23 :33 :43 :53 정확히 10분), 그 여파로 런 시작이
    minute 0~2에 드는 사이클이 하루 7회에서 3회로 줄어 정각 텔레그램 리포트가
    대부분 누락됐다.
    """
    scraped_at = NOW.replace(minute=0, second=58)
    scrape_gate.mark_scraped(scraped_at, data_dir=str(tmp_path))
    next_tick = NOW.replace(minute=10, second=4)   # 직전보다 54초 빠른 셋업
    assert scrape_gate.is_scrape_due(next_tick, data_dir=str(tmp_path)) is True


def test_schedule_stays_on_the_ten_minute_grid_despite_jitter(tmp_path):
    """셋업 시간이 매 런 요동쳐도 스크래핑은 :00 :10 :20 … 에 고정돼야 한다.

    정각(minute 0~2) 유지가 목적이다 — PipelineContext.should_notify()가
    그 창에서만 텔레그램을 보내므로, 격자가 밀리면 리포트가 조용히 사라진다.
    """
    jitter = [58, 4, 41, 12, 55, 7]   # 런마다 다른 셋업 소요(초)
    scraped_minutes = []
    for i, sec in enumerate(jitter):
        for minute in range(0, 60, 2):          # 태스커 2분 트리거
            tick = NOW.replace(hour=10 + i, minute=minute, second=sec)
            if scrape_gate.is_scrape_due(tick, data_dir=str(tmp_path)):
                scrape_gate.mark_scraped(tick, data_dir=str(tmp_path))
                scraped_minutes.append(minute)
    assert scraped_minutes == [0, 10, 20, 30, 40, 50] * len(jitter)


def test_run_starting_just_before_a_slot_boundary_does_not_scrape_twice(tmp_path):
    """격자만으로 판정하면 경계 직전에 시작한 런이 연속 스크래핑을 만든다.

    셋업이 평소(약 52초)보다 오래 걸려 :08 트리거의 파이썬이 09:09:58에
    시작하면, 6초 뒤 :10 트리거는 다음 격자라 곧바로 또 스크래핑 대상이 된다.
    네이버를 연달아 두드리는 건 이 게이트가 애초에 막으려던 바로 그 동작이다.
    """
    scrape_gate.mark_scraped(NOW.replace(hour=9, minute=9, second=58), data_dir=str(tmp_path))
    next_tick = NOW.replace(hour=9, minute=10, second=4)
    assert scrape_gate.is_scrape_due(next_tick, data_dir=str(tmp_path)) is False
    # 다음 격자에서는 정상적으로 재개한다(한 사이클만 건너뛴다).
    assert scrape_gate.is_scrape_due(NOW.replace(hour=9, minute=20, second=6),
                                     data_dir=str(tmp_path)) is True


def test_reads_legacy_state_without_slot(tmp_path):
    """이미 db-data에 올라가 있는 상태 파일에는 slot이 없다(last_scrape_at만).

    배포 직후 첫 런이 그걸 '모른다'로 읽고 매 틱 스크래핑하면 네이버 부하가
    5배가 된다 — 시각에서 격자를 되계산해 이어간다.
    """
    (tmp_path / 'scrape_gate_state.json').write_text(
        json.dumps({'last_scrape_at': NOW.isoformat()}), encoding='utf-8')
    assert scrape_gate.is_scrape_due(NOW + timedelta(minutes=2), data_dir=str(tmp_path)) is False
    assert scrape_gate.is_scrape_due(NOW + timedelta(minutes=10), data_dir=str(tmp_path)) is True


def test_due_when_well_past_interval(tmp_path):
    """스크래핑이 몇 사이클 실패해도(휴장·장애) 다음 성공 시 바로 잡는다."""
    scrape_gate.mark_scraped(NOW, data_dir=str(tmp_path))
    later = NOW + timedelta(minutes=37)
    assert scrape_gate.is_scrape_due(later, data_dir=str(tmp_path)) is True


def test_future_timestamp_in_state_does_not_force_a_scrape(tmp_path):
    """시계 오류 등으로 last_scrape_at이 미래면 elapsed가 음수 — 무리하게
    스크래핑을 강제하지 않는다(다음 정상 틱에서 자연히 바로잡힌다)."""
    future = NOW + timedelta(minutes=5)
    scrape_gate.mark_scraped(future, data_dir=str(tmp_path))
    assert scrape_gate.is_scrape_due(NOW, data_dir=str(tmp_path)) is False


def test_mark_scraped_persists_across_reads(tmp_path):
    scrape_gate.mark_scraped(NOW, data_dir=str(tmp_path))
    raw = json.loads((tmp_path / 'scrape_gate_state.json').read_text(encoding='utf-8'))
    assert raw['last_scrape_at'] == NOW.isoformat()


def test_interval_constant_matches_agreed_freshness():
    """버즈 필요 심 신선도는 10분 유지로 합의됐다(2026-08-06) — 상수가 그와
    어긋나면 조용히 신선도가 나빠진다."""
    assert scrape_gate.SCRAPE_INTERVAL_MIN == 10
