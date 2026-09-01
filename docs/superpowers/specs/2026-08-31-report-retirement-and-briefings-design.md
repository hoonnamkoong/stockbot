# 리포트 폐기 + 심7 제거 + 브리핑 재편 설계

- 작성: 2026-08-31
- 상태: 승인됨(사용자), 구현 계획 대기

## 배경

2026-08-31 점검에서 심5·7·11·13이 당일 거래 0건이었다. 원인을 실측한 결과:

| 심 | 원인 | 판정 |
|---|---|---|
| 심13 테마 | 10:32~11:29 국면 BEAR → `regime_blocked` 28건 | 전략대로 |
| 심7 리포트 | bull_score 34.7 < `SIM7_BULL_SCORE_MIN=40` → 딥다이브 미생성 → 강력매수 목록 없음 | 전략대로 |
| 심11 미너비니 | 감시목록 엔트리가 GS 하나인데 08-28부터 보유 중 | 전략대로 |
| 심5 횡보 | 진단 이력 없음 — **소급 확인 불가** | 미해결(본 설계 범위 밖) |

심7은 Gemini 딥다이브 리포트의 "강력 매수" 판정을 유일한 입력으로 삼는다. 그
리포트를 폐기하기로 결정했으므로 심7도 함께 사라진다.

리포트 폐기 결정의 근거는 사용자 판단이다. 대신 **브리핑**(실적 요약)을 국내
2회·미국 1회로 재편한다. 리포트는 "무엇을 살까"를 말했고 브리핑은 "무엇이
일어났나"를 말한다 — 후자만 남긴다.

별건으로 `premarket_data.yml`의 intraday 커밋이 파일 크기 한도로 실패하는 문제도
함께 고친다(같은 배포 사이클에 묶는다).

## 결정 사항 (사용자 확정)

1. 11:00·14:00 리포트 슬롯을 **통째로 폐기**한다(대시보드 링크·어텐션 리포트·딥다이브 전부).
2. 국내 브리핑은 **12:00 + 15:00** 두 슬롯. 12:00은 09:00~12:00 구간, 15:00은 하루 전체.
3. 미국 브리핑은 **09:00 KST 마감 브리핑 1회**만. 장중 브리핑은 만들지 않는다.
4. 미국 브리핑 발송 경로는 **trading.yml**(그 시각에 이미 2분마다 돌고 있다).
5. 심7은 **청산 없이 즉시 제거**한다.
6. intraday CSV는 **gzip**으로 커밋한다.

## 범위 밖 (명시)

- **심5 진단 이력 추가.** 심5가 왜 안 샀는지는 여전히 소급 확인 불가로 남는다.
  요청 범위 밖이라 넣지 않았다. 별건으로 다뤄야 한다.
- **Stage 2 Gemini 배치 분석.** `fact_score`를 심1이 쓰므로 그대로 둔다.
  폐기하는 것은 Stage 3.5 딥다이브 생성뿐이다.
- **`telegram_manager.send_market_report` / `send_dashboard_link` 메서드 자체.**
  `scripts/scraper_legacy_v49.py`가 아직 참조하므로 남긴다. 이 변경이 만든
  고아가 아니다.

## 1. 리포트 폐기

### 삭제 대상

| 파일 | 내용 |
|---|---|
| `src/report/gate.py` | `REPORT_SLOTS`, `due_slot()` |
| `src/pipeline/context.py` | `report_slot()`, `should_notify()` — 둘 다 통째로 삭제 |
| `src/pipeline/orchestrator.py` | Stage 3.5 딥다이브 생성(227~251), `SIM7_BULL_SCORE_MIN`, `sim7_should_buy()`, Stage 3.6 |
| `src/pipeline/workers/notifier.py` | `_send_report()`, `_send_fallback_summary()`, 슬롯 분기, `reported_codes` 갱신 |
| `src/pipeline/workers/llm_analyzer.py` | `generate_deep_dive()` |
| `src/strategy/advisor.py` | `generate_deep_dive_report()` |

### 딸려 죽는 것 — `reported_codes`

`notifier.py:73-79`의 `reported_codes` 갱신이 `if slot:` 안에 묶여 있다. 슬롯이
사라지면 이 상태는 영원히 갱신되지 않는다.

조사 결과 이 필드는 `src/data/schemas.py:220`에 `[Legacy]`로 표시돼 있고 실제
소비자는 `scripts/scraper_legacy_v49.py`뿐이다 — **현행 파이프라인에서는 이미
죽은 배선**이다. 따라서 조용히 방치하지 않고 notifier에서 함께 제거한다.
`SyncState`의 필드 자체는 legacy 스크립트가 읽으므로 남긴다.

`PipelineContext.should_notify()`의 소비자는 `orchestrator.py:229`(Stage 3.5)와
`notifier.py:52`뿐이고 **둘 다 이번에 삭제된다.** 따라서 메서드 자체를 지운다.
(`scripts/notify_workflow_failure.py`에도 같은 이름의 함수가 있으나 워크플로 실패
알림용으로 무관하다 — 건드리지 않는다.)

### 구현 착수 중 발견 — 슬롯 안에 숨어 있던 두 가지

**(1) 월별 리서치 엑셀이 Stage 3.5 안에 있다.**
`orchestrator.py:237-238`의 `storage.update_monthly_excel(final_picks, ctx.now_kst)`가
`if ctx.should_notify():` 블록 안에 중첩돼 있다. 이것이 쓰는 파일은
`reports/monthly_research_{YYYY-MM}.xlsx`로, **2026-08-31에 "별개의 살아있는
산출물이라 유지"로 명시적으로 결정한 바로 그 파일**이다(월간 리포트 폐기 건에서
구분해 남긴 것). Stage 3.5를 통째로 지우면 이 결정이 조용히 뒤집힌다.

→ **엑셀 기록은 살린다.** 다만 리포트 게이트가 사라지므로 발동 조건을 옮겨야
한다. 현행 주기(하루 2회)를 유지하기 위해 **브리핑 슬롯(12:00·15:00)이 열릴 때**
기록한다. 매 사이클로 옮기면 행 수가 수십 배로 늘어 성격이 달라진다.

**(2) "9개 완성 순위 알림"도 리포트 슬롯 안에 있다.**
`notifier.py:124-144`가 `_send_report()` 내부에서 `📋 오늘의 추천 종목 (오전/오후
9개 완성)` 텔레그램을 별도로 보낸다. 리포트 본문과 다른 메시지라 눈에 안 띈다.

→ **함께 폐기한다.** "무엇을 살까"를 말하는 추천 목록이고, 슬롯 통째 폐기 결정의
대상이다. 이 블록이 읽던 `sync_state` 필드는 **성격이 갈린다.**
`daily_reported_info`·`reported_codes`는 여전히 읽는 곳이 있고
(`scripts/scraper_legacy_v49.py`의 중복 방지 경로), `morning_reported_info`·
`afternoon_reported_info`·`morning_complete`·`afternoon_complete`는 이제
**쓰기 전용**이다 — 이 값을 소비하는 코드가 레포 어디에도 없다(앞의 둘은
`total_session` 계산을 위해 자기를 쓰는 블록 안에서만 다시 읽히고, `*_complete`는
읽는 곳이 아예 없다). 그래도 **필드 자체는 남긴다**: 저장된 sync_state JSON의
스키마이고, 지우면 기존 상태 파일 역직렬화가 깨진다.

### 폐기 후 notifier에 남는 것

1. 멀티데이 집계 저장
2. 브리핑 발송(국내 12:00·15:00)
3. 실거래 예약 주문 처리(`_run_trade_executor`)

`orchestrator.py`의 `rebuild_reports_index()`(대시보드 리서치 목록용 `reports.json`)는
Stage 3.5 **밖**에 있으므로 그대로 둔다.

## 2. 심7 제거

### 하드코딩 지점 전수 (실측)

```
src/strategy/strategy_manifest.yaml:202-216   블록 삭제 → gen_sim_registry.py 재실행
src/strategy/simulators/sim7_report_follower.py   파일 삭제
src/pipeline/orchestrator.py:41,266,267       Stage 3.6 + 게이트 삭제
scripts/audit_sim_fields.py:34                SKIP_SIMS에서 제거
tests/test_sim7_gate.py                       파일 삭제
tests/test_all_sims_can_trade.py:178          test_sim7_report_can_buy 삭제
tests/test_needs_buzz_registry.py:28,121      항목 삭제
tests/test_program_turn.py:186                다른 심으로 교체
```

`src/lib/sim-registry.generated.ts`는 `gen_sim_registry.py`가 다시 만든다. 손으로
고치지 않는다.

### 데이터 처리

db-data의 `sim_reportfollower_state.json`·`trade_history_sim_reportfollower.csv`는
**삭제하지 않는다**(이력 보존). 매니페스트에서 빠지는 순간 브리핑·대시보드
목록에서만 사라진다. 보유 2종목(215600 78주, 950260 11주)은 청산 기록 없이
동결된다 — 사용자 결정이며, 페이퍼 심이라 실제 손익에 영향이 없다.

`config/data_freshness.yaml`에는 심7 산출물이 **없음을 확인했다**(심 상태 파일은
애초에 신선도 감사 대상에서 빠져 있다 — 값이 바뀔 때만 커밋돼 안 사고 안 판 심이
정지처럼 보이기 때문). 따라서 여기는 손댈 것이 없다.

## 3. 국내 12:00 구간 브리핑

`src/report/gate.py`:

```python
BRIEF_SLOT = '15:00'            # 삭제
BRIEF_SLOTS = ('12:00', '15:00')  # 신규
```

`brief_due(now)`는 열려 있는 슬롯 문자열을 돌려주도록 바꾼다(`bool` → `str|None`).
호출자가 어느 슬롯인지 알아야 제목과 집계 구간이 갈린다.

이에 맞춰 `daily_brief.should_send_brief()`도 `bool` → `str|None`으로 바뀌고,
`notifier.py:70-71`의 호출부는 반환된 슬롯을 `build_daily_brief`에 넘긴 뒤 **그
슬롯으로** `mark_sent`한다(현행은 `BRIEF_SLOT` 상수를 넘긴다 — 그대로 두면 12시
브리핑을 보내고 15시 슬롯을 닫아 마감 브리핑이 사라진다).

`src/pipeline/daily_brief.py`:

- `build_daily_brief(balance, sims, now_kst, slot)` — `slot`으로 제목 분기
  - `12:00` → `📅 12:00 오전 브리핑 (09:00~12:00)`
  - `15:00` → `📅 15:00 마감 브리핑` (현행 문구 유지)
- `_count_today_tickers(path, today_str, since=None, until=None)` — 시각 범위 인자 추가.
  12:00 슬롯은 `09:00~12:00`, 15:00 슬롯은 하루 전체(현행과 동일).
- 수익률은 **두 슬롯 모두 현재 시점 누적**이다. 구간 수익률이 아니다 —
  상태 파일에 구간 시작 시점 스냅샷이 없어서 만들어낼 수 없다. 브리핑 문구에
  그렇게 적는다.

### 소유권

writer는 `scraper.yml` 그대로다. `report_gate_state.json`의 배포 경로가 바뀌지
않으므로 `test_scraper_deploys_the_report_gate_state`·
`test_trading_does_not_deploy_the_report_gate_state`는 그대로 통과해야 한다.

## 4. 미국 09:00 브리핑

### 왜 별도 상태 파일인가

`report_gate_state.json`은 **writer가 scraper.yml 하나**라는 것이 명시적 계약이고
`tests/test_workflow_file_ownership.py:147`가 "trading.yml은 이 파일을 배포하지
않는다"를 강제한다. 두 writer가 붙으면 lost update로 이미 닫은 슬롯이 다시 열려
같은 브리핑이 여러 번 나간다.

→ 미국 브리핑은 **`us_brief_gate_state.json`**을 쓰고, 그 파일의 유일 writer는
trading.yml이다.

### gate.py 일반화

`_state_path`·`_sent_today`·`_due`·`mark_sent`가 상태 파일명을 인자로 받도록
바꾼다. 기존 두 호출자는 기본값(`report_gate_state.json`)으로 **동작이 바뀌지
않아야 한다.**

```python
US_BRIEF_SLOT = '09:00'
US_BRIEF_STATE_FILENAME = 'us_brief_gate_state.json'

def us_brief_due(now_kst, data_dir=None) -> bool: ...
```

창은 기존 `SLOT_WINDOW_MIN`(40분) 재사용 → 09:00~09:40. `kr_session_open`이
09:00부터 True라(`src/session_gate.py:47-54`) 첫 트리거에 잡힌다.

### 신규 모듈 `src/pipeline/us_brief.py`

```python
def build_us_brief(sims: list[dict], now_kst: datetime) -> str
```

순수 함수(I/O 없음). `daily_brief.build_daily_brief`와 같은 형태로 만들고 같은
포맷 헬퍼를 공유한다.

- 심 목록은 `src.strategy.us_registry.get_us_sim_registry()`에서 파생한다.
  자체 목록을 갖지 않는다(`daily_brief.SIM_BRIEF_TARGETS`와 같은 이유 —
  손으로 적어두면 새 심이 조용히 빠진다).
- **실계좌 블록이 없다.** 미국 심은 전부 페이퍼다.
- 조회 실패는 `측정 불가`로 적는다. `0`으로 폴백하지 않는다.
- 거래 종목 수의 "간밤" 구간은 **전일 22:00 ~ 당일 09:00 KST**. 미국 거래이력의
  timestamp가 KST 기준임을 실측 확인했다(`2026-08-31 22:31:41` = 개장 직후).

### trade_loop 배선

`scripts/trade_loop.py`에 발송 스텝을 추가한다. 발송 성공 직후에만 `mark_sent`를
부른다(실패를 '보냈다'로 적으면 그날 회차가 사라진다).

배포 매니페스트(`regime_output_files`)에 `us_brief_gate_state.json`을 추가한다 —
db-data를 왕복하지 못하면 매 런이 새 컨테이너라 "아직 안 보냈다"로 읽고 40분 창
안의 20번 트리거가 전부 브리핑을 보낸다.

## 5. intraday gzip

`.github/workflows/premarket_data.yml`의 intraday 커밋 스텝:

```bash
for f in data/rt_intraday_*.csv; do
  [ -e "$f" ] || continue
  gzip -9 -c "$f" > "db_data_repo/data/$(basename "$f").gz"
done
```

**압축 후 크기를 재서 100MB를 넘으면 명시적으로 실패시키고 알림을 보낸다.**
조용히 잘리거나 push가 거부되는 것보다 낫다.

읽는 쪽 수정은 필요 없다 — 이 파일은 db-data에 올라간 적이 한 번도 없어
소비자가 없다(2026-08-31 실측: `git log` 결과 0건).

## 6. 테스트

| 대상 | 확인 |
|---|---|
| 게이트 슬롯 | 12:00·15:00 독립 판정, 하나를 보내도 다른 하나가 열림 |
| 게이트 분리 | 미국 슬롯 `mark_sent`가 `report_gate_state.json`을 건드리지 않음 |
| 소유권 | `us_brief_gate_state.json`은 trading.yml만, `report_gate_state.json`은 scraper.yml만 배포 |
| `build_us_brief` | 순수 함수. 조회 실패 → `측정 불가`(0 아님), 거래 0건 → `0종목` |
| 구간 집계 | `_count_today_tickers`가 09:00~12:00 밖 거래를 세지 않음 |
| 심7 제거 | 레지스트리 일관성, `test_all_sims_can_trade`, `needs_buzz` 목록 |
| 리포트 폐기 | `REPORT_SLOTS` 참조가 코드베이스에 남아 있지 않음 |
| 월별 엑셀 | 브리핑 슬롯이 열릴 때만 `update_monthly_excel`이 불림(하루 2회 유지) |

## 배포 후 검증 지점

1. **당일 12:00 KST** — 국내 오전 브리핑이 텔레그램에 도착하고, 종목 수가
   09:00~12:00 거래만 세는지 이력과 대조
2. **당일 15:00 KST** — 마감 브리핑의 **수치가 현행 그대로**인지(회귀 없음).
   문구는 한 곳이 의도적으로 바뀐다: `_sim_block` 헤더가 "누적 수익률"로
   명시된다. 그 외의 문구 변화는 회귀다.
3. **당일 11:00·14:00 KST** — 리포트가 **오지 않는지**
4. **화~금 09:00 KST** — 미국 마감 브리핑 도착. `us_brief_gate_state.json`이
   db-data에 커밋돼 09:00~09:40 사이 중복 발송이 없는지 확인.
   (월요일은 런이 있어도 창이 다르므로 화~금에 본다.)
   4-1. **월요일 09:00 KST** — 본문의 "대상 구간"이 **직전 금요일 22:00**에서
   시작하고, 금요일 밤 세션의 거래가 종목 수에 잡히는지 별도로 확인. 일요일
   22:00에서 시작하면 세션이 없는 창이라 세 심 모두 0종목이 된다.
5. **양 브리핑 슬롯(12:00·15:00)** — `reports/monthly_research_{YYYY-MM}.xlsx`에
   **행이 늘어나는지**. 이 기록은 폐기된 Stage 3.5 안에 있던 것을 브리핑 슬롯으로
   옮긴 것이라, 이 브랜치가 이전시킨 산출물 중 가장 깨지기 쉽다. 조용히 멈춰도
   워크플로는 초록색이다 — 하루 2회 늘어나는지 눈으로 확인한다.
6. **익일 07:20 KST** — premarket intraday 잡이 gzip으로 push 성공하는지
   (`data/rt_intraday_*.csv.gz`가 **`intraday-data` 브랜치**에 올라오는지 —
   db-data가 아니다. 첫 실행은 고아 브랜치 생성 경로를 탄다)
