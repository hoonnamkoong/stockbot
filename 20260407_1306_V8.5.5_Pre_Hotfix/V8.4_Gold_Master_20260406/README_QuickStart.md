# README_QuickStart: V8.4 Gold Master (2026-04-06)

이 가이드는 **V8.4: Attention Deep-Dive & Real-Trade** 시스템을 즉시 가동하기 위한 핵심 매뉴얼입니다.

## 1. 환경 구축 (Environment Setup)
- **Python**: 3.10 이상 권장.
- **의존성 설치**: `pip install -r requirements_V8.4.txt`
- **환경 변수**: 제공된 `.env` 파일이 `V8.4_Gold_Master_20260406` 최상위에 위치해야 합니다. (KIS API Key, Gemini API Key 포함)

## 2. 핵심 실행 명령어 (Execution)
- **메인 스크래핑 및 분석**:
  ```bash
  python scraper.py
  ```
  *(수동 강제 실행 시: `.env`에서 `FORCE_RUN=true` 설정)*
- **실거래 예약 및 주문 집행**:
  ```bash
  python src/trade_executor.py
  ```

## 3. 파일 구조 및 역할 (Key Components)
- `scraper.py`: 데이터 수집 및 3단계 깔때기 분석 엔진의 시작점.
- `src/strategy/advisor.py`: Gemini AI를 통한 딥다이브 리포트 생성기.
- `data/status.json`: 현재 시스템의 업데이트 상태 및 예약 주문 목록(PENDING) 저장.
- `data/latest_stocks.json`: 웹 대시보드와 연동되는 최종 분석 결과 데이터.

## 4. 트러블슈팅 (Troubleshooting)
- **텔레그램 알림 누락**: `FORCE_RUN=true`를 사용하여 알림 보호 로직을 우회하세요.
- **KIS API 에러(7)**: 시스템이 자동 재시도(5회)를 수행합니다. 지속될 경우 네트워크 상태를 확인하세요.
- **AI 감성 분석 0점 현상**: V9.5 패치로 해결되었습니다. AI가 원본 데이터를 읽지 못할 경우 로그에서 `[Raw Data]` 누락 여부를 확인하세요.

---
*Last Updated: 2026-04-06 (V8.4 Gold Master Milestone)*
