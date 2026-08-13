"""예산 클램프가 어느 현금을 보고 있는지 드러낸다.

2026-08-13 실전 로그:
    budget(2,000,000) + 누적실현손익(+25,254) = effective_budget(2,025,254)
    effective_budget이 실제 계좌가치(1,235,198)를 초과 — 클램프

계좌가치는 `deposit + Σ(avg_price×qty)`로 재구성하는데, `deposit`이
`dnca_tot_amt`(예수금총액) **하나뿐**이다. 매도대금은 D+2에 편입되므로,
매일 파는 단타 심에서는 판 돈이 이틀간 이 숫자에 안 잡힌다.

대시보드(TS)는 이미 D+2를 읽고 있다 — `src/lib/kis-api.ts`가
`prvs_rcdl_excc_amt`를 `deposit_d2`로 파싱하고 주석까지 달려 있다. Python
쪽만 빠져 있어서 같은 계좌를 두 코드가 다르게 본다.

**여기서는 값을 드러내기만 한다.** 클램프 상한을 올리는 건 "실제로 없는 돈으로
주문을 낸다"는 방향의 실패라, 실계좌 raw 응답으로 세 숫자의 관계를 확인하기
전에는 하지 않는다. 진단이 가정보다 앞선다.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.trade import balance as balance_mod


class _Res:
    status_code = 200

    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


_OUTPUT2 = {
    'dnca_tot_amt': '1000000',        # 예수금총액(D+0)
    'nxdy_excc_amt': '1000000',       # 익일정산금액(D+1)
    'prvs_rcdl_excc_amt': '1765198',  # 가수도정산금액(D+2) — 매도대금 편입분
    'tot_evlu_amt': '2000396',        # 총평가금액
    'evlu_pfls_smtl_amt': '396',
}


def _balance(output2=None):
    payload = {'rt_cd': '0', 'output1': [], 'output2': [output2 or _OUTPUT2]}
    env = {'KIS_APP_KEY': 'k', 'KIS_APP_SECRET': 's', 'KIS_ACCOUNT_NO': '1234567890'}
    with mock.patch.dict(os.environ, env, clear=False), \
         mock.patch.object(balance_mod, 'get_access_token', return_value='tok'), \
         mock.patch.object(balance_mod, 'load_env', lambda: None), \
         mock.patch('requests.get', return_value=_Res(payload)):
        return balance_mod.get_balance()


def test_d2_deposit_is_exposed():
    """매도대금 D+2 편입분. 이게 안 보이면 단타 심의 예산이 판 만큼 깎인다."""
    assert _balance()['deposit_d2'] == 1765198


def test_d1_deposit_is_exposed():
    assert _balance()['deposit_d1'] == 1000000


def test_plain_deposit_is_unchanged():
    """클램프가 지금 쓰는 값. 동작을 바꾸지 않았다는 것을 고정한다."""
    assert _balance()['deposit'] == 1000000


def test_total_asset_still_comes_from_kis():
    assert _balance()['total_asset'] == 2000396


def test_missing_fields_are_none_not_zero():
    """모의계좌·구버전 응답에 필드가 없을 수 있다. 그때 0으로 채우면
    '이 응답엔 없다'와 '예수금이 0이다'가 합쳐진다 — 이 값들의 용도가
    "예산 상한을 올려도 되나"를 사람이 판단하는 것이라 그 혼동이 곧 오판이다."""
    out = _balance({'dnca_tot_amt': '500000', 'tot_evlu_amt': '500000'})

    assert out['deposit_d2'] is None
    assert out['deposit_d1'] is None
    assert out['deposit'] == 500000
