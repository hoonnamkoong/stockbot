"""
프로그램 매매 엔진 (실전 계좌 자동 심 운용)
=======================================================
config(비공개 stockbot-secret/program_trading.json)가 ON이고 유효할 때, 선택된 심을
'실계좌 상태'로 실행해 매매 결정을 실제 주문으로 집행한다.

안전 원칙 (실계좌·실제 돈):
- fail-closed: config/원장 조회 실패, OFF, 무효 sim, budget<=0, 주말·장외 → 아무것도 안 함.
  원장은 중복매수 방지·예산 추적·손절 대상 식별·중복실행 가드의 유일한 근거이므로
  유실/조회실패 상태로는 절대 진행하지 않는다.
- config·원장 모두 실행 시점 GitHub(secret repo)에서 직접 읽고 쓴다. 워크플로우의
  clone(fetch)/deploy(push) 라운드트립에 의존하지 않는다 — 어느 한쪽만 실패해도
  다음 실행이 백지 원장으로 중복 매수하던 사고(진흥기업 5연속 매수)의 근본 차단.
- selected_sim은 tradeable 화이트리스트(active && tradeable)만 허용 → 임의 코드 실행 차단.
- 심의 실제 가상 상태 파일은 절대 건드리지 않는다(save_state/log_trade no-op).
- 매도는 프로그램 원장(program_positions.json) 종목만 → 수동 보유분 미매도.
- 매수 이중 방어: 실계좌에 이미 있는데 원장에 없는 종목은 매수 거부
  (수동 보유 물타기 방지 + 원장이 어떤 이유로든 유실돼도 중복 매수 불가).
- 심 선택 = 해당 심과 동일 동작:
  (1) 심 전용 유니버스(get_universe)를 페이퍼 경로(_run_simulators)와 동일하게 적용,
  (2) 사이징을 effective_budget 기준으로 스케일(비례 축소 복제본),
  (3) partial_sold 등 전략 플래그·손절 쿨다운을 원장에 영속화,
  (4) market_index_healthy 게이트를 가상 심 상태에서 승계.
- 매수는 effective_budget(=budget + 누적실현손익) − 프로그램 기투자액 내(스냅샷 cash로 강제).
  실현손익이 원장에 누적되어 자동 복리 — 수익은 다음 실행부터 굴리고, 손실도 그만큼 반영.
- 중복 실행 가드(원장 last_run).

이 파일은 파이프라인(GitHub Actions)에서 trade_engine.run() 종료부에 호출된다.
"""

import os
import json
import base64
import requests
from datetime import datetime, timedelta

# config·원장 모두 비공개 레포에 있다. config는 프론트가 유일 writer(파이프라인은 읽기만),
# 원장은 이 모듈이 유일 writer.
_SECRET_OWNER = 'hoonnamkoong'
_SECRET_REPO = 'stockbot-secret'
_SECRET_BRANCH = 'main'
_CONFIG_PATH = 'program_trading.json'
_LEDGER_PATH = 'program_positions.json'

_DUP_GUARD_MIN = 15  # 최근 N분 내 재실행 skip (중복 디스패치 방지)


def _gh_token() -> str | None:
    return os.environ.get('GH_PAT') or os.environ.get('GITHUB_PAT') or os.environ.get('GITHUB_TOKEN')


def _gh_headers(token: str) -> dict:
    return {'Authorization': f'token {token}', 'Accept': 'application/vnd.github.v3+json'}


def _read_config_fresh(log=print) -> dict | None:
    """실행 시점에 GitHub(secret repo)에서 config를 직접 조회. 실패/없음 → None(=OFF, fail-closed)."""
    token = _gh_token()
    if not token:
        log('[Program] GH 토큰 없음 → config 조회 불가, OFF 취급')
        return None
    url = f'https://api.github.com/repos/{_SECRET_OWNER}/{_SECRET_REPO}/contents/{_CONFIG_PATH}?ref={_SECRET_BRANCH}'
    try:
        res = requests.get(url, headers=_gh_headers(token), timeout=10)
        if res.status_code == 404:
            return None  # config 미설정 → OFF
        if res.status_code != 200:
            log(f'[Program] config 조회 실패 HTTP {res.status_code} → OFF 취급')
            return None
        content = base64.b64decode(res.json()['content']).decode('utf-8')
        return json.loads(content)
    except Exception as e:
        log(f'[Program] config 조회 예외: {e} → OFF 취급')
        return None


def _default_ledger() -> dict:
    return {'positions': {}, 'last_run': None, 'sim': None, 'realized_pnl': 0, 'cooldown_codes': {}}


def _read_ledger_fresh(log=print) -> tuple[dict | None, str | None]:
    """원장을 GitHub(secret repo)에서 직접 조회.

    반환: (원장 dict, sha).
    - 404(최초 실행, 원장 미생성) → (기본 원장, None) — 부트스트랩 허용.
    - 그 외 실패(토큰/네트워크/파싱) → (None, None) — 호출부는 실행 전체를 skip해야 한다
      (fail-closed). 원장 없이 진행하면 중복매수·예산초과·중복실행 가드가 전부 무력화된다.
    """
    token = _gh_token()
    if not token:
        log('[Program] GH 토큰 없음 → 원장 조회 불가 (fail-closed)')
        return None, None
    url = f'https://api.github.com/repos/{_SECRET_OWNER}/{_SECRET_REPO}/contents/{_LEDGER_PATH}?ref={_SECRET_BRANCH}'
    try:
        res = requests.get(url, headers=_gh_headers(token), timeout=10)
        if res.status_code == 404:
            return _default_ledger(), None
        if res.status_code != 200:
            log(f'[Program] 원장 조회 실패 HTTP {res.status_code} (fail-closed)')
            return None, None
        payload = res.json()
        d = json.loads(base64.b64decode(payload['content']).decode('utf-8'))
        d.setdefault('positions', {})
        d.setdefault('realized_pnl', 0)
        d.setdefault('cooldown_codes', {})
        return d, payload.get('sha')
    except Exception as e:
        log(f'[Program] 원장 조회 예외: {e} (fail-closed)')
        return None, None


def _write_ledger(ledger: dict, sha: str | None, log=print) -> bool:
    """원장을 GitHub(secret repo)에 직접 기록. sha 충돌(409/422) 시 fresh sha로 1회 재시도.

    기록 실패는 예외를 올리지 않는다 — 다음 실행에서 매수 시 실잔고 이중 방어가
    중복 매수를 차단하고, 매도된 포지션은 원장∩실보유 교집합에서 자연 제거된다.
    """
    token = _gh_token()
    if not token:
        log('[Program] GH 토큰 없음 → 원장 기록 불가')
        return False
    url = f'https://api.github.com/repos/{_SECRET_OWNER}/{_SECRET_REPO}/contents/{_LEDGER_PATH}'
    body = {
        'message': f"program ledger {ledger.get('last_run') or ''}".strip(),
        'content': base64.b64encode(
            json.dumps(ledger, indent=2, ensure_ascii=False).encode('utf-8')).decode('ascii'),
        'branch': _SECRET_BRANCH,
    }
    if sha:
        body['sha'] = sha
    try:
        res = requests.put(url, headers=_gh_headers(token), json=body, timeout=10)
        if res.status_code in (409, 422):
            cur = requests.get(f'{url}?ref={_SECRET_BRANCH}', headers=_gh_headers(token), timeout=10)
            if cur.status_code == 200:
                body['sha'] = cur.json().get('sha')
                res = requests.put(url, headers=_gh_headers(token), json=body, timeout=10)
        if res.status_code not in (200, 201):
            log(f'[Program] 원장 기록 실패 HTTP {res.status_code}')
            return False
        return True
    except Exception as e:
        log(f'[Program] 원장 기록 예외: {e}')
        return False


def _recently_ran(ledger: dict, now_kst: datetime) -> bool:
    last = ledger.get('last_run')
    if not last:
        return False
    try:
        prev = datetime.fromisoformat(last)
        return (now_kst - prev) < timedelta(minutes=_DUP_GUARD_MIN)
    except Exception:
        return False


def _make_adapter(sim, snapshot_state: dict, today: str, real_holdings: dict | None = None):
    """심 인스턴스를 실계좌 스냅샷으로 운용하도록 개조하고, 의도 주문을 수집한다.
    - state를 스냅샷으로 교체, save_state/log_trade는 no-op(실제 가상 상태 파일 보호).
    - buy/sell을 오버라이드: 주문 의도를 기록 + 스냅샷을 갱신(같은 run 내 일관성).
    - 매수 이중 방어: 실계좌에 있는데 스냅샷 포트폴리오(=원장)에 없는 종목은 거부."""
    sim.state = snapshot_state
    sim.save_state = lambda *a, **k: None
    sim.log_trade = lambda *a, **k: None
    real_holdings = real_holdings or {}
    orders: list[dict] = []

    def _buy(code, name, price, quantity, reason=""):
        try:
            price = float(price); quantity = int(quantity)
        except (TypeError, ValueError):
            return False
        if quantity <= 0 or price <= 0:
            return False
        if code in real_holdings and code not in snapshot_state['portfolio']:
            # 실계좌 보유 중인데 프로그램 원장엔 없음 → 수동 보유 종목이거나 원장 유실.
            # 어느 쪽이든 매수하면 안 된다(물타기/중복매수 이중 방어).
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


def _resolve_candidates(sim, candidates: list[dict], enrich, log=print, log_error=print) -> list[dict]:
    """심 전용 유니버스를 적용한 최종 후보를 반환.

    페이퍼 경로(trade_engine._run_simulators)와 동일 의미론:
    get_universe()가 truthy면 enrich해서 교체, 없거나 실패하면 파이프라인 candidates 유지.
    """
    try:
        own_universe = sim.get_universe()
    except Exception as e:
        log_error(f'[Program] get_universe 예외: {e} — 파이프라인 후보 사용')
        own_universe = None
    if not own_universe:
        return candidates
    if enrich:
        try:
            enriched = enrich(own_universe)
            if enriched:
                log(f'[Program] 심 전용 유니버스 적용: {len(enriched)}종목')
                return enriched
        except Exception as e:
            log_error(f'[Program] 유니버스 보강 실패: {e} — 원본 유니버스 사용')
    log(f'[Program] 심 전용 유니버스 적용(미보강): {len(own_universe)}종목')
    return own_universe


def _merge_strategy_flags(positions: dict, snapshot_portfolio: dict, failed_codes: set) -> None:
    """심이 run 중 스냅샷 포지션에 기록한 전략 플래그(partial_sold, partial_sold_date,
    peak_price 등)를 원장에 머지한다. 수량/평단은 체결 기준(_apply_order_to_positions)이
    진실이므로 덮어쓰지 않는다. 주문이 거부/실패한 종목은 의도-체결 불일치 상태이므로
    플래그를 머지하지 않는다(다음 실행에서 심이 같은 판단을 다시 내리면 됨)."""
    for code, p in positions.items():
        snap_p = snapshot_portfolio.get(code)
        if not snap_p or code in failed_codes:
            continue
        for k, v in snap_p.items():
            if k not in ('quantity', 'avg_price'):
                p[k] = v


def run_program_trading(candidates: list[dict], is_market_hours: bool, now_kst: datetime,
                        log=print, log_error=print, enrich=None) -> None:
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

    # 3. 원장 fresh 조회 (fail-closed) + 중복 실행 가드
    ledger, ledger_sha = _read_ledger_fresh(log)
    if ledger is None:
        log_error('[Program] 원장 조회 실패 — skip (fail-closed: 원장 없이 진행 금지)')
        return
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

    # [복리 반영] 프로그램 자체 실현손익(realized_pnl, 원장 누적)을 설정 budget에 더해
    # '이번 실행에서 실제 쓸 수 있는 예산(effective_budget)'을 만든다. 수익이 나면 다음
    # 실행부터 그 수익까지 포함해 굴리고(복리), 손실이 나면 그만큼 줄어든다(사용자 확정 설계).
    realized_pnl = ledger.get('realized_pnl', 0)
    effective_budget = budget + realized_pnl
    if realized_pnl:
        log(f"[Program] budget({budget:,}) + 누적실현손익({realized_pnl:+,.0f}) = "
            f"effective_budget({effective_budget:,.0f})")

    # [보안/안전 교정] effective_budget이 잘못 커지거나(계산 drift) 사용자가 계좌에서
    # 다른 용도로 현금을 소진한 경우 실제 살 수 없는 주문을 낼 위험이 있다.
    # 증권사 거부에만 기대지 않고, 여기서 실제 예수금으로 상한을 강제한다.
    real_deposit = int(bal.get('deposit') or 0)
    real_invested = sum(h['avg_price'] * h['qty'] for h in real_holdings.values())
    real_account_value = real_deposit + real_invested
    if effective_budget > real_account_value:
        log(f"[Program] effective_budget({effective_budget:,.0f})이 실제 계좌가치"
            f"({real_account_value:,.0f})를 초과 — 클램프")
        effective_budget = real_account_value
    if effective_budget <= 0:
        log('[Program] 클램프 후 effective_budget<=0 — skip')
        return

    # 5. 원장 ↔ 실보유 정합: 프로그램 포지션이 실제로 남아있는 것만 유지(수동 매도분 제거).
    #    dict 전체 복사 — 심이 붙인 전략 플래그(partial_sold 등)를 그대로 보존.
    today = now_kst.strftime('%Y-%m-%d')
    positions = {c: dict(p) for c, p in ledger.get('positions', {}).items() if c in real_holdings}

    # 6. 심 인스턴스화(화이트리스트). 사이징을 effective_budget 기준으로 스케일
    #    → 시뮬(initial_cash/N 사이징)의 비례 축소 복제본으로 동작.
    sim = get_simulator_by_id(sim_id, initial_cash=int(effective_budget))
    if sim is None:
        log(f"[Program] 심 인스턴스 생성 실패: {sim_id} — skip")
        return

    # market_index_healthy 게이트는 가상 심 상태(리베로가 기록)에서 승계 — 페이퍼와 동일 동작.
    market_index_healthy = True
    if isinstance(getattr(sim, 'state', None), dict):
        market_index_healthy = bool(sim.state.get('market_index_healthy', True))

    # 7. 심 전용 유니버스 적용 (페이퍼 경로 _run_simulators와 동일 의미론)
    sim_candidates = _resolve_candidates(sim, candidates, enrich, log, log_error)

    # 현재가 맵: 최종 후보 + 프로그램 보유 종목
    current_prices = {}
    for s in sim_candidates:
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

    # 8. 실계좌 스냅샷 state 구성 (cash = effective_budget − 프로그램 기투자 원가)
    invested_cost = sum(p['avg_price'] * p['quantity'] for p in positions.values())
    snapshot_portfolio = {c: dict(p) for c, p in positions.items()}
    for c, p in snapshot_portfolio.items():
        p.setdefault('name', c)
        p.setdefault('peak_price', p.get('avg_price', 0))
        p.setdefault('entry_date', today)
        p.setdefault('is_scaled_out', False)
    snapshot = {
        'cash': max(0.0, effective_budget - invested_cost),
        'invested': invested_cost,
        'portfolio': snapshot_portfolio,
        'total_fees': 0, 'history': [effective_budget], 'daily_trades': [], 'peak_nav': effective_budget,
        'market_index_healthy': market_index_healthy,
        'cooldown_codes': dict(ledger.get('cooldown_codes', {})),  # 손절 쿨다운 영속화
    }

    # 9. 어댑터(실잔고 이중 방어 포함) + 실행
    orders = _make_adapter(sim, snapshot, today, real_holdings)
    try:
        sim.run(sim_candidates, current_prices=current_prices)
    except Exception as e:
        log_error(f'[Program] 심 실행 예외: {e} — 주문 없이 종료')
        return

    if not orders:
        log(f'[Program] {sim_id}: 주문 없음')
        ledger['positions'] = positions
        ledger['cooldown_codes'] = snapshot.get('cooldown_codes', {})
        ledger['last_run'] = now_kst.isoformat()
        ledger['sim'] = sim_id
        _write_ledger(ledger, ledger_sha, log)
        return

    # 10. 안전 필터 + 집행
    from src.trade_executor import place_order_via_vercel, append_order_history
    executed = 0
    failed_codes: set = set()
    for i, o in enumerate(orders):
        # 주문 직전 kill-switch 재확인 (실행 중 OFF/심 변경 감지)
        cfg2 = _read_config_fresh(log)
        if not cfg2 or not cfg2.get('enabled') or cfg2.get('selected_sim') != sim_id:
            log('[Program] 실행 중 OFF/변경 감지 — 신규 주문 중단(kill-switch)')
            failed_codes.update(x['code'] for x in orders[i:])  # 미집행 주문은 의도-체결 불일치
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
                # [복리] 매도 체결분의 실현손익을 원장에 누적(다음 실행의 effective_budget에 반영).
                # _apply_order_to_positions가 positions[code]를 지우거나 수량을 줄이기 전에 계산해야 함.
                # price는 KIS 확정 체결가가 아닌 주문가 추정치 — 원장의 avg_price/peak_price와 동일한
                # 근사 정밀도(기존 설계와 일관).
                if side == 'sell' and code in positions:
                    realized_delta = qty * (price - positions[code]['avg_price'])
                    ledger['realized_pnl'] = round(ledger.get('realized_pnl', 0) + realized_delta, 2)
                _apply_order_to_positions(positions, o, today)
                append_order_history({
                    'executed_at': now_kst.isoformat(), 'side': side, 'code': code,
                    'name': o.get('name', ''), 'qty': qty, 'price': price,
                    'status': 'executed', 'reason': f"[프로그램:{sim_id}] {o.get('reason', '')}",
                })
                executed += 1
                log(f"[Program] 체결: {side.upper()} {code} {qty}주 @ {price}")
            else:
                failed_codes.add(code)
                log(f"[Program] 주문 거부 {code}: {res.get('error')}")
        except Exception as e:
            failed_codes.add(code)
            log_error(f'[Program] 주문 집행 실패 {code}: {e}')

    # 11. 전략 플래그 머지(체결 성공 종목만) + 원장 저장
    _merge_strategy_flags(positions, snapshot['portfolio'], failed_codes)
    ledger['positions'] = positions
    ledger['cooldown_codes'] = snapshot.get('cooldown_codes', {})
    ledger['last_run'] = now_kst.isoformat()
    ledger['sim'] = sim_id
    _write_ledger(ledger, ledger_sha, log)
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
