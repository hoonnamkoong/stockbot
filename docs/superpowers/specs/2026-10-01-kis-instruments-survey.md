# KIS Open API 거래 수단 조사 — 심6(하락장) 재설계용

- 작성: 2026-10-01 (읽기 조사만. KIS 자격증명 실호출 없음, 레포 코드 수정 없음)
- 질문: "한투 API를 이용 가능하다면 채권, 금, ETF 등 다른 수단도 고려" — 이 봇이 **실제로** 사고팔 수 있는 수단은 무엇인가
- 기준 코드: 워크트리 `stock-regime6` (브랜치 feat/regime6-sideways, HEAD 999340649)

## 0. 한 줄 결론

**국내 상장 ETF/ETN은 지금 주문 코드를 그대로 쓰면 된다**(일반 주식과 같은 `order-cash` 경로이고 6자리 종목코드만 바꾸면 된다). 채권·금·달러·미국 국채에 투자할 때도 **국내 상장 ETF를 쓰는 것**이 유일하게 코드 추가 없이 가능한 길이다. 장내채권 직접 매매, 국내 선물옵션, 해외주식(TLT·GLD·SH 등), 해외선물은 KIS가 API로 지원한다. 하지만 이 레포에는 해당 코드가 **한 줄도 없고**, 대부분 별도 계좌상품코드나 사전교육·예탁금 같은 계좌 요건도 필요하다. KRX 금시장(금 현물 직접 매매)은 공식 API 범위에서 찾지 못했다.

## 1. 현재 코드의 주문·시세 경로 (확인 결과)

| 항목 | 현재 코드 | 근거 |
|---|---|---|
| 주문 API | `POST /uapi/domestic-stock/v1/trading/order-cash` | `src/lib/kis-api.ts:520` |
| TR ID | 매수 `TTTC0802U` / 매도 `TTTC0801U` (모의 `VTTC…`) | `src/lib/kis-api.ts:467-470` (`buildOrderRequest`) |
| 계좌상품코드 | `ACNT_PRDT_CD` = 계좌번호 9~10번째 자리, 비어 있으면 `"01"`(종합) | `src/lib/kis-api.ts:484` |
| 시장 구분 | 바디에 `EXCG_ID_DVSN_CD` 없음 = 구 TR(KRX 단일) | 같은 곳 |
| 주문 유형 | 매수=지정가(`00`, 심 판단가), 매도=항상 시장가(`01`, 단가 0) | `kis-api.ts:472-489`, `program_trader.py:1386-1396` |
| 종목코드 필터 | 없음. `PDNO`에 코드 문자열을 그대로 넣는다(ETF 배제 없음) | `kis-api.ts:485`, `src/app/api/trade/order/route.ts:59-140` |
| 호출 체인 | `program_trader.py` → `trade_executor.place_order_via_vercel` → Vercel `/api/trade/order` → `placeRealOrder` | `src/trade_executor.py:60`, `route.ts:140` |
| 잔고/체결/실현손익 | `TTTC8434R` / `TTTC8001R` / `TTTC8715R` (모두 국내주식 종합계좌용) | `src/trade/balance.py:67`, `executions.py:69`, `realized_pnl.py:64` |
| 시세 | `FHKST01010100` inquire-price(`FID_COND_MRKT_DIV_CODE=J`) 등 국내주식 TR만 사용 | `src/trade/kis_data_provider.py:771-775` |
| 해외·채권·선물 코드 | **없음** (`overseas-stock`, `domestic-bond`, `domestic-futureoption`, `TTTT1002U` grep 0건) | 레포 전체 grep |
| 미국 심(US1~3) | 가상 매매만 함(db-data CSV). KIS 해외 주문 경로 없음 | `src/app/api/trade/history-us/route.ts`, `src/strategy/simulators/us_*.py` |

**심6가 쓰는 KODEX 인버스(114800)의 주문 경로**는 일반 주식과 **완전히 같다**(`order-cash` + `TTTC0802U/0801U` + 계좌 01). 2026-07-21 설계 문서(`2026-07-21-sim5-sim6-sideways-redesign.md` §0.2)도 같은 결론이었다. 단 그 문서도 "실주문은 미검증"이라고 적었고, 이번 조사에서도 114800 실주문 기록은 확인하지 않았다.

**가격 보강(`trade_engine._enrich_universe`)과 ETF**: 심6처럼 유니버스에 가격 없이 들어온 종목은 `_needs_live_price=True`로 표시된다. 그러면 네이버 `investor_trend`(20일 일봉)로 sparkline·`range_history`·`amount_ma20`을 채운 뒤 KIS `get_price_quote`(FHKST01010100) 실시간가로 가격을 덮어쓴다(`trade_engine.py:684-813`). 이번 조사에서 네이버 `investor_trend`를 ETF 25종에 실제로 호출해 보니 **전부 20행이 돌아왔다**(아래 §3 거래대금이 그 결과다). KIS inquire-price가 ETF에 정상 응답한다는 것은 07-21 문서에 기록돼 있다(PER=0, 섹터 "ETF(실물복제/수익증권)").

**알아 둘 점: 구 주문 TR.** 공식 예제는 이제 `TTTC0012U`(매수)/`TTTC0011U`(매도)와 `EXCG_ID_DVSN_CD`(KRX/NXT/SOR)를 쓰고, `TTTC0802U`는 미수매수용 대안으로만 언급한다. 현재 코드는 구 TR로 실주문을 내고 있다(odno 이력). 폐지 공지는 찾지 못했지만, 새 상품을 붙이는 김에 구 TR 폐지 리스크를 따로 확인해 둘 가치는 있다.
- https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/order_cash/order_cash.py

## 2. 상품군별 KIS 지원 여부

| 상품군 | KIS Open API 지원 | 주문 TR / 경로 | 필요한 계좌·설정 | 현재 코드로 가능? | 제약 | 근거 |
|---|---|---|---|---|---|---|
| 국내 주식·**ETF·ETN**(채권·금·달러·해외지수·인버스·레버리지 ETF 포함) | 지원 | `order-cash` TTTC0802U/0801U(구), TTTC0012U/0011U(신) | 종합계좌(01) | **가능**(코드 변경 0, 종목코드만) | 레버리지·인버스2X는 사전교육+기본예탁금(§4) | [order_cash.py](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/order_cash/order_cash.py) |
| ETF/ETN 전용 시세(NAV·괴리율·구성종목) | 지원(시세만, 주문은 위와 같음) | `FHPST02400000` `/uapi/etfetn/v1/quotations/inquire-price`, NAV 추이 등 | 없음 | 코드 추가 필요(현재는 일반 inquire-price만 씀) | — | [etfetn/inquire_price](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/etfetn/inquire_price/inquire_price.py) |
| 지수 시세(KOSPI 0001, KOSDAQ 1001, KOSPI200 2001) | 지원 | 현재 `FHPUP02100000`, 기간별 `FHKUP03500100` | 없음 | 코드 추가 필요(현재 KIS 지수 TR 미사용) | — | [inquire_index_price](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_index_price/inquire_index_price.py), [inquire_daily_indexchartprice](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_daily_indexchartprice/inquire_daily_indexchartprice.py) |
| 장내채권(국채 등 소매채권) | 지원 | `TTTC0952U` `/uapi/domestic-bond/v1/trading/buy`, sell·정정취소·잔고·시세 별도 | 종합계좌(01로 보임) | **불가 — 새 코드 필요**(주문·잔고·체결·실현손익 전부 별도 TR) | PDNO 12자리 표준코드, `BOND_ORD_UNPR`·`BOND_RTL_MKET_YN`(소매시장) 등 필드가 주식과 다르다. 소매채권 호가 유동성은 측정 못 함 | [domestic_bond/buy](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_bond/buy/buy.py), [폴더 목록](https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm/domestic_bond) |
| 국내 선물옵션(KOSPI200 선물·미니·옵션) | 지원 | `TTTO1101U`(주간)/`STTN1101U`(야간) `/uapi/domestic-futureoption/v1/trading/order` | **선물옵션 계좌(상품코드 03)** 별도 개설 | **불가 — 새 계좌+새 코드** | 개인 파생상품 진입요건: 사전교육 1h+모의거래 3h+기본예탁금. 증거금·만기 롤오버 관리 필요 | [order.py](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_futureoption/order/order.py), [README 계좌코드](https://github.com/koreainvestment/open-trading-api), [KB 사전교육 안내](https://www.kbsec.com/go.able?linkcd=s070400201000) |
| 해외주식(미국 ETF: TLT·GLD·SH·SQQQ) | 지원 | `TTTT1002U` 매수 / `TTTT1006U` 매도 `/uapi/overseas-stock/v1/trading/order`, `OVRS_EXCG_CD`=NASD/NYSE/AMEX | 해외주식 거래 신청 + 외화(환전 또는 통합증거금) | **불가 — 새 코드**(주문·잔고·체결·실현손익·시세 전부 해외 TR) | 미국 **매수는 지정가만**(`00`, 실전에서 `32`/`34` LOO/LOC), 시장가 매수 불가. 장 시간 KST 22:30~05:00(서머타임)/23:30~06:00 → 현재 60초 루프(국내 장중)와 시간대가 다르다. us_trading cron은 08-27부터 미발화(메모리). SQQQ 등 ±1배 초과 상품은 해외 레버리지 ETP 사전교육(25-12-15~)+기본예탁금(26-05-21~) | [overseas_stock/order](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/overseas_stock/order/order.py), [KIS 공지](https://m.koreainvestment.com/main/customer/notice/Notice.jsp?cmd=TF04ga000002&num=45727), [KB 공지](https://www.kbsec.com/go.able?linkcd=s060901010000&seq=10009835&idt=20260512) |
| 해외선물옵션 | 지원 | `OTFM3001U` `/uapi/overseas-futureoption/v1/trading/order` | **해외선물옵션 계좌(08)** | **불가 — 새 계좌+새 코드** | 해외 파생상품 사전교육·모의거래 의무 | [overseas_futureoption/order](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/overseas_futureoption/order/order.py), [헤럴드경제](https://biz.heraldcorp.com/article/10636038) |
| ELW | 시세만 확인 | — | — | 해당 없음 | 하락장 헤지 수단으로 부적합(만기·LP) | 공식 레포 `elw` 폴더 |
| KRX 금시장(금 현물 직접) | **공식 API 카테고리에 없음**(확인 범위 내) | — | 금현물 계좌(HTS [7519] 거래신청) | **불가** | 대신 **ACE/TIGER KRX금현물 ETF**로 같은 기초자산을 산다(과세는 다름, §3) | [open-trading-api 폴더 목록](https://github.com/koreainvestment/open-trading-api), [HTS 7519](http://www.truefriend.com/pro_help/7519.html) |

계좌상품코드(공식 README `kis_devlp.yaml`): 01 종합 / 03 국내선물옵션 / 08 해외선물옵션 / 22 개인연금 / 29 퇴직연금.

## 3. 국내 상장 ETF 후보

- 출처: 네이버 증권 모바일 API(`m.stock.naver.com/api/stock/{code}/etfAnalysis`·`integration`), ETF 목록 API(`finance.naver.com/api/sise/etfItemList.nhn`). 2026-10-01 18:40 KST 조회.
- **거래대금 = 20거래일 평균**(2026-09-01~09-30). 네이버 `investor_trend` 20행의 종가×거래량으로 근사했으므로 실제 거래대금과 약간 다를 수 있다.
- 보수 = 네이버 `totalFee`(총보수 표기). 3개월·1년 수익률도 같은 출처.
- 과세: "기타"는 매매차익과 분배금 모두 배당소득세 15.4%(매매차익과 과표기준가 증분 중 작은 쪽에 과세), "국내주식형"은 매매차익 비과세. [삼성자산운용 ETF 세금](https://www.samsungfund.com/etf/insight/guide/view05.do)
- 사전교육: 배율이 ±1배를 넘는 상품(레버리지·인버스2X)만 해당한다. **-1배 인버스(114800 등)는 제외.** [삼성증권 공지](https://www.samsungpop.com/ux/kor/customer/notice/notice/noticeViewContent.do?MenuSeqNo=16993)

| 분류 | 코드 | 종목명 | 상장일 | 총보수 | 20일 평균 거래대금 | 3개월 / 1년 | 과세 | 특이사항 |
|---|---|---|---|---|---|---|---|---|
| 인버스 | 114800 | KODEX 인버스 | 2009-09-16 | 0.64% | 6,580억 | +10.6% / -68.4% | 기타 15.4% | **현행 심6 유니버스.** -1배라 교육·예탁금 없음 |
| 인버스 | 252670 | KODEX 200선물인버스2X | 2016-09-22 | 0.64% | 4,212억 | +4.3% / -93.3% | 기타 | 레버리지 ETP 요건. 가격 69원(1틱≈1.4%) |
| 인버스 | 251340 | KODEX 코스닥150선물인버스 | 2016-08-10 | 0.64% | 847억 | +4.2% / -28.7% | 기타 | -1배, 요건 없음 |
| 단기자금 | 459580 | KODEX CD금리액티브(합성) | 2023-06-08 | 0.02% | 7,896억 | +0.7% / +2.8% | 기타 | 가격 약 107만원/주 → 소액 NAV에서 수량 정수화 오차 큼 |
| 단기자금 | 357870 | TIGER CD금리투자KIS(합성) | 2020-07-07 | 0.03% | 107억 | +0.8% / +2.9% | 기타 | 가격 5.8만원 |
| 단기자금 | 423160 | KODEX KOFR금리액티브(합성) | 2022-04-26 | 0.05% | 103억 | +0.7% / +2.7% | 기타 | 가격 11만원 |
| 단기자금 | 488770 | KODEX 머니마켓액티브 | 2024-08-06 | 0.05% | 641억 | +0.9% / +3.2% | 기타 | 가격 10.6만원 |
| 단기채 | 153130 | KODEX 단기채권 | 2012-02-22 | 0.15% | 11억 | +0.6% / +2.2% | 기타 | 유동성 낮음 |
| 국고채 | 114260 | KODEX 국고채3년 | 2009-07-29 | 0.15% | 9억 | +0.1% / -0.6% | 기타 | 유동성 낮음 |
| 국고채 | 148070 | KIWOOM 국고채10년(구 KOSEF) | 2011-10-20 | 0.05% | 24억 | -1.3% / -7.1% | 기타 | 브랜드가 KOSEF에서 KIWOOM으로 바뀜 |
| 국고채 | 439870 | KODEX 국고채30년액티브 | 2022-08-23 | 0.05% | 5억 | -2.1% / -24.9% | 기타 | 유동성 매우 낮음 |
| 국고채 | 385560 | RISE KIS국고채30년Enhanced | 2021-05-26 | 0.05% | 15억 | -2.9% / -31.8% | 기타 | — |
| 미국채 | 305080 | TIGER 미국채10년선물 | 2018-08-30 | 0.29% | 8억 | -16.7% / -8.3% | 기타 | 환노출(원화 강세에 손실) |
| 미국채 | 453850 | ACE 미국30년국채액티브(H) | 2023-03-14 | 0.05% | 64억 | -9.0% / -9.6% | 기타 | 환헤지 |
| 금 | 411060 | ACE KRX금현물 | 2021-12-15 | 0.19% | 202억 | -6.7% / -6.7% | 기타 | KRX 금현물 기초 |
| 금 | 0072R0 | TIGER KRX금현물 | 2025-06-24 | 0.15% | 105억 | -6.7% / -6.5% | 기타 | 코드에 영문자가 들어 있음(§5 확인 필요) |
| 금 | 132030 | KODEX 골드선물(H) | 2010-10-01 | 0.68% | 26억 | +3.7% / +3.8% | 기타 | 환헤지 |
| 달러 | 261240 | KODEX 미국달러선물 | 2016-12-27 | 0.25% | 16억 | -12.0% / -0.5% | 기타 | — |
| 달러 | 261250 | KODEX 미국달러선물레버리지 | 2016-12-27 | 0.45% | 22억 | -23.1% / -4.3% | 기타 | 레버리지 ETP 요건 |
| 달러 | 261270 | KODEX 미국달러선물인버스 | 2016-12-27 | 0.45% | 5억 | +14.6% / +3.2% | 기타 | -1배 |
| 달러 | 261260 | KODEX 미국달러선물인버스2X | 2016-12-27 | 0.45% | 21억 | +29.9% / +3.4% | 기타 | 레버리지 ETP 요건 |
| 달러단기채 | 329750 | TIGER 미국달러단기채권액티브 | 2019-07-24 | 0.30% | 41억 | -12.1% / -0.5% | 기타 | — |
| 원자재 | 261220 | KODEX WTI원유선물(H) | 2016-12-27 | 0.35% | 31억 | +34.9% / +80.8% | 기타 | 헤지 성격 아님(참고) |
| 엔 | 292560 | TIGER 일본엔선물 | 2018-04-17 | 0.25% | 9억 | -9.2% / -9.1% | 기타 | — |
| 해외지수(참고) | 360750 | TIGER 미국S&P500 | 2020-08-07 | 0.0068% | 8,772억 | -9.6% / +12.3% | 기타 | 헤지 아님. 환노출 |
| VIX ETN | 500095 | 신한 S&P500 VIX S/T 선물 ETN E | (미확인) | (미확인) | 당일 0.02억 | 52주 고점 17,155→6,515 | 기타 | **상장 중이지만 사실상 거래 없음.** ETN은 만기 있음 |
| VIX ETN | 520088 | 미래에셋 S&P500 VIX S/T 선물 ETN(H) | (미확인) | (미확인) | 당일 0.28억 | 52주 고점 15,365→6,295 | 기타 | 거래 거의 없음 |

**최근 3개월(대략 KOSPI200 -20.8%, KODEX 200 기준) 동안 헤지 수단별 성적**(같은 조회 결과):

| 수단 | 성적 |
|---|---|
| 인버스 1X | **+10.6%** |
| 달러 인버스 | +14.6% |
| 금 현물 | -6.7% |
| 달러 롱 | -12% |
| 미국채 | -9%~-17% |
| 국고채 | -3%~0% |
| CD·머니마켓 | +0.7~0.9% |

**이번 하락에서는 "달러·금·미국채가 주식 하락을 메워 준다"는 통념이 맞지 않았다**(원화 강세가 같이 왔기 때문). 이 수치는 한 구간 관측일 뿐 백테스트가 아니다.

**심 사이징에 대한 함의**: 300만원 NAV × 95%(심6) ≈ 285만원 기준으로 보면 다음과 같다.
- 거래대금 하루 5억 이하 상품(국고채30년액티브 439870, 달러인버스 261270, 국고채3년 114260 등)은 우리 주문이 호가를 흔들 위험이 상대적으로 크다. 대금 자체는 충분하지만 LP 호가 공백이 생길 수 있다.
- CD금리액티브(459580, 약 107만원/주)는 2주만 살 수 있어 수량 정수화 오차가 약 37%에 이른다.

## 4. 계좌·규정 제약 (자동매매 계좌에 걸리는 것)

| 대상 | 요건 | 시행 | 근거 |
|---|---|---|---|
| 국내 레버리지 ETP(배율 ±1배 초과: 레버리지, 인버스2X) | 금융투자교육원 사전교육 1시간 + 기본예탁금(단계별 면제·500만·1,000만·1,500만원). **-1배 인버스 제외** | 2020-09-07 | [삼성증권 공지](https://www.samsungpop.com/ux/kor/customer/notice/notice/noticeViewContent.do?MenuSeqNo=16993) |
| 해외 레버리지 ETP(SQQQ·TQQQ 등) | 사전교육 1시간("국내외 레버리지 ETP Guide"). 시행 전 거래자·국내 교육 이수자는 면제 | 2025-12-15 | [KIS 공지](https://m.koreainvestment.com/main/customer/notice/Notice.jsp?cmd=TF04ga000002&num=45727) |
| 해외 레버리지·인버스 ETP | 기본예탁금 도입(외화 인정) | 2026-05-21 | [KB증권 공지](https://www.kbsec.com/go.able?linkcd=s060901010000&seq=10009835&idt=20260512), [네이트(1,000만원)](https://m.news.nate.com/view/20260421n31283) |
| 단일종목 레버리지·인버스 ETP(국내·해외) | 기본예탁금 3,000만원, **현금만 인정**(대용증권 제외, 매도대금은 T+2 결제 후 인정) + 심화교육 1시간. 지수형(코스피200·나스닥100)은 기존 요건 유지 | 2026-07-31 | [다음/연합](https://v.daum.net/v/20260724094006490) |
| 국내 선물옵션 | 사전교육 1시간 + 모의거래 3시간 + 기본예탁금 + 03 계좌 | 기존 제도 | [KB 안내](https://www.kbsec.com/go.able?linkcd=s070400201000) |

자동매매 관점의 결론은 이렇다.
- **-1배 인버스(114800·251340·261270)는 요건이 없어 바로 쓸 수 있다.**
- 2X 상품은 사용자 계좌의 교육 이수 여부와 예탁금 단계에 달려 있다. 이수하지 않은 계좌라면 KIS가 주문을 거부한다(거부 메시지 형태는 미확인).
- 원장이 fail-closed로 동작하므로, 거부되면 "주문 실패"로 남고 진입 자체가 안 될 것이다.

## 5. 봇 운영 제약과의 정합

- **한 번에 한 심**: 프로그램 매매는 선택된 심 하나만 실행한다. 심6를 "인버스 + 현금성 ETF" 같은 다종목 구조로 바꿔도 같은 심 안에서 처리하면 이 제약과 충돌하지 않는다.
- **사이징**: 심6는 `MAX_HOLDINGS=1`, `ENTRY_RATIO=0.95`(`sim6_bear_hedge.py:17-18`)이고 다른 심은 NAV×19%×5종목이다. 위 표의 고가 ETF(CD금리 107만원, 머니마켓 10만원대)는 정수 수량 제약을 주의해야 한다.
- **60초 루프·장 시간**: 국내 ETF(채권·금·달러 포함)는 KRX 정규장 09:00~15:30으로 주식과 같다. 현재 루프와 `_buy_allowed`(정규장 종료 후 신규 매수 금지) 그대로 맞는다. 해외 ETF는 시간대가 달라 이 루프로는 못 다룬다.
- **매도=시장가**: ETF는 LP가 있어 시장가 매도 체결 리스크가 낮다. 다만 거래대금 수억 원대 상품은 LP 호가 공백 시간대(장 시작 직후·종료 직전)의 슬리피지를 측정하지 못했다.
- **호가단위**: 매수 지정가 = 심 판단가(KIS 현재가)라 원래 호가단위 위에 있다. 다만 심이 가격을 계산해서 낸다면 ETF 호가단위(2,000원 미만 1원, 이상 5원으로 알려짐, 이번 조사에서 미확인)에 맞춰야 한다.
- **영문자가 섞인 신규 코드(0072R0 등)**: 주문(`PDNO`)·시세(`FID_INPUT_ISCD`)·네이버 API 모두 문자열로 다뤄 원리상 문제는 없어 보인다. 그러나 레포의 6자리 숫자 가정(정규식·int 변환·CSV 숫자 파싱 시 앞자리 0 손실 등)을 전수 검사하지는 않았다. **채택하려면 먼저 grep으로 점검해야 한다.**

## 6. 결론 — 수단 분류

**A. 현재 코드로 바로 쓸 수 있다**(종목코드만 바꾸면 됨, 계좌 01, 교육 불필요)
- 인버스 -1배: 114800(현행), 251340(코스닥 인버스)
- 현금성 대피: 459580 / 357870 / 423160 / 488770(CD·KOFR·MMF). "BEAR일 때 현금 대신 연 2.7~3.2%"
- 금: 411060 / 0072R0(KRX금현물), 132030(골드선물H)
- 채권: 148070·114260(국고채), 453850·305080(미국채)
- 달러: 261240(롱), 261270(인버스 -1배)

**B. 계좌 요건만 맞으면 현재 코드로 가능**(사전교육·예탁금 필요)
- 252670(인버스2X), 261250/261260(달러 레버리지·인버스2X), VIX ETN(-1배 초과가 아니면 교육 불필요하나 **유동성이 없어 사실상 제외**)

**C. 새 코드가 필요하다**
- ETF NAV·괴리율 조회(`FHPST02400000`), KIS 지수 시세(`FHPUP02100000`/`FHKUP03500100`) — 시세만이라 추가 비용은 작다
- 장내채권 직접 매매(`TTTC0952U` 외 주문·잔고·체결 일습) — 국채 ETF로 대체할 수 있어 실익이 작다

**D. 새 계좌 + 새 코드 + 규정 요건이 필요하다 (사실상 불가)**
- 국내 선물옵션(03 계좌, 교육·모의거래·예탁금, 증거금·롤오버)
- 해외주식(TLT·GLD·SH·SQQQ: 해외 TR 일습, 미국 장 시간 별도 루프, 시장가 매수 불가, 해외 레버리지 요건, 양도세 체계 별도)
- 해외선물옵션(08 계좌)
- KRX 금시장 금 현물 직접 매매(공식 API에서 확인 못 함)

## 7. 측정 불가·미확인

- 114800을 포함한 ETF의 **실주문 체결**: 실계좌 호출 금지 범위라 확인하지 못했다(07-21 문서도 미검증).
- 구 TR `TTTC0802U/0801U`의 폐지 일정: 찾지 못했다.
- 레버리지 ETP 미이수 계좌에 대한 KIS 주문 거부 응답 형태(msg 코드).
- 장내채권 API의 계좌상품코드가 정확히 01인지, 모의투자를 지원하는지(예제에 명시 없음).
- 국내 선물옵션 기본예탁금 현행 금액(1차 출처 미확인).
- VIX ETN 500095·520088의 만기·보수·상장일.
- ETF 호가단위 현행 규정, 저유동 ETF의 LP 호가 공백과 슬리피지.
- 거래대금은 종가×거래량 근사라 KRX 공식 거래대금과 다를 수 있다.
- 영문자 포함 종목코드(0072R0)가 레포의 모든 경로에서 안전한지.
