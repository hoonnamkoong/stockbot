# 텔레그램 딥다이브 리포트 리디자인 스펙

**작성일**: 2026-06-01  
**범위**: `src/strategy/advisor.py`, `src/pipeline/workers/data_fetcher.py`, `src/trade/kis_data_provider.py`

---

## 배경 및 문제

KIS 데이터(PER/PBR/ROE/목표가 등)를 Gemini 프롬프트에 넣은 뒤 리포트가 수치 나열식으로 퇴화했다. 사용자에게 실제로 필요한 것은 "왜 이 종목이 지금 주목받는가" — 트렌드, 사회적 맥락, 배경 분석이다. 수치 데이터는 별도 블록으로 분리한다.

---

## 설계

### 1. 파이프라인 시작 시: 업종 평균 PER/PBR 스크래핑 캐시

**파일**: `src/pipeline/workers/data_fetcher.py` 또는 신규 `src/data/sector_cache.py`

- 네이버 업종별 시세 페이지(`https://finance.naver.com/sise/sise_group.naver?type=upjong`) 스크래핑
- 업종명 → 평균 PER, 평균 PBR 매핑 테이블 추출
- `data/sector_per_pbr.json` 저장 (TTL 1일, 기존 파일 mtime 체크)
- DataFetcherWorker.run() 초반에 1회 호출

**저장 형식**:
```json
{
  "updated_at": "2026-06-01T09:00:00",
  "sectors": {
    "소프트웨어": {"avg_per": 38.2, "avg_pbr": 4.1},
    "반도체": {"avg_per": 22.5, "avg_pbr": 2.8},
    ...
  }
}
```

### 2. 종목 스크래핑 시: 업종명 추출 (추가 API 호출 없음)

**파일**: `src/pipeline/workers/data_fetcher.py` — `_get_stock_details()`

기존 KIS `inquire-price` 응답(FHKST01010100)에서 추가로 추출:
```python
if out.get('bstp_kor_isnm'):
    details['sector_name'] = out['bstp_kor_isnm']  # 예: "소프트웨어"
```
추가 API 호출 없이 기존 호출 응답에서 파싱.

### 3. KIS 뉴스 타이틀 API 추가

**파일**: `src/trade/kis_data_provider.py` — 신규 메서드 `get_news_titles(code)`

```
TR ID: FHKST01011800
URL: /uapi/domestic-stock/v1/quotations/news-title
파라미터:
  FID_INPUT_ISCD: 종목코드
  FID_NEWS_OFER_ENTP_CODE: "" (전체)
  FID_COND_MRKT_CLS_CODE: ""
  FID_TITL_CNTT: ""
  FID_INPUT_DATE_1: ""  (현재 기준)
  FID_INPUT_HOUR_1: ""
  FID_RANK_SORT_CLS_CODE: ""
  FID_INPUT_SRNO: ""
```

반환값: 최근 뉴스 제목 5~7개 리스트 (`hts_pbnt_titl_cntt` 필드)  
캐시: TTL 30분  
딥다이브 시점(종목당 1회)에 호출.

### 4. Gemini 프롬프트 재설계

**파일**: `src/strategy/advisor.py` — `generate_deep_dive_report()`

**프롬프트에 포함 (맥락 분석용)**:
- 종목명, 현재가, 52주 위치 (고/저가 대비 %)
- 토론 요약 (`posts_summary`)
- 최근 뉴스 제목 5~7개 (KIS news-title API)
- 외인변화 (%p)

**프롬프트에서 제거**:
- PER, PBR, EPS, ROE, 부채비율
- 외인추정/기관추정 수량
- 증권사 투자의견, 목표가, 괴리율

**지시 변경**:
- 기존: "위 수치 데이터를 반드시 활용하여 분석"
- 변경: "이 종목이 왜 지금 주목받는지, 어떤 트렌드·사회적 변화·산업 흐름이 배경인지 맥락 중심으로 분석"

**출력 항목 (아이콘 없음)**:
```json
{
  "rank_and_recommendation": "순위 및 추천등급",
  "business_summary": "주요 사업 1~2문장",
  "rationale": "트렌드·사회적 맥락·전문가 시각 기반 상승/하락 배경 3~5줄",
  "target_price_flow": "현재가 → 목표가",
  "risk": "리스크 요인"
}
```

**포맷 (아이콘 제거)**:
```
종목명 (순위 및 추천등급)
사업 요약: ...
추천 근거: ...
목표가: ...
리스크: ...
```

### 5. KIS 투자의견 블록 — Gemini 리포트 뒤에 병합

**파일**: `src/strategy/advisor.py` — `generate_deep_dive_report()`

Gemini 리포트 출력 후 구분선(`---`) 아래에 별도 블록 추가:

```
── 투자 데이터 ─────────────────────────
종목투자의견: 매수 | 목표가: 58,000원 (현재가 대비 +26.4%)
컨센서스: 매수 7/9개사 | 평균목표가 61,000원
PER 41.5x (소프트웨어 업종 평균 38.2x 대비 +8%) | PBR 1.8x (업종 평균 4.1x 대비 -56%)
52주: 고 62,400원 / 저 39,800원 (현재 위치 68%)
────────────────────────────────────────
```

**PER/PBR 업종 비교 표시**:
- `sector_per_pbr.json`에서 `sector_name` 매칭
- 매칭 실패 시 절대값 + 정성 레이블만 표시
  - PER: ~15 저평가 / 15~30 적정 / 30~50 성장주 / 50+ 고평가
  - PBR: ~1 자산가치 이하 / 1~3 적정 / 3+ 프리미엄

데이터 출처:
- `invest_opinion`: `get_invest_opinion()` (이미 enrich_batch에서 수집)
- `consensus_summary`: `get_invest_opbysec()` (이미 수집)
- `per`, `pbr`, `w52_hgpr`, `w52_lwpr`: KIS inquire-price (이미 수집)
- `sector_name`: 이번 작업으로 추가

---

## 파일별 변경 요약

| 파일 | 변경 내용 |
|------|-----------|
| `data_fetcher.py` | ① `bstp_kor_isnm` 추출 추가 ② 파이프라인 시작 시 업종 PER/PBR 스크래핑 1회 |
| `kis_data_provider.py` | `get_news_titles(code)` 메서드 추가 |
| `advisor.py` | Gemini 프롬프트 재설계 + 투자 데이터 블록 포맷 추가 |
| `data/sector_per_pbr.json` | 신규 (자동 생성, 1일 캐시) |

---

## 데이터 흐름

```
[파이프라인 시작]
  └─ sector_per_pbr.json 갱신 (1일 TTL)

[종목 스크래핑 — DataFetcherWorker]
  └─ KIS inquire-price → sector_name 추가 추출 (기존 호출)

[딥다이브 — generate_deep_dive_report]
  ├─ KIS news-title API → 뉴스 제목 5~7개
  ├─ Gemini 프롬프트: 뉴스 제목 + 토론 요약 + 52주 위치 → 맥락 분석
  └─ 투자 데이터 블록 조립:
       invest_opinion + consensus + PER/PBR(업종비교) + 52주
       → Gemini 리포트 뒤에 병합하여 텔레그램 발송
```

---

## 미결 항목

- 시간외현재가 시뮬레이터 활용 — 별도 토의 예정
