"""
프로그램 매매 엔진 (실전 계좌 자동 심 운용)
=======================================================
config(비공개 stockbot-secret/program_trading.json)가 ON이고 유효할 때, 선택된 심을
'실계좌 상태'로 실행해 매매 결정을 실제 주문으로 집행한다.

안전 원칙 (실계좌·실제 돈):
- fail-closed: config 없음/파싱실패/OFF/무효 sim/budget<=0/주말·장외 → 아무것도 안 함.
- config는 실행 시점 GitHub에서 fresh 재조회(체크아웃 사본 아님) + 주문 직전 재확인(kill-switch).
- selected_sim은 tradeable 화이트리스트(active && tradeable)만 허용 → 임의 코드 실행 차단.
- 심의 실제 가상 상태 파일은 절대 건드리지 않는다(save_state/log_trade no-op).
- 매도는 프로그램 원장(program_positions.json) 종목만 → 수동 보유분 미매도.
- 매수는 budget − 프로그램 기투자액 내(스냅샷 cash로 강제).
- 중복 실행 가드(원장 last_run).

이 파일은 파이프라인(GitHub Actions)에서 trade_engine.run() 종료부에 호출된다.
"""

import os
import json
import requests
from datetime import datetime, timedelta

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
_LEDGER_FILE = os.path.join(_REPO_ROOT, 'data', 'program_positions.json')

# config는 비공개 레포에 있고 프론트가 유일 writer. 파이프라인은 읽기만.
_SECRET_OWNER = 'hoonnamkoong'
_SECRET_REPO = 'stockbot-secret'
_SECRET_BRANCH = 'main'
_CONFIG_PATH = 'program_trading.json'

_DUP_GUARD_MIN = 15  # 최근 N분 내 재실행 skip (중복 디스패치 방지)


def _gh_token() -> str | None:
    return os.environ.get('GH_PAT') or os.environ.get('GITHUB_PAT') or os.environ.get('GITHUB_TOKEN')


def _read_config_fresh(log=print) -> dict | None:
    """실행 시점에 GitHub(secret repo)에서 config를 직접 조회. 실패/없음 → None(=OFF, fail-closed)."""
    token = _gh_token()
    if not token:
        log('[Program] GH 토큰 없음 → config 조회 불가, OFF 취급')
        return None
    url = f'https://api.github.com/repos/{_SECRET_OWNER}/{_SECRET_REPO}/contents/{_CONFIG_PATH}?ref={_SECRET_BRANCH}'
    try:
        res = requests.get(url, headers={'Authorization': f'token {token}',
                                         'Accept': 'application/vnd.github.v3+json'}, timeout=10)
        if res.status_code == 404:
            return None  # config 미설정 → OFF
        if res.status_code != 200:
            log(f'[Program] config 조회 실패 HTTP {res.status_code} → OFF 취급')
            return None
        import base64
        content = base64.b64decode(res.json()['content']).decode('utf-8')
        return json.loads(content)
    except Exception as e:
        log(f'[Program] config 조회 예외: {e} → OFF 취급')
        return None


def _read_ledger() -> dict:
    if not os.path.exists(_LEDGER_FILE):
        return {'positions': {}, 'last_run': None, 'sim': None}
    try:
        with open(_LEDGER_FILE, 'r', encoding='utf-8') as f:
            d = json.load(f)
        d.setdefault('positions', {})
        return d
    except Exception:
        return {'positions': {}, 'last_run': None, 'sim': None}


def _write_ledger(ledger: dict) -> None:
    os.makedirs(os.path.dirname(_LEDGER_FILE), exist_ok=True)
    with open(_LEDGER_FILE, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, indent=2, ensure_ascii=False)


def _recently_ran(ledger: dict, now_kst: datetime) -> bool:
    last = ledger.get('last_run')
    if not last:
        return False
    try:
        prev = datetime.fromisoformat(last)
        return (now_kst - prev) < timedelta(minutes=_DUP_GUARD_MIN)
    except Exception:
        return False


def _make_adapter(sim, snapshot_state: dict, today: str):
    """심 인스턴스를 실계좌 스냅샷으로 운용하도록 개조하고, 의도 주문을 수집한다.
    - state를 스냅샷으로 교체, save_state/log_trade는 no-op(실제 가상 상태 파일 보호).
    - buy/sell을 오버라이드: 주문 의도를 기록 + 스냅샷을 갱신(같은 run 내 일관성)."""
    sim.state = snapshot_state
    sim.save_state = lambda *a, **k: None
    sim.log_trade = lambda *a, **k: None
    orders: list[dict] = []

    def _buy(code, name, price, quantity, reason=""):
        try:
            price = float(price); quantity = int(quantity)
        except (TypeError, ValueError):
            return False
        if quantity <= 0 or price <= 0:
            return False
        cost = quantity * price
        if snapshot_state['cash'] < cost:
            return False  # budget 초과 → 심 스스로 매수 안 함
        orders.append({'side': 'buy', 'code': code, 'name': name, 'price': price, 'qty': quantity, 'reason': reason})
        snapshot_state['cash'] -= cost
        pf = snapshot_state['portfolio']
        if code in pf:
            o = pf[code]; oq = o['quantity']; op = o.get('avg_price', price); nq = oq + quantity
            o['quantity'] = nq
            o['avg_price'] = ((oq * op) + cost) / nq
        else:
            pf[code] = {'name': name, 'quantity': quantity, 'avg_price': price,
                        'peak_price': price, 'entry_date': today, 'is_scaled_out': False}
        return True

    def _sell(code, price, quantity=None, reason=""):
        pf = snapshot_state['portfolio']
        if code not in pf:
            return False  # 프로그램 미소유 → 매도 불가(수동 보유분 보호)
        try:
            price = float(price)
        except (TypeError, ValueError):
            return False
        held = pf[code]['quantity']
        q = held if quantity is None else min(int(quantity), held)
        if q <= 0:
            return False
        orders.append({'side': 'sell', 'code': code, 'name': pf[code].get('name', code),
                       'price': price, 'qty': q, 'reason': reason})
        snapshot_state['cash'] += q * price
        if q >= held:
            del pf[code]
        else:
            pf[code]['quantity'] -= q
            pf[code]['is_scaled_out'] = True
        return True

    sim.buy = _buy
    sim.sell = _sell
    return orders


def run_program_trading(candidates: list[dict], is_market_hours: bool, now_kst: datetime,
                        log=print, log_error=print) -> None:
    """프로그램 매매 1회 실행. 모든 게이트 통과 시에만 실주문."""
    # 1. config fresh 조회 (fail-closed)
    cfg = _read_config_fresh(log)
    if not cfg or not cfg.get('enabled'):
        return
    sim_id = cfg.get('selected_sim')
    try:
        budget = int(cfg.get('budget') or 0)
    except (TypeError, ValueError):
        budget = 0

    # 2. 게이트 (fail-closed)
    if now_kst.weekday() >= 5 or not is_market_hours:
        log('[Program] 장 외 시간 — skip')
        return
    if budget <= 0:
        log('[Program] budget<=0 — skip')
        return
    from src.strategy.registry import get_tradeable_simulator_ids, get_simulator_by_id
    if sim_id not in get_tradeable_simulator_ids():
        log(f"[Program] selected_sim '{sim_id}' 무효(화이트리스트 밖) — skip (fail-safe OFF)")
        return

    # 3. 중복 실행 가드
    ledger = _read_ledger()
    if _recently_ran(ledger, now_kst):
        log('[Program] 최근 실행됨 — 중복 방지 skip')
        return

    # 4. 실계좌 잔고
    try:
        from src.trade.balance import get_balance
        bal = get_balance()
    except Exception as e:
        log_error(f'[Program] 잔고 조회 실패: {e} — skip')
        return
    if bal.get('error'):
        log_error(f"[Program] 잔고 오류: {bal.get('error')} — skip")
        return
    real_holdings = {h['code']: h for h in bal.get('holdings', []) if h.get('code')}

    # [보안/안전 교정] budget이 config 상 값만으로 정해지면, 잘못된 큰 budget이나 사용자가
    # 계좌에서 다른 용도로 현금을 소진한 경우 실제 살 수 없는 주문을 낼 위험이 있다.
    # 증권사 거부에만 기대지 않고, 여기서 실제 예수금으로 상한을 강제한다.
    real_deposit = int(bal.get('deposit') or 0)
    real_invested = sum(h['avg_price'] * h['qty'] for h in real_holdings.values())
    real_account_value = real_deposit + real_invested
    if budget > real_account_value:
        log(f"[Program] budget({budget:,})이 실제 계좌가치({real_account_value:,.0f})를 초과 — 클램프")
        budget = int(real_account_value)
    if budget <= 0:
        log('[Program] 클램프 후 budget<=0 — skip')
        return

    # 5. 원장 ↔ 실보유 정합: 프로그램 포지션이 실제로 남아있는 것만 유지(수동 매도분 제거)
    today = now_kst.strftime('%Y-%m-%d')
    positions = {c: dict(p) for c, p in ledger.get('positions', {}).items() if c in real_holdings}

    # 현재가 맵: 후보 + 프로그램 보유 종목
    current_prices = {}
    for s in candidates:
        code = s.get('code')
        px = s.get('price', s.get('current_price', 0))
        if code and px:
            current_prices[code] = float(px)
    for c, p in positions.items():
        cp = float(real_holdings[c].get('current_price') or 0)
        if cp > 0:
            current_prices.setdefault(c, cp)
            if cp > p.get('peak_price', 0):
                p['peak_price'] = cp  # 트레일링용 고점 갱신

    # 6. 실계좌 스냅샷 state 구성 (cash = budget − 프로그램 기투자 원가)
    invested_cost = sum(p['avg_price'] * p['quantity'] for p in positions.values())
    snapshot = {
        'cash': max(0.0, budget - invested_cost),
        'invested': invested_cost,
        'portfolio': {c: {'name': p.get('name', c), 'quantity': p['quantity'], 'avg_price': p['avg_price'],
                          'peak_price': p.get('peak_price', p['avg_price']),
                          'entry_date': p.get('entry_date', today),
                          'is_scaled_out': p.get('is_scaled_out', False)} for c, p in positions.items()},
        'total_fees': 0, 'history': [budget], 'daily_trades': [], 'peak_nav': budget,
    }

    # 7. 심 인스턴스화(화이트리스트) + 개조 + 실행
    sim = get_simulator_by_id(sim_id)
    if sim is None:
        log(f"[Program] 심 인스턴스 생성 실패: {sim_id} — skip")
        return
    orders = _make_adapter(sim, snapshot, today)
    try:
        sim.run(candidates, current_prices=current_prices)
    except Exception as e:
        log_error(f'[Program] 심 실행 예외: {e} — 주문 없이 종료')
        return

    if not orders:
        log(f'[Program] {sim_id}: 주문 없음')
        ledger['positions'] = positions
        ledger['last_run'] = now_kst.isoformat()
        ledger['sim'] = sim_id
        _write_ledger(ledger)
        return

    # 8. 안전 필터 + 집행
    from src.trade_executor import place_order_via_vercel, append_order_history
    executed = 0
    for o in orders:
        # 주문 직전 kill-switch 재확인 (실행 중 OFF/심 변경 감지)
        cfg2 = _read_config_fresh(log)
        if not cfg2 or not cfg2.get('enabled') or cfg2.get('selected_sim') != sim_id:
            log('[Program] 실행 중 OFF/변경 감지 — 신규 주문 중단(kill-switch)')
            break
        code = o['code']; side = o['side']; qty = int(o['qty'])
        price = int(o['price'] or current_prices.get(code, 0) or 0)
        if qty <= 0:
            continue
        # 매도는 프로그램 원장 종목만(이중 방어)
        if side == 'sell' and code not in positions:
            log(f'[Program] SKIP sell {code} — 프로그램 미소유')
            continue
        try:
            res = place_order_via_vercel(side, code, qty, price)
            if res.get('success'):
                _apply_order_to_positions(positions, o, today)
                append_order_history({
                    'executed_at': now_kst.isoformat(), 'side': side, 'code': code,
                    'name': o.get('name', ''), 'qty': qty, 'price': price,
                    'status': 'executed', 'reason': f"[프로그램:{sim_id}] {o.get('reason', '')}",
                })
                executed += 1
                log(f"[Program] 체결: {side.upper()} {code} {qty}주 @ {price}")
            else:
                log(f"[Program] 주문 거부 {code}: {res.get('error')}")
        except Exception as e:
            log_error(f'[Program] 주문 집행 실패 {code}: {e}')

    # 9. 원장 저장
    ledger['positions'] = positions
    ledger['last_run'] = now_kst.isoformat()
    ledger['sim'] = sim_id
    _write_ledger(ledger)
    log(f'[Program] 완료: {executed}/{len(orders)}건 체결 (sim={sim_id})')


def _apply_order_to_positions(positions: dict, o: dict, today: str) -> None:
    """체결된 주문을 프로그램 원장에 반영."""
    code = o['code']; qty = int(o['qty']); price = float(o['price'] or 0)
    if o['side'] == 'buy':
        if code in positions:
            p = positions[code]; oq = p['quantity']; op = p.get('avg_price', price); nq = oq + qty
            p['quantity'] = nq
            p['avg_price'] = ((oq * op) + qty * price) / nq if nq else price
            p['peak_price'] = max(p.get('peak_price', price), price)
        else:
            positions[code] = {'name': o.get('name', code), 'quantity': qty, 'avg_price': price,
                               'peak_price': price, 'entry_date': today, 'is_scaled_out': False}
    else:  # sell
        if code in positions:
            p = positions[code]
            p['quantity'] -= qty
            if p['quantity'] <= 0:
                del positions[code]
            else:
                p['is_scaled_out'] = True
