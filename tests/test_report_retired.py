"""11:00·14:00 리포트 슬롯 폐기를 지킨다.

되살아나면 Gemini 비용이 조용히 다시 붙고, 심7이 없는데 강력매수 판정만
도는 반쪽 상태가 된다.
"""
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _grep(pattern: str) -> str:
    # encoding을 명시한다. 윈도우 기본(cp949)으로 디코드하면 한글이 섞인
    # grep 출력에서 UnicodeDecodeError가 나고 stdout이 None이 된다.
    r = subprocess.run(['git', 'grep', '-n', pattern, '--', 'src', 'scripts'],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return r.stdout or ''


def test_report_slots_are_gone():
    assert _grep('REPORT_SLOTS') == '', 'REPORT_SLOTS 참조가 남아 있다'


def test_deep_dive_is_gone():
    for name in ('generate_deep_dive', 'due_slot'):
        hits = [ln for ln in _grep(name).splitlines()
                if 'scraper_legacy_v49.py' not in ln]
        assert hits == [], f'{name} 참조가 남아 있다: {hits}'


def test_should_notify_method_is_gone():
    """PipelineContext.should_notify()만 본다.

    이름만으로 grep하면 세 곳에 걸린다 — scripts/notify_workflow_failure.py의
    동명 함수(워크플로 실패 알림용, 무관), src/alerts.py와
    src/pipeline/daily_brief.py의 **설명 주석**. 뒤 둘은 왜 지금 구조가
    이런지를 남긴 기록이라 지우면 안 된다. 정의만 확인한다.
    """
    ctx = os.path.join(ROOT, 'src', 'pipeline', 'context.py')
    with open(ctx, encoding='utf-8') as f:
        src = f.read()
    assert 'def should_notify' not in src
    assert 'def report_slot' not in src


def test_monthly_research_excel_survives_and_keeps_its_cadence():
    """월간 리서치 엑셀은 2026-08-31에 '살아있는 산출물'로 명시 유지 결정한 것이다.

    Stage 3.5 안에 중첩돼 있어서 리포트를 지우면 같이 죽는다 — 그러면 그
    결정이 조용히 뒤집힌다. 살리되 **주기도 지킨다**: 매 사이클로 옮기면
    행 수가 수십 배가 되어 성격이 달라진다. 브리핑 슬롯(하루 2회)에 묶는다.
    """
    orch = os.path.join(ROOT, 'src', 'pipeline', 'orchestrator.py')
    with open(orch, encoding='utf-8') as f:
        src = f.read()

    assert 'update_monthly_excel' in src, '월간 리서치 엑셀 기록이 사라졌다'

    # 호출이 브리핑 슬롯 판정 안에 있어야 한다. 같은 구문 안인지를 본다.
    call_at = src.index('update_monthly_excel')
    guard_at = src.rindex('should_send_brief', 0, call_at)
    between = src[guard_at:call_at]
    assert between.count('\n') <= 3, (
        'update_monthly_excel이 브리핑 슬롯 판정에 묶여 있지 않다 — '
        '매 사이클 실행되면 하루 2회 주기가 깨진다')
