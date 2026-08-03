"""파이프라인 로그는 '언제 찍혔는지'를 보여줘야 한다.

ctx.log()가 now_kst(런 시작 시각으로 고정된 값)를 찍는 바람에 한 런의 모든 줄이
같은 시각이었다. 2026-08-03 스크래퍼 로그가 통째로 [15:31:00]이라, 6~11분 걸리는
런에서 어느 단계가 시간을 먹는지 볼 수 없었다. 매매 판단이 쓰는 가격의 신선도가
여기에 걸려 있어 계측이 먼저다.

now_kst 자체는 그대로 둔다 — 날짜·거래일 판정이 한 런 안에서 흔들리면 안 된다.
"""
import os, sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.context import PipelineContext


def test_log_uses_wall_clock_not_frozen_start_time(capsys):
    ctx = PipelineContext()
    ctx.now_kst = datetime(2020, 1, 1, 3, 4, 5)   # 런 시작 시각을 과거로 고정
    ctx.log('hello')
    out = capsys.readouterr().out
    assert 'hello' in out
    assert '03:04:05' not in out, 'now_kst를 찍으면 모든 줄이 같은 시각이 된다'


def test_now_kst_stays_frozen_for_date_decisions():
    """로그 시각을 실시간으로 바꿔도 날짜 판정 기준은 고정이어야 한다."""
    ctx = PipelineContext()
    first = ctx.now_kst
    ctx.log('tick')
    assert ctx.now_kst == first
    assert ctx.today_str == first.strftime('%Y%m%d')


def test_stage_logs_elapsed_seconds(capsys):
    """단계 소요가 로그에 남아야 어디를 줄일지 정할 수 있다."""
    ctx = PipelineContext()
    with ctx.stage('Stage 1: 데이터 수집'):
        pass
    out = capsys.readouterr().out
    assert 'Stage 1: 데이터 수집' in out
    assert '초' in out or 's)' in out


def test_stage_logs_elapsed_even_on_failure(capsys):
    """단계가 예외로 죽어도 소요는 남긴다 — 느려서 죽은 건지 알아야 한다."""
    ctx = PipelineContext()
    try:
        with ctx.stage('Stage 2: AI 분석'):
            raise RuntimeError('boom')
    except RuntimeError:
        pass
    out = capsys.readouterr().out
    assert 'Stage 2: AI 분석' in out
    assert out.count('Stage 2: AI 분석') >= 2, '시작과 종료가 모두 찍혀야 한다'
