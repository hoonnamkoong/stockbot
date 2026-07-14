# 실전 계좌 정보창 확장: 보유 총액 · 턴당 수익률 · 턴당 SIM별 수익률 설계

## 배경

실전 계좌 카드(`/trade`)는 현재 예수금·총자산수익률·총평가손익·프로그램 매매 수익률·프로그램 매매 평가손익 5개를 보여준다(2026-07-03 설계분). 여기에 4개를 추가한다.

- **보유 종목 총액** — 계좌 전체 보유 종목의 평가금액 합.
- **프로그램 매매 보유 종목 총액** — 프로그램 원장 포지션의 평가금액 합.
- **프로그램 매매 턴당 수익률** — 한 턴 동안의 수익률.
- **프로그램 매매 턴당 SIM별 수익률** — 턴 안에서 전략별 기여도.

앞의 2개는 프론트에 이미 있는 데이터로 계산되므로 표시만 추가하면 된다. 뒤의 2개는 원장에 없는 **턴(turn)** 개념을 새로 도입해야 한다.

## 턴의 정의

프로그램 매매를 **켠 시점부터 끈 시점까지**가 한 턴이다. 심 선택·예산 변경은 OFF 상태에서만 가능하므로(`TradeClient.tsx`의 Select/NumberInput이 `disabled={programEnabled}`), 턴 경계는 곧 config의 ON/OFF 전환과 일치한다.

프로그램을 OFF해도 보유 종목은 청산되지 않고 원장에 남는다(`program_trader.run_program_trading`은 OFF면 즉시 리턴). 따라서 새 턴은 이전 턴이 사둔 종목을 물려받은 채 시작할 수 있다.

## 회계 규칙 (확정)

### 1. 두 개의 회계 트랙을 분리한다

원장의 기존 `realized_pnl`은 **복리 계산의 근거**다(`effective_budget = budget + realized_pnl`). 여기에 턴 회계를 섞으면 매매 로직이 오염된다. 그래서 턴 회계는 완전히 별도 트랙으로 둔다.

| 트랙 | 기준가 | 용도 | 변경 |
|---|---|---|---|
| `realized_pnl` (기존) | `avg_price` (평단) | 복리 → `effective_budget` | **불변** |
| 턴 회계 (신규) | `basis` (기준가) | 표시 전용 | 신규 |

**`basis`(기준가)** 는 턴 시작·전략 스위칭 시점에 그 순간 시세로 리셋되는 값이다.

두 트랙의 합계는 자연히 일치한다. 3,000원에 사서 턴1이 3,500원에 끝나고 턴2에서 3,700원에 팔면 — 턴1 +500, 턴2 +200, 합 +700 = 누적 실현손익 +700.

### 2. 턴 경계에서 MTM 리셋

턴이 시작될 때 물려받은 보유 종목의 기준가를 **그 시점 현재가**로 재설정한다. 이전 턴이 만든 미실현 이익이 새 턴 성과로 둔갑하지 않게 하여, 심별 비교를 공정하게 만든다.

프로그램이 OFF인 동안의 시세 변동은 **어느 턴에도 귀속되지 않는다**. 프로그램이 돌지 않은 구간이므로 의도된 동작이다.

### 3. 스위칭 시점에도 MTM 리셋 (Sim10)

Sim10은 Sim0의 국면 판단에 따라 하위 전략을 갈아탄다(BULL→Sim4-1, SIDEWAYS→Sim5, BEAR→전량 청산). 한 턴 안에서 국면이 바뀌면 턴 경계와 같은 문제가 한 번 더 생긴다.

동일 원칙을 적용한다. 스위칭 시점의 현재가를 새 기준가로 잡고, 직전 전략은 자기 구간에서 움직인 만큼만 확정 귀속받는다. 답하는 질문: **"어떤 국면 운용이 잘했나"**.

### 4. 턴 수익률의 분모

**턴 시작 시점 유효자본** = `budget + 턴 시작 시점의 누적 realized_pnl`. 그 턴에 실제로 굴린 돈이 분모가 되므로, 복리가 쌓인 뒤에도 턴간 수익률을 공정하게 비교할 수 있다.

### 5. OFF 시점 동결

OFF를 누른 순간의 턴 손익을 그대로 박제해 "직전 턴 결과"로 보여준다. OFF 이후의 시세 변동은 어느 턴의 성과도 아니므로 섞이지 않는다.

### 6. SIM별 수익률 = 기여도 분해

각 전략의 손익을 **같은 분모(턴 시작 유효자본)** 로 나눈다. 그래야 하위 전략 수익률의 합이 턴 수익률과 정확히 일치한다. 일반 심은 항목이 하나뿐이라 자연히 턴 수익률과 같아지고, Sim10만 여러 줄로 쪼개진다.

## 데이터 모델

### 원장 `program_positions.json` (파이썬이 유일 writer)

```jsonc
{
  "positions": {
    "005930": {
      "name": "삼성전자", "quantity": 10, "avg_price": 70000, "peak_price": 71000,
      "tag": "sim4_1"          // [신규] 이 종목을 현재 들고 있는 전략
    }
  },
  "realized_pnl": 123456,      // [기존] 평단 기준 누적. 복리용. 불변.
  "cooldown_codes": {}, "last_run": "...", "sim": "orchestrator",

  "turn": {                    // [신규] 턴 회계 (표시 전용)
    "id": "2026-07-14T09:05:00+09:00",   // config.turn.id 를 그대로 복사
    "capital": 1200000,                   // 턴 시작 유효자본 (분모)
    "basis": { "005930": 71000 },         // MTM 기준가
    "by_tag": { "sim4_1": 5000, "sim5": -1200 },  // 태그별 확정 손익
    "active_tag": "sim5"
  }
}
```

`tag`는 일반 심이면 `sim_id` 그대로, Sim10이면 하위 전략(`sim4_1` / `sim5` / `cash`)이다.

### config `program_trading.json` (프론트 route가 유일 writer)

```jsonc
{
  "enabled": true, "selected_sim": "orchestrator", "budget": 1000000,
  "turn": {                    // [신규] ON 시 기록
    "id": "2026-07-14T09:05:00+09:00",
    "started_at": "2026-07-14 09:05:00",
    "capital": 1200000,
    "opening_basis": { "005930": 71000 }   // ON 시점 시세 스냅샷 (실패 시 {})
  },
  "last_turn_result": {        // [신규] OFF 시 동결 기록
    "id": "...", "ended_at": "...", "sim": "orchestrator",
    "capital": 1200000, "pnl": 120000,
    "by_tag": { "sim4_1": 90000, "sim5": 30000 }
  }
}
```

기존의 **단일 writer 불변식**(config는 프론트만, 원장은 파이썬만)을 깨지 않는다. 턴 경계는 config가 열고 닫으며, 턴 중의 집계는 원장이 담당한다.

## 백엔드 변경

### `src/app/api/trade/program/route.ts`

**POST ON** — 서버가 `getRealPortfolio()`(`src/lib/kis-api.ts`)로 그 순간 시세를 받아, 원장 포지션에 대한 기준가 스냅샷을 만든다. `turn = { id, started_at, capital, opening_basis }`를 config에 함께 쓴다.
- `id`는 ON 시각(KST ISO). `capital = budget + 원장의 realized_pnl`.
- 잔고 조회 실패 시 `opening_basis: {}`로 두고 **ON은 정상 진행**한다(기준가는 파이썬 첫 실행 때 채우는 폴백). 표시용 지표가 매매 활성화를 막아선 안 된다.

**POST OFF** — 서버가 원장 + `getRealPortfolio()` 현재가로 턴 손익을 확정 계산해 `last_turn_result`를 config에 쓴다.
- 계산: `pnl = Σ by_tag + Σ(보유 종목의 (현재가 − basis) × 수량)`. 후자는 각 종목의 `tag`에 가산.
- 원장의 `turn.id`가 config의 `turn.id`와 다르면 이번 턴에 파이썬이 한 번도 돌지 않은 것(장 외 시간에 ON→OFF 등)이므로, `pnl: 0, by_tag: {}`로 기록한다.
- **이 계산 전체를 try/catch로 감싼다.** OFF는 kill-switch이므로 계산이 실패해도 `enabled: false` 기록은 무조건 성공해야 한다. 실패 시 `last_turn_result` 없이 OFF.
- 기존 보안 교정(OFF는 `enabled` 필드만 변경, `selected_sim`/`budget` 불변)은 그대로 유지한다. `turn`/`last_turn_result`만 추가로 건드린다.

**GET** — 응답에 `turn`(원장), `last_turn_result`(config)를 추가한다. 기존 `getPositions()`의 fail-safe 패턴(실패 시 빈 값, GET 전체를 막지 않음)을 그대로 따른다.

### `src/pipeline/workers/program_trader.py`

실행 흐름에 턴 회계를 끼워넣는다. **모든 턴 회계 코드는 예외를 삼켜, 실패해도 주문 경로를 막지 않는다.**

1. **턴 전환 감지** — `config.turn.id != ledger.turn.id`면 새 턴을 연다. `capital`은 config에서 받고, `basis`는 config의 `opening_basis`를 쓰되 비어 있으면 현재가로 채운다. `by_tag = {}`.
2. **활성 태그 결정** — `sim.run()` 직후 스냅샷에서 읽는다. Sim10은 `run()` 중 `state["active_regime"]`을 쓰므로(`sim10_orchestrator.py:54`), 프로그램 트레이더가 스냅샷 dict에서 그대로 읽을 수 있다. **Sim10은 수정하지 않는다.**
   - `BULL → sim4_1`, `SIDEWAYS → sim5`, `BEAR → cash`. 일반 심은 `sim_id`.
3. **스위칭 처리** — 활성 태그가 직전과 다르면: 보유 종목별 `(현재가 − basis) × 수량`을 직전 태그의 `by_tag`에 락인 → `basis`를 현재가로 리셋 → `positions[code].tag`를 새 태그로 갱신.
4. **체결 반영** —
   - 매도: `by_tag[active_tag] += qty × (체결가 − basis[code])`. **기존 `realized_pnl` 누적(평단 기준)은 그대로 병행 유지한다.**
   - 매수: `basis[code] = 체결가`, `positions[code].tag = active_tag`. (기존 포지션에 추가 매수 시 basis도 평단처럼 가중평균)
5. **원장 저장** — `turn`을 함께 기록.

`effective_budget` 계산, 주문 집행, 안전 게이트, kill-switch 재확인은 **일절 변경하지 않는다**.

## 프론트엔드 변경

`src/app/trade/TradeClient.tsx` — `renderRealPortfolioSection()`.

**기존 3칸 Group(예수금/총자산수익률/총평가손익)** 에 `보유 종목 총액`을 추가해 4칸으로. 값은 이미 계산된 `totalEval`을 그대로 쓴다.

**기존 프로그램 2칸 Group(수익률/평가손익)** 에 `프로그램 매매 보유 종목 총액`을 추가해 3칸으로. 값은 프로그램 포지션의 `현재가 × 수량` 합 — 현재가는 기존 `programUnrealizedPnl` 계산과 동일하게 `balance.holdings`에서 code로 매칭하고, 실패 시 `avg_price`로 대체한다.

**신규 Group** — 턴 지표:
- `프로그램 매매 턴당 수익률` — ON이면 원장 `turn`으로 실시간 계산, OFF면 config `last_turn_result`의 동결값. OFF일 때는 "직전 턴" 라벨을 붙인다.
- `프로그램 매매 턴당 SIM별 수익률` — `by_tag`를 손익 내림차순으로 나열. 각 항목은 `전략명 +X.XX%` 형태(분모는 턴 자본). 일반 심은 한 줄, Sim10은 여러 줄.

표시 조건은 기존 `programHasData` 패턴을 따른다 — 턴 데이터(`turn` 또는 `last_turn_result`)가 없으면 턴 Group 자체를 렌더링하지 않는다.

부호에 따른 red(+)/blue(−) 색상과 폰트 스케일은 기존 항목과 동일하게 맞춘다.

## 테스트/검증 계획

파이썬 매매 로직에 유닛 테스트 인프라가 없으므로, 순수 함수로 뽑아낼 수 있는 부분만 테스트한다.

- **턴 회계 순수 함수 테스트** — 기준가 리셋·락인·태그별 집계를 `program_trader`에서 순수 함수로 분리해(입력: 원장 dict + 체결 + 현재가, 출력: 갱신된 turn dict) 다음 시나리오를 검증한다:
  - 턴1에서 매수 후 미실현 → 턴2 시작 시 기준가 리셋 → 턴2에서 매도. 턴1 손익 + 턴2 손익 = 총 실현손익.
  - Sim10 BULL→SIDEWAYS 스위칭 시 직전 태그 락인 및 기준가 리셋.
  - `by_tag` 합 = 턴 총손익.
- **회귀 방지** — 기존 `realized_pnl` 누적값이 턴 회계 도입 전후로 동일한지(같은 체결 시퀀스에 대해).
- `npx tsc --noEmit` 통과.
- 원장/config에 `turn` 필드가 없는 기존 상태(마이그레이션 없이 배포)에서 GET이 500 없이 응답하고, 프론트가 턴 Group을 렌더링하지 않는지 확인.
- OFF POST에서 잔고 조회를 강제 실패시켰을 때도 `enabled: false`가 기록되는지 확인(kill-switch 무결성).

## 범위 밖

- 턴 히스토리(과거 여러 턴의 목록/차트) — 현재 턴과 직전 턴 하나만 보관한다.
- 기존 원장의 마이그레이션 스크립트 — `turn` 필드가 없으면 다음 ON에서 자연히 첫 턴이 열린다.
- Sim10 및 하위 전략(Sim4-1/Sim5) 로직 변경 — 태그는 기존 `active_regime`을 읽기만 한다.
- `realized_pnl`·`effective_budget`·주문 집행 로직 — 일절 손대지 않는다.
