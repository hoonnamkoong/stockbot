"""스크래핑·국면 갱신 주기 게이트 — 태스커가 2분마다 trading.yml을 부르는데
스크래핑(Stage 1~4)까지 매 2분 돌면 신선도 10분 유지·네이버 부하 억제라는
애초 목표가 깨진다. 여기서 "지금이 스크래핑할 차례인가"만 판정하고,
trade_loop이 그 답을 보고 scraper.yml을 dispatch한다.

writer는 scraper.yml(완료 시점), reader는 trade_loop 하나다. 국면 게이트는
격자만 같을 뿐 writer가 trading.yml이라 파일이 따로다.

판정 자체는 순수 함수로 분리해 GH Actions 없이 시간만 바꿔가며 테스트한다.
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


def test_a_scrape_that_finished_recently_still_lets_the_next_grid_through(tmp_path):
    """2026-08-09. 예전에는 '직전 스크래핑으로부터 5분'이라는 바닥값이 있었다.

    **mark_scraped는 완료 시점에 불린다.** 스크래핑은 4~5분 걸리므로 :00 격자에
    시작한 런은 :04~:06에 끝나고, 그러면 :10 격자와의 간격이 4~6분이다 — 바닥값
    5분이 매 사이클 동전 던지기가 되어 절반쯤 :12로 밀린다. 한 번 밀리면 격자로
    영영 못 돌아온다(08-07 회귀와 같은 형태).

    연속 스크래핑을 막는 건 이 바닥값이 아니라 dispatch 쪽의 scraper_is_running()
    이다(scripts/trade_loop.py). 실행 중이면 애초에 dispatch하지 않는다.
    """
    scrape_gate.mark_scraped(NOW.replace(hour=9, minute=5, second=30), data_dir=str(tmp_path))

    assert scrape_gate.is_scrape_due(NOW.replace(hour=9, minute=10, second=4),
                                     data_dir=str(tmp_path)) is True


def test_the_grid_is_the_only_thing_that_decides(tmp_path):
    """같은 격자 안에서는 완료 직후든 8분 뒤든 닫혀 있다."""
    scrape_gate.mark_scraped(NOW.replace(hour=9, minute=0, second=30), data_dir=str(tmp_path))

    for minute, second in ((0, 40), (2, 10), (8, 59)):
        assert scrape_gate.is_scrape_due(
            NOW.replace(hour=9, minute=minute, second=second),
            data_dir=str(tmp_path)) is False


def test_a_state_file_with_a_slot_but_no_timestamp_still_gates(tmp_path):
    """`last_scrape_at`은 이제 폴백 전용이다 — 없다고 게이트가 열리면 안 된다.

    파싱을 무조건 먼저 하면 KeyError가 나고, 그 except가 '모른다 → 스크래핑'으로
    떨어져 매 2분 네이버를 두드린다. 판정에 안 쓰는 값 때문에 판정이 뒤집히는 꼴이다.
    """
    (tmp_path / 'scrape_gate_state.json').write_text(
        json.dumps({'last_scrape_slot': scrape_gate._slot(NOW)}), encoding='utf-8')

    assert scrape_gate.is_scrape_due(NOW + timedelta(minutes=2), data_dir=str(tmp_path)) is False
    assert scrape_gate.is_scrape_due(NOW + timedelta(minutes=10), data_dir=str(tmp_path)) is True


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


# ── 국면 게이트 (2026-08-08 회귀) ─────────────────────────────────────
# 국면 갱신은 스크래핑과 같은 10분 격자를 쓰지만 **주기가 같을 뿐 다른 일**이다.
# 스크래핑 게이트를 같이 쓰면, writer(scraper.yml 완료 시점)와 reader(trading.yml)
# 사이에 db-data 왕복 4~5분이 끼어 그동안 게이트가 계속 열려 있고, 국면이 격자당
# 3번 갱신된다 — 평활 시간상수 50분이 14분이 되는 알고리즘 변경이다.

def test_regime_gate_closes_even_while_the_scraper_is_still_running(tmp_path):
    """스크래퍼가 아직 안 끝나 스크래핑 게이트는 열려 있어도, 국면은 이번
    격자에 이미 갱신했으므로 닫혀 있어야 한다."""
    d = str(tmp_path)
    scrape_gate.mark_scraped(datetime(2026, 8, 10, 8, 55), d)   # 직전 격자 스크래핑

    assert scrape_gate.is_regime_due(datetime(2026, 8, 10, 9, 0, 40), d) is True
    scrape_gate.mark_regime(datetime(2026, 8, 10, 9, 0, 40), d)

    # 스크래퍼는 09:05에야 끝난다 → 그때까지 스크래핑 게이트는 열려 있다.
    assert scrape_gate.is_scrape_due(datetime(2026, 8, 10, 9, 2, 40), d) is True
    assert scrape_gate.is_regime_due(datetime(2026, 8, 10, 9, 2, 40), d) is False
    assert scrape_gate.is_regime_due(datetime(2026, 8, 10, 9, 4, 40), d) is False


def test_regime_gate_opens_on_the_next_grid(tmp_path):
    d = str(tmp_path)
    scrape_gate.mark_regime(datetime(2026, 8, 10, 9, 0, 40), d)
    assert scrape_gate.is_regime_due(datetime(2026, 8, 10, 9, 10, 40), d) is True


def test_regime_gate_is_open_when_never_refreshed(tmp_path):
    """모르면 갱신 쪽으로 fail — 국면 없이 도는 것보다 한 번 더 도는 게 낫다."""
    assert scrape_gate.is_regime_due(NOW, data_dir=str(tmp_path)) is True
