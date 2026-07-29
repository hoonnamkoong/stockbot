# Sim1 프로그램 매매 파리티 — 이력을 페이퍼에서 승계한다

2026-07-29 · Phase 2 선행 과제

## 문제

`program_trader._make_adapter`가 `sim.state`를 실계좌 스냅샷으로 갈아끼운다. 그 합성
state에는 `psych_prev_day`·`psych_snapshot`이 없다. 따라서 Sim1이 `selected_sim`으로
선택되면 프로그램 런은 **항상** `hist_missing=1`, `d_sov=d_hype=accel=0`이다.

지금은 `ignition4`가 진입에 안 쓰이므로 잘못된 매매는 나지 않는다. 그러나 Phase 2에서
`accel>0` 게이트가 진입식에 들어가는 순간 **프로그램 Sim1은 영구 무매매**가 된다.
조용히 안 사는 것은 잘못 사는 것만큼 나쁘다. "심 선택 = 실전 정확히 동일 동작"이 깨진다.

부수 문제: `run()`이 두 경로 모두에서 `sim_diag.append('sim1', diags)`를 부른다.
Sim1이 선택되면 같은 사이클·같은 종목이 한 CSV에 2행씩 들어가 분포 분석이 이중계상된다.

## 왜 "그냥 페이퍼 state를 읽는다"가 안 되는가

`trade_engine`은 6단계에서 페이퍼 심을 전부 돌린 **직후** 7단계에서 프로그램 매매를
부른다. 페이퍼 Sim1은 이미 `psych_snapshot`을 **이번 런의 z**로 덮어쓰고 저장했다.
프로그램이 그 파일을 읽어 `last_run`으로 쓰면 `accel = z − 같은 z = 0`이 전 종목 항상
0이다. 문제를 해결하는 대신 다른 얼굴로 재현한다.

`market_index_healthy`는 같은 패턴으로 승계해도 안전하다 — 그 값은 런 중에 갱신되지
않기 때문이다. 이력 슬롯은 갱신된다. **런 중에 덮어써지는 값은 승계 대상이 아니다.**

## 설계

페이퍼가 이번 런에 **실제로 소비한** 이력 쌍을 state에 남기고, 프로그램이 그것을 주입한다.

### 1. sim1 — 소비한 쌍 저장

`run()`은 이미 `resolve_history`로 `(prev_day, last_run)`을 만들어 `view`에 넣는다.
`prev_day`만 저장하고 `last_run`은 버리던 것을 둘 다 저장한다.

```python
self.state['psych_prev_day'] = prev_day
self.state['psych_last_run'] = last_run      # 프로그램 경로 승계용
if snapshot.get('z'):
    self.state['psych_snapshot'] = snapshot
```

새 계산은 없다. 페이퍼 자신은 이 값을 읽지 않는다.

### 2. program_trader — 스냅샷에 주입

`market_index_healthy`를 읽는 자리에서 페이퍼 state를 한 번 잡아두고, 8단계 `snapshot`
딕셔너리에 세 키를 더한다.

```python
'psych_prev_day': paper_state.get('psych_prev_day'),
'psych_snapshot': paper_state.get('psych_last_run'),
'diag_key': f'{sim_id}_program',
```

`psych_last_run`을 `psych_snapshot` 슬롯에 넣는 이유: 프로그램 쪽 `run()`도 다시
`resolve_history`를 통과하는데, 그 함수는 이 입력에 **멱등**이다.

```
resolve_history(prev_day, snapshot, today):
    if snapshot and snapshot['date'] != today: return snapshot, None   # 승격
    return prev_day, snapshot                                          # 그대로
```

소비된 `last_run`은 정의상 `None`이거나 오늘 날짜다(페이퍼의 `resolve_history`가 이미
승격을 끝냈으므로). 두 경우 다 두 번째 분기로 떨어져 입력이 그대로 반환된다. 재승격은
일어날 수 없다.

### 3. 진단 키

```python
sim_diag.append(self.state.get('diag_key', 'sim1'), diags)
```

`sim_diag.month_path(sim)`이 sim 키로 파일명을 만들고 `sim` 컬럼도 그 값으로 채운다.
페이퍼는 키가 없어 `'sim1'`(현행 그대로), 프로그램은 `'sim1_program'` →
`data/sim1_program_diag_YYYY-MM.csv`. **컬럼은 변하지 않으므로 헤더 회전이 없고 07-29
데이터가 갈라지지 않는다.**

### 경계 조건

- `sim.state`가 dict가 아니면(인스턴스화 실패 등) 세 키는 넣지 않는다. 현행
  `market_index_healthy`와 같은 방어를 공유한다. 이 경우 프로그램은 지금과 동일하게
  `hist_missing=1`로 동작한다 — 현행보다 나빠지지 않는다.
- 페이퍼 Sim1이 이번 사이클에 돌지 않았다면(매니페스트 비활성 등) `psych_last_run`은
  이전 사이클 값이다. 그때는 페이퍼도 안 돌았으므로 비교 대상 자체가 없다.

### 기각한 대안

- **원장 캐리(`cooldown_codes` 패턴)** — 프로그램이 자체 이력 체인을 갖는다. 프로그램은
  15분 중복가드, 파이프라인은 약 10분 주기(07-29 실측: 09:02→09:12→09:23→09:32)라
  프로그램은 대체로 한 사이클씩 건너뛴다. `accel`이 페이퍼의 10분 델타 대신 20분 델타가
  되어 파리티가 근사치로 떨어진다. 원장도 15~20KB 커진다.
- **페이퍼 state 직접 승계** — 위 "왜 안 되는가" 참조. `accel` 항상 0.

## 검증

- **멱등성(단위)** — `resolve_history(prev_day, consumed_last_run, today)`가 입력을 그대로
  반환한다. 3케이스: `last_run`이 `None` / 오늘 날짜 / `prev_day`만 있음.
- **파리티(통합)** — 같은 후보·같은 시각으로 페이퍼 심과 프로그램 어댑터를 각각 돌려
  `diags`의 `d_sov`·`d_hype`·`accel`·`accel_d1`·`hist_missing`·`ignition4`가 **전 종목
  일치**한다. 이것이 파리티의 실제 증명이다.
- **진단 분리** — 프로그램 어댑터 실행 후 `data/sim1_program_diag_*.csv`가 생기고
  `data/sim1_diag_*.csv`에는 행이 추가되지 않는다.
- **회귀** — `scratch/test_sim1_history.py`, `scratch/test_sim_run.py` 기존 PASS 유지.

## 범위 밖

`ignition4`를 진입식에 넣는 것은 Phase 2다. 이 변경 후에도 두 경로 모두 3항 `ignition`으로
매매한다 — **매매 동작은 바뀌지 않고 기록만 정확해진다.** 그래야 Phase 2에서 진입식 교체의
효과를 분리해 볼 수 있다.

Sim1이 아닌 다른 심에는 영향이 없다. `diag_key`는 Sim1만 읽고, 이력 슬롯도 Sim1만 쓴다.
