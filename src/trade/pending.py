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
from src.trade.fees import realized_pnl_after_fees, roundtrip_cost


def register_pending(ledger, code, odno, side, qty, price, ordered_at,
                     avg_price=None, tag=None, snapshot=None, log_error=None):
    """주문을 pending에 올린다. **종목당 1건** — 이미 있으면 덮어쓰지 않는다.

    덮어쓰면 먼저 낸 주문의 주문번호를 잃어 영원히 정산도 취소도 못 한다.

    거부는 조용히 넘어가지 않는다: `log_error`가 주어지면 남긴다. 매도가 이
    경로로 거부되면(같은 종목에 이미 pending 매수/매도가 있는 경우) 그 매도는
    정산 대상이 아니게 되어 실현손익이 추정가로 영구히 고정된다 — 사람이 볼
    수 있어야 한다.

    `snapshot`: 매도 시, 주문을 내기 **직전** `positions[code]`의 사본
    (`entry_date`·`is_scaled_out`·`peak_price` 등). 매도는 주문과 동시에
    포지션이 원장에서 지워지므로(Task 6), 미체결·부분체결로 되돌릴 때 원래
    보유일수·분할매도 여부를 알 방법이 이것뿐이다 — 넘기지 않으면
    `_correct_sell`이 빈 값/기본값으로 복원한다.
    """
    pend = ledger.setdefault('pending_orders', {})
    if code in pend:
        if log_error:
            log_error(f'[Program] pending 등록 거부 — {code}는 이미 pending 중'
                      f'(odno={pend[code].get("odno")}). 이번 {side} 주문'
                      f'(odno={odno})은 정산 대상에서 빠집니다.')
        return
    pend[code] = {
        'odno': odno, 'side': side, 'qty': int(qty), 'price': float(price),
        'ordered_at': ordered_at, 'avg_price': avg_price, 'tag': tag,
        'snapshot': snapshot or {}, 'applied_qty': 0,
    }


def reconcile_pending(ledger, lookups, today, on_fill=None):
    """조회 결과로 pending을 정산한다. 반환은 취소해야 할 주문 목록.

    `lookups`에 없는 주문번호는 UNKNOWN으로 본다 — 조회하지 못한 것을
    미체결로 단정하면 팔린 포지션이 되살아난다.

    KIS 체결조회는 **누적** 체결수량을 돌려준다. 취소가 실패해 같은 pending이
    다음 사이클에도 살아남으면(호출부가 복원), 같은 조회가 같은 누적값을 또
    돌려줄 수 있다 — 그걸 매번 전량 반영하면 부분체결이 사이클마다 중복으로
    쌓인다(2주 체결인데 원장엔 4주, 6주...). `applied_qty`(이번까지 이미
    반영한 누적량)를 pending 항목에 들고 다니며, 이번 조회 - 이미 반영분
    만큼만 새로 반영한다. 복원하는 쪽(settle_pending_orders)이 반환된
    `applied_qty`를 pending에 이어 붙여야 이 불변식이 유지된다.

    `on_fill(code, qty, price, entry)`: 매수 체결이 **새로** 반영될 때 부른다.
    이 모듈은 I/O를 하지 않으므로, 실거래 이력에 남기는 일은 호출부가 맡는다.
    주문 접수와 체결을 같은 줄로 적으면 미체결이 체결처럼 보인다(2026-08-12:
    001210이 7번 주문 0체결인데 이력엔 매수 7건).
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
            already_applied = int(p.get('applied_qty', 0))
            new_fill = filled_qty - already_applied
            if new_fill > 0:
                _enter_position(positions, code, p, new_fill, fill_px, today)
                if on_fill:
                    # 실측 체결가·수량으로 남긴다. 주문가가 아니다.
                    on_fill(code, new_fill, fill_px, p)
            if filled_qty < ordered_qty:
                # UNFILLED 응답은 filled_qty=0으로 온다 — 이전 사이클에서 이미
                # 부분체결분을 반영했어도(already_applied) 그대로 0을 넘기면,
                # 복원된 pending의 applied_qty가 0으로 리셋된다. 다음 사이클에
                # 같은 누적 체결이 다시 FILLED로 돌아오면 그 몫이 또 반영된다
                # (예: 2주 체결 → UNFILLED 한 번 낌 → 같은 2주 FILLED → 4주로 오적용).
                cancels.append({'odno': p['odno'], 'code': code,
                                'qty': ordered_qty - filled_qty,
                                'applied_qty': max(filled_qty, already_applied)})
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


def apply_confirmed_sell(ledger, positions, code, entry, filled_qty, realized):
    """조회로 **확정된** 매도를 원장에 반영한다 — 추정치를 갈아끼운다.

    `_correct_sell`과 같은 일을 하되, 실현손익을 체결가로 다시 계산하지 않고
    KIS가 확정한 금액(TTTC8715R)을 그대로 쓴다. 체결가 재계산은 수수료·세금
    처리가 증권사와 미세하게 어긋날 수 있고, 그 차이가 `effective_budget`을
    통해 다음 주문 크기에 들어간다.

    `filled_qty=0, realized=0.0`이면 "그 매도는 체결되지 않았다"가 되어
    추정치를 통째로 되돌리고 포지션을 복원한다.
    """
    _correct_sell(ledger, positions, code, entry, filled_qty, 0.0,
                  realized_override=realized)


def _correct_sell(ledger, positions, code, p, filled_qty, fill_px,
                  realized_override=None):
    """주문 시 추정으로 더한 값을 실측으로 갈아끼우고, 안 팔린 수량을 되돌린다.

    주문 시 `E = est(ordered_qty, 주문가)`를 더해 뒀으므로, 진실
    `A = actual(filled_qty, 체결가)`에 대해 보정은 `A - E` 하나로 떨어진다.

    `realized_override`: 체결가로 재계산하는 대신 쓸 확정 실현손익(원).
    KIS 기간별매매손익이 확정한 값을 그대로 반영할 때 쓴다.
    """
    avg = float(p.get('avg_price') or 0)
    estimated = realized_pnl_after_fees(p['qty'], avg, p['price']) if avg else 0.0
    if realized_override is not None:
        actual = float(realized_override)
    else:
        actual = realized_pnl_after_fees(filled_qty, avg, fill_px) if (avg and filled_qty) else 0.0
    correction = actual - estimated
    # 반올림하지 않는다 — 여기서 반올림하면 realized_pnl(before) + correction이
    # actual과 정확히 상쇄되지 않는다. 주문 시 더한 estimated와 지금 빼는
    # estimated가 부동소수점으로 정확히 같은 값이어야 텔레스코핑이 성립한다.
    ledger['realized_pnl'] = ledger.get('realized_pnl', 0) + correction

    # 손익과 같은 텔레스코핑. 주문 시 더한 추정 비용을 실측으로 갈아끼운다.
    # realized_override(KIS 확정) 경로는 KIS가 비용을 분해해 주지 않으므로
    # 우리 모델 값으로 남는다 — 그 괴리는 체결 대사가 잡는다.
    est_fee = roundtrip_cost(p['qty'], avg, p['price']) if avg else 0.0
    act_fee = roundtrip_cost(filled_qty, avg, fill_px or p['price']) if (avg and filled_qty) else 0.0
    turn = ledger.get('turn')
    if turn is not None:
        turn['fees_realized'] = turn.get('fees_realized', 0.0) + (act_fee - est_fee)

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
