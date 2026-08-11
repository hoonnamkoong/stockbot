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
  (3) partial_sold 등 전략 플래그·손절 쿨다운을 원장에 영속화.
- 매수는 effective_budget(=budget + 누적실현손익) − 프로그램 기투자액 내(스냅샷 cash로 강제).
  실현손익이 원장에 누적되어 자동 복리 — 수익은 다음 실행부터 굴리고, 손실도 그만큼 반영.
- 중복 실행 가드(원장 last_run).

이 파일은 파이프라인(GitHub Actions)에서 trade_engine.run() 종료부에 호출된다.
"""

import os
import json
import time
import uuid
import base64
import requests
from datetime import datetime, timedelta

from src import alerts
from src.pipeline.context import MARKET_CLOSE_HHMM
from src.trade.fees import realized_pnl_after_fees
from src.trade.pending import register_pending
from src.pipeline.workers.program_turn import (
    REGIME_TAG, new_turn, switch_tag, record_sell, prune_basis,
)


def accrue_realized_pnl(ledger: dict, positions: dict, code: str,
                        qty: int, price: float) -> float:
    """매도 체결분의 실현손익을 원장에 누적한다. 반환은 이번에 더한 값.

    **비용을 뺀 값을 적는다.** 2026-08-10까지는 단순 차액이었고, 그래서 대덕전자
    1주 매도에서 원장 -3,500원 / KIS 실측 -3,723원으로 223원이 벌어졌다. 매도마다
    같은 방향으로 벌어지는 편향이라 매매가 잦을수록 커진다.

    realized_pnl은 표시용이 아니라 effective_budget(복리)의 근거다 — 부풀린 채로
    두면 다음 매수의 주문 크기까지 함께 부풀어 오른다.

    원장에 없는 종목은 기준가가 없으므로 아무것도 하지 않는다. 손익을 지어내는
    대신 계상하지 않는다([[no-fabricated-financial-values]]).
    """
    pos = positions.get(code)
    if not pos:
        return 0.0
    delta = realized_pnl_after_fees(qty, pos['avg_price'], price)
    ledger['realized_pnl'] = round(ledger.get('realized_pnl', 0) + delta, 2)
    return delta


def _buy_allowed(now_kst) -> bool:
    """신규 매수 허용 시각인가. 정규장 종료(15:30)부터 막는다.

    차단선을 `MARKET_CLOSE_HHMM` 하나에서 가져온다 — 심의 `allow_buy`
    (`ctx.is_buy_window()`)와 다른 시각을 쓰면 페이퍼 기록과 실전 동작이 갈린다.
    이유는 `PipelineContext.is_buy_window()` 주석에 있다.
    """
    return (now_kst.hour, now_kst.minute) < MARKET_CLOSE_HHMM


def _extract_odno(order_res: dict) -> str:
    """/api/trade/order 응답에서 KIS 주문번호를 꺼낸다(E10).

    'UNKNOWN'은 라우트가 ODNO를 못 받았을 때의 폴백값(order/route.ts) —
    나중에 TTTC8001R 체결 조회와 매칭하는 데 못 쓰므로 빈 문자열로 취급한다.
    """
    odno = ((order_res or {}).get('data') or {}).get('odno') or ''
    odno = odno.strip()
    return '' if odno == 'UNKNOWN' else odno

# config·원장 모두 비공개 레포에 있다. config는 프론트가 유일 writer(파이프라인은 읽기만),
# 원장은 이 모듈이 유일 writer.
_SECRET_OWNER = 'hoonnamkoong'
_SECRET_REPO = 'stockbot-secret'
_SECRET_BRANCH = 'main'
_CONFIG_PATH = 'program_trading.json'
_LEDGER_PATH = 'program_positions.json'

_DUP_GUARD_MIN = 0.5   # 최근 N분 내 재실행 skip (중복 디스패치 방지)
# **이 값은 매매 주기를 따라와야 한다.** 같은 함정에 세 번 빠졌다:
#   - 파이프라인 10분 주기에 가드 15분 → 매 사이클이 걸려 실행이 20분마다로 반토막
#     (2026-07-29 Actions 로그 실측)
#   - 태스커 2분 주기에 가드 5분 → t=0,6,12만 통과, 실효 간격 6분
#   - 매매 루프 60초 주기에 가드 1.5분 → 두 바퀴 중 한 바퀴가 skip돼 실효 2분.
#     1분 매매를 만들어놓고 가드가 그걸 되돌리는 형태였다(2026-08-08).
# 지금 주기는 60초(scripts/trade_loop.TRADE_INTERVAL_SEC)이므로 그보다 작아야 한다.
# 막으려는 건 같은 사이클의 중복 디스패치(수초)이므로 30초면 충분하다.
#
# 주의: 이 가드는 '겹침 방지' 수단이 아니다. 런 실행시간이 가드와 비슷해서 시간
# 기반 판정만으로는 동시 실행을 막을 수 없다. 그건 아래 원장 락이 한다.

_LOCK_LEASE_MIN = 4   # 락 리스(분). 죽은 런의 락을 자동 회수하는 용도.
# 런 최대 실행시간보다 길어야 실행 중인 런의 락이 안 뺏긴다. 정상 종료한 런은
# 락을 명시적으로 비우므로(_release_payload) 리스가 길어도 다음 사이클을 막지 않는다.
# 워크플로 job의 timeout-minutes를 이 값보다 짧게 걸어, 리스 만료 전에 런이 반드시
# 죽게 만들어야 좀비 런이 생기지 않는다.

_ORDER_LOOP_DEADLINE_SEC = 150   # 주문 루프 자체 예산(초). 리스(240초)보다 짧다.
# 리스가 있다고 안심할 게 아니다 — KIS/Vercel이 느려져 이 런이 리스보다 오래
# 살아있으면, 리스 만료 후 다음 런이 "죽은 런"으로 오판해 락을 회수하고 같은
# 주문을 또 낸다(원래 런은 아직 살아서 나머지 주문을 계속 내는 중이다). 리스
# 만료를 기다리지 않고 이 런 스스로 신규 주문을 멈추게 하는 게 유일한 확실한
# 방어다. 클레임 이후 잔고 조회 등에 쓴 시간을 감안해 리스보다 여유 있게 짧게 잡는다.


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
    return {'positions': {}, 'last_run': None, 'sim': None, 'realized_pnl': 0,
            'cooldown_codes': {}, 'turn': {}, 'pending_orders': {}}


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
        d.setdefault('turn', {})
        d.setdefault('pending_orders', {})
        return d, payload.get('sha')
    except Exception as e:
        log(f'[Program] 원장 조회 예외: {e} (fail-closed)')
        return None, None


def _write_ledger(ledger: dict, sha: str | None, log=print, retry_on_conflict: bool = True):
    """원장을 GitHub(secret repo)에 직접 기록.

    retry_on_conflict=True(기본): sha 충돌(409/422) 시 fresh sha로 1회 재시도.
      결과 기록 단계용 — 이미 락을 쥐고 있으므로 덮어써도 된다.
    retry_on_conflict=False: 충돌이면 그대로 실패를 반환한다.
      **락 선점 단계는 반드시 이쪽을 써야 한다** — 충돌은 "다른 런이 먼저 잡았다"는
      뜻이고, 여기서 fresh sha로 재시도하면 남의 락을 덮어써 중복 주문이 난다.

    반환: (성공 여부, 새 sha | None). 새 sha는 다음 PUT에 이어 쓸 수 있다.
    """
    token = _gh_token()
    if not token:
        log('[Program] GH 토큰 없음 → 원장 기록 불가')
        return False, None
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
            if not retry_on_conflict:
                return False, None
            cur = requests.get(f'{url}?ref={_SECRET_BRANCH}', headers=_gh_headers(token), timeout=10)
            if cur.status_code == 200:
                body['sha'] = cur.json().get('sha')
                res = requests.put(url, headers=_gh_headers(token), json=body, timeout=10)
        if res.status_code not in (200, 201):
            log(f'[Program] 원장 기록 실패 HTTP {res.status_code}')
            return False, None
        new_sha = ((res.json() or {}).get('content') or {}).get('sha')
        return True, new_sha
    except Exception as e:
        log(f'[Program] 원장 기록 예외: {e}')
        return False, None


def _new_run_id() -> str:
    """이번 런의 식별자. GitHub Actions 런이면 그 ID를 쓰고(로그 대조가 쉬움),
    로컬 실행이면 난수로 만든다."""
    gh = os.environ.get('GITHUB_RUN_ID')
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT') or '1'
    if gh:
        return f'gh-{gh}-{attempt}'
    return f'local-{uuid.uuid4().hex[:12]}'


def _lock_is_live(ledger: dict, now_kst: datetime) -> bool:
    """다른 런이 원장 락을 쥐고 있는가.

    파싱 불가한 lock_at은 '락 없음'이 아니라 '살아있음'으로 본다 — 모르는 것을
    자유로 읽으면 중복 주문이 난다(fail-closed).
    """
    if not ledger.get('lock_run_id'):
        return False
    raw = ledger.get('lock_at')
    if not raw:
        return True
    try:
        held_since = datetime.fromisoformat(raw)
    except Exception:
        return True
    return (now_kst - held_since) < timedelta(minutes=_LOCK_LEASE_MIN)


def _lock_held_by(ledger: dict, run_id: str) -> bool:
    """이 원장의 락이 아직 내 것인가 (좀비 방어용, 결과 기록 직전 확인)."""
    return ledger.get('lock_run_id') == run_id


def _claim_payload(ledger: dict, run_id: str, now_kst: datetime) -> dict:
    """락 선점용 원장 사본.

    last_run은 건드리지 않는다 — 중복가드(_recently_ran)의 입력이고 락과 수명이
    다르다. 선점 시점에 밀어버리면 주문이 실패해도 다음 사이클이 가드에 걸린다.
    """
    out = dict(ledger)
    out['lock_run_id'] = run_id
    out['lock_at'] = now_kst.isoformat()
    return out


def _release_payload(ledger: dict) -> dict:
    """락 해제용 원장 사본. 정상 종료한 런은 리스를 기다리지 않고 바로 비운다."""
    out = dict(ledger)
    out['lock_run_id'] = None
    out['lock_at'] = None
    return out


def _release_lock(ledger: dict, sha: str | None, log=print) -> None:
    """락만 비우고 나간다 (주문 없이 중단하는 경로 전용).

    실패해도 예외를 올리지 않는다 — 리스 만료로 자동 회수되므로 최악의 비용은
    다음 몇 사이클을 못 도는 것이다.
    """
    ok, _ = _write_ledger(_release_payload(ledger), sha, log)
    if not ok:
        log(f'[Program] 락 해제 실패 — 리스({_LOCK_LEASE_MIN}분) 만료로 자동 회수됩니다')


def _resolve_active_tag(sim_id: str, snapshot: dict) -> str:
    """턴 회계용 활성 전략 태그.

    Sim10은 Sim0 국면에 따라 하위 전략(Sim4-1/Sim5/현금)을 갈아타므로 그 하위 전략을
    태그로 쓴다. active_regime은 Sim10이 run() 중 self.state(=스냅샷)에 써둔 값이라
    Sim10을 수정하지 않고 읽기만 하면 된다. 나머지 심은 자기 id가 곧 태그다.
    """
    if sim_id != 'sim10_orchestrator':
        return sim_id
    return REGIME_TAG.get(snapshot.get('active_regime'), sim_id)


def _recently_ran(ledger: dict, now_kst: datetime) -> bool:
    last = ledger.get('last_run')
    if not last:
        return False
    try:
        prev = datetime.fromisoformat(last)
        return (now_kst - prev) < timedelta(minutes=_DUP_GUARD_MIN)
    except Exception:
        return False


def _psych_carry(paper_state) -> dict:
    """Sim1 이력 슬롯을 페이퍼 심 state에서 프로그램 스냅샷으로 승계한다.

    페이퍼가 **이번 런에 실제로 소비한** 쌍(psych_prev_day, psych_last_run)을 옮긴다.
    psych_snapshot을 옮기면 안 된다 — 그 값은 페이퍼가 방금 이번 런의 z로 덮어썼기
    때문에 프로그램의 accel이 z - 같은 z = 0이 되어 전 종목 0으로 무너진다.

    이 승계가 멱등인 근거는 "정의상 오늘 날짜"가 아니라 resolve_history 자체다 —
    페이퍼가 이번 사이클에 안 돌아 어제자 last_run이 남아 있어도, resolve_history가
    그 값을 다시 승격시켜 페이퍼가 도달했을 결론과 같은 (prev_day, last_run)을
    만든다. 그래서 프로그램 쪽 run()이 다시 resolve_history를 통과해도 재승격으로
    입력이 갈라지지 않는다.

    Sim1 외의 심은 이 슬롯이 없어 빈 dict가 나온다(현행 동작 유지).
    """
    if not isinstance(paper_state, dict):
        return {}
    prev_day = paper_state.get('psych_prev_day')
    last_run = paper_state.get('psych_last_run')
    if prev_day is None and last_run is None:
        return {}
    return {'psych_prev_day': prev_day, 'psych_snapshot': last_run}


def _make_adapter(sim, snapshot_state: dict, today: str, real_holdings: dict | None = None,
                  pending_codes: set | None = None):
    """심 인스턴스를 실계좌 스냅샷으로 운용하도록 개조하고, 의도 주문을 수집한다.
    - state를 스냅샷으로 교체, save_state/log_trade는 no-op(실제 가상 상태 파일 보호).
    - buy/sell을 오버라이드: 주문 의도를 기록 + 스냅샷을 갱신(같은 run 내 일관성).
    - 매수 이중 방어: 실계좌에 있는데 스냅샷 포트폴리오(=원장)에 없는 종목은 거부.
    - 미체결 필터: pending_codes에 걸린 종목은 거부(같은 종목 중복 주문 방지)."""
    sim.state = snapshot_state
    sim.save_state = lambda *a, **k: None
    sim.log_trade = lambda *a, **k: None
    real_holdings = real_holdings or {}
    pending_codes = pending_codes or set()
    orders: list[dict] = []

    def _buy(code, name, price, quantity, reason=""):
        try:
            price = float(price); quantity = int(quantity)
        except (TypeError, ValueError):
            return False
        if quantity <= 0 or price <= 0:
            return False
        if code in pending_codes:
            # 미체결 주문이 걸린 종목 → 매수하면 안 된다(중복 주문 방지).
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
            if k not in ('quantity', 'avg_price', 'tag'):
                p[k] = v


def peek_selected_sim(log=print) -> str | None:
    """프로그램 매매가 켜져 있고 유효하면 선택된 심 id, 아니면 None.

    E3(순서 가변 분기)이 스크래핑 전에 '버즈가 필요한 심을 골랐는가'만 미리
    알기 위해 쓴다. run_program_trading()의 본 게이트(예산·원장·실계좌 조회 등)를
    앞질러 판단하지 않는다 — 이 함수가 True를 준 뒤에도 실제 실행 여부는
    run_program_trading()이 다시 처음부터 fail-closed로 판정한다. 이 함수는
    그 어떤 안전장치도 대체하지 않는다.
    """
    cfg = _read_config_fresh(log)
    if not cfg or not cfg.get('enabled'):
        return None
    sim_id = cfg.get('selected_sim')
    from src.strategy.registry import get_tradeable_simulator_ids
    if sim_id not in get_tradeable_simulator_ids():
        return None
    return sim_id


def settle_pending_orders(ledger, today, lookup, cancel, log, log_error):
    """pending을 정산하고 미체결 잔량을 취소한다. I/O는 주입받는다(테스트 가능).

    취소가 실패하면 그 종목의 pending을 되살린다 — 다음 사이클에 새 주문을
    막기 위해서다. 중복 주문보다 한 사이클 기회손실이 싸다.
    """
    from src.trade.pending import reconcile_pending

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


def run_program_trading(candidates: list[dict], is_market_hours: bool, now_kst: datetime,
                        log=print, log_error=print, enrich=None) -> list[dict] | None:
    """프로그램 매매 1회 실행. 모든 게이트 통과 시에만 실주문.

    반환: 이번 실행이 심에게 실제로 넘긴 후보 목록(심 전용 유니버스를 적용·보강한
    최종본). 게이트에 막혀 심을 돌리지 못했으면 None.

    왜 돌려주는가: 오프틱 사이클에서 페이퍼 쌍둥이가 같은 유니버스를 써야 한다.
    페이퍼 쪽이 get_universe()를 다시 부르면 수십 초 뒤의 라이브 랭킹이라 다른
    종목 집합이 나올 수 있고, 그러면 실전과 페이퍼가 다른 입력으로 판단한다 —
    "심 선택 = 실전 정확히 동일 동작"이 무너지는 방식이다. 조회 비용(네이버 30
    페이지)이 절반으로 주는 건 부수 효과다.
    """
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

    # 3. 원장 fresh 조회 (fail-closed) + 중복 실행 가드 + 락 선점
    ledger, ledger_sha = _read_ledger_fresh(log)
    if ledger is None:
        log_error('[Program] 원장 조회 실패 — skip (fail-closed: 원장 없이 진행 금지)')
        return
    if _recently_ran(ledger, now_kst):
        log('[Program] 최근 실행됨 — 중복 방지 skip')
        return

    # 3-b. 원장 락 — 주문을 내기 전에 배타권을 잡는다.
    # 시간 기반 가드만으로는 겹침을 못 막는다(런 실행시간 ≈ 주기). 두 런이 같은 원장을
    # 읽고 둘 다 가드를 통과해 같은 주문을 두 번 내는 창을 여기서 닫는다.
    if _lock_is_live(ledger, now_kst):
        log(f"[Program] 다른 런이 실행 중(lock={ledger.get('lock_run_id')}) — skip")
        return
    run_id = _new_run_id()
    claimed, ledger_sha = _write_ledger(
        _claim_payload(ledger, run_id, now_kst), ledger_sha, log, retry_on_conflict=False)
    if not claimed:
        # 충돌 = 다른 런이 방금 잡았다. 여기서 fresh sha로 재시도하면 남의 락을
        # 덮어써 중복 주문이 난다. 이번 사이클은 포기한다(fail-closed).
        log('[Program] 락 선점 실패(다른 런이 선점) — skip')
        return
    ledger['lock_run_id'] = run_id
    ledger['lock_at'] = now_kst.isoformat()
    _lock_claimed_at = time.monotonic()  # 주문 루프 자체 데드라인 계산용(벽시계 아님)
    log(f'[Program] 락 선점 (run_id={run_id})')
    # ⚠ 여기부터는 주문 없이 나가는 모든 경로에서 _release_lock()을 불러야 한다.
    #   빠뜨리면 리스({_LOCK_LEASE_MIN}분)가 만료될 때까지 다음 사이클이 전부 막힌다.

    # 4. 실계좌 잔고
    try:
        from src.trade.balance import get_balance
        bal = get_balance()
    except Exception as e:
        log_error(f'[Program] 잔고 조회 실패: {e} — skip')
        _release_lock(ledger, ledger_sha, log)
        return
    if bal.get('error'):
        log_error(f"[Program] 잔고 오류: {bal.get('error')} — skip")
        _release_lock(ledger, ledger_sha, log)
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
        _release_lock(ledger, ledger_sha, log)
        return

    # 5~9. 정합 → 심 인스턴스화 → 유니버스 → 스냅샷 → 어댑터 → 심 실행.
    # 이 블록 전체를 하나의 try로 묶는다 — 락 선점 이후 주문 없이 나가는 경로가
    # 여럿인데(reconcile_positions, get_simulator_by_id, snapshot 구성 등) 하나씩
    # 개별 가드를 달면 새로 추가되는 단계가 빠지기 쉽다. 여기서 예외가 나면
    # 주문은 절대 못 나간 상태이므로, 무조건 락을 놓고 다음 사이클에 넘긴다.
    try:
        # 5. 원장 ↔ 실보유 정합: 프로그램 포지션이 실제로 남아있는 것만 유지(수동 매도분 제거).
        #    dict 전체 복사 — 심이 붙인 전략 플래그(partial_sold 등)를 그대로 보존.
        #    사라진 포지션은 손익을 알 수 없으므로 지어내지 않되 미정산으로 기록한다.
        today = now_kst.strftime('%Y-%m-%d')
        positions = reconcile_positions(ledger, real_holdings, today, log_error)
        ledger['positions'] = positions

        # 5-b. pending 정산은 심 판단보다 먼저다. 정산 전에 판단하면 심이 낡은
        #      보유 상태를 본다 — 방금 체결된 매수를 못 보고 또 사려 들 수 있다.
        from src.trade.executions import lookup_execution
        from src.trade.order_cancel import cancel_order
        settle_pending_orders(ledger, today, lookup_execution, cancel_order, log, log_error)
        positions = ledger['positions']

        # 6. 심 인스턴스화(화이트리스트). 사이징을 effective_budget 기준으로 스케일
        #    → 시뮬(initial_cash/N 사이징)의 비례 축소 복제본으로 동작.
        sim = get_simulator_by_id(sim_id, initial_cash=int(effective_budget))
        if sim is None:
            log(f"[Program] 심 인스턴스 생성 실패: {sim_id} — skip")
            _release_lock(ledger, ledger_sha, log)
            return

        # 주의: sim.state는 _make_adapter가 스냅샷으로 갈아끼우기 전까지만 페이퍼 상태다.
        paper_state = getattr(sim, 'state', None)

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

        # 7-b. [턴 회계] config가 연 턴을 원장에 반영. 표시 전용 — 실패해도 매매는 계속한다.
        turn = ledger.get('turn') or {}
        try:
            cfg_turn = cfg.get('turn') or {}
            if cfg_turn.get('id') and turn.get('id') != cfg_turn['id']:
                turn = new_turn(
                    cfg_turn['id'],
                    cfg_turn.get('capital') or effective_budget,
                    positions,
                    cfg_turn.get('opening_basis'),
                    current_prices,
                )
                log(f"[Program] 새 턴 시작: {cfg_turn['id']} (자본 {turn['capital']:,.0f})")
        except Exception as e:
            log_error(f'[Program] 턴 열기 실패(무시): {e}')
            turn = ledger.get('turn') or {}  # 기존 턴 레코드를 날리지 않는다(다음 실행이 재시도)

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
            'cooldown_codes': dict(ledger.get('cooldown_codes', {})),  # 손절 쿨다운 영속화
            'exec_path': 'program',  # 심이 진단 로그를 페이퍼와 분리하도록 알린다
        }
        # 이력 승계(현재 Sim1만 해당). 없으면 아무것도 안 넣는다 = 현행 동작.
        snapshot.update(_psych_carry(paper_state))

        # 9. 어댑터(실잔고 이중 방어 + 미체결 필터 포함) + 실행
        pending_codes = set(ledger.get('pending_orders') or {})
        orders = _make_adapter(sim, snapshot, today, real_holdings, pending_codes)
        sim.run(sim_candidates, current_prices=current_prices)
    except Exception as e:
        log_error(f'[Program] 주문 준비/심 실행 실패(무시하고 락 해제): {e}')
        _release_lock(ledger, ledger_sha, log)
        return

    # [턴 회계] 활성 전략 확정. Sim10이면 이번 run의 국면(하위 전략)이 스냅샷에 들어있다.
    # 전략이 바뀌었으면 직전 전략의 평가손익을 락인하고 기준가를 리셋한다(MTM).
    active_tag = sim_id
    try:
        active_tag = _resolve_active_tag(sim_id, snapshot)
        if turn:
            switch_tag(turn, positions, active_tag, current_prices)
    except Exception as e:
        log_error(f'[Program] 턴 태그 전환 실패(무시): {e}')

    if not orders:
        log(f'[Program] {sim_id}: 주문 없음')
        ledger['positions'] = positions
        ledger['cooldown_codes'] = snapshot.get('cooldown_codes', {})
        ledger['last_run'] = now_kst.isoformat()
        ledger['sim'] = sim_id
        ledger['turn'] = turn
        _write_ledger(_release_payload(ledger), ledger_sha, log)
        return sim_candidates

    # 10. 안전 필터 + 집행
    from src.trade_executor import place_order_via_vercel, append_order_history
    executed = 0
    failed_codes: set = set()

    # 준비 단계(잔고 조회 → 정합 → 유니버스 보강 → 심 실행)에 쓴 시간. 정상은
    # 10초대지만(2026-08-07 실측 Stage 0.5 = 12.4초), KIS나 네이버가 느려지면
    # 이것만으로 주문 예산을 다 먹을 수 있다. 그러면 아래 루프가 첫 바퀴에서
    # 곧바로 끊겨 **매 사이클 체결 0건인데 로그는 정상으로 보이는** 상태가 된다.
    # 그건 조용한 정지이므로 따로 구분해 알린다.
    prep_sec = time.monotonic() - _lock_claimed_at
    log(f'[Program] 주문 준비 {prep_sec:.1f}초 / 예산 {_ORDER_LOOP_DEADLINE_SEC}초')
    if prep_sec > _ORDER_LOOP_DEADLINE_SEC:
        msg = (f'주문 준비에만 {prep_sec:.0f}초가 걸려 예산'
               f'({_ORDER_LOOP_DEADLINE_SEC}초)을 넘겼습니다. 이번 사이클은 주문을 '
               f'내지 않습니다({len(orders)}건 보류). 계속되면 매매가 사실상 멈춥니다 — '
               f'KIS/네이버 응답 지연을 확인하세요.')
        log_error(f'[Program] ⚠ {msg}')
        alerts.send_alert_once('program_prep_over_budget', msg, now_kst,
                               cooldown_min=60, log=log)

    for i, o in enumerate(orders):
        # 락 리스 데드라인 재확인 — KIS/Vercel이 느려져 이 런이 예상보다 오래 걸리면,
        # 리스 만료를 기다리지 않고 스스로 신규 주문을 멈춘다. 안 그러면 리스가
        # 만료된 줄 알고 들어온 다음 런과 동시에 주문을 내게 된다.
        if time.monotonic() - _lock_claimed_at > _ORDER_LOOP_DEADLINE_SEC:
            log(f"[Program] 주문 루프 데드라인 초과({_ORDER_LOOP_DEADLINE_SEC}초) — "
                f"신규 주문 중단, 나머지 {len(orders) - i}건 다음 사이클로")
            failed_codes.update(x['code'] for x in orders[i:])
            break
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
        # 정규장이 닫힌 뒤에는 신규 매수를 내지 않는다. 매도는 그대로 둔다.
        if side == 'buy' and not _buy_allowed(now_kst):
            log(f'[Program] SKIP buy {code} — 정규장 종료({MARKET_CLOSE_HHMM[0]}:'
                f'{MARKET_CLOSE_HHMM[1]:02d}) 이후 신규 매수 금지')
            continue

        # 판단가와 체결 시점 가격이 벌어졌으면 그 진입은 포기한다(매수 한정).
        # 후보 가격은 스크래퍼 스냅샷이라 주문 시점엔 10분 이상 묵어 있을 수 있다.
        # 지정가는 심 판단가로 건다 — 여기서 조회하는 live_px는 괴리 판정에만 쓰고
        # 주문가를 덮어쓰지 않는다. 덮어쓰면 "원하는 가격에만 산다"는 지정가의
        # 취지가 시장가와 다를 바 없어진다. 그래도 괴리가 너무 크면 체결 가능성이
        # 낮은 pending만 쌓여 그 종목의 다음 매수 기회를 막으므로 미리 포기한다.
        limit_price = price
        if side == 'buy':
            allowed, live_px, why = check_buy_drift(code, price, _price_quote)
            if not allowed:
                log(f'[Program] SKIP buy {code} — {why}')
                failed_codes.add(code)
                continue
        try:
            res = place_order_via_vercel(
                side, code, qty, limit_price if side == 'buy' else price,
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
                    # price는 KIS 확정 체결가가 아닌 주문가 추정치 — 다음 사이클
                    # settle_pending_orders가 실측가로 차액을 정정한다.
                    pre_sell_snapshot = dict(positions[code]) if code in positions else {}
                    avg = pre_sell_snapshot.get('avg_price')
                    accrue_realized_pnl(ledger, positions, code, qty, price)
                    try:
                        if turn:
                            record_sell(turn, positions, code, qty, price)
                    except Exception as e:
                        log_error(f'[Program] 턴 체결 기록 실패(무시): {e}')
                    _apply_order_to_positions(positions, o, today)
                    if odno:
                        register_pending(ledger, code, odno, 'sell', qty, price,
                                         now_kst.isoformat(), avg_price=avg, tag=active_tag,
                                         snapshot=pre_sell_snapshot)
                else:
                    # 매수는 원장에 넣지 않는다 — 체결 확인 후 다음 사이클
                    # (settle_pending_orders)에 들어간다. 여기서 넣으면 "주문 접수 =
                    # 체결"로 간주하던 옛 버그가 지정가에서 재발한다.
                    if odno:
                        register_pending(ledger, code, odno, 'buy', qty, limit_price,
                                         now_kst.isoformat(), tag=active_tag)
                append_order_history({
                    'executed_at': now_kst.isoformat(), 'side': side, 'code': code,
                    'name': o.get('name', ''), 'qty': qty, 'price': price,
                    'status': 'executed' if side == 'sell' else 'pending',
                    'reason': f"[프로그램:{sim_id}] {o.get('reason', '')}",
                    'odno': odno,
                })
                executed += 1
                if side == 'sell':
                    log(f"[Program] 체결: SELL {code} {qty}주 @ {price}"
                        f"{f' (odno={odno})' if odno else ''}")
                else:
                    log(f"[Program] 지정가 주문 접수: BUY {code} {qty}주 @ {price}"
                        f"{f' (odno={odno})' if odno else ''} — 체결 확인 대기")
            else:
                failed_codes.add(code)
                log(f"[Program] 주문 거부 {code}: {res.get('error')}")
        except Exception as e:
            failed_codes.add(code)
            log_error(f'[Program] 주문 집행 실패 {code}: {e}')

    # 11. 전략 플래그 머지(체결 성공 종목만) + 원장 저장 + 락 해제
    _merge_strategy_flags(positions, snapshot['portfolio'], failed_codes)
    ledger['positions'] = positions
    ledger['cooldown_codes'] = snapshot.get('cooldown_codes', {})
    ledger['last_run'] = now_kst.isoformat()
    ledger['sim'] = sim_id
    try:
        if turn:
            prune_basis(turn, positions)
    except Exception as e:
        log_error(f'[Program] 턴 기준가 정리 실패(무시): {e}')
    ledger['turn'] = turn

    # 좀비 방어: 기록 직전에 락이 아직 내 것인지 확인한다. 리스가 만료될 만큼 오래
    # 걸린 런은 그 사이 다른 런이 락을 회수해 같은 주문을 냈을 수 있다. 조용히
    # 넘어가면 중복 체결을 모른 채 지나가므로, 덮어쓰지 않고 크게 남긴다.
    current, current_sha = _read_ledger_fresh(log)
    if current is not None and not _lock_held_by(current, run_id):
        msg = (f"락을 빼앗겼습니다(내 run_id={run_id}, "
               f"현재={current.get('lock_run_id')}). 이 런의 결과를 덮어쓰지 않습니다 — "
               f"중복 체결 가능성이 있으니 KIS 체결 내역을 확인하세요. "
               f"체결 {executed}/{len(orders)}건.")
        log_error(f'[Program] ⚠ {msg}')
        # 실제 돈이 두 번 나갔을 수 있는 유일한 신호다. log_error는 print라
        # Actions 로그에만 남는다 — 사람에게 직접 보낸다. 반복 억제는 걸지
        # 않는다: 체결 건마다 확인해야 할 사고다.
        alerts.send_alert(f'프로그램 매매 원장 락 상실\n\n{msg}', log)
        return sim_candidates
    if current_sha:
        ledger_sha = current_sha
    _write_ledger(_release_payload(ledger), ledger_sha, log)
    log(f'[Program] 완료: {executed}/{len(orders)}건 체결 (sim={sim_id})')
    return sim_candidates


# 매수 판단가 대비 허용 괴리(%). 초과하면 그 진입은 포기한다.
# 심의 진입 조건(모멘텀·ADX·기간수익률)은 판단 시점 가격으로 계산된 것이라,
# 그보다 크게 오른 가격에서는 근거가 성립하지 않는다. 2026-07-30 LG생활건강이
# 263,000 판단 → 303,000 체결(+15.2%)로 이 구멍을 드러냈다.
BUY_DRIFT_MAX_PCT = 2.0


def _price_quote(code: str) -> dict:
    """주문 직전 현재가 조회. 매번 새 인스턴스를 쓴다 — KISDataProvider의 캐시는
    인스턴스 단위(TTL 5분)라, 재사용하면 가드가 5분 묵은 값을 볼 수 있다."""
    from src.trade.kis_data_provider import KISDataProvider
    return KISDataProvider().get_price_quote(code)


def check_buy_drift(code: str, decided_price: float, quote_fn) -> tuple[bool, float | None, str]:
    """매수 직전 현재가를 재조회해 판단가와의 괴리를 검사한다.

    반환: (주문해도 되는가, 조회된 현재가 또는 None, 차단 사유)

    - 상승 괴리만 막는다. 판단가보다 싸진 것은 불리하지 않다.
    - 현재가를 못 받으면 막는다(fail-closed). 매수는 건너뛰어도 원금 손실이 없고
      다음 사이클에 기회가 다시 온다 — 괴리를 모르는 채 시장가로 던지는 쪽이 위험하다.
    - 매도에는 쓰지 않는다. 청산은 무조건 나가야 한다.
    """
    if not decided_price or decided_price <= 0:
        return True, None, ''          # 비교 기준이 없으면 가드를 걸지 않는다
    try:
        quote = quote_fn(code) or {}
        live = float(quote.get('price') or 0)
    except Exception as e:
        return False, None, f'현재가 조회 실패({e})'
    if live <= 0:
        return False, None, '현재가 조회 실패(값 없음)'

    drift_pct = (live - decided_price) / decided_price * 100
    if drift_pct > BUY_DRIFT_MAX_PCT:
        return False, live, (f'판단가 {decided_price:,.0f} → 현재가 {live:,.0f} '
                             f'괴리 +{drift_pct:.1f}% (상한 {BUY_DRIFT_MAX_PCT:.0f}%)')
    return True, live, ''


def reconcile_positions(ledger: dict, real_holdings: dict, today: str, log_error) -> dict:
    """원장 ↔ 실보유 정합. 실계좌에 없는 프로그램 포지션은 빼되, 뺐다는 사실을 남긴다.

    조용히 지우면 그 청산 손익이 realized_pnl에서 통째로 빠진다. realized_pnl은
    프로그램이 낸 매도가 체결될 때만 누적되기 때문이다. 2026-07-08에 진흥기업
    1,230주(매입원가 1,495,680원)와 비엘팜텍 72주(295,920원)가 그렇게 빠졌고,
    수동 매도가 대개 손절이라 손실만 빠지고 이익은 남아 수익률이 실제보다
    좋아 보였다.

    체결가는 우리 기록에 없으므로 손익을 만들어 채우지 않는다. 매입원가만 적고
    '미정산'으로 남겨 나중에 사람이 정산할 수 있게 한다.
    """
    prev = ledger.get('positions', {}) or {}
    kept = {c: dict(p) for c, p in prev.items() if c in real_holdings}

    for code in prev:
        if code in kept:
            continue
        p = prev[code]
        qty = p.get('quantity', 0)
        avg = p.get('avg_price', 0)
        cost = round(float(avg) * float(qty), 2)
        ledger.setdefault('unreconciled_exits', []).append({
            'date': today, 'code': code, 'name': p.get('name', code),
            'quantity': qty, 'avg_price': avg, 'cost_basis': cost,
        })
        log_error(f"[Program] 원장에서 사라진 포지션 {code}({p.get('name', '?')}) "
                  f"{qty}주 매입원가 {cost:,.0f}원 — 실계좌에 없음. 손익 미계상(수동 매도 추정)")
    return kept


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
