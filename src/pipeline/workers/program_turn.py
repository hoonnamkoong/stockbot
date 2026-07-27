"""프로그램 매매 턴 회계 (표시 전용, 순수 함수)
=======================================================
턴 = 프로그램 매매를 켠 시점부터 끈 시점까지.

기존 원장의 realized_pnl은 평단(avg_price) 기준으로 누적되며 effective_budget(복리)의
근거다 — 여기에는 절대 손대지 않는다. 턴 회계는 그와 분리된 별도 트랙으로, 기준가(basis)
기준으로 집계한다. 기준가는 턴 시작 시점에 **매입 평단**으로 seed된다(ON 시점 시세로
리셋하지 않는다). 전략 스위칭 시점에는 직전 태그 구간을 락인하며 기준가를 그 순간 시세로
리셋한다 — 하지만 seed가 평단이므로 구간 손익의 합은 평단 기준으로 telescoping된다.

이렇게 하면 ON 전부터 보유한 종목도 원래 매입가부터 손익이 계산되어, 턴 손익이 KIS
종목별 ROI와 정합한다. (이전 턴이 만든 미실현이 실현되는 턴에 온전히 귀속되므로, 구
MTM-리셋 설계가 지키던 '턴별 손익 합 = 누적 실현손익' 불변식은 더 이상 성립하지 않는다.)

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
    """새 턴을 연다. 물려받은 보유 종목의 기준가를 **매입 평단(avg_price)**으로 잡는다.

    ON 시점 시세로 리셋(MTM)하지 않는다 — ON 전부터 보유한 종목도 원래 매입가부터 손익을
    재야 KIS 종목별 ROI와 턴 손익이 정합하기 때문이다. opening_basis/current_prices는 구
    스냅샷-리셋 방식의 잔재로, 호출부 호환을 위해 시그니처만 남기고 의도적으로 무시한다.
    """
    basis = {code: float(p.get('avg_price', 0)) for code, p in positions.items()}
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
