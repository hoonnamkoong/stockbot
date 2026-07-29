# StockBot 구조 진단 — 오버뷰

작성 2026-07-30. 심 레지스트리 리팩터링(Phase 1·2) 직후 전체를 훑어 만든 지도다.
개별 버그 목록이 아니라 **왜 매번 새 문제가 튀어나오는지**를 설명하는 것이 목적이다.

---

## 0. 다음 세션은 여기서 시작한다

**끝난 것 (2026-07-30, 전부 main):**

| 커밋 | 무엇 |
|---|---|
| `fd539d8e` `e41d56b0` | 심 목록 복제 해소 — 매니페스트가 유일한 원천, 생성기가 TS로 옮김 |
| `a60b26cb` | **CI 도입** + 실거래 TS 첫 테스트 17개 (턴 손익 11, 주문 조립 6) |
| `5d1495c5` | `manifest-sims.ts` 제거 — 런타임 매니페스트 파싱·fail-open 소멸 |

지금 상태: pytest 441 · node 30 · push마다 CI 자동 실행.
**아래 3순위(리셋 상태 shape)부터 이어가면 된다.** 4~6순위는 그 뒤.

**배포 후 아직 눈으로 확인 못 한 것** — 다음 세션 첫 5분에 볼 것:
1. 심8·심9·심9-1 카드에 매매 기록이 뜨는가 (`5d1495c5` 이전 커밋에서 고친 실버그).
   셋 다 페이퍼 단계라 체결이 없으면 여전히 비어 보일 수 있다 — db-data에
   `trade_history_sim_accumulation.csv` 등이 있는데도 비면 그때 다시 봐야 한다.
2. 레이더 색이 카드 색과 붙어 보이는가 (심5 yellow, 심8 indigo, 심9-1 lime, 심10 grape).
3. 프로그램 매매 드롭다운 이름이 "심리 괴리형 (Sim 1)" 형태로 뜨는가.

---

## 1. 시스템 지도

런타임이 넷이고, 셋 사이에 **스키마 강제자가 없다.**

| 런타임 | 사는 곳 | 하는 일 |
|---|---|---|
| 파이썬 파이프라인 | GitHub Actions (cron·dispatch) | 수집 → LLM 분석 → 심 실행 → 프로그램 매매 → 알림 |
| Next.js 앱 | Vercel | 대시보드, 실거래 주문, 프로그램 매매 ON/OFF |
| GitHub | `db-data` 브랜치 · `stockbot-secret` | **데이터베이스**. state JSON, 매매 CSV, 엑셀 |
| 외부 | KIS · Gemini · 네이버 | 시세·체결, LLM, 스크래핑 |

핵심은 세 번째다. **DB가 파일이라 스키마를 강제하는 주체가 없다.**
파이썬이 JSON을 쓰고 TS가 읽는데, 둘 사이의 계약은 코드에만 있고 어디에도 선언돼 있지 않다.

```
파이썬 ──write──> db-data/*.json ──read──> Next.js
   └── 계약: 없음. 양쪽이 각자 필드명을 안다.
```

---

## 2. 문제를 만드는 구조 — 근본 원인 셋

지금까지 튀어나온 문제는 대부분 새로운 종류가 아니다. 아래 셋 중 하나의 재발이다.

### A. 같은 지식이 파이썬과 TS에 각각 인코딩된다

경계에 스키마가 없으니 양쪽이 같은 사실을 따로 적는다. 한쪽만 고치면 조용히 어긋난다.

| 중복된 지식 | 파이썬 | TS | 상태 |
|---|---|---|---|
| 심 목록·라벨·파일명 | `registry.py` | 6곳 | **해결** (07-30, 생성기) |
| 매매 가능 심 화이트리스트 | `registry.get_tradeable_simulator_ids()` | `manifest-sims.ts` (자체 YAML 파서) | **미해결** |
| 리셋 상태 shape (10키) | `base_simulator.reset_state()` | `sim-reset-targets.buildResetState()` | **미해결** |
| 국면 파일 경로 | 4곳에 리터럴 | 해결됨 | **미해결(py)** |
| KIS TR·헤더·필드명 | `kis_data_provider.py`, `balance.py` | `kis-api.ts` | 구조적 |
| 턴 손익 계산 | `program_turn.py` | `program-turn.ts` | 의도된 이중화 |
| 수수료율 | `base_simulator.py` 상수 / `virtual_portfolio.py` 인라인 | — | **미해결(py 내부)** |

**이게 "매번 새 문제가 튀어나오는" 정체다.** 한 항목을 고쳐도 목록의 나머지는 그대로다.

### B. 실패가 조용하다

네트워크 의존이 많고(GitHub raw, KIS, Gemini) 기본 처리가 "빈 값으로 진행"이다.
`kis-api.ts`에만 `catch` 12개, `trade_engine.py`에 `except Exception` 14개.

[[no-fabricated-financial-values]] 원칙이 있는데도 경계마다 개별 판단으로 처리돼 있어,
어떤 실패가 "정상적으로 빔"이고 어떤 것이 "조회 실패"인지 호출자가 구분할 수 없다.

가장 뾰족한 사례: `manifest-sims.fetchTradeableSims()`가 `catch { return [] }`다.
GitHub raw가 한 번 실패하면 [program/route.ts:316](../src/app/api/trade/program/route.ts#L316)에서
`sim = null`이 되어 **사용자가 심을 골라 ON을 눌러도 선택이 조용히 버려진다.**
잘못 매매하지는 않으니 방향은 안전하지만, 아무 신호가 없다.

### C. 안전망이 파이썬에만 있다

| | 테스트 | 대상 |
|---|---|---|
| 파이썬 | 51파일 · 439케이스 | 심 전략, 파이프라인, 국면, 파리티 |
| TS | 2파일 · 7케이스 | 리셋 타깃 형식, GitHub 커밋 |

**실거래를 다루는 TS 약 1,400줄(`kis-api.ts` 706 + `program/route.ts` 367 + `order/route.ts` 161 +
`reservation` 165)에 테스트가 0이다.**

그래서 파이썬 쪽 결함은 테스트가 잡고, TS 쪽 결함은 **사용자가 눈으로 발견한다.**
07-29·07-30 두 건 모두 눈이 먼저 잡았다 — 우연이 아니라 구조의 결과다.

---

## 3. 시급 순서

우선순위 기준: **① 돈이 걸렸나 ② 조용히 실패하나 ③ 재발 빈도**

### ~~1순위 — `manifest-sims.ts` 통합~~ ✅ 완료 (`5d1495c5`)
런타임 조회는 설계 결정이 아니었음을 확인하고 `SIM_REGISTRY`로 대체했다.
fail-open 소멸, 이름 통일, 정규식 YAML 파서 43줄 삭제. id 집합은 전후 동일(9개).
가드 둘을 걸었다 — TS가 매니페스트를 직접 읽지 않는가, 드롭다운 tradeable 집합이
파이썬 화이트리스트와 같은가.

### ~~2순위 — 실거래 TS에 테스트 깔기~~ ◐ 착수 (`a60b26cb`)
CI + 17개를 깔았다. **남은 것:** `order/route.ts`, `program/route.ts`(PIN 잠금·
화이트리스트), `kis-api.ts`의 토큰 캐시·잔고 파싱·`matchRealizedRoi`.
라우트를 통째로 테스트하려면 vitest가 필요하다(`next/server`를 node가 못 푼다) —
4순위의 lib 추출을 먼저 하면 필요 없어질 수도 있다.

### 3순위 — 리셋 상태 shape 단일화 ← **여기서 이어간다**
파이썬이 정본을 만들고 TS가 그것에서 파생하거나(생성기 재사용), 최소한 두 곳을 묶는 테스트.
지금은 한쪽에 키가 늘면 대시보드로 리셋한 심만 다른 상태로 시작하고, **아무도 모른다.**

### 4순위 — 국면 파일 리터럴 4곳 + `_read_regime` 2벌
심 목록과 같은 병의 잔여. registry가 이미 analyzer의 `state_file`을 안다.

### 5순위 — 대시보드 로드 비용
1회 로드에 GitHub raw 약 25회(stats 13 + history 12), 전부 `no-store`.
**심 개수에 선형 비례**하는데 레지스트리 작업으로 심 추가가 쉬워진 만큼 곧 커진다.
심 20개면 41회다. 지금 당장 아프지는 않다.

### 6순위 — `TradeClient.tsx` 분해 (1,040줄 · `useState` 41개)
실거래 주문·예약·프로그램·심 카드·히스토리가 한 함수 안에 있다.
가치는 있지만 **2순위(테스트) 없이 건드리면 위험하다.** 순서가 중요하다.

---

## 4. 지금 손대지 말 것

- **KIS 프로토콜 이중 구현** — Next 서버 + 파이썬 파이프라인이라는 구조에서 나오는 것이라,
  없애려면 아키텍처를 바꿔야 한다. 비용 대비 이득이 안 맞는다.
- **심 간 소소한 중복** (`_zmap` 3벌, `_features`·`_median` 2벌) — 각 심이 독립적으로
  진화하는 게 설계 의도다. 공통화하면 한 심의 튜닝이 다른 심을 건드린다.
- **`scraper_legacy_v49.py`** (853줄) — 이름이 legacy다. 지우기 전에 참조 여부 확인 필요.

## 4-1. 별건: 파이썬 의존성 목록이 갈라져 있고 하나는 깨져 있다

`scripts/requirements.txt`는 파일 끝이 UTF-16으로 깨져 있어(`p y t h o n - d o t e n v`)
pip가 패키지명을 잘못 읽는다. 그래서 워크플로들이 전부 `requirements-scraper.txt`를 쓰는데,
그쪽에는 `holidays`가 없다 — `src/analyzer_5days.py`가 최상단에서 import하는 패키지다.

CI를 켜자마자 이것이 드러났다(pytest exit 2, 수집 단계 사망). 지금은 워크플로에서
`holidays`를 따로 설치해 막아뒀다. 제대로 고치려면 목록을 하나로 합치고 깨진 인코딩을
정리해야 한다.

---

## 5. 한 줄 요약

개별 버그가 아니라 **경계에 계약이 없다**는 것이 문제다.
1·3·4순위는 전부 "계약을 한 곳에 두기"의 사례이고, 2순위는 "계약이 깨진 걸 눈이 아니라
테스트가 잡게 하기"다. 이 둘을 끝내면 같은 종류의 문제가 새로 튀어나오는 일이 멈춘다.

---

## 6. 이 레포에서 일할 때 알아둘 것 (실측)

**검증 명령 (전부 로컬에서 돌아간다):**
```
python -m pytest tests/ -q          # 441 passed, 4 skipped
node --test "src/**/*.test.ts"      # 30 passed
npx tsc --noEmit
npm run build
python scripts/gen_sim_registry.py  # 매니페스트 고쳤으면 반드시
```

**TS 테스트 러너 제약:**
- Node 23.6+는 `--experimental-strip-types` 없이 `.ts`가 돈다 (CI는 24, 로컬은 26).
- **상대 import에 `.ts` 확장자가 필요하다** — node ESM 해석기가 확장자 없는 상대경로를
  못 찾는다. `tsconfig.json`의 `allowImportingTsExtensions: true`가 그래서 있다.
  단 `@/` 별칭 import는 node가 모르므로, 테스트가 닿아야 하는 모듈은 상대경로로 쓴다.
- **라우트 핸들러(`app/api/**/route.ts`)는 import 자체가 안 된다** — `next/server` 미해결.

**테스트를 쓸 때:** 통과하는 것만으로는 부족하다. 이번 세션에서 새로 건 불변식은 전부
**소스를 일부러 망가뜨려 실제로 잡히는지 확인**했다(기준가 `||`→`??`, `by_tag` 복사 제거,
매니페스트 재fetch, tradeable 불일치). 같은 방식을 계속 쓸 것.

**함정:**
- `git checkout --`를 정리 명령에 끼워 넣지 말 것. 이번 세션에서 미커밋 편집을 날렸다.
- Bash 툴의 작업 디렉터리는 호출 사이에 유지된다. `cd` 후에는 `git -C <repo>`를 쓸 것.
  이번 세션에서 임시 클론에 `cd`한 채 커밋이 엉뚱한 곳에서 돌았다.
- 파이썬 heredoc에 `/c/Users/...` 경로를 쓰면 못 찾는다(파이썬은 Windows 프로그램).
  `C:/Users/...`를 쓸 것.
