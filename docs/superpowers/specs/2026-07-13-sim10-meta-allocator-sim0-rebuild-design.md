# Sim10 메타-얼로케이터 + Sim0 국면 재구성 설계

**작성일:** 2026-07-13
**대상:** Sim10 오케스트레이터(컨셉 재정의), Sim0 리베로(국면 판단 재구성)
**범위 밖:** Sim7(기술 게이트)·Sim1(빈도 축소)은 별도 후속 스펙

## 배경 — 데이터 진단

6주(2026-06-01~07-13) 실거래 시뮬 데이터에서 Sim10은 최악(-43%, MDD 43%)이었다.
두 가지 구조적 원인이 겹쳤다.

1. **Sim10 자체 결함:** 오케스트레이터가 검증된 하위 심을 두고 자기만의 순진한
   픽커(`abs(등락률)` 최대 종목을 3종목에 33%씩 집중)를 재구현했다. 가장 변동 큰
   종목에 몰빵 + 넓은 스탑 상속.

2. **Sim0 국면 오판:** Sim10은 Sim0의 `current_regime`/`bull_score`를 신뢰하는데,
   Sim0의 국면 판단이 편향돼 있었다. 6월엔 breadth가 버즈풀 기반이라 86%(실제 34%)까지
   튀어 BULL을 오판했고, 그 오판이 Sim10을 BULL 모드(넓은 -8% 스탑·집중·고정익절 없음)로
   밀어넣었다.

2026-07-10(금) top100 breadth 실측 주입으로 breadth는 고쳤으나, **momentum/trend/foreign은
아직 버즈 후보풀(3~30개 화제주)에서 계산**된다. 버즈 종목은 태생적으로 등락·ADX가 높아
`bull_score`(가중합)를 부풀리고, BEAR 조건(`momentum≤-2`)이 영영 안 잡히게 만든다.

## 목표

- **Sim0:** momentum/trend/foreign까지 top100 실측 기반으로 옮겨 국면·bull_score를
  대표성 있게 만든다. (금요일 breadth 수정의 완성)
- **Sim10:** 자체 픽커를 버리고, 국면에 맞는 **검증된 하위 전략 로직을 자기 자본으로 실행**하는
  메타-얼로케이터로 재정의한다. BULL→Sim4-1, SIDEWAYS→Sim5, BEAR→현금.

---

## Part 1 — Sim0 국면 판단 재구성

### 지표 출처 통일

| 지표 | 현재 | 재구성 후 | 소스 |
|---|---|---|---|
| breadth | top100 실측 | 유지 | `_fetch_top100_breadth` (기존) |
| momentum | 버즈풀 median 등락 | **top100 median 등락률** | `_fetch_top100_breadth` 확장 |
| trend | 버즈풀 median ADX | **top100 median ADX** | `data/kospi_top100_close.csv` |
| foreign | 버즈풀 mean | **제거** | — |
| volatility | 버즈풀 stdev | 유지(표시 전용) | 버즈풀 |

### 변경 내용

- **momentum:** `trade_engine._fetch_top100_breadth`가 현재 top100 각 종목 등락률을 긁어
  상승/하락만 카운트한다. 이를 확장해 등락률 리스트도 반환하고, 그 median을 momentum으로 쓴다.
- **trend:** `data/kospi_top100_close.csv`(1행=1날짜, 컬럼=top100 종가, ~100거래일)에서
  각 종목 종가 시계열로 ADX 근사(`base_simulator.calculate_adx`)를 구해 median. 일 단위
  갱신이며 장중엔 최신 값 유지(ADX는 느린 신호라 허용).
- **foreign 제거:** 버즈풀 mean은 신뢰 불가이고 top100 소스가 없다. `bull_score`에서 빼고
  재가중한다: `breadth 0.40 + momentum_n 0.35 + trend_n 0.25` (기존
  `breadth 0.30 + momentum 0.25 + foreign 0.25 + trend 0.20`).
- **classify_regime:** 로직(임계값)은 그대로 두되 세 입력이 모두 top100이 된다. 결과적으로
  BEAR(`breadth≤40 AND momentum≤-2 AND trend≥15`)가 진짜 시장 하락 시 발동한다.

### 격리(테스트 용이성)

Sim0는 파일 I/O를 하지 않는다. `trade_engine`이 `live_market_metrics = {breadth, momentum,
trend, sample}`를 주입한다(현 `live_breadth_info` 확장). 주입값이 없으면 기존 버즈풀
계산으로 폴백. → Sim0는 주입 metrics의 순수 함수라 단위 테스트가 쉽다.

### 데이터 흐름

```
trade_engine._fetch_top100_breadth()  → (breadth, momentum, sample, codes)   # Naver 시총페이지 장중
trade_engine._top100_trend_from_csv() → trend(ADX median)                     # kospi_top100_close.csv
        ↓ 주입
sim.live_market_metrics = {breadth, momentum, trend, sample}
        ↓
Sim0.run(): metrics 있으면 사용, 없으면 버즈풀 폴백 → classify_regime + calc_bull_score
```

---

## Part 2 — 전략 로직 추출 (decide/execute 분리)

### 원리

Sim4-1·Sim5의 "무엇을 사고팔지 결정"(decide)을 "실제 매매·상태 변경"(execute)에서 분리한다.
[[program-trading-parity-mandate]]의 "심 선택 = 실전 정확히 동일 동작" 원칙과 정합 —
Sim10이 Sim4-1을 *흉내내는* 게 아니라 *정확히 같은 결정 로직*을 실행한다.

### 인터페이스

```python
# 순수 함수 (부작용·I/O 없음). 각 sim 모듈에 위치.
def decide_bull_daytrade(view, candidates, current_prices) -> list[Order]
def decide_sideways(view, candidates, current_prices) -> list[Order]

# view: 읽기 전용 상태 뷰
#   { portfolio, cash, initial_cash, cooldown_codes, market_index_healthy }
# Order: (action, code, name, quantity, price, reason)
#   action ∈ {"BUY", "SELL"};  SELL은 quantity=None이면 전량
```

### 기존 심 리팩터

```python
class BullMomentumDayTradingSimulator(BaseSimulator):
    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        orders = decide_bull_daytrade(self._view(), candidates, current_prices)
        self._apply(orders, current_prices)   # base의 buy/sell 재사용
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
```

- `_view()`, `_apply()`는 `BaseSimulator`에 추가하는 공통 헬퍼.
- **동작 불변 보장:** 추출 전/후 Sim4-1·Sim5가 동일 orders를 내는 파리티 테스트.

### 주의: 상태 의존 청산(부분매도 플래그 등)

Sim4-1의 분할익절은 `partial_sold`/`partial_sold_date` 플래그를 청산 중 갱신한다. decide는
순수해야 하므로, 이런 상태 전이는 **Order에 실어 execute 단계에서 반영**한다(예:
`("MARK_PARTIAL", code, ...)` 또는 SELL Order의 메타). 파리티 테스트가 이 전이까지 검증한다.

---

## Part 3 — Sim10 얼로케이터 재작성

- 기존 순진한 픽커(`_filter_candidates`)·`REGIME_PARAMS` **삭제**.
- `get_universe()`: Sim0 regime을 읽어 **국면에 맞는 유니버스** 반환.
  - BULL → Sim4-1 유니버스(KIS 등락률 상위 30, `get_fluctuation_rank`)
  - SIDEWAYS → None(공통 버즈 후보, Sim5와 동일)
  - BEAR → None (어차피 신규매수 없음)
  - ← 이게 있어야 "BULL에서 Sim4-1을 그대로 실행"이 성립.
- `run()`: regime에 따라
  - BULL → `decide_bull_daytrade(self._view(), candidates, prices)` 실행 (Sim4-1 파라미터:
    종목당 initial/10, MAX_HOLDINGS 4)
  - SIDEWAYS → `decide_sideways(...)` (Sim5 파라미터)
  - BEAR → 보유 전량 청산 + 신규매수 없음(현금 보유)
- `regime_log`(ML 학습용) 유지.
- 별도 confidence 게이트는 넣지 않는다 — Sim0 재구성으로 국면을 신뢰(단순 유지).

---

## 테스트 전략 (TDD)

| 대상 | 테스트 |
|---|---|
| Sim0 재구성 | 주입 metrics로 regime 경계(BULL/SIDEWAYS/BEAR) + BEAR 실제 발동 + bull_score 재가중 |
| Part 2 추출 | Sim4-1·Sim5 파리티: 추출 전후 동일 orders(부분매도 전이 포함) |
| Sim10 | 국면별 올바른 decide 호출 / BULL 유니버스 전환 / BEAR 전량청산 |
| trade_engine | `_fetch_top100_breadth`가 momentum도 반환 / CSV trend 산출 |

## 변경 파일

| 파일 | 변경 |
|---|---|
| `src/strategy/simulators/sim0_libero.py` | metrics 주입 수용, foreign 제거·재가중 |
| `src/pipeline/workers/trade_engine.py` | top100 momentum 반환 + CSV trend 산출 + `live_market_metrics` 주입 |
| `src/strategy/simulators/sim4_bull_daytrading.py` | `decide_bull_daytrade` 추출, run() 래퍼화 |
| `src/strategy/simulators/sim5_sideways_swing.py` | `decide_sideways` 추출, run() 래퍼화 |
| `src/strategy/simulators/sim10_orchestrator.py` | 얼로케이터로 재작성, 순진한 픽커 삭제 |
| `src/strategy/simulators/base_simulator.py` | `_view()`, `_apply()` 공통 헬퍼 |

## 성공 판정

- Sim0: 재구성 후 calibration_log gap이 축소되고, 실제 하락 국면에서 BEAR가 잡힌다.
- Sim10: 다음 몇 거래일 실전에서 BULL 국면 시 Sim4-1과 동일한 진입/청산을 보이고,
  MDD가 기존(-43%) 대비 크게 줄어든다.
- 회귀 없음: Sim4-1·Sim5 파리티 테스트 그린(기존 심 동작 불변).
