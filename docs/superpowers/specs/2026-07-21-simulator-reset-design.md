# 시뮬레이터 리셋 버튼 — 설계 문서

- 작성일: 2026-07-21
- 목적: 대시보드에서 예수금을 입력하고 리셋하면, 모든 매매 시뮬레이터가 동일 예수금으로
  초기화되어 같은 조건에서 경쟁을 다시 시작한다.
- 상태: **설계 합의 완료, 미구현**

---

## 1. 요구사항 (사용자 확정)

- 예수금 입력 → 리셋 버튼 → **모든 매매 심이 해당 예수금만 가진 채 동일 조건에서 재경쟁**.
- **범위**: 상태 + 거래기록 **완전 클린슬레이트** (cash/포트폴리오/히스토리 초기화 + 거래기록 비움).
- **대상 심**: 매매하는 심 전부 = **Sim1~7 + Sim10** (9개). Sim0(리베로, 매매 없는 국면
  분석기)은 제외 — 국면 학습 데이터 보존. 실계좌는 무조건 제외.
- **보안**: 확인 모달만 (가상 자본이라 PIN 불필). 단, API는 로그인 세션 필요.

---

## 2. 현행 구조 (사전 조사)

- 심 상태는 **public db-data 브랜치**의 `data/sim_*_state.json`, 거래기록은
  `data/trade_history_sim_*.csv`에 저장(둘 다 db-data에 존재 확인).
- 프론트 읽기: `stats` 라우트가 `raw.githubusercontent.com/.../db-data/data/*.json`에서 조회
  (CDN 캐시 존재).
- 프론트 쓰기 경로: `program` 라우트가 **인증 Contents API**(GET sha → PUT base64)로
  GitHub에 기록. `GITHUB_PAT`(repo 스코프) 사용. 세션 가드는 next-auth `getToken`(미인증 401).
- `base_simulator.reset_state()`가 이미 원하는 초기화 shape를 정의(아래 §4.1과 동일). CSV는
  `os.remove` 후 첫 거래 시 헤더와 함께 재생성.
- 활성 매매 심 9개(id → 파일):

  | id | 상태 파일 | 거래기록 CSV |
  |---|---|---|
  | sim1 (psych) | sim_psych_state.json | trade_history_sim_psych.csv |
  | sim2 (spillover) | sim_spillover_state.json | trade_history_sim_spillover.csv |
  | sim3 (risk) | sim_risk_state.json | trade_history_sim_risk.csv |
  | sim4 (bull) | sim_bull_state.json | trade_history_sim_bull.csv |
  | sim4_daytrading | sim_bulldaytrade_state.json | trade_history_sim_bulldaytrade.csv |
  | sim5 (sideways) | sim_sideways_state.json | trade_history_sim_sideways.csv |
  | sim6 (bear) | sim_bear_state.json | trade_history_sim_bear.csv |
  | sim7 (reportfollower) | sim_reportfollower_state.json | trade_history_sim_reportfollower.csv |
  | sim10 (orchestrator) | sim_orchestrator_state.json | trade_history_sim_orchestrator.csv |

---

## 3. 접근법 결정

| 접근 | 내용 | 결정 |
|---|---|---|
| A. API가 db-data 직접 쓰기 | program과 동일 인증 Contents/Git API로 즉시 반영 | **채택** |
| B. GitHub Actions 워크플로우 | reset_state 재사용·직렬화되나 비동기·구성 복잡 | 미채택 |
| C. 리셋 플래그 → 다음 런 처리 | 경쟁조건 회피하나 수 시간 지연 | 미채택 |

**A 채택 이유**: 기존 패턴 동일, 즉시 반영, 리셋은 드문 수동 작업.

**★ 원자성**: "모든 심 동일 조건"이 목적이라 부분 실패(일부만 리셋)는 불공정. 파일별 개별 커밋
(18커밋, 비원자적) 대신 **Git Data API로 단일 원자 커밋**을 쓴다: 전부 반영 or 전부 무변경.

---

## 4. 설계

### 4.1 API 라우트 `POST /api/simulation/reset`
- **인증**: next-auth `getToken` — 미인증 시 401 (program 라우트와 동일).
- **입력**: `{ cash: number }`.
- **검증**: 정수, `100_000 ≤ cash ≤ 1_000_000_000`. 벗어나면 400.
- **상태 JSON (심별 생성, reset_state와 동일 shape)**:
  ```json
  {
    "initial_cash": <cash>, "cash": <cash>, "invested": 0, "portfolio": {},
    "peak_nav": <cash>, "total_fees": 0, "history": [<cash>], "daily_trades": [],
    "market_index_healthy": true, "cooldown_codes": {}
  }
  ```
  (Sim10 전용 필드(regime_log 등)는 담지 않는다 — 다음 run()이 재생성. 미존재 키는 심 로드 시
  `.get()` 기본값 처리라 안전.)
- **CSV**: 헤더 1행만 남김 — `﻿timestamp,symbol,action,price,quantity,total_amount,reason`
  (UTF-8 BOM 포함, base_simulator writer와 일치). 삭제 대신 헤더화 → history 라우트 404 처리 불필요.
- **커밋(원자, Git Data API)**:
  1. `GET /git/ref/heads/db-data` → 최신 커밋 sha
  2. 그 커밋의 tree sha 확보
  3. `POST /git/trees`(base_tree=현재) — 9 JSON + 9 CSV(총 18) blob을 inline content로 교체
  4. `POST /git/commits`(message, tree, parent)
  5. `PATCH /git/refs/heads/db-data`(force=false) — ref 이동
  - 5의 conflict(스크래퍼 동시 커밋)면 1~5 **1회 재시도**(최신 ref로). 그래도 실패면 500 반환
    (무변경 안전).
- **응답**: `{ success: true, cash, sims: [9개 id] }` 또는 오류.
- **파일 목록 공유**: stats 라우트의 심 목록과 중복되지 않게 공용 상수(`src/lib`)로 분리.

### 4.2 프론트 (TradeClient.tsx)
- 심 경쟁 카드 영역 근처에 **"시뮬레이터 리셋"** 블록:
  - 예수금 입력(number, 기본 `3000000`).
  - **리셋** 버튼.
- 클릭 → **확인 모달**: "9개 시뮬레이터를 {cash}원으로 초기화하고 거래기록을 모두 삭제합니다.
  되돌릴 수 없습니다. 계속하시겠습니까?"
- 확인 → `POST /api/simulation/reset` (busy 상태 처리) → 성공 알림 + stats 재조회.
- **UX 주의**: stats는 raw.github(CDN 캐시 ~수분)라 리셋 직후 화면 반영이 지연될 수 있음 →
  "리셋 완료. 대시보드 반영까지 잠시 걸릴 수 있습니다" 안내.

### 4.3 에러 처리
- 400(검증), 401(미인증), 500(GitHub 실패·conflict 재시도 후). 원자 커밋이라 부분 반영 없음.

---

## 5. 테스트
- **단위**: 리셋 페이로드 빌더(cash → 올바른 상태 JSON shape) + 검증 로직(범위 밖/비정수 거부).
- **수동**: 대시보드에서 리셋 → db-data 커밋 1건 확인(9 JSON 초기화 + 9 CSV 헤더화) → 대시보드
  반영 확인.

## 6. 알려진 한계
- **스크래퍼 경쟁조건**: 스크래퍼 런 중 리셋 시 그 런의 커밋이 리셋을 덮어쓸 수 있음(작은 창).
  드문 수동 작업이라 감수 — **런 사이에 리셋 권장**. [[db-data-verification-gotchas]]
- **CDN 반영 지연**: 리셋 후 stats(raw) 반영에 캐시 지연.
