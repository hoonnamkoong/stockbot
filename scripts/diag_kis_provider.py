"""
일회성 진단: KISDataProvider 5종 보강 API의 실제 응답 구조/실패원인 덤프.
시뮬(bull 등)이 의존하는 기관/외인 추정·재무비율 데이터가 왜 0인지 규명용.

실행(장중 09:00~15:30 KST 권장):
    KIS_APP_KEY=... KIS_APP_SECRET=... python scripts/diag_kis_provider.py [종목코드]
  - 토큰은 data/kis_token_cache.json(로컬 캐시) 또는 GH_PAT로 stockbot-secret에서 자동 획득
  - 종목코드 미지정 시 005930(삼성전자)
"""
import os, sys, json, requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.trade.auth import get_access_token, get_base_url

CODE = sys.argv[1] if len(sys.argv) > 1 else "005930"

token = get_access_token()
base = get_base_url()
appkey = os.environ.get("KIS_APP_KEY", "").strip()
secret = os.environ.get("KIS_APP_SECRET", "").strip()
print(f"token={'OK(len%d)'%len(token) if token else 'NONE'} base={base} appkey={'OK' if appkey else 'MISSING'} secret={'OK' if secret else 'MISSING'} code={CODE}\n")

CALLS = [
    ("investor-trend-estimate", "HHPTJ04160200",
     "/uapi/domestic-stock/v1/quotations/investor-trend-estimate", {"MKSC_SHRN_ISCD": CODE}),
    ("finance/profit-ratio", "FHKST66430400",
     "/uapi/domestic-stock/v1/finance/profit-ratio",
     {"FID_INPUT_ISCD": CODE, "FID_DIV_CLS_CODE": "0", "FID_COND_MRKT_DIV_CODE": "J"}),
    ("finance/stability-ratio", "FHKST66430600",
     "/uapi/domestic-stock/v1/finance/stability-ratio",
     {"FID_INPUT_ISCD": CODE, "FID_DIV_CLS_CODE": "0", "FID_COND_MRKT_DIV_CODE": "J"}),
    ("invest-opinion", "FHKST663300C0",
     "/uapi/domestic-stock/v1/quotations/invest-opinion",
     {"FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "16633", "FID_INPUT_ISCD": CODE}),
]

for name, tr_id, path, params in CALLS:
    print(f"===== {name}  (tr_id={tr_id}) =====")
    try:
        r = requests.get(f"{base}{path}",
                         headers={"Content-Type": "application/json; charset=utf-8",
                                  "authorization": f"Bearer {token}",
                                  "appkey": appkey, "appsecret": secret, "tr_id": tr_id},
                         params=params, timeout=6)
        print(f"  HTTP {r.status_code}")
        try:
            b = r.json()
        except Exception:
            print("  (JSON 아님):", r.text[:200]); print(); continue
        print(f"  rt_cd={b.get('rt_cd')} msg_cd={b.get('msg_cd')} msg1={b.get('msg1')}")
        print(f"  top-level keys: {list(b.keys())}")
        for k in ("output", "output1", "output2"):
            if k in b:
                v = b[k]
                if isinstance(v, list):
                    print(f"  {k}: list(len={len(v)})", end="")
                    if v:
                        print(f"  첫행 keys={list(v[0].keys())[:12]}")
                        # 가집계 필드가 있으면 처음/끝 행 값 표시
                        for idx in ([0, -1] if len(v) > 1 else [0]):
                            row = v[idx]
                            picked = {kk: row.get(kk) for kk in
                                      ('bsop_hour', 'frgn_fake_ntby_qty', 'orgn_fake_ntby_qty',
                                       'sum_fake_ntby_qty', 'self_cptl_ntin_inrt', 'lblt_rate',
                                       'invt_opnn', 'hts_goal_prc') if kk in row}
                            print(f"    row[{idx}]: {picked}")
                    else:
                        print(" (비어있음)")
                elif isinstance(v, dict):
                    print(f"  {k}: dict keys={list(v.keys())[:12]}")
    except Exception as e:
        print(f"  요청 예외: {e}")
    print()
