# Sim8 리포트 팔로워 + Libero 캘리브레이션 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 텔레그램 딥다이브 리포트의 "강력 매수" 종목을 자동 매수하는 Sim8을 추가하고, Libero 예측-실제 갭 데이터를 수집하며, 레이더 차트를 개선한다.

**Architecture:** Sim8은 파이프라인 Stage 3(포트폴리오 관리)와 Stage 3.6(신규 매수) 이중 호출 패턴으로 동작한다. Libero는 매 실행 후 `output/kospi_top100_close.csv`로 실제 브레드스를 산출해 `calibration_log`에 90일 누적한다. 프론트엔드는 두 데이터를 합쳐 직접 비교 가능한 차트로 렌더링한다.

**Tech Stack:** Python 3.11, Next.js 14 (App Router), TypeScript, Recharts, Mantine UI

---

## 파일 맵

| 작업 | 파일 | 변경 유형 |
|---|---|---|
| Task 1 | `src/strategy/simulators/sim8_report_follower.py` | 신규 생성 |
| Task 2 | `src/strategy/advisor.py` | 수정 (rank_and_recommendation 역전파) |
| Task 2 | `src/pipeline/workers/llm_analyzer.py` | 수정 (백필 추가) |
| Task 3 | `src/strategy/simulators/sim7_libero.py` | 수정 (record_calibration 추가) |
| Task 4 | `src/pipeline/workers/trade_engine.py` | 수정 (브레드스 산출 + 캘리브레이션 호출) |
| Task 5 | `src/pipeline/orchestrator.py` | 수정 (Stage 3.6 추가) |
| Task 6 | `src/strategy/strategy_manifest.yaml` | 수정 (sim8 등록) |
| Task 7 | `src/app/api/simulation/stats/route.ts` | 수정 (sim8 추가) |
| Task 7 | `src/app/api/trade/history/route.ts` | 수정 (sim8 추가) |
| Task 7 | `src/app/api/simulation/libero-history/route.ts` | 수정 (calibration_log 반환) |
| Task 8 | `src/app/trade/TradeClient.tsx` | 수정 (simConfigs 카드 추가) |
| Task 9 | `src/app/components/StrategyRadarChart.tsx` | 수정 (차트 전면 개선) |
| Test  | `tests/test_sim8.py` | 신규 생성 |

---

### Task 1: Sim8 시뮬레이터 클래스

**Files:**
- Create: `src/strategy/simulators/sim8_report_follower.py`
- Create: `tests/test_sim8.py`

- [ ] **Step 1: 테스트 파일 작성**

```python
# tests/test_sim8.py
import json, os, tempfile, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy.simulators.sim8_report_follower import ReportFollowerSimulator


def _make_sim(tmp_dir):
    sim = ReportFollowerSimulator(initial_cash=3_000_000)
    sim.data_dir = tmp_dir
    sim.state_file = os.path.join(tmp_dir, 'sim_reportfollower_state.json')
    sim.csv_file   = os.path.join(tmp_dir, 'trade_history_sim_reportfollower.csv')
    sim.log_file   = os.path.join(tmp_dir, 'sim_reportfollower_log.json')
    sim.reset_state()
    return sim


def test_calc_weight_gate():
    sim = ReportFollowerSimulator.__new__(ReportFollowerSimulator)
    assert sim._calc_weight(45.0) == 0.10


def test_calc_weight_max():
    sim = ReportFollowerSimulator.__new__(ReportFollowerSimulator)
    assert sim._calc_weight(100.0) == 0.20


def test_calc_weight_midpoint():
    sim = ReportFollowerSimulator.__new__(ReportFollowerSimulator)
    w = sim._calc_weight(72.5)  # midpoint of 45~100
    assert abs(w - 0.15) < 0.001


def test_buy_from_report_strong(tmp_path):
    sim = _make_sim(str(tmp_path))
    picks = [{'code': '005930', 'name': '삼성전자', 'current_price': 75000,
              'rank_and_recommendation': '강력 매수'}]
    sim.buy_from_report(picks, bull_score=80.0)
    assert '005930' in sim.state['portfolio']
    assert sim.state['cash'] < 3_000_000


def test_buy_from_report_not_strong(tmp_path):
    sim = _make_sim(str(tmp_path))
    picks = [{'code': '005930', 'name': '삼성전자', 'current_price': 75000,
              'rank_and_recommendation': '매수'}]
    sim.buy_from_report(picks, bull_score=80.0)
    assert '005930' not in sim.state['portfolio']


def test_buy_skips_when_full(tmp_path):
    sim = _make_sim(str(tmp_path))
    sim.state['portfolio'] = {f'00000{i}': {'name': f'종목{i}', 'quantity': 1,
        'avg_price': 1000, 'peak_price': 1000, 'entry_date': '2026-01-01',
        'is_scaled_out': False} for i in range(5)}  # MAX_HOLDINGS = 5
    initial_cash = sim.state['cash']
    picks = [{'code': '999999', 'name': '신규', 'current_price': 10000,
              'rank_and_recommendation': '강력 매수'}]
    sim.buy_from_report(picks, bull_score=80.0)
    assert '999999' not in sim.state['portfolio']
    assert sim.state['cash'] == initial_cash


def test_trailing_stop_fires(tmp_path):
    sim = _make_sim(str(tmp_path))
    sim.state['portfolio'] = {
        '005930': {'name': '삼성전자', 'quantity': 10, 'avg_price': 70000,
                   'peak_price': 80000, 'entry_date': '2026-01-01', 'is_scaled_out': False}
    }
    # 고점 80000, 현재가 75999 → drop_from_peak = 5.0% → trailing fires
    sim.run([], current_prices={'005930': 75999})
    assert '005930' not in sim.state['portfolio']


def test_hard_stop_fires(tmp_path):
    sim = _make_sim(str(tmp_path))
    sim.state['portfolio'] = {
        '005930': {'name': '삼성전자', 'quantity': 10, 'avg_price': 70000,
                   'peak_price': 70000, 'entry_date': '2026-01-01', 'is_scaled_out': False}
    }
    # 매입가 70000, 현재가 64399 → -8.0% → hard stop fires
    sim.run([], current_prices={'005930': 64399})
    assert '005930' not in sim.state['portfolio']


def test_time_stop_fires(tmp_path):
    sim = _make_sim(str(tmp_path))
    sim.state['portfolio'] = {
        '005930': {'name': '삼성전자', 'quantity': 10, 'avg_price': 70000,
                   'peak_price': 70500, 'entry_date': '2026-01-01', 'is_scaled_out': False}
    }
    # entry_date가 오래됨 → 7일 이상 경과, 현재가가 ±2% 이내 부동
    sim.run([], current_prices={'005930': 70350})
    assert '005930' not in sim.state['portfolio']
```

- [ ] **Step 2: 테스트 실행 (FAIL 확인)**

```
pytest tests/test_sim8.py -v
```

Expected: `ImportError: cannot import name 'ReportFollowerSimulator'`

- [ ] **Step 3: 시뮬레이터 클래스 작성**

```python
# src/strategy/simulators/sim8_report_follower.py
import json
import os
from datetime import date

from .base_simulator import BaseSimulator, get_kst_now


class ReportFollowerSimulator(BaseSimulator):
    """
    [Sim 8] 리포트 팔로워 — 딥다이브 "강력 매수" 종목 자동 매수.
    Stage 3: run()으로 포트폴리오 관리 (청산 조건 체크).
    Stage 3.6: buy_from_report()로 신규 매수 신호 처리.
    """
    MAX_HOLDINGS = 5
    WEIGHT_MIN   = 0.10
    WEIGHT_MAX   = 0.20
    GATE         = 45.0

    def __init__(self, initial_cash=3_000_000):
        super().__init__("ReportFollower", initial_cash)

    def _calc_weight(self, bull_score: float) -> float:
        """bull_score(45~100)를 10~20% 비중으로 선형 변환."""
        w = self.WEIGHT_MIN + (self.WEIGHT_MAX - self.WEIGHT_MIN) * (bull_score - self.GATE) / (100.0 - self.GATE)
        return max(self.WEIGHT_MIN, min(self.WEIGHT_MAX, w))

    def _days_held(self, pos: dict) -> int:
        try:
            entry = date.fromisoformat(pos.get('entry_date', '2000-01-01'))
            return (date.today() - entry).days
        except Exception:
            return 0

    def run(self, candidates, current_prices=None):
        """포트폴리오 청산 조건 체크만 수행. 신규 매수 없음."""
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)

        for code in list(self.state['portfolio'].keys()):
            pos = self.state['portfolio'].get(code)
            if not pos:
                continue
            cur = current_prices.get(code, 0)
            if cur <= 0:
                continue
            avg = pos.get('avg_price', 0)
            if avg <= 0:
                continue

            profit_rate = (cur - avg) / avg * 100

            # 하드 스탑: -8%
            if profit_rate <= -8.0:
                self.sell(code, cur, reason="[리포트팔로워] 하드 스탑 -8%")
                continue

            # 트레일링 스탑: 고점 대비 -5% (수익 +5% 달성 후 활성화)
            if self.check_trailing_stop(code, cur, activation_pct=5.0, callback_pct=5.0):
                self.sell(code, cur, reason="[리포트팔로워] 트레일링 스탑 -5%")
                continue

            # 타임 스탑: 7일 경과 + ±2% 이내 부동
            if self._days_held(pos) >= 7 and abs(profit_rate) <= 2.0:
                self.sell(code, cur, reason="[리포트팔로워] 타임 스탑 7일 부동")
                continue

        self.save_state(current_prices)

    def buy_from_report(self, strong_picks: list[dict], bull_score: float = 50.0):
        """
        딥다이브 "강력 매수" 픽을 매수.
        strong_picks: rank_and_recommendation에 '강력 매수'가 포함된 final_picks 서브셋.
        bull_score: 리베로 bull_score (비중 결정용).
        """
        weight = self._calc_weight(bull_score)
        holdings_count = len(self.state['portfolio'])

        for pick in strong_picks:
            if holdings_count >= self.MAX_HOLDINGS:
                print(f"[Sim8] MAX_HOLDINGS({self.MAX_HOLDINGS}) 초과 — 매수 스킵: {pick.get('name')}")
                break

            code = pick.get('code')
            name = pick.get('name', code)
            price = pick.get('current_price', pick.get('price', 0))

            if not code or price <= 0:
                continue
            if code in self.state['portfolio']:
                print(f"[Sim8] 이미 보유 중 — 스킵: {name}({code})")
                continue

            qty = int(self.state['cash'] * weight / price)
            if qty <= 0:
                print(f"[Sim8] 현금 부족 — 스킵: {name}({code})")
                continue

            ok = self.buy(code, name, price, qty,
                          reason=f"[리포트팔로워] 강력매수 bull_score={bull_score:.1f} weight={weight:.0%}")
            if ok:
                holdings_count += 1
                print(f"[Sim8] 매수 완료: {name}({code}) {qty}주 @{price:,}원 (비중 {weight:.0%})")
```

- [ ] **Step 4: 테스트 실행 (PASS 확인)**

```
pytest tests/test_sim8.py -v
```

Expected: 모든 테스트 PASS

- [ ] **Step 5: 커밋**

```bash
git add src/strategy/simulators/sim8_report_follower.py tests/test_sim8.py
git commit -m "feat(sim): Sim8 ReportFollower 시뮬레이터 신규 구현"
```

---

### Task 2: rank_and_recommendation 역전파

Gemini 딥다이브가 생성한 추천 등급이 `final_picks`에 저장되도록 한다.
Stage 3.6에서 Sim8이 이 값을 읽어 "강력 매수" 여부를 판단한다.

**Files:**
- Modify: `src/strategy/advisor.py` (~line 372)
- Modify: `src/pipeline/workers/llm_analyzer.py` (~line 135)

- [ ] **Step 1: advisor.py — recommendation을 stock dict에 저장**

`src/strategy/advisor.py`의 `generate_deep_dive_report()` 내에서 `recommendation` 변수 할당 직후 한 줄 추가.

변경 전 (line 372 근처):
```python
data = json.loads(response.text)
recommendation = data.get('rank_and_recommendation', '')
```

변경 후:
```python
data = json.loads(response.text)
recommendation = data.get('rank_and_recommendation', '')
stock['rank_and_recommendation'] = recommendation  # Sim8 Stage 3.6용
```

- [ ] **Step 2: llm_analyzer.py — 백필 루프에 rank_and_recommendation 추가**

`src/pipeline/workers/llm_analyzer.py`의 `generate_deep_dive()` 내 백필 루프.

변경 전 (line 135 근처):
```python
for p in final_picks:
    dp = next((c for c in detail_picks if c['code'] == p['code']), None)
    if dp and 'deep_dive_text' in dp:
        p['deep_dive_text'] = dp['deep_dive_text']
```

변경 후:
```python
for p in final_picks:
    dp = next((c for c in detail_picks if c['code'] == p['code']), None)
    if dp:
        if 'deep_dive_text' in dp:
            p['deep_dive_text'] = dp['deep_dive_text']
        if 'rank_and_recommendation' in dp:
            p['rank_and_recommendation'] = dp['rank_and_recommendation']
```

- [ ] **Step 3: 커밋**

```bash
git add src/strategy/advisor.py src/pipeline/workers/llm_analyzer.py
git commit -m "feat(pipeline): 딥다이브 rank_and_recommendation을 final_picks에 역전파"
```

---

### Task 3: Libero 캘리브레이션 메서드 추가

**Files:**
- Modify: `src/strategy/simulators/sim7_libero.py`

- [ ] **Step 1: `record_calibration()` 메서드 추가**

`sim7_libero.py`의 `run()` 메서드 아래에 추가:

```python
def record_calibration(self, actual_kospi_breadth: float) -> None:
    """
    실제 KOSPI 브레드스와 리베로 추정치의 갭을 calibration_log에 기록.
    하루 1회만 기록 (중복 방지). 최대 90일 롤링 보관.
    """
    today_str = get_kst_now().strftime('%Y-%m-%d')
    log = list(self.state.get('calibration_log', []))
    if log and log[-1].get('date') == today_str:
        return  # 당일 이미 기록됨

    libero_breadth = self.state.get('metrics', {}).get('breadth_score', 0.0)
    bull_score     = self.state.get('bull_score', 0.0)
    regime         = self.state.get('current_regime', 'SIDEWAYS')

    log.append({
        'date':                 today_str,
        'libero_breadth':       round(libero_breadth, 1),
        'actual_kospi_breadth': round(actual_kospi_breadth, 1),
        'gap':                  round(libero_breadth - actual_kospi_breadth, 1),
        'bull_score':           round(bull_score, 1),
        'regime':               regime,
    })
    self.state['calibration_log'] = log[-90:]
    self.save_state()
    print(f"[Libero] 캘리브레이션 기록: libero={libero_breadth:.1f}% / actual={actual_kospi_breadth:.1f}% / gap={libero_breadth - actual_kospi_breadth:+.1f}%")
```

- [ ] **Step 2: 커밋**

```bash
git add src/strategy/simulators/sim7_libero.py
git commit -m "feat(sim7): calibration_log 수집 메서드 추가"
```

---

### Task 4: TradeEngineWorker — KOSPI 브레드스 산출 + 캘리브레이션 연결

**Files:**
- Modify: `src/pipeline/workers/trade_engine.py`

- [ ] **Step 1: `_get_actual_breadth_from_csv()` 추가**

`TradeEngineWorker` 클래스 내부, `_run_simulators()` 아래에 추가:

```python
def _get_actual_breadth_from_csv(self, csv_path: str = 'output/kospi_top100_close.csv') -> float | None:
    """KOSPI top100 CSV의 최근 2행으로 오늘 실제 브레드스(상승 종목 비율%) 산출."""
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            lines = [l for l in f.read().split('\n') if l.strip()]
        if len(lines) < 3:  # 헤더 + 데이터 최소 2행
            return None
        prev_cols = lines[-2].split(',')
        curr_cols = lines[-1].split(',')
        # 첫 번째 컬럼은 날짜 — 슬라이싱으로 제외
        ups, total = 0, 0
        for p_str, c_str in zip(prev_cols[1:], curr_cols[1:]):
            try:
                p, c = float(p_str.strip()), float(c_str.strip())
                if p > 0:
                    total += 1
                    if c > p:
                        ups += 1
            except ValueError:
                continue
        return round(ups / total * 100, 1) if total > 0 else None
    except Exception as e:
        self.log_error(f"KOSPI 브레드스 CSV 산출 실패: {e}")
        return None
```

- [ ] **Step 2: `_run_simulators()` — libero 실행 후 calibration 연결**

`_run_simulators()` 내 `for sim in simulators:` 루프 내부에서 libero 실행 직후 캘리브레이션 호출 추가.

변경 전 (루프 내부):
```python
for sim in simulators:
    try:
        ...
        sim.run(sim_candidates, current_prices=sim_prices)
        self.log(f"  {sim.__class__.__name__} 완료")
    except Exception as e:
        self.log_error(f"시뮬레이터 실패 ({sim.__class__.__name__}): {e}")
```

변경 후:
```python
for sim in simulators:
    try:
        own_universe = sim.get_universe()
        if own_universe:
            sim_candidates = self._enrich_universe(own_universe)
            sim_prices = dict(current_prices)
            sim_prices.update({
                s['code']: s.get('price', s.get('current_price', 0))
                for s in sim_candidates if s.get('price', 0) > 0
            })
        else:
            sim_candidates = candidates
            sim_prices = current_prices
        sim.run(sim_candidates, current_prices=sim_prices)
        self.log(f"  {sim.__class__.__name__} 완료")

        # Libero 캘리브레이션: libero 실행 직후 실제 KOSPI 브레드스와 비교 기록
        if getattr(sim, 'IS_ANALYZER', False) and sim.__class__.__name__ == 'LiberoSimulator':
            actual_breadth = self._get_actual_breadth_from_csv()
            if actual_breadth is not None:
                sim.record_calibration(actual_breadth)
    except Exception as e:
        self.log_error(f"시뮬레이터 실패 ({sim.__class__.__name__}): {e}")
```

- [ ] **Step 3: 커밋**

```bash
git add src/pipeline/workers/trade_engine.py
git commit -m "feat(pipeline): KOSPI 브레드스 CSV 산출 + Libero calibration 연결"
```

---

### Task 5: Orchestrator Stage 3.6 추가

**Files:**
- Modify: `src/pipeline/orchestrator.py`

- [ ] **Step 1: Stage 3.6 블록 삽입**

`orchestrator.py`의 `# ── Stage 4` 바로 위에 삽입:

변경 전:
```python
    if not final_picks:
        # [Bug 1 Fix] 신규 picks 없어도 reports.json 항상 재생성
        storage.rebuild_reports_index(ctx.now_kst)

    # ── Stage 4: 텔레그램 발송 + 최종 저장 ───────────────────────
```

변경 후:
```python
    if not final_picks:
        # [Bug 1 Fix] 신규 picks 없어도 reports.json 항상 재생성
        storage.rebuild_reports_index(ctx.now_kst)

    # ── Stage 3.6: Sim8 신규 매수 ────────────────────────────────
    # final_picks에 rank_and_recommendation이 역전파된 이후 실행 (Task 2 필수)
    try:
        from src.strategy.simulators.sim8_report_follower import ReportFollowerSimulator
        from src.strategy.simulators.sim7_libero import LiberoSimulator
        import json as _json, os as _os

        strong_picks = [
            p for p in final_picks
            if '강력 매수' in (p.get('rank_and_recommendation') or '')
        ]

        # libero state에서 bull_score 읽기
        libero_state_file = _os.path.join('data', 'sim_libero_state.json')
        bull_score = 50.0
        try:
            with open(libero_state_file, 'r', encoding='utf-8') as _f:
                bull_score = float(_json.load(_f).get('bull_score', 50.0))
        except Exception:
            pass

        if strong_picks and bull_score >= 45.0:
            ctx.log(f"▶ Stage 3.6: Sim8 강력 매수 처리 ({len(strong_picks)}개 / bull_score={bull_score:.1f})")
            sim8 = ReportFollowerSimulator()
            sim8.buy_from_report(strong_picks, bull_score=bull_score)
        else:
            ctx.log(f"▶ Stage 3.6: Sim8 스킵 (강력매수={len(strong_picks)}개 / bull_score={bull_score:.1f})")
    except Exception as _e:
        ctx.log(f"[Warn] Stage 3.6 Sim8 실패: {_e}")

    # ── Stage 4: 텔레그램 발송 + 최종 저장 ───────────────────────
```

- [ ] **Step 2: 커밋**

```bash
git add src/pipeline/orchestrator.py
git commit -m "feat(pipeline): Stage 3.6 Sim8 신규 매수 단계 추가"
```

---

### Task 6: strategy_manifest.yaml 등록 + Sim8 포트폴리오 관리 등록

**Files:**
- Modify: `src/strategy/strategy_manifest.yaml`

- [ ] **Step 1: simulators 목록 끝에 sim8 추가**

`strategy_manifest.yaml`의 `sim7_libero` 블록 아래에 추가:

```yaml
  - id: "sim8_report_follower"
    module: "src.strategy.simulators.sim8_report_follower"
    class: "ReportFollowerSimulator"
    description: "리포트 팔로워 — 딥다이브 강력 매수 종목 자동 매수 + 트레일링 라이딩"
    active: true
```

- [ ] **Step 2: 커밋**

```bash
git add src/strategy/strategy_manifest.yaml
git commit -m "feat(manifest): Sim8 ReportFollower 등록"
```

---

### Task 7: API Routes 업데이트

**Files:**
- Modify: `src/app/api/simulation/stats/route.ts`
- Modify: `src/app/api/trade/history/route.ts`
- Modify: `src/app/api/simulation/libero-history/route.ts`

- [ ] **Step 1: stats/route.ts — sim8 추가**

`types` 배열 끝에 추가 (sim6 항목 아래):

```typescript
{ id: 'sim8', file: 'sim_reportfollower_state.json' },
```

- [ ] **Step 2: history/route.ts — sim8 추가**

`simFiles` 배열 끝에 추가 (sim_bear 아래):

```typescript
{ type: 'sim8_report_follower', name: 'trade_history_sim_reportfollower.csv' },
```

- [ ] **Step 3: libero-history/route.ts — calibration_log 응답 추가**

`GET()` 함수 내 liberoLog 파싱 블록에서 `calibration_log` 추출 추가:

변경 전:
```typescript
const res = await fetch(`${GITHUB_BASE}/sim_libero_state.json?t=${Date.now()}`, { cache: 'no-store' });
if (res.ok) {
    const s = await res.json();
    liberoLog = s.daily_regime_log ?? [];
```

변경 후:
```typescript
const res = await fetch(`${GITHUB_BASE}/sim_libero_state.json?t=${Date.now()}`, { cache: 'no-store' });
let calibrationLog: any[] = [];
if (res.ok) {
    const s = await res.json();
    liberoLog = s.daily_regime_log ?? [];
    calibrationLog = s.calibration_log ?? [];
```

그리고 `return NextResponse.json(...)` 변경:

변경 전:
```typescript
return NextResponse.json({ libero_log: liberoLog, market_data: marketData });
```

변경 후:
```typescript
return NextResponse.json({ libero_log: liberoLog, market_data: marketData, calibration_log: calibrationLog });
```

- [ ] **Step 4: 커밋**

```bash
git add src/app/api/simulation/stats/route.ts \
        src/app/api/trade/history/route.ts \
        src/app/api/simulation/libero-history/route.ts
git commit -m "feat(api): sim8 통계·히스토리 API 추가 + libero calibration_log 노출"
```

---

### Task 8: TradeClient.tsx — Sim8 카드 추가

**Files:**
- Modify: `src/app/trade/TradeClient.tsx`

- [ ] **Step 1: simConfigs 배열에 sim8 추가**

`simConfigs` 배열의 sim6 항목 아래에 추가:

```typescript
{ id: 'sim8', key: 'sim8', label: '리포트 팔로워 (Sim 8)', color: 'pink', type: 'sim8_report_follower' },
```

그리고 `renderSimulationTripod()` 내 섹션 제목을 변경:

```typescript
// 변경 전
<Title order={3}><IconRobot size={24} style={{ marginBottom: -4, marginRight: 8 }}/>6-Track 지능형 시뮬레이션</Title>
// 변경 후
<Title order={3}><IconRobot size={24} style={{ marginBottom: -4, marginRight: 8 }}/>8-Track 지능형 시뮬레이션</Title>
```

- [ ] **Step 2: 커밋**

```bash
git add src/app/trade/TradeClient.tsx
git commit -m "feat(ui): 대시보드 Sim8 리포트팔로워 카드 추가"
```

---

### Task 9: StrategyRadarChart.tsx — 차트 전면 개선

**Files:**
- Modify: `src/app/components/StrategyRadarChart.tsx`

- [ ] **Step 1: SERIES 배열에 sim8 추가 + 그룹 재구성**

`SERIES` 배열 끝에 추가:
```typescript
{ key: 'sim8', label: '리포트 팔로워 (Sim 8)', color: '#e64980', desc: '딥다이브 강력 매수 종목 자동 매수 · 트레일링 라이딩' },
```

`SERIES_G1`, `SERIES_G2` 재정의:
```typescript
// 변경 전
const SERIES_G1 = SERIES.filter(s => ['sim1', 'sim2', 'sim3'].includes(s.key));
const SERIES_G2 = SERIES.filter(s => ['sim4', 'sim4_daytrading', 'sim5', 'sim6'].includes(s.key));

// 변경 후
const SERIES_G1 = SERIES.filter(s => ['sim1', 'sim2', 'sim3', 'sim4', 'sim4_daytrading'].includes(s.key));
const SERIES_G2 = SERIES.filter(s => ['sim5', 'sim6', 'sim8'].includes(s.key));
```

레이더 그룹 제목 변경 (JSX):
```typescript
// 변경 전
title="Sim 1~3 (심리·수급·리스크)"
title="Sim 4~6 (모멘텀·단타·눌림·줍줍)"

// 변경 후
title="Sim 1~4-1 (심리·수급·리스크·모멘텀)"
title="Sim 5~8 (눌림·줍줍·리포트팔로워)"
```

- [ ] **Step 2: state 추가 및 fetchSim7 개선**

기존 `const [sim7Data, setSim7Data] = useState<any[]>([]);` 아래에:
```typescript
const [sim7HitRate, setSim7HitRate] = useState<{ hits: number; total: number; pct: number } | null>(null);
```

`fetchSim7` 함수 전체 교체:
```typescript
const fetchSim7 = async () => {
  setSim7Loading(true);
  try {
    const res = await fetch(`/api/simulation/libero-history?cb=${Date.now()}`);
    const d = await res.json();

    // 실제 시장 breadth 맵
    const marketMap: Record<string, number> = {};
    for (const m of (d.market_data ?? [])) marketMap[m.date] = m.breadth;

    // 리베로 자체 breadth 맵 (bull_score 대신 breadth 사용 — 같은 단위)
    const liberoMap: Record<string, number> = {};
    for (const l of (d.libero_log ?? [])) {
      if (l.breadth != null) liberoMap[l.date] = l.breadth;
    }

    const allDates = Array.from(new Set([
      ...Object.keys(marketMap),
      ...Object.keys(liberoMap),
    ])).sort().slice(-14);

    const merged = allDates.map(date => ({
      date: date.slice(5),
      sim7Score: liberoMap[date] ?? null,
      marketBreadth: marketMap[date] ?? null,
      gap: (liberoMap[date] != null && marketMap[date] != null)
        ? parseFloat((liberoMap[date] - marketMap[date]).toFixed(1))
        : null,
    }));
    setSim7Data(merged);

    // 방향 적중률 계산
    const comparable = merged.filter(d => d.sim7Score !== null && d.marketBreadth !== null);
    const zone = (v: number) => v >= 60 ? 'BULL' : v <= 40 ? 'BEAR' : 'SIDEWAYS';
    const hits = comparable.filter(d => zone(d.sim7Score!) === zone(d.marketBreadth!));
    if (comparable.length > 0) {
      setSim7HitRate({ hits: hits.length, total: comparable.length, pct: Math.round(hits.length / comparable.length * 100) });
    }
  } catch {
    setSim7Data([]);
  } finally {
    setSim7Loading(false);
  }
};
```

- [ ] **Step 3: 차트 JSX 업데이트**

차트 섹션 레이블 변경:
```typescript
// 변경 전
<Text size="sm" fw={700}>리베로 bull_score vs KOSPI 실제 Breadth (최근 14 거래일)</Text>

// 변경 후
<Text size="sm" fw={700}>리베로 추정 Breadth vs KOSPI 실제 Breadth (최근 14 거래일)</Text>
```

범례 설명 변경:
```typescript
// 변경 전
· <b style={{ color: '#7950f2' }}>보라선</b>: Sim7의 시장 판단 점수 (bull_score 0~100) &nbsp;
· <b style={{ color: '#868e96' }}>회색선</b>: KOSPI top100 실제 Breadth (상승 종목 비율 %)

// 변경 후
· <b style={{ color: '#7950f2' }}>보라선</b>: 리베로 추정 Breadth (버즈 유니버스 상승 비율 %) &nbsp;
· <b style={{ color: '#868e96' }}>회색선</b>: KOSPI top100 실제 Breadth (상승 종목 비율 %) &nbsp;
· <b style={{ color: '#ced4da' }}>점선</b>: 갭 (리베로 − 실제, 0 기준선)
```

방향 적중률 뱃지 추가 (차트 상단 `<Group>` 블록 내):
```typescript
{sim7HitRate && (
  <Badge color={sim7HitRate.pct >= 60 ? 'green' : sim7HitRate.pct >= 40 ? 'yellow' : 'red'} variant="light" size="sm">
    방향 적중 {sim7HitRate.hits}/{sim7HitRate.total}일 ({sim7HitRate.pct}%)
  </Badge>
)}
```

`Line` 컴포넌트 변경 (sim7Score → breadth):
```typescript
// 변경 전 (보라선 name)
name="Sim7 bull_score"

// 변경 후
name="리베로 추정 Breadth"
```

갭 추이선 추가 (기존 두 `<Line>` 아래에):
```typescript
<Line
  type="monotone"
  dataKey="gap"
  name="갭 (리베로−실제)"
  stroke="#ced4da"
  strokeWidth={1}
  strokeDasharray="3 3"
  dot={false}
  connectNulls
/>
```

0 기준선 추가 (기존 `<ReferenceLine y={60}` 위에):
```typescript
<ReferenceLine y={0} stroke="#ced4da" strokeDasharray="2 2" strokeWidth={1} />
```

- [ ] **Step 4: 커밋**

```bash
git add src/app/components/StrategyRadarChart.tsx
git commit -m "feat(chart): 리베로 breadth 직접비교 + 방향적중률 + 갭선 + Sim8 레이더 그룹 재구성"
```

---

## 자체 검토

### 스펙 커버리지

| 스펙 요구사항 | 구현 태스크 |
|---|---|
| Sim8 클래스 신규 생성 | Task 1 |
| rank_and_recommendation 시그널 | Task 2 |
| bull_score 선형 비중 10~20% | Task 1 (_calc_weight) |
| MAX_HOLDINGS 5 | Task 1 |
| 트레일링 -5% / 하드 -8% / 타임 7일 | Task 1 (run) |
| Stage 3.6 오케스트레이터 추가 | Task 5 |
| manifest 등록 (Stage 3 포트폴리오 관리) | Task 6 |
| libero record_calibration | Task 3 |
| KOSPI CSV 브레드스 산출 | Task 4 |
| calibration_log API 노출 | Task 7 |
| stats/history API 추가 | Task 7 |
| TradeClient 카드 추가 | Task 8 |
| 차트 sim7Score → breadth 교체 | Task 9 |
| 방향 적중률 뱃지 | Task 9 |
| 갭 추이선 | Task 9 |
| 레이더 그룹 Sim1~4-1 / Sim5~8 재구성 | Task 9 |

**누락 없음.**

### 타입 일관성

- `buy_from_report(picks, bull_score)` → Task 1에서 정의, Task 5에서 동일 시그니처 호출 ✓
- `record_calibration(actual_breadth)` → Task 3에서 정의, Task 4에서 동일 시그니처 호출 ✓
- `sim7Score` dataKey → `fetchSim7`에서 설정, `<Line dataKey="sim7Score">` → 변경 없음 (key 이름 유지) ✓
- `gap` dataKey → `fetchSim7`에서 추가, `<Line dataKey="gap">` ✓
