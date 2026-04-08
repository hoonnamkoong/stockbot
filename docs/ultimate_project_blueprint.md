# 💎 Stock Trading System: 완성형 마스터 청사진 (Ultimate Project Blueprint)

본 문서는 시스템의 모든 구성 요소, 데이터 체계, 가상 매매 로직, 웹 서비스 구성 등을 총망라한 최종 기술 사양서입니다.

---

## 🏛️ 1. 전체 아키텍처 및 자동화 (Architecture & Automation)

시스템은 **Tasker**를 시발점으로 하여 클라우드 인프라가 유기적으로 작동하는 구조입니다.

- **실행 체인**: `Tasker (Android Mobile)` -> `Vercel API (route.ts)` -> `GitHub Actions (scraper.yml)` -> `Python (Bot Logic)` -> `GitHub db-data (Storage)`.
- **태스커(Tasker) 역할**: 매시간(정시) 실행 신호를 Vercel로 전송하여 전체 파이프라인의 스케줄러 역할을 수행.

---

## 📊 2. 데이터 조직 및 저장 체계 (Data Organization)

모든 데이터는 별도의 외부 DB 없이 GitHub의 `db-data` 브랜치 내 `data/` 디렉토리에 정형화된 파일 형태로 저장됩니다.

### 2.1 주요 데이터 파일
- **`gemini_portfolio.json`**: 제미나이 가상 매매 계좌 현황 (예수금, 보유 종목, 매매 이력).
- **`reports.json`**: 수집된 분석 리포트의 메타데이터 및 인덱스 정보.
- **`status.json`**: 시스템의 최근 실행 결과, 성공 여부, 분석된 종목 통계.
- **`kis_token.json`**: 한국투자증권 API 접근 토큰 (발급 시각 기록을 통한 당일 재사용 로직 포함).
- **`trending_integrated_*.xlsx`**: 텍스트 분석, 수급 분석, AI 요약이 통합된 심층 엑셀 리포트.

---

## 🤖 3. 제미나이 가상 포트폴리오 로직 (Gemini Virtual Trading)

Gemini AI의 분석 결과를 바탕으로 실제 자산 운용을 시뮬레이션하는 코어 로직입니다.

- **기본 설정**: 초기 자본금 300만 원, 종목당 최대 비중 20% 제한.
- **시장 상황(Regime) 기반 매매 전략**:
    - **BULL (상승장)**: 익절 20%, 손절 -7%, 최대 보유 10일.
    - **BEAR/NEUTRAL (하락/횡보장)**: 익절 10%, 손절 -5%, 최대 보유 7일.
- **매수 조건**: Gemini ML Probability가 60% 이상인 종목 선별.
- **매도 조건**: 목표 수익률 달성, 손절선 터치, 또는 보유 기간 초과(Time Stop). 이익 구간에서 모멘텀 하락 시 조기 익절 수행.

---

## 📱 4. 웹페이지 구성 및 UI 아키텍처 (Web Configuration)

Next.js 14 및 Mantine UI를 기반으로 하며, 데이터 대시보드 기능을 수행합니다.

### 4.1 핵심 페이지 구성
- **트레이딩 페이지 (`/trade`)**: 
    - KIS 실계좌 및 Gemini 가상 포트폴리오의 실시간 상태 시각화.
    - `QuickOrderModal`을 통한 수동 주문 및 비중 조절 인터페이스 제공.
- **리서치 페이지 (`/research`)**: 
    - 68KB 규모의 대형 분석 페이지로, 과거 리포트의 히스토리 내역을 필터링하여 조회 및 다운로드 가능.

### 4.2 UI 컴포넌트 및 데이터 바인딩
- **컴포넌트 구조**: `AuthSessionProvider`로 사용자 인증을 관리하며, 모든 화면은 `MantineProvider`를 통해 일관된 디자인 시스템 적용.
- **데이터 로딩**: 클라이언트 측에서 GitHub REST API를 호출하여 `data/` 폴더의 JSON 파일을 직접 파싱 후 상태 관리에 반영.

---

## 📡 5. 데이터 수집 및 알림 로직 (Scraping & Telegram)

- **수집**: 시장당 상위 35개 종목, 종목당 **최대 800개** 토론글 수집.
- **Sentinel-V**: 실시간 감시 모듈이 매수/매도 시그널 및 보유 종목에 대한 어드바이저리 발송.
    - **콘텐츠 생성**: 등락률, 토론량, Gemini AI 요약(80자)이 결합된 카드 형태의 리포트 구성.

이 마스터 청사진은 시스템의 설계부터 실행, 시각화까지 모든 구현 세부 사항을 총괄합니다.
