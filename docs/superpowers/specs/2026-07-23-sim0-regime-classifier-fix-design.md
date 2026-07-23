# 심0(리베로) 국면 분류기 수정 설계

**Goal:** 심0의 국면 결정(`current_regime`)이 상승장을 놓치는 문제를 오프라인 검증 기반으로 교정하고, 향후 앙상블 검증을 위한 4신호 데이터 수집을 도입한다.

**대원칙:** "확인 후 대체." 모든 분류기 변형은 과거 데이터로 국면 적중률을 먼저 증명하고, 구 로직 대비 개선이 확인된 조합만 라이브 반영한다.

**Tech Stack:** Python (기존 스택 유지). 라이브 데이터는 `db-data` 브랜치의 `data/sim_libero_state.json`.

---

## 1. 현재 문제 (데이터 실증)

Sim6(`current_regime=="BEAR"` 게이트)와 Sim10(`active_regime`)이 심0의 `current_regime`을 읽어 매매를 좌우한다. 이 값은 `run()`에서 `classify_regime(breadth, momentum, trend)` → 5회 스무딩으로 산출된다.

**`classify_regime`의 AND 게이트가 상승장을 놓친다.** BULL 조건이 `breadth≥60 AND momentum≥2.0 AND trend≥20` 3조건 동시 충족이라, breadth가 극단적으로 높아도 momentum/trend 하나만 미달하면 SIDEWAYS로 붕괴한다.

db-data 브랜치 `daily_regime_log` 실측 (2026-07 기준):

| 날짜 | 실측 breadth | bull_score | 확정 regime | 판정 |
|---|---|---|---|---|
| 07-10 | 89 | 71.4 | SIDEWAYS | 상승장 놓침 |
| 07-13 | 68 | 72.3 | SIDEWAYS | 상승장 놓침 |
| 07-15 | 96 | 71.0 | SIDEWAYS | 강한 상승장 놓침 |
| 07-22 | 98 | 68.7 | SIDEWAYS | 극단 상승장 놓침 |
| 07-16 | 40 | 37.9 | BULL | 거꾸로(약세인데 BULL) |
| 07-20 | 5 | 21.9 | SIDEWAYS | (BEAR이어야) |
| 07-21 | 12 | 29.3 | BEAR | 정상 |

calibration_log 27건 중 regime 분포: SIDEWAYS 20 / BULL 6 / BEAR 1. 실측 breadth≥60인 날의 2/3이 BULL을 놓쳤다.

심0 매매 철학은 "상승장에서만 승자 라이딩"인데, **핵심 트리거가 상승장을 거의 다 놓치고 있다.** 이는 nowcast 예측 오차보다 상위 문제다.

**참고 — 예측 층은 매매에 안 쓰인다.** EOD(09:00 종일) 예측 |gap| 35.5, hourly +1h 예측 |gap| 9.5는 표시/채점 전용이며 `current_regime` 산출에는 관여하지 않는다. 본 설계는 **매매를 좌우하는 국면 결정부**를 고친다.

## 2. 목표 & 성공 기준

- **1차(검증):** 27일 calibration + 129 hourly 데이터에 대해 신규 분류기의 **국면 적중률**과 **상승장 포착률**이 구 AND게이트 대비 개선됨을 오프라인으로 증명.
- **2차(대체):** 검증 통과 조합만 라이브 `run()`에 반영. 미통과 시 구 로직 유지(fail-safe).
- **데이터 수집:** 4신호가 매 런 `hourly_regime_log`에 적재되기 시작(향후 앙상블 검증 코퍼스).

**국면 적중 정의(오프라인):** 그날 `actual_kospi_breadth`로 정의한 기준 국면(actual≥60=BULL, ≤35=BEAR, else SIDEWAYS)과 분류기 출력의 일치 여부. 상승장 포착률 = 기준이 BULL인 날 중 분류기도 BULL로 맞춘 비율.

## 3. 아키텍처

심0 국면 결정부를 순수 함수로 분리해 검증 하네스가 오프라인 재현할 수 있게 한다. `current_regime` 계약(문자열 BULL/SIDEWAYS/BEAR)은 불변 — **Sim6/Sim10은 수정하지 않는다.**

```
run() 국면 결정 흐름 (신규):
  breadth, momentum, trend  (기존 수집)
    → [3b] breadth 항에 hourly +1h 예측 주입(옵션)
    → bull_score = 0.40*breadth + 0.35*momentum_n + 0.25*trend_n  (기존 식)
    → [1] regime = classify_by_score(bull_score, θ_bull, θ_bear)   (밴드)
    → [3a] confirmed = smooth(history, 완화 규칙)
    → current_regime
```

## 4. 컴포넌트 상세

### Part 1 — bull_score 밴드 분류기

`classify_regime`의 AND게이트를 대체하는 순수 함수:

```python
def classify_by_score(bull_score, theta_bull, theta_bear):
    if bull_score >= theta_bull: return "BULL"
    if bull_score <= theta_bear: return "BEAR"
    return "SIDEWAYS"
```

- θ는 하드코딩하지 않는다. 검증 하네스가 스윕해 27일 적중률 최대점을 찾는다(초기 탐색 60/35).
- `calc_bull_score`(기존, 0.40/0.35/0.25 가중)는 그대로 재사용 — bull_score는 이미 3지표를 합리적으로 혼합한다.

### Part 3a — 스무딩 완화

현 `_confirm_regime`은 5회 과반 + `counts[top] < len//2+1 → SIDEWAYS` 강제. 이 편향이 상승 전환을 늦추고 SIDEWAYS로 끌어당긴다.

- 후보 A: 히스토리 길이 5→3 축소(반응성↑).
- 후보 B: 신뢰도 가중(최근 회차 가중 다수결).
- 검증 하네스가 랙(전환 지연)–적중률을 측정해 택1. 강제 SIDEWAYS 편향은 제거하고, 동률/불명확 시에만 직전 국면 유지.

### Part 3b — 전방지향 regime

bull_score의 breadth 항에 현재 breadth 대신 **hourly +1h 예측 breadth**를 주입한다.

- momentum/trend는 예측값이 없으므로 현재값 유지 → 하이브리드 전방 score.
- 예측 breadth는 기존 `update_nowcast`의 +1h 예측을 재사용(신규 예측 로직 없음).
- 검증: intraday_score_log의 (pred, actual) 쌍으로 "전방 score 기반 국면"이 "현재 score 기반 국면"보다 실측 국면을 잘 맞추는지 비교.
- 예측 실패(값 없음) 시 현재 breadth로 폴백 — 전방지향이 매매를 막지 않는다.

### Part 2 — 4신호 데이터 수집 (매매 무관)

향후 앙상블 검증을 위해 매 런 4신호를 `hourly_regime_log`에 적재한다. 매매 로직·regime 결정에 영향 없음(순수 기록).

신규 수집 입력:
- **KOSPI 지수 price / 5일 MA** — 현재 파이프라인은 KOSPI healthy 불리언만 노출. 지수 종가 시계열을 저장해 ma5 산출.
- **외국인 순매수 총액** — 현재 종목별 `foreign_net_buy`만 수집. top100 합산으로 시장 총액 집계.
- **낙폭비율** — declining/rising 카운트. top100 breadth 산출 시 이미 계산되는 값을 노출.

`hourly_regime_log` 항목:
```jsonc
{
  "hour": "11:00",
  "regime": "BULL",          // 그 시각 run()의 current_regime (수집은 미검증 분류기와 무관)
  "breadth": 74.0,
  "inputs": { "breadth": 74.0, "kospi_trend": 12.3,
              "foreigner_score": 61.0, "decline_ratio": 26.0 }
}
```

수집 실패한 신호는 해당 필드 생략(가짜 0/50 금지) — [[no-fabricated-financial-values]] 원칙.

### 검증 하네스 (신규 테스트)

`tests/test_sim0_regime_backtest.py` — db-data 스냅샷(또는 커밋된 픽스처)을 입력으로:

- 분류기 변형별 국면 적중률·상승장 포착률·전환 랙 비교표 출력:
  `[구 AND게이트] / [Part1] / [Part1+3a] / [Part1+3a+3b]`
- θ 스윕 결과(적중률 곡선).
- **구 대비 개선이 확인된 조합만 배포 게이트 통과** — 개선 없으면 해당 Part 미반영.

## 5. 데이터 소스

라이브 심0 상태는 **`db-data` 브랜치** `data/sim_libero_state.json` (파이프라인이 GitHub Actions로 커밋). main의 동명 파일은 빈 플레이스홀더. 검증 하네스는 커밋된 픽스처(스냅샷)를 쓰고, CDN 캐시 함정을 피한다([[db-data-verification-gotchas]]).

## 6. 인터페이스 계약 (불변)

- `current_regime`: "BULL"|"SIDEWAYS"|"BEAR" 문자열. Sim6/Sim10 소비 방식 무변경.
- `run()` 반환·저장 state 키: 기존 유지 + `hourly_regime_log` 적재 시작.
- 매매 집행·effective_budget·주문 경로: 일절 무관.

## 7. 테스트 계획

- 순수 함수 단위 테스트: `classify_by_score`(밴드 경계), 스무딩 완화 규칙, 전방 score 폴백.
- 백테스트 하네스(위): 변형별 적중률 비교, 배포 게이트.
- 4신호 수집: 각 신호 수집 함수 단위 테스트 + 실패 시 필드 생략 검증.
- 회귀: 신규 분류기 미배포(검증 실패) 시 `run()`이 구 `classify_regime` 그대로 쓰는지.
- 기존 `tests/test_sim0_*`·`test_libero_*` 통과 유지.

## 8. 범위 밖

- 앙상블 라이브 배선(kospi_trend·foreigner·decline_ratio를 regime 결정에 실제 사용) — 데이터 축적·검증 후 별도 사이클.
- Sim6 신뢰도 게이팅, EOD forecast 포화 수정 — 이번 미포함(사용자 선택).
- Sim6/Sim10 로직 변경.
- 예측(nowcast) 로직 자체 변경 — 3b는 기존 +1h 예측을 재사용만.

## 9. 롤아웃

1. 데이터 수집(Part 2) 먼저 배포 — 매매 무관, 코퍼스 축적 시작.
2. 검증 하네스로 Part 1/3a/3b 오프라인 증명.
3. 통과 조합만 `run()`에 반영(구 로직 폴백 유지).
4. 라이브 반영 후 `daily_regime_log`로 상승장 포착 개선 관찰.
