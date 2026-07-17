# 휴장일 게이트 재설계 — KIS 달력 기반 fail-closed 판정

- 날짜: 2026-07-17
- 대상: 휴장일 스크래퍼 차단 (`is_trading_day`)
- 관련 원칙: [[no-fabricated-financial-values]] ("정상적으로 빔"과 "실패"를 구분), [[program-trading-parity-mandate]] (fail-closed)

## 문제

2026-07-17(공휴일) 휴장일인데 스크래퍼가 계속 돌고 텔레그램이 발송됐다.

`PipelineContext.is_trading_day()`(`src/pipeline/context.py`)의 3단 판정이 모두 샌다.

### 1차 — KIS API가 없는 필드를 읽는다

`_check_trading_day_via_kis()`가 `chk-holiday`(TR `CTCA0903R`) 응답에서
`bzdy_tp_cd`를 먼저 읽는다. **이 필드는 응답 스펙에 없다.** 실제 필드는 6개다.

| 필드 | 의미 |
|---|---|
| `bass_dt` / `wday_dvsn_cd` | 기준일자 / 요일구분코드 |
| `bzdy_yn` | 영업일여부 (금융기관 업무일) |
| `tr_day_yn` | 거래일여부 |
| **`opnd_yn`** | **개장일여부 — 휴장 판정의 정답 필드** |
| `setl_day_yn` | 결제일여부 |

`bzdy_tp_cd`는 항상 빈 문자열이라 `tr_day_yn`으로 폴백하고,
정작 주식시장 개장 여부인 `opnd_yn`은 한 번도 읽지 않는다.

### 2차 — holidays 패키지가 오늘을 모른다

실측 확인:

```
holidays 0.86
2026-07-17 -> None        # 오늘 (공휴일인데 목록에 없음)
```

신규 지정·임시공휴일은 패키지 폴백으로 구조적으로 못 잡는다.

### 3차 — 판정 실패가 "개장"으로 통과된다

`is_trading_day()` 말미가 `return True`다. 앞의 두 단이 실패하면 조용히
거래일로 간주되어 파이프라인이 끝까지 돈다. **판정 불가와 개장이 같은 값**인
것이 문제의 뿌리다.

## 방식 결정 (사용자 확정)

- **판정 순서**: 토큰을 **먼저** 발급하고 `chk-holiday`로 판정한다.
  (토큰 없이는 조회 자체가 불가능하므로 "휴장 체크 → 토큰 발급" 순서는 성립하지 않음.
  휴장일에도 토큰 1회 발급은 감수한다.)
- **차단 지점**: 스크래퍼 내부 게이트. dispatch는 되지만 orchestrator가 즉시 종료.
- **실패 처리**: **fail-closed**. 판정 불가 시 중단 + 경고 텔레그램.
- **재조회 계층**: 달력에 오늘이 없으면 스크래퍼가 직접 `chk-holiday` 조회.
  (07시 런 1회 실패가 하루 종일 정지로 번지지 않게)
- **holidays 패키지**: **완전 제거**. 판정 소스를 KIS 하나로 통일.

## 아키텍처

### 핵심 아이디어

`chk-holiday`는 `BASS_DT` 하루가 아니라 **약 3개월치 달력을 한 번에 반환**한다.
응답을 통째로 저장하면 재조회가 거의 일어나지 않고, 07시 런이 하루 통째로
실패해도 **어제 저장된 달력에 이미 오늘이 들어있어** fail-closed가 걸리지 않는다.
저장 비용은 응답을 필터링하지 않는 것뿐이다.

### 데이터 흐름

```
07시  token_refresh.yml
        ├─ token_manager.py        → 토큰 발급 (기존)
        └─ market_calendar 갱신     → chk-holiday(BASS_DT=오늘) 조회
                                   → data/market_calendar.json (3개월치)
                                   → db-data push

09시+ scraper.yml
        └─ orchestrator.is_trading_day()
             1. 주말             → False (API 호출 없음)
             2. 달력에 오늘 키 있음 → 그 값 사용 (API 호출 없음)
             3. 오늘 키 없음      → chk-holiday 직접 조회 + 달력 갱신
             4. 조회 실패         → None → 중단 + 경고 텔레그램
```

**신선도(staleness) 판정은 두지 않는다.** 07시 런이 매일 달력 전체를
새로 받으므로 저장분은 항상 최신이고, 임시공휴일 지정도 발표 후 다음 07시
런에 반영된다. 스크래퍼는 `days`에 **오늘 키가 있는지만** 보면 된다.
`updated_at`은 사람이 읽는 디버깅용 메타데이터이지 판정에 쓰지 않는다.

`data/*.json`은 scraper.yml의 `Deploy Data to db-data branch` 스텝이 이미
자동 배포하고, 스크래퍼는 시작 시 `git checkout db-data -- data/`로 읽어온다.
별도 배관은 필요 없다.

### 저장 형식 — `data/market_calendar.json`

판정에 필요한 `opnd_yn`만 남긴다.

```json
{
  "updated_at": "2026-07-17T07:00:12+09:00",
  "days": { "20260717": "N", "20260720": "Y", "20260721": "Y" }
}
```

민감정보가 아니므로 public db-data에 배포해도 무방하다
(scraper.yml 배포 제외 목록에 추가하지 않는다).

### 신규 모듈 — `src/market_calendar.py`

순수 로직과 I/O를 분리해 테스트 가능하게 둔다.

- `parse_calendar(api_response: dict) -> dict[str, str]`
  — 응답에서 `bass_dt → opnd_yn` 맵 추출. 순수 함수.
- `fetch_calendar(token, app_key, app_secret, base_date) -> dict[str, str]`
  — `chk-holiday` 호출 + `parse_calendar`. 실패 시 예외.
- `load_calendar(path) -> dict | None` / `save_calendar(path, days) -> None`
  — 파일 I/O.
- `lookup(days: dict, yyyymmdd: str) -> bool | None`
  — `"Y"` → True, `"N"` → False, 키 없음 → None. 순수 함수.

### `is_trading_day()` 반환값 변경

`True`(개장) / `False`(휴장) / **`None`(판정 불가)** 3값으로 바꾼다.
판정 불가를 개장과 구분하는 것이 이번 변경의 핵심이다.

호출부 영향:

- `orchestrator.py`의 휴장 게이트: `None`이면 경고 발송 후 종료.
- `is_market_hours()`: 현재 `return (self.is_trading_day() and ...)` 형태라
  `None`이 그대로 **반환값으로 새어나간다** (`None and X` → `None`).
  `-> bool` 타입 힌트를 어기므로 `bool(...)`로 감싼다.
- `is_after_market_close()`: 말미가 `return self.is_trading_day()`라
  마찬가지로 `None`이 샌다. `is True` 비교로 바꾼다.

두 메서드 모두 실거래 게이트(`trade_engine.allow_buy`, `program_trader`)이므로
판정 불가 시 **닫히는** 방향이어야 한다. truthy 평가상으론 이미 그렇게
동작하지만, 타입을 명시적으로 좁혀 의도를 코드에 남긴다.

## 에러 처리

| 상황 | 동작 |
|---|---|
| 주말 | 휴장. API 호출 없음 |
| 달력에 오늘 있음 | 그 값 사용 |
| 달력 없음/오늘 없음 → 재조회 성공 | 판정 + 달력 갱신 |
| 재조회 실패 (토큰 없음/API 오류/네트워크) | `None` → 중단 + 경고 텔레그램 |
| `FORCE_RUN=true` (workflow_dispatch) | 게이트 우회 → `True` |

### FORCE_RUN — fail-closed의 수동 탈출구

`scraper.yml`이 `FORCE_RUN` env를 넘기지만 **현재 코드는 아무도 읽지 않는다**
(죽은 환경변수). fail-closed를 도입하면 KIS 장애 시 봇을 수동으로 돌릴
수단이 사라지므로, 이번에 `is_trading_day()` 머리에서 이 값을 읽어 게이트를
우회한다. 워크플로우 input·env 배관은 이미 있으므로 코드만 읽으면 된다.

### 경고 발송은 `should_notify()`를 우회한다

`should_notify()`는 정각(0~2분) 런에만 발송을 허용한다. 경고가 이 게이트를
타면 15/30/45분 런에서 침묵해 장애를 놓친다. 판정 불가 경고는
`TelegramManager.send_message()`를 직접 호출한다.

경고는 매 런 발송한다. Tasker가 매시간 트리거하므로 KIS 장애가 길어지면
반복되지만, "봇이 멈췄다"는 놓치면 안 되는 신호다. 중복 억제는 실제로
성가실 때 넣는다 (YAGNI).

## 테스트

`parse_calendar` / `lookup`이 순수 함수라 API 없이 검증 가능하다.

- `parse_calendar`: 실제 `chk-holiday` 응답 형태 → `{bass_dt: opnd_yn}` 맵
- `lookup`: `"Y"` → True, `"N"` → False, 없는 키 → None
- `is_trading_day`: 달력 주입으로 3값(True/False/None) 각각 검증
- 회귀 테스트: **2026-07-17이 휴장으로 판정되는지** (오늘 사고의 재현 방지)
- 주말 조기 반환 시 API를 호출하지 않는지

## 범위 밖

- `/api/cron`의 dispatch 차단 (스크래퍼 내부 게이트만 쓰기로 결정)
- 경고 중복 억제 로직
- `eod_data.yml` / `monthly_report.yml` 등 다른 워크플로우의 휴장 게이트
- 기존 `tr_day_yn` / `bzdy_yn` 활용 (개장 판정엔 `opnd_yn`만 쓴다)
- **`src/analyzer_5days.py`의 `holidays` 사용** — `get_recent_working_days()`가 `holidays.KR()`로
  5영업일을 계산해 같은 결함(2026-07-17을 영업일로 봄)을 갖는다. 다만 스크래퍼 런타임 import
  체인에 없고 `analyze_cumulative()`가 파이프라인 어디서도 호출되지 않아 이번 사고와 무관하다.
  `holidays` 제거는 **휴장 판정 경로 한정**이다 (저장소 전체가 아니다).

## 변경 파일

| 파일 | 변경 |
|---|---|
| `src/market_calendar.py` | 신규. 달력 조회·저장·판정 |
| `src/pipeline/context.py` | `bzdy_tp_cd` 제거 → `opnd_yn`. holidays 폴백 제거. `return True` → `None`. `FORCE_RUN` 우회. `is_market_hours`/`is_after_market_close` 반환 타입 좁히기 |
| `src/pipeline/orchestrator.py` | `None` 판정 시 경고 텔레그램 후 종료 (`should_notify()` 우회) |
| `.github/workflows/token_refresh.yml` | 달력 갱신 + db-data push 스텝 추가 |
| `scripts/requirements-scraper.txt` | `holidays` 제거 |
| `tests/` | 위 테스트 추가 |
