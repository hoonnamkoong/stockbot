"""결과 감시 — "오늘 아무도 안 샀다"를 장중에 알린다.

2026-09-01, 장이 열리고 5시간이 지나도록 실전 매매가 0건이었는데 시스템은
아무 말도 하지 않았다. 워크플로는 전부 초록이었고, 신선도 감사가 보는 10개
산출물도 전부 최신이었다 — 그 10개가 **입력·중간물뿐**이고 결과는 하나도
없었기 때문이다.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.trade_outcome import (  # noqa: E402
    CHECKPOINT_HHMM, count_trades_by_sim, outcome_verdict)


def test_silent_before_the_checkpoint():
    """개장 직후의 0건은 정상이다 — 아직 아무 일도 안 일어났을 뿐이다."""
    assert outcome_verdict({'A': 0, 'B': 0}, '09:30') is None
    assert outcome_verdict({'A': 0, 'B': 0}, '13:59') is None


def test_alerts_when_every_sim_is_zero():
    msg = outcome_verdict({'A': 0, 'B': 0, 'C': 0}, CHECKPOINT_HHMM)
    assert msg is not None
    assert '매매 0건' in msg
    assert '3개' in msg


def test_one_trade_anywhere_is_enough():
    """개별 심의 0건은 정상이다. 하나라도 샀으면 배선은 살아 있다."""
    assert outcome_verdict({'A': 0, 'B': 0, 'C': 1}, '14:30') is None


def test_all_unreadable_is_not_reported_as_zero():
    """전부 못 읽으면 그건 매매 문제가 아니라 데이터 문제다.

    여기서 '0건'이라고 말하면 거짓말이 된다 — 이 레포가 금지하는 조작이다.
    """
    assert outcome_verdict({'A': None, 'B': None}, '14:30') is None


def test_partial_unreadable_is_disclosed():
    """일부만 못 읽었으면 판정은 하되 몇 개를 못 봤는지 함께 적는다."""
    msg = outcome_verdict({'A': 0, 'B': None}, '14:30')
    assert msg is not None and '측정 불가' in msg and 'B' in msg


def test_zero_and_unknown_are_not_the_same(tmp_path):
    """파일이 없어서 0인 것과, 못 읽어서 모르는 것은 다르다."""
    from src.pipeline.trade_outcome import _count_rows
    missing = tmp_path / 'nope.csv'
    assert _count_rows(str(missing), '2026-09-01') == 0

    broken = tmp_path / 'broken.csv'
    broken.write_bytes(b'\xff\xfe\x00bad')
    assert _count_rows(str(broken), '2026-09-01') is None


def test_counts_come_from_the_manifest(tmp_path):
    """심 목록을 자체로 들지 않는다 — 새 심이 조용히 빠지는 사고가 반복됐다."""
    from src.strategy.registry import get_sim_registry
    counts = count_trades_by_sim(str(tmp_path), '2026-09-01')
    assert set(counts) == {s['label'] for s in get_sim_registry()}
    # 디렉터리가 비었으므로 전부 0(측정 불가가 아니다)
    assert set(counts.values()) == {0}


def test_counts_only_todays_rows(tmp_path):
    from src.strategy.registry import get_sim_registry
    sim = get_sim_registry()[0]
    (tmp_path / sim['csv_file']).write_text(
        'timestamp,symbol\n'
        '2026-09-01 09:30:00,AAA\n'
        '2026-08-31 09:30:00,BBB\n', encoding='utf-8')
    counts = count_trades_by_sim(str(tmp_path), '2026-09-01')
    assert counts[sim['label']] == 1
