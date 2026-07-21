"""프로그램 매매 턴 회계 (표시 전용, 순수 함수)
=======================================================
턴 = 프로그램 매매를 켠 시점부터 끈 시점까지.

기존 원장의 realized_pnl은 평단(avg_price) 기준으로 누적되며 effective_budget(복리)의
근거다 — 여기에는 절대 손대지 않는다. 턴 회계는 그와 분리된 별도 트랙으로, 기준가(basis)
기준으로 집계한다. 기준가는 턴 시작·전략 스위칭 시점에 그 순간 시세로 리셋된다(MTM).

이렇게 하면 이전 턴이 만든 미실현 이익이 새 턴 성과로 둔갑하지 않고, 턴별 손익의 합은
평단 기준 누적 실현손익과 정확히 일치한다.

이 모듈은 I/O를 하지 않는다. 원장 dict을 받아 제자리에서 갱신할 뿐이다.
"""

# Sim10의 국면 → 하위 전략 태그 (manifest의 실제 심 id)
REGIME_TAG = {
    'BULL': 'sim4_bull_daytrading',
    'SIDEWAYS': 'sim5_sideways',
    'BEAR': 'sim6',
}


def new_turn(turn_id: str, capital: float, positions: dict,
             opening_basis: dict | None = None, current_prices: dict | None = None) -> dict:
    """새 턴을 연다. 물려받은 보유 종목의 기준가를 턴 시작 시세로 재설정한다(MTM).

    기준가 우선순위: opening_basis(프론트가 ON 시점에 찍은 스냅샷) > current_prices > 평단.
    """
    opening_basis = opening_basis or {}
    current_prices = current_prices or {}
    basis = {}
    for code, p in positions.items():
        px = opening_basis.get(code) or current_prices.get(code) or p.get('avg_price', 0)
        basis[code] = float(px)
    return {'id': turn_id, 'capital': float(capital), 'basis': basis,
            'by_tag': {}, 'active_tag': None}


def switch_tag(turn: dict, positions: dict, new_tag: str, current_prices: dict) -> None:
    """활성 전략을 전환한다. 직전 태그가 자기 구간의 평가손익을 확정 귀속받고, 기준가가 리셋된다.

    턴 첫 실행(active_tag=None)은 락인할 직전 태그가 없으므로 기준가를 그대로 둔다 —
    ON 시점부터 첫 실행까지의 변동은 첫 태그의 몫이다.
    """
    old = turn.get('active_tag')
    if old == new_tag:
        return
    basis = turn.setdefault('basis', {})
    by_tag = turn.setdefault('by_tag', {})
    for code, p in positions.items():
        if old is None:
            p['tag'] = new_tag           # 기준가는 new_turn이 잡은 ON 시점 값 유지
            continue
        px = float(current_prices.get(code) or 0)
        if px <= 0:
            continue                     # 시세 없음 → 락인 불가. 이 종목은 직전 태그·기준가 유지.
        b = float(basis.get(code, px))
        by_tag[old] = round(by_tag.get(old, 0.0) + (px - b) * p['quantity'], 2)
        basis[code] = px
        p['tag'] = new_tag
    turn['active_tag'] = new_tag


def record_buy(turn: dict, code: str, qty: int, price: float, prev_qty: int) -> None:
    """매수 체결 반영. 추가 매수 시 기준가는 평단처럼 가중평균된다.

    prev_qty는 체결 반영 '이전'의 보유 수량이다(호출부가 _apply_order_to_positions 전에 캡처).
    """
    basis = turn.setdefault('basis', {})
    price = float(price)
    if prev_qty > 0 and code in basis:
        basis[code] = (basis[code] * prev_qty + price * qty) / (prev_qty + qty)
    else:
        basis[code] = price


def record_sell(turn: dict, positions: dict, code: str, qty: int, price: float) -> None:
    """매도 체결 반영. 평단이 아니라 '기준가' 대비 손익을 그 종목을 들고 있던 태그에 귀속한다.

    활성 태그가 아니라 positions[code]['tag']를 쓰는 이유: switch_tag는 시세를 못 구한 종목을
    의도적으로 직전 태그·기준가에 남겨둔다. 그런 종목의 매도를 활성 태그에 귀속하면 기준가는
    옛것인데 손익은 새 태그가 가져가 SIM별 분해가 엇갈린다. 표시 계산(TS computeTurnPnl)도
    미실현을 pos.tag에 귀속하므로 양쪽 기준을 일치시킨다.
    """
    basis = turn.get('basis', {})
    if code not in basis:
        return
    tag = (positions.get(code) or {}).get('tag') or turn.get('active_tag')
    if not tag:
        return
    by_tag = turn.setdefault('by_tag', {})
    by_tag[tag] = round(by_tag.get(tag, 0.0) + (float(price) - basis[code]) * qty, 2)


def prune_basis(turn: dict, positions: dict) -> None:
    """전량 매도된 종목의 기준가를 정리한다(손익은 record_sell이 이미 귀속시켰다)."""
    basis = turn.get('basis', {})
    for code in list(basis):
        if code not in positions:
            basis.pop(code, None)
