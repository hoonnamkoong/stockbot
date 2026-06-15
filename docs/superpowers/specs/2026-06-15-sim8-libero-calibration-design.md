# 설계 문서: Sim8 리포트 팔로워 + Libero 캘리브레이션 + 차트 수정

**작성일**: 2026-06-15  
**범위**: 신규 시뮬레이터 Sim8, Libero 갭 데이터 수집, 차트 개선

---

## 1. 배경 및 목표

### 1-1. Sim8 신설 이유
텔레그램으로 발송되는 딥다이브 리포트에서 Gemini가 "강력 매수"로 등급을 부여한 종목을 매수했을 때 실제 성과가 어떤지 추적하는 시뮬레이터가 없었음. Sim8은 이 신호를 충실하게 따르는 "리포트 팔로워" 역할을 담당.

### 1-2. Libero 캘리브레이션 이유
현재 리베로 차트에서 bull_score(보라선)와 실제 KOSPI 브레드스(회색선)가 다른 단위와 스케일로 표시되어 둘의 차이(갭)를 정량적으로 파악하기 어려움. 향후 Sim7(리베로) 알고리즘을 개선할 때 근거 데이터로 활용하기 위해 갭 데이터를 미리 누적 수집.

---

## 2. Sim8 — 리포트 팔로워 (ReportFollower)

### 2-1. 기본 정보

| 항목 | 값 |
|---|---|
| 파일 | `src/strategy/simulators/sim8_report_follower.py` |
| 클래스 | `ReportFollowerSimulator` |
| 이름 인자 | `"ReportFollower"` |
| 상태 파일 | `data/sim_reportfollower_state.json` |
| CSV 파일 | `data/trade_history_sim_reportfollower.csv` |
| 초기 자본 | 3,000,000원 |
| IS_ANALYZER | False |

### 2-2. 유니버스 및 시그널 소스

기존 심들은 KIS API나 버즈 필터로 유니버스를 구성한 뒤 자체 진입 조건을 평가함.
Sim8은 유니버스 구성을 하지 않고, 오케스트레이터의 **Stage 3.5가 완료된 후** `final_picks`를 직접 전달받음.

**시그널 정의**: `final_picks` 중 `rank_and_recommendation` 필드가 `"강력 매수"` 문자열을 포함하는 종목만 진입 후보.

### 2-3. 진입 조건

1. `rank_and_recommendation`에 `"강력 매수"` 포함
2. 리베로 게이트: `libero.bull_score >= 45` (BEAR 국면 진입 차단)
3. 이미 보유 중인 종목(`portfolio`에 존재) → 스킵
4. 보유 종목 수 `>= MAX_HOLDINGS(5)` → 스킵 (교체 없음, 슬롯 빌 때까지 대기)

### 2-4. 포지션 사이징

- MAX_HOLDINGS: **5**
- 종목당 비중: **리베로 bull_score 선형 스케일링 (최소 10%, 최대 20%)**

```python
WEIGHT_MIN = 0.10   # bull_score = 45 (진입 게이트) 시
WEIGHT_MAX = 0.20   # bull_score = 100 시
GATE       = 45

weight = WEIGHT_MIN + (WEIGHT_MAX - WEIGHT_MIN) * (bull_score - GATE) / (100 - GATE)
weight = max(WEIGHT_MIN, min(WEIGHT_MAX, weight))  # clamp
```

예시: bull_score 45 → 10%, 72 → 15%, 100 → 20%

- 매수 수량: `floor(cash * weight / current_price)`
- 총 배치 한도: bull_score에 따라 50~100% (5슬롯 × 10~20%)

### 2-5. 청산 조건 (승자 라이딩 철학)

| 조건 | 기준 | 설명 |
|---|---|---|
| 트레일링 스탑 | 고점 대비 -5% | 라이딩 유지하되 되돌림 방어 |
| 하드 스탑 | 매입가 대비 -8% | 치명적 손실 방지 |
| 타임 스탑 | 7일 경과 + ±2% 이내 부동 | thesis 불발 판단, 자본 회수 |

고정 익절가 없음 — 트레일링에 걸릴 때까지 보유.

리베로 스탑 없음 — 진입 게이트에서 이미 BEAR 차단. 보유 중 포지션은 트레일링이 처리.

### 2-6. 실행 구조 — 이중 호출 패턴

Sim8은 두 가지 역할을 가지므로 두 경로로 호출됨:

**경로 A — Stage 3 (포트폴리오 관리)**  
`strategy_manifest.yaml`에 등록 → `engine.execute_simulation(candidates, current_prices)`가 매 실행마다 호출.  
이 경로에서는 **매수를 하지 않음** (candidates는 버즈 유니버스이므로 Sim8 시그널과 무관).  
트레일링 스탑 / 하드 스탑 / 타임 스탑 체크만 수행.

**경로 B — Stage 3.6 (신규 매수)**  
`src/pipeline/orchestrator.py`에 Stage 3.6 추가:

```
Stage 3.5: 딥다이브 리포트 생성 (기존)
Stage 3.6: Sim8 신규 매수 (신규)
  - final_picks에서 "강력 매수" 포함 픽만 필터
  - libero state 읽어서 bull_score >= 45 확인
  - Sim8.buy_from_report(filtered_picks) 호출
  - 가격은 final_picks의 current_price 사용
```

두 경로 분리 이유: 포트폴리오 관리(매일 실행)와 매수 시그널(딥다이브 생성 시에만)의 트리거가 다름.

---

## 3. Libero 캘리브레이션 데이터 수집

### 3-1. 목표

리베로의 버즈 유니버스 브레드스 추정치와 실제 KOSPI top100 브레드스 사이의 갭을 일별로 수집하여, 향후 Sim7 알고리즘 튜닝의 정량적 근거로 활용.

### 3-2. 수집 항목

```json
{
  "date": "2026-06-15",
  "libero_breadth": 62.5,
  "actual_kospi_breadth": 54.0,
  "gap": 8.5,
  "bull_score": 71.2,
  "regime": "BULL"
}
```

### 3-3. 실제 KOSPI 브레드스 산출 방법

`output/kospi_top100_close.csv` 최근 2행을 파이썬에서 직접 읽어 계산.
새 API 호출 없음. 스크래퍼가 이미 이 파일을 업데이트함.

```python
def get_actual_breadth_from_csv(csv_path='output/kospi_top100_close.csv') -> float | None:
    # 최근 2행 읽기 → 오늘 > 어제인 종목 비율(%) 반환
    # 파일 없으면 None
```

### 3-4. 저장 위치

`data/sim_libero_state.json` 내 `calibration_log` 키. 최대 **90일** 보관 (이후 롤링).

### 3-5. 파이프라인 연결

`src/pipeline/workers/trade_engine.py`에서 libero 실행 직후:

```
libero.run(candidates, current_prices)
→ actual_breadth = get_actual_breadth_from_csv()
→ if actual_breadth is not None:
     libero.record_calibration(actual_breadth)
```

`record_calibration()`은 `sim7_libero.py`에 추가. 같은 날 중복 기록 방지 (날짜 체크).

### 3-6. API 노출

`src/app/api/simulation/libero-history/route.ts` 응답에 `calibration_log` 필드 추가.
차트에서 이 데이터로 갭 추이선 렌더링.

---

## 4. 차트 수정

### 4-1. sim7Score 교체

`StrategyRadarChart.tsx`에서:

- **변경 전**: `liberoMap[l.date] = l.bull_score`
- **변경 후**: `liberoMap[l.date] = l.breadth`

두 선이 모두 "상승 종목 비율(%)" 단위로 통일됨. 직접 비교 가능.

범례 텍스트:
- 보라선: "리베로 추정 Breadth (버즈 유니버스)" 
- 회색선: "실제 KOSPI Breadth (top100)"

### 4-2. 방향 적중률 뱃지

차트 상단에 추가:
- 두 선이 같은 구역(60 이상 / 40~60 / 40 이하)에 있던 날 수 / 전체 비교 가능 일수
- 표시 예: `방향 적중 8/13일 (62%)`

### 4-3. 갭 추이선 (3번째 선)

`calibration_log`가 있는 경우 갭 데이터를 3번째 선으로 추가:
- 데이터: `libero_breadth - actual_kospi_breadth`
- 색상: 연한 회색 점선
- Y축: 0 기준선에 ReferenceLine 추가
- 없으면 표시하지 않음 (초기 기간 동안 데이터 없음)

### 4-4. 레이더 차트 그룹 재구성

Sim8 추가로 기존 2그룹 분류를 갱신:

| 그룹 | 심 목록 | 설명 |
|---|---|---|
| 그룹 1 | Sim1, Sim2, Sim3, Sim4, Sim4-1 | 심리·수급·리스크·모멘텀 계열 |
| 그룹 2 | Sim5, Sim6, Sim8 | 눌림·줍줍·리포트 팔로워 |

Sim7 리베로는 IS_ANALYZER=True로 성과 데이터 없음 → 레이더 차트 제외.

**`StrategyRadarChart.tsx` 변경**:
- `SERIES_G1`: sim1, sim2, sim3, sim4, sim4_daytrading
- `SERIES_G2`: sim5, sim6, sim8 (신규)
- `SERIES` 배열에 sim8 항목 추가 (label, color, desc)

---

## 5. 신규 심 추가 연결 체크리스트

기존 레슨런(메모리)의 필수 5곳 + Sim8 전용 3곳:

| # | 파일 | 수정 내용 |
|---|---|---|
| 1 | `src/strategy/simulators/sim8_report_follower.py` | 클래스 신규 생성 |
| 2 | `src/strategy/strategy_manifest.yaml` | id/module/class 등록 |
| 3 | `src/app/trade/TradeClient.tsx` | simConfigs 카드 추가 |
| 4 | `src/app/api/simulation/stats/route.ts` | types 배열 추가 |
| 5 | `src/app/api/trade/history/route.ts` | simFiles 배열 추가 |
| 6 | `src/pipeline/orchestrator.py` | Stage 3.6 추가 |
| 7 | `src/pipeline/workers/trade_engine.py` | calibration 계산 및 libero 전달 |
| 8 | `src/app/api/simulation/libero-history/route.ts` | calibration_log 응답 추가 |

---

## 6. 설계 결정 요약

| 항목 | 결정값 | 근거 |
|---|---|---|
| 진입 필터 | "강력 매수"만 | 빈도 제한 + 고확신 픽만 추적 |
| 비중 | bull_score 선형 10~20% | 시장 강도 연동, 단일 권위 신호 |
| MAX_HOLDINGS | 5 | 10~20% × 5 = 50~100% 배치 한도 |
| 교체 매매 | 없음 | 승자 라이딩 — 슬롯 빌 때까지 대기 |
| 리베로 스탑 | 없음 | 진입 게이트에서 이미 처리, 트레일링으로 충분 |
| 트레일링 | -5% | 라이딩 유지 |
| 하드 스탑 | -8% | 치명적 손실 방지 |
| 타임 스탑 | 7일 + ±2% 부동 | thesis 불발 처리 |
| 캘리브레이션 보관 | 90일 롤링 | Sim7 튜닝 근거 누적 |
| 차트 시리즈 교체 | bull_score → breadth | 같은 단위로 직접 비교 |
