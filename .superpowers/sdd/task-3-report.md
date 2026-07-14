# Task 3 리포트: 턴 손익 표시 계산(TS) + API route

> 주: 이 경로에 이전 태스크 사이클의 `Task 3` 리포트(base_simulator `_view`/`_apply`, 커밋 `0e4da23c`)가 있었다. 이번 지시에 따라 현재 태스크 내용으로 덮어썼다 — 과거 리포트는 `git log -p -- .superpowers/sdd/task-3-report.md`로 복구 가능.

## 1. 만든 것 / 고친 것

| 파일 | 내용 |
|---|---|
| `src/lib/program-turn.ts` (신규) | `ProgramTurn`·`ProgramPosition`·`TurnResult` 타입, `computeTurnPnl()`. 브리프 Step 1 **verbatim**. |
| `src/app/api/trade/program/route.ts` (수정) | Step 2~6 **verbatim**. import 2줄 추가, `getPositions()`가 `turn`도 반환, `getLivePrices()` 신규, GET에 `turn`·`last_turn_result` 추가, OFF에서 턴 동결, ON에서 턴 열기. |

브리프와 어긋난 것: **없음**. 8개 스텝 모두 브리프 코드 그대로 적용했다.

### 중복 선언 확인 (브리프가 경고한 지점)
Step 6에서 기존 ON 분기의 `const now = ...`(구 216행)를 새 블록이 흡수하도록 **`const now`+`const next`를 한 번의 Edit으로 함께 교체**했다. 결과적으로 파일에 남은 `const now`는 정확히 2개이며 서로 다른 블록 스코프다:
- 204행 — OFF 분기 `if (!wantEnabled) { ... }` 내부
- 264행 — ON 경로 (함수 본문 스코프)

TS 0 에러가 이를 재확인한다(같은 스코프 중복이면 TS2451이 떴을 것).

## 2. `npx tsc --noEmit` 실제 출력

```
$ npx tsc --noEmit 2>&1; echo "EXIT=$?"
EXIT=0
```

출력 한 줄도 없음, exit 0 → **0 errors**.

## 3. OFF가 "어떤 실패 상황에서도" enabled:false를 기록하는지 — 어떻게 확인했나

정적 리딩만으로 주장하지 않고 **실제 route.ts를 트랜스파일해 실행**했다.

**방법**: `npx tsc`로 진짜 `route.ts`를 CommonJS로 트랜스파일한 뒤(`scratchpad/route_out/route.js`), Node의 `Module._load` 훅으로 `next/server`·`next-auth/jwt`·`@/lib/*`를 스텁으로 가로채고 `global.fetch`로 GitHub API를 흉내냈다. 그 상태에서 턴 동결의 모든 의존성(원장 조회, KIS 잔고/시세 조회, 손익 계산)을 하나씩·그리고 동시에 사보타주하고, **route가 GitHub에 PUT한 config 본문**을 캡처해 `enabled` 값을 직접 확인했다. 테스트용으로 로직을 재작성한 게 아니라 **배포될 코드 그 자체**를 실행한 것이다.

**결과 (10/10 PASS)** — 모든 행에서 `enabled=false`, `turn=null` 기록됨:

```
PASS  정상 (기준선)          enabled=false  turn=null  sim="sim5_sideways"  budget=3000000  last_turn_result=pnl:1300 capital:3000000
PASS  원장 조회 네트워크 예외   enabled=false  turn=null  sim="sim5_sideways"  budget=3000000  last_turn_result=pnl:0 capital:3000000
PASS  원장 500              enabled=false  turn=null  sim="sim5_sideways"  budget=3000000  last_turn_result=pnl:0 capital:3000000
PASS  원장 JSON 깨짐         enabled=false  turn=null  sim="sim5_sideways"  budget=3000000  last_turn_result=pnl:0 capital:3000000
PASS  원장 내용 이상(문자열)   enabled=false  turn=null  sim="sim5_sideways"  budget=3000000  last_turn_result=pnl:0 capital:3000000
PASS  KIS 잔고조회 throw     enabled=false  turn=null  sim="sim5_sideways"  budget=3000000  last_turn_result=pnl:300 capital:3000000
PASS  KIS error 응답        enabled=false  turn=null  sim="sim5_sideways"  budget=3000000  last_turn_result=pnl:300 capital:3000000
PASS  KIS holdings=null     enabled=false  turn=null  sim="sim5_sideways"  budget=3000000  last_turn_result=pnl:300 capital:3000000
PASS  손익 계산 자체가 throw  enabled=false  turn=null  sim="sim5_sideways"  budget=3000000  last_turn_result=null
PASS  전부 동시 실패          enabled=false  turn=null  sim="sim5_sideways"  budget=3000000  last_turn_result=pnl:0 capital:3000000

RESULT: 모든 실패 시나리오에서 enabled:false 기록됨 (kill-switch 불변식 성립)
```

**코드 경로로 본 이유** (실행 결과와 일치):
1. `let lastTurnResult`가 `try` **바깥**에 선언된다 → catch로 빠져도 `next` 구성 시점에 항상 정의돼 있다.
2. 동결 계산 전체가 `try { ... } catch { console.error }` 안에 있다 → 내부에서 무엇이 throw해도 삼켜진다. ("손익 계산 자체가 throw" 행이 이를 실증: `computeTurnPnl`이 폭발해도 OFF는 기록됨.)
3. `putConfig(next, ...)`는 try/catch **뒤에서 무조건** 실행된다 → 동결 성공 여부와 무관.
4. 보조 헬퍼 자체도 total하다: `getPositions()`·`getLivePrices()` 모두 내부 try/catch로 실패 시 빈 값을 반환하고 throw하지 않는다 — 즉 방어가 이중이다.

**남는 단 하나의 OFF 실패 경로**는 `putConfig`(GitHub config 쓰기) 자체의 실패이며, 이는 이번 변경 이전부터 있던 동작이다(쓰기가 실패하면 OFF는 원래도 기록될 수 없다). **이번 태스크가 추가한 어떤 코드도 OFF를 막지 않는다.**

**보안 교정 보존도 같은 실행으로 확인**: 위 모든 행에서 `sim="sim5_sideways"`, `budget=3000000`이 **기존 config 값 그대로** 유지됐다. route는 OFF에서 `enabled`/`turn`/`last_turn_result`만 건드린다.

## 4. ON 경로도 동일 방식으로 검증 (9/9 PASS)

```
[A] 조회 실패에도 ON 진행
PASS  정상 (기준선)        enabled=true  capital=3005000  opening_basis={"005930":1100}  http=200
PASS  원장 조회 예외        enabled=true  capital=3000000  opening_basis={}  http=200
PASS  원장 500            enabled=true  capital=3000000  opening_basis={}  http=200
PASS  KIS 잔고조회 throw   enabled=true  capital=3005000  opening_basis={}  http=200
PASS  KIS error 응답      enabled=true  capital=3005000  opening_basis={}  http=200
PASS  원장+KIS 동시 실패    enabled=true  capital=3000000  opening_basis={}  http=200

[B] 게이트는 여전히 fail-closed (config 기록이 없어야 정상)
PASS  PIN 틀림            enabled=(기록 안됨)  http=403
PASS  화이트리스트 밖 sim    enabled=(기록 안됨)  http=400
PASS  budget=0           enabled=(기록 안됨)  http=400
```

- 기준선 `capital=3005000` = budget 3,000,000 + realized_pnl 5,000 → 브리프의 "턴 시작 유효자본" 정의와 일치.
- 잔고 조회 실패 시 `opening_basis={}`로 두고 ON 정상 진행 → 파이썬 `new_turn()`이 `current_prices`로 폴백한다(확인: `program_turn.py:33`의 기준가 우선순위 `opening_basis > current_prices > avg_price`).
- PIN/레이트리밋/화이트리스트/budget>0 게이트는 한 줄도 건드리지 않았고, 여전히 config를 쓰지 않고 차단한다.

## 5. `computeTurnPnl` 산수 검증 (트랜스파일한 진짜 함수 실행)

- 확정 300 + 미실현 (1100−1000)×10 = **1300** ✓
- Sim10 태그 분리: 보유 종목의 `tag`별 귀속 → `{sim5_sideways: +100, sim4_bull_daytrading: −100}` ✓
- 시세 결손 종목은 기여 0 ✓ / `basis` 미기록 종목은 기준가=현재가 폴백 → 기여 0 ✓
- 적대적 입력(`turn=null`, `positions=null`, `by_tag` 누락, 가격 NaN/문자열)에서 throw 없음 ✓

## 6. 자체 리뷰에서 고친 것

프로덕션 코드 수정은 없었다(브리프 verbatim이 모든 검증을 통과). 검증 하네스 작성 중 내 sed 스크립트 실수로 ON 테스트가 전부 FAIL로 나온 적이 있는데, 원인은 자식 프로세스에 `TRADE_PIN`이 전달되지 않아 라우트가 auth 게이트에서 조기 반환한 것이었다(즉 **route가 옳게 fail-closed로 동작한 것**). 하네스를 다시 작성해 해결했다. 코드 문제 아님.

또한 `route.ts`가 새로 `@/lib/kis-api`를 import하므로 최상위 사이드이펙트를 점검했다 — `kis-api.ts`의 최상위 문은 `if (typeof window === 'undefined') logEnvStatus();`(로깅뿐)이고 env 접근은 `getKISConfig()` 안에서 지연 평가된다. import 시점에 throw할 여지 없음.

## 7. 우려사항

1. **[표시 정확도] 조회 실패 시 "틀린" 턴 결과가 동결된다.** 원장 조회가 실패하면 `matched=null` → `pnl:0`이 `last_turn_result`에 박제된다. KIS 조회만 실패하면 확정분만 남고 미실현이 통째로 빠진다(위 표의 `pnl:300`). 즉 OFF 순간 GitHub/KIS가 일시 장애면 사용자에게 **0원 또는 축소된 수익률이 사실인 것처럼** 남는다. 브리프가 명시한 동작이라 그대로 뒀지만, 표시 진실성 관점에서는 `pnl: null`(=미상)로 구분하는 편이 정직하다. 다음(마지막) 태스크에서 화면에 그릴 때 고려할 가치가 있다. **매매 안전성에는 영향 없음**(OFF는 항상 성사됨).
2. **[지연] OFF 경로에 타임아웃 없는 fetch가 2개 늘었다.** `getPositions()`+`getLivePrices()`는 실패는 잘 처리하지만 **행(hang)**은 try/catch로 잡지 못한다. Node `fetch`는 기본 타임아웃이 없어, GitHub/KIS가 응답을 주지 않고 매달리면 kill-switch 응답이 그만큼 늦어진다(기존에도 `getConfig()` 1개가 같은 성질이었으나 표면이 넓어졌다). 브리프에 없어 추가하지 않았다. `AbortSignal.timeout(3000)` 한 줄로 막을 수 있다 — 승인 주면 반영하겠다.
3. **[사소]** `computeTurnPnl`은 `prices=null`을 넘기면 throw한다(TS 타입상 불가하고 `getLivePrices()`는 항상 맵을 반환하므로 route에서는 도달 불가, 게다가 OFF의 try/catch가 삼킨다). 다음 태스크의 프론트에서 **시세 미도착 상태를 `null`이 아니라 `{}`로** 넘길 것.
4. `turn.id`는 `new Date().toISOString()`(UTC)이고 `started_at`은 KST 문자열이라 형식이 다르다. 브리프대로이며 id는 불투명 식별자로만 쓰이니 기능 문제는 없다.

## 8. 불변식 준수

- 원장(`program_positions.json`)은 **읽기 전용**으로만 접근했다(`getPositions()`의 GET뿐, PUT 없음).
- config(`program_trading.json`)의 단일 writer는 여전히 이 route 뿐이다.
- 커밋은 지정된 2개 파일만 명시적 경로로 스테이징(`git add -A` 미사용).

---

# Task 3 후속: 코드 리뷰 지적 3건 수정 (Critical / Important / Minor)

앞 리포트 §7의 우려사항 1·2를 리뷰가 각각 Important·Critical로 확정했다. 승인받아 수정했다.

## 1. 🔴 Critical — OFF가 hang으로 죽어 kill-switch가 기록되지 못하는 경로 차단

`try/catch`는 throw를 잡지만 **hang은 못 잡는다**. OFF 경로에 추가된 조회 2개(GitHub 원장, KIS 잔고)는
상한이 없어(undici 기본 ≈300s / axios 토큰 발급 무한) 서버리스 타임아웃에 함수가 통째로 죽으면
`catch`도 `putConfig`도 실행되지 않는다 → `enabled:false`가 안 남는다.
게다가 이 최악 경로는 `matched`(=장중 정상 매매 중)일 때만 타므로 **kill-switch를 누르는 그 순간이 핫패스**다.

| 수정 | 위치 |
|---|---|
| `withDeadline<T>(p, ms, fallback)` 추가 — `Promise.race`로 상한을 건다 | `route.ts` |
| 동결 계산 전체를 `withDeadline(freezeTurn(...), 2500, null)`로 감쌈 | OFF 분기 |
| ON 스냅샷 블록도 동일 데드라인(2500ms). fail-open이지만 같은 hang 노출이 있었다 | ON 경로 |
| 원장 조회 fetch에 `signal: AbortSignal.timeout(3000)` (config 조회/PIN 잠금은 범위 밖 — 미변경) | `getPositions()` |
| `putConfig`(쓰기)에는 **데드라인 없음** — 그게 kill-switch 그 자체다 | 그대로 |

데드라인은 매달린 fetch를 취소하지 못한다(소켓은 뜬 채로 남는다). 하지만 **핸들러는 폴백을 들고 즉시
`putConfig`로 진행**하므로 OFF 지연이 상수로 묶인다 — 그게 요구사항이다.

## 2. 🟡 Important — 실패한 계산이 "손익 0원"으로 영구 박제되던 문제

조회 실패와 "파이썬이 이번 턴에 한 번도 안 돎"(장 외 ON→OFF)이 **같은 분기로 합쳐져** 둘 다 `pnl:0`이 됐다.
분리했다.

- `getPositions()` → `{ ok, positions, realized_pnl, turn }`. **404는 `ok:true`**(원장 미생성 = 정상적으로 빈 원장),
  네트워크/파싱/그 외 HTTP 실패만 `ok:false`.
- `getLivePrices()` → `{ ok, prices }` (`getRealPortfolio()`가 `error` 반환 또는 throw → `ok:false`).
- 동결 규칙(`freezeTurn()`):
  | 상황 | 기록 |
  |---|---|
  | 원장 `ok:false` **또는 데드라인 초과** | `pnl: null, by_tag: {}, degraded: 'ledger_unavailable'` |
  | 보유 종목 있는데 시세 `ok:false` | `pnl: null, by_tag: {}, degraded: 'prices_unavailable'` |
  | 보유 종목 없음 + 시세 실패 | **정상 기록**(확정분 by_tag만으로 정확) |
  | 원장 turn id ≠ config turn id (파이썬 미실행) | `pnl: 0`, degraded **없음** ← 실패가 아니다 |
  | 정상 | `pnl: number`, degraded 없음 |
- 타입 `LastTurnResult`를 `src/lib/program-turn.ts`에서 export (프론트가 `pnl===null`을 "측정 불가"로 그림).
  `pnl: number | null`, `degraded?: 'ledger_unavailable' | 'prices_unavailable'`.

**브리프에서 한 곳 판단**: 시세 실패 시 `by_tag`를 브리프가 명시하지 않았다. `by_tag: {}`로 비웠다 —
`pnl`이 숫자일 때만 `pnl === sum(by_tag)`라는 불변식을 지켜, 프론트가 부분 합계를 전체 손익으로
그리는 사고를 원천 차단하기 위해서다. (확정분을 보여주고 싶다면 별도 필드로 다시 논의 필요.)

## 3. ⚪ Minor — `??` → `||`

`program-turn.ts`의 `Number(basis[code] ?? px)` → `Number(basis[code] || px)`.
파이썬 `new_turn()`의 기준가 폴백은 `opening_basis.get(c) or current_prices.get(c) or p.get('avg_price', 0)`
— **avg_price=0이면 basis에 0이 실제로 들어간다**. `??`는 0을 통과시켜 `(px - 0) * qty`, 즉 시가총액 전체가
턴 수익으로 계상된다.

## 4. 검증 — `npx tsc --noEmit`

```
$ npx tsc --noEmit 2>&1; echo "EXIT=$?"
EXIT=0
```
출력 없음, exit 0 → **0 errors**.

## 5. 검증 — kill-switch 지연 상한 **실측** (핵심 증거)

앞 리포트와 동일한 하네스 방식(진짜 `route.ts`를 CJS로 트랜스파일 → `Module._load` 훅으로
`next/server`·`next-auth/jwt`·`@/lib/manifest-sims`·`@/lib/kis-api` 스텁, `@/lib/program-turn`은 **진짜 구현**,
`global.fetch`로 GitHub 흉내). 이번엔 **원장 조회와 KIS 조회를 `new Promise(() => {})`로 영영 응답하지 않게**
만들고 OFF 요청의 벽시계 시간과 실제 PUT된 config 본문을 측정했다. 테스트용 재작성이 아니라 **배포될 코드 그 자체**를 실행했다.

```
=== [A] HANG 시뮬레이션 — 원장/시세가 영영 응답하지 않음 ===
PASS  원장 hang + 시세 hang                   2513ms  enabled=false  pnl=null  degraded=ledger_unavailable  by_tag={}  capital=3000000
PASS  원장 OK + 시세만 hang                    2501ms  enabled=false  pnl=null  degraded=ledger_unavailable  by_tag={}  capital=3000000

=== [B] 동결 degraded 경로 3종 ===
PASS  원장 조회 실패(500)                          0ms  enabled=false  pnl=null  degraded=ledger_unavailable  by_tag={}  capital=3000000
PASS  원장 네트워크 예외                             0ms  enabled=false  pnl=null  degraded=ledger_unavailable  by_tag={}  capital=3000000
PASS  시세 조회 실패(보유O)                          0ms  enabled=false  pnl=null  degraded=prices_unavailable  by_tag={}  capital=3000000
PASS  시세 실패+보유X → 정상기록                       0ms  enabled=false  pnl=300  degraded=-  by_tag={"sim5_sideways":300}  capital=3000000
PASS  파이썬 미실행(원장 turn id≠)                   0ms  enabled=false  pnl=0  degraded=-  by_tag={}  capital=3000000
PASS  원장 404(미생성)                            1ms  enabled=false  pnl=0  degraded=-  by_tag={}  capital=3000000

=== [C] 정상 경로(회귀) ===
PASS  정상 (확정300 + 미실현1000)                   0ms  enabled=false  pnl=1300  degraded=-  by_tag={"sim5_sideways":1300}  capital=3000000

원장 fetch에 AbortSignal 전달됨: YES

=== [D] ON 경로도 같은 hang에서 상한 내 완료 ===
PASS  ON: 원장+시세 hang             2504ms  enabled=true  capital=3000000  opening_basis={}  http=200

=== [E] ON 게이트 불변(fail-closed) ===
PASS  PIN 틀림                                      http=403  config기록=없음
PASS  화이트리스트 밖 sim                                http=400  config기록=없음
PASS  budget=0                                    http=400  config기록=없음

RESULT: 13/13 PASS
```

**핵심 수치: 조회가 영영 응답하지 않아도 OFF는 2.5초 안에 `enabled:false`를 PUT한다(2513ms / 2501ms).**
수정 전이라면 이 두 행은 fetch가 매달린 채 함수 타임아웃까지 갔고 config는 기록되지 않았다.
[A]의 두 번째 행(원장 OK + 시세만 hang)이 `ledger_unavailable`인 것은 의도대로다 — 데드라인 초과는
"원장을 확인하지 못했다"와 동일 취급(브리프 명시).

모든 행에서 `selected_sim="sim5_sideways"`, `budget=3000000`이 **원래 config 값 그대로** 유지됐다(보안 교정 보존).
[E]는 PIN/화이트리스트/`budget>0` 게이트가 여전히 config를 쓰지 않고 차단함을 재확인한다(한 줄도 안 건드림).

## 6. 검증 — `??` → `||` 회귀 (진짜 함수 실행)

```
$ node -e "... computeTurnPnl({basis:{'005930':0}, ...}, {'005930':{quantity:10,avg_price:0}}, {'005930':70000})"
basis=0 (파이썬 avg_price=0 폴백 경로) → pnl = 0 {"sim5":0}
기대: 0 (??였다면 700000 = 시가총액 전체가 수익으로 계상)
PASS
```

## 7. 불변식 준수

- 원장(`program_positions.json`)은 여전히 **읽기 전용**(GET만, PUT 없음).
- `src/lib/kis-api.ts` **미변경** — 데드라인으로 감싸기만 했다.
- ON의 PIN 검증·레이트리밋·화이트리스트·`budget>0` fail-closed 게이트 **미변경**([E]가 실증).
- OFF는 `enabled`/`turn`/`last_turn_result`만 건드리고 `selected_sim`/`budget`은 안 덮어쓴다([A]~[C]가 실증).
- 브리프 밖 기능 추가 없음.

## 8. 남는 우려사항

1. **데드라인은 소켓을 취소하지 않는다.** `withDeadline`이 이기면 매달린 fetch는 백그라운드에 남는다
   (`getPositions`의 `AbortSignal.timeout(3000)`이 3초 뒤 정리하지만, KIS 쪽은 `kis-api.ts` 미수정 원칙상
   그대로 매달린다). 서버리스에서 응답 후 함수가 얼어붙으면 그 promise는 그냥 버려지므로 실害는 없다.
   다만 **`putConfig`(쓰기)에는 상한이 없다** — GitHub 쓰기 자체가 매달리면 OFF는 여전히 못 남는다.
   이건 이번 변경 이전부터 있던 성질이고 브리프도 "putConfig에는 데드라인을 걸지 말라"고 못박았다.
   진짜로 막으려면 별도 대책(예: 재시도 + 파이프라인 측 heartbeat/TTL)이 필요하다.
2. **2.5s는 KIS 정상 응답 시간을 자를 수 있다.** KIS 잔고 조회는 재시도 포함 수 초가 정상 범위다.
   장중 KIS가 느린 날 OFF를 누르면 `degraded: 'ledger_unavailable'`(데드라인)로 기록될 수 있다.
   **표시 정확도를 매매 정지보다 낮게 둔 의도적 트레이드오프**이며, 이제 최소한 조용히 0원으로
   박제되지는 않고 "측정 불가"로 남는다.
3. `getConfig()`(OFF 경로의 첫 조회)에는 여전히 타임아웃이 없다. 브리프가 범위 밖으로 지정했다.
   OFF는 이 조회 없이는 sha를 몰라 PUT을 못 하므로 데드라인을 걸 수도 없다 — 구조적 한계다.
   같은 `AbortSignal.timeout` 한 줄은 넣을 수 있으니 승인 주면 별도로 반영하겠다.

---

# Task 3 후속2: 리뷰 잔여 4건(Minor 2 / Nit 2) 수정 — 표시 정확성

앞 리뷰에서 남은 4건. 전부 "조회 실패 시 그럴듯한 숫자를 지어내지 말고 측정 불가로 표시하라"는
원칙의 연장선이며 매매 안전성(PIN/레이트리밋/화이트리스트/`budget>0`/OFF 2.5s 데드라인)은 손대지 않았다.

## 1. 수정 1(Minor) — ON 시 원장 조회 실패 시 `capital`이 `budgetNum`으로 조용히 축소 박제되던 문제

**위치**: `route.ts` 300~326행 (ON 경로, `withDeadline((async () => {...})())` 블록).

기존엔 `turn.capital = budgetNum`으로 초기화해두고 IIFE 안에서 무조건
`turn.capital = budgetNum + realized_pnl`로 덮어썼다 — 원장 조회가 실패해도 `realized_pnl`은
`getPositions()`의 실패 폴백값 `0`이므로 결과적으로 `budgetNum`(truthy)이 그대로 박제됐다.
파이썬(`program_trader.py`)은 `cfg_turn.get('capital') or effective_budget`으로 읽으므로 이 truthy한
잘못된 값을 그대로 채택 — 누적실현이 있으면 진짜 자본보다 축소된 값이 분모로 쓰인다.

**수정**: `getPositions()`의 `ok` 플래그를 확인해 `ok`일 때만 `budgetNum + realized_pnl`을,
실패/타임아웃이면 `0`(falsy)을 대입하도록 변경(316행):
```ts
const capital = ledgerOk ? budgetNum + realized_pnl : 0;
```
falsy면 파이썬의 `or effective_budget` 폴백이 살아나 올바른 값을 채운다.

## 2. 수정 2(Minor) — 보유 종목 있는데 시세 맵이 비어도 degraded가 안 붙던 문제

**위치**: `route.ts` `freezeTurn()` 130~137행.

`getLivePrices()`는 `getRealPortfolio()`가 `error`를 반환/throw할 때만 `ok:false`다. 성공 응답인데
`holdings`가 비었거나 모든 `price`가 0이면 `ok:true` + `prices:{}`가 되어 `held && !pricesOk` 가드를
통과, `computeTurnPnl`이 전 종목을 건너뛰어 미실현이 0인 채로 degraded 없이 확정분만 박제됐다.

**수정**: 보유 종목 중 양수 시세를 하나도 못 얻었으면 `prices_unavailable`로 취급(133~137행):
```ts
const noUsablePrice = held && !Object.keys(positions).some((c) => Number(prices[c]) > 0);
if (held && (!pricesOk || noUsablePrice)) return { ...base, capital, pnl: null, by_tag: {}, degraded: 'prices_unavailable' };
```

## 3. 수정 3(Nit) — 데드라인 초과가 `ledger_unavailable`로 오라벨되던 문제

**위치**: `src/lib/program-turn.ts` 32행(`LastTurnResult.degraded` 유니온에 `'timeout'` 추가),
`route.ts` 251~259행(OFF 경로 데드라인 폴백).

데드라인(2.5초) 초과는 원장이 정상인데 KIS/GitHub가 느렸을 수도 있다는 뜻인데, 즉시 HTTP
실패(`ledger_unavailable`)와 같은 라벨로 묶여 사후 원인 규명이 어려웠다.

**수정**: `LastTurnResult['degraded']`에 `'timeout'` 추가(export 타입, 프론트가 참조), OFF의
`withDeadline` 폴백 객체의 `degraded`를 `'ledger_unavailable'` → `'timeout'`으로 변경(258행).
`freezeTurn()` 내부의 즉시 HTTP 실패 경로(123행)는 그대로 `'ledger_unavailable'`.

## 4. 수정 4(Nit) — ON의 IIFE가 `turn`을 in-place mutate하던 구조

**위치**: `route.ts` 300~326행.

데드라인이 이겨도 백그라운드 IIFE가 나중에 `turn` 객체를 계속 건드릴 수 있는 구조였다(현재는
`await withDeadline` 직후 `putConfig`까지 동기 실행이라 우연히 안전했을 뿐).

**수정**: IIFE가 `{ capital, opening_basis }`를 **반환**하도록 바꾸고(`return` 추가, `turn.xxx = ...`
in-place 대입 제거), 호출부가 `withDeadline`의 반환값(`opened`)으로 `turn`을 구성하도록 변경:
```ts
const opened = await withDeadline((async () => { ...; return { capital, opening_basis: basis }; })(),
    DISPLAY_DEADLINE_MS, { capital: 0, opening_basis: {} });
const turn: any = { id: new Date().toISOString(), started_at: now, capital: opened.capital, opening_basis: opened.opening_basis };
```
`turn`은 이 지점 이전엔 존재하지 않으므로 이후 어떤 `await`가 끼어들어도 늦게 끝난 IIFE가
이미 구성된 `turn`을 건드릴 여지가 구조적으로 없다.

## 5. 검증 — `npx tsc --noEmit`

```
$ npx tsc --noEmit 2>&1; echo "EXIT=$?"
EXIT=0
```
출력 없음, exit 0 → **0 errors**.

## 6. 검증 — 실측 하네스 (배포될 코드 그 자체를 실행)

기존 하네스와 동일 방식: `npx tsc route.ts program-turn.ts --module commonjs`로 진짜 코드를
CommonJS로 트랜스파일 → `Module._load`로 `next/server`·`next-auth/jwt`·`@/lib/manifest-sims`·
`@/lib/kis-api`를 스텁, `@/lib/program-turn`은 **트랜스파일된 진짜 구현**을 그대로 사용,
`global.fetch`로 GitHub API를 흉내. route가 GitHub에 PUT한 config 본문을 캡처해 단언(assert)했다.

```
=== [1] 회귀: OFF hang(원장+시세 무응답)이어도 2.5s 내 enabled:false PUT ===
PASS  OFF: 원장+시세 모두 hang                         2513ms  enabled=false turn=null elapsed=2513ms (<=2.5s 확인)

=== [2] 수정1: ON 시 원장 조회 실패/타임아웃 → turn.capital === 0 (falsy) ===
PASS  ON: 원장 500 (조회실패)                             1ms  turn.capital=0 (기대: 0, falsy)
PASS  ON: 원장 정상(realized=50만) → capital=budget+realized      0ms  turn.capital=3500000 (기대: 3,500,000 = 300만+50만)
PASS  ON: 원장+시세 hang(데드라인 초과) → capital=0        2512ms  turn.capital=0 elapsed=2512ms (기대: 0, <=2.5s)

=== [3] 수정2: 보유종목 있는데 시세맵이 비었거나 전부 0 → degraded:prices_unavailable ===
PASS  OFF: 보유O, KIS holdings=[] (ok:true, 시세 없음)      0ms  degraded=prices_unavailable pnl=null
PASS  OFF: 보유O, KIS holdings 있으나 price=0 전부 (ok:true)      0ms  degraded=prices_unavailable pnl=null
PASS  OFF: 보유O, 정상 시세(회귀 확인, degraded 없어야 함)        0ms  degraded=undefined pnl=1300 (기대: undefined, 1300)

=== [4] 수정3: OFF 데드라인 초과 → degraded:timeout (ledger_unavailable과 구분) ===
PASS  OFF: 원장 hang(데드라인 초과)                      2512ms  degraded=timeout elapsed=2512ms
PASS  OFF: 원장 500(즉시 실패) → 여전히 ledger_unavailable      1ms  degraded=ledger_unavailable elapsed=1ms (즉시 실패는 timeout 아님)

=== [E] 게이트 회귀 확인(fail-closed 불변, 4건 수정과 무관히 안 건드렸는지) ===
PASS  PIN 틀림                                        0ms  http=403 config기록없음
PASS  화이트리스트 밖 sim                                  0ms  http=400 config기록없음
PASS  budget=0                                      0ms  http=400 config기록없음
PASS  OFF: selected_sim/budget 보존(보안 교정 회귀)         1ms  selected_sim/budget 원본 유지

RESULT: 13 PASS, 0 FAIL
```

핵심 확인 사항:
- **hang 시(원장·시세 둘 다 무응답) OFF가 여전히 2.5초 내에 `enabled:false`를 PUT함**: 2513ms — 이번
  변경(특히 수정 4의 구조 변경)이 데드라인 보호를 약화시키지 않았음을 재확인.
- 수정 1: 원장 조회 실패 시 `turn.capital === 0`(정상 시 `3,500,000`과 대비).
- 수정 2: 보유O + 시세 맵 비었거나 전부 0가 → `degraded: 'prices_unavailable'`, `pnl: null`.
- 수정 3: 데드라인 초과 → `degraded: 'timeout'` (즉시 HTTP 500은 여전히 `ledger_unavailable'`로 구분).
- PIN/화이트리스트/`budget>0` 게이트, OFF의 `selected_sim`/`budget` 불변 보존 — 전부 회귀 없음.

## 7. 불변식 준수

- ON의 PIN 검증·레이트리밋·화이트리스트 검증·`budget>0` fail-closed 게이트: 미변경(코드 위치도 그대로).
- OFF는 여전히 `enabled`/`turn`/`last_turn_result`만 변경([E] 마지막 행이 실증).
- `withDeadline`(2.5초) 로직 자체는 미변경 — 감싸는 대상(IIFE의 반환 형태)만 바꿨다. `putConfig`에는
  여전히 데드라인 없음.
- 원장(`program_positions.json`)은 계속 읽기 전용, `src/lib/kis-api.ts` 미수정.
- 지시된 4건 외 리팩터링 없음.

## 8. 남는 우려사항

없음. 이번 4건은 모두 표시 정확성 문제였고 실측으로 각각 확인했다. §7·§8(이전 라운드)에 남아있던
"putConfig에 데드라인 없음"·"2.5s가 KIS 정상 응답을 자를 수 있음"·"getConfig 타임아웃 없음"은
이번 지시 범위 밖이라 그대로 남아 있다.
