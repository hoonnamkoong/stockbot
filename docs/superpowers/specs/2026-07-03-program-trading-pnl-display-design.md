# 프로그램 매매 수익률/평가손익 별도 표시 설계

## 배경

실전 계좌 카드(`/trade`)는 현재 예수금·총자산수익률·총평가손익을 KIS 브로커가 계산한 "계좌 전체" 기준으로 보여준다. 프로그램 매매(자동 심 운용)는 자체 원장(`program_positions.json`, 비공개 stockbot-secret 레포)에 `positions{code:{avg_price,quantity,name}}`와 `realized_pnl`(누적 실현손익)을 따로 관리하는데, 이 데이터가 프론트엔드에 전혀 노출되지 않는다. 프로그램 매매만의 수익률/평가손익을 별도로 보여주고, 향후 프로그램 예산을 추가/변경해도 코드 수정 없이 자동으로 반영되도록 한다.

## 요구사항

- 기존 예수금/총자산수익률/총평가손익 표시는 그대로 유지한다.
- "프로그램 매매 수익률(%)"과 "프로그램 매매 평가손익(원)"을 별도로 표시한다.
- 프로그램 예산(budget)이 나중에 추가되거나 바뀌어도 자동으로 반영되어야 한다(재계산 로직에 하드코딩 없음).

## 데이터 소스 및 계산

- `realized_pnl`: `program_positions.json`의 누적 실현손익(원장, sell 체결 시마다 누적).
- `unrealized_pnl`: 각 포지션의 `(현재가 - avg_price) * quantity` 합. 현재가는 이미 실시간 폴링 중인 `balance.holdings`(브로커 시세)에서 code로 매칭해 가져온다. 매칭 실패 시(외부 개입 등 예외) `avg_price`로 대체해 기여분을 0으로 처리한다.
- `total_pnl = realized_pnl + unrealized_pnl`
- `total_pnl_rate = budget > 0 ? total_pnl / budget * 100 : 0` — 분모는 현재 confirmed budget(설정 예산). 예산이 바뀌면 그 시점부터 새 기준으로 계산된다(과거 기간을 소급 재계산하지 않음, `program_trader.py`의 `effective_budget` 로직과 별개로 "원금 대비 수익률" 관점의 표시용 지표).

## 백엔드 변경

`src/app/api/trade/program/route.ts` (GET만 변경, POST 불변):

- `getPositions()` 함수 추가 — `program_positions.json`을 stockbot-secret repo에서 조회(기존 `getConfig()`와 동일한 GitHub Contents API 패턴, 동일 인증/브랜치 사용).
- 404(파일 없음, 한 번도 실행 안 됨) 또는 조회 예외 시 `{ positions: {}, realized_pnl: 0 }`로 안전하게 대체(swallow). 이 필드는 표시 전용이므로 실패해도 기존 GET 응답(enabled/selected_sim/budget/sims)의 성공을 막지 않는다.
- GET 응답에 `positions`(원장의 code별 `{name, quantity, avg_price}`)와 `realized_pnl`(number) 필드를 추가한다.

## 프론트엔드 변경

`src/app/trade/TradeClient.tsx`:

- state 추가: `programPositions`(`Record<string, {name, quantity, avg_price}>`, 기본 `{}`), `programRealizedPnl`(number, 기본 0).
- `fetchProgram()`에서 응답의 `positions`, `realized_pnl`을 파싱해 반영.
- `renderRealPortfolioSection()` 내부, 기존 예수금/총자산수익률/총평가손익 `Group`(grow, 3칸) 바로 아래에 조건부로 새 `Group`(grow, 2칸)을 추가:
  - "프로그램 매매 수익률" — `total_pnl_rate`, 부호에 따라 red(+)/blue(-), 기존 총자산수익률과 동일한 스타일(`fw={800}`, `size="lg"`).
  - "프로그램 매매 평가손익" — `total_pnl`(원), 부호에 따라 red/blue, 기존 총평가손익과 동일 스타일(`fw={700}`, `size="lg"`).
- 표시 조건: `Number(programBudget) > 0 || Object.keys(programPositions).length > 0 || programRealizedPnl !== 0` 일 때만 렌더링. 세 조건이 모두 거짓(프로그램 매매를 한 번도 설정한 적 없음)이면 이 두 항목 자체를 렌더링하지 않는다. 예산을 처음 넣거나 포지션이 생기는 순간부터 자동으로 나타난다.
- 계산은 렌더 시점마다 `balance`(30초 폴링) · `programBudget` · `programPositions` · `programRealizedPnl`로부터 인라인으로 도출한다(별도 메모이제이션 불필요, 이 화면 규모에서는 과함).

## 테스트/검증 계획

- 이 기능은 순수 프론트/백엔드 API 변경(파이썬 매매 로직 무변경)이라 별도 유닛 테스트 인프라가 없다. 다음으로 검증한다:
  - `npx tsc --noEmit` (또는 기존 빌드 스크립트)로 타입 오류 없는지 확인.
  - `program_positions.json`이 없는 경우(로컬 개발 환경 = 항상 이 상태, secret repo 접근 불가)에도 GET `/api/trade/program`이 500 없이 정상 응답하고 `positions: {}, realized_pnl: 0`을 반환하는지 확인.
  - budget=0이고 포지션 없는 초기 상태에서 새 UI 블록이 렌더링되지 않는지(기존 화면과 시각적으로 동일한지) 확인.
  - (배포 후, 실제 secret repo에 원장이 존재하는 프로덕션에서) 프로그램 매매 수익률/평가손익 숫자가 `realized_pnl + unrealized_pnl` 계산과 일치하는지 눈으로 확인.

## 범위 밖

- `program_trader.py`(매매 실행 로직)는 변경하지 않는다 — 순수 표시 기능.
- 프로그램 매매 예산 변경 UI/PIN 플로우는 기존 그대로 유지, 변경 없음.
- 히스토리성 차트(시간에 따른 프로그램 수익률 추이)는 이번 스코프에 포함하지 않는다 — 현재 시점 스냅샷만 표시.
