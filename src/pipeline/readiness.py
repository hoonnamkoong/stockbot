"""실전 매매 준비상태 — "지금 주문을 낼 수 있는 상태인가".

================================================================
왜 필요한가
================================================================
2026-09-01 장중 실전 매매가 0건이었다. 원인은 결국 "조건 미달"이었지만, 그걸
알아내는 데 로그를 뒤지고 코드를 읽어야 했다. **"안 살 이유가 있었다"와
"살 수 없는 상태였다"가 밖에서 똑같이 생겼기 때문이다.**

둘은 완전히 다른 사건이다.
  - 조건 미달   → 전략 문제. 오늘은 기다리는 게 맞을 수도 있다.
  - 배선 고장   → 사고. 토큰이 죽었거나 유니버스가 비었거나 락이 안 풀린다.

이 모듈은 **주문을 내지 않고** 후자만 본다. 개장 직후 한 번 돌려서 "쏠 수는
있는 상태"임을 확인해두면, 그날 0건이 나와도 전략 문제로 좁혀진다.

================================================================
여기서 하지 않는 것
================================================================
  - **주문.** 한 건도 내지 않는다. 읽기 전용이다.
  - **전략 판단.** 살 종목이 있는지는 보지 않는다. 그건 깔때기 로그의 몫이다.
  - **숫자 만들기.** 조회에 실패하면 실패로 적는다. 0이나 빈 목록으로
    폴백하면 "죽은 상태"가 "정상인데 비어 있음"으로 보인다.
"""


def evaluate(checks: dict) -> tuple:
    """(준비됨, 요약문). checks는 이름 → (통과여부, 상세) 이다.

    순수 함수 — I/O 없음. 호출자가 실제 조회를 하고 결과만 넘긴다. 그래야
    네트워크 없이 판정 로직을 테스트할 수 있다(이 레포의 게이트 모듈들과 같은
    방식이다).

    **`None`은 실패로 센다.** 확인하지 못한 것을 통과로 치면 이 점검이
    "항상 초록"이 되어 없느니만 못해진다.
    """
    failed = [name for name, (ok, _) in checks.items() if ok is not True]
    if not failed:
        return True, '실전 매매 준비 완료 — ' + ', '.join(checks)

    lines = ['<b>실전 매매 준비 실패</b>', '',
             '주문을 낼 수 없는 상태입니다. 오늘 매매가 0건이면 전략이 아니라 배선 문제입니다.', '']
    for name, (ok, detail) in checks.items():
        mark = '✅' if ok is True else ('❓' if ok is None else '❌')
        lines.append(f'  {mark} {name}: {detail}')
    return False, '\n'.join(lines)


def collect(log=print, budget_sec: float = 20.0) -> dict:
    """실제 조회. 각 항목은 (통과여부, 상세) — 확인 불가는 `None`이다.

    항목 하나가 예외를 내도 나머지는 계속 본다. 첫 실패에서 멈추면 "토큰이
    죽었다"만 알고 "유니버스도 비었다"는 못 본다 — 사고는 겹쳐서 온다.
    """
    import time
    checks = {}
    started = time.monotonic()

    def _run(name, fn):
        # 예산을 넘기면 남은 항목은 '확인 못 함'으로 남긴다. 이 점검은 매매
        # 뒤에 돌지만, 잡 타임아웃(3분)을 넘기면 `Deploy state`가 통째로 스킵돼
        # 심 상태와 알림 쿨다운 기록까지 날아간다 — 감시가 사고가 되는 자리다.
        if time.monotonic() - started > budget_sec:
            checks[name] = (None, f'시간 예산({budget_sec:.0f}초) 초과로 건너뜀')
            return
        try:
            checks[name] = fn()
        except Exception as e:
            checks[name] = (None, f'점검 실패: {type(e).__name__}: {e}')

    def _token():
        from src.trade.auth import get_access_token
        tok = get_access_token()
        return (bool(tok), '유효' if tok else '발급 실패')

    def _balance():
        from src.trade.balance import get_balance
        b = get_balance()
        if b.get('error'):
            return (False, b['error'])
        dep = b.get('deposit')
        if dep is None:
            # `b.get('deposit', 0)`으로 찍으면 "필드가 없다"가 "예수금 0원"으로
            # 보인다. 조회는 성공했는데 응답 형태가 바뀐 경우이고, 그건 정상이
            # 아니다 — 이 레포가 금지하는 0 폴백이다.
            return (None, '조회는 됐으나 예수금 필드가 없다(응답 형태 변경?)')
        return (True, f'예수금 {round(dep):,}원')

    def _universe():
        from src.strategy.simulators.sim3_risk import SmartRiskSimulator
        u = SmartRiskSimulator().get_universe()
        if u is None:
            return (None, '조회 실패(유니버스를 못 받았다)')
        return (len(u) > 0, f'{len(u)}종목')

    _run('KIS 토큰', _token)
    _run('계좌 조회', _balance)
    _run('실전 심 유니버스', _universe)
    return checks
