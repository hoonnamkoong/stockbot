# KIS 클라이언트 이중화 해소 구현 계획

> **에이전트 작업자에게:** 필수 서브스킬 — `superpowers:subagent-driven-development` 또는
> `superpowers:executing-plans`로 태스크 단위로 실행할 것. 각 스텝은 체크박스(`- [ ]`)다.

**목표:** `data_fetcher`가 손으로 굴리는 KIS 호출 사본을 없애고, 하드닝된
`KISDataProvider` 하나만 남긴다.

**아키텍처:** KIS 호출 지점이 지금 두 곳이다. `KISDataProvider._get`은 `rt_cd`를 검사하고
응답 형태(list/dict)를 다루며 캐시를 갖는다. `data_fetcher._get_stock_details`는 같은 두
엔드포인트를 `requests.get`으로 직접 부르고 그 방어가 하나도 없다. 후자를 전자의 메서드
호출로 바꾼다. 파싱을 한 곳으로 모으는 것이 목적이고, 동작은 바뀌지 않아야 한다.

**기술 스택:** Python 3.10+, pytest, KIS OpenAPI (FHKST01010100 현재가 / FHKST01010300 체결)

## 왜 지금인가

2026-08-12 하루에 이 이중화가 두 번 사고를 냈다.

1. **ccnl 응답 형태 오류** — `inquire-ccnl`의 `output`은 체결 30행 리스트인데 dict로 읽어
   전 종목 `AttributeError`, `tick_power` 100% 결손. `KISDataProvider`는 같은 문제를
   `get_investor_trend_estimate`에서 이미 풀어놨다(리스트/dict 양쪽 대응). 사본에는 그
   해법이 없었다.
2. **per 27/27 전량 결손** — KIS 접속이 몇 분 막혔을 때 `connect timeout=3`으로 전멸했다.
   provider는 timeout 기본값이 5이고 캐시가 있어 피해가 작았을 구간이다.

두 사고 모두 "provider에는 있는데 사본에는 없는 것" 때문이었다.

## Global Constraints

- **동작 무변경이 합격선이다.** 이건 리팩터링이다. `_get_stock_details`가 돌려주는 dict의
  키와 값이 변경 전후로 같아야 한다.
- 실전 매매가 이 경로의 산출물(`price`·`open_price`·`per`·`tick_power`)을 쓴다. 값이
  달라지면 주문이 달라진다.
- 새 기능을 넣지 않는다. 재시도·백오프는 **provider에도 없다** — 이번 범위 밖이다.
- 테스트는 실제 KIS 응답 형태로 mock한다. mock이 코드의 가정을 복제하면 초록인 채로
  버그가 산다(2026-08-11 CCNL_OUT이 정확히 그랬다).

## 지금 상태 (실측)

| | `KISDataProvider` | `data_fetcher` 사본 |
|---|---|---|
| `rt_cd` 검사 | 함 (`_get`) | **안 함** (HTTP 200만 봄) |
| 응답 형태 | list/dict 대응 | 08-12에야 대응 추가 |
| 캐시 | 인스턴스 5분(`TTL_REALTIME`) | 없음 |
| 타임아웃 | 5초 | 3초 하드코딩 |
| 재시도 | 없음 | 없음 |

**필드 대응** — `get_price_quote`가 이미 주는 것: `price`, `change_rate_pct`, `per`, `pbr`,
`sector_name`, `w52_hgpr`, `w52_lwpr`, `open_price`, `day_high`, `day_low`, `prev_close`.

`data_fetcher`가 추가로 쓰는 것(= Task 2에서 채울 것): `hts_frgn_ehrt`→`foreign_rate`,
`eps`, `bps`, `hts_avls`→`mkt_cap`, `acml_tr_pbmn`→`amount`, `acml_vol`→`volume`.

`tick_power`(`tday_rltv`, inquire-ccnl)는 provider에 **메서드 자체가 없다** → Task 1.

## 캐시 안전성 (검토 완료)

`get_price_quote`는 `_get_cached`(인스턴스 캐시)만 쓴다. `_get_disk_cached`(프로세스 넘어
사는 캐시)는 재무비율·투자의견 전용이다. 스크래퍼는 런마다 새 프로세스라 인스턴스 캐시는
**같은 런 안에서 같은 종목을 두 번 부를 때만** 걸린다. 런 간 staleness가 생기지 않는다.

## 파일 구조

- `src/trade/kis_data_provider.py` — KIS 호출·파싱의 **유일한** 지점이 된다. Task 1·2에서
  `get_tick_power` 추가, `get_price_quote` 필드 확장.
- `src/pipeline/workers/data_fetcher.py` — KIS 호출을 provider 위임으로 교체(Task 3).
  네이버 파싱(`frgn.naver`·`main.naver`)은 **건드리지 않는다**.
- `tests/test_kis_tick_power.py` — 신규(Task 1)
- `tests/test_kis_price_quote_fields.py` — 신규(Task 2)
- `tests/test_data_fetcher_kis_isolation.py` — 수정(Task 3). 지금은 `requests.get`을
  monkeypatch하는데, provider 위임 후엔 그 훅이 안 걸린다.

---

### Task 1: `KISDataProvider.get_tick_power`

**Files:**
- Modify: `src/trade/kis_data_provider.py` (`get_price_quote` 아래에 추가)
- Test: `tests/test_kis_tick_power.py` (신규)

**Interfaces:**
- Produces: `get_tick_power(code: str) -> float` — 당일 체결강도. 얻지 못하면 `0.0`.

**참고 — 실제 응답 형태** (2026-08-12 실호출 확인):
```
{"rt_cd":"0","output":[{"stck_cntg_hour":"155954","stck_prpr":"255500",
  "cntg_vol":"19","tday_rltv":"128.92","prdy_ctrt":"6.68"}, ...30행, 최신순]}
```
`tday_rltv`는 당일 **누적** 체결강도라 모든 행이 같은 값이다. 최신 행만 본다.

- [ ] **Step 1: 실패 테스트를 쓴다**

```python
"""체결강도는 inquire-ccnl(FHKST01010300)이고, output은 체결 30행 리스트다."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.trade.kis_data_provider import KISDataProvider

CCNL_ROWS = [
    {'stck_cntg_hour': '155954', 'stck_prpr': '255500', 'cntg_vol': '19',
     'tday_rltv': '128.92', 'prdy_ctrt': '6.68'},
    {'stck_cntg_hour': '155747', 'stck_prpr': '255500', 'cntg_vol': '1',
     'tday_rltv': '128.92', 'prdy_ctrt': '6.68'},
]


def _provider(monkeypatch, body):
    p = object.__new__(KISDataProvider)
    p._token, p._base_url = 'tok', 'https://x'
    p._cache = {}
    monkeypatch.setattr(KISDataProvider, '_get', lambda self, *a, **k: body)
    return p


def test_reads_tick_power_from_the_latest_row(monkeypatch):
    p = _provider(monkeypatch, {'rt_cd': '0', 'output': CCNL_ROWS})
    assert p.get_tick_power('005930') == 128.92


def test_empty_output_is_zero_not_a_crash(monkeypatch):
    """장 시작 전엔 체결이 없다. 0으로 떨어지되 죽지 않아야 한다."""
    p = _provider(monkeypatch, {'rt_cd': '0', 'output': []})
    assert p.get_tick_power('005930') == 0.0


def test_failed_call_is_zero(monkeypatch):
    """_get은 실패 시 {}를 준다(예외 아님)."""
    p = _provider(monkeypatch, {})
    assert p.get_tick_power('005930') == 0.0
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_kis_tick_power.py -v`
Expected: FAIL — `AttributeError: 'KISDataProvider' object has no attribute 'get_tick_power'`

- [ ] **Step 3: 최소 구현**

`src/trade/kis_data_provider.py`의 `get_price_quote` 정의 바로 아래에 추가:

```python
    # ──────────────────────────────────────────────────
    # 7-b. 체결강도 (FHKST01010300 — 주식현재가 체결)
    # ──────────────────────────────────────────────────
    def get_tick_power(self, code: str) -> float:
        """당일 체결강도(tday_rltv). 얻지 못하면 0.0.

        이 응답의 output은 dict가 아니라 **체결 내역 리스트**다(실호출 확인: 30행,
        최신순). tday_rltv는 당일 누적값이라 모든 행이 같으므로 최신 행만 본다.
        inquire-price(FHKST01010100)에는 이 필드가 없다 — 2026-08-11에 그걸 몰라
        전 종목 결손이 났다.
        """
        key = f"tick_power_{code}"
        cached = self._get_cached(key, self.TTL_REALTIME)
        if cached is not None:
            return cached['value']

        body = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-ccnl",
            "FHKST01010300",
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
        )
        rows = body.get("output") or []
        if isinstance(rows, dict):
            rows = [rows]
        value = self._to_float(rows[0].get("tday_rltv", 0)) if rows else 0.0
        self._set_cache(key, {'value': value})
        return value
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_kis_tick_power.py -v`
Expected: PASS (3건)

- [ ] **Step 5: 커밋**

```bash
git add src/trade/kis_data_provider.py tests/test_kis_tick_power.py
git commit -m "feat(kis): 체결강도 조회를 하드닝된 클라이언트로 옮긴다"
```

---

### Task 2: `get_price_quote`에 빠진 6개 필드 추가

**Files:**
- Modify: `src/trade/kis_data_provider.py:506-518` (`get_price_quote`의 `result` dict, 그리고
  `out`이 빈 경우의 폴백 dict `:500-502`)
- Test: `tests/test_kis_price_quote_fields.py` (신규)

**Interfaces:**
- Consumes: 없음
- Produces: `get_price_quote`가 기존 키에 더해 `foreign_rate: float`, `eps: int`,
  `bps: int`, `mkt_cap: int`, `amount: int`, `volume: int`를 돌려준다.

**주의:** 이 함수는 이미 `program_trader`·`trade_engine`이 쓴다. **키를 추가만 하고 기존
키의 이름·타입을 바꾸지 않는다.** 폴백 dict에도 같은 키를 넣어야 호출부가
`KeyError` 없이 돈다.

- [ ] **Step 1: 실패 테스트를 쓴다**

```python
"""data_fetcher가 쓰던 필드를 get_price_quote가 마저 돌려줘야 사본을 지울 수 있다."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.trade.kis_data_provider import KISDataProvider

OUT = {
    'stck_prpr': '18000', 'prdy_ctrt': '3.6', 'per': '11.2', 'pbr': '0.9',
    'bstp_kor_isnm': '건설 ', 'w52_hgpr': '20000', 'w52_lwpr': '9000',
    'stck_oprc': '17000', 'stck_hgpr': '18500', 'stck_lwpr': '16800',
    'stck_sdpr': '17310',
    'hts_frgn_ehrt': '3.47', 'eps': '1500', 'bps': '20000',
    'hts_avls': '1234', 'acml_tr_pbmn': '1234567890', 'acml_vol': '4321',
}


def _provider(monkeypatch, body):
    p = object.__new__(KISDataProvider)
    p._token, p._base_url = 'tok', 'https://x'
    p._cache = {}
    monkeypatch.setattr(KISDataProvider, '_get', lambda self, *a, **k: body)
    return p


def test_returns_the_fields_data_fetcher_parsed_by_hand(monkeypatch):
    q = _provider(monkeypatch, {'rt_cd': '0', 'output': OUT}).get_price_quote('002990')
    assert q['foreign_rate'] == 3.47
    assert q['eps'] == 1500
    assert q['bps'] == 20000
    assert q['mkt_cap'] == 1234
    assert q['amount'] == 1234567890
    assert q['volume'] == 4321


def test_existing_keys_are_unchanged(monkeypatch):
    """회귀 방지 — program_trader·trade_engine이 이미 이 키들을 쓴다."""
    q = _provider(monkeypatch, {'rt_cd': '0', 'output': OUT}).get_price_quote('002990')
    assert q['price'] == 18000 and q['per'] == 11.2 and q['open_price'] == 17000
    assert q['sector_name'] == '건설'


def test_empty_response_still_carries_every_key(monkeypatch):
    """폴백에 키가 빠지면 호출부가 KeyError로 죽는다."""
    q = _provider(monkeypatch, {}).get_price_quote('002990')
    for k in ('foreign_rate', 'eps', 'bps', 'mkt_cap', 'amount', 'volume'):
        assert q[k] == 0
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_kis_price_quote_fields.py -v`
Expected: FAIL — `KeyError: 'foreign_rate'`

- [ ] **Step 3: 최소 구현**

`get_price_quote`의 빈 응답 폴백에 6개 키를 추가:

```python
            result = {"price": 0, "change_rate_pct": 0.0, "per": 0.0, "pbr": 0.0,
                      "sector_name": "", "w52_hgpr": 0, "w52_lwpr": 0,
                      "open_price": 0, "day_high": 0, "day_low": 0, "prev_close": 0,
                      "foreign_rate": 0.0, "eps": 0, "bps": 0,
                      "mkt_cap": 0, "amount": 0, "volume": 0}
```

그리고 정상 경로 `result`에 같은 6개를 추가(기존 키는 그대로 둔다):

```python
            "foreign_rate": self._to_float(out.get("hts_frgn_ehrt", 0)),
            "eps": self._to_int(float(self._to_float(out.get("eps", 0)))),
            "bps": self._to_int(float(self._to_float(out.get("bps", 0)))),
            "mkt_cap": self._to_int(out.get("hts_avls", 0)),
            "amount": self._to_int(out.get("acml_tr_pbmn", 0)),
            "volume": self._to_int(out.get("acml_vol", 0)),
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_kis_price_quote_fields.py -v`
Expected: PASS (3건)

- [ ] **Step 5: 전체 스위트로 회귀를 확인한다**

Run: `python -m pytest tests/ -q`
Expected: 기존 통과 수 + 3, 실패 0

- [ ] **Step 6: 커밋**

```bash
git add src/trade/kis_data_provider.py tests/test_kis_price_quote_fields.py
git commit -m "feat(kis): get_price_quote가 수급·밸류 필드를 마저 돌려준다"
```

---

### Task 3: `data_fetcher`의 KIS 사본을 위임으로 교체

**Files:**
- Modify: `src/pipeline/workers/data_fetcher.py` — `_get_stock_details`의 KIS 블록 2개
  (inquire-price / inquire-ccnl) 삭제 후 provider 호출로 교체. `run()`의 토큰 사전 발급
  블록도 함께 정리.
- Modify: `tests/test_data_fetcher_kis_isolation.py` — `requests.get` monkeypatch가 더는
  KIS를 가로채지 못하므로 provider를 주입하도록 고친다.

**Interfaces:**
- Consumes: `KISDataProvider.get_price_quote(code) -> dict` (Task 2),
  `KISDataProvider.get_tick_power(code) -> float` (Task 1)

**동작 무변경 검사표** — 교체 후 `details`에 남아야 하는 키:
`price`, `current_price`, `change_rate`, `foreign_rate`, `prev_close`, `open_price`,
`day_high`, `day_low`, `per`, `pbr`, `eps`, `bps`, `w52_hgpr`, `w52_lwpr`, `mkt_cap`,
`amount`, `volume`, `sector_name`, `tick_power`

**주의 3가지**
1. 기존 코드는 값이 **참일 때만** 덮어썼다(`if out.get('stck_prpr')`). provider는 0을
   돌려주므로, 같은 의미를 유지하려면 `if q['price']:` 형태를 지켜야 한다. 안 그러면
   네이버에서 얻은 값을 KIS의 0으로 덮어쓴다 — 2026-08-04 실전 0체결의 형태다.
2. `change_rate`는 문자열 포맷(`+3.60%`)이다. `change_rate_pct`(float)에서 다시 만든다.
3. 네이버 블록(`frgn.naver` 수급, `main.naver` 호가)은 **손대지 않는다.**

- [ ] **Step 1: 동작 무변경을 고정하는 실패 테스트를 쓴다**

`tests/test_data_fetcher_kis_isolation.py`에 추가:

```python
class _FakeProvider:
    def __init__(self, quote=None, tick=0.0):
        self._quote = quote or {}
        self._tick = tick

    def get_price_quote(self, code):
        return self._quote

    def get_tick_power(self, code):
        return self._tick


QUOTE = {
    'price': 18000, 'change_rate_pct': 3.6, 'per': 11.2, 'pbr': 0.9,
    'sector_name': '건설', 'w52_hgpr': 20000, 'w52_lwpr': 9000,
    'open_price': 17000, 'day_high': 18500, 'day_low': 16800, 'prev_close': 17310,
    'foreign_rate': 3.47, 'eps': 1500, 'bps': 20000,
    'mkt_cap': 1234, 'amount': 1234567890, 'volume': 4321,
}


def test_kis_fields_come_from_the_shared_provider(monkeypatch):
    """사본을 지운 뒤에도 같은 키·같은 값이 나와야 한다(동작 무변경)."""
    def fake_get(url, **kw):
        if 'frgn.naver' in url:
            return FakeResponse(frgn_html())
        if 'main.naver' in url:
            return FakeResponse('<table class="type2 type_stock2"></table>')
        raise AssertionError(f'KIS를 직접 부르면 안 된다: {url}')

    monkeypatch.setattr(data_fetcher.requests, 'get', fake_get)
    w = _worker()
    w.kis = _FakeProvider(QUOTE, tick=128.9)

    d = w._get_stock_details('002990')

    assert d['open_price'] == 17000 and d['day_high'] == 18500
    assert d['per'] == 11.2 and d['tick_power'] == 128.9
    assert d['amount'] == 1234567890 and d['sector_name'] == '건설'
    assert d['change_rate'] == '+3.60%'


def test_zero_quote_does_not_overwrite_naver_values(monkeypatch):
    """KIS가 0을 주면 덮어쓰지 않는다 — 08-04 실전 0체결이 이 형태였다."""
    def fake_get(url, **kw):
        if 'frgn.naver' in url:
            return FakeResponse(frgn_html())
        if 'main.naver' in url:
            return FakeResponse('<table class="type2 type_stock2"></table>')
        raise AssertionError(f'KIS를 직접 부르면 안 된다: {url}')

    monkeypatch.setattr(data_fetcher.requests, 'get', fake_get)
    w = _worker()
    w.kis = _FakeProvider({k: 0 for k in QUOTE}, tick=0.0)

    d = w._get_stock_details('002990')

    assert d['prev_close'] == 17940, '네이버가 준 전일종가가 0으로 덮이면 안 된다'
```

`_worker()` 헬퍼에 `w.kis = None` 기본값을 추가하고, 기존 `w.kis_token`·`w.kis_app_key`
설정은 지운다(더는 쓰이지 않는다).

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_data_fetcher_kis_isolation.py -v`
Expected: FAIL — `AssertionError: KIS를 직접 부르면 안 된다: .../inquire-price`

- [ ] **Step 3: `run()`의 토큰 사전 발급 블록을 provider 생성으로 교체**

`data_fetcher.py`의 `# [V61.0] KIS API 토큰 사전 발급` 블록 전체를 다음으로 교체:

```python
        # KIS 호출은 KISDataProvider 하나로 한다. 예전엔 여기서 토큰을 직접 받아
        # requests로 굴리는 사본이 있었는데, 그 사본에는 rt_cd 검사도 응답 형태
        # 대응도 캐시도 없었다 — 2026-08-12에 그 차이로 두 번 사고가 났다.
        try:
            from src.trade.kis_data_provider import KISDataProvider
            self.kis = KISDataProvider()
        except Exception as e:
            self.kis = None
            self.log_error(f"KIS 클라이언트 초기화 실패: {e} — 시세·체결강도 조회 불가")
```

- [ ] **Step 4: `_get_stock_details`의 KIS 블록 2개를 위임으로 교체**

`details['tick_power'] = 0.0`부터 inquire-ccnl `except` 끝까지(= 네이버 호가 블록 바로
앞까지)를 다음으로 교체:

```python
        # KIS 보강. 네이버 파싱과 같은 try에 묶지 않는다 — 2026-08-03에 둘이 한
        # 블록이라 main.naver가 타임아웃 나자 KIS 호출이 실행조차 되지 않았다.
        details['tick_power'] = 0.0
        if getattr(self, 'kis', None):
            try:
                q = self.kis.get_price_quote(code)
                # 0으로 덮어쓰지 않는다. 조회 실패도 0으로 오므로, 덮으면 네이버가
                # 얻어둔 값을 잃는다(2026-08-04 실전 0체결의 형태).
                if q.get('price'):
                    details['price'] = q['price']
                    details['current_price'] = q['price']
                if q.get('change_rate_pct'):
                    r = q['change_rate_pct']
                    details['change_rate'] = f"+{r:.2f}%" if r >= 0 else f"{r:.2f}%"
                for src, dst in (
                    ('foreign_rate', 'foreign_rate'), ('prev_close', 'prev_close'),
                    ('open_price', 'open_price'), ('day_high', 'day_high'),
                    ('day_low', 'day_low'), ('per', 'per'), ('pbr', 'pbr'),
                    ('eps', 'eps'), ('bps', 'bps'), ('w52_hgpr', 'w52_hgpr'),
                    ('w52_lwpr', 'w52_lwpr'), ('mkt_cap', 'mkt_cap'),
                    ('amount', 'amount'), ('volume', 'volume'),
                ):
                    if q.get(src):
                        details[dst] = q[src]
                if q.get('sector_name'):
                    details['sector_name'] = q['sector_name']
            except Exception as e:
                print(f"   [DataFetcher] KIS 시세 보강 실패 {code}: {e}")
            try:
                details['tick_power'] = self.kis.get_tick_power(code)
            except Exception as e:
                print(f"   [DataFetcher] KIS 체결강도 조회 실패 {code}: {e}")
```

- [ ] **Step 5: 고아가 된 코드를 지운다**

`data_fetcher.py`에서 더는 참조되지 않는 것: `TICK_POWER_FIELD`, `tick_power_probe`,
`self._tick_probe_logged`(`__init__`), `import os`(다른 용도가 없으면).
`tests/test_tick_power_probe.py`에서 `tick_power_probe`를 쓰는 테스트를 지운다.
**`missing_field_alert`는 남긴다** — 결손 경보는 계속 필요하다.

주의: 지우기 전에 `grep -rn "tick_power_probe\|TICK_POWER_FIELD" .`로 다른 참조가 없는지
확인할 것.

- [ ] **Step 6: 통과를 확인한다**

Run: `python -m pytest tests/ -q`
Expected: 실패 0

- [ ] **Step 7: 실제 KIS로 끝단 확인**

```bash
python - <<'PY'
import os, sys
sys.path.insert(0, '.')
for line in open('.env', encoding='utf-8'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
from src.pipeline.workers.data_fetcher import DataFetcherWorker
from src.trade.kis_data_provider import KISDataProvider
w = object.__new__(DataFetcherWorker)
w.kis = KISDataProvider()
for code in ('005930', '000660'):
    d = w._get_stock_details(code)
    print(code, {k: d.get(k) for k in
                 ('price', 'open_price', 'per', 'tick_power', 'amount', 'sector_name')})
PY
```

Expected: 두 종목 모두 `price`·`open_price`·`per`·`tick_power`가 0이 아니다.
**0이 하나라도 나오면 배포하지 말 것** — 그게 정확히 이번에 고치려는 사고의 형태다.

- [ ] **Step 8: 커밋**

```bash
git add src/pipeline/workers/data_fetcher.py tests/test_data_fetcher_kis_isolation.py tests/test_tick_power_probe.py
git commit -m "refactor(scraper): KIS 호출을 하드닝된 클라이언트 하나로 모은다"
```

---

## 자체 검토

**커버리지:** 위 "지금 상태" 표의 4개 격차(rt_cd·응답형태·캐시·타임아웃)는 Task 3에서
provider 위임으로 한 번에 닫힌다. 필드 격차 6개는 Task 2, `tick_power`는 Task 1.

**빈칸 없음:** 모든 스텝에 실제 코드가 들어 있다.

**타입 일관성:** Task 1이 `get_tick_power -> float`, Task 2가 `get_price_quote -> dict`(키
추가만). Task 3의 `_FakeProvider`가 그 두 시그니처를 그대로 흉내 낸다.

**남기는 위험**
- Task 3이 이 계획에서 가장 위험하다. 실전 매매가 쓰는 값이 지나가는 경로다. Step 7의
  실호출 확인을 건너뛰지 말 것.
- `tests/test_data_fetcher_kis_isolation.py`의 기존 3개 테스트는 `requests.get` 훅에
  기대고 있다. Task 3에서 KIS 부분이 provider로 빠지므로 **그 테스트들의 KIS 단언은
  의미를 잃는다.** 네이버 격리(main.naver 실패해도 살아남는지)는 여전히 유효하니
  그 부분만 남기고 KIS 단언은 새 테스트로 옮긴다.
- 롤백은 커밋 단위 revert로 충분하다. 상태 파일·원장 포맷을 건드리지 않는다.
