# 미국 주식 페이퍼 트레이딩 심 설계 (US Sim1~6)

## 배경 / 목적

국내(KRX) 매매를 전제로 짜인 스톡봇에 미국 주식 매매를 추가하려는 요청에서 출발했다.
코드베이스 조사 결과 KIS TR ID, 종목코드 포맷(6자리 숫자), 원화 정수 처리, KST 고정
시간 게이트, 원장 계좌 스키마까지 6개 층위가 전부 국내 전용으로 하드코딩되어 있었다
(`src/trade/kis_data_provider.py`, `src/lib/kis-api.ts:437-440`,
`src/data/market_cap_universe.py:67`, `src/pipeline/workers/trade_engine.py:980`,
`src/pipeline/context.py:163-210`, `src/config_validator.py:77-85`). 기존에 미국
관련 코드는 `scripts/fetch_us_market.py`(나스닥 지수를 국면판정 보조지표로만 쓰는
용도) 하나뿐이라 실질적으로 그린필드다.

이 부담을 감안해, **실주문 연동·계좌 스키마 확장 등 인프라 전면 개편은 미루고**,
먼저 페이퍼(관찰) 모드로만 동작하는 미국 주식 전략 6개를 새 트랙으로 구축한다.
기존 국내 심 중 버즈·수급 의존도가 낮아 이식 가능한 전략을 우선순위화해 골랐다.

## 범위와 원칙

- **페이퍼 전용.** KIS 해외주식 실주문 연동은 하지 않는다. 자본 이동 없음.
- **국내 파이프라인과 완전 분리.** 60초 매매 루프·KST 게이트·KIS TR 호출 등 기존
  코드는 건드리지 않는다. 데이터 소스, 스케줄러, 원장, 프론트 페이지 전부 독립된
  새 트랙으로 신설한다.
- **통화는 USD 그대로.** 환율 변환을 도입하지 않는다 — 원화로 환산해 표시하면
  전략 순수 성과에 환율 변동이 섞여 오염된다.
- V1은 아래 6개 심 전부를 포함한다(순서대로 구현): 공용 인프라 → US Sim1(미너비니)
  끝까지 완성·검증 → 나머지 5개는 같은 인프라를 재사용하는 전략 로직만 추가.

## 이식 대상 심 6개

| 새 번호 | 원본(국내) | 전략 | 비고 |
|---|---|---|---|
| US Sim1 | (신규 설계) | 미너비니 추세형(SEPA/VCP) | 국내 Sim11 로직을 미국 종목에 이식 |
| US Sim2 | Sim9-1 | 돈치안 채널 돌파(20일 상단 돌파, 10일 이탈/2ATR 청산) | 순수 기술적, 배선 가장 단순 |
| US Sim3 | Sim4 | 상승 모멘텀형(불타기, 고정익절 없이 트레일링) | 등락률 랭킹만 있으면 됨 |
| US Sim4 | Sim4-1 | 상승 단타형(분할익절+2/5일 강제청산) | Sim3와 유니버스 공유, 타이밍 촘촘 |
| US Sim5 | Sim9 | 갭소진 반등(갭+7%→장중-6%저가권 매수, 익일청산) | 당일 시가·장중저가 폴링 추적 신규 배선 필요 |
| US Sim6 | Sim5 | 추세눌림목형(20일 채널 저점+3%, 상단근접 트레일링) | range_history를 버즈 경로 없이 새로 배선 |

**이식 제외**(한국 특화 데이터 원천이라 무료 대체재가 마땅치 않음): Sim1(버즈
텍스트), Sim2·Sim3·Sim8(KIS 외국인·기관 수급/재무순위), Sim6(인버스 ETF, 단 Sim0
국면판정 종속이라 국면판정기 없이는 트리거 불가 — 향후 확장 절 참고), Sim7(딥다이브
리포트), Sim10·Sim12(Libero 국면 의존), Sim13(테마 데이터).

## 데이터 파이프라인 (공용)

### 유니버스

`api.nasdaq.com/api/screener/stocks`(키 불필요, `exchange=nasdaq,nyse,amex`
파라미터로 3개 거래소 통합) — 네이버 시총랭킹 스크레이핑을 대체하는 포지션.
시총 상위 500~1000개를 받아 ETF·우선주·워런트를 제외하고
`data/us_universe.json`으로 하루 1회 저장한다. US Sim1(SEC EDGAR 펀더멘털 필요)만
`country == "United States"`(국내법인, 분기 10-Q 제출 대상)로 추가 필터링한다 —
ADR(20-F 제출, 연 1회)은 분기 실적 YoY를 못 구하므로 Sim1 후보에서 자동 제외되고,
나머지 5개 심(순수 기술적)은 이 필터가 필요 없다.

### 일봉 OHLCV

Yahoo Finance 비공식 chart API(`query1.finance.yahoo.com/v8/finance/chart/{symbol}`,
`fetch_us_market.py`가 이미 키 없이 안정 작동을 확인한 패턴) — 종목당 1콜,
`interval=1d&range=1y`로 200일 이동평균 계산에 필요한 기간을 확보한다. 지금은
종가만 파싱하지만 open/high/low/volume까지 확장해야 한다(Sim5 갭 판정에 시가·저가
필요). 이 API는 공식 rate limit 문서가 없고 과호출 시 IP 차단 사례가 보고되므로
호출 간 슬립을 두고, 필요하면 배치를 여러 스텝으로 나눈다 — 알려진 리스크로 명시.

### 펀더멘털 (US Sim1 전용)

SEC EDGAR — 완전 무료, 키 불필요, 10 req/s.
1. `https://www.sec.gov/files/company_tickers.json`으로 ticker→CIK 매핑(캐시, 가끔
   갱신).
2. `https://data.sec.gov/api/xbrl/companyconcept/CIK{10자리}/us-gaap/EarningsPerShareDiluted.json`,
   `.../Revenues.json`(회사마다 태그가 다를 수 있어 `RevenueFromContractWithCustomerExcludingAssessedTax`
   등 폴백 태그 목록 필요)에서 분기 값을 뽑아 같은 분기 전년동기 대비 YoY를 계산한다.
3. 국내 Sim11이 "종목당 KIS 3콜"로 절제했듯, **트렌드 템플릿을 먼저 통과한 소수
   후보에만** 이 조회를 실행해 EDGAR 콜 수를 최소화한다.
4. User-Agent 헤더 필수(SEC 정책, 연락처 포함 권장).

(Finnhub 무료 티어도 `epsGrowthTTMYoy`를 사전계산된 값으로 제공해 검토했으나, API
키 발급·비상업 조건 의존을 피하고자 SEC EDGAR를 기본으로 채택했다.)

## 스케줄링

### EOD 워치리스트 배치

신규 `scripts/run_eod_sim_us.py` + 신규 워크플로 `.github/workflows/us_eod_watchlist.yml`.
하루 1회, 미국장 마감(16:00 ET) 이후 안전 마진을 둔 UTC 시각에 실행 — EDT(20:00 UTC
마감)·EST(21:00 UTC 마감) 양쪽을 다 지나는 고정 시각이면 되므로(예: 22:00 UTC)
이 배치 자체는 서머타임 분기 로직이 필요 없다. 6개 심 각각의 무거운 계산(추세
템플릿·VCP 압축·채널·갭 후보 등)을 여기서 끝내고 `data/sim_us{N}_*_watchlist.json`에
남긴다.

### 장중 실행 루프

신규 `scripts/us_trade_loop.py` + 신규 워크플로 `.github/workflows/us_trading.yml`.

기존 국내 매매(`trading.yml`)는 태스커(사용자 폰 앱)가 `repository_dispatch`로
2분마다 깨우는 구조다 — GitHub Actions 네이티브 cron이 부하 시 몇 분씩 밀리는데,
**실거래는 그 지연이 실제 손실**로 이어지기 때문이다. US 심은 페이퍼(자본 이동
없음)라 이 제약이 적용되지 않고, 반대로 태스커 방식을 그대로 쓰면 사용자 폰이
한국시간 밤 10~11시부터 새벽 5~6시까지(서머타임에 따라 다름) 계속 깨어 있어야 하는
부담이 생긴다.

→ **네이티브 cron 채택.** UTC 기준 양쪽 세션(EDT·EST)을 다 덮는 넓은 창(예:
13:00~21:30 UTC)에 5분 간격으로 스케줄하고, 워크플로 내부에서 Python `zoneinfo`
(`America/New_York`)로 실제 개장 여부를 판정해 장외 시간엔 즉시 종료한다 — 서머타임
전환은 zoneinfo가 자동 처리하므로 별도 분기 코드가 필요 없다. 태스커·사용자 폰 개입
없음.

루프는 워치리스트에 있는 종목만(전체 유니버스가 아님) Yahoo Finance로 실시간에
가까운 시세를 조회해 6개 심의 진입/청산 판정 함수를 순서대로 호출하고, 페이퍼 주문을
상태 파일에 반영한다.

## 원장 · 통화 스키마

- 심마다 자체 `sim_us{N}_*_state.json` / `trade_history_sim_us{N}_*.csv` — 국내와
  동일 shape, `currency` 필드만 `"USD"`.
- `src/strategy/strategy_manifest.yaml`에 `currency` 필드 추가(기본값 `"KRW"`,
  기존 국내 심은 값을 안 적으면 그대로 KRW로 동작 — 하위 호환). US 심 6개 블록은
  `currency: "USD"`로 등록.
- `scripts/gen_sim_registry.py`가 이 필드를 `src/lib/sim-registry.generated.ts`로
  옮긴다.
- `src/lib/sim-reset-targets.ts`의 `RESET_TARGETS`(현재 `SIM_REGISTRY` 전체를
  대상으로 KRW 리셋 검증 `100_000~1_000_000_000`을 적용)는 **KRW 심만**(즉
  `currency !== 'USD'`) 대상으로 좁힌다. US 심은 별도 `US_RESET_TARGETS` +
  신규 API `src/app/api/simulation/reset-us/route.ts`가 전담하고, USD 검증 범위는
  `$1,000 ~ $500,000` 정수로 별도 검증한다(원화보다 자리수가 훨씬 작다).
- 초기 자본은 하드코딩하지 않는다 — 국내와 동일하게 리셋 버튼 옆 입력창(USD)에서
  사용자가 지정한 값으로 초기화한다. `BaseSimulator.__init__`의 `initial_cash`
  기본값은 리셋 전 최초 기동용 placeholder로만 쓰이며 $20,000을 기본값으로 둔다.

## 프론트엔드

- 신규 `src/app/trade/us/page.tsx` + `TradeUSClient.tsx` — 기존 `TradeClient.tsx`를
  축소 복제한다. 실계좌 요약·프로그램매매 훅(`useProgramTrading.ts`) 등 국내
  실거래 전용 UI는 제외 — 이 페이지는 페이퍼 전용이다.
- `middleware.ts`의 `matcher: ["/trade/:path*", ...]`가 이미 와일드카드라 별도
  인증 설정 없이 `/trade/us`가 보호된다.
- 기존 `/trade` 페이지 헤더 타이틀을 "트레이딩" → "국내 트레이딩"으로 바꾸고,
  상단에 "미국" 탭/링크를 추가해 `/trade/us`로 이동한다. URL 자체(`/trade`)는
  바꾸지 않는다 — 이미 연결된 네비게이션·북마크를 깨지 않기 위함.

## 전략별 이식 규칙 요약

각 심은 국내 원본의 파라미터(비중 19%, 최대 5종목, 손절폭 등)를 그대로 이식하고
데이터 소스만 교체한다. 상세 임계값·판정식은 구현 단계에서 국내 원본
(`src/strategy/simulators/sim{N}_*.py`)을 그대로 참조해 옮긴다.

- **US Sim1(미너비니)**: 추세 템플릿(MA50>MA150>MA200 정배열, 52주 고저 대비 위치)
  +SEC EDGAR EPS·매출 YoY 필터+VCP 압축→pivot 돌파 매수, 손절 -7.5%/50일선 이탈
  청산. `sim11_minervini.py`를 그대로 이식(국내 Sim11이 이미 EOD판단+장중체결로
  룩어헤드를 피하도록 재설계돼 있어 이 구조를 그대로 가져간다).
- **US Sim2(돈치안)**: 20일 채널 상단 돌파 매수, 10일 채널 이탈 또는 2×ATR 청산.
  펀더멘털 불필요, OHLCV만 있으면 된다.
- **US Sim3(상승 모멘텀)**: nasdaq 스크리너의 당일 등락률 상위 랭킹으로 유니버스를
  대신하고, 고정 익절 없이 트레일링 스탑으로 승자를 태운다.
- **US Sim4(상승 단타)**: Sim3와 유니버스 공유, +5%/+10% 분할 익절 + 2일/5일
  강제청산. 5분 간격 폴링이라 국내(1분 루프)보다 체결 타이밍 정밀도가 떨어질 수
  있음 — 알려진 한계로 명시.
- **US Sim5(갭소진 반등)**: 갭+7% 이상 후 장중 -6% 저가권 마감 시 매수, 익일 청산.
  당일 시가·누적 장중 저가를 루프가 폴링하며 직접 추적하는 신규 상태가 필요하다
  (국내판은 버즈 경로의 부산물을 썼지만 US는 그 경로가 없다).
- **US Sim6(추세눌림목)**: 20일 채널 저점 대비 +3% 이내 진입, 상단 근접 후
  트레일링. range_history(20일 종가)를 국내처럼 버즈 경로에 얹지 않고 OHLCV
  캐시에서 직접 계산하도록 새로 배선한다.

## 향후 확장 (V1 범위 밖)

- **US Sim7 후보(하락 줍줍형, 국내 Sim6)**: SQQQ 등 미국 인버스 ETF로 대체
  가능하나, 진입 게이트가 국내 Sim0(리베로) 국면판정에 종속돼 있다. 미국판
  국면판정기가 없는 한 트리거를 못 낸다 — 별도 프로젝트.
- 실주문 연동(KIS 해외주식 API), 계좌 스키마 확장(국내/해외 구분), 원화 환산
  표시 등은 이번 범위에서 의도적으로 제외했다. 페이퍼 성과가 몇 주 이상 쌓여
  검증된 이후에 별도로 브레인스토밍한다.

## 알려진 리스크 / 미검증 항목

- Yahoo Finance 비공식 API는 SLA가 없다 — 언젠가 차단되거나 응답 형식이 바뀔 수
  있다. `fetch_us_market.py`가 이미 감수 중인 리스크를 그대로 이어받는다.
- SEC EDGAR의 회사별 XBRL 태그 명명이 일관되지 않아(특히 매출 태그) 폴백 리스트가
  필요하고, 초기 구현에서 일부 종목의 실적 YoY가 결손으로 남을 수 있다 — "측정
  불가"로 명시하고 0으로 폴백하지 않는다.
- 5분 간격 폴링의 체결 정밀도는 국내 1분 루프보다 낮다. 페이퍼라 실손실은 없지만
  시뮬레이션 신뢰도에는 영향을 줄 수 있다.
- nasdaq.com 스크리너 API도 비공식이라 스키마 변경 리스크가 있다.
