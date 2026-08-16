# 실거래 매매 히스토리 ROI 계산 — 설계

- 날짜: 2026-07-15
- 대상: 실거래(real) 매매 히스토리의 ROI 표시
- 관련 원칙: [[no-fabricated-financial-values]] (조회 실패를 0으로 폴백 금지, "측정 불가" 명시)

## 문제

실거래 매매 히스토리의 ROI 열이 대부분 `-`로만 표시된다.

원인: `getRealTradeHistory`(`src/lib/kis-api.ts`)가 일별체결 API
(`inquire-daily-ccld`)의 `evlu_pfls_rt`(평가손익률) 필드를 그대로 `roi`로 쓴다.
이 API는 체결 단건에 실현손익/원가를 채워주지 않아 값이 사실상 비어 있다.

요구사항: 매도 시점에 "매수한 금액 대비 매도 금액의 차액"을 계산해
**ROI(%)** 와 **ROI(금액)** 를 함께 표시한다.

## 방식 결정 (사용자 확정)

- **매수 원가 소스**: KIS 실현손익 전용 API 사용 (수수료·세금 반영, 정확).
- **원가를 못 구하는 경우**: 0/가짜값 금지, **"측정 불가"** 명시.
- **표시**: ROI(%) 열과 ROI(금액) 열을 **분리**.
- **범위**: 실거래(real)만. 시뮬레이터 히스토리 ROI는 손대지 않는다.

## 아키텍처

### 데이터 소스

1. `inquire-daily-ccld` (TR `TTTC8001R` / 모의 `VTTC8001R`)
   — 기존. BUY/SELL 체결 단건 목록. 실현손익 없음.
2. `inquire-period-trade-profit` (**기간별매매손익현황조회**, TR `TTTC8715R`)
   — **신규**. 매도 건별 매수금액·매도금액·실현손익·손익률을 KIS가 계산해 반환.

두 API를 같은 기간(from~to, 기본 오늘~30일 전)으로 호출한다.

### 조인 로직

매도 체결 행(ccld의 `SELL`)에 실현손익 API 결과를 매칭한다.

- 신규 헬퍼 `getRealizedProfitMap(from, to)`:
  실현손익 API를 호출해 `${종목코드}_${매매일자}` 키로 버킷(bucket)을 만든다.
  각 버킷 값은 매도 건 리스트: `{ sellQty, roiPct, roiAmount }`.
- `getRealTradeHistory` 내부:
  - 두 API를 모두 호출(실현손익 조회 실패는 빈 맵으로 폴백 — 전체 "측정 불가"로 귀결).
  - 각 SELL 체결 행에 대해 `종목코드+일자` 버킷을 찾아 **수량 기준 FIFO**로
    소진하며 `roi`(손익률 %)·`roiAmount`(실현손익 금액)를 부여.
  - **BUY 행**: 실현 개념 아님 → ROI 미부여(프론트에서 `-`).
  - **SELL인데 매칭 실패**(버킷 없음/수량 초과/API 미지원):
    `roi`·`roiAmount` 미부여 → 프론트에서 **"측정 불가"**.

### 반환 필드 (real 항목)

기존 필드에 추가:

- `roi`: 손익률 문자열. 예 `"+3.2"` 또는 `"-1.5"` (부호 포함, `%` 기호는 프론트에서).
- `roiAmount`: 실현손익 금액(number, 원). 예 `12400`, `-3200`.
- SELL 매칭 실패 시 두 필드 모두 `undefined`.

프론트에서 BUY(action==='BUY')와 "매칭 실패 SELL"을 구분해야 한다:
- BUY → `-`
- SELL & roi === undefined → "측정 불가"
- SELL & roi 존재 → 값 표시

## KIS API 상세 (`TTTC8715R`)

- 엔드포인트: `/uapi/domestic-stock/v1/trading/inquire-period-trade-profit`
- 헤더: 기존 호출과 동일 패턴(authorization/appkey/appsecret/tr_id/custtype).
- 파라미터(확인 필요, 구현 시 KIS 문서 대조):
  `CANO`, `ACNT_PRDT_CD`, `SORT_DVSN`, `PDNO`(''=전체),
  `INQR_STRT_DT`, `INQR_END_DT`, `CBLC_DVSN`,
  `CTX_AREA_FK100`, `CTX_AREA_NK100`.
- output1 각 행(필드명 구현 시 대조): 종목코드, 매매일자, 매도수량,
  매수금액, 매도금액, 실현손익(`rlzt_pfls`류), 손익률(`pfls_rt`류).

**주의(구현 시 검증할 항목)**:
- 정확한 파라미터/필드명은 KIS 공식 문서로 대조한다. 이름이 틀리면
  조용히 빈 값이 오므로, 첫 실 호출 로그로 실제 응답 키를 확인한다.
- 페이지네이션(`CTX_AREA_NK100`)이 필요한 데이터량이면 후속 페이지 처리
  (30일·소량이면 단일 페이지로 충분할 수 있음 — 실제 응답으로 판단).

## 리스크

- **모의투자 계정**: `TTTC8715R`은 실계좌 전용일 수 있어 `IS_VIRTUAL`에선
  실패 가능. 이 경우 실현손익 맵이 비어 전체 SELL이 "측정 불가"로 표시된다.
  가짜값보다 정직하므로 허용. 미지원이면 그대로 둔다.
- **필드명 오추정**: 위 "주의" 참조. 첫 호출 로그로 실제 키 확정.

## 프론트 (`src/app/trade/TradeClient.tsx`)

`renderHistoryTable`의 `real` 분기:
- 헤더: 기존 `ROI(%)` 열 뒤에 `ROI(금액)` 열 추가.
- 각 행 셀:
  - ROI(%): 기존 부호색 뱃지 로직 재사용(`+`=red, `-`=blue).
  - ROI(금액): `roiAmount` 부호색으로 `+12,400원` / `-3,200원`.
  - BUY 행: 두 열 `-`.
  - 매칭 실패 SELL: 두 열 dimmed "측정 불가".

## 테스트 / 검증

- `getRealizedProfitMap`의 조인·FIFO 소진 로직: 단위 테스트
  (같은 종목·같은 날 복수 매도, 수량 초과, 버킷 없음 케이스).
- 실 계정 대상 첫 호출 로그로 실제 응답 키·값 확인 후 필드 매핑 확정.
- 프론트: BUY=`-`, 매칭성공 SELL=값, 매칭실패 SELL="측정 불가" 3케이스 육안 확인.

## 범위 밖 (YAGNI)

- 시뮬레이터 히스토리 ROI(별도 CSV `roi` 필드) 변경 없음.
- 미실현(보유 중) 손익 표시는 기존 포트폴리오 섹션이 담당 — 이번 범위 아님.
