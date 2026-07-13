# Sim10 메타-얼로케이터 + Sim0 국면 재구성 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sim0 국면 판단을 top100 실측 기반으로 재구성하고, Sim10을 검증된 하위 전략(BULL→Sim4-1, SIDEWAYS→Sim5, BEAR→현금) 로직을 자기 자본으로 실행하는 메타-얼로케이터로 재정의한다.

**Architecture:** 각 전략의 "결정"(decide, 순수 함수)을 "실행"(execute, base의 buy/sell)에서 분리한다. Sim4-1·Sim5와 Sim10이 동일 decide 함수를 호출한다. Sim0는 trade_engine이 주입하는 top100 metrics의 순수 함수가 된다.

**Tech Stack:** Python 3.12, pytest. 기존 시뮬레이터 프레임워크(`BaseSimulator`).

## Global Constraints

- 모든 시뮬레이터 초기자본 300만원(`initial_cash=3_000_000`).
- 상태/CSV 파일명 규칙: `sim_{name.lower()}_state.json`, `trade_history_sim_{name.lower()}.csv`.
- 기존 심(Sim4-1·Sim5) 동작 불변: decide 추출 전후 매매 결정이 동일해야 함(파리티 테스트로 보장).
- 테스트 격리: 시뮬레이터 테스트는 `sim.state_file`/`csv_file`/`log_file`을 `tmp_path`로 재지정하고 `sim.state`를 통제 dict로 설정한다(기존 `tests/test_sim_stop_tightening.py` 패턴).
- 테스트 실행: `python -m pytest <path> -v`.
- 커밋 메시지 말미: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `src/strategy/simulators/sim0_libero.py` | 국면·bull_score 산출 | calc_bull_score 재가중(foreign 제거), run()이 주입 metrics 소비 |
| `src/pipeline/workers/trade_engine.py` | top100 실측 수집·주입 | momentum 반환 + CSV trend 산출 + `live_market_metrics` 주입 |
| `src/strategy/simulators/base_simulator.py` | 공통 실행 | `_view()`, `_apply()` 헬퍼 + Order 규약 |
| `src/strategy/simulators/sim4_bull_daytrading.py` | 단타 전략 | `decide_bull_daytrade` 추출, run() 래퍼화 |
| `src/strategy/simulators/sim5_sideways_swing.py` | 눌림목 전략 | `decide_sideways` 추출, run() 래퍼화 |
| `src/strategy/simulators/sim10_orchestrator.py` | 메타-얼로케이터 | 순진한 픽커 삭제, 국면별 decide 실행 |

**Order 규약 (Task 3에서 정의, Task 4·5·6이 소비):**
```python
# dict. decide 함수가 반환, _apply가 실행.
{'action': 'BUY',  'code': str, 'name': str, 'price': float, 'quantity': int, 'reason': str, 'cooldown': int|None}
{'action': 'SELL', 'code': str, 'price': float, 'quantity': int|None, 'reason': str,
 'cooldown': int|None, 'mark_partial': bool}
# SELL의 quantity=None → 전량. mark_partial=True → 매도 후 partial_sold 플래그 설정.
```

---

### Task 1: Sim0 국면 재구성 (calc_bull_score 재가중 + run 주입 metrics 소비)

**Files:**
- Modify: `src/strategy/simulators/sim0_libero.py`
- Test: `tests/test_sim0_regime_rebuild.py`

**Interfaces:**
- Consumes: `sim.live_market_metrics = {'breadth': float, 'momentum': float, 'trend': float, 'sample': int}` (Task 2가 주입). 없으면 버즈풀 폴백.
- Produces: `state['current_regime']`, `state['bull_score']` (Sim10이 읽음). `calc_bull_score(breadth, momentum, trend)` (foreign 인자 제거).

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_sim0_regime_rebuild.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest
from src.strategy.simulators.sim0_libero import LiberoSimulator


def _libero(tmp_path):
    sim = LiberoSimulator()
    sim.state_file = str(tmp_path / "libero_state.json")
    sim.log_file = str(tmp_path / "libero_log.json")
    sim.csv_file = str(tmp_path / "libero_trades.csv")
    sim.state = {'initial_cash': 0, 'cash': 0, 'invested': 0, 'portfolio': {},
                 'peak_nav': 0, 'total_fees': 0, 'history': [0], 'daily_trades': [],
                 'market_index_healthy': True, 'cooldown_codes': {}, 'regime_history': []}
    return sim


def test_bull_score_drops_foreign_and_reweights():
    sim = LiberoSimulator.__new__(LiberoSimulator)  # __init__ 없이 메서드만
    # breadth=100, momentum=0(→50), trend=100 → 100*0.4 + 50*0.35 + 100*0.25 = 82.5
    assert sim.calc_bull_score(100, 0, 100) == 82.5


def test_injected_metrics_drive_bull_regime(tmp_path):
    sim = _libero(tmp_path)
    sim.live_market_metrics = {'breadth': 70, 'momentum': 3.0, 'trend': 30, 'sample': 100}
    # 국면 확정은 스무딩(5회 과반)이라 instant_regime로 검증
    candidates = [{'code': '1', 'change_rate': '+1.0%', 'sparkline_price': [100, 101, 102]}]
    sim.run(candidates)
    assert sim.state['instant_regime'] == 'BULL'
    assert sim.state['breadth_source'] == 'top100_live'


def test_injected_weak_metrics_trigger_bear(tmp_path):
    sim = _libero(tmp_path)
    # 진짜 하락장: breadth 낮고 momentum 음수, trend 존재 → 버즈풀이었으면 못 잡던 BEAR
    sim.live_market_metrics = {'breadth': 30, 'momentum': -3.0, 'trend': 20, 'sample': 100}
    candidates = [{'code': '1', 'change_rate': '+2.0%', 'sparkline_price': [100, 90, 80]}]
    sim.run(candidates)
    assert sim.state['instant_regime'] == 'BEAR'


def test_no_injection_falls_back_to_buzz(tmp_path):
    sim = _libero(tmp_path)
    # live_market_metrics 미설정 → 후보 기반 폴백, breadth_source='candidates'
    candidates = [{'code': '1', 'change_rate': '+1.0%', 'sparkline_price': [100, 101, 102]}]
    sim.run(candidates)
    assert sim.state['breadth_source'] == 'candidates'
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_sim0_regime_rebuild.py -v`
Expected: FAIL — `test_bull_score_drops_foreign_and_reweights`는 현재 시그니처가 `calc_bull_score(breadth, momentum, foreign, trend)`라 TypeError; `injected_*`는 `live_market_metrics` 미지원으로 폴백돼 실패.

- [ ] **Step 3: calc_bull_score 재가중**

`sim0_libero.py`의 `calc_bull_score`를 교체:
```python
    def calc_bull_score(self, breadth, momentum, trend):
        """0(극단 약세)~100(극단 강세). breadth/momentum/trend를 가중합. foreign 제거(top100 소스 없음)."""
        momentum_n = self._clamp(50 + momentum * 5)   # 0%→50, +10%→100, -10%→0
        trend_n = self._clamp(trend)                  # ADX 근사 0~100
        return round(breadth * 0.40 + momentum_n * 0.35 + trend_n * 0.25, 1)
```

- [ ] **Step 4: run()이 주입 metrics 소비**

`sim0_libero.py`의 `run()`에서 breadth/momentum/trend 산출부(현재 `live = getattr(self, 'live_breadth_info', None)` 블록부터 `foreign = ...`까지)를 교체:
```python
        metrics = getattr(self, 'live_market_metrics', None)
        if metrics:
            breadth = round(float(metrics['breadth']), 1)
            momentum = round(float(metrics['momentum']), 2)
            trend = round(float(metrics['trend']), 1)
            breadth_sample = int(metrics.get('sample', 0))
            breadth_source = 'top100_live'
        else:
            breadth = round(ups / total * 100, 1) if total else 0.0
            momentum = round(_median(period_changes), 2) if period_changes else 0.0
            trend = round(_median(adxs), 1) if adxs else 0.0
            breadth_sample = total
            breadth_source = 'candidates'
        foreign = round(_mean(foreigns), 3) if foreigns else 0.0   # metrics 표시 전용(bull_score 미사용)
        volatility = round(_pstdev(dailies), 2) if len(dailies) > 1 else 0.0
```
그리고 `bull_score = self.calc_bull_score(breadth, momentum, foreign, trend)` →
```python
        bull_score = self.calc_bull_score(breadth, momentum, trend)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `python -m pytest tests/test_sim0_regime_rebuild.py -v`
Expected: PASS (4개)

- [ ] **Step 6: 회귀 확인 + 커밋**

Run: `python -m pytest tests/ -v -k "libero or orchestrator"`
Expected: 기존 libero 테스트 그린 (기 실패 `test_kis_news`는 무관)

```bash
git add src/strategy/simulators/sim0_libero.py tests/test_sim0_regime_rebuild.py
git commit -m "feat(sim0): 국면 지표를 top100 주입 metrics 기반으로 재구성 (foreign 제거·재가중)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: trade_engine — top100 momentum 반환 + CSV trend + live_market_metrics 주입

**Files:**
- Modify: `src/pipeline/workers/trade_engine.py`
- Test: `tests/test_top100_metrics.py`

**Interfaces:**
- Consumes: `data/kospi_top100_close.csv` (wide 포맷: 1행=1날짜, 컬럼=종목 종가).
- Produces: `_breadth_momentum(rates: list[float]) -> tuple[float, float] | None`, `_top100_trend_from_csv(csv_path, lookback) -> float | None`. 그리고 Task 1이 읽는 `sim.live_market_metrics`.

- [ ] **Step 1: 실패 테스트 작성 (순수 헬퍼)**

```python
# tests/test_top100_metrics.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.pipeline.workers.trade_engine import TradeEngineWorker


def _worker():
    return TradeEngineWorker.__new__(TradeEngineWorker)  # __init__ 우회, 순수 메서드만


def test_breadth_momentum_from_rates():
    w = _worker()
    breadth, momentum = w._breadth_momentum([2.0, -1.0, 3.0, -4.0])
    assert breadth == 50.0            # 2/4 상승
    assert momentum == 0.5            # median([-4,-1,2,3]) = (-1+2)/2


def test_breadth_momentum_empty_returns_none():
    assert _worker()._breadth_momentum([]) is None


def test_trend_from_csv(tmp_path):
    csv = tmp_path / "top100.csv"
    # 3종목 × 4일. A 우상향(추세강), B 톱니(추세약)
    csv.write_text(
        "date,A,B,C\n"
        "20260101,100,100,100\n"
        "20260102,110,90,100\n"
        "20260103,120,100,100\n"
        "20260104,130,90,100\n", encoding='utf-8')
    w = _worker()
    trend = w._top100_trend_from_csv(str(csv), lookback=4)
    # A: |130-100|/(10+10+10)=100, B: |90-100|/(10+10+10)=33.3, C: 0 → median=33.3
    assert 33.0 <= trend <= 34.0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_top100_metrics.py -v`
Expected: FAIL — `_breadth_momentum`/`_top100_trend_from_csv` 미정의(AttributeError)

- [ ] **Step 3: 순수 헬퍼 구현**

`trade_engine.py` 상단(클래스 밖)에 median 헬퍼 추가:
```python
def _median(xs):
    if not xs:
        return 0.0
    s = sorted(xs); n = len(s); m = n // 2
    return float(s[m]) if n % 2 else (s[m - 1] + s[m]) / 2.0
```
`TradeEngineWorker`에 메서드 추가:
```python
    @staticmethod
    def _breadth_momentum(rates):
        """top100 등락률 리스트 → (breadth%, momentum median). 빈 리스트면 None."""
        if not rates:
            return None
        ups = sum(1 for r in rates if r > 0)
        return round(ups / len(rates) * 100, 1), round(_median(rates), 2)

    def _top100_trend_from_csv(self, csv_path='data/kospi_top100_close.csv', lookback=10):
        """종가 시계열 CSV(wide)에서 종목별 ADX 근사의 median. 실패 시 None."""
        import csv as _csv
        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                rows = list(_csv.reader(f))
        except Exception:
            return None
        if len(rows) < 3:
            return None
        header = rows[0]
        data = rows[1:][-lookback:]
        adxs = []
        for col in range(1, len(header)):
            series = []
            for r in data:
                if col < len(r):
                    try:
                        series.append(float(r[col]))
                    except ValueError:
                        pass
            if len(series) >= 2:
                adxs.append(self.calculate_adx(series))
        return round(_median(adxs), 1) if adxs else None
```
참고: `calculate_adx`는 `BaseSimulator`에만 있으므로 `TradeEngineWorker`에서 쓰려면 모듈 함수로 분리하거나 임시 인스턴스 사용이 필요하다. 간단히 `trade_engine.py`에 지역 함수로 복제:
```python
def _adx(series):
    if len(series) < 2:
        return 0.0
    direction = abs(series[-1] - series[0])
    volatility = sum(abs(series[i] - series[i-1]) for i in range(1, len(series)))
    return (direction / volatility * 100.0) if volatility else 0.0
```
그리고 `_top100_trend_from_csv`의 `self.calculate_adx(series)` → `_adx(series)`.

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_top100_metrics.py -v`
Expected: PASS (3개)

- [ ] **Step 5: 주입 배선 (통합)**

`trade_engine.py`의 `_fetch_top100_breadth` 반환을 확장한다. 현재 `return round(ups / len(codes) * 100, 1), len(codes), codes` 인데, 각 종목 등락률을 모아 momentum도 만든다:
- 루프에서 `rate` 파싱 직후 `rates.append(rate)` (리스트 `rates=[]`를 상단에 추가).
- 반환을 `return breadth, momentum, len(codes), codes`로 변경(`breadth, momentum = self._breadth_momentum(rates)`).

주입부(현재 `sim.live_breadth_info = ...`, 약 214행)를 교체:
```python
                    if is_libero:
                        trend = self._top100_trend_from_csv()
                        if live_breadth and trend is not None:
                            sim.live_market_metrics = {
                                'breadth': live_breadth[0], 'momentum': live_breadth[1],
                                'trend': trend, 'sample': live_breadth[2]}
                        else:
                            sim.live_market_metrics = None
```
`live_breadth` 사용처(예: `finalize_eod`의 `actual_eod = live_breadth[0]`, `update_nowcast(live_breadth[0], ...)`, `codes = live_breadth[2]`)를 새 튜플 인덱스(breadth=[0], momentum=[1], sample=[2], codes=[3])에 맞춰 갱신한다.

- [ ] **Step 6: 회귀 확인 + 커밋**

Run: `python -m pytest tests/ -v -k "libero or top100 or trade"`
Expected: 그린

```bash
git add src/pipeline/workers/trade_engine.py tests/test_top100_metrics.py
git commit -m "feat(trade_engine): top100 momentum·trend 산출 후 Sim0에 live_market_metrics 주입

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: base_simulator — _view() / _apply() + Order 규약

**Files:**
- Modify: `src/strategy/simulators/base_simulator.py`
- Test: `tests/test_base_view_apply.py`

**Interfaces:**
- Produces: `sim._view() -> dict` (읽기 전용 상태 뷰), `sim._apply(orders, current_prices)` (Order 리스트 실행). Order 규약은 이 문서 상단 참조.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_base_view_apply.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.strategy.simulators.sim5_sideways_swing import SidewaysSwingSimulator
from src.strategy.simulators.base_simulator import get_kst_now


def _sim(tmp_path):
    s = SidewaysSwingSimulator(initial_cash=3_000_000)
    s.state_file = str(tmp_path / "s.json"); s.csv_file = str(tmp_path / "s.csv"); s.log_file = str(tmp_path / "s.log")
    s.state = {'initial_cash': 3_000_000, 'cash': 3_000_000, 'invested': 0, 'portfolio': {},
               'peak_nav': 3_000_000, 'total_fees': 0, 'history': [3_000_000], 'daily_trades': [],
               'market_index_healthy': True, 'cooldown_codes': {}}
    return s


def test_view_exposes_readonly_state(tmp_path):
    s = _sim(tmp_path)
    v = s._view()
    assert v['cash'] == 3_000_000 and v['initial_cash'] == 3_000_000
    assert v['portfolio'] == {} and v['market_index_healthy'] is True


def test_apply_buy_then_sell(tmp_path):
    s = _sim(tmp_path)
    s._apply([{'action': 'BUY', 'code': '005930', 'name': '삼성', 'price': 1000, 'quantity': 10,
               'reason': 'test', 'cooldown': None}], {'005930': 1000})
    assert '005930' in s.state['portfolio']
    s._apply([{'action': 'SELL', 'code': '005930', 'price': 1100, 'quantity': None,
               'reason': 'test', 'cooldown': 2, 'mark_partial': False}], {'005930': 1100})
    assert '005930' not in s.state['portfolio']
    assert '005930' in s.state['cooldown_codes']


def test_apply_partial_sell_sets_flag(tmp_path):
    s = _sim(tmp_path)
    s._apply([{'action': 'BUY', 'code': '005930', 'name': '삼성', 'price': 1000, 'quantity': 10,
               'reason': 'test', 'cooldown': None}], {'005930': 1000})
    s._apply([{'action': 'SELL', 'code': '005930', 'price': 1050, 'quantity': 5,
               'reason': 'partial', 'cooldown': None, 'mark_partial': True}], {'005930': 1050})
    assert s.state['portfolio']['005930']['partial_sold'] is True
    assert 'partial_sold_date' in s.state['portfolio']['005930']
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_base_view_apply.py -v`
Expected: FAIL — `_view`/`_apply` 미정의

- [ ] **Step 3: 헬퍼 구현**

`base_simulator.py`의 `BaseSimulator`에 추가:
```python
    def _view(self):
        """decide 함수에 넘길 읽기 전용 상태 뷰."""
        return {
            'portfolio': self.state['portfolio'],
            'cash': self.state['cash'],
            'initial_cash': self.initial_cash,
            'cooldown_codes': self.state.get('cooldown_codes', {}),
            'market_index_healthy': self.state.get('market_index_healthy', True),
        }

    def _apply(self, orders, current_prices=None):
        """decide가 반환한 Order 리스트를 실제 매매로 실행."""
        from datetime import date
        for o in orders:
            if o['action'] == 'BUY':
                self.buy(o['code'], o['name'], o['price'], o['quantity'], reason=o.get('reason', ''))
            elif o['action'] == 'SELL':
                self.sell(o['code'], o['price'], quantity=o.get('quantity'), reason=o.get('reason', ''))
                if o.get('mark_partial') and o['code'] in self.state['portfolio']:
                    self.state['portfolio'][o['code']]['partial_sold'] = True
                    self.state['portfolio'][o['code']]['partial_sold_date'] = date.today().isoformat()
            if o.get('cooldown'):
                self.add_cooldown(o['code'], o['cooldown'])
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_base_view_apply.py -v`
Expected: PASS (3개)

- [ ] **Step 5: 커밋**

```bash
git add src/strategy/simulators/base_simulator.py tests/test_base_view_apply.py
git commit -m "feat(base): decide/execute 분리용 _view()·_apply() 헬퍼 + Order 규약

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Sim4-1 decide 추출 + run() 래퍼화 (파리티)

**Files:**
- Modify: `src/strategy/simulators/sim4_bull_daytrading.py`
- Test: `tests/test_sim4_1_parity.py`

**Interfaces:**
- Consumes: `sim._view()`, `sim._apply()` (Task 3). Order 규약.
- Produces: 모듈 함수 `decide_bull_daytrade(view, candidates, current_prices) -> list[Order]` (Sim10이 import).

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_sim4_1_parity.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from datetime import date
from src.strategy.simulators.sim4_bull_daytrading import decide_bull_daytrade


def _view(portfolio, cash=3_000_000, healthy=True):
    return {'portfolio': portfolio, 'cash': cash, 'initial_cash': 3_000_000,
            'cooldown_codes': {}, 'market_index_healthy': healthy}


def _pos(avg, qty=10, partial=False, entry=None):
    return {'name': 'T', 'quantity': qty, 'avg_price': avg, 'peak_price': avg,
            'entry_date': entry or date.today().isoformat(), 'partial_sold': partial}


def test_stop_loss_minus_3pct():
    orders = decide_bull_daytrade(_view({'005930': _pos(1000)}), [], {'005930': 960})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and sells[0]['quantity'] is None and '손절' in sells[0]['reason']


def test_partial_take_profit_at_plus_5pct():
    orders = decide_bull_daytrade(_view({'005930': _pos(1000)}), [], {'005930': 1050})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and sells[0]['quantity'] == 5 and sells[0]['mark_partial'] is True


def test_breakeven_stop_after_partial():
    orders = decide_bull_daytrade(_view({'005930': _pos(1000, partial=True)}), [], {'005930': 1000})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '매입가 복귀' in sells[0]['reason']


def test_entry_when_conditions_met():
    cand = [{'code': '111', 'name': '진입주', 'price': 1000, 'amount': 5_000_000_000,
             'sparkline_price': [90, 95, 100, 105, 110], 'change_rate': '+3.0%',
             'orgn_fake_ntby_qty': 100, 'frgn_fake_ntby_qty': 0, 'tick_power': 130.0}]
    orders = decide_bull_daytrade(_view({}), cand, {'111': 1000})
    buys = [o for o in orders if o['action'] == 'BUY']
    assert len(buys) == 1 and buys[0]['code'] == '111'
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_sim4_1_parity.py -v`
Expected: FAIL — `decide_bull_daytrade` 미정의(ImportError)

- [ ] **Step 3: decide 추출**

`sim4_bull_daytrading.py`에 모듈 함수 추가(현재 `run()`의 청산+진입 로직을 그대로 옮김, `self.sell/buy` → Order append):
```python
from datetime import date, datetime


def _holding_days(p_item, today):
    s = p_item.get('entry_date', '')
    try:
        return (today - datetime.strptime(s, '%Y-%m-%d').date()).days if s else 0
    except Exception:
        return 0


def _partial_days(p_item, today):
    s = p_item.get('partial_sold_date', '')
    try:
        return (today - datetime.strptime(s, '%Y-%m-%d').date()).days if s else 0
    except Exception:
        return 0


def _cooldown_active(cooldown_codes, code):
    exp = cooldown_codes.get(code)
    return bool(exp) and date.today().isoformat() < exp


def _validate_tick(stock, threshold=120.0):
    tp = float(stock.get('tick_power', 0.0))
    return True if tp == 0.0 else tp >= threshold


def _adx(sparkline):
    if len(sparkline) < 2:
        return 0.0
    direction = abs(sparkline[-1] - sparkline[0])
    vol = sum(abs(sparkline[i] - sparkline[i-1]) for i in range(1, len(sparkline)))
    return (direction / vol * 100.0) if vol else 0.0


def _period_change(sparkline):
    if not sparkline or len(sparkline) < 2 or sparkline[0] <= 0:
        return 0.0
    return (sparkline[-1] - sparkline[0]) / sparkline[0] * 100.0


def _parse_change_rate(stock):
    cr = stock.get('change_rate', stock.get('daily_change_rate', 0))
    if isinstance(cr, str):
        try:
            return float(cr.replace('%', '').replace('+', '').strip())
        except ValueError:
            return 0.0
    return float(cr or 0)


MAX_HOLDINGS = 4


def decide_bull_daytrade(view, candidates, current_prices):
    """[Sim4-1] 단타 결정. 순수 함수 — 매매·상태 없음. Order 리스트 반환."""
    orders = []
    portfolio = view['portfolio']
    today = date.today()
    # 1. 청산
    sold = set()
    for code in list(portfolio.keys()):
        p = portfolio[code]
        cur = current_prices.get(code, 0)
        if cur <= 0:
            continue
        avg = p.get('avg_price', 0)
        if avg <= 0:
            continue
        pr = (cur - avg) / avg * 100
        if not p.get('partial_sold', False):
            if _holding_days(p, today) >= 2:
                orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                               'reason': "[단타] 2일 경과 모멘텀 소멸 강제청산", 'cooldown': 1, 'mark_partial': False})
                sold.add(code); continue
            if pr <= -3.0:
                orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                               'reason': f"[단타] 손절 ({pr:.1f}%)", 'cooldown': 2, 'mark_partial': False})
                sold.add(code); continue
            if pr >= 5.0:
                half = p['quantity'] // 2
                if half > 0:
                    orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': half,
                                   'reason': f"[단타] 1차 분할 익절 +5% ({pr:.1f}%)", 'cooldown': None, 'mark_partial': True})
        else:
            if _partial_days(p, today) >= 5:
                orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                               'reason': "[단타] 5일 경과 2차 강제청산", 'cooldown': 1, 'mark_partial': False})
                sold.add(code); continue
            if pr <= 0.0:
                orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                               'reason': f"[단타] 매입가 복귀 손절 ({pr:.1f}%)", 'cooldown': 2, 'mark_partial': False})
                sold.add(code); continue
            if pr >= 10.0:
                orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                               'reason': f"[단타] 2차 전량 익절 +10% ({pr:.1f}%)", 'cooldown': 2, 'mark_partial': False})
                sold.add(code); continue
    # 2. 진입
    if not view['market_index_healthy']:
        return orders
    target_amount = view['initial_cash'] / 10
    held = len(portfolio) - len(sold)
    for stock in candidates:
        if held >= MAX_HOLDINGS:
            break
        code = stock['code']
        if code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            continue
        price = float(stock.get('price', 0))
        amount = float(stock.get('amount', 0))
        if price <= 0 or amount < 3_000_000_000:
            continue
        sparkline = stock.get('sparkline_price', [])
        adx = _adx(sparkline) if sparkline else 0.0
        if adx < 20.0:
            continue
        period_change = _period_change(sparkline)
        daily_change = _parse_change_rate(stock)
        has_inst = (stock.get('orgn_fake_ntby_qty', 0) > 0 or stock.get('frgn_fake_ntby_qty', 0) > 0)
        if (5.0 <= period_change <= 40.0 and daily_change > 0 and adx >= 20.0
                and _validate_tick(stock, 120.0) and has_inst):
            qty = int(target_amount / price)
            if qty > 0:
                orders.append({'action': 'BUY', 'code': code, 'name': stock['name'], 'price': price,
                               'quantity': qty, 'cooldown': None,
                               'reason': f"[단타] 탑승 (기간 {period_change:.1f}%, ADX {adx:.1f}, 기관{stock.get('orgn_fake_ntby_qty',0):+,}/외인{stock.get('frgn_fake_ntby_qty',0):+,})"})
                held += 1
    return orders
```

- [ ] **Step 4: run() 래퍼화**

`BullMomentumDayTradingSimulator.run()`을 교체:
```python
    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        orders = decide_bull_daytrade(self._view(), candidates, current_prices)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
```
기존 `_holding_days`/`_partial_days` 메서드는 모듈 함수로 대체됐으므로 제거(래퍼가 안 씀).

- [ ] **Step 5: 테스트 통과 + 회귀 확인**

Run: `python -m pytest tests/test_sim4_1_parity.py -v`
Expected: PASS (4개)

Run: `python -m pytest tests/ -v -k "not kis_news"`
Expected: 그린

- [ ] **Step 6: 커밋**

```bash
git add src/strategy/simulators/sim4_bull_daytrading.py tests/test_sim4_1_parity.py
git commit -m "refactor(sim4-1): decide_bull_daytrade 순수 함수 추출, run() 래퍼화

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Sim5 decide 추출 + run() 래퍼화 (파리티)

**Files:**
- Modify: `src/strategy/simulators/sim5_sideways_swing.py`
- Test: `tests/test_sim5_parity.py`

**Interfaces:**
- Consumes: `sim._view()`, `sim._apply()`. Order 규약. Task 4의 모듈 헬퍼(`_adx`, `_period_change`, `_parse_change_rate`, `_cooldown_active`, `_validate_tick`)는 sim5에도 필요하므로 **Task 5에서 sim5 파일에 동일 헬퍼를 복제**한다(파일 간 결합 최소화; 두 파일이 독립적으로 읽힘).
- Produces: `decide_sideways(view, candidates, current_prices) -> list[Order]` (Sim10이 import).

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_sim5_parity.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from datetime import date
from src.strategy.simulators.sim5_sideways_swing import decide_sideways


def _view(portfolio, cash=3_000_000, healthy=True):
    return {'portfolio': portfolio, 'cash': cash, 'initial_cash': 3_000_000,
            'cooldown_codes': {}, 'market_index_healthy': healthy}


def _pos(avg, qty=10):
    return {'name': 'T', 'quantity': qty, 'avg_price': avg, 'peak_price': avg,
            'entry_date': date.today().isoformat()}


def test_take_profit_plus_4pct():
    orders = decide_sideways(_view({'005930': _pos(1000)}), [], {'005930': 1040})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '익절' in sells[0]['reason']


def test_hard_stop_minus_3pct():
    orders = decide_sideways(_view({'005930': _pos(1000)}), [], {'005930': 970})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '손절' in sells[0]['reason']


def test_pullback_entry():
    # 추세(ADX≥20) + 우상향 + MA5 이하 눌림 1~10% + 당일 -2%초과 + tick
    cand = [{'code': '222', 'name': '눌림주', 'price': 104, 'amount': 2_000_000_000,
             'sparkline_price': [100, 108, 110, 112, 106], 'change_rate': '-1.0%', 'tick_power': 110.0}]
    orders = decide_sideways(_view({}), cand, {'222': 104})
    buys = [o for o in orders if o['action'] == 'BUY']
    assert len(buys) == 1 and buys[0]['code'] == '222'
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_sim5_parity.py -v`
Expected: FAIL — `decide_sideways` 미정의

- [ ] **Step 3: decide 추출**

`sim5_sideways_swing.py`에 Task 4와 동일한 모듈 헬퍼(`_adx`, `_period_change`, `_parse_change_rate`, `_cooldown_active`, `_validate_tick`)를 복제하고, `run()`의 청산+진입 로직을 옮긴 모듈 함수 추가:
```python
from datetime import date, datetime

MAX_HOLDINGS = 4


def decide_sideways(view, candidates, current_prices):
    """[Sim5] 추세 눌림목 결정. 순수 함수. Order 리스트 반환."""
    orders = []
    portfolio = view['portfolio']
    today = date.today()
    sold = set()
    # 1. 청산
    for code in list(portfolio.keys()):
        p = portfolio[code]
        cur = current_prices.get(code, 0)
        if cur <= 0:
            continue
        avg = p.get('avg_price', 0)
        if avg <= 0:
            continue
        pr = (cur - avg) / avg * 100
        stock = next((s for s in candidates if s.get('code') == code), None)
        sparkline = stock.get('sparkline_price', []) if stock else []
        if pr >= 4.0:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[눌림목] 목표 익절 (+{pr:.1f}%)", 'cooldown': 2, 'mark_partial': False})
            sold.add(code); continue
        if sparkline:
            recent_high = max(sparkline[-5:]) if len(sparkline) >= 5 else max(sparkline)
            if cur >= recent_high * 0.99:
                orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                               'reason': "[눌림목] 반등 회복 익절 (고점 근접)", 'cooldown': 2, 'mark_partial': False})
                sold.add(code); continue
        entry_str = p.get('entry_date')
        if entry_str:
            try:
                if (today - datetime.strptime(entry_str, '%Y-%m-%d').date()).days >= 7:
                    orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                                   'reason': "[눌림목] 타임 스탑 (7일 경과)", 'cooldown': 1, 'mark_partial': False})
                    sold.add(code); continue
            except ValueError:
                pass
        if pr <= -3.0:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[눌림목] 하드 손절 ({pr:.1f}%)", 'cooldown': 3, 'mark_partial': False})
            sold.add(code); continue
    # 2. 진입
    if not view['market_index_healthy']:
        return orders
    target_amount = view['initial_cash'] / 10
    held = len(portfolio) - len(sold)
    for stock in candidates:
        if held >= MAX_HOLDINGS:
            break
        code = stock['code']
        if code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            continue
        price = float(stock.get('price', 0))
        amount = float(stock.get('amount', 0))
        if price <= 0 or amount < 1_000_000_000:
            continue
        sparkline = stock.get('sparkline_price', [])
        if len(sparkline) < 3:
            continue
        adx = _adx(sparkline)
        period_change = _period_change(sparkline)
        daily_change = _parse_change_rate(stock)
        hist = sparkline[:-1] if len(sparkline) > 1 else sparkline
        recent_high = max(hist[-4:]) if len(hist) >= 4 else (max(hist) if hist else price)
        pullback_pct = (recent_high - price) / recent_high * 100 if recent_high > 0 else 0
        if (adx >= 20.0 and period_change > 0 and 1.0 <= pullback_pct <= 10.0
                and daily_change > -2.0 and _validate_tick(stock, 100.0)):
            qty = int(target_amount / price)
            if qty > 0:
                orders.append({'action': 'BUY', 'code': code, 'name': stock['name'], 'price': price,
                               'quantity': qty, 'cooldown': None,
                               'reason': f"[눌림목] 추세 눌림 저가매수 (ADX {adx:.1f}, 눌림 {pullback_pct:.1f}%)"})
                held += 1
    return orders
```

- [ ] **Step 4: run() 래퍼화**

`SidewaysSwingSimulator.run()`을 교체:
```python
    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        orders = decide_sideways(self._view(), candidates, current_prices)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
```

- [ ] **Step 5: 테스트 통과 + 회귀 확인**

Run: `python -m pytest tests/test_sim5_parity.py -v`
Expected: PASS (3개)

Run: `python -m pytest tests/ -v -k "not kis_news"`
Expected: 그린

- [ ] **Step 6: 커밋**

```bash
git add src/strategy/simulators/sim5_sideways_swing.py tests/test_sim5_parity.py
git commit -m "refactor(sim5): decide_sideways 순수 함수 추출, run() 래퍼화

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Sim10 얼로케이터 재작성

**Files:**
- Modify: `src/strategy/simulators/sim10_orchestrator.py`
- Test: `tests/test_sim10_allocator.py`

**Interfaces:**
- Consumes: `decide_bull_daytrade`(Task 4), `decide_sideways`(Task 5), `sim._view()`/`_apply()`(Task 3), Sim0 `current_regime`(state 파일).
- Produces: 국면별 매매를 자기 자본으로 실행하는 `Sim10OrchestratorSimulator`.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_sim10_allocator.py
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from datetime import date
from src.strategy.simulators.sim10_orchestrator import Sim10OrchestratorSimulator


def _sim(tmp_path, regime):
    # Sim0 state 파일을 tmp에 두고 data_dir을 tmp로
    (tmp_path / "sim_libero_state.json").write_text(
        json.dumps({'current_regime': regime, 'bull_score': 60.0}), encoding='utf-8')
    s = Sim10OrchestratorSimulator(initial_cash=3_000_000)
    s.data_dir = str(tmp_path)
    s.state_file = str(tmp_path / "orch.json"); s.csv_file = str(tmp_path / "orch.csv"); s.log_file = str(tmp_path / "orch.log")
    s.state = {'initial_cash': 3_000_000, 'cash': 3_000_000, 'invested': 0, 'portfolio': {},
               'peak_nav': 3_000_000, 'total_fees': 0, 'history': [3_000_000], 'daily_trades': [],
               'market_index_healthy': True, 'cooldown_codes': {}, 'regime_log': []}
    return s


def test_bull_regime_enters_via_daytrade_logic(tmp_path):
    s = _sim(tmp_path, 'BULL')
    cand = [{'code': '111', 'name': '진입주', 'price': 1000, 'amount': 5_000_000_000,
             'sparkline_price': [90, 95, 100, 105, 110], 'change_rate': '+3.0%',
             'orgn_fake_ntby_qty': 100, 'frgn_fake_ntby_qty': 0, 'tick_power': 130.0}]
    s.run(cand, {'111': 1000})
    assert '111' in s.state['portfolio']


def test_bear_regime_liquidates_all(tmp_path):
    s = _sim(tmp_path, 'BEAR')
    s.state['portfolio'] = {'005930': {'name': '삼성', 'quantity': 10, 'avg_price': 1000,
                                       'peak_price': 1000, 'entry_date': date.today().isoformat()}}
    s.state['invested'] = 10000
    s.run([], {'005930': 1000})
    assert s.state['portfolio'] == {}


def test_bull_universe_is_fluctuation_rank(tmp_path, monkeypatch):
    s = _sim(tmp_path, 'BULL')
    called = {}
    class _FakeKIS:
        def get_fluctuation_rank(self, market, sort, limit):
            called['hit'] = True
            return [{'code': '999', 'name': 'x'}]
    monkeypatch.setattr('src.trade.kis_data_provider.KISDataProvider', lambda: _FakeKIS())
    uni = s.get_universe()
    assert called.get('hit') and uni[0]['code'] == '999'
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_sim10_allocator.py -v`
Expected: FAIL — 현행 Sim10은 자체 픽커라 BULL에서 `decide_bull_daytrade` 규칙과 다르게 동작; `get_universe` 없음(None 반환).

- [ ] **Step 3: Sim10 재작성**

`sim10_orchestrator.py` 전체를 교체:
```python
import json
import os

from datetime import date

from .base_simulator import BaseSimulator, get_kst_now
from .sim4_bull_daytrading import decide_bull_daytrade
from .sim5_sideways_swing import decide_sideways


class Sim10OrchestratorSimulator(BaseSimulator):
    """[Sim 10] 메타-얼로케이터 — Sim0 국면에 따라 검증된 하위 전략 로직을 자기 자본으로 실행.

    BULL → Sim4-1(단타), SIDEWAYS → Sim5(눌림목), BEAR → 현금(전량 청산).
    자체 종목 선정을 하지 않는다. 300만원 독립 운용.
    """

    def __init__(self, initial_cash=3_000_000):
        super().__init__("orchestrator", initial_cash)

    def _read_regime(self):
        try:
            with open(os.path.join(self.data_dir, "sim_libero_state.json"), "r", encoding="utf-8-sig") as f:
                d = json.load(f)
            regime = d.get("current_regime", "SIDEWAYS")
            return regime if regime in ("BULL", "SIDEWAYS", "BEAR") else "SIDEWAYS", float(d.get("bull_score", 50.0))
        except Exception:
            return "SIDEWAYS", 50.0

    def get_universe(self):
        """국면 연동 유니버스. BULL은 Sim4-1과 동일(KIS 등락률 상위 30), 그 외 공통 버즈."""
        regime, _ = self._read_regime()
        if regime == "BULL":
            try:
                from src.trade.kis_data_provider import KISDataProvider
                return KISDataProvider().get_fluctuation_rank(market='0001', sort='0', limit=30)
            except Exception:
                return None
        return None

    def _log_regime(self, regime, bull_score):
        today_str = get_kst_now().strftime("%Y-%m-%d")
        log = self.state.setdefault("regime_log", [])
        if log and log[-1].get("date") == today_str:
            return
        nav = self.state["cash"] + self.state.get("invested", 0)
        log.append({"date": today_str, "regime": regime, "bull_score": round(bull_score, 1),
                    "nav": nav, "holdings": len(self.state.get("portfolio", {}))})
        if len(log) > 200:
            self.state["regime_log"] = log[-200:]

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        regime, bull_score = self._read_regime()
        self.update_peak_prices(current_prices)
        self.state["active_regime"] = regime
        self.state["active_bull_score"] = round(bull_score, 1)

        if regime == "BULL":
            orders = decide_bull_daytrade(self._view(), candidates, current_prices)
        elif regime == "SIDEWAYS":
            orders = decide_sideways(self._view(), candidates, current_prices)
        else:  # BEAR: 전량 청산 + 신규매수 없음
            orders = [{'action': 'SELL', 'code': code, 'price': current_prices.get(code, 0),
                       'quantity': None, 'reason': "[Sim10-BEAR] 현금 보유 전량 청산",
                       'cooldown': 1, 'mark_partial': False}
                      for code in list(self.state["portfolio"].keys())
                      if current_prices.get(code, 0) > 0]

        self._apply(orders, current_prices)
        self._log_regime(regime, bull_score)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_sim10_allocator.py -v`
Expected: PASS (3개)

- [ ] **Step 5: 전체 회귀 확인**

Run: `python -m pytest tests/ -v -k "not kis_news"`
Expected: 그린 (기 실패 `test_kis_news`만 제외)

- [ ] **Step 6: 커밋**

```bash
git add src/strategy/simulators/sim10_orchestrator.py tests/test_sim10_allocator.py
git commit -m "feat(sim10): 자체 픽커 폐기, 국면별 하위 전략 실행 메타-얼로케이터로 재작성

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 실전 배포 후 확인 (구현 완료 후)

- Sim0 `calibration_log`의 gap 축소, 실제 하락 국면에서 `current_regime=BEAR` 발동.
- Sim10 `active_regime`이 BULL일 때 거래 CSV가 Sim4-1과 동일 사유·타이밍으로 매매하는지.
- Sim4-1·Sim5 실전 동작이 리팩터 전과 동일한지(파리티).

## 범위 밖 (별도 후속 스펙)

- Sim7 리포트팔로워 기술적 게이트(A안)
- Sim1 심리괴리 빈도 축소
