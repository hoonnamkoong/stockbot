# 매수 지정가 + 체결 확인 원장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 프로그램 매매의 매수를 지정가로 바꾸고, 원장을 "주문했다"가 아니라 "체결됐다"로 쓴다.

**Architecture:** 주문 직후 원장을 갱신하던 것을 `pending_orders`(원장 상태)로 미루고, 다음 사이클(60초)에 KIS 체결 조회로 확정한다. 매수는 확인 후 신규 반영, 매도는 시장가로 즉시 반영한 뒤 실측가로 차액 정정한다. 정산 로직은 I/O 없는 순수 함수로 분리한다.

**Tech Stack:** Python 3.10 (pytest), TypeScript (node --test), KIS OpenAPI (TTTC0802U/0801U 주문, TTTC0803U 취소, TTTC8001R 체결조회)

**설계 문서:** `docs/superpowers/specs/2026-08-10-limit-order-fill-confirmation-design.md`

## Global Constraints

- **fail-closed**: 조회 실패·취소 실패는 원장을 건드리지 않고 pending을 유지한다. 모르는 상태에서 주문을 내지 않는다.
- **추정값을 확정인 척 기록하지 않는다**: `odno`가 없으면(`''`/`'UNKNOWN'`) 추정 매칭 금지, 경보만.
- **종목당 pending 1건**: 이 제약이 중복 주문 방지의 근거다.
- **매도는 시장가 유지**: `ORD_DVSN='01'`, `ORD_UNPR='0'`. 기존 테스트(683cc55 회귀 방지)를 깨지 말 것.
- **지정가는 심 판단가**: `check_buy_drift`가 돌려주는 `live_px`로 덮어쓰지 않는다.
- **정산은 심 판단보다 먼저**: 낡은 보유 상태로 판단하면 안 된다.
- 커밋 메시지는 파일로 전달한다(`git commit -F <파일>`). 인라인 heredoc은 이 환경에서 깨진다.

---

### Task 1: 체결 조회를 3값으로 가른다

`find_execution_by_odno`가 미체결과 조회 실패를 똑같이 `None`으로 돌려준다. 이 둘은 반대로 처리해야 한다 — 미체결은 취소, 조회 실패는 원장 불변. 구분이 없으면 일시적 API 오류에 팔린 포지션을 되살린다.

**Files:**
- Modify: `src/trade/executions.py`
- Test: `tests/test_kis_executions.py` (기존 파일에 추가)

**Interfaces:**
- Consumes: 없음
- Produces:
  - `FILLED = 'filled'`, `UNFILLED = 'unfilled'`, `UNKNOWN = 'unknown'` (모듈 상수)
  - `lookup_execution(odno: str, from_date: str | None = None, to_date: str | None = None) -> tuple[str, dict | None]`
  - 기존 `get_daily_executions`·`find_execution_by_odno`는 시그니처·동작 그대로 유지

- [ ] **Step 1: Write the failing test**

`tests/test_kis_executions.py` 끝에 추가:

```python
from src.trade import executions
from src.trade.executions import FILLED, UNFILLED, UNKNOWN, lookup_execution


def test_lookup_returns_filled_with_the_fill(monkeypatch):
    fill = {'odno': '0007441100', 'code': '353200', 'name': '대덕전자',
            'side': 'SELL', 'price': 108000.0, 'qty': 1, 'amount': 108000.0,
            'time': '20260810 094437'}
    monkeypatch.setattr(executions, '_request_executions', lambda *a, **k: [fill])

    status, got = lookup_execution('0007441100')

    assert status == FILLED
    assert got == fill


def test_lookup_returns_unfilled_when_query_succeeds_with_no_rows(monkeypatch):
    """조회는 됐는데 체결이 없다 = 미체결. 취소해도 되는 상태다."""
    monkeypatch.setattr(executions, '_request_executions', lambda *a, **k: [])

    assert lookup_execution('0007441100') == (UNFILLED, None)


def test_lookup_returns_unknown_when_query_itself_fails(monkeypatch):
    """조회 실패는 미체결이 아니다 — 이걸 섞으면 팔린 포지션을 되살린다."""
    monkeypatch.setattr(executions, '_request_executions', lambda *a, **k: None)

    assert lookup_execution('0007441100') == (UNKNOWN, None)


def test_lookup_without_odno_is_unknown_not_unfilled(monkeypatch):
    """주문번호가 없으면 추적 자체가 불가능하다. 미체결로 단정하면 안 된다."""
    monkeypatch.setattr(executions, '_request_executions', lambda *a, **k: [])

    assert lookup_execution('') == (UNKNOWN, None)
    assert lookup_execution('UNKNOWN') == (UNKNOWN, None)


def test_lookup_ignores_rows_for_other_orders(monkeypatch):
    monkeypatch.setattr(executions, '_request_executions',
                        lambda *a, **k: [{'odno': '9999999999', 'qty': 5, 'price': 100.0}])

    assert lookup_execution('0007441100') == (UNFILLED, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_kis_executions.py -q`
Expected: FAIL — `ImportError: cannot import name 'FILLED'`

- [ ] **Step 3: Write minimal implementation**

`src/trade/executions.py`에서 HTTP 부분을 `_request_executions`로 떼어내고(실패는 `None`), 기존 `get_daily_executions`는 `or []`로 감싸 동작을 보존한다.

```python
FILLED = 'filled'
UNFILLED = 'unfilled'
UNKNOWN = 'unknown'


def _request_executions(from_date=None, to_date=None, odno=''):
    """KIS 일별체결조회 원본. **조회 실패는 None, 성공은 리스트(0건 포함).**

    이 구분이 이 함수의 존재 이유다. 호출부가 미체결('조회는 됐는데 없다')과
    조회 실패('모른다')를 반대로 처리하기 때문이다.
    """
    # 기존 get_daily_executions(현 :22-107)의 본문을 통째로 옮긴다. 바꾸는 것은
    # **조기 반환 6곳뿐**이고, 전부 `return []` → `return None`이다:
    #   토큰 없음 / account_no 없음 / 계좌번호 10자 미만 /
    #   status_code != 200 / rt_cd != '0' / except 블록
    # 루프 안의 `continue`와 마지막 `return fills`는 그대로 둔다 —
    # 파싱에 실패한 행 하나는 조회 실패가 아니다.


def get_daily_executions(from_date=None, to_date=None, odno=''):
    """기존 소비자용 fail-quiet 래퍼. 조회 실패와 0건을 구분하지 않는다."""
    return _request_executions(from_date, to_date, odno) or []


def lookup_execution(odno, from_date=None, to_date=None):
    """주문번호 하나의 체결 상태. ('filled', fill) | ('unfilled', None) | ('unknown', None)"""
    if not odno or odno == 'UNKNOWN':
        return UNKNOWN, None
    rows = _request_executions(from_date, to_date, odno=odno)
    if rows is None:
        return UNKNOWN, None
    for f in rows:
        if f.get('odno') == odno:
            return FILLED, f
    return UNFILLED, None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_kis_executions.py -q`
Expected: PASS (신규 5개 + 기존 전부)

- [ ] **Step 5: Commit**

```bash
git add src/trade/executions.py tests/test_kis_executions.py
git commit -F - <<'MSG'
feat(trade): 체결 조회를 미체결·조회실패로 가른다

find_execution_by_odno는 둘 다 None을 돌려줬다. 곧 붙일 pending 정산은 이
둘을 반대로 처리한다 — 미체결은 취소, 조회 실패는 원장 불변. 섞으면 일시적
API 오류에 팔린 포지션을 되살린다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

### Task 2: KIS 주문취소 (TTTC0803U)

미체결 주문을 매 사이클 거두려면 취소가 필요한데 지금 없다. `executions.py`와 같은 방식으로 파이썬에서 KIS를 직접 호출한다(주문 접수만 Vercel 라우트를 거치고, 조회·관리성 호출은 파이썬 직접이 이 레포의 기존 패턴이다).

**Files:**
- Create: `src/trade/order_cancel.py`
- Test: `tests/test_order_cancel.py`

**Interfaces:**
- Consumes: `src.trade.auth.get_access_token`, `get_base_url` (기존)
- Produces: `cancel_order(odno: str, code: str, qty: int) -> bool` — 취소 성공 시 True. 실패·주문번호 없음은 False.

- [ ] **Step 1: Write the failing test**

```python
"""미체결 주문 취소(TTTC0803U). 실패를 성공으로 오인하면 같은 종목에 주문이 겹친다."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.trade import order_cancel


class _Res:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _patch(monkeypatch, res, captured=None):
    monkeypatch.setattr(order_cancel, 'get_access_token', lambda: 'tok')
    monkeypatch.setattr(order_cancel, 'get_base_url', lambda: 'https://kis.test')
    monkeypatch.setenv('KIS_ACCOUNT_NO', '1234567801')
    monkeypatch.setenv('KIS_APP_KEY', 'k')
    monkeypatch.setenv('KIS_APP_SECRET', 's')
    monkeypatch.setenv('KIS_IS_VIRTUAL', 'false')

    def fake_post(url, headers=None, json=None, timeout=None):
        if captured is not None:
            captured.update({'url': url, 'headers': headers, 'body': json})
        return res

    monkeypatch.setattr(order_cancel.requests, 'post', fake_post)


def test_returns_true_on_success(monkeypatch):
    _patch(monkeypatch, _Res(200, {'rt_cd': '0', 'msg1': '정상처리'}))
    assert order_cancel.cancel_order('0007441100', '353200', 3) is True


def test_returns_false_when_kis_rejects(monkeypatch):
    _patch(monkeypatch, _Res(200, {'rt_cd': '1', 'msg1': '취소할 수량이 없습니다'}))
    assert order_cancel.cancel_order('0007441100', '353200', 3) is False


def test_returns_false_on_http_error(monkeypatch):
    _patch(monkeypatch, _Res(500, {}))
    assert order_cancel.cancel_order('0007441100', '353200', 3) is False


def test_returns_false_without_odno(monkeypatch):
    """주문번호가 없으면 취소할 대상을 특정할 수 없다. 호출조차 하지 않는다."""
    called = {'n': 0}
    monkeypatch.setattr(order_cancel, 'get_access_token', lambda: 'tok')
    monkeypatch.setattr(order_cancel.requests, 'post',
                        lambda *a, **k: called.__setitem__('n', called['n'] + 1))

    assert order_cancel.cancel_order('', '353200', 3) is False
    assert order_cancel.cancel_order('UNKNOWN', '353200', 3) is False
    assert called['n'] == 0


def test_sends_full_cancel_with_required_fields(monkeypatch):
    captured = {}
    _patch(monkeypatch, _Res(200, {'rt_cd': '0'}), captured)

    order_cancel.cancel_order('0007441100', '353200', 3)

    body = captured['body']
    assert body['ORGN_ODNO'] == '0007441100'
    assert body['RVSE_CNCL_DVSN_CD'] == '02', '02=취소 (01=정정)'
    assert body['QTY_ALL_ORD_YN'] == 'Y', '잔량 전부 취소'
    assert body['CANO'] == '12345678'
    assert body['ACNT_PRDT_CD'] == '01'
    assert body['ORD_QTY'] == '3'
    assert captured['headers']['tr_id'] == 'TTTC0803U'


def test_uses_virtual_tr_id_when_virtual(monkeypatch):
    captured = {}
    _patch(monkeypatch, _Res(200, {'rt_cd': '0'}), captured)
    monkeypatch.setenv('KIS_IS_VIRTUAL', 'true')

    order_cancel.cancel_order('0007441100', '353200', 3)

    assert captured['headers']['tr_id'] == 'VTTC0803U'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_order_cancel.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.trade.order_cancel'`

- [ ] **Step 3: Write minimal implementation**

```python
"""KIS 주문취소(TTTC0803U) — 미체결 주문을 거둔다.

매 사이클 미체결을 취소하고 새 판단가로 다시 내는 구조라, 취소가 실패하면
그 종목에 새 주문을 내지 않는다(중복보다 기회손실이 싸다). 그래서 이 함수의
반환값은 "성공했다고 믿어도 되는가"여야 하고, 애매하면 False다.
"""
import os

import requests

from src.trade.auth import get_access_token, get_base_url


def cancel_order(odno: str, code: str, qty: int) -> bool:
    """미체결 잔량을 전부 취소한다. 성공하면 True.

    주문번호가 없으면 대상을 특정할 수 없으므로 호출하지 않고 False.
    """
    if not odno or odno == 'UNKNOWN':
        return False
    token = get_access_token()
    if not token:
        return False

    acc = os.environ.get('KIS_ACCOUNT_NO', '').strip().replace('-', '').replace(' ', '')
    if len(acc) < 10:
        return False
    is_virtual = os.environ.get('KIS_IS_VIRTUAL', 'false').lower() == 'true'

    headers = {
        'content-type': 'application/json; charset=utf-8',
        'authorization': f'Bearer {token}',
        'appkey': os.environ.get('KIS_APP_KEY', '').strip(),
        'appsecret': os.environ.get('KIS_APP_SECRET', '').strip(),
        'tr_id': 'VTTC0803U' if is_virtual else 'TTTC0803U',
        'custtype': 'P',
    }
    body = {
        'CANO': acc[:8],
        'ACNT_PRDT_CD': acc[8:10],
        'KRX_FWDG_ORD_ORGNO': '',
        'ORGN_ODNO': odno,
        'ORD_DVSN': '00',
        'RVSE_CNCL_DVSN_CD': '02',   # 02=취소
        'ORD_QTY': str(qty),
        'ORD_UNPR': '0',
        'QTY_ALL_ORD_YN': 'Y',       # 잔량 전부
    }

    try:
        res = requests.post(
            f'{get_base_url()}/uapi/domestic-stock/v1/trading/order-rvsecncl',
            headers=headers, json=body, timeout=10,
        )
        if res.status_code != 200:
            return False
        return res.json().get('rt_cd') == '0'
    except Exception:
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_order_cancel.py -q`
Expected: PASS (7개)

- [ ] **Step 5: Commit**

```bash
git add src/trade/order_cancel.py tests/test_order_cancel.py
git commit -F - <<'MSG'
feat(trade): KIS 주문취소(TTTC0803U)

미체결을 매 사이클 거두려면 필요한데 없었다. 애매한 응답은 전부 False다 —
취소 실패를 성공으로 오인하면 같은 종목에 주문이 겹친다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

### Task 3: 지정가 주문을 KIS까지 흘린다

`buildOrderRequest`는 지금 무조건 시장가다. 매수만 지정가로 보낼 수 있게 하고, 파이썬 → 라우트 → KIS 경로에 주문유형·단가를 실어 보낸다.

**Files:**
- Modify: `src/lib/kis-api.ts:431-455` (`buildOrderRequest`), `placeRealOrder`
- Modify: `src/app/api/trade/order/route.ts` (body에서 `ordType`/`limitPrice` 수신)
- Modify: `src/trade_executor.py:49` (`place_order_via_vercel`)
- Test: `src/lib/kis-order.test.ts` (기존 파일에 추가)

**Interfaces:**
- Consumes: 없음
- Produces:
  - TS: `buildOrderRequest(code, qty, side, opts)` — `opts`에 `ordType?: 'market' | 'limit'`, `limitPrice?: number` 추가. 미지정 시 기존 시장가 동작
  - Python: `place_order_via_vercel(side, code, qty, price, ord_type='market')`

- [ ] **Step 1: Write the failing test**

`src/lib/kis-order.test.ts` 끝에 추가:

```typescript
test('지정가 매수는 ORD_DVSN=00과 실제 단가를 싣는다', () => {
  const { body } = buildOrderRequest('353200', 3, 'buy',
    { ...REAL, ordType: 'limit', limitPrice: 111000 });

  assert.equal(body.ORD_DVSN, '00', '00=지정가');
  assert.equal(body.ORD_UNPR, '111000');
});

test('ordType을 안 주면 기존 시장가 그대로다 — 호출부를 안 고쳐도 동작이 안 바뀐다', () => {
  const { body } = buildOrderRequest('005930', 1, 'buy', REAL);

  assert.equal(body.ORD_DVSN, '01');
  assert.equal(body.ORD_UNPR, '0');
});

test('지정가인데 단가가 없거나 0이면 시장가로 떨어지지 않는다 — 던진다', () => {
  // 조용히 시장가로 내면 "원하는 가격에만 산다"가 소리 없이 깨진다.
  assert.throws(() => buildOrderRequest('353200', 3, 'buy',
    { ...REAL, ordType: 'limit' }));
  assert.throws(() => buildOrderRequest('353200', 3, 'buy',
    { ...REAL, ordType: 'limit', limitPrice: 0 }));
});

test('매도는 지정가를 요청해도 시장가다 — 손절은 체결 자체가 목적이다', () => {
  const { body } = buildOrderRequest('353200', 3, 'sell',
    { ...REAL, ordType: 'limit', limitPrice: 111000 });

  assert.equal(body.ORD_DVSN, '01');
  assert.equal(body.ORD_UNPR, '0');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test src/lib/kis-order.test.ts`
Expected: FAIL — 지정가 케이스에서 `ORD_DVSN`이 `'01'`로 나옴

- [ ] **Step 3: Write minimal implementation**

`src/lib/kis-api.ts`:

```typescript
export function buildOrderRequest(
    code: string,
    qty: number,
    side: 'buy' | 'sell',
    opts: { accountNo: string; isVirtual: boolean; ordType?: 'market' | 'limit'; limitPrice?: number },
): { trId: string; body: Record<string, string> } {
    const trId = side === 'buy'
        ? (opts.isVirtual ? 'VTTC0802U' : 'TTTC0802U')
        : (opts.isVirtual ? 'VTTC0801U' : 'TTTC0801U');

    // 매도는 항상 시장가다. 손절·트레일링은 리스크를 줄이려는 행동이라
    // 체결 자체가 목적이고, 미체결로 남으면 손실이 계속 커진다.
    const limit = side === 'buy' && opts.ordType === 'limit';
    if (limit && !(Number(opts.limitPrice) > 0)) {
        // 조용히 시장가로 떨어뜨리면 "원하는 가격에만 산다"가 소리 없이 깨진다.
        throw new Error('지정가 주문에 단가가 없습니다');
    }

    return {
        trId,
        body: {
            "CANO": opts.accountNo.slice(0, 8),
            "ACNT_PRDT_CD": opts.accountNo.slice(8, 10) || "01",
            "PDNO": code,
            "ORD_DVSN": limit ? "00" : "01",   // 00=지정가, 01=시장가
            "ORD_QTY": qty.toString(),
            // 시장가는 매수·매도 모두 단가 0 필수 (KIS 규칙, 683cc55 회귀 방지)
            "ORD_UNPR": limit ? String(Math.trunc(Number(opts.limitPrice))) : "0",
        },
    };
}
```

`placeRealOrder`에 인자를 흘린다:

```typescript
export async function placeRealOrder(
    code: string, qty: number, price: number, side: 'buy' | 'sell',
    ordType: 'market' | 'limit' = 'market',
): Promise<any> {
    ...
    const { trId: tr_id, body } = buildOrderRequest(code, qty, side, {
        accountNo: config.ACCOUNT_NO,
        isVirtual: config.IS_VIRTUAL,
        ordType,
        limitPrice: price,
    });
    ...
}
```

`src/app/api/trade/order/route.ts` — body 구조분해에 `ordType` 추가하고 호출부에 전달:

```typescript
const { code, qty, price, side, isVirtual, pin, ordType } = body;
...
result = await placeRealOrder(code, Number(qty), Number(price), side,
                              ordType === 'limit' ? 'limit' : 'market');
```

`src/trade_executor.py`:

```python
def place_order_via_vercel(side, code, qty, price, ord_type='market'):
    ...
    payload = {
        "side": side,
        "code": code,
        "qty": qty,
        "price": price,
        "ordType": ord_type,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test src/lib/kis-order.test.ts && npx tsc --noEmit`
Expected: PASS, 타입 에러 없음

- [ ] **Step 5: Commit**

```bash
git add src/lib/kis-api.ts src/lib/kis-order.test.ts src/app/api/trade/order/route.ts src/trade_executor.py
git commit -F - <<'MSG'
feat(order): 매수 지정가 지원 — 매도는 시장가로 고정

ordType 미지정이면 기존 시장가 그대로라 호출부를 안 고쳐도 동작이 안 바뀐다.
지정가인데 단가가 없으면 던진다 — 조용히 시장가로 떨어뜨리면 "원하는 가격에만
산다"가 소리 없이 깨진다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

### Task 4: pending 정산 순수 함수

원장 dict과 조회 결과를 받아 원장을 갱신하고, 취소해야 할 목록을 돌려준다. I/O가 없어야 매수·매도 × 전량·부분·미체결·조회실패를 전부 테스트할 수 있다.

**Files:**
- Create: `src/trade/pending.py`
- Test: `tests/test_pending_reconcile.py`

**Interfaces:**
- Consumes: `src.trade.fees.realized_pnl_after_fees` (기존)
- Produces:
  - `register_pending(ledger, code, odno, side, qty, price, ordered_at, tag=None) -> None`
  - `reconcile_pending(ledger, lookups, today) -> list[dict]`
    - `lookups`: `{odno: (status, fill|None)}` — 호출부가 미리 조회해 넣는다
    - 반환: 취소 요청 `[{'odno': str, 'code': str, 'qty': int}]`
    - 정산한 항목은 `reconcile_pending`이 직접 지운다. 취소 실패 시 되살리는 건
      호출부(Task 6)의 몫이다 — 취소 성공 여부는 I/O라 여기서 알 수 없다.

**정산 규칙 요약**

| side | 조회 | 처리 |
|---|---|---|
| buy | filled | 체결 수량·실측가로 `positions` 반영. 잔량 있으면 취소 요청 |
| buy | unfilled | 원장 불변, 취소 요청 |
| buy | unknown | **pending 유지**, 원장 불변, 취소 요청 없음 |
| sell | filled | `realized_pnl += 실측 − 추정(전량)`, 미체결분 `positions` 복원 |
| sell | unfilled | 추정분 전부 되돌리고 `positions` 전량 복원 |
| sell | unknown | **pending 유지**, 원장 불변 |

매도 보정식이 하나로 떨어진다. 주문 시 `E = est(qty, est_px)`를 더해 뒀으니, 진실이 `A = actual(filled_qty, fill_px)`이면 보정은 `A − E`다. 여기에 미체결 수량만 `positions`로 되돌리면 끝난다.

- [ ] **Step 1: Write the failing test**

```python
"""pending 정산 — 주문과 체결을 가르는 지점.

이 함수가 틀리면 원장이 실계좌와 갈린다. 매수는 체결 전까지 원장에 없고,
매도는 추정으로 먼저 반영된 뒤 실측으로 정정된다는 비대칭이 핵심이다.

조회 실패(unknown)를 미체결로 오인하면 팔린 포지션이 되살아난다. 그래서
unknown은 어떤 경우에도 원장을 건드리지 않는다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.trade.executions import FILLED, UNFILLED, UNKNOWN
from src.trade.fees import realized_pnl_after_fees
from src.trade.pending import reconcile_pending, register_pending

TODAY = '2026-08-11'


def _fill(qty, price, odno='OD1'):
    return {'odno': odno, 'qty': qty, 'price': price}


def _buy_ledger():
    led = {'positions': {}, 'realized_pnl': 0}
    register_pending(led, '353200', 'OD1', 'buy', 3, 111000, '2026-08-11T09:20:31')
    return led


def _sell_ledger():
    """매도는 주문 시 추정으로 이미 반영된 상태다(applied)."""
    led = {'positions': {}, 'realized_pnl': realized_pnl_after_fees(1, 111500, 107900)}
    register_pending(led, '353200', 'OD1', 'sell', 1, 107900, '2026-08-11T09:44:31',
                     avg_price=111500)
    return led


# ---- 매수 ----

def test_buy_filled_enters_positions_at_measured_price():
    led = _buy_ledger()

    cancels = reconcile_pending(led, {'OD1': (FILLED, _fill(3, 111200))}, TODAY)

    assert led['positions']['353200']['quantity'] == 3
    assert led['positions']['353200']['avg_price'] == 111200, '주문가가 아니라 체결 실측가'
    assert cancels == []
    assert led['pending_orders'] == {}


def test_buy_unfilled_leaves_ledger_untouched_and_asks_cancel():
    led = _buy_ledger()

    cancels = reconcile_pending(led, {'OD1': (UNFILLED, None)}, TODAY)

    assert led['positions'] == {}
    assert cancels == [{'odno': 'OD1', 'code': '353200', 'qty': 3}]


def test_buy_partial_enters_filled_part_and_cancels_remainder():
    led = _buy_ledger()

    cancels = reconcile_pending(led, {'OD1': (FILLED, _fill(2, 111200))}, TODAY)

    assert led['positions']['353200']['quantity'] == 2
    assert cancels == [{'odno': 'OD1', 'code': '353200', 'qty': 1}]


def test_buy_unknown_keeps_pending_and_asks_nothing():
    """조회 실패 — 다음 사이클에 다시 본다. 취소도 하지 않는다."""
    led = _buy_ledger()

    cancels = reconcile_pending(led, {'OD1': (UNKNOWN, None)}, TODAY)

    assert led['positions'] == {}
    assert cancels == []
    assert '353200' in led['pending_orders'], 'pending이 남아야 중복 주문이 막힌다'


# ---- 매도 ----

def test_sell_filled_corrects_to_measured_price():
    led = _sell_ledger()

    reconcile_pending(led, {'OD1': (FILLED, _fill(1, 108000))}, TODAY)

    assert led['realized_pnl'] == realized_pnl_after_fees(1, 111500, 108000)
    assert '353200' not in led['positions']


def test_sell_unfilled_restores_position_and_undoes_pnl():
    """시장가가 안 잡히는 경우(거래정지·하한가). 원장이 거짓말하면 고착 포지션이 된다."""
    led = _sell_ledger()

    reconcile_pending(led, {'OD1': (UNFILLED, None)}, TODAY)

    assert led['realized_pnl'] == 0
    assert led['positions']['353200']['quantity'] == 1
    assert led['positions']['353200']['avg_price'] == 111500


def test_sell_partial_restores_only_unfilled_quantity():
    led = {'positions': {}, 'realized_pnl': realized_pnl_after_fees(10, 111500, 107900)}
    register_pending(led, '353200', 'OD1', 'sell', 10, 107900, '2026-08-11T09:44:31',
                     avg_price=111500)

    reconcile_pending(led, {'OD1': (FILLED, _fill(6, 108000))}, TODAY)

    assert led['realized_pnl'] == realized_pnl_after_fees(6, 111500, 108000)
    assert led['positions']['353200']['quantity'] == 4


def test_sell_unknown_keeps_everything_frozen():
    led = _sell_ledger()
    before = led['realized_pnl']

    reconcile_pending(led, {'OD1': (UNKNOWN, None)}, TODAY)

    assert led['realized_pnl'] == before
    assert led['positions'] == {}
    assert '353200' in led['pending_orders']


# ---- 공통 ----

def test_missing_lookup_is_treated_as_unknown():
    """조회 결과에 아예 없는 주문번호를 미체결로 단정하면 안 된다."""
    led = _buy_ledger()

    cancels = reconcile_pending(led, {}, TODAY)

    assert cancels == []
    assert '353200' in led['pending_orders']


def test_register_rejects_second_order_for_same_code():
    """종목당 1건 — 이 제약이 중복 주문 방지의 근거다."""
    led = _buy_ledger()

    register_pending(led, '353200', 'OD2', 'buy', 5, 112000, '2026-08-11T09:22:31')

    assert led['pending_orders']['353200']['odno'] == 'OD1', '기존 주문을 덮어쓰면 안 된다'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pending_reconcile.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.trade.pending'`

- [ ] **Step 3: Write minimal implementation**

```python
"""미체결 주문 장부 — "주문했다"와 "체결됐다"를 가르는 자리.

원장은 오랫동안 KIS 주문 접수(rt_cd='0')를 체결로 간주했다. 시장가에서는
대체로 맞았지만 지정가에서는 상시로 깨진다. 이 모듈이 그 간극을 관리한다.

**비대칭이 핵심이다.**
  - 매수: 체결 확인 전까지 원장에 넣지 않는다
  - 매도: 시장가라 즉시 반영하고, 다음 사이클에 실측가로 정정한다
    (반영하지 않으면 다음 사이클에 같은 종목을 또 판다)

I/O를 하지 않는다. 조회 결과를 받아 원장 dict을 제자리에서 갱신하고, 취소가
필요한 목록을 돌려줄 뿐이다.
"""
from src.trade.executions import FILLED, UNFILLED, UNKNOWN
from src.trade.fees import realized_pnl_after_fees


def register_pending(ledger, code, odno, side, qty, price, ordered_at,
                     avg_price=None, tag=None):
    """주문을 pending에 올린다. **종목당 1건** — 이미 있으면 덮어쓰지 않는다.

    덮어쓰면 먼저 낸 주문의 주문번호를 잃어 영원히 정산도 취소도 못 한다.
    """
    pend = ledger.setdefault('pending_orders', {})
    if code in pend:
        return
    pend[code] = {
        'odno': odno, 'side': side, 'qty': int(qty), 'price': float(price),
        'ordered_at': ordered_at, 'avg_price': avg_price, 'tag': tag,
    }


def reconcile_pending(ledger, lookups, today):
    """조회 결과로 pending을 정산한다. 반환은 취소해야 할 주문 목록.

    `lookups`에 없는 주문번호는 UNKNOWN으로 본다 — 조회하지 못한 것을
    미체결로 단정하면 팔린 포지션이 되살아난다.
    """
    pend = ledger.setdefault('pending_orders', {})
    positions = ledger.setdefault('positions', {})
    cancels = []

    for code in list(pend):
        p = pend[code]
        status, fill = lookups.get(p['odno'], (UNKNOWN, None))
        if status == UNKNOWN:
            continue                       # 원장 불변, pending 유지

        filled_qty = int(fill['qty']) if (status == FILLED and fill) else 0
        fill_px = float(fill['price']) if (status == FILLED and fill) else 0.0
        ordered_qty = p['qty']

        if p['side'] == 'buy':
            if filled_qty > 0:
                _enter_position(positions, code, p, filled_qty, fill_px, today)
            if filled_qty < ordered_qty:
                cancels.append({'odno': p['odno'], 'code': code,
                                'qty': ordered_qty - filled_qty})
        else:
            _correct_sell(ledger, positions, code, p, filled_qty, fill_px)

        del pend[code]

    return cancels


def _enter_position(positions, code, p, qty, price, today):
    """체결 실측가로 포지션에 넣는다. 추가 매수면 평단을 가중평균한다."""
    if code in positions:
        cur = positions[code]
        oq = cur['quantity']
        nq = oq + qty
        cur['avg_price'] = ((oq * cur.get('avg_price', price)) + qty * price) / nq
        cur['quantity'] = nq
        cur['peak_price'] = max(cur.get('peak_price', price), price)
    else:
        positions[code] = {
            'name': p.get('name', code), 'quantity': qty, 'avg_price': price,
            'peak_price': price, 'entry_date': today, 'is_scaled_out': False,
        }
    if p.get('tag'):
        positions[code]['tag'] = p['tag']


def _correct_sell(ledger, positions, code, p, filled_qty, fill_px):
    """주문 시 추정으로 더한 값을 실측으로 갈아끼우고, 안 팔린 수량을 되돌린다.

    주문 시 `E = est(ordered_qty, 주문가)`를 더해 뒀으므로, 진실
    `A = actual(filled_qty, 체결가)`에 대해 보정은 `A - E` 하나로 떨어진다.
    """
    avg = float(p.get('avg_price') or 0)
    estimated = realized_pnl_after_fees(p['qty'], avg, p['price']) if avg else 0.0
    actual = realized_pnl_after_fees(filled_qty, avg, fill_px) if (avg and filled_qty) else 0.0
    correction = actual - estimated
    ledger['realized_pnl'] = round(ledger.get('realized_pnl', 0) + correction, 2)

    tag = p.get('tag')
    if tag:
        by_tag = (ledger.get('turn') or {}).get('by_tag')
        if by_tag is not None:
            by_tag[tag] = round(by_tag.get(tag, 0.0) + correction, 2)

    unfilled = p['qty'] - filled_qty
    if unfilled > 0 and avg:
        cur = positions.get(code)
        if cur:
            oq = cur['quantity']
            nq = oq + unfilled
            cur['avg_price'] = ((oq * cur.get('avg_price', avg)) + unfilled * avg) / nq
            cur['quantity'] = nq
        else:
            positions[code] = {
                'name': p.get('name', code), 'quantity': unfilled, 'avg_price': avg,
                'peak_price': avg, 'entry_date': p.get('entry_date', ''),
                'is_scaled_out': False,
            }
            if tag:
                positions[code]['tag'] = tag
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pending_reconcile.py -q`
Expected: PASS (11개)

- [ ] **Step 5: Commit**

```bash
git add src/trade/pending.py tests/test_pending_reconcile.py
git commit -F - <<'MSG'
feat(trade): pending 정산 — 주문과 체결을 가른다

매수는 체결 확인 전까지 원장에 넣지 않고, 매도는 시장가라 즉시 반영한 뒤
실측가로 차액을 정정한다. 조회 실패(unknown)는 어떤 경우에도 원장을 건드리지
않는다 — 미체결로 오인하면 팔린 포지션이 되살아난다.

I/O가 없어 매수·매도 × 전량·부분·미체결·조회실패를 전부 테스트한다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

### Task 5: 중복 주문 가드에 pending을 넣는다

매수 후보 필터가 `positions`만 본다. 지정가로 바꾸면 체결 전까지 `positions`가 비어 있으므로, pending을 안 보면 같은 종목에 주문이 겹친다. 2026-07 진흥기업 5연속 매수와 같은 형태다.

**Files:**
- Modify: `src/pipeline/workers/program_trader.py:343-368` (`_make_adapter`의 `_buy`), 원장 기본 shape(`:130`, `:157`)
- Test: `tests/test_program_pending_guard.py`

**Interfaces:**
- Consumes: Task 4의 `register_pending`
- Produces: `_make_adapter(sim, snapshot_state, today, real_holdings=None, pending_codes=None)` — `pending_codes`는 `set[str]`

- [ ] **Step 1: Write the failing test**

```python
"""미체결 주문이 있는 종목은 다시 사지 않는다.

지정가로 바꾸면 체결 전까지 원장 positions가 비어 있다. pending을 안 보면
매 사이클 같은 종목에 주문이 쌓이고, 나중에 한꺼번에 체결되면 의도한 수량의
몇 배를 산다. 2026-07 진흥기업 5연속 매수가 이 형태였다(그때 원인도
"원장이 비어 있어 중복 판정을 못 했다").
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.program_trader import _make_adapter


class _Sim:
    def __init__(self):
        self.state = {}


def _snapshot(cash=1_000_000):
    return {'cash': cash, 'portfolio': {}, 'invested': 0}


def test_buy_is_blocked_when_order_is_pending():
    sim, snap = _Sim(), _snapshot()
    orders = _make_adapter(sim, snap, '2026-08-11', {}, pending_codes={'353200'})

    assert sim.buy('353200', '대덕전자', 111000, 3) is False
    assert orders == []


def test_buy_is_allowed_for_a_code_without_pending():
    sim, snap = _Sim(), _snapshot()
    orders = _make_adapter(sim, snap, '2026-08-11', {}, pending_codes={'005930'})

    assert sim.buy('353200', '대덕전자', 111000, 3) is True
    assert len(orders) == 1


def test_pending_codes_defaults_to_empty():
    """인자를 안 넘긴 기존 호출부의 동작이 바뀌면 안 된다."""
    sim, snap = _Sim(), _snapshot()
    orders = _make_adapter(sim, snap, '2026-08-11', {})

    assert sim.buy('353200', '대덕전자', 111000, 3) is True
    assert len(orders) == 1


def test_sell_is_not_blocked_by_pending():
    """매도는 리스크를 줄이는 행동이라 막지 않는다."""
    sim, snap = _Sim(), _snapshot()
    snap['portfolio']['353200'] = {'name': '대덕전자', 'quantity': 3, 'avg_price': 111000}
    orders = _make_adapter(sim, snap, '2026-08-11', {}, pending_codes={'353200'})

    assert sim.sell('353200', 108000, 3) is True
    assert orders[0]['side'] == 'sell'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_program_pending_guard.py -q`
Expected: FAIL — `_make_adapter() got an unexpected keyword argument 'pending_codes'`

- [ ] **Step 3: Write minimal implementation**

`_make_adapter` 시그니처와 `_buy` 앞부분:

```python
def _make_adapter(sim, snapshot_state: dict, today: str, real_holdings: dict | None = None,
                  pending_codes: set | None = None):
    """...(기존 docstring 유지)
    - 미체결 주문이 걸린 종목은 매수 거부: 지정가는 체결 전까지 원장에 없으므로
      positions만 보면 같은 종목에 주문이 쌓인다."""
    sim.state = snapshot_state
    sim.save_state = lambda *a, **k: None
    sim.log_trade = lambda *a, **k: None
    real_holdings = real_holdings or {}
    pending_codes = pending_codes or set()
    orders: list[dict] = []

    def _buy(code, name, price, quantity, reason=""):
        if code in pending_codes:
            return False           # 미체결 주문 있음 — 겹쳐 내지 않는다
        try:
            ...
```

원장 기본 shape에 `pending_orders`를 추가한다(`:130` 부근의 dict 리터럴과 `:157` 부근의 `setdefault` 블록 양쪽):

```python
return {'positions': {}, 'last_run': None, 'sim': None, 'realized_pnl': 0,
        'pending_orders': {}, ...}
```
```python
d.setdefault('realized_pnl', 0)
d.setdefault('pending_orders', {})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_program_pending_guard.py tests/ -q`
Expected: PASS (신규 4개 + 기존 전부)

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/workers/program_trader.py tests/test_program_pending_guard.py
git commit -F - <<'MSG'
feat(program): 미체결 주문이 걸린 종목은 매수하지 않는다

지정가는 체결 전까지 positions가 비어 있어, 지금의 중복 가드로는 매 사이클
같은 종목에 주문이 쌓인다. 나중에 한꺼번에 체결되면 의도한 수량의 몇 배다 —
2026-07 진흥기업 5연속 매수가 이 형태였다.

매도는 막지 않는다. 리스크를 줄이는 행동이다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

### Task 6: 사이클에 정산을 끼우고 매수를 지정가로 전환

여기서 실제 동작이 바뀐다. 앞의 다섯 과제는 전부 부가적이었다.

**Files:**
- Modify: `src/pipeline/workers/program_trader.py` — 정산 단계 삽입(`:578` `reconcile_positions` 직후), 주문 집행부(`:735` 부근)
- Test: `tests/test_program_cycle_order.py`

**Interfaces:**
- Consumes: Task 1 `lookup_execution`, Task 2 `cancel_order`, Task 4 `reconcile_pending`/`register_pending`, Task 5 `pending_codes`
- Produces: 없음(최종 배선)

- [ ] **Step 1: Write the failing test**

```python
"""정산은 심 판단보다 먼저다. 그리고 매수는 원장에 즉시 들어가지 않는다."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.program_trader import settle_pending_orders
from src.trade.executions import FILLED, UNFILLED, UNKNOWN


def test_settle_applies_fills_and_cancels_remainder():
    led = {'positions': {}, 'realized_pnl': 0, 'pending_orders': {
        '353200': {'odno': 'OD1', 'side': 'buy', 'qty': 3, 'price': 111000,
                   'ordered_at': 'x', 'avg_price': None, 'tag': None}}}
    cancelled = []

    settle_pending_orders(
        led, '2026-08-11',
        lookup=lambda odno: (FILLED, {'odno': odno, 'qty': 2, 'price': 111200}),
        cancel=lambda odno, code, qty: cancelled.append((odno, code, qty)) or True,
        log=lambda *a: None, log_error=lambda *a: None,
    )

    assert led['positions']['353200']['quantity'] == 2
    assert cancelled == [('OD1', '353200', 1)]
    assert led['pending_orders'] == {}


def test_failed_cancel_keeps_pending_so_no_new_order_goes_out():
    """취소 실패 → 그 종목에 새 주문을 내지 않는다. 중복보다 기회손실이 싸다."""
    led = {'positions': {}, 'realized_pnl': 0, 'pending_orders': {
        '353200': {'odno': 'OD1', 'side': 'buy', 'qty': 3, 'price': 111000,
                   'ordered_at': 'x', 'avg_price': None, 'tag': None}}}

    settle_pending_orders(
        led, '2026-08-11',
        lookup=lambda odno: (UNFILLED, None),
        cancel=lambda odno, code, qty: False,
        log=lambda *a: None, log_error=lambda *a: None,
    )

    assert '353200' in led['pending_orders']


def test_unknown_lookup_keeps_pending_and_skips_cancel():
    led = {'positions': {}, 'realized_pnl': 0, 'pending_orders': {
        '353200': {'odno': 'OD1', 'side': 'buy', 'qty': 3, 'price': 111000,
                   'ordered_at': 'x', 'avg_price': None, 'tag': None}}}
    cancelled = []

    settle_pending_orders(
        led, '2026-08-11',
        lookup=lambda odno: (UNKNOWN, None),
        cancel=lambda odno, code, qty: cancelled.append(odno) or True,
        log=lambda *a: None, log_error=lambda *a: None,
    )

    assert '353200' in led['pending_orders']
    assert cancelled == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_program_cycle_order.py -q`
Expected: FAIL — `cannot import name 'settle_pending_orders'`

- [ ] **Step 3: Write minimal implementation**

`program_trader.py`에 추가:

```python
def settle_pending_orders(ledger, today, lookup, cancel, log, log_error):
    """pending을 정산하고 미체결 잔량을 취소한다. I/O는 주입받는다(테스트 가능).

    취소가 실패하면 그 종목의 pending을 되살린다 — 다음 사이클에 새 주문을
    막기 위해서다. 중복 주문보다 한 사이클 기회손실이 싸다.
    """
    from src.trade.pending import reconcile_pending, register_pending

    pend = ledger.get('pending_orders') or {}
    if not pend:
        return
    lookups = {p['odno']: lookup(p['odno']) for p in pend.values()}
    snapshot = {c: dict(p) for c, p in pend.items()}

    for req in reconcile_pending(ledger, lookups, today):
        if cancel(req['odno'], req['code'], req['qty']):
            log(f"[Program] 미체결 취소: {req['code']} {req['qty']}주 (odno={req['odno']})")
        else:
            log_error(f"[Program] 취소 실패 — {req['code']} pending 유지, 재주문 안 함")
            ledger.setdefault('pending_orders', {})[req['code']] = snapshot[req['code']]
```

사이클 배선 — `reconcile_positions` 직후(`:578` 부근), 심 판단 **앞**:

```python
        positions = reconcile_positions(ledger, real_holdings, today, log_error)
        ledger['positions'] = positions

        # [신규] pending 정산은 심 판단보다 먼저다. 정산 전에 판단하면 심이
        # 낡은 보유 상태를 본다.
        from src.trade.executions import lookup_execution
        from src.trade.order_cancel import cancel_order
        settle_pending_orders(ledger, today, lookup_execution, cancel_order, log, log_error)
        positions = ledger['positions']
```

어댑터에 pending 전달(`:645` 부근):

```python
        pending_codes = set(ledger.get('pending_orders') or {})
        orders = _make_adapter(sim, snapshot, today, real_holdings, pending_codes)
```

주문 집행부(`:735` 부근) — 매수는 지정가로 내고 원장에 넣지 않는다:

```python
        # 지정가는 **심 판단가**로 건다. 아래 check_buy_drift가 돌려주는 live_px로
        # 덮어쓰면 현재가로 거는 셈이라 "원하는 가격에만 산다"가 무의미해진다.
        limit_price = price
        if side == 'buy':
            allowed, live_px, why = check_buy_drift(code, price, _price_quote)
            if not allowed:
                log(f'[Program] SKIP buy {code} — {why}')
                failed_codes.add(code)
                continue
        try:
            res = place_order_via_vercel(side, code, qty,
                                         limit_price if side == 'buy' else price,
                                         ord_type='limit' if side == 'buy' else 'market')
            if res.get('success'):
                odno = _extract_odno(res)
                if not odno:
                    # 추적 불가 = 정산도 취소도 못 한다. 사람 경로로 올린다.
                    # 반복될 수 있는 조건이라 쿨다운 있는 쪽을 쓴다.
                    alerts.send_alert_once(
                        f'odno_missing_{code}',
                        f'[Program] 주문번호 없음 — {side} {code} {qty}주 추적 불가',
                        now_kst,
                    )
                    log_error(f'[Program] odno 없음: {side} {code} — pending 등록 불가')
                if side == 'sell':
                    # 시장가라 즉시 반영한다. 반영하지 않으면 다음 사이클에 또 판다.
                    # 다음 사이클이 실측가로 차액을 정정한다.
                    avg = positions.get(code, {}).get('avg_price')
                    accrue_realized_pnl(ledger, positions, code, qty, price)
                    try:
                        if turn:
                            record_sell(turn, positions, code, qty, price)
                    except Exception as e:
                        log_error(f'[Program] 턴 체결 기록 실패(무시): {e}')
                    _apply_order_to_positions(positions, o, today)
                    if odno:
                        register_pending(ledger, code, odno, 'sell', qty, price,
                                         now_kst.isoformat(), avg_price=avg, tag=active_tag)
                else:
                    # 매수는 원장에 넣지 않는다. 체결 확인 후 다음 사이클에 들어간다.
                    if odno:
                        register_pending(ledger, code, odno, 'buy', qty, limit_price,
                                         now_kst.isoformat(), tag=active_tag)
```

`register_pending` import를 파일 상단에 추가한다
(`from src.trade.pending import register_pending`).

시각은 헬퍼를 새로 만들지 않는다 — `now_kst`가 이미 이 함수의 인자로 들어와
있고, 레포의 기존 관례가 `now_kst.isoformat()`이다(`ledger['last_run']`,
`ledger['lock_at']`과 같은 형식).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/ -q && npx tsc --noEmit`
Expected: PASS 전부, 타입 에러 없음

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/workers/program_trader.py tests/test_program_cycle_order.py
git commit -F - <<'MSG'
feat(program): 매수를 지정가로, 원장을 체결 확인으로

주문 접수를 체결로 간주하던 것을 끝낸다. 매수는 심 판단가로 지정가를 걸고
체결이 확인된 다음 사이클에 원장에 들어간다. 매도는 시장가 그대로 즉시
반영하고 실측가로 차액을 정정한다.

정산은 심 판단보다 먼저다 — 정산 전에 판단하면 낡은 보유 상태를 본다.
취소 실패는 pending을 되살려 그 종목의 재주문을 막는다.

부수 효과로 원장 avg_price가 추정치가 아니라 KIS 체결 실측가가 된다(E10).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

## 배포 후 관측 (첫 거래일)

코드가 아니라 **관측**이 이 작업의 마지막 단계다. 단위 테스트는 "위임한다"를 검증할 수 있어도 "위임 대상이 실재하는지"는 검증하지 못한다.

- [ ] **체결률** — 매수 주문 대비 체결 건수. 배포 전(하루 8건 수준) 대비 급락하면 재검토. 이게 급락하면 버그가 아니라 **전략이 바뀐 것**이다
- [ ] 원장 `avg_price` vs KIS 체결 실측가 — 오차 0원이어야 한다
- [ ] 매도 `realized_pnl` vs `TTTC8715R` 실측 — 수수료 오차 4원 이내
- [ ] `pending_orders`가 사이클을 넘겨 쌓이지 않는가 (조회·취소 실패 시에만 유지)
- [ ] 중복 주문 0건 / 고착 포지션 0건
- [ ] 로그에 `미체결 취소`·`취소 실패`·`odno 없음`이 어떤 빈도로 찍히는가

**롤백:** Task 6의 `ord_type='limit'`을 `'market'`으로 되돌리면 즉시 원복된다. pending 구조는 남겨도 무해하다(시장가는 다음 사이클에 전량 체결로 확인된다).
