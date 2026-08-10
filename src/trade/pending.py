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
                     avg_price=None, tag=None, snapshot=None):
    """주문을 pending에 올린다. **종목당 1건** — 이미 있으면 덮어쓰지 않는다.

    덮어쓰면 먼저 낸 주문의 주문번호를 잃어 영원히 정산도 취소도 못 한다.

    `snapshot`: 매도 시, 주문을 내기 **직전** `positions[code]`의 사본
    (`entry_date`·`is_scaled_out`·`peak_price` 등). 매도는 주문과 동시에
    포지션이 원장에서 지워지므로(Task 6), 미체결·부분체결로 되돌릴 때 원래
    보유일수·분할매도 여부를 알 방법이 이것뿐이다 — 넘기지 않으면
    `_correct_sell`이 빈 값/기본값으로 복원한다.
    """
    pend = ledger.setdefault('pending_orders', {})
    if code in pend:
        return
    pend[code] = {
        'odno': odno, 'side': side, 'qty': int(qty), 'price': float(price),
        'ordered_at': ordered_at, 'avg_price': avg_price, 'tag': tag,
        'snapshot': snapshot or {},
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
    # 반올림하지 않는다 — 여기서 반올림하면 realized_pnl(before) + correction이
    # actual과 정확히 상쇄되지 않는다. 주문 시 더한 estimated와 지금 빼는
    # estimated가 부동소수점으로 정확히 같은 값이어야 텔레스코핑이 성립한다.
    ledger['realized_pnl'] = ledger.get('realized_pnl', 0) + correction

    tag = p.get('tag')
    if tag:
        by_tag = (ledger.get('turn') or {}).get('by_tag')
        if by_tag is not None:
            by_tag[tag] = by_tag.get(tag, 0.0) + correction

    unfilled = p['qty'] - filled_qty
    if unfilled > 0 and avg:
        cur = positions.get(code)
        if cur:
            oq = cur['quantity']
            nq = oq + unfilled
            cur['avg_price'] = ((oq * cur.get('avg_price', avg)) + unfilled * avg) / nq
            cur['quantity'] = nq
        else:
            # 매도 직후 positions[code]가 이미 지워진 게 정상 경로다(Task 6).
            # entry_date·is_scaled_out은 pending 엔트리 자체엔 없으므로
            # register_pending이 받아 둔 snapshot(매도 직전 원래 포지션)에서
            # 가져온다 — 없으면(snapshot 미전달) 빈 값/기본값으로 떨어진다.
            snap = p.get('snapshot') or {}
            positions[code] = {
                'name': snap.get('name', p.get('name', code)),
                'quantity': unfilled, 'avg_price': avg,
                'peak_price': max(avg, snap.get('peak_price', avg)),
                'entry_date': snap.get('entry_date', ''),
                'is_scaled_out': snap.get('is_scaled_out', False),
            }
            if tag:
                positions[code]['tag'] = tag
