# 🏛️ Stock-Analysis & Auto-Trading Robot: 최종 기술 정의서 (Definitive Blueprint)

본 문서는 프로젝트의 모든 로직, 알고리즘, UI 구성 및 자동화 체계를 100% 명문화한 "Reconstruction Guide"입니다. 본 문서를 통해 제3의 개발자가 시스템을 처음부터 끝까지 동일하게 재구축할 수 있음을 보증합니다.

---

## 1. 전역 시스템 아키텍처 (Global Architecture)

시스템은 분산형 하이브리드 자동화 구조를 가집니다.

- **Trigger Layer**: `Tasker (Android App)`가 정해진 스케줄(보통 정시)마다 Vercel API(`/api/cron`) 호출.
- **Orchestration Layer**: `Vercel API`가 호출을 받아 KST 요일 검증(주중만 실행) 후 `GitHub Workflow Dispatch` 실행. (내부 시간 제약 없이 호출 즉시 실행)
- **Execution Layer**: `GitHub Actions (Ubuntu Runner)`가 Python 스크립트 실행. 
- **Storage Layer**: `GitHub db-data branch`를 NoSQL 데이터베이스처럼 활용 (JSON/XLSX 저장).
- **Presentation Layer**: `Next.js 14 (Vercel)` 대시보드가 GitHub의 Raw 데이터를 직접 Fetch하여 시각화.

---

## 2. 데이터 수집 엔진 (Scraper Specifications)

### 2.1 타겟 및 범위
- **플랫폼**: 네이버 금융 (finance.naver.com)
- **대상**: KOSPI/KOSDAQ 전일 대비 상승률 상위(sise_rise) 각각 **35개**, 총 70개 종목.
- **수집량**: 각 종목당 네이버 종목토론실 게시글 최근 **800개**.

### 2.2 상세 알고리즘
- **셀렉터**: 
  - 종목 리스트: `table.type_2 > tr`
  - 종목 정보: `td[1]`(이름/코드), `td[2]`(현재가), `td[4]`(등락률)
- **시간 필터**: 게시글 작성 시각이 당일 **08:00 KST** 이후인 것만 수집.
- **안티-블로킹**: 
  - `User-Agent` 랜덤화.
  - 페이지 전환 시 **0.5초** `time.sleep` 적용.
  - ETF/ETN 종목 제외 (KODEX, TIGER, ACE 등 키워드 필터링).

---

## 3. 지능형 분석 엔진 (Analysis & Intelligence)

### 3.1 가중치 감성 분석 (Weighted Sentiment Model)
각 게시물의 중요도를 아래 공식으로 산출하여 분석에 반영합니다.
- **게시물 점수**: `Score = (조회수) + (공감수 * 30)`
- **점수 보정**:
  - **Penalty**: 본문 내용 50자 미만 혹은 2줄 이하 시 점수 **-80% (0.2 곱함)**.
  - **Bonus**: 본문에 **예측성 키워드** 포함 시 **+2000점**.
    - **예측 키워드 예시**: `목표`, `예상`, `전망`, `분석`, `이유`
- **감성 분석 키워드**:
  - **Positive (긍정)**: `상승`, `급등`, `호재`, `대박`, `매수`, `가즈아`, `축하`, `수익`, `기대`, `찬티`
  - **Negative (부정)**: `하락`, `폭락`, `악재`, `손절`, `매도`, `망`, `개미털기`, `설거지`, `폭망`, `안티`
- **콘텐츠 요약**: 점수 상위 **4개** 게시물의 제목을 추출하여 `posts_summary` 생성.

### 3.2 핵심 지표 알고리즘
- **PQI (Post Quality Index)**: `(총 공감수 / 총 조회수) * 100`. 커뮤니티 신뢰도 측정 지표.
- **Anti-FOMO**: 과거 5일간 누적 상승률이 **50%** 초과 시 추천 제외.
- **외인 Divergence**: 외국인 지분율이 전일 대비 하락했으나 주가가 상승 중인 경우 "수급 이탈"로 판단.

---

## 4. 텔레그램 알림 체계 (Sentinel-V)

### 4.1 알림 유형 및 조건
1. **[BUY_SIGNAL]**: Gemini AI가 승인(`APPROVED`)하고 `SPARK_POSTS_MIN` (400건) 이상 발생 시.
2. **[Advisory: Trailing Stop]**: 최고점 대비 **-4%** 하락 시 이익 실현 알림.
3. **[Advisory: Stop Loss]**: 매수가 대비 **-5%** 하락 시 손절 알림.
4. **[Advisory: Overheat]**: 게시글 **800건** 초과 시 과열 경고.

---

## 5. 포트폴리오 및 매매 로직 (Portfolio Logic)

### 5.1 Gemini 가상 매매 (Paper Trading)
- **초기 자본**: 3,000,000 KRW (가상).
- **종목 비중**: 자산 대비 최대 **20%** 배분.
- **BULL**: 익절 20%, 손절 -7%, 보유 10일.
  - **BEAR/NEUTRAL**: 익절 10%, 손절 -5%, 보유 7일.
- **매매 타이밍**: 별도의 내부 스케줄 없이, **태스커에 의해 스크래퍼가 실행될 때마다(Run on Trigger)** 즉시 분석 및 매매 로직 집행.
- **수수료 체계**: 매수 0.015%, 매도 0.2115% (제비용 포함).

### 5.2 KIS 실거래 인증 (`auth.py`)
- **토큰 관리**: `issued_at`를 파일에 기록하여 24시간 내 동일 날짜일 경우 재발급 없이 기존 토큰 사용.
- **자동 갱신**: API 호출 중 `401 Unauthorized` 발생 시 토큰 파일을 삭제하고 즉시 재발급 프로세스 진입.

---

## 6. 웹 대시보드 인터페이스 (Web UI)

### 6.1 기술 스택: Next.js 14 + Mantine 7.x
- **Trade Page (`/trade`)**:
  - 잔고 조회: `api/trade/account-balance` 연동.
  - 주문 폼: 일반 주문 및 **PIN 번호(4자리)** 기반 보안 확인.
  - 예약 매매: 클라이언트 측 `useInterval` (30초)을 통한 스케줄 체크 로직.
- **Research Page (`/research`)**:
  - 히스토리 뷰어: `reports.json`을 통해 과거 엑셀/JSON 리포트 인덱싱.
  - 시각화: `Sparkline` 컴포넌트를 사용하여 5일간의 **가격-거래량-토론량** 추이 차트 제공.

---

## 7. 데이터 스키마 (Data Schemas)

### 7.1 `reports.json`
```json
[
  { "type": "daily", "date": "YYYY-MM-DD HH:MM", "filename": "...", "count": 100, "timestamp": 12345 }
]
```

### 7.2 `gemini_portfolio.json`
```json
{
  "cash": 3000000,
  "holdings": { "CODE": { "qty": 10, "avg_price": 1000, "days_held": 2, "name": "..." } },
  "trade_log": [], "market_regime": "NEUTRAL"
}
```

---

## 8. 환경 설정 (Environment Variables)
- `KIS_APP_KEY / KIS_APP_SECRET`: 실거래용.
- `TELEGRAM_BOT_TOKEN / CHAT_ID`: 알림 시스템용.
- `GEMINI_API_KEY`: 전략 Advisor 및 요약용.
- `GITHUB_PAT`: 데이터 저장 및 Actions 실행용.
