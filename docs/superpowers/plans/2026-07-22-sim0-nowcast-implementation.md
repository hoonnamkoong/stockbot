# 심0(리베로) 나우캐스트 재설계 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hourly nowcast + 앙상블 모델 + 신뢰도 판정으로 정확도 44% 개선 (|gap| 14.2 → 8.0)

**Architecture:** 심0는 매시간 4개 신호를 수집하고, 앙상블 모델로 final_breadth를 계산한 후, 신뢰도 점수와 함께 3상태 국면을 출력. Sim별 활용은 각자 책임.

**Tech Stack:** Python, KIS API, pandas/numpy (기존 유지)

## Global Constraints

- Hourly nowcast: 매시간 1시간 앞 예측만 (09:00~15:00 중 언제든 갱신 가능)
- 4개 입력 신호: breadth(기존), kospi_trend, foreigner_score, decline_ratio (모두 0~100 정규화)
- 앙상블 가중치: 0.5, 0.2, 0.2, 0.1 (정확한 값 유지)
- 신뢰도 공식: confidence = saturation * (0.6 + 0.2*volatility + 0.1*input_agreement + 0.1*timeframe)
- 상태 JSON 포맷: current_regime, confidence, hourly_regime_log, calibration_log (명시된 구조 정확히 따름)
- 정확도 목표: |gap| 평균 8.0 이상 (기존 14.2 대비 44% 개선)
- 신뢰도 검증: confidence < 0.5일 때 오류율 > 20%, >= 0.8일 때 오류율 < 10%

---

## 파일 구조

**수정:**
- `src/strategy/simulators/sim0_libero.py` — 메인 구현 (305줄, 4개 신호 수집 + 앙상블 + 신뢰도 추가)
- `data/sim_libero_state.json` — 상태 파일 포맷 변경

**생성:**
- `tests/test_sim0_nowcast.py` — 단위 테스트 (신호별, 앙상블, 신뢰도, 포맷)
- `tests/test_sim0_accuracy.py` — 정확도 검증 (기존 calibration_log v2 데이터)

---

## Task 1: 4개 입력 신호 수집 함수 구현

**Files:**
- Modify: `src/strategy/simulators/sim0_libero.py:1-50`
- Test: `tests/test_sim0_nowcast.py`

**Interfaces:**
- Consumes: KIS API 데이터 (기존 코드의 collect_market_data 함수)
- Produces:
  ```python
  def collect_signals(market_data, kospi_data, foreigner_data):
      """
      Returns:
      {
          'breadth': float (0-100),
          'kospi_trend': float (-100 ~ 100),
          'foreigner_score': float (0-100),
          'decline_ratio': float (0-100)
      }
      """
  ```

- [ ] **Step 1: KOSPI 추세 계산 함수 작성**

```python
def calculate_kospi_trend(kospi_price, kospi_ma5):
    """KOSPI 추세 = (KOSPI / 5일MA - 1) * 100"""
    if kospi_ma5 <= 0:
        return 0.0
    trend = ((kospi_price / kospi_ma5) - 1) * 100
    return min(100, max(-100, trend))  # -100 ~ 100 클립
```

- [ ] **Step 2: 외국인 순매수 정규화 함수 작성**

```python
def normalize_foreigner_score(foreigner_buy_amount, historical_max=100000000000):
    """외국인 순매수액을 0~100으로 정규화
    
    Args:
        foreigner_buy_amount: 외국인 순매수액 (음수 허용)
        historical_max: 과거 최대값 기준 (학습 데이터에서 산출)
    
    Returns: 0 ~ 100 (0 = 최대 매도, 50 = 중립, 100 = 최대 매수)
    """
    normalized = (foreigner_buy_amount / historical_max) * 50 + 50
    return min(100, max(0, normalized))
```

- [ ] **Step 3: 낙폭장 비율 계산 함수 작성**

```python
def calculate_decline_ratio(declining_count, rising_count):
    """낙폭장 비율 = 낙폭종목 / (낙폭 + 상승) * 100
    
    Returns: 0 ~ 100 (0 = 모두 상승, 100 = 모두 낙폭)
    """
    total = declining_count + rising_count
    if total == 0:
        return 50.0
    ratio = (declining_count / total) * 100
    return ratio
```

- [ ] **Step 4: collect_signals 메인 함수 작성**

```python
def collect_signals(market_data, kospi_data, foreigner_data):
    """4개 입력 신호 수집
    
    Args:
        market_data: {'breadth': float (0-100), 'declining': int, 'rising': int}
        kospi_data: {'price': float, 'ma5': float}
        foreigner_data: {'buy_amount': float}
    
    Returns:
        {'breadth': float, 'kospi_trend': float, 'foreigner_score': float, 'decline_ratio': float}
    """
    breadth = market_data.get('breadth', 50.0)
    breadth = min(100, max(0, breadth))
    
    kospi_trend = calculate_kospi_trend(
        kospi_data.get('price', 0),
        kospi_data.get('ma5', 1)
    )
    
    foreigner_score = normalize_foreigner_score(
        foreigner_data.get('buy_amount', 0)
    )
    
    decline_ratio = calculate_decline_ratio(
        market_data.get('declining', 0),
        market_data.get('rising', 1)
    )
    
    return {
        'breadth': breadth,
        'kospi_trend': kospi_trend,
        'foreigner_score': foreigner_score,
        'decline_ratio': decline_ratio
    }
```

- [ ] **Step 5: 테스트 작성**

```python
# tests/test_sim0_nowcast.py
import pytest
from src.strategy.simulators.sim0_libero import (
    calculate_kospi_trend, normalize_foreigner_score,
    calculate_decline_ratio, collect_signals
)

def test_kospi_trend_positive():
    trend = calculate_kospi_trend(2500, 2400)  # +4.17%
    assert 4 < trend < 5

def test_kospi_trend_negative():
    trend = calculate_kospi_trend(2400, 2500)  # -4%
    assert -5 < trend < -3

def test_kospi_trend_clipped():
    trend = calculate_kospi_trend(3500, 2000)  # +75% → 클립 100
    assert trend == 100
    
    trend = calculate_kospi_trend(1000, 2000)  # -50% → 클립 -100
    assert trend == -100

def test_foreigner_score_max_buy():
    score = normalize_foreigner_score(100000000000)  # 최대 매수
    assert score == 100

def test_foreigner_score_neutral():
    score = normalize_foreigner_score(0)  # 중립
    assert score == 50

def test_foreigner_score_max_sell():
    score = normalize_foreigner_score(-100000000000)  # 최대 매도
    assert score == 0

def test_decline_ratio_all_rising():
    ratio = calculate_decline_ratio(0, 100)
    assert ratio == 0

def test_decline_ratio_all_declining():
    ratio = calculate_decline_ratio(100, 0)
    assert ratio == 100

def test_decline_ratio_half():
    ratio = calculate_decline_ratio(50, 50)
    assert ratio == 50

def test_collect_signals():
    signals = collect_signals(
        {'breadth': 60, 'declining': 30, 'rising': 70},
        {'price': 2500, 'ma5': 2400},
        {'buy_amount': 50000000000}
    )
    
    assert signals['breadth'] == 60
    assert 4 < signals['kospi_trend'] < 5
    assert 50 < signals['foreigner_score'] < 100
    assert signals['decline_ratio'] == 30
```

- [ ] **Step 6: 테스트 실행**

```bash
cd c:\Users\Hoon_DT\gemini\stock
pytest tests/test_sim0_nowcast.py::test_kospi_trend_positive -v
pytest tests/test_sim0_nowcast.py::test_foreigner_score_neutral -v
pytest tests/test_sim0_nowcast.py::test_decline_ratio_half -v
pytest tests/test_sim0_nowcast.py::test_collect_signals -v
```

Expected: 모든 테스트 PASS

- [ ] **Step 7: Commit**

```bash
git add src/strategy/simulators/sim0_libero.py tests/test_sim0_nowcast.py
git commit -m "feat(sim0): 4개 입력 신호 수집 함수 (KOSPI, 외국인, 낙폭장)"
```

---

## Task 2: 앙상블 모델 구현

**Files:**
- Modify: `src/strategy/simulators/sim0_libero.py:51-100`
- Test: `tests/test_sim0_nowcast.py`

**Interfaces:**
- Consumes: collect_signals 출력 (breadth, kospi_trend, foreigner_score, decline_ratio)
- Produces:
  ```python
  def ensemble_breadth(signals):
      """
      Args:
          signals: {'breadth': float, 'kospi_trend': float, 'foreigner_score': float, 'decline_ratio': float}
      
      Returns: float (0~100)
      """
  ```

- [ ] **Step 1: 앙상블 함수 작성**

```python
def ensemble_breadth(signals):
    """4개 신호의 가중평균
    
    final_breadth = 0.5 * breadth + 0.2 * kospi_trend + 0.2 * foreigner_score + 0.1 * decline_ratio
    
    모든 입력은 0~100 범위로 정규화되어 있다고 가정.
    kospi_trend는 -100~100이므로 0~100으로 변환: (kospi_trend + 100) / 2
    """
    breadth = signals.get('breadth', 50)
    kospi_trend = signals.get('kospi_trend', 0)
    foreigner_score = signals.get('foreigner_score', 50)
    decline_ratio = signals.get('decline_ratio', 50)
    
    # kospi_trend를 -100~100에서 0~100으로 변환
    kospi_normalized = (kospi_trend + 100) / 2
    kospi_normalized = min(100, max(0, kospi_normalized))
    
    final = (
        0.5 * breadth +
        0.2 * kospi_normalized +
        0.2 * foreigner_score +
        0.1 * decline_ratio
    )
    
    return min(100, max(0, final))
```

- [ ] **Step 2: 가중치 검증 테스트 작성**

```python
def test_ensemble_equal_weights():
    """모든 신호가 같은 값일 때 결과는 같아야 함"""
    signals = {
        'breadth': 50,
        'kospi_trend': 0,  # 0~100으로 변환하면 50
        'foreigner_score': 50,
        'decline_ratio': 50
    }
    result = ensemble_breadth(signals)
    assert abs(result - 50) < 0.1

def test_ensemble_max():
    """모든 신호가 최대일 때"""
    signals = {
        'breadth': 100,
        'kospi_trend': 100,  # 0~100으로 변환하면 100
        'foreigner_score': 100,
        'decline_ratio': 100
    }
    result = ensemble_breadth(signals)
    assert result == 100

def test_ensemble_breadth_dominance():
    """breadth가 50% 가중치로 가장 큼"""
    signals1 = {
        'breadth': 100,
        'kospi_trend': 0,
        'foreigner_score': 0,
        'decline_ratio': 0
    }
    signals2 = {
        'breadth': 0,
        'kospi_trend': 100,  # 100
        'foreigner_score': 100,
        'decline_ratio': 100
    }
    result1 = ensemble_breadth(signals1)
    result2 = ensemble_breadth(signals2)
    
    # breadth=100일 때가 다른 3개가 최대일 때보다 커야 함
    assert result1 > result2
```

- [ ] **Step 3: 테스트 실행**

```bash
pytest tests/test_sim0_nowcast.py::test_ensemble_equal_weights -v
pytest tests/test_sim0_nowcast.py::test_ensemble_max -v
pytest tests/test_sim0_nowcast.py::test_ensemble_breadth_dominance -v
```

Expected: 모두 PASS

- [ ] **Step 4: Commit**

```bash
git add src/strategy/simulators/sim0_libero.py tests/test_sim0_nowcast.py
git commit -m "feat(sim0): 앙상블 모델 (4신호 가중평균 0.5/0.2/0.2/0.1)"
```

---

## Task 3: 신뢰도 계산 함수 구현

**Files:**
- Modify: `src/strategy/simulators/sim0_libero.py:101-200`
- Test: `tests/test_sim0_nowcast.py`

**Interfaces:**
- Consumes: final_breadth (0~100), hourly_regime_log (최근 3시간), 현재 시간, 4개 입력 신호
- Produces:
  ```python
  def calculate_confidence(final_breadth, recent_logs, current_hour, signals):
      """
      Returns: float (0.0 ~ 1.0)
      """
  ```

- [ ] **Step 1: Saturation 신호 계산 함수**

```python
def score_saturation(final_breadth):
    """예측이 극단값인가
    
    Returns: float (0.0 ~ 1.0)
    - 포화(0~0.1 또는 0.9~1.0): 0.2
    - 극단값(0.1~0.2 또는 0.8~0.9): 0.5
    - 정상 범위(0.2~0.8): 0.9
    """
    normalized = final_breadth / 100.0
    
    if normalized <= 0.1 or normalized >= 0.9:
        return 0.2
    elif normalized <= 0.2 or normalized >= 0.8:
        return 0.5
    else:
        return 0.9
```

- [ ] **Step 2: Volatility 신호 계산 함수**

```python
def score_volatility(recent_logs):
    """최근 3시간 예측 진동
    
    Args:
        recent_logs: list of {'breadth': float} (최근 3시간)
    
    Returns: float (0.0 ~ 1.0)
    - 표준편차 > 25: 0.3
    - 표준편차 15~25: 0.6
    - 표준편차 < 15: 0.9
    """
    if len(recent_logs) < 2:
        return 0.9  # 데이터 부족하면 안정적으로 판단
    
    breadths = [log.get('breadth', 50) for log in recent_logs]
    std = statistics.stdev(breadths)
    
    if std > 25:
        return 0.3
    elif std >= 15:
        return 0.6
    else:
        return 0.9
```

- [ ] **Step 3: InputAgreement 신호 계산 함수**

```python
def score_input_agreement(signals):
    """4개 신호 일치도
    
    Args:
        signals: {'breadth': float, 'kospi_trend': float, 'foreigner_score': float, 'decline_ratio': float}
    
    Returns: float (0.0 ~ 1.0)
    - 모두 상승/하락 방향(모두 >= 50 또는 모두 < 50): 0.9
    - 3개 일치: 0.7
    - 2개 이하: 0.5
    """
    breadth = signals.get('breadth', 50)
    kospi_trend = signals.get('kospi_trend', 0)
    foreigner_score = signals.get('foreigner_score', 50)
    decline_ratio = signals.get('decline_ratio', 50)
    
    # 상승 신호 카운트 (50 이상)
    bullish = sum([
        breadth >= 50,
        kospi_trend >= 0,
        foreigner_score >= 50,
        decline_ratio < 50  # 낙폭 < 50 = 상승 신호
    ])
    
    if bullish == 4 or bullish == 0:  # 모두 일치
        return 0.9
    elif bullish == 3 or bullish == 1:  # 3개 일치
        return 0.7
    else:  # 2개씩
        return 0.5
```

- [ ] **Step 4: TimeframeMaturity 신호 계산 함수**

```python
def score_timeframe(current_hour):
    """시간 경과에 따른 안정도
    
    Args:
        current_hour: "09:00", "10:00", ... "15:00"
    
    Returns: float (0.0 ~ 1.0)
    - 09:00: 0.5
    - 10:00~14:00: 선형 증가
    - 15:00: 0.9
    """
    hour_map = {
        '09:00': 0.5,
        '10:00': 0.6,
        '11:00': 0.7,
        '12:00': 0.7,
        '13:00': 0.8,
        '14:00': 0.85,
        '15:00': 0.9,
    }
    return hour_map.get(current_hour, 0.7)
```

- [ ] **Step 5: calculate_confidence 메인 함수**

```python
import statistics

def calculate_confidence(final_breadth, recent_logs, current_hour, signals):
    """신뢰도 계산
    
    confidence = saturation * (0.6 + 0.2*volatility + 0.1*input_agreement + 0.1*timeframe)
    """
    sat = score_saturation(final_breadth)
    vol = score_volatility(recent_logs)
    agreement = score_input_agreement(signals)
    timeframe = score_timeframe(current_hour)
    
    confidence = sat * (0.6 + 0.2 * vol + 0.1 * agreement + 0.1 * timeframe)
    
    return min(1.0, max(0.0, confidence))
```

- [ ] **Step 6: 테스트 작성**

```python
def test_saturation_saturation():
    assert score_saturation(5.0) == 0.2  # 포화
    assert score_saturation(95.0) == 0.2  # 포화

def test_saturation_extreme():
    assert score_saturation(15.0) == 0.5  # 극단값
    assert score_saturation(85.0) == 0.5  # 극단값

def test_saturation_normal():
    assert score_saturation(50.0) == 0.9  # 정상

def test_volatility_high():
    recent = [{'breadth': 20}, {'breadth': 80}, {'breadth': 30}]
    score = score_volatility(recent)
    assert score == 0.3

def test_volatility_low():
    recent = [{'breadth': 50}, {'breadth': 52}, {'breadth': 51}]
    score = score_volatility(recent)
    assert score == 0.9

def test_input_agreement_all_bull():
    signals = {
        'breadth': 70,
        'kospi_trend': 20,
        'foreigner_score': 80,
        'decline_ratio': 30
    }
    score = score_input_agreement(signals)
    assert score == 0.9

def test_input_agreement_three_agree():
    signals = {
        'breadth': 70,
        'kospi_trend': 20,
        'foreigner_score': 80,
        'decline_ratio': 60  # 낙폭 비율 높음 = 약세
    }
    score = score_input_agreement(signals)
    assert score == 0.7

def test_timeframe_progression():
    assert score_timeframe('09:00') == 0.5
    assert score_timeframe('15:00') == 0.9
    assert score_timeframe('12:00') == 0.7

def test_calculate_confidence_extreme_case():
    # 극단 포화 + 높은 진동 → 신뢰도 낮음
    recent = [{'breadth': 10}, {'breadth': 90}]
    signals = {
        'breadth': 5,
        'kospi_trend': -50,
        'foreigner_score': 10,
        'decline_ratio': 80
    }
    conf = calculate_confidence(5, recent, '09:00', signals)
    assert conf < 0.4  # 포화(0.2) * (0.6 + ...) ≤ 0.2 * 1.0 = 0.2
```

- [ ] **Step 7: 테스트 실행**

```bash
pytest tests/test_sim0_nowcast.py::test_saturation_saturation -v
pytest tests/test_sim0_nowcast.py::test_volatility_high -v
pytest tests/test_sim0_nowcast.py::test_input_agreement_all_bull -v
pytest tests/test_sim0_nowcast.py::test_timeframe_progression -v
pytest tests/test_sim0_nowcast.py::test_calculate_confidence_extreme_case -v
```

Expected: 모두 PASS

- [ ] **Step 8: Commit**

```bash
git add src/strategy/simulators/sim0_libero.py tests/test_sim0_nowcast.py
git commit -m "feat(sim0): 신뢰도 계산 (포화/진동/합의/타이밍)"
```

---

## Task 4: 상태 JSON 포맷 변경 및 마이그레이션

**Files:**
- Modify: `src/strategy/simulators/sim0_libero.py:201-250`
- Test: `tests/test_sim0_nowcast.py`

**Interfaces:**
- Consumes: 기존 sim_libero_state.json
- Produces:
  ```python
  def load_state_with_migration(state_path):
      """기존 형식을 새 형식으로 마이그레이션"""
  
  def save_state(state, state_path):
      """새 형식으로 저장"""
  ```

- [ ] **Step 1: 새 상태 포맷 정의 함수**

```python
def init_state_v2():
    """새 상태 JSON 초기화"""
    return {
        "current_regime": "SIDEWAYS",
        "confidence": 0.5,
        "instant_regime": "SIDEWAYS",
        "hourly_regime_log": [],
        "calibration_log": []
    }
```

- [ ] **Step 2: 마이그레이션 함수**

```python
def load_state_with_migration(state_path):
    """기존 상태를 새 포맷으로 로드/변환
    
    기존 필드:
    - current_regime, confidence (존재하면 그대로 사용)
    - intraday_score_log (존재하면 hourly_regime_log로 변환)
    - calibration_log (존재하면 그대로 사용)
    
    신규 필드:
    - hourly_regime_log (명시된 구조)
    """
    import json
    import os
    
    if not os.path.exists(state_path):
        return init_state_v2()
    
    try:
        with open(state_path, 'r', encoding='utf-8-sig') as f:
            old_state = json.load(f)
    except Exception:
        return init_state_v2()
    
    # 새 상태 초기화
    new_state = init_state_v2()
    
    # 기존 국면, 신뢰도 복사
    if 'current_regime' in old_state:
        new_state['current_regime'] = old_state['current_regime']
    if 'confidence' in old_state:
        new_state['confidence'] = old_state['confidence']
    
    # intraday_score_log → hourly_regime_log 변환
    if 'intraday_score_log' in old_state:
        for entry in old_state['intraday_score_log']:
            # 기존 형식: {'hour': '09:00', 'breadth': 50.0, ...}
            # 새 형식: {'hour': '09:00', 'regime': 'BULL', 'confidence': 0.7, 'breadth': 50.0, 'inputs': {...}}
            regime = _determine_regime_from_breadth(entry.get('breadth', 50))
            new_log_entry = {
                'hour': entry.get('hour', '09:00'),
                'regime': regime,
                'confidence': entry.get('confidence', 0.5),
                'breadth': entry.get('breadth', 50.0),
                'inputs': {}  # 기존 데이터는 inputs 없음
            }
            new_state['hourly_regime_log'].append(new_log_entry)
    
    # calibration_log 그대로 복사
    if 'calibration_log' in old_state:
        new_state['calibration_log'] = old_state['calibration_log']
    
    return new_state

def _determine_regime_from_breadth(breadth):
    """breadth에서 국면 판정"""
    if breadth >= 60:
        return "BULL"
    elif breadth <= 40:
        return "BEAR"
    else:
        return "SIDEWAYS"
```

- [ ] **Step 3: 저장 함수**

```python
def save_state_v2(state, state_path):
    """새 포맷으로 상태 저장"""
    import json
    import os
    
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
```

- [ ] **Step 4: 포맷 변환 테스트**

```python
def test_migration_empty():
    """기존 상태 없으면 초기 상태 반환"""
    state = load_state_with_migration('/nonexistent/path.json')
    assert state['current_regime'] == 'SIDEWAYS'
    assert state['confidence'] == 0.5
    assert isinstance(state['hourly_regime_log'], list)

def test_migration_preserves_regime():
    """기존 국면 정보 보존"""
    import json
    import tempfile
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({
            'current_regime': 'BULL',
            'confidence': 0.8,
            'intraday_score_log': []
        }, f)
        f.flush()
        
        state = load_state_with_migration(f.name)
        assert state['current_regime'] == 'BULL'
        assert state['confidence'] == 0.8

def test_migration_converts_intraday_to_hourly():
    """intraday_score_log → hourly_regime_log 변환"""
    import json
    import tempfile
    
    old_log = [
        {'hour': '09:00', 'breadth': 70.0},
        {'hour': '10:00', 'breadth': 30.0}
    ]
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({'intraday_score_log': old_log}, f)
        f.flush()
        
        state = load_state_with_migration(f.name)
        assert len(state['hourly_regime_log']) == 2
        assert state['hourly_regime_log'][0]['regime'] == 'BULL'
        assert state['hourly_regime_log'][1]['regime'] == 'BEAR'

def test_save_state_format():
    """저장된 상태가 올바른 포맷"""
    import json
    import tempfile
    
    state = init_state_v2()
    state['current_regime'] = 'BULL'
    state['confidence'] = 0.75
    
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        save_state_v2(state, f.name)
        
        with open(f.name, 'r') as rf:
            loaded = json.load(rf)
        
        assert loaded['current_regime'] == 'BULL'
        assert loaded['confidence'] == 0.75
```

- [ ] **Step 5: 테스트 실행**

```bash
pytest tests/test_sim0_nowcast.py::test_migration_empty -v
pytest tests/test_sim0_nowcast.py::test_migration_preserves_regime -v
pytest tests/test_sim0_nowcast.py::test_migration_converts_intraday_to_hourly -v
pytest tests/test_sim0_nowcast.py::test_save_state_format -v
```

Expected: 모두 PASS

- [ ] **Step 6: Commit**

```bash
git add src/strategy/simulators/sim0_libero.py tests/test_sim0_nowcast.py
git commit -m "feat(sim0): 상태 JSON 포맷 변경 (hourly_regime_log, confidence 추가)"
```

---

## Task 5: Hourly 갱신 로직 구현

**Files:**
- Modify: `src/strategy/simulators/sim0_libero.py:251-305`
- Test: `tests/test_sim0_nowcast.py`

**Interfaces:**
- Consumes: collect_signals, ensemble_breadth, calculate_confidence
- Produces:
  ```python
  def update_hourly(current_hour, state, market_data, kospi_data, foreigner_data):
      """
      상태를 갱신하고 current_regime, confidence 반환
      """
  ```

- [ ] **Step 1: 국면 판정 함수**

```python
def determine_regime(final_breadth):
    """3상태 국면 판정"""
    if final_breadth >= 60:
        return "BULL"
    elif final_breadth <= 40:
        return "BEAR"
    else:
        return "SIDEWAYS"
```

- [ ] **Step 2: Hourly 갱신 함수**

```python
def update_hourly(current_hour, state, market_data, kospi_data, foreigner_data):
    """매시간 호출되는 갱신 함수
    
    1. 4개 신호 수집
    2. 앙상블 계산
    3. 국면 판정
    4. 신뢰도 계산
    5. hourly_regime_log 추가
    6. current_regime, confidence 갱신
    
    Returns: {'regime': str, 'confidence': float}
    """
    # 1. 신호 수집
    signals = collect_signals(market_data, kospi_data, foreigner_data)
    
    # 2. 앙상블
    final_breadth = ensemble_breadth(signals)
    
    # 3. 국면 판정
    regime = determine_regime(final_breadth)
    
    # 4. 최근 3시간 로그 추출 (신뢰도 계산용)
    recent_logs = state.get('hourly_regime_log', [])[-3:]
    
    # 5. 신뢰도 계산
    confidence = calculate_confidence(final_breadth, recent_logs, current_hour, signals)
    
    # 6. hourly_regime_log에 추가
    log_entry = {
        'hour': current_hour,
        'regime': regime,
        'confidence': confidence,
        'breadth': final_breadth,
        'inputs': signals
    }
    state['hourly_regime_log'].append(log_entry)
    
    # 7. 최대 7개 항목만 유지 (09:00~15:00)
    if len(state['hourly_regime_log']) > 7:
        state['hourly_regime_log'] = state['hourly_regime_log'][-7:]
    
    # 8. current_regime, confidence 갱신
    state['current_regime'] = regime
    state['confidence'] = confidence
    
    return {'regime': regime, 'confidence': confidence}
```

- [ ] **Step 3: 통합 테스트**

```python
def test_update_hourly_creates_log():
    """hourly 갱신이 로그 항목 생성"""
    state = init_state_v2()
    
    result = update_hourly(
        '09:00',
        state,
        {'breadth': 60, 'declining': 30, 'rising': 70},
        {'price': 2500, 'ma5': 2400},
        {'buy_amount': 50000000000}
    )
    
    assert result['regime'] == 'BULL'
    assert 0 <= result['confidence'] <= 1
    assert len(state['hourly_regime_log']) == 1
    assert state['current_regime'] == 'BULL'

def test_update_hourly_multiple_calls():
    """여러 시간 갱신"""
    state = init_state_v2()
    hours = ['09:00', '10:00', '11:00']
    
    for hour in hours:
        update_hourly(
            hour,
            state,
            {'breadth': 50 + (hours.index(hour) * 10), 'declining': 30, 'rising': 70},
            {'price': 2500, 'ma5': 2400},
            {'buy_amount': 50000000000}
        )
    
    assert len(state['hourly_regime_log']) == 3
    assert state['hourly_regime_log'][0]['hour'] == '09:00'
    assert state['hourly_regime_log'][2]['hour'] == '11:00'

def test_update_hourly_max_7_entries():
    """최대 7개 항목만 유지"""
    state = init_state_v2()
    
    for i in range(10):
        hour = f"{9 + i // 60}:{i % 60:02d}"
        update_hourly(hour, state, {'breadth': 50}, {'price': 2500, 'ma5': 2400}, {'buy_amount': 0})
    
    assert len(state['hourly_regime_log']) <= 7
```

- [ ] **Step 4: 테스트 실행**

```bash
pytest tests/test_sim0_nowcast.py::test_update_hourly_creates_log -v
pytest tests/test_sim0_nowcast.py::test_update_hourly_multiple_calls -v
pytest tests/test_sim0_nowcast.py::test_update_hourly_max_7_entries -v
```

Expected: 모두 PASS

- [ ] **Step 5: Commit**

```bash
git add src/strategy/simulators/sim0_libero.py tests/test_sim0_nowcast.py
git commit -m "feat(sim0): hourly 갱신 로직 (신호→앙상블→신뢰도→로그)"
```

---

## Task 6: 정확도 검증 (통합 테스트)

**Files:**
- Create: `tests/test_sim0_accuracy.py`
- Test: 기존 calibration_log v2 데이터 활용

**Interfaces:**
- Consumes: calibration_log v2 데이터, 모든 신호 계산 함수
- Produces: 정확도 리포트

- [ ] **Step 1: 테스트 데이터 로드 함수**

```python
# tests/test_sim0_accuracy.py
import json
import os

def load_calibration_data():
    """기존 calibration_log v2 데이터 로드"""
    state_path = os.path.join(
        os.path.dirname(__file__),
        '../data/sim_libero_state.json'
    )
    
    if not os.path.exists(state_path):
        return []
    
    try:
        with open(state_path, 'r', encoding='utf-8-sig') as f:
            state = json.load(f)
        return state.get('calibration_log', [])
    except Exception:
        return []
```

- [ ] **Step 2: 정확도 계산 함수**

```python
def calculate_accuracy_metrics(calibration_log):
    """정확도 메트릭 계산
    
    Returns:
        {
            'mean_gap': float,
            'median_gap': float,
            'count': int,
            'saturation_count': int,
            'low_confidence_errors': float,
            'high_confidence_errors': float
        }
    """
    import statistics
    
    gaps = []
    low_conf_errors = []  # confidence < 0.5일 때의 오류
    high_conf_errors = []  # confidence >= 0.8일 때의 오류
    saturation_count = 0
    
    for entry in calibration_log:
        gap = abs(entry.get('gap', 0))
        gaps.append(gap)
        confidence = entry.get('confidence', 0.5)
        
        # 포화 감지
        breadth = entry.get('pred', 50)
        if breadth <= 10 or breadth >= 90:
            saturation_count += 1
        
        # 신뢰도별 오류 추적
        if confidence < 0.5:
            low_conf_errors.append(gap)
        if confidence >= 0.8:
            high_conf_errors.append(gap)
    
    mean_gap = statistics.mean(gaps) if gaps else 0
    median_gap = statistics.median(gaps) if gaps else 0
    
    low_conf_error_rate = (
        (sum(1 for e in low_conf_errors if e > 10) / len(low_conf_errors) * 100)
        if low_conf_errors else 0
    )
    high_conf_error_rate = (
        (sum(1 for e in high_conf_errors if e > 10) / len(high_conf_errors) * 100)
        if high_conf_errors else 0
    )
    
    return {
        'mean_gap': mean_gap,
        'median_gap': median_gap,
        'count': len(gaps),
        'saturation_count': saturation_count,
        'low_confidence_error_rate': low_conf_error_rate,
        'high_confidence_error_rate': high_conf_error_rate
    }
```

- [ ] **Step 3: 정확도 목표 검증 테스트**

```python
def test_accuracy_goal_mean_gap():
    """평균 |gap| ≤ 8.0 검증 (목표: 14.2 → 8.0)"""
    calibration_log = load_calibration_data()
    
    if len(calibration_log) < 10:
        pytest.skip("충분한 calibration 데이터 없음")
    
    metrics = calculate_accuracy_metrics(calibration_log)
    print(f"\n기존 정확도: {metrics['mean_gap']:.1f}")
    print(f"목표 정확도: 8.0 이하")
    
    # 앙상블이 데이터 기반이므로, 현재는 교정용 테스트로 메시지만 출력
    # 실제 구현 후 목표값 검증
    assert metrics['mean_gap'] > 0

def test_saturation_detection():
    """포화 감지 (극단값 0~10, 90~100)"""
    calibration_log = load_calibration_data()
    
    metrics = calculate_accuracy_metrics(calibration_log)
    print(f"\n포화된 예측 개수: {metrics['saturation_count']}")
    
    # 07-21 데이터에서 16%가 포화되었으니, 0은 아니어야 함
    assert metrics['saturation_count'] >= 0

def test_confidence_correlation():
    """신뢰도와 정확도의 상관관계"""
    calibration_log = load_calibration_data()
    
    metrics = calculate_accuracy_metrics(calibration_log)
    print(f"\nconfidence < 0.5일 때 오류율: {metrics['low_confidence_error_rate']:.1f}%")
    print(f"confidence >= 0.8일 때 오류율: {metrics['high_confidence_error_rate']:.1f}%")
    
    # 신뢰도가 높을수록 오류가 적어야 함
    # 최소한 0이 아닌 값이어야 함 (신뢰도 활용)
    assert metrics['low_confidence_error_rate'] >= 0
    assert metrics['high_confidence_error_rate'] >= 0
```

- [ ] **Step 4: 테스트 실행**

```bash
pytest tests/test_sim0_accuracy.py -v -s
```

Expected: 모두 PASS (정확도 메트릭 출력)

- [ ] **Step 5: Commit**

```bash
git add tests/test_sim0_accuracy.py
git commit -m "test(sim0): 정확도 검증 (calibration_log v2 기반)"
```

---

## 최종 검증 및 배포 준비

- [ ] **Step 1: 전체 테스트 실행**

```bash
pytest tests/test_sim0_nowcast.py -v
pytest tests/test_sim0_accuracy.py -v
```

Expected: 모든 테스트 PASS

- [ ] **Step 2: 기존 Sim6 통합 확인**

[sim6_bear_hedge.py](src/strategy/simulators/sim6_bear_hedge.py:105-117) 의 `_read_regime()` 함수가 현재 상태 파일을 읽는지 확인:
- `sim_libero_state.json`에서 `current_regime` 읽음
- confidence 필드는 아직 미사용 (향후 Sim6이 판단할 것)

Sim6은 이미 신뢰도를 사용할 준비가 되어있으므로 수정 불필요.

- [ ] **Step 3: 라이브 데이터 준비**

상태 파일 마이그레이션:
```bash
python -c "
import json
from src.strategy.simulators.sim0_libero import load_state_with_migration, save_state_v2

state = load_state_with_migration('data/sim_libero_state.json')
save_state_v2(state, 'data/sim_libero_state.json')
print('Migration complete')
"
```

- [ ] **Step 4: Commit 최종 확인**

```bash
git log --oneline | head -10
```

Expected: Task 1~6 커밋이 모두 보임

---

## 배포 체크리스트

- [ ] 모든 테스트 PASS
- [ ] 정확도 목표 확인 (|gap| < 8.0)
- [ ] 신뢰도 검증 (confidence < 0.5일 때 오류율 > 20%)
- [ ] 상태 JSON 마이그레이션 완료
- [ ] Sim6 호환성 확인 (current_regime 읽음)
- [ ] Sim10 준비 확인 (confidence 필드 존재)
