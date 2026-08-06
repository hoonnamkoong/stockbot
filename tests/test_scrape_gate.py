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
