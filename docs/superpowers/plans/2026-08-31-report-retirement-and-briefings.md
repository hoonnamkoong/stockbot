# 리포트 폐기 + 심7 제거 + 브리핑 재편 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 11:00·14:00 Gemini 딥다이브 리포트 슬롯을 통째로 폐기하고, 그 입력에만 의존하던 심7을 제거하며, 브리핑을 국내 2회(12:00 구간·15:00 마감)·미국 1회(09:00 KST 마감)로 재편한다. 덤으로 premarket intraday 커밋의 100MB 초과 실패를 gzip으로 고친다.

**Architecture:** 발송 슬롯 판정은 `src/report/gate.py`의 순수 함수에 모여 있다. 이 모듈을 상태 파일명 인자를 받도록 일반화해서, 국내 브리핑(writer=scraper.yml, `report_gate_state.json`)과 미국 브리핑(writer=trading.yml, `us_brief_gate_state.json`)이 **서로 다른 파일**을 쓰게 한다. 브리핑 본문 조립은 I/O 없는 순수 함수로 분리해 시각·상태만 바꿔가며 테스트한다.

**Tech Stack:** Python 3.10(trading.yml) / 3.11(premarket), pytest, GitHub Actions, PyYAML

**Spec:** `docs/superpowers/specs/2026-08-31-report-retirement-and-briefings-design.md`

## Global Constraints

- **모든 사용자 대면 문자열은 한국어다.** 기존 브리핑 문구 톤을 따른다.
- **조회 실패를 0으로 폴백하지 않는다.** 금액·수익률은 실패 시 `측정 불가`로 적는다. `0`은 "정상적으로 0"일 때만 쓴다.
- **슬롯은 발송에 성공한 직후에만 닫는다.** 실패를 '보냈다'로 기록하면 그 회차가 그날 통째로 사라진다.
- **상태 파일의 writer는 하나다.** `report_gate_state.json`은 scraper.yml만, `us_brief_gate_state.json`은 trading.yml만 배포한다.
- **커밋 메시지는 여러 줄이면 `git commit -F <파일>`로 쓴다.** 인라인 heredoc은 이 환경에서 `@` 문자가 박힌다.
- 각 Task 끝에서 `python -m pytest tests/ -q`가 통과해야 한다(기준선: 1564 passed / 4 skipped).

---

### Task 1: gate.py를 상태 파일명 인자로 일반화 (동작 불변)

미국 브리핑이 별도 상태 파일을 쓰려면 게이트가 파일명을 받아야 한다. 이 Task는 **기존 동작을 1비트도 바꾸지 않는다** — 순수 리팩터링이라 회귀 테스트만으로 검증된다.

**Files:**
- Modify: `src/report/gate.py`
- Test: `tests/test_report_gate.py`

**Interfaces:**
- Consumes: 없음(첫 Task)
- Produces: `_state_path(data_dir, filename=STATE_FILENAME)`, `_sent_today(now, data_dir, filename=STATE_FILENAME)`, `_due(now_kst, slots, data_dir, filename=STATE_FILENAME) -> str|None`, `mark_sent(slot, now_kst, data_dir=None, filename=STATE_FILENAME)`

- [ ] **Step 1: 파일명을 달리하면 기록이 섞이지 않는다는 실패 테스트를 쓴다**

`tests/test_report_gate.py` 끝에 추가:

```python
def test_mark_sent_writes_to_the_named_file(tmp_path):
    """다른 파일명을 주면 기본 상태 파일을 건드리지 않는다."""
    from src.report import gate
    now = datetime(2026, 9, 1, 9, 5)

    gate.mark_sent('09:00', now, str(tmp_path), filename='us_brief_gate_state.json')

    assert (tmp_path / 'us_brief_gate_state.json').exists()
    assert not (tmp_path / gate.STATE_FILENAME).exists()


def test_due_reads_only_the_named_file(tmp_path):
    """기본 파일에 09:00을 보냈다고 적어도, 다른 파일을 보는 판정은 열려 있다."""
    from src.report import gate
    now = datetime(2026, 9, 1, 9, 5)

    gate.mark_sent('09:00', now, str(tmp_path))   # 기본 파일에 기록

    assert gate._due(now, ('09:00',), str(tmp_path)) is None
    assert gate._due(now, ('09:00',), str(tmp_path),
                     filename='us_brief_gate_state.json') == '09:00'
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `python -m pytest tests/test_report_gate.py -q`
Expected: FAIL — `TypeError: mark_sent() got an unexpected keyword argument 'filename'`

- [ ] **Step 3: gate.py의 네 함수에 filename 인자를 단다**

`src/report/gate.py`에서 아래 네 함수의 시그니처와 본문을 바꾼다. **기본값이 있으므로 기존 호출부는 손대지 않는다.**

```python
def _state_path(data_dir: str | None, filename: str = STATE_FILENAME) -> str:
    return os.path.join(data_dir or DEFAULT_DATA_DIR, filename)


def _sent_today(now, data_dir: str | None, filename: str = STATE_FILENAME) -> list[str]:
    try:
        with open(_state_path(data_dir, filename), 'r', encoding='utf-8') as f:
            raw = json.load(f)
        if raw.get('date') != now.strftime('%Y-%m-%d'):
            return []
        sent = raw.get('sent')
        return [str(s) for s in sent] if isinstance(sent, list) else []
    except Exception:
        return []


def _due(now_kst: datetime, slots, data_dir: str | None,
         filename: str = STATE_FILENAME) -> str | None:
    now_min = now_kst.hour * 60 + now_kst.minute
    sent = _sent_today(now_kst, data_dir, filename)
    for slot in sorted(slots, key=_slot_minutes, reverse=True):
        if slot in sent:
            continue
        start = _slot_minutes(slot)
        if start <= now_min < start + SLOT_WINDOW_MIN:
            return slot
    return None


def mark_sent(slot: str, now_kst: datetime, data_dir: str | None = None,
              filename: str = STATE_FILENAME) -> None:
    path = _state_path(data_dir, filename)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    sent = _sent_today(now_kst, data_dir, filename)
    if slot not in sent:
        sent.append(slot)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'date': now_kst.strftime('%Y-%m-%d'),
                   'sent': sorted(sent, key=_slot_minutes),
                   'last_sent_at': now_kst.isoformat()}, f, ensure_ascii=False)
```

`mark_sent`의 기존 docstring("그 슬롯을 보냈다고 기록한다. **발송에 성공한 직후에만 부른다.**" 이하 전문)은 그대로 유지한다.

- [ ] **Step 4: 새 테스트와 기존 게이트 테스트가 모두 통과하는지 확인한다**

Run: `python -m pytest tests/test_report_gate.py tests/test_report_gate_wiring.py tests/test_daily_brief.py -q`
Expected: PASS (기존 테스트 전부 + 신규 2개)

- [ ] **Step 5: 커밋**

```bash
git add src/report/gate.py tests/test_report_gate.py
cat > /tmp/msg.txt <<'MSG'
refactor(gate): 슬롯 상태 파일명을 인자로 받는다

미국 브리핑이 국내 리포트와 같은 상태 파일을 쓰면 writer가 둘이 되어
lost update로 닫은 슬롯이 다시 열린다. 파일을 나눌 수 있게 일반화만 한다
— 기본값이 있어 기존 호출부의 동작은 바뀌지 않는다.
MSG
git commit -F /tmp/msg.txt
```

---

### Task 2: 국내 브리핑을 12:00 + 15:00 두 슬롯으로

**Files:**
- Modify: `src/report/gate.py` (`BRIEF_SLOT` → `BRIEF_SLOTS`, `brief_due` 반환형)
- Modify: `src/pipeline/daily_brief.py` (`should_send_brief`, `build_daily_brief`, `_count_today_tickers`, `collect_sim_brief`)
- Modify: `src/pipeline/workers/notifier.py:68-71`
- Test: `tests/test_daily_brief.py`, `tests/test_report_gate.py`

**Interfaces:**
- Consumes: Task 1의 `_due(now, slots, data_dir, filename)`
- Produces:
  - `gate.BRIEF_SLOTS = ('12:00', '15:00')`
  - `gate.brief_due(now_kst, data_dir=None) -> str | None`
  - `daily_brief.should_send_brief(now_kst, data_dir=None) -> str | None`
  - `daily_brief.build_daily_brief(balance, sims, now_kst, slot) -> str`
  - `daily_brief.collect_sim_brief(data_dir, today_str, since=None, until=None) -> list[dict]`

- [ ] **Step 1: 실패 테스트를 쓴다**

`tests/test_daily_brief.py` 끝에 추가:

```python
def test_two_brief_slots_are_independent(tmp_path):
    """12시를 보내도 15시 슬롯은 따로 열린다."""
    from src.report import gate
    noon = datetime(2026, 9, 1, 12, 5)
    close = datetime(2026, 9, 1, 15, 5)

    assert gate.brief_due(noon, str(tmp_path)) == '12:00'
    gate.mark_sent('12:00', noon, str(tmp_path))
    assert gate.brief_due(noon, str(tmp_path)) is None
    assert gate.brief_due(close, str(tmp_path)) == '15:00'


def test_noon_brief_title_names_the_window():
    msg = build_daily_brief(OK_BALANCE, OK_SIMS, datetime(2026, 9, 1, 12, 5), '12:00')
    assert '12:00' in msg and '09:00~12:00' in msg


def test_close_brief_title_is_unchanged():
    msg = build_daily_brief(OK_BALANCE, OK_SIMS, datetime(2026, 9, 1, 15, 5), '15:00')
    assert '15:00 마감 브리핑' in msg


def test_ticker_count_respects_the_window(tmp_path):
    """09:00~12:00 창이면 그 밖의 거래는 세지 않는다."""
    from src.pipeline.daily_brief import _count_today_tickers
    csv_path = tmp_path / 'hist.csv'
    csv_path.write_text(
        'timestamp,symbol\n'
        '2026-09-01 09:30:00,AAA\n'
        '2026-09-01 14:30:00,BBB\n',
        encoding='utf-8')

    assert _count_today_tickers(str(csv_path), '2026-09-01') == 2
    assert _count_today_tickers(str(csv_path), '2026-09-01',
                                since='09:00', until='12:00') == 1
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `python -m pytest tests/test_daily_brief.py -q`
Expected: FAIL — `AttributeError: module 'src.report.gate' has no attribute 'brief_due'` 반환형 불일치 및 `build_daily_brief() takes 3 positional arguments but 4 were given`

- [ ] **Step 3: gate.py의 브리핑 슬롯을 둘로 늘린다**

`src/report/gate.py`에서 `BRIEF_SLOT` 정의를 교체한다:

```python
# 2026-08-31: 11:00·14:00 리포트를 폐기하면서 브리핑을 둘로 늘렸다.
# 12:00은 09:00~12:00 구간, 15:00은 하루 전체 마감이다. 슬롯마다 제목과
# 집계 구간이 다르므로 brief_due는 bool이 아니라 **어느 슬롯인지**를 준다.
BRIEF_SLOTS = ('12:00', '15:00')
```

`brief_due`를 교체한다:

```python
def brief_due(now_kst: datetime, data_dir: str | None = None) -> str | None:
    """지금 열려 있는 브리핑 슬롯('12:00'/'15:00'), 없으면 None.

    리포트 슬롯과 **독립이다.** 두 브리핑끼리도 독립이다 — 12시를 보냈다는
    사실이 15시 마감 브리핑을 막지 않는다.
    """
    return _due(now_kst, BRIEF_SLOTS, data_dir)
```

- [ ] **Step 4: daily_brief.py에 슬롯·구간을 배선한다**

`_count_today_tickers`를 교체한다:

```python
def _count_today_tickers(path: str, today_str: str,
                         since: str | None = None, until: str | None = None) -> int:
    """오늘 매매한 종목 수(중복 제거). 파일이 없으면 거래가 없었다는 뜻이므로 0.

    since/until은 'HH:MM' 문자열이다. 둘 다 없으면 하루 전체를 센다.
    timestamp 형식은 'YYYY-MM-DD HH:MM:SS'로 고정이다.
    """
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            out = set()
            for row in csv.DictReader(f):
                ts = row.get('timestamp') or ''
                code = row.get('symbol')
                if not code or not ts.startswith(today_str):
                    continue
                hhmm = ts[11:16]
                if since and hhmm < since:
                    continue
                if until and hhmm >= until:
                    continue
                out.add(code)
            return len(out)
    except FileNotFoundError:
        return 0
    except Exception as e:
        print(f"[Brief] 거래이력 읽기 실패: {path} — {type(e).__name__}: {e}")
        return 0
```

`collect_sim_brief`를 교체한다:

```python
def collect_sim_brief(data_dir: str, today_str: str,
                      since: str | None = None, until: str | None = None) -> list[dict]:
    """심별 (표시명, 수익률, 거래 종목 수)를 모은다.

    수익률은 since/until과 무관하게 **현재 시점 누적**이다. 상태 파일에 구간
    시작 시점 스냅샷이 없어 구간 수익률은 만들 수 없다 — 지어내지 않는다.
    """
    return [
        {
            'label': label,
            'profit_rate': _profit_rate_from_state(os.path.join(data_dir, state_file)),
            'ticker_count': _count_today_tickers(
                os.path.join(data_dir, csv_file), today_str, since, until),
        }
        for label, state_file, csv_file in SIM_BRIEF_TARGETS
    ]
```

`build_daily_brief`를 교체한다:

```python
# 슬롯별 (제목, 집계 시작, 집계 끝). 끝이 None이면 하루 전체다.
BRIEF_SPECS = {
    '12:00': ('12:00 오전 브리핑 (09:00~12:00)', '09:00', '12:00'),
    '15:00': ('15:00 마감 브리핑', None, None),
}


def build_daily_brief(balance: dict, sims: list[dict], now_kst: datetime, slot: str) -> str:
    """브리핑 본문. 순수 함수 — I/O 없음."""
    title, _, _ = BRIEF_SPECS[slot]
    day = f"{now_kst.strftime('%m/%d')} ({_WEEKDAY_KR[now_kst.weekday()]})"
    parts = [f"📅 {title}  {day}", '']
    parts += _account_block(balance)
    parts += ['']
    parts += _sim_block(sims)
    return '\n'.join(parts)
```

`_sim_block`의 헤더를 구간에 맞게 바꾼다 — 현행 `'🤖 심별 현황 (수익률 / 금일 거래)'`를 그대로 두면 12시 브리핑에서 거짓말이 된다:

```python
def _sim_block(sims: list[dict], window_label: str = '금일') -> list[str]:
    lines = [f'🤖 심별 현황 (누적 수익률 / {window_label} 거래)']
    for s in sims:
        rate = s.get('profit_rate')
        rate_str = '측정 불가' if rate is None else _signed_pct(rate)
        lines.append(f"  {s['label']:<20} {rate_str:>9}   {s.get('ticker_count', 0)}종목")
    return lines
```

`build_daily_brief`의 `_sim_block` 호출을 `parts += _sim_block(sims, '오전' if slot == '12:00' else '금일')`로 바꾼다.

`should_send_brief`를 교체한다(docstring의 2026-08-09 배경 설명은 유지):

```python
def should_send_brief(now_kst, data_dir=None) -> str | None:
    """지금 열려 있는 브리핑 슬롯('12:00'/'15:00'), 없으면 None."""
    from src.report.gate import brief_due
    return brief_due(now_kst, data_dir)
```

- [ ] **Step 5: notifier의 호출부를 슬롯 인식으로 바꾼다**

`src/pipeline/workers/notifier.py:68-71`을 교체한다. **`BRIEF_SLOT` 상수를 넘기던 것을 반환된 슬롯으로 바꾸는 게 핵심이다** — 그대로 두면 12시 브리핑을 보내고 15시 슬롯을 닫아 마감 브리핑이 사라진다.

```python
        # 2-1. 브리핑 — 리포트와 **다른 슬롯이다.** 12:00(오전 구간)과 15:00(마감)
        # 둘이 서로 독립이므로, 보낸 슬롯을 그대로 닫아야 한다. 상수를 닫으면
        # 12시를 보내고 15시가 사라진다.
        brief_slot = should_send_brief(self.ctx.now_kst, data_dir)
        if brief_slot:
            if self.safe_run(self._send_daily_brief, self._brief_fallback,
                             brief_slot) is True:
                report_gate.mark_sent(brief_slot, self.ctx.now_kst, data_dir)
```

`_send_daily_brief`를 슬롯을 받도록 바꾼다:

```python
    def _send_daily_brief(self, slot: str) -> bool:
        """브리핑을 별도 메시지로 발송. 성공했으면 True."""
        from src.trade.balance import get_balance
        from src.pipeline.daily_brief import BRIEF_SPECS

        try:
            balance = get_balance()
        except Exception as e:
            balance = {'error': f'잔고 조회 예외: {e}', 'holdings': []}

        _, since, until = BRIEF_SPECS[slot]
        sims = collect_sim_brief('data', self.ctx.now_kst.strftime('%Y-%m-%d'),
                                 since, until)
        sent = self.tg.send_message(
            build_daily_brief(balance, sims, self.ctx.now_kst, slot))
        if not sent:
            raise RuntimeError(f"{slot} 브리핑 텔레그램 발송 실패")
        self.log(f"{slot} 브리핑 발송 완료")
        return True
```

`_brief_fallback`도 인자를 받도록 바꾼다(`safe_run`이 같은 인자를 fallback에 넘긴다):

```python
    def _brief_fallback(self, slot: str = '') -> None:
        """브리핑 조립·발송 실패. 숫자를 지어내지 않고 실패만 알린다."""
        try:
            self.tg.send_message(
                f"[{self.ctx.now_kst.strftime('%m/%d %H:%M')}] {slot} 브리핑 생성 실패")
        except Exception:
            pass
```

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_daily_brief.py tests/test_report_gate.py tests/test_report_gate_wiring.py -q`
Expected: PASS

기존 테스트 중 `build_daily_brief(...)`를 3인자로 부르는 것들(`tests/test_daily_brief.py:45,54,64,73,81`)은 네 번째 인자 `'15:00'`을 붙여 고친다 — 문구가 안 바뀌는 것을 확인하는 회귀 테스트이므로 `'15:00'`이 맞다.

- [ ] **Step 7: 전체 테스트**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 8: 커밋**

```bash
git add src/report/gate.py src/pipeline/daily_brief.py src/pipeline/workers/notifier.py tests/test_daily_brief.py
cat > /tmp/msg.txt <<'MSG'
feat(brief): 국내 브리핑을 12:00 구간 + 15:00 마감 두 슬롯으로

12:00은 09:00~12:00 거래만 센다. 수익률은 두 슬롯 모두 현재 시점 누적이다
— 상태 파일에 구간 시작 스냅샷이 없어 구간 수익률은 만들 수 없다.

보낸 슬롯을 그대로 닫는다. 상수(BRIEF_SLOT)를 닫으면 12시를 보내고
15시 마감이 통째로 사라진다.
MSG
git commit -F /tmp/msg.txt
```

---

### Task 3: 리포트 슬롯 폐기 (월별 엑셀은 살린다)

**Files:**
- Modify: `src/report/gate.py` (`REPORT_SLOTS`, `due_slot` 삭제)
- Modify: `src/pipeline/context.py:137-160` (`report_slot`, `should_notify` 삭제)
- Modify: `src/pipeline/orchestrator.py:227-251` (Stage 3.5 삭제, 엑셀 기록만 이관)
- Modify: `src/pipeline/workers/notifier.py` (`_send_report`, `_send_fallback_summary`, 슬롯 분기, `reported_codes` 갱신 삭제)
- Modify: `src/pipeline/workers/llm_analyzer.py:189+` (`generate_deep_dive` 삭제)
- Modify: `src/strategy/advisor.py` (`generate_deep_dive_report` 삭제)
- Test: `tests/test_report_gate.py`, 신규 `tests/test_report_retired.py`

**Interfaces:**
- Consumes: Task 2의 `should_send_brief() -> str|None`
- Produces: `NotifierWorker.run(all_stocks, simulation_results, sync_state)` — `final_picks`·`deep_dive_report` 인자가 사라진다

- [ ] **Step 1: 폐기를 강제하는 실패 테스트를 쓴다**

`tests/test_report_retired.py` 신규:

```python
"""11:00·14:00 리포트 슬롯 폐기를 지킨다.

되살아나면 Gemini 비용이 조용히 다시 붙고, 심7이 없는데 강력매수 판정만
도는 반쪽 상태가 된다.
"""
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _grep(pattern: str) -> str:
    r = subprocess.run(['git', 'grep', '-n', pattern, '--', 'src', 'scripts'],
                       cwd=ROOT, capture_output=True, text=True)
    return r.stdout


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
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `python -m pytest tests/test_report_retired.py -q`
Expected: FAIL — `REPORT_SLOTS 참조가 남아 있다`

- [ ] **Step 3: gate.py와 context.py에서 리포트 판정을 지운다**

`src/report/gate.py`에서 `REPORT_SLOTS` 상수 정의와 `due_slot()` 함수를 통째로 삭제한다. 모듈 docstring의 "왜 분 창이 아니라 슬롯 상태인가" 설명은 브리핑에도 그대로 적용되므로 유지하되, `하루 2회(11:00·14:00)`를 `브리핑 슬롯`으로 고친다.

`src/pipeline/context.py`에서 `report_slot()`과 `should_notify()` 두 메서드를 통째로 삭제한다. 소비자는 orchestrator·notifier뿐이고 둘 다 이 Task에서 사라진다.

- [ ] **Step 4: orchestrator에서 Stage 3.5를 지우고 엑셀 기록만 살린다**

`src/pipeline/orchestrator.py:227-251`(Stage 3.5 블록 전체)을 삭제하고 아래로 교체한다. `deep_dive_report` 지역변수도 사라진다.

```python
    # ── 월별 리서치 엑셀 ─────────────────────────────────────────
    # 예전에는 Stage 3.5(딥다이브) 안에 중첩돼 있었다. 리포트를 폐기하면서
    # 이것까지 같이 죽으면 2026-08-31에 "살아있는 산출물이라 유지"로 결정한
    # reports/monthly_research_*.xlsx가 조용히 멈춘다.
    # 발동 조건을 브리핑 슬롯으로 옮겨 **하루 2회라는 기존 주기를 유지한다** —
    # 매 사이클로 옮기면 행 수가 수십 배가 되어 성격이 달라진다.
    from src.pipeline.daily_brief import should_send_brief
    if final_picks and should_send_brief(ctx.now_kst,
                                         getattr(ctx, '_report_data_dir', None)):
        storage.update_monthly_excel(final_picks, ctx.now_kst)
```

Stage 4 호출에서 `final_picks=final_picks,`와 `deep_dive_report=deep_dive_report,` 두 줄을 지운다.

- [ ] **Step 5: notifier에서 리포트 발송 경로를 지운다**

`src/pipeline/workers/notifier.py`에서:
- `run()`의 시그니처에서 `final_picks`, `deep_dive_report` 인자를 뺀다
- `slot = self.ctx.report_slot() if ... else None` 줄과 `if slot:` 발송 블록, `else:` 로그 블록을 삭제
- `# 3. reported_codes 상태 업데이트` 블록 전체 삭제(이미 죽은 배선 — `schemas.py:220`에 `[Legacy]`, 실소비자는 `scraper_legacy_v49.py`뿐)
- `# 5. 슬롯 닫기` 블록 삭제
- `_send_report()`와 `_send_fallback_summary()` 메서드 전체 삭제. **`_send_report` 안의 "9개 완성 순위 알림"(124~144행)도 함께 사라진다** — 이것도 추천 목록이라 슬롯 통째 폐기 대상이다
- 모듈 docstring의 인터페이스 목록에서 `send_dashboard_link()`·`send_market_report()` 줄을 지운다

`run()`에 남는 것은 ① 멀티데이 집계 ② 브리핑 발송 ③ 실거래 예약 주문 셋뿐이다.

- [ ] **Step 6: 딥다이브 생성 코드를 지운다**

`src/pipeline/workers/llm_analyzer.py`에서 `generate_deep_dive()` 메서드를 삭제하고, 모듈 docstring의 `StrategyAdvisor.generate_deep_dive_report(list[dict]) → str` 줄과 `Stage 2: ... + 딥다이브 리포트 생성`의 뒷부분을 정리한다.

`src/strategy/advisor.py`에서 `generate_deep_dive_report()` 메서드를 삭제한다.

**`analyze_batch`와 Stage 2 배치 분석은 건드리지 않는다** — `fact_score`를 심1이 쓴다.

- [ ] **Step 7: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_report_retired.py -q`
Expected: PASS

Run: `python -m pytest tests/ -q`
Expected: PASS. 실패하면 리포트를 전제한 오래된 테스트다 — 삭제하거나 브리핑 기준으로 고친다.

- [ ] **Step 8: 커밋**

```bash
git add -A src tests
cat > /tmp/msg.txt <<'MSG'
feat!: 11:00·14:00 리포트 슬롯 폐기 — 대시보드 링크·어텐션·딥다이브 전부

Gemini 딥다이브 생성(Stage 3.5)과 발송 경로를 통째로 지운다. Stage 2 배치
분석은 남긴다 — 심1이 fact_score를 쓴다.

슬롯 안에 숨어 있던 둘을 갈라 처리했다.
- 월별 리서치 엑셀(update_monthly_excel)은 살린다. 08-31에 "살아있는
  산출물이라 유지"로 결정한 것인데 Stage 3.5 안에 중첩돼 있었다.
  발동 조건을 브리핑 슬롯으로 옮겨 하루 2회 주기를 유지한다.
- "9개 완성 순위 알림"은 함께 폐기한다. _send_report 안에 있어 눈에 안
  띄었을 뿐, 추천 목록이라 폐기 대상이다.

reported_codes 갱신도 지운다 — schemas.py에 [Legacy]로 표시돼 있고 실제
소비자는 scraper_legacy_v49.py뿐인 죽은 배선이었다.
MSG
git commit -F /tmp/msg.txt
```

---

### Task 4: 심7 제거

**Files:**
- Modify: `src/strategy/strategy_manifest.yaml:202-216` (블록 삭제)
- Delete: `src/strategy/simulators/sim7_report_follower.py`, `tests/test_sim7_gate.py`
- Modify: `src/pipeline/orchestrator.py` (Stage 3.6, `sim7_should_buy`, `SIM7_BULL_SCORE_MIN`)
- Modify: `scripts/audit_sim_fields.py:34`, `tests/test_all_sims_can_trade.py:178`, `tests/test_needs_buzz_registry.py:28,121`, `tests/test_program_turn.py:186`
- Regenerate: `src/lib/sim-registry.generated.ts`

**Interfaces:**
- Consumes: Task 3의 orchestrator(Stage 3.5가 이미 없음)
- Produces: 심 매니페스트에서 `sim7_report_follower` 제거. `get_sim_registry()` 결과가 하나 줄어 브리핑·대시보드 목록에서 자동으로 빠진다

- [ ] **Step 1: 실패 테스트를 쓴다**

`tests/test_report_retired.py`에 추가:

```python
def test_sim7_is_gone():
    hits = [ln for ln in _grep('sim7').splitlines()]
    assert hits == [], f'심7 참조가 남아 있다: {hits}'


def test_sim7_state_files_are_not_deleted():
    """이력은 보존한다. 매니페스트에서만 빠진다."""
    from src.strategy.registry import get_sim_registry
    ids = {s['id'] for s in get_sim_registry(include_analyzers=True)}
    assert 'sim7_report_follower' not in ids
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `python -m pytest tests/test_report_retired.py -q`
Expected: FAIL — `심7 참조가 남아 있다`

- [ ] **Step 3: 매니페스트 블록과 시뮬레이터 파일을 지운다**

`src/strategy/strategy_manifest.yaml`에서 202~216행(`- id: "sim7_report_follower"`부터 `needs_buzz: true` 주석까지) 블록을 삭제한다.

```bash
git rm src/strategy/simulators/sim7_report_follower.py tests/test_sim7_gate.py
```

- [ ] **Step 4: 나머지 참조를 지운다**

- `src/pipeline/orchestrator.py`: `SIM7_BULL_SCORE_MIN` 상수와 그 위 주석, `sim7_should_buy()` 함수, `# ── Stage 3.6: Sim7 신규 매수` 블록 전체(try/except 포함), 그리고 이제 쓰이지 않는 `read_regime` import를 삭제한다(같은 파일에서 다른 용도로 쓰이면 남긴다 — `git grep read_regime src/pipeline/orchestrator.py`로 확인)
- `scripts/audit_sim_fields.py:34`: `SKIP_SIMS`에서 `'sim7_report_follower'`를 뺀다
- `tests/test_all_sims_can_trade.py`: `test_sim7_report_can_buy` 함수 전체 삭제
- `tests/test_needs_buzz_registry.py`: 28행의 `'sim7_report_follower': True,`와 121행의 `assert 'sim7_report_follower' not in buzz_free` 삭제
- `tests/test_program_turn.py:186`: `sim7_report_follower`를 살아 있는 심(`sim_risk`)으로 교체한다

- [ ] **Step 5: 대시보드 레지스트리를 재생성한다**

```bash
python scripts/gen_sim_registry.py
```

`src/lib/sim-registry.generated.ts`는 손으로 고치지 않는다.

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/ -q`
Expected: PASS

Run: `python scripts/audit_sim_fields.py`
Expected: 심 9개 감사, 거짓 양성 0

- [ ] **Step 7: 커밋**

```bash
git add -A
cat > /tmp/msg.txt <<'MSG'
feat!: 심7(리포트 팔로워) 제거 — 유일한 입력이 사라졌다

심7은 딥다이브 리포트의 "강력 매수" 판정을 유일한 입력으로 삼는다. 그
리포트를 폐기했으므로 심7은 영원히 아무것도 못 산다.

보유 2종목(215600, 950260)은 청산 없이 동결한다(사용자 결정). db-data의
상태 파일과 거래이력은 지우지 않는다 — 이력은 남긴다. 매니페스트에서
빠지는 순간 브리핑·대시보드 목록에서만 사라진다.

audit_sim_fields의 SKIP_SIMS에서도 뺐다. 목록을 남겨두면 다음에 그 이름을
쓰는 심이 생겼을 때 조용히 감사에서 빠진다.
MSG
git commit -F /tmp/msg.txt
```

---

### Task 5: 미국 브리핑 본문 조립 (순수 함수)

**Files:**
- Create: `src/pipeline/us_brief.py`
- Test: `tests/test_us_brief.py`

**Interfaces:**
- Consumes: `src.strategy.us_registry.get_us_sim_registry() -> list[dict]` (키: `label`, `state_file`, `csv_file`)
- Produces:
  - `us_brief.build_us_brief(sims: list[dict], now_kst: datetime) -> str`
  - `us_brief.collect_us_sim_brief(data_dir: str, now_kst: datetime) -> list[dict]` — 각 항목은 `{'label': str, 'profit_rate': float|None, 'ticker_count': int}`
  - `us_brief.overnight_window(now_kst: datetime) -> tuple[str, str]` — `('YYYY-MM-DD HH:MM', 'YYYY-MM-DD HH:MM')`

- [ ] **Step 1: 실패 테스트를 쓴다**

`tests/test_us_brief.py` 신규:

```python
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline.us_brief import (  # noqa: E402
    build_us_brief, collect_us_sim_brief, overnight_window)

NOW = datetime(2026, 9, 1, 9, 5)
OK_SIMS = [
    {'label': 'US 미너비니 추세형 (US Sim 1)', 'profit_rate': 3.21, 'ticker_count': 2},
    {'label': 'US 돈치안 돌파 (US Sim 2)', 'profit_rate': -1.5, 'ticker_count': 4},
    {'label': 'US 기준선·유동성 상위 (US Sim 3)', 'profit_rate': None, 'ticker_count': 0},
]


def test_title_names_the_us_close():
    msg = build_us_brief(OK_SIMS, NOW)
    assert '미국장 마감 브리핑' in msg
    assert '09/01' in msg


def test_unknown_profit_rate_is_not_zero():
    """조회 실패는 '측정 불가'다. 0%는 '정상적으로 본전'이라는 뜻이라 다르다."""
    msg = build_us_brief(OK_SIMS, NOW)
    assert '측정 불가' in msg
    assert '+0.00%' not in msg


def test_signs_are_explicit():
    msg = build_us_brief(OK_SIMS, NOW)
    assert '+3.21%' in msg
    assert '-1.50%' in msg


def test_no_real_account_block():
    """미국 심은 전부 페이퍼다. 실계좌 블록이 있으면 안 된다."""
    msg = build_us_brief(OK_SIMS, NOW)
    assert '실전 계좌' not in msg
    assert '예수금' not in msg


def test_overnight_window_is_prev_2200_to_today_0900():
    since, until = overnight_window(NOW)
    assert since == '2026-08-31 22:00'
    assert until == '2026-09-01 09:00'


def test_collect_counts_only_the_overnight_window(tmp_path):
    (tmp_path / 'sim_us2donchian_state.json').write_text(
        '{"initial_cash": 10000, "cash": 10000, "portfolio": {}}', encoding='utf-8')
    (tmp_path / 'trade_history_sim_us2donchian.csv').write_text(
        'timestamp,symbol\n'
        '2026-08-31 22:31:41,AAPL\n'      # 간밤 — 센다
        '2026-09-01 05:00:00,MSFT\n'      # 간밤 — 센다
        '2026-08-31 15:00:00,TSLA\n',     # 창 밖 — 안 센다
        encoding='utf-8')

    sims = collect_us_sim_brief(str(tmp_path), NOW)
    row = next(s for s in sims if 'US Sim 2' in s['label'])
    assert row['ticker_count'] == 2
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `python -m pytest tests/test_us_brief.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.pipeline.us_brief'`

- [ ] **Step 3: us_brief.py를 만든다**

```python
"""09:00 KST 미국장 마감 브리핑 조립.

국내 브리핑(daily_brief.py)과 형태를 맞추되 **실계좌 블록이 없다** — 미국 심은
전부 페이퍼다. 심 목록은 us_strategy_manifest에서 파생한다. 자체 목록을 갖지
않는다: 손으로 적어두면 새 심이 조용히 빠진다(daily_brief가 같은 이유로
매니페스트 파생이다).
"""
import csv
import json
import os
from datetime import datetime, timedelta

from src.strategy.us_registry import get_us_sim_registry

_WEEKDAY_KR = '월화수목금토일'

# 미국장은 22:30~05:00 KST(서머타임 기준)다. 창을 22:00~09:00으로 넉넉히 잡아
# 서머타임 전환(23:30~06:00)에도 세션 전체가 들어오게 한다. 이 창에는 국내장이
# 없으므로 국내 거래를 잘못 셀 위험이 없다.
_WINDOW_START_HHMM = '22:00'
_WINDOW_END_HHMM = '09:00'


def _signed_pct(v) -> str:
    return f"{'+' if v >= 0 else ''}{v:.2f}%"


def overnight_window(now_kst: datetime) -> tuple[str, str]:
    """간밤 미국 세션의 (시작, 끝) — 'YYYY-MM-DD HH:MM' 두 개.

    미국 거래이력의 timestamp는 KST다(2026-08-31 22:31:41 = 개장 직후).
    """
    prev = (now_kst - timedelta(days=1)).strftime('%Y-%m-%d')
    today = now_kst.strftime('%Y-%m-%d')
    return f'{prev} {_WINDOW_START_HHMM}', f'{today} {_WINDOW_END_HHMM}'


def _profit_rate_from_state(path: str):
    """대시보드와 같은 식으로 수익률을 계산한다. 모르면 None(0.0이 아니다)."""
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            state = json.load(f)
        initial_cash = state.get('initial_cash')
        if not initial_cash or initial_cash <= 0:
            return None
        current_prices = (state.get('raw_stats') or {}).get('current_prices') or {}
        portfolio_value = 0
        for code, item in (state.get('portfolio') or {}).items():
            price = (current_prices.get(code) or item.get('current_price')
                     or item.get('avg_price') or 0)
            qty = item.get('quantity') or item.get('qty') or 0
            portfolio_value += price * qty
        total = (state.get('cash') or 0) + portfolio_value
        return (total - initial_cash) / initial_cash * 100
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"[USBrief] 상태 파일 읽기 실패: {path} — {type(e).__name__}: {e}")
        return None


def _count_tickers(path: str, since: str, until: str) -> int:
    """창 안에서 매매한 종목 수(중복 제거). 파일이 없으면 거래가 없었다는 뜻이라 0."""
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return len({
                row['symbol'] for row in csv.DictReader(f)
                if row.get('symbol') and since <= (row.get('timestamp') or '') < until
            })
    except FileNotFoundError:
        return 0
    except Exception as e:
        print(f"[USBrief] 거래이력 읽기 실패: {path} — {type(e).__name__}: {e}")
        return 0


def collect_us_sim_brief(data_dir: str, now_kst: datetime) -> list[dict]:
    """미국 심별 (표시명, 누적 수익률, 간밤 거래 종목 수)."""
    since, until = overnight_window(now_kst)
    return [
        {
            'label': s['label'],
            'profit_rate': _profit_rate_from_state(
                os.path.join(data_dir, s['state_file'])),
            'ticker_count': _count_tickers(
                os.path.join(data_dir, s['csv_file']), since, until),
        }
        for s in get_us_sim_registry()
    ]


def build_us_brief(sims: list[dict], now_kst: datetime) -> str:
    """마감 브리핑 본문. 순수 함수 — I/O 없음."""
    day = f"{now_kst.strftime('%m/%d')} ({_WEEKDAY_KR[now_kst.weekday()]})"
    lines = [f"🇺🇸 미국장 마감 브리핑  {day}", '',
             '🤖 US 심별 현황 (누적 수익률 / 간밤 거래)']
    for s in sims:
        rate = s.get('profit_rate')
        rate_str = '측정 불가' if rate is None else _signed_pct(rate)
        lines.append(f"  {s['label']:<28} {rate_str:>9}   {s.get('ticker_count', 0)}종목")
    return '\n'.join(lines)
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_us_brief.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/pipeline/us_brief.py tests/test_us_brief.py
cat > /tmp/msg.txt <<'MSG'
feat(us-brief): 미국장 마감 브리핑 본문 조립 (순수 함수)

국내 브리핑과 형태를 맞추되 실계좌 블록이 없다 — 미국 심은 전부 페이퍼다.
심 목록은 us_strategy_manifest에서 파생한다.

간밤 창은 전일 22:00 ~ 당일 09:00 KST다. 미국 거래이력의 timestamp가 KST
기준임을 실측 확인했고(22:31:41 = 개장 직후), 창을 넉넉히 잡아 서머타임
전환에도 세션 전체가 들어온다. 이 창에는 국내장이 없어 오염되지 않는다.

조회 실패는 '측정 불가'다. 0%는 '정상적으로 본전'이라는 뜻이라 다르다.
MSG
git commit -F /tmp/msg.txt
```

---

### Task 6: 미국 브리핑을 trade_loop에 배선

**Files:**
- Modify: `src/report/gate.py` (`US_BRIEF_SLOT`, `US_BRIEF_STATE_FILENAME`, `us_brief_due`)
- Modify: `scripts/trade_loop.py` (발송 스텝 + `regime_output_files`에 상태 파일 추가)
- Test: `tests/test_us_brief.py`, `tests/test_workflow_file_ownership.py`

**Interfaces:**
- Consumes: Task 1의 `_due(..., filename=)`, Task 5의 `build_us_brief`·`collect_us_sim_brief`
- Produces: `gate.us_brief_due(now_kst, data_dir=None) -> bool`, `gate.US_BRIEF_SLOT = '09:00'`, `gate.US_BRIEF_STATE_FILENAME = 'us_brief_gate_state.json'`

- [ ] **Step 1: 실패 테스트를 쓴다**

`tests/test_us_brief.py`에 추가:

```python
def test_us_slot_does_not_touch_the_kr_gate_state(tmp_path):
    """writer가 하나여야 한다. 미국 브리핑이 국내 상태 파일을 건드리면
    scraper.yml이 방금 닫은 슬롯이 다시 열린다."""
    from src.report import gate
    now = datetime(2026, 9, 1, 9, 5)

    assert gate.us_brief_due(now, str(tmp_path)) is True
    gate.mark_sent(gate.US_BRIEF_SLOT, now, str(tmp_path),
                   filename=gate.US_BRIEF_STATE_FILENAME)

    assert gate.us_brief_due(now, str(tmp_path)) is False
    assert not (tmp_path / gate.STATE_FILENAME).exists()
    # 국내 브리핑 판정은 영향을 받지 않는다
    assert gate.brief_due(datetime(2026, 9, 1, 12, 5), str(tmp_path)) == '12:00'


def test_us_slot_window_is_40_minutes():
    from src.report import gate
    assert gate.us_brief_due(datetime(2026, 9, 1, 9, 39)) is True
    assert gate.us_brief_due(datetime(2026, 9, 1, 9, 41)) is False
    assert gate.us_brief_due(datetime(2026, 9, 1, 8, 59)) is False
```

`tests/test_workflow_file_ownership.py`에 추가:

```python
def test_trading_deploys_the_us_brief_gate_state():
    """미국 브리핑 슬롯의 writer는 trading.yml이다.

    db-data를 왕복하지 못하면 매 런이 새 컨테이너라 '아직 안 보냈다'로 읽고
    09:00~09:40 창의 20번 트리거가 전부 브리핑을 보낸다."""
    from src.report.gate import US_BRIEF_STATE_FILENAME
    import scripts.trade_loop as trade_loop

    now = __import__('datetime').datetime(2026, 9, 1, 9, 5)
    names = trade_loop.regime_output_files(now)
    assert US_BRIEF_STATE_FILENAME in names


def test_scraper_does_not_own_the_us_brief_gate_state():
    """국내 리포트 게이트와 **반대 방향**의 소유권이다.

    report_gate_state.json은 scraper.yml이 배포하고 trading.yml이 안 한다.
    us_brief_gate_state.json은 그 반대다. 한쪽이 남의 파일을 같이 올리면
    lost update로 닫은 슬롯이 다시 열린다.
    """
    from src.report.gate import US_BRIEF_STATE_FILENAME
    assert US_BRIEF_STATE_FILENAME not in _text('scraper.yml'), (
        f'{US_BRIEF_STATE_FILENAME}을 scraper.yml이 배포하면 writer가 둘이 된다')
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `python -m pytest tests/test_us_brief.py tests/test_workflow_file_ownership.py -q`
Expected: FAIL — `AttributeError: module 'src.report.gate' has no attribute 'us_brief_due'`

- [ ] **Step 3: gate.py에 미국 슬롯을 더한다**

`src/report/gate.py`에 추가한다:

```python
# 미국장 마감 브리핑(09:00 KST). **상태 파일이 국내와 다르다.**
# report_gate_state.json은 writer가 scraper.yml 하나라는 게 명시적 계약이고
# tests/test_workflow_file_ownership.py가 그걸 강제한다 — trading.yml이 같이
# 쓰면 lost update로 닫은 슬롯이 다시 열려 09:00~09:40에 브리핑이 20번 나간다.
US_BRIEF_SLOT = '09:00'
US_BRIEF_STATE_FILENAME = 'us_brief_gate_state.json'


def us_brief_due(now_kst: datetime, data_dir: str | None = None) -> bool:
    """지금 미국장 마감 브리핑을 보낼 차례인가. 국내 슬롯과 완전히 독립이다."""
    return _due(now_kst, (US_BRIEF_SLOT,), data_dir,
                filename=US_BRIEF_STATE_FILENAME) is not None
```

- [ ] **Step 4: trade_loop에 발송을 배선한다**

`scripts/trade_loop.py`의 `regime_output_files`가 돌려주는 목록에 상태 파일을 더한다:

```python
    out = [os.path.basename(month_path(now)), 'regime_gate_state.json',
           'us_brief_gate_state.json']
```

주석도 한 줄 늘린다:

```python
    # 미국장 마감 브리핑(09:00 KST) 슬롯도 이 워크플로가 유일 writer다. 이게
    # db-data에 도달하지 못하면 40분 창의 20번 트리거가 전부 브리핑을 보낸다.
```

매매 1바퀴가 끝난 뒤(국면 로그 다음, 배포 매니페스트 기록 앞) 발송 스텝을 넣는다:

```python
def _send_us_brief_if_due(now_kst, log=print) -> None:
    """09:00 KST 미국장 마감 브리핑. 실패해도 매매 루프를 멈추지 않는다.

    발송에 **성공한 직후에만** 슬롯을 닫는다. 실패를 '보냈다'로 적으면 그날
    회차가 통째로 사라진다.
    """
    from src.report import gate
    if not gate.us_brief_due(now_kst, 'data'):
        return
    try:
        from src.pipeline.us_brief import build_us_brief, collect_us_sim_brief
        from src.telegram_manager import TelegramManager

        sims = collect_us_sim_brief('data', now_kst)
        if TelegramManager().send_message(build_us_brief(sims, now_kst)):
            gate.mark_sent(gate.US_BRIEF_SLOT, now_kst, 'data',
                           filename=gate.US_BRIEF_STATE_FILENAME)
            log('[USBrief] 미국장 마감 브리핑 발송 완료 — 슬롯을 닫습니다')
        else:
            log('[USBrief] 텔레그램 발송 실패 — 슬롯을 열어 둡니다(다음 틱 재시도)')
    except Exception as e:
        log(f'[USBrief] 브리핑 실패: {type(e).__name__}: {e}')
```

호출은 `_write_deploy_manifest(...)` **앞에** 둔다 — 매니페스트가 이 스텝이 쓴 상태 파일을 포함해야 한다.

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_us_brief.py tests/test_workflow_file_ownership.py -q`
Expected: PASS

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: 워크플로 문법을 확인한다**

Run: `for f in .github/workflows/*.yml; do python -c "import yaml,sys; yaml.safe_load(open('$f',encoding='utf-8'))" || echo "FAIL $f"; done`
Expected: 출력 없음

- [ ] **Step 7: 커밋**

```bash
git add src/report/gate.py scripts/trade_loop.py tests/test_us_brief.py tests/test_workflow_file_ownership.py
cat > /tmp/msg.txt <<'MSG'
feat(us-brief): 09:00 KST 미국장 마감 브리핑을 trading.yml에서 보낸다

슬롯 상태는 us_brief_gate_state.json에 쓴다 — report_gate_state.json은
writer가 scraper.yml 하나라는 게 명시적 계약이고, trading.yml이 같이 쓰면
lost update로 닫은 슬롯이 다시 열려 09:00~09:40에 20번 나간다.

그 파일을 배포 매니페스트에 넣는다. db-data를 왕복하지 못하면 매 런이 새
컨테이너라 "아직 안 보냈다"로 읽어 같은 일이 벌어진다.

발송에 성공한 직후에만 슬롯을 닫는다. 실패하면 창이 열려 있는 동안 다음
틱이 재시도한다.
MSG
git commit -F /tmp/msg.txt
```

---

### Task 7: premarket intraday를 gzip으로 커밋

`rt_intraday_20260831.csv`가 115.14MB로 GitHub 100MB 한도를 넘어 push가 거부됐다(2026-08-31, 이 잡의 첫 실행). rebase 3회 재시도는 파일 크기를 바꾸지 않으므로 전부 같은 이유로 죽는다.

**Files:**
- Modify: `.github/workflows/premarket_data.yml` (intraday 잡의 `커밋 (db-data)` 스텝)
- Test: `tests/test_workflow_file_ownership.py`

**Interfaces:**
- Consumes: 없음(독립)
- Produces: db-data에 `data/rt_intraday_YYYYMMDD.csv.gz`

- [ ] **Step 1: 실패 테스트를 쓴다**

`tests/test_workflow_file_ownership.py`에 추가:

```python
def test_intraday_is_committed_compressed():
    """원시 CSV는 100MB 한도를 넘는다(2026-08-31 실측 115.14MB).

    첫 실행에서 push가 거부됐고, rebase 재시도는 크기를 안 바꾸므로 3회가
    전부 같은 이유로 죽었다.
    """
    intraday = _text('premarket_data.yml').split('  intraday:', 1)[1]
    assert 'gzip' in intraday, 'intraday 커밋이 압축하지 않는다'
    assert 'rt_intraday_*.csv.gz' in intraday or '.csv.gz' in intraday


def test_intraday_fails_loudly_when_still_too_large():
    """압축 후에도 한도를 넘으면 조용히 잘리지 않고 실패해야 한다."""
    intraday = _text('premarket_data.yml').split('  intraday:', 1)[1]
    assert '104857600' in intraday, '압축 후 크기 검사가 없다'
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `python -m pytest tests/test_workflow_file_ownership.py -q`
Expected: FAIL — `intraday 커밋이 압축하지 않는다`

- [ ] **Step 3: 커밋 스텝을 gzip으로 바꾼다**

`.github/workflows/premarket_data.yml`의 **intraday 잡** `커밋 (db-data)` 스텝에서 복사 루프를 교체한다. collect 잡의 같은 이름 스텝은 건드리지 않는다.

```bash
          # gzip으로 커밋한다. 원시 CSV는 100MB 한도를 넘는다 — 2026-08-31
          # 첫 실행에서 115.14MB로 push가 거부됐다(체결 H0STCNT0 + 호가
          # H0STASP0 2TR × 20종목 × 2시간반). rebase 재시도는 파일 크기를
          # 바꾸지 않으므로 3회가 전부 같은 이유로 죽는다.
          for f in data/rt_intraday_*.csv; do
            [ -e "$f" ] || { echo "없음: $f"; continue; }
            gzip -9 -c "$f" > "db_data_repo/data/$(basename "$f").gz"
          done
          # 압축 후에도 한도를 넘으면 **명시적으로 실패한다.** 조용히 잘리거나
          # push가 거부되는 것보다 낫다 — 실패 알림이 사람을 부른다.
          for g in db_data_repo/data/rt_intraday_*.csv.gz; do
            [ -e "$g" ] || continue
            sz=$(stat -c%s "$g")
            echo "[Deploy] $(basename "$g"): $((sz / 1024 / 1024))MB"
            if [ "$sz" -gt 104857600 ]; then
              echo "[Deploy] 압축 후에도 100MB 초과 — 수집 범위를 줄여야 한다"
              exit 1
            fi
          done
```

- [ ] **Step 4: 테스트와 셸 문법을 확인한다**

Run: `python -m pytest tests/test_workflow_file_ownership.py -q`
Expected: PASS

Run: `python -c "import yaml; d=yaml.safe_load(open('.github/workflows/premarket_data.yml',encoding='utf-8')); [print(s['run']) for j in d['jobs'].values() for s in j['steps'] if 'run' in s]" > /tmp/steps.sh && bash -n /tmp/steps.sh; echo "exit=$?"`
Expected: `exit=0`

- [ ] **Step 5: 전체 테스트**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add .github/workflows/premarket_data.yml tests/test_workflow_file_ownership.py
cat > /tmp/msg.txt <<'MSG'
fix(premarket): intraday를 gzip으로 커밋 — 115MB가 100MB 한도를 넘었다

2026-08-31에 collect가 도입 이래 처음 성공하면서 intraday 잡이 처음
실행됐고, 첫 실행에서 rt_intraday_20260831.csv 115.14MB로 push가 거부됐다.
체결+호가 2TR × 20종목 × 2시간반이면 넘게 되어 있다. rebase 3회 재시도는
파일 크기를 안 바꾸니 전부 같은 이유로 죽었다.

db-data에 이 파일이 올라간 적이 한 번도 없어(git log 0건) 읽는 쪽 수정은
필요 없다.

압축 후에도 한도를 넘으면 명시적으로 실패시킨다 — 조용한 실패보다 낫다.
MSG
git commit -F /tmp/msg.txt
```

---

## 배포 후 검증 지점

구현이 끝나고 main에 병합한 뒤 아래를 순서대로 확인한다. **초록 런이 의도한
경로를 탄 것을 뜻하지 않는다** — 로그에서 판정을 직접 읽는다.

1. **당일 11:00·14:00 KST** — 리포트가 **오지 않는지**. 텔레그램에 아무것도 안 오면 성공이다.
2. **당일 12:00 KST** — 국내 오전 브리핑 도착. 종목 수가 09:00~12:00 거래만 세는지 `trade_history_sim_*.csv`와 대조한다.
3. **당일 15:00 KST** — 마감 브리핑 문구·수치가 종전과 같은지(회귀 없음). 12시를 보낸 뒤에도 열리는지가 핵심이다.
4. **당월 리서치 엑셀** — `reports/monthly_research_2026-09.xlsx`에 12:00·15:00 두 시각의 행이 붙는지. 안 붙으면 살리려던 산출물이 죽은 것이다.
5. **익일 09:00 KST** — 미국 마감 브리핑 도착. `us_brief_gate_state.json`이 db-data에 커밋되고 09:00~09:40에 **한 번만** 오는지 확인한다(중복이 오면 배포 매니페스트가 빠진 것이다).
6. **익일 07:20 KST** — premarket intraday가 push에 성공하고 `data/rt_intraday_*.csv.gz`가 db-data에 처음 올라오는지. 압축 후 크기 로그(`[Deploy] ...MB`)를 함께 읽는다.

## 이 계획이 다루지 않는 것

- **심5 진단 이력.** 심5가 왜 안 샀는지는 여전히 소급 확인 불가로 남는다. 심13의 "후보 0" 구간도 같다. 별건이다.
- **`telegram_manager.send_market_report` / `send_dashboard_link` 메서드 삭제.** `scripts/scraper_legacy_v49.py`가 아직 참조한다. 이 변경이 만든 고아가 아니므로 남긴다.
- **Stage 2 Gemini 배치 분석.** `fact_score`를 심1이 쓴다. 그대로 둔다.
