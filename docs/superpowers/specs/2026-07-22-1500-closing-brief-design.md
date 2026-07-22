# 15시 마감 브리핑 텔레그램 설계

- 작성일: 2026-07-22
- 상태: 승인됨 (구현 계획 대기)

## 배경

장중 텔레그램은 매시 정각 회차에만 발송된다([`context.py`](../../../src/pipeline/context.py) `should_notify()` — 시작 분이 0~2분일 때만 True). 태스커가 09:00~15:30을 10분 주기로 호출하므로 스크래핑은 매 10분, 텔레그램은 시간당 1회이고 **15:00 회차가 당일 마지막 발송**이다.

이 마지막 발송에 하루를 마무리하는 요약을 붙인다. 지금은 종목 리포트만 나가서, 실전 계좌가 어떻게 됐는지와 각 심이 뭘 했는지를 보려면 대시보드를 따로 열어야 한다.

## 목표

15:00 텔레그램에 다음을 담은 별도 메시지를 추가한다.

1. 실전 계좌: 예수금, 총 자산수익률, 총 평가손익, 보유 종목 총액
2. 심별: 수익률, 금일 거래 종목 수 (리셋 대상 9개 전부)

## 설계 원칙

**대시보드와 같은 수를 보여준다.** 텔레그램과 웹이 다른 값을 말하면 둘 다 못 믿게 된다. 계산식을 새로 만들지 않고 대시보드가 쓰는 식을 그대로 옮긴다. 심 수익률은 계산조차 하지 않고 상태 파일에 이미 저장된 값을 읽는다.

**없는 수는 만들지 않는다.** 조회에 실패하면 0원이나 0%가 아니라 "측정 불가"로 적는다. 0원과 "모름"은 다른 정보다.

## 데이터 소스

### 실전 계좌 — `src/trade/balance.py`의 `get_balance()`

KIS 잔고조회(TTTC8434R) 응답을 쓴다. 대시보드는 같은 데이터를 TS 경로([`kis-api.ts`](../../../src/lib/kis-api.ts) `getRealPortfolio`)로 받아 [`TradeClient.tsx`](../../../src/app/trade/TradeClient.tsx) `renderRealPortfolioSection()`에서 아래처럼 계산한다.

| 표시 항목 | 계산식 | 비고 |
|---|---|---|
| 예수금 | `output2.dnca_tot_amt` | 그대로 |
| 보유 종목 총액 | `Σ(현재가 × 수량)` | 수량 0인 종목 제외 |
| 총 평가손익 | `Σ(evlu_pfls_amt)` | 종목별 평가손익 합 |
| 총 자산수익률 | `총평가손익 ÷ (보유총액 − 총평가손익) × 100` | 분모는 매입원가 |

`get_balance()`가 현재 반환하는 holdings에는 `evlu_pfls_amt`가 없다(수익률 `evlu_pfls_rt`만 있음). 종목별 평가손익을 합산할 수 없으므로 **`pl_amount` 필드를 추가한다.** 이것이 이 작업에서 유일하게 기존 파일에 손대는 부분이다.

### 심별 수익률 — `data/sim_*_state.json`에서 대시보드와 같은 식으로 산출

**대시보드는 상태 파일의 `raw_stats.profit_rate`를 쓰지 않는다.** [`stats/route.ts`](../../../src/app/api/simulation/stats/route.ts)가 live 상태로 다시 계산해 그 필드를 덮어쓴다.

```
portfolio_value = Σ (raw_stats.current_prices[code] or item.current_price or item.avg_price) × item.quantity
profit_rate     = (state.cash + portfolio_value − state.initial_cash) / state.initial_cash × 100
```

브리핑도 **이 식을 그대로 쓴다.** `raw_stats.profit_rate`를 읽으면 안 되는 이유는 분모가 어긋나기 때문이다: [`base_simulator.py`](../../../src/strategy/simulators/base_simulator.py) `calculate_stats()`는 분모로 `self.initial_cash`를 쓰는데, `load_state()`가 `setdefault`만 하고 상태 파일의 `initial_cash`를 `self.initial_cash`로 되읽지 않는다. 그래서 파이썬 쪽 분모는 생성자 기본값 300만에 고정된다. 리셋 버튼은 10만~10억을 허용하므로, 300만이 아닌 금액으로 리셋하는 순간 텔레그램과 웹이 다른 수익률을 말하게 된다.

**`cash + invested`로 구하지도 않는다.** `invested`는 매입원가라서 실시간 시세 평가가 되지 않는다.

측정 불가(`None`) 조건: 상태 파일 없음, 파일 읽기 실패, `initial_cash`가 없거나 0 이하(분모를 만들 수 없음).

### 금일 거래 종목 수 — `data/trade_history_*.csv`

오늘(KST) 날짜로 시작하는 행을 모아 **symbol 중복을 제거한 개수**를 센다. 거래 건수가 아니라 종목 수다. 대시보드도 같다.

### 대상 심 9개

`RESET_TARGETS`([`sim-reset-targets.ts`](../../../src/lib/sim-reset-targets.ts))와 동일한 9개. 리셋 버튼이 다루는 범위와 정확히 일치시켜 비교 조건을 맞춘다. Sim0 리베로는 매매하지 않으므로 제외한다.

표시명은 대시보드 라벨을 그대로 쓴다.

| id | 상태 파일 | 표시명 |
|---|---|---|
| sim1 | `sim_psych_state.json` | 심리 괴리형 (Sim 1) |
| sim2 | `sim_spillover_state.json` | 수급 동승형 (Sim 2) |
| sim3 | `sim_risk_state.json` | 가치 페어형 (Sim 3) |
| sim4 | `sim_bull_state.json` | 상승 모멘텀형 (Sim 4) |
| sim4_daytrading | `sim_bulldaytrade_state.json` | 상승 단타형 (Sim 4-1) |
| sim5 | `sim_sideways_state.json` | 추세 눌림목형 (Sim 5) |
| sim6 | `sim_bear_state.json` | 하락 줍줍형 (Sim 6) |
| sim7 | `sim_reportfollower_state.json` | 리포트 팔로워 (Sim 7) |
| sim10 | `sim_orchestrator_state.json` | 오케스트레이터 (Sim 10) |

Sim 5·6 라벨은 2026-07-21 재설계 이전 이름이다(현재 전략은 레인지 스윙 / 인버스 ETF 추세추종). 지금은 대시보드와 일치시키는 쪽을 택했다. 이름 정정은 대시보드와 함께 별건으로 다룬다.

## 구조

메시지 조립을 순수 함수로 떼어내 발송·조회와 분리한다.

```
src/pipeline/daily_brief.py            (신규)
  build_daily_brief(balance, sims, now_kst) -> str
      순수 함수. 입력은 이미 조회된 dict, 출력은 텔레그램 본문 문자열.
      I/O 없음 → 단위 테스트 대상.

  collect_sim_brief(data_dir, today_str) -> list[dict]
      상태 파일 + CSV를 읽어 [{label, profit_rate|None, ticker_count}] 반환.

src/pipeline/workers/notifier.py       (수정)
  run()에 15시 분기 추가 → _send_daily_brief()
```

`build_daily_brief`가 순수 함수인 덕에 잔고 조회 실패·`raw_stats` 누락·보유 0종목 같은 경계 상황을 KIS API 없이 테스트할 수 있다.

## 발송 조건

[`notifier.py`](../../../src/pipeline/workers/notifier.py) `run()`에서 기존 리포트 발송 **직후**:

```
if self.ctx.should_notify() and self.ctx.now_kst.hour == 15:
    self.safe_run(self._send_daily_brief, self._brief_fallback)
```

- `should_notify()`는 건드리지 않는다. 이 게이트는 다른 알림도 함께 통제하므로 조건을 넓히면 영향 범위를 예측하기 어렵다.
- 15:00 회차만 통과한다(15:10~15:30 회차는 분 조건에서 이미 걸러진다).
- 기존 메시지에 붙이지 않고 별도 메시지로 보낸다. 실패해도 종목 리포트는 이미 나간 뒤다.
- `safe_run`으로 감싸 발송 실패가 파이프라인을 멈추지 않게 한다.

## 메시지 형식

```
📅 15:00 마감 브리핑  07/22 (수)

💼 실전 계좌 (KIS)
  예수금          1,240,000원
  보유 종목 총액   5,250,000원
  총 평가손익      +250,000원
  총 자산수익률    +5.00%

🤖 심별 현황 (수익률 / 금일 거래)
  심리 괴리형 (Sim 1)      -1.11%   6종목
  수급 동승형 (Sim 2)      -0.01%   3종목
  가치 페어형 (Sim 3)       0.00%   0종목
  상승 모멘텀형 (Sim 4)    -0.01%   4종목
  상승 단타형 (Sim 4-1)    -0.01%   3종목
  추세 눌림목형 (Sim 5)     0.00%   0종목
  하락 줍줍형 (Sim 6)       0.00%   0종목
  리포트 팔로워 (Sim 7)     0.00%   0종목
  오케스트레이터 (Sim 10)   -0.01%   3종목
```

금액은 천 단위 구분, 손익·수익률은 양수에 `+`를 붙인다. `send_message()`는 HTML 파스 모드가 기본이고 실패 시 평문으로 재시도하므로, 정렬은 공백으로만 맞추고 마크업에 기대지 않는다.

## 실패 처리

| 상황 | 표시 |
|---|---|
| KIS 잔고 조회 실패 | 계좌 블록을 `⚠️ 실전 계좌: 조회 실패 (사유)`로 대체. 심 블록은 정상 발송 |
| 보유 종목 0개 | 예수금·보유총액·평가손익은 실제 값(0원 포함), 수익률은 `—` (분모 0은 0%가 아니다) |
| 상태 파일 없음 / `raw_stats` 없음 | 해당 심 수익률만 `측정 불가`, 나머지 심은 정상 |
| CSV 없음 | 해당 심 거래 종목 수 `0종목` (파일 없음 = 거래 없음이 맞다) |

수익률의 `—`와 거래 종목 수의 `0`은 구분한다. 전자는 모르는 것이고 후자는 아는 것이다.

## 테스트

`tests/test_daily_brief.py` (기존 규약: `tests/test_*.py`, pytest):

1. 정상 입력 → 계좌 4항목과 심 9줄이 모두 있고 수익률 부호가 맞는지
2. `balance`에 `error` 키 → 조회 실패 문구가 나오고 심 블록은 유지되는지
3. 보유 0종목 → 수익률이 `0.00%`가 아니라 `—`인지
4. 특정 심의 `raw_stats` 누락 → 그 심만 `측정 불가`, 다른 심은 정상인지
5. `collect_sim_brief`: 오늘 날짜 행만 세는지, 같은 종목 2회 거래를 1종목으로 세는지

`build_daily_brief`가 I/O를 하지 않으므로 전부 고정 입력으로 검증된다.

## 범위 밖

- `should_notify()` 게이트 변경 (15:30 마감 확정 수치 발송)
- Sim 5·6 표시명 정정
- 심별 승률·손익비 등 추가 지표
