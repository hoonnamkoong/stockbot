"""진단 로거가 조용히 실패하지 않는다.

2026-08-09에 드러난 것: sim_psych는 12개 매매 심에 포함돼 실제로 돌고
`sim_diag.append()`의 쓰기 경로도 정적으로는 정상인데, **db-data에 diag 파일이
하나도 없다.**

원인을 특정할 수 없었던 이유가 곧 원인이다 — `append`는 0을 돌려주는 길이 셋인데
(records 비었음 / 옛 헤더 파일을 못 비켜놓음 / 예외) 전부 같은 `return 0`이고,
호출부는 그 값을 보지도 않는다. 세 경우가 모두 로그에서 똑같이 침묵한다.

"진단을 남기는 장치"가 자기 실패를 진단할 수 없으면 그 장치는 없는 것과 같다.
Sim1이 6개월간 실패 원인을 몰랐던 문제를 고치려고 만든 게 이것이다.

예외는 계속 삼킨다 — 로깅 실패로 심이 죽으면 원래 문제보다 나쁘다. 다만 **시끄럽게**
삼킨다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data import sim_diag  # noqa: E402


def _rec(code='005930'):
    return {'code': code, 'name': '삼성전자', 'decision': 'skip', 'reason': 'buzz'}


def _logs():
    out = []
    return out, out.append


# ── 0을 돌려주는 세 갈래가 로그에서 구분된다 ────────────────────────

def test_empty_records_says_so(tmp_path):
    """'기록할 게 없었다'와 '기록에 실패했다'는 완전히 다른 사건이다."""
    logs, log = _logs()
    n = sim_diag.append('sim1', [], path=str(tmp_path / 'd.csv'), log=log)

    assert n == 0
    assert logs, '빈 records가 아무 흔적도 안 남겼다'
    assert any('sim1' in m for m in logs)


def test_a_write_failure_names_the_exception(tmp_path):
    """디렉터리를 파일 자리에 두면 open이 죽는다. 예외 타입이 로그에 남아야
    '왜 파일이 없나'를 다음 날 되짚을 수 있다."""
    blocked = tmp_path / 'd.csv'
    blocked.mkdir()                      # 파일이 아니라 디렉터리 → open 실패
    logs, log = _logs()
    n = sim_diag.append('sim1', [_rec()], path=str(blocked), log=log)

    assert n == 0
    assert logs, '쓰기 실패가 조용히 삼켜졌다'
    assert any('sim1' in m for m in logs)


def test_a_stale_header_that_cannot_be_moved_says_so(tmp_path, monkeypatch):
    """옛 헤더 파일을 비켜놓지 못하면 기록을 생략한다 — 그 판단 자체는 옳지만
    (열이 어긋나느니 안 쓰는 게 낫다) 침묵하면 안 된다."""
    monkeypatch.setattr(sim_diag, '_move_stale_if_needed', lambda p: False)
    logs, log = _logs()
    n = sim_diag.append('sim1', [_rec()], path=str(tmp_path / 'd.csv'), log=log)

    assert n == 0
    assert logs, '헤더 이동 실패가 조용히 삼켜졌다'


# ── 실패해도 심은 죽지 않는다 ───────────────────────────────────────

def test_a_write_failure_never_raises(tmp_path):
    """로깅 실패로 심이 죽으면 원래 알리려던 문제보다 나쁘다."""
    blocked = tmp_path / 'd.csv'
    blocked.mkdir()
    sim_diag.append('sim1', [_rec()], path=str(blocked))   # log 인자 없이도 안전


def test_a_broken_logger_does_not_kill_the_sim(tmp_path):
    """로거 자체가 터져도 마찬가지다."""
    def boom(_):
        raise RuntimeError('로거 고장')

    blocked = tmp_path / 'd.csv'
    blocked.mkdir()
    sim_diag.append('sim1', [_rec()], path=str(blocked), log=boom)


# ── 정상 경로는 조용하다 ────────────────────────────────────────────

def test_a_successful_write_returns_the_row_count(tmp_path):
    logs, log = _logs()
    n = sim_diag.append('sim1', [_rec('005930'), _rec('000660')],
                        path=str(tmp_path / 'd.csv'), log=log)

    assert n == 2
    assert not logs, f'정상 기록이 로그를 더럽힌다: {logs}'
    assert (tmp_path / 'd.csv').exists()


# ── 호출부가 결과를 본다 ────────────────────────────────────────────

def test_the_caller_logs_how_many_rows_it_wrote():
    """append가 0을 돌려줘도 호출부가 안 보면 아무 일도 안 일어난다.
    db-data에 파일이 없다는 걸 몇 주째 아무도 모른 이유가 정확히 이것이다."""
    import inspect
    from src.strategy.simulators import sim1_psych

    src = inspect.getsource(sim1_psych.PsychDivergenceSimulator.run)
    assert 'sim_diag.append' in src
    call_line = [l for l in src.splitlines() if 'sim_diag.append' in l][0]
    assert '=' in call_line, (
        'sim_diag.append의 반환값을 버리고 있다 — 0행이어도 흔적이 없다')
