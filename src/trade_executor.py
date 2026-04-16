import json
import os
import sys
import traceback
from datetime import datetime, timezone

# ─── 경로 설정 ───────────────────────────────────────────────────────────────
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_TRADE_DIR = os.path.join(_REPO_ROOT, 'trade')

if _TRADE_DIR not in sys.path:
    sys.path.insert(0, _TRADE_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ─── 환경 변수 검증 (ConfigValidator 연동) ───────────────────────────────────

def _validate_trade_env_strict() -> bool:
    """
    KIS 트레이딩 환경 변수를 엄격하게 검증합니다.
    누락되거나 형식이 틀리면 sys.exit(1)로 강제 종료하여 가시성을 확보합니다.
    """
    try:
        from src.config_validator import validate_trade
        is_ok, missing = validate_trade()
        if not is_ok:
            print(f"[TradeExecutor] ❌ 환경 변수 검증 실패 (항목: {len(missing)})")
            return False
        return True
    except ImportError:
        # 폴백: 직접 검증 (Vercel Proxy 용)
        required = ['WEBHOOK_SECRET', 'DASHBOARD_URL']
        for k in required:
            if not os.environ.get(k):
                print(f"[TradeExecutor] ❌ 필수 환경 변수 누락: {k}")
                return False
        return True


# ─── place_order 임포트 ───────────────────────────────────────────────────────

# ─── place_order 대규모 수정 (Vercel Proxy 위임) ──────────────────────────

import requests

def place_order_via_vercel(side, code, qty, price):
    webhook_secret = os.environ.get("WEBHOOK_SECRET")
    dashboard_url = os.environ.get("DASHBOARD_URL", "https://stockbot-phi.vercel.app").rstrip("/")
    # [V8.9.9.25 Structural Fix] API 주소 교정 (trade -> trade/order)
    url = f"{dashboard_url}/api/trade/order"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {webhook_secret}"
    }
    payload = {
        "side": side,
        "code": code,
        "qty": qty,
        "price": price
    }
    
    print(f"[TradeExecutor] Sending Webhook to Vercel: {url} | payload: {payload}")
    # 타임아웃 15초(Vercel Severless 특성 고려)
    res = requests.post(url, headers=headers, json=payload, timeout=15)
    
    if res.status_code != 200:
        print(f"[TradeExecutor] ❌ Vercel API Error: {res.status_code} - {res.text}")
        raise RuntimeError(f"Vercel API failed with {res.status_code}")
    
    data = res.json()
    if not data.get('success'):
        # [V8.9.9.28 Robustness Fix] 시장 사유로 인한 거부 시 특수 로깅
        if data.get('rejected'):
            print(f"[TradeExecutor] ⚠️ 시장 사유로 주문 거부됨: {data.get('error')}")
            return data # 실패가 아닌 '거부됨' 데이터를 반환
        raise RuntimeError(f"API success false: {data.get('error')}")
        
    print(f"[TradeExecutor] ✅ Vercel API 응답: {res.text}")
    return data


# ─── 파일 경로 상수 ───────────────────────────────────────────────────────────

RESERVATIONS_FILE  = os.path.join(_REPO_ROOT, 'data', 'reservations.json')
ORDER_HISTORY_FILE = os.path.join(_REPO_ROOT, 'data', 'order_history.json')


# ─── 유틸리티 ────────────────────────────────────────────────────────────────

def _load_json_file(filepath: str, default):
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        print(f"[TradeExecutor] ❌ JSON 읽기 실패: {filepath}")
        traceback.print_exc()
        return default


def _save_json_file(filepath: str, data) -> bool:
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        print(f"[TradeExecutor] ❌ JSON 저장 실패: {filepath}")
        traceback.print_exc()
        return False

# (load_reservations, save_reservations, append_order_history 등 기존 유틸리티 유지)
def load_reservations() -> list:
    return _load_json_file(RESERVATIONS_FILE, [])

def save_reservations(reservations: list) -> None:
    if _save_json_file(RESERVATIONS_FILE, reservations):
        print(f"[TradeExecutor] 예약 목록 업데이트 완료 (잔여: {len(reservations)}건)")

import csv
def append_trade_history_csv(side, code, qty, price, name="Unknown", reason="[실전] KIS 체정 후 수동 기록", roi=None):
    filepath = os.path.join(_REPO_ROOT, 'data', 'trade_history_real.csv')
    file_exists = os.path.exists(filepath)
    now_kst = datetime.now() # KST 기준 (로컬 실행 시)
    total_amount = qty * price
    # ROI 문자열 처리 (없으면 '-')
    roi_str = f"{roi:+.2f}%" if roi is not None else "-"
    
    with open(filepath, 'a', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "symbol", "action", "price", "quantity", "total_amount", "roi", "reason"])
        writer.writerow([
            now_kst.strftime('%Y-%m-%d %H:%M:%S'), 
            f"{name}({code})", 
            side.upper(), 
            f"{price:,.0f}", 
            qty, 
            f"{total_amount:,.0f}",
            roi_str,
            reason
        ])

    )


# ─── 유틸리티: 종목명 자동 매칭 ─────────────────────────

def _lookup_stock_name(code: str) -> str:
    """코드를 기반으로 로컬 DB에서 종목명을 찾습니다."""
    try:
        stocks_db_path = os.path.join(_REPO_ROOT, 'data', 'all_stocks.json')
        if os.path.exists(stocks_db_path):
            with open(stocks_db_path, 'r', encoding='utf-8') as f:
                stocks = json.load(f)
                for s in stocks:
                    if s.get('code') == code:
                        return s.get('name', 'Unknown')
    except Exception:
        pass
    return "Unknown"


def append_order_history(record: dict) -> None:
    history = _load_json_file(ORDER_HISTORY_FILE, [])
    if not isinstance(history, list): history = []
    
    # [V8.9.9.45 Robustness] 종목명 자동 복구 (Unknown 방지)
    code = record.get('code', '')
    name = record.get('name', 'Unknown')
    if (not name or name == 'Unknown') and code:
        record['name'] = _lookup_stock_name(code)
    
    # [V8.9.9.45 Robustness] 가격 보정 (0원 방지)
    price = float(record.get('price', 0))
    if price <= 0:
        # 시장가로 주문된 경우 portfolio.json의 현재가(prpr)라도 가져오기 시도
        try:
            p_path = os.path.join(_REPO_ROOT, 'data', 'portfolio.json')
            p_data = _load_json_file(p_path, {})
            for h in p_data.get('output1', []):
                if h.get('pdno') == code:
                    record['price'] = float(h.get('prpr', 0))
                    break
        except: pass

    # [V8.9.9.41 ROI Calculation] 매도 시 수익률 계산
    roi = None
    side = record.get('side', 'buy').lower()
    if side == 'sell':
        try:
            portfolio_path = os.path.join(_REPO_ROOT, 'data', 'portfolio.json')
            portfolio_data = _load_json_file(portfolio_path, {})
            # output1에서 해당 종목 찾기
            holdings = portfolio_data.get('output1', [])
            for h in holdings:
                if h.get('pdno') == record.get('code'):
                    avg_price = float(h.get('pchs_avg_pric', 0))
                    sell_price = float(record.get('price', 0))
                    if avg_price > 0:
                        roi = ((sell_price - avg_price) / avg_price) * 100
                    break
        except Exception as e:
            print(f"[TradeExecutor] ROI 계산 실패: {e}")

    history.insert(0, record)
    _save_json_file(ORDER_HISTORY_FILE, history)
    # CSV에도 동시 기록 (ROI 포함)
    append_trade_history_csv(
        side=side,
        code=record.get('code', ''),
        qty=record.get('qty', 0),
        price=record.get('price', 0),
        name=record.get('name', 'Unknown'),
        roi=roi,
        reason=record.get('reason', '[실전] KIS 체결 기록')
    )


# ─── 메인 로직 ───────────────────────────────────────────────────────────────

def main():
    # [V8.9.9.16] 기준 시각을 KST로 통일 (한국 시장 기준)
    from datetime import timedelta
    now_kst = datetime.utcnow() + timedelta(hours=9)
    print(f"\n[TradeExecutor] 실행 — {now_kst.strftime('%Y-%m-%d %H:%M:%S')} KST")

    # --- KIS 잔고 조회 의존성 제거 (Vercel Proxy) ---
    print("\n[TradeExecutor] 로컬에서의 KIS 직접 호출 방식을 제거하고 Vercel Proxy로 이관되었습니다.")
    # ------------------------------------------------

    # 1. 환경 변수 엄격 검증
    if not _validate_trade_env_strict():
        print("[TradeExecutor] ❌ 치명적 오류: 환경 변수 미비. Workflow를 중단합니다.")
        sys.exit(1) # Silent Failure 방지

    # 2. 주문 모듈 확인 (제거됨 - Vercel 프록시가 대신함)
    pass

    # 3. 예약 목록 처리
    reservations = load_reservations()
    if not reservations:
        print("[TradeExecutor] 처리할 예약 주문이 없습니다.")
        return # 대기 중인 예약이 없는 것은 정상 종료

    print(f"[TradeExecutor] {len(reservations)}건의 예약 검토 시작...")
    pending_reservations = []
    executed_count = 0
    failed_count = 0

    # [V8.9.9.18 End-of-Day Audit] 당일 장 마감(15:30) 이후에는 처리 안 된 모든 예약을 취소 처리
    is_market_closed = now_kst.hour >= 16 or (now_kst.hour == 15 and now_kst.minute >= 40)
    
    for res in reservations:
        res_id = res.get('id', 'unknown')
        try:
            # [기존 예약 파싱 로직]
            target_time_str = res.get('targetTime', res.get('time', '')).strip()
            if not target_time_str:
                pending_reservations.append(res)
                continue

            if ":" in target_time_str and "-" not in target_time_str:
                h, m = map(int, target_time_str.split(":"))
                target_time = now_kst.replace(hour=h, minute=m, second=0, microsecond=0)
            else:
                if target_time_str.endswith('Z'):
                    target_time_str = target_time_str[:-1] + '+00:00'
                target_time_dt = datetime.fromisoformat(target_time_str)
                if target_time_dt.tzinfo is not None:
                    target_time = target_time_dt.astimezone(timezone(timedelta(hours=9))).replace(tzinfo=None)
                else:
                    target_time = target_time_dt

            status = res.get('status', 'pending')
            if status == 'executed' or status == 'cancelled': continue
            
            # 장 마감 후 미처리 건은 자동 취소
            if is_market_closed:
                print(f"  [Audit] 예약 {res_id}: 장 마감으로 인한 자동 취소 처리.")
                append_order_history({
                    'id': res_id, 'executed_at': now_kst.isoformat(),
                    'side': res.get('side', ''), 'code': res.get('code', ''), 'qty': res.get('qty', 0), 'price': res.get('price', 0),
                    'status': 'cancelled', 'reason': 'Market Closed (End-of-Day Audit)'
                })
                continue

            is_overdue = now_kst >= target_time
            if not is_overdue:
                pending_reservations.append(res)
                continue

            # [실행 로직]
            code  = res.get('code', '')
            side  = res.get('side', 'buy')
            qty   = int(res.get('qty', 1))
            price = int(res.get('price', 0))

            print(f"  [Execute] 예약 {res_id}: {side.upper()} {code} {qty}주 -> Vercel Proxy 요청")
            exec_res = place_order_via_vercel(side=side, code=code, qty=qty, price=price)

            if exec_res.get('success'):
                status = 'executed'
                reason = 'Executed via Vercel Proxy'
            else:
                # [V8.9.9.28] 거부된 종목 처리
                status = 'cancelled'
                reason = f"Rejected by Broker: {exec_res.get('error')}"
                print(f"  [Skip] 예약 {res_id} 거부됨 -> 취소 처리 ({reason})")

            # [V8.9.9.31 Precision Fix] 실제 체결 정보 기록 보강 (Unknown 방지)
            real_name = exec_res.get('name', res.get('name', 'Unknown'))
            real_price = exec_res.get('price', price)
            if real_price == 0: real_price = price # 폴백
            
            # [V8.9.9.31] 수익률(Yield) 계산 (매도 시에만)
            profit_rate = None
            if side == 'sell':
                avg_buy_price = res.get('avg_buy_price', 0)
                if avg_buy_price > 0:
                    profit_rate = ((real_price - avg_buy_price) / avg_buy_price) * 100

            append_order_history({
                'id': res_id, 
                'executed_at': now_kst.isoformat(),
                'side': side, 
                'code': code, 
                'name': real_name,
                'qty': qty, 
                'price': real_price,
                'yield': round(profit_rate, 2) if profit_rate is not None else None,
                'status': status, 
                'reason': reason
            })
            executed_count += 1

        except Exception:
            failed_count += 1
            print(f"  [Error] 예약 {res_id} 처리 실패")
            traceback.print_exc()
            pending_reservations.append(res)

    print(f"\n[TradeExecutor] 결과: 성공={executed_count}, 실패={failed_count}, 대기={len(pending_reservations)}")

    if failed_count > 0:
        save_reservations(pending_reservations)
        print("[TradeExecutor] ❌ 일부 주문 실패가 발생했습니다. 로그를 확인하세요.")
        # 실패한 주문이 있어도 Workflow 전체를 실패로 띄워야 가시성이 확보됨
        sys.exit(1)
        
    if executed_count > 0:
        save_reservations(pending_reservations)

if __name__ == "__main__":
    main()
