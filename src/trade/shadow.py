# -*- coding: utf-8 -*-
"""그림자 운전 — 계좌를 바꾸는 호출을 전부 막는다 (이관 3단계).

폰 워커가 옛 경로와 **같은 결정을 내리는지** 5거래일 확인하는 동안, 폰은
읽기만 해야 한다. 두 경로가 같은 계좌를 보고 있으므로 폰이 무엇이든 실행하면
그건 시험이 아니라 **중복 실행**이다.

## 막아야 하는 것은 주문만이 아니다

    place_order_via_vercel   /api/trade/order        신규 주문(매수·매도)
    cancel_order             KIS order-rvsecncl      미체결 취소  ← Vercel 우회

취소가 더 위험하다. 폰이 보는 미체결은 **옛 경로가 낸 진짜 주문**이라,
폰이 취소하면 살아 있는 매매를 방해한다. 주문은 안 나가면 그만이지만 취소는
남의 것을 거둔다.

## 왜 runner가 모드를 정하는가

`SHADOW_MODE=1`을 폰에서 빠뜨리면 주문이 나간다. 그 실수의 대가가 돈이므로
환경변수 하나에 걸지 않는다 — **`STOCKBOT_RUNNER=phone`이면 무조건 그림자다.**
3단계 내내 폰은 주문 권한이 없다는 사실을 코드가 갖는다.

4단계(소유권 이전)에서 폰을 승격할 때 `_SHADOW_RUNNERS`에서 'phone'을 빼는
것이 그 결정의 유일한 지점이다. 한 줄이고, 리뷰에서 보인다.

## 층이 둘인 이유

층1이 이 파일이고, 층2는 **폰에 `WEBHOOK_SECRET`을 주지 않는 것**이다.
층1만 두면 플래그 하나 실수로 실주문이 나가고, 층2만 두면 취소 경로(KIS 직접)가
그대로 열린다 — 폰은 조회를 위해 KIS 자격증명을 갖기 때문이다.
"""
import os

# 이 runner로 도는 프로세스는 환경변수와 무관하게 그림자다.
# **4단계에서 'phone'을 빼는 것이 승격 결정 그 자체다.**
_SHADOW_RUNNERS = frozenset({'phone'})


def is_shadow(runner: str | None = None) -> bool:
    """계좌를 바꾸는 호출을 막아야 하는가."""
    if (os.environ.get('SHADOW_MODE') or '').strip() == '1':
        return True
    if runner is None:
        from src.data.decision_log import runner_name
        runner = runner_name()
    return runner in _SHADOW_RUNNERS


def refused(action: str, detail: str = '', log=print) -> None:
    """막았다는 사실을 남긴다.

    **조용히 막으면 안 된다.** 그림자 운전의 판정은 "폰이 무엇을 하려 했나"를
    보는 것이고, 시도 자체가 기록되지 않으면 '결정이 없었다'와 구분되지 않는다.
    """
    log(f'[Shadow] 차단: {action}' + (f' — {detail}' if detail else ''))


def blocked_order_result(side: str, code: str) -> dict:
    """`place_order_via_vercel`이 그림자에서 돌려줄 값.

    호출부는 `res.get('success')`로 판단한다. 예외를 던지면 상위의 except가
    '주문 실패'로 알림을 보내 5일 내내 텔레그램이 울린다 — 차단은 장애가 아니다.
    """
    return {'success': False, 'shadow': True,
            'message': f'그림자 운전 — {side} {code} 주문을 내보내지 않았습니다'}
