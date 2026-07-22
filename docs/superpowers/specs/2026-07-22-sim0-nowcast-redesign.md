# 심0(리베로) 나우캐스트 재설계

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to create implementation plan after this spec is approved.

**Goal:** 심0 나우캐스트 정확도 44% 개선 + 신뢰도 기반 국면 판정으로 Sim 보호

**Architecture:** Hourly nowcast(짧은 지평) + 앙상블 모델(4개 신호 가중평균) + 신뢰도 판정(포화 최우선)

**Tech Stack:** Python, KIS API, pandas/numpy (기존 스택 유지)

## Global Constraints

- 심0는 국면 판정과 신뢰도만 담당; Sim별 동작(Sim6 스킵 등)은 각 Sim의 책임
- 신뢰도는 예측 정확도를 올리지 않고, "이 판정을 믿을 수 있는가" 판정만 함
- 현재 11일 데이터(9일 calibration_log v2 + 127개 hourly nowcast)로 학습
- Hourly nowcast는 매시간 갱신되며, 매 정각 회차에 출력됨

---

## 1. 현재 문제

**예측 정확도:**
- EOD(09:00 종일 예측): 평균 |gap| 14.2, 중앙값 9.0
- Hourly(1시간 앞): 평균 |gap| 9.4, 중앙값 6.0
- **개선 가능성: 34%** (데이터로 증명됨)

**신뢰도 부재:**
- 07-21 극단 케이스: 09:00 예측 12 → 10:00 예측 100 → 실제 70 (진동)
- 포화 문제: 16%의 예측이 0.0 또는 100.0에 박혀있음 (외삽)
- Sim이 "이 판정이 정확한가"를 판단할 신호 없음

---

## 2. 솔루션

### 2.1 예측 구조: Hourly Nowcast + 앙상블

**Hourly Nowcast (짧은 지평)**
- 기존: 09:00에 15:00까지 종일 예측
- 개선: 매시간 1시간 뒤만 예측 (rolling)
- 효과: |gap| 14.2 → 9.4 (34% 개선, 데이터 증명)

**앙상블 입력 (4개 신호)**
```
Input 1: Breadth (기존)
         = top100 거래량 기준 상승장 비율 (0~100)

Input 2: KOSPI 추세
         = (KOSPI / 5일MA - 1) * 100 (강도 판정)
         - 음수면 약세, 양수면 강세

Input 3: 외국인 순매수
         = 외국인 순매수액 정규화 (0~100)
         - 대량 진입/이탈 신호

Input 4: 낙폭장 비율
         = 낙폭종목 / (낙폭 + 상승) * 100
         - 약세 신호 (20 이하면 약세)
```

**앙상블 가중평균:**
```python
final_breadth = (
    0.5 * breadth 
    + 0.2 * kospi_trend 
    + 0.2 * foreigner_score 
    + 0.1 * decline_ratio
)
```

**예상 정확도:** |gap| 9.4 → 8.0 이상 (추가 10~15% 개선)

### 2.2 신뢰도 계산 (포화 최우선)

**4가지 신호:**

1. **Saturation (포화)** — 예측이 극단값인가
   - 포화(0~0.1 또는 0.9~1.0): 0.2
   - 극단값(0.1~0.2 또는 0.8~0.9): 0.5
   - 정상 범위(0.2~0.8): 0.9

2. **Volatility (진동)** — 최근 3시간 예측 진동
   - 표준편차 > 25: 0.3
   - 표준편차 15~25: 0.6
   - 표준편차 < 15: 0.9

3. **Input Agreement (입력 합의)** — 4개 신호 일치도
   - 모두 상승/하락 방향: 0.9
   - 3개 일치: 0.7
   - 2개 이하: 0.5

4. **Timeframe Maturity (타이밍)** — 시간 경과에 따른 안정도
   - 09:00: 0.5
   - 12:00: 0.7
   - 15:00: 0.9

**최종 신뢰도 공식:**
```python
confidence = saturation * (0.6 + 0.2*volatility + 0.1*input_agreement + 0.1*timeframe)
```

**효과:**
- 포화 감지: 07-21 같은 극단 케이스의 신뢰도 자동 낮춤
- 진동 감지: 국면 전환 시기 불확실성 표현
- 입력 합의: 여러 신호가 일치할 때 신뢰도 올림
- 타이밍: 오후가 아침보다 신뢰도 높음 (데이터 충분)

### 2.3 국면 판정 (3상태 유지)

**판정 로직:**
```python
if final_breadth >= 60:
    regime = "BULL"
elif final_breadth <= 40:
    regime = "BEAR"
else:
    regime = "SIDEWAYS"
```

**신뢰도와의 분리:**
- regime: 3상태 (변함없음)
- confidence: 0.0~1.0 점수 (새로 추가)
- Sim의 역할: regime은 참고만 하고, confidence를 보고 판단 (각자 로직)

---

## 3. 상태 JSON 구조

```json
{
  "current_regime": "BULL",
  "confidence": 0.72,
  "instant_regime": "BULL",
  
  "hourly_regime_log": [
    {
      "hour": "09:00",
      "regime": "SIDEWAYS",
      "confidence": 0.45,
      "breadth": 25.0,
      "inputs": {
        "breadth": 25,
        "kospi_trend": 15,
        "foreigner": 30,
        "decline_ratio": 45
      }
    },
    {
      "hour": "10:00",
      "regime": "BULL",
      "confidence": 0.68,
      "breadth": 62.0,
      "inputs": {...}
    }
  ],
  
  "calibration_log": [
    {
      "date": "2026-07-22",
      "hour": "10:00",
      "pred": 62.0,
      "actual": 60.0,
      "gap": 2.0,
      "confidence": 0.68
    }
  ]
}
```

---

## 4. 데이터 흐름

**매시간 (09:00 ~ 15:00):**
```
1. 장 데이터 수집 (top100 거래량, KOSPI, 외국인, 낙폭장)
2. 4개 입력 계산
3. 앙상블: final_breadth = 가중평균
4. 국면 판정: BULL/SIDEWAYS/BEAR
5. 신뢰도 계산: 4가지 신호 → confidence
6. hourly_regime_log에 추가
7. current_regime, confidence 갱신
```

**매일 18:00 (장 종료 후):**
```
1. 실제 종가 및 최종 국면 확정
2. calibration_log 갱신 (예측 vs 실제 비교)
3. 모델 평가 (정확도 추이)
```

---

## 5. 검증 방법

**정확도 테스트 (현재 11일 데이터):**
- 앙상블 모델 vs 기존 EOD
- 목표: |gap| 14.2 → 8.0 이상 (44% 개선)
- 실패 기준: 8.0 미달 또는 신뢰도와 오류의 상관관계 없음

**신뢰도 검증:**
- confidence < 0.5일 때의 오류율 > 20%인가?
- confidence >= 0.8일 때의 오류율 < 10%인가?
- 포화 감지가 07-21 극단 케이스를 잡았는가?

**Sim 통합 검증:**
- Sim6: confidence < 0.5일 때 실제로 매매 스킵하는가?
- Sim10: 신뢰도 낮을 때 allocation 감소하는가?

---

## 6. 배포 계획

**구현 일정:**
- 구현 + 테스트: 2일
- 배포: 2026-07-28(월) 또는 2026-07-23(목) 중 선택

**배포 전 체크:**
- 정확도 목표 달성 확인
- calibration_log 형식 일치 확인
- Sim6/10 통합 테스트
- 라이브 시뮬레이션 1일 (07-28~07-29)

**롤백 계획:**
- 신뢰도 < 0.3이면 현재 regime 유지 (안전장치)
- 긴급 시 hourly_regime_log 무시하고 current_regime만 사용

---

## 변경 영향

**Sim0 (리베로):**
- 출력 구조 변경: current_regime + confidence 추가
- 학습 데이터: calibration_log v2 기반

**Sim6 (인버스 ETF):**
- confidence < 0.5이면 매매 중단 가능 (각 Sim 판단)

**Sim10 (오케스트레이터):**
- 신뢰도 낮은 국면에서 allocation 조정 가능 (각 Sim 판단)

**Sim5 (레인지 스윙):**
- 영향 없음 (Sim0 판정 미사용)
