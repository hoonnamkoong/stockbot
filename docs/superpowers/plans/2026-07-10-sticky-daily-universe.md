# 당일 채택 종목 고정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 당일 채택된 종목을 거래량 상위 이탈·임계값 상승과 무관하게 그날 끝까지 추적해 기록에 남긴다. 매매 동작은 바꾸지 않는다.

**Architecture:** 채택 이력을 `data/daily_adopted.json`에 날짜 단위로 보관한다. Stage 1이 유니버스를 `거래량 상위 ∪ 당일 채택 종목`으로 넓히고 각 종목을 `활성`(임계값 통과) / `추적`(채택 이력만) 으로 분류한다. Stage 2는 `활성`만 Gemini로 분석하고 `추적`에는 캐시된 요약을 붙인 뒤 둘 다 기록한다. Stage 3(매매)에는 `활성`만 넘긴다.

**Tech Stack:** Python 3.10, pydantic v2, pandas, pytest, Next.js/TypeScript(대시보드)

**Spec:** `docs/superpowers/specs/2026-07-10-sticky-daily-universe-design.md`

## Global Constraints

- 주석과 로그는 한국어로 쓴다 (기존 코드 관행).
- 매매 경로(`TradeEngineWorker` 이하)의 동작은 변하지 않아야 한다.
- 상태 문자열은 정확히 `'활성'`, `'추적'` 두 가지다.
- 기록에 `상태` 컬럼이 없는 과거 데이터는 전부 `활성`으로 간주한다.
- 반쪽 런(`ctx.scrape_degraded()`)에서는 아무것도 기록하지 않고 레지스트리도 갱신하지 않는다.
- 모든 테스트는 `python -m pytest tests/ -q`로 돌린다. `tests/test_kis_news.py::test_get_news_titles_uses_cache`는 이 작업 이전부터 실패하는 기존 결함이므로 무시한다.

## File Structure

| 파일 | 책임 |
|---|---|
| `src/data/adopted_registry.py` (신규) | 당일 채택 레지스트리 로드/저장, 날짜 경계 초기화 |
| `src/data/schemas.py` | `StockData.status` 필드 추가 |
| `src/pipeline/workers/data_fetcher.py` | 유니버스 합집합, 활성/추적 판정, 시세 보강 |
| `src/pipeline/workers/llm_analyzer.py` | 활성만 AI, 추적은 캐시, 레지스트리 저장 |
| `src/pipeline/orchestrator.py` | 매매에 활성만 전달 |
| `src/strategy/analyzer.py` | 기록에 `상태` 컬럼 |
| `src/analyzer_5days.py` | 스냅샷 읽을 때 `활성`만 |
| `src/app/research/types.ts`, `hooks/useResearchSource.ts`, `components/ResearchTables.tsx` | 대시보드에서 추적 종목 구분 표시 |

---

### Task 1: 채택 레지스트리

**Files:**
- Create: `src/data/adopted_registry.py`
- Test: `tests/test_adopted_registry.py`

**Interfaces:**
- Produces: `load(today_str: str) -> dict[str, dict]`, `save(today_str: str, stocks: dict[str, dict]) -> None`, 상수 `PATH`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_adopted_registry.py
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from src.data import adopted_registry as reg


@pytest.fixture(autouse=True)
def chdir_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_no_file_returns_empty():
    assert reg.load('20260710') == {}


def test_roundtrip_same_day():
    reg.save('20260710', {'002990': {'name': '금호건설'}})
    assert reg.load('20260710') == {'002990': {'name': '금호건설'}}


def test_date_change_resets():
    """어제 채택분이 오늘로 넘어오면 안 된다."""
    reg.save('20260709', {'002990': {'name': '금호건설'}})
    assert reg.load('20260710') == {}


def test_corrupt_file_returns_empty():
    os.makedirs('data', exist_ok=True)
    with open(reg.PATH, 'w', encoding='utf-8') as f:
        f.write('{ broken')
    assert reg.load('20260710') == {}
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_adopted_registry.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.data.adopted_registry'`

- [ ] **Step 3: 최소 구현**

```python
# src/data/adopted_registry.py
"""당일 채택 종목 레지스트리.

한 번 임계값을 넘겨 채택된 종목은 거래량 상위에서 빠지거나 임계값이 올라
미달이 되어도 그날 안에는 계속 추적한다. 그 이력을 날짜 단위로 보관한다.

sync_state.json을 쓰지 않는 이유: SyncState.stocks는 종목코드가 키여야 하는데
data_fetcher가 평면 dict를 .update()로 병합해 종목별 저장이 동작하지 않는다.
"""
import json
import os

PATH = 'data/daily_adopted.json'


def load(today_str: str) -> dict:
    """오늘 채택된 종목 {code: info}. 날짜가 다르거나 파일이 없으면 빈 dict."""
    if not os.path.exists(PATH):
        return {}
    try:
        with open(PATH, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception:
        return {}
    if raw.get('date') != today_str:
        return {}
    return raw.get('stocks', {})


def save(today_str: str, stocks: dict) -> None:
    os.makedirs('data', exist_ok=True)
    with open(PATH, 'w', encoding='utf-8') as f:
        json.dump({'date': today_str, 'stocks': stocks}, f, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_adopted_registry.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/data/adopted_registry.py tests/test_adopted_registry.py
git commit -m "feat(scraper): 당일 채택 종목 레지스트리 추가"
```

---

### Task 2: 거래상위 밖 종목의 현재가 보강

거래량 상위 표에서 빠진 종목은 `current_price`가 없다. 네이버 외인 페이지(`frgn.naver`)의 첫 데이터 행에 종가(현재가)가 있다. 컬럼 순서는 `날짜(0) 종가(1) 전일비(2) 등락률(3) 거래량(4) 기관순매매(5) 외국인순매매(6) 보유주수(7) 보유율(8)`이다.

`change_rate`는 `data_fetcher.run()`이 `prev_close`와 가격으로 다시 계산하므로 따로 파싱하지 않는다.

**Files:**
- Modify: `src/pipeline/workers/data_fetcher.py` (`_get_stock_details`)
- Test: `tests/test_data_fetcher_details.py`

**Interfaces:**
- Produces: `_get_stock_details(code)` 반환 dict에 `current_price: int` 추가

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_data_fetcher_details.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from src.pipeline.workers import data_fetcher
from src.pipeline.workers.data_fetcher import DataFetcherWorker


def frgn_html():
    def row(date, close, rate, foreign_rate):
        return (
            f'<tr><td>{date}</td><td>{close}</td><td>0</td><td>{rate}</td>'
            f'<td>1</td><td>10</td><td>20</td><td>30</td><td>{foreign_rate}%</td></tr>'
        )
    return ('<table class="type2">'
            + row('2026.07.10', '17,940', '+3.64%', '3.47')
            + row('2026.07.09', '17,310', '+1.00%', '3.40')
            + '</table>')


class FakeResponse:
    def __init__(self, html):
        self.content = html.encode('utf-8')


def test_current_price_is_parsed(monkeypatch):
    """거래상위에서 빠진 종목도 현재가를 얻어야 한다."""
    monkeypatch.setattr(data_fetcher.requests, 'get',
                        lambda url, **kw: FakeResponse(frgn_html()))
    w = object.__new__(DataFetcherWorker)

    d = w._get_stock_details('002990')

    assert d['current_price'] == 17940
    assert d['prev_close'] == 17310
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_data_fetcher_details.py -q`
Expected: FAIL — `KeyError: 'current_price'`

- [ ] **Step 3: 최소 구현**

`src/pipeline/workers/data_fetcher.py`의 `_get_stock_details` 안, `details['prev_foreign_rate'] = prev_rate` 바로 아래에 추가한다.

```python
                # 거래상위에서 빠진 종목은 시세를 여기서만 얻을 수 있다 (표 첫 행 = 오늘 종가/현재가)
                details['current_price'] = int(data_rows[0][1].get_text().replace(',', '').strip() or 0)
```

그리고 함수 상단 기본값 dict에도 키를 추가한다.

```python
        details = {
            'foreign_rate': 0.0, 'foreign_change': 0.0,
            'foreign_net_buy': 0, 'prev_close': 0, 'prev_foreign_rate': 0.0,
            'current_price': 0,
        }
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_data_fetcher_details.py -q`
Expected: PASS

주의: `s.update(d)`가 거래량 상위에서 온 `current_price`를 덮어쓴다. 두 값 모두 같은 종목의 현재가이므로 문제 없다.

- [ ] **Step 5: 커밋**

```bash
git add src/pipeline/workers/data_fetcher.py tests/test_data_fetcher_details.py
git commit -m "feat(scraper): 외인 페이지에서 현재가 파싱 (거래상위 밖 종목용)"
```

---

### Task 3: 유니버스 합집합 + 활성/추적 판정

**Files:**
- Modify: `src/data/schemas.py` (`StockData`)
- Modify: `src/pipeline/workers/data_fetcher.py` (`run`, `process_one`)
- Test: `tests/test_sticky_universe.py`

**Interfaces:**
- Consumes: `adopted_registry.load` (Task 1)
- Produces: `StockData.status: str` — `'활성'` 또는 `'추적'`. `DataFetcherWorker.run()`은 둘을 합쳐 반환한다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_sticky_universe.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from src.data.schemas import StockData


def test_stockdata_defaults_to_active():
    s = StockData(code='002990', name='금호건설')
    assert s.status == '활성'


def test_classify_active_when_threshold_met():
    from src.pipeline.workers.data_fetcher import classify
    assert classify(count=90, threshold=80, adopted=set()) == '활성'


def test_classify_tracked_when_adopted_but_below_threshold():
    """9시에 채택된 종목은 11시 임계값을 못 넘겨도 리스트에 남는다."""
    from src.pipeline.workers.data_fetcher import classify
    assert classify(count=70, threshold=80, adopted={'002990'}, code='002990') == '추적'


def test_classify_drops_unadopted_below_threshold():
    from src.pipeline.workers.data_fetcher import classify
    assert classify(count=70, threshold=80, adopted=set(), code='002990') is None
```

`classify` 시그니처: `classify(count: int, threshold: int, adopted: set, code: str = '') -> str | None`

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_sticky_universe.py -q`
Expected: FAIL — `ImportError: cannot import name 'classify'`, 그리고 `StockData`에 `status` 없음

- [ ] **Step 3: 최소 구현**

`src/data/schemas.py`의 `StockData`에 추가한다 (`consecutive_days` 아래).

```python
    status: str = '활성'        # '활성'(임계값 통과) | '추적'(당일 채택 이력만)
```

`src/pipeline/workers/data_fetcher.py` 모듈 최상단(상수 아래)에 추가한다.

```python
def classify(count: int, threshold: int, adopted: set, code: str = '') -> str | None:
    """임계값은 신규 채택 기준으로만 쓴다. 이미 채택된 종목은 미달이어도 추적한다."""
    if count >= threshold:
        return '활성'
    if code in adopted:
        return '추적'
    return None
```

`run()`에서 유니버스를 넓힌다. `candidates = (...)` 직후에 추가한다.

```python
        from src.data import adopted_registry
        adopted = adopted_registry.load(self.ctx.today_str)
        known = {c['code'] for c in candidates}
        for code, info in adopted.items():
            if code not in known:
                candidates.append({'code': code, 'name': info.get('name', ''),
                                   'market': info.get('market', '')})
        self.log(f"유니버스 {len(candidates)}개 (당일 채택 {len(adopted)}개 포함)")
```

`process_one`의 판정부를 교체한다.

```python
                status = classify(count, self.ctx.threshold, set(adopted), s['code'])
                if status is None:
                    return None, stats['updated_state'], False, pages

                s['recent_posts_count'] = count
                s['status'] = status
                if status == '활성':
                    posts = sorted(stats['new_posts'], key=lambda x: x['likes'], reverse=True)[:5]
                    for p in posts:
                        p['body'] = self._get_post_body(s['code'], p['nid'])
                    s['posts'] = posts
                else:
                    s['posts'] = []
                return s, stats['updated_state'], True, pages
```

`5. 연속 카운트 갱신`의 `passed_codes`는 활성만 세도록 바꾼다 (추적 종목이 연속일수를 늘리면 안 된다).

```python
        passed_codes = [s['code'] for s in results_raw if s.get('status') == '활성']
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_sticky_universe.py tests/test_scrape_reliability.py -q`
Expected: PASS (기존 수집 테스트도 그대로 통과)

- [ ] **Step 5: 커밋**

```bash
git add src/data/schemas.py src/pipeline/workers/data_fetcher.py tests/test_sticky_universe.py
git commit -m "feat(scraper): 유니버스에 당일 채택 종목 합집합, 활성/추적 분류"
```

---

### Task 4: AI는 활성만, 추적은 캐시 재사용

**Files:**
- Modify: `src/pipeline/workers/llm_analyzer.py`
- Test: `tests/test_llm_analyzer_sticky.py`

**Interfaces:**
- Consumes: `StockData.status` (Task 3), `adopted_registry` (Task 1)
- Produces: `LLMAnalyzerWorker._persist(candidates)` 가 레지스트리도 저장한다

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_llm_analyzer_sticky.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from src.pipeline.workers import llm_analyzer
from src.pipeline.workers.llm_analyzer import LLMAnalyzerWorker


class FakeCtx:
    scrape_pages_failed = 0
    scrape_pages_total = 100
    today_str = '20260710'
    now_kst = None

    def log(self, msg): pass

    def scrape_degraded(self):
        from src.pipeline.context import PipelineContext
        return PipelineContext.scrape_degraded(self)


class FakeStorage:
    def __init__(self): self.saved = []
    def save_latest_stocks(self, stocks, now_kst): self.saved.append(stocks)


@pytest.fixture(autouse=True)
def chdir_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def make_worker():
    w = object.__new__(LLMAnalyzerWorker)
    w.ctx = FakeCtx()
    w.storage = FakeStorage()
    return w


def test_ai_batch_receives_active_only(monkeypatch):
    """추적 종목은 Gemini 배치 대상이 아니다."""
    seen = []
    monkeypatch.setattr(llm_analyzer, 'analyze_batch', lambda c: seen.extend(x['code'] for x in c) or {})
    w = make_worker()
    active = [{'code': '111111', 'status': '활성'}]
    tracked = [{'code': '222222', 'status': '추적'}]

    w._analyze_active(active + tracked)

    assert seen == ['111111']


def test_tracked_stock_reuses_cached_summary(monkeypatch):
    from src.data import adopted_registry
    adopted_registry.save('20260710', {
        '222222': {'name': '비엘팜텍', 'market': 'KOSDAQ',
                   'ai': {'posts_summary': '캐시된 요약', 'sentiment': 'Positive', 'keywords': ['텅스텐']}},
    })
    w = make_worker()
    tracked = [{'code': '222222', 'status': '추적'}]

    w._apply_cached_ai(tracked)

    assert tracked[0]['posts_summary'] == '캐시된 요약'
    assert tracked[0]['sentiment'] == 'Positive'


def test_persist_updates_registry(monkeypatch):
    from src.data import adopted_registry
    monkeypatch.setattr(llm_analyzer.analyzer, 'analyze_discussion_trend', lambda c: (c, None))
    monkeypatch.setattr(llm_analyzer.analyzer, 'save_data', lambda df: None)
    w = make_worker()

    w._persist([{'code': '111111', 'name': '금호건설', 'market': 'KOSPI', 'status': '활성',
                 'posts_summary': '요약', 'sentiment': 'Positive', 'keywords': []}])

    assert '111111' in adopted_registry.load('20260710')


def test_degraded_run_does_not_touch_registry(monkeypatch):
    from src.data import adopted_registry
    w = make_worker()
    w.ctx.scrape_pages_failed = 50

    assert w._persist([{'code': '111111', 'status': '활성'}]) is False
    assert adopted_registry.load('20260710') == {}
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_llm_analyzer_sticky.py -q`
Expected: FAIL — `_analyze_active`, `_apply_cached_ai` 없음

- [ ] **Step 3: 최소 구현**

`src/pipeline/workers/llm_analyzer.py` 상단에 추가한다.

```python
from src.data import adopted_registry


def analyze_batch(candidates: list[dict]) -> dict:
    """StrategyAdvisor 호출을 감싸 테스트에서 대체할 수 있게 한다."""
    from src.strategy.advisor import StrategyAdvisor
    return StrategyAdvisor().analyze_batch_discovery(candidates)
```

`_run_with_ai`를 아래로 바꾼다.

```python
    def _run_with_ai(self, candidates: list[dict]) -> list[dict]:
        """Gemini 배치 분석 (활성 종목만). 추적 종목은 캐시된 요약을 재사용한다."""
        self._analyze_active(candidates)
        self._apply_cached_ai(candidates)
        self._persist(candidates)
        self.log("AI 분석 완료")
        return candidates

    def _analyze_active(self, candidates: list[dict]) -> None:
        active = [c for c in candidates if c.get('status', '활성') == '활성']
        if not active:
            return
        self.log(f"AI 배치 분석 시작 ({len(active)}개 종목)")
        time.sleep(2)  # 429 방어용 지연
        batch_results = analyze_batch(active)

        for s in active:
            ai = batch_results.get(s['code'])
            if ai:
                s['posts_summary'] = ai.get('summary', '분석 오류')
                s['sentiment'] = str(ai.get('sentiment', 'Neutral'))
                s['keywords'] = ai.get('keywords', [])

            if s.get('posts_summary') in [None, "분석 대기중", "분석 오류", "AI 분석 불가", ""]:
                kws = ", ".join(s.get('keywords', [])) or "시장 주도주"
                s['posts_summary'] = f"[데이터 분석] '{kws}' 중심 {s.get('recent_posts_count', 0)}건 토론 포착"

    def _apply_cached_ai(self, candidates: list[dict]) -> None:
        """추적 종목에는 마지막으로 활성이었을 때의 AI 결과를 붙인다."""
        registry = adopted_registry.load(self.ctx.today_str)
        for s in candidates:
            if s.get('status') != '추적':
                continue
            ai = registry.get(s['code'], {}).get('ai', {})
            s['posts_summary'] = ai.get('posts_summary', '추적 중 (신규 게시글 적음)')
            s['sentiment'] = ai.get('sentiment', 'Neutral')
            s['keywords'] = ai.get('keywords', [])
```

`_persist`에 레지스트리 갱신을 더한다 (기존 저장 3줄 뒤).

```python
        df_final, _ = analyzer.analyze_discussion_trend(candidates)
        analyzer.save_data(df_final)
        self.storage.save_latest_stocks(candidates, self.ctx.now_kst)
        self._update_registry(candidates)
        return True

    def _update_registry(self, candidates: list[dict]) -> None:
        registry = adopted_registry.load(self.ctx.today_str)
        for s in candidates:
            if s.get('status', '활성') != '활성':
                continue
            entry = registry.setdefault(s['code'], {})
            entry['name'] = s.get('name', entry.get('name', ''))
            entry['market'] = s.get('market', entry.get('market', ''))
            entry['ai'] = {
                'posts_summary': s.get('posts_summary', ''),
                'sentiment': s.get('sentiment', 'Neutral'),
                'keywords': s.get('keywords', []),
            }
        adopted_registry.save(self.ctx.today_str, registry)
```

`_run_rule_based_fallback`도 `self._apply_cached_ai(candidates)`를 `_persist` 앞에 넣는다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_llm_analyzer_sticky.py tests/test_scrape_reliability.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/pipeline/workers/llm_analyzer.py tests/test_llm_analyzer_sticky.py
git commit -m "feat(scraper): 활성 종목만 AI 분석, 추적 종목은 캐시 재사용"
```

---

### Task 5: 매매에는 활성 종목만

**Files:**
- Modify: `src/pipeline/orchestrator.py:56`
- Test: `tests/test_orchestrator_active_only.py`

**Interfaces:**
- Consumes: `StockData.status` (Task 3)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_orchestrator_active_only.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data.schemas import StockData
from src.pipeline.orchestrator import active_only


def test_active_only_filters_tracked():
    """추적 종목은 매수 후보로 넘어가면 안 된다."""
    stocks = [
        StockData(code='111111', name='활성종목', status='활성'),
        StockData(code='222222', name='추적종목', status='추적'),
    ]
    assert [s.code for s in active_only(stocks)] == ['111111']
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_orchestrator_active_only.py -q`
Expected: FAIL — `ImportError: cannot import name 'active_only'`

- [ ] **Step 3: 최소 구현**

`src/pipeline/orchestrator.py` 상단(함수 밖)에 추가한다.

```python
def active_only(stocks: list) -> list:
    """추적 종목은 기록용이다. 시뮬레이터·실전 매매에는 활성 종목만 넘긴다."""
    return [s for s in stocks if getattr(s, 'status', '활성') == '활성']
```

Stage 3 호출을 바꾼다.

```python
    final_picks, simulation_results, sell_candidate = trade_worker.run(active_only(stocks), sync_state)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_orchestrator_active_only.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/pipeline/orchestrator.py tests/test_orchestrator_active_only.py
git commit -m "feat(scraper): 매매 경로에는 활성 종목만 전달"
```

---

### Task 6: 기록에 `상태` 컬럼

**Files:**
- Modify: `src/strategy/analyzer.py` (`analyze_discussion_trend`의 `col_map`, `desired_order`)
- Test: `tests/test_analyzer_status_column.py`

**Interfaces:**
- Produces: 엑셀/CSV에 `상태` 컬럼

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_analyzer_status_column.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from src.strategy.analyzer import analyze_discussion_trend


@pytest.fixture(autouse=True)
def chdir_tmp(tmp_path, monkeypatch):
    # compare_with_history()가 cwd의 data/ 를 읽는다. 실제 데이터와 격리한다.
    monkeypatch.chdir(tmp_path)


def test_status_column_present():
    """상태 컬럼이 없으면 백테스트가 추적 종목을 매수 후보로 오인한다."""
    rows = [
        {'code': '111111', 'name': '활성종목', 'price': 1000, 'change_rate': '+1.00%',
         'recent_posts_count': 90, 'status': '활성'},
        {'code': '222222', 'name': '추적종목', 'price': 2000, 'change_rate': '+2.00%',
         'recent_posts_count': 70, 'status': '추적'},
    ]
    df, _ = analyze_discussion_trend(rows)
    assert '상태' in df.columns
    assert sorted(df['상태'].tolist()) == ['추적', '활성']
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_analyzer_status_column.py -q`
Expected: FAIL — `assert '상태' in df.columns`

- [ ] **Step 3: 최소 구현**

`col_map`에 추가한다.

```python
        'consecutive_days': '연속',
        'status': '상태',
```

`desired_order`에 추가한다 (`code` 앞).

```python
    desired_order = [
        'name', 'price', 'change_rate', 'foreign_change', 'recent_posts_count', 'foreign_rate', 'market',
        'prev_close', 'prev_foreign_rate', 'posts_summary',
        'sentiment_score', 'keywords', 'consecutive_days', 'status', 'code'
    ]
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_analyzer_status_column.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/strategy/analyzer.py tests/test_analyzer_status_column.py
git commit -m "feat(scraper): 기록에 상태 컬럼 추가 (활성/추적)"
```

---

### Task 7: 5일/3일 분석기는 활성만 읽는다

**Files:**
- Modify: `src/analyzer_5days.py` (`load_daily_snapshots`)
- Test: `tests/test_analyzer_5days_filter.py`

**Interfaces:**
- Consumes: Task 6의 `상태` 컬럼

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_analyzer_5days_filter.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
from src.analyzer_5days import filter_active


def test_filters_tracked_rows():
    df = pd.DataFrame([{'code': '1', '상태': '활성'}, {'code': '2', '상태': '추적'}])
    assert filter_active(df)['code'].tolist() == ['1']


def test_missing_column_treats_all_as_active():
    """2026-07-10 이전 데이터에는 상태 컬럼이 없다. 전부 활성이었다."""
    df = pd.DataFrame([{'code': '1'}, {'code': '2'}])
    assert filter_active(df)['code'].tolist() == ['1', '2']
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_analyzer_5days_filter.py -q`
Expected: FAIL — `ImportError: cannot import name 'filter_active'`

- [ ] **Step 3: 최소 구현**

`src/analyzer_5days.py`에 추가한다.

```python
def filter_active(df):
    """추적 종목(임계값 미달)은 누적 분석에서 제외한다.
    상태 컬럼이 없는 과거 스냅샷은 전부 활성으로 간주한다."""
    if '상태' not in df.columns:
        return df
    return df[df['상태'] == '활성']
```

`load_daily_snapshots`에서 `normalize_columns` 호출 앞에 끼운다.

```python
            df = filter_active(df)
            df = normalize_columns(df)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_analyzer_5days_filter.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/analyzer_5days.py tests/test_analyzer_5days_filter.py
git commit -m "feat(scraper): 5일/3일 분석기는 활성 종목만 집계"
```

---

### Task 8: 대시보드에서 추적 종목 구분

**Files:**
- Modify: `src/app/research/types.ts`
- Modify: `src/app/research/hooks/useResearchSource.ts`
- Modify: `src/app/research/components/ResearchTables.tsx`

**Interfaces:**
- Consumes: `latest_stocks.json` 각 항목의 `status` 필드 (Task 3·4)

- [ ] **Step 1: 타입에 필드 추가**

`src/app/research/types.ts`의 `Stock` 인터페이스에 추가한다.

```typescript
    status?: string;   // '활성' | '추적' (없으면 활성)
```

- [ ] **Step 2: 매핑 추가**

`src/app/research/hooks/useResearchSource.ts`의 `mappedData` 매핑 객체에 추가한다.

```typescript
                status: item.status || item['상태'] || '활성',
```

- [ ] **Step 3: 표에서 구분 표시**

`src/app/research/components/ResearchTables.tsx`에서 종목명 셀에 뱃지를 붙인다. 종목명을 렌더링하는 곳을 찾아 감싼다.

```tsx
{stock.status === '추적' && (
  <Badge size="xs" color="gray" variant="light" ml={4}>추적</Badge>
)}
```

- [ ] **Step 4: 타입 체크**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: exit 0

- [ ] **Step 5: 실제 화면 확인**

Run: `npm run dev` 후 `http://localhost:3000/trade` 에서 추적 종목에 회색 `추적` 뱃지가 붙는지 본다. 확인 후 dev 서버를 종료한다.

- [ ] **Step 6: 커밋**

```bash
git add src/app/research/types.ts src/app/research/hooks/useResearchSource.ts src/app/research/components/ResearchTables.tsx
git commit -m "feat(dashboard): 추적 종목 뱃지 표시"
```

---

### Task 9: 전체 검증

- [ ] **Step 1: 전체 테스트**

Run: `python -m pytest tests/ -q`
Expected: `test_kis_news.py::test_get_news_titles_uses_cache` 1건만 실패 (기존 결함), 나머지 전부 통과

- [ ] **Step 2: 타입 체크**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: exit 0

- [ ] **Step 3: 실제 데이터로 한 사이클 확인**

`data/daily_adopted.json`이 없는 상태에서 스크래퍼를 한 번 돌리고(또는 병합 후 첫 Tasker 런 로그를 확인하고), 다음을 본다.

- 로그에 `유니버스 N개 (당일 채택 M개 포함)` 이 찍히는가
- `data/daily_adopted.json`이 생성되고 `date`가 오늘인가
- 두 번째 런에서 첫 런의 채택 종목이 임계값 미달이어도 `추적`으로 남는가
- 월간 엑셀에 `상태` 컬럼이 생겼는가

- [ ] **Step 4: PR 생성**

```bash
git push -u origin feat/sticky-daily-universe
```

---

## 후속 (이 계획 범위 밖)

- `sync_state.stocks` 병합 버그: `data_fetcher.py`가 종목별 상태 대신 평면 dict를 `.update()`로 덮어쓴다. 실물 확인: `"stocks": {"cumulative_count": 24, "last_nid": "425187924"}`
- `max_pages = 40` 상한: 게시글 800건 초과 종목의 정확한 수를 알 수 없다
- `recent_posts_count` 이름과 동작의 괴리(누적 하한 vs 증가 속도)
