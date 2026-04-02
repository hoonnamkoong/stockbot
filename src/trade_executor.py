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
        # 폴백: 직접 검증
        required = ['KIS_APP_KEY', 'KIS_APP_SECRET', 'KIS_ACCOUNT_NO', 'KIS_BASE_URL']
        for k in required:
            if not os.environ.get(k):
                print(f"[TradeExecutor] ❌ 필수 환경 변수 누락: {k}")
                return False
        return True


# ─── place_order 임포트 ───────────────────────────────────────────────────────

try:
    from order import place_order
    _ORDER_AVAILABLE = True
except ImportError as _e:
    print(f"[TradeExecutor] ⚠️  place_order 임포트 실패 (Trade 기능 제한): {_e}")
    _ORDER_AVAILABLE = False
    def place_order(side, code, qty, price):
        raise RuntimeError("place_order 모듈 로드 실패로 주문을 실행할 수 없습니다.")


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

def append_order_history(record: dict) -> None:
    history = _load_json_file(ORDER_HISTORY_FILE, [])
    if not isinstance(history, list): history = []
    history.insert(0, record)
    _save_json_file(ORDER_HISTORY_FILE, history)


# ─── 메인 로직 ───────────────────────────────────────────────────────────────

def main():
    now_utc = datetime.now(timezone.utc)
    print(f"\n[TradeExecutor] 실행 — {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC")

    # --- KIS 잔고 조회 강제 실행 (사용자 긴급 지시) ---
    print("\n[TradeExecutor] (강제 지시) KIS 계좌 잔고 조회 루틴 강제 실행...")
    try:
        from balance import check_balance
        check_balance()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[TradeExecutor] KIS 잔고 조회 강제 실행 중 실패: {e}")
    # ------------------------------------------------

    # 1. 환경 변수 엄격 검증
    if not _validate_trade_env_strict():
        print("[TradeExecutor] ❌ 치명적 오류: 환경 변수 미비. Workflow를 중단합니다.")
        sys.exit(1) # Silent Failure 방지

    # 2. 주문 모듈 확인
    if not _ORDER_AVAILABLE:
        print("[TradeExecutor] ❌ 치명적 오류: 주문 모듈(order.py) 로드 불가.")
        sys.exit(1)

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

            if res.get('status') == 'executed': continue

            if now_utc < target_time:
                pending_reservations.append(res)
                continue

            # ── 실행 ──
            code  = res.get('code', '')
            side  = res.get('side', 'buy')
            qty   = int(res.get('qty', 1))
            price = int(res.get('price', 0))

            print(f"  [Execute] 예약 {res_id}: {side.upper()} {code} {qty}주")
            place_order(side=side, code=code, qty=qty, price=price)

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
