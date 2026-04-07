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
    url = f"{dashboard_url}/api/trade"

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
    print(f"[TradeExecutor] ✅ Vercel API 응답: {res.text}")


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
def append_trade_history_csv(side, code, qty, price, name="Unknown", reason="[실전] KIS 체정 후 수동 기록"):
    filepath = os.path.join(_REPO_ROOT, 'data', 'trade_history_real.csv')
    file_exists = os.path.exists(filepath)
    now_kst = datetime.now() # KST 기준 (로컬 실행 시)
    total_amount = qty * price
    with open(filepath, 'a', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "symbol", "action", "price", "quantity", "total_amount", "reason"])
        writer.writerow([
            now_kst.strftime('%Y-%m-%d %H:%M:%S'), 
            f"{name}({code})", 
            side.upper(), 
            f"{price:,.0f}", 
            qty, 
            f"{total_amount:,.0f}",
            reason
        ])

def append_order_history(record: dict) -> None:
    history = _load_json_file(ORDER_HISTORY_FILE, [])
    if not isinstance(history, list): history = []
    history.insert(0, record)
    _save_json_file(ORDER_HISTORY_FILE, history)
    # CSV에도 동시 기록
    append_trade_history_csv(
        side=record.get('side', 'buy'),
        code=record.get('code', ''),
        qty=record.get('qty', 0),
        price=record.get('price', 0),
        name=record.get('name', 'Unknown'),
        reason=record.get('reason', '[실전] KIS 체결 기록')
    )


# ─── 메인 로직 ───────────────────────────────────────────────────────────────

def main():
    now_utc = datetime.now(timezone.utc)
    print(f"\n[TradeExecutor] 실행 — {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC")

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

    for res in reservations:
        res_id = res.get('id', 'unknown')
        try:
            target_time_str = res.get('targetTime', '').strip()
            if not target_time_str:
                pending_reservations.append(res)
                continue

            if target_time_str.endswith('Z'):
                target_time_str = target_time_str[:-1] + '+00:00'

            target_time = datetime.fromisoformat(target_time_str)
            if target_time.tzinfo is None:
                target_time = target_time.replace(tzinfo=timezone.utc)

            # [Catch-up 로직] 예약 상태가 'pending'이고 실행 목표 시간이 현재보다 과거인 경우 즉시 실행
            status = res.get('status', 'pending')
            if status == 'executed': continue
            
            is_overdue = now_utc >= target_time
            if not is_overdue:
                # 미래 예약이므로 건너뜀
                pending_reservations.append(res)
                continue

            # 이 시점에서는 target_time <= now_utc 이고 status != 'executed'임
            print(f"  [Catch-up] 예약 {res_id}: 목표시간({target_time_str}) 경과됨. 즉시 실행 시도.")

            # ── 실행 ──
            code  = res.get('code', '')
            side  = res.get('side', 'buy')
            qty   = int(res.get('qty', 1))
            price = int(res.get('price', 0))

            print(f"  [Execute] 예약 {res_id}: {side.upper()} {code} {qty}주 -> Vercel Proxy 요청")
            place_order_via_vercel(side=side, code=code, qty=qty, price=price)

            append_order_history({
                'id': res_id, 'executed_at': now_utc.isoformat(),
                'side': side, 'code': code, 'qty': qty, 'price': price,
                'status': 'executed'
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
