# -*- coding: utf-8 -*-
"""외부 호출 정책의 유일한 원천.

## 왜 생겼나 (2026-09-08 실측)

`requests.get/post` 호출이 **46곳**이고 타임아웃이 **7종**이었다
(3·5·6·8·10·15·20초). connect와 read를 나눈 곳은 1곳, 차단기가 있는 곳도 1곳뿐.

그날 아침 실전매매 런 넷이 잡 타임아웃에 잘렸는데, **어느 한 호출도 틀리지
않았다:**

    한 호출의 재시도 예산 = 3 + 0.3 + 3 + 0.6 + 3 = 9.9초   (합리적)
    5종목                 = 49.5초                          (실측 50.0초)
    구간 3개              = 132초                           (잡 예산 180초)

각자 맞는 값이 **곱해져서** 터졌다. 그래서 곱셈을 막는 일은 호출부가 아니라
여기서 한다 — 호출부는 숫자가 아니라 **등급**만 고른다.

## 차단기는 대상별이다

`KISDataProvider._conn_fail_streak`(같은 날 넣은 것)는 클래스 레벨이라 대상
구분이 없다. 네이버가 죽어도 그 차단기는 모르고, 반대도 마찬가지다.
여기서는 `target`별로 나눠 한 서비스의 장애가 다른 서비스를 막지 않게 한다.

## 청산은 막지 않는다

`CRITICAL`은 차단기를 걸지 않는다(`breaker_streak=0`). "청산은 무조건 나가야
한다"가 이 레포의 규칙이고, 매도를 차단기가 막으면 리스크를 줄이는 행동이
봉쇄된다. 못 닿으면 어차피 실패하지만, **시도조차 안 하는 것과는 다르다.**

## 값을 지어내지 않는다

실패하면 `None`을 돌려준다. 호출부가 그걸 0이나 빈 값으로 접으면 "측정 못 함"이
"값이 0이다"로 위장된다 — 이 레포가 반복해서 당한 형태다.
"""
import time
from dataclasses import dataclass

import requests

__all__ = ['Policy', 'FAST', 'BULK', 'CRITICAL', 'get', 'post', 'request']


@dataclass(frozen=True)
class Policy:
    """호출 등급. 호출부는 숫자가 아니라 이 이름을 고른다."""
    name: str
    connect: float          # 연결은 빨리 포기한다
    read: float             # 응답은 기다린다
    attempts: int           # 연결 계열 실패에만 쓴다
    backoff: float
    breaker_streak: int     # 0이면 차단하지 않는다

    def budget_sec(self) -> float:
        """이 정책이 한 호출에 태울 수 있는 최대 시간(대략). 예산 계산용."""
        waits = sum(self.backoff * (i + 1) for i in range(self.attempts - 1))
        return self.attempts * (self.connect + self.read) + waits


# 시세·지표처럼 **자주, 많이** 부르는 것. 여기가 곱해져서 사고가 났다.
FAST = Policy('FAST', connect=3, read=5, attempts=3, backoff=0.3, breaker_streak=3)

# 스크래핑처럼 느려도 되지만 양이 많은 것. 실패가 쌓이면 빨리 포기하는 편이
# 낫다 — 어차피 하류에 '수집 실패율 초과 → 기록 안 함' 게이트가 있다.
BULK = Policy('BULK', connect=3, read=8, attempts=2, backoff=0.5, breaker_streak=3)

# 주문·취소. 차단하지 않는다(위 독스트링 참고).
CRITICAL = Policy('CRITICAL', connect=5, read=10, attempts=3, backoff=0.5,
                  breaker_streak=0)


# 대상별 연속 소진 횟수. 프로세스 상태다 — 테스트는 conftest가 아니라
# 각 테스트 파일이 초기화한다(대상 키가 테스트마다 다르기 때문).
_STREAKS: dict[str, int] = {}

_CONN_ERRORS = (requests.exceptions.Timeout, requests.exceptions.ConnectionError)


def _note(reasons, key):
    if reasons is not None:
        reasons[key] = reasons.get(key, 0) + 1


def request(method: str, url: str, *, policy: Policy = FAST,
            target: str | None = None, reasons: dict | None = None,
            session=None, **kwargs):
    """정책에 따라 호출한다. 실패하면 None — 없는 값을 지어내지 않는다.

    target: 차단기를 나누는 키(보통 서비스 이름). 없으면 URL의 호스트를 쓴다.
    reasons: 주면 실패 이유별 건수를 담는다. 429인지 리셋인지 타임아웃인지는
      대응이 전혀 다른데, 세지 않으면 로그에 횟수만 남는다.
    session: `requests.Session`. 같은 호스트를 연달아 칠 때 연결을 재사용한다 —
      스크래핑처럼 종목당 수십 페이지를 긁는 경로는 이게 없으면 매번 TLS
      핸드셰이크를 새로 한다. **스레드 안전이 아니므로** 스레드마다 하나씩
      만들어 넘길 것.
    """
    key = target or url.split('/')[2] if '//' in url else (target or url)

    if policy.breaker_streak and _STREAKS.get(key, 0) >= policy.breaker_streak:
        _note(reasons, 'breaker_open')
        return None

    kwargs.setdefault('timeout', (policy.connect, policy.read))
    last_conn_reason = None

    caller = session if session is not None else requests
    for attempt in range(policy.attempts):
        try:
            res = caller.get(url, **kwargs) if method == 'GET' \
                else caller.request(method, url, **kwargs)
        except _CONN_ERRORS as e:
            last_conn_reason = type(e).__name__
            if attempt + 1 < policy.attempts:
                time.sleep(policy.backoff * (attempt + 1))
                continue
            break
        except Exception as e:                      # noqa: BLE001
            _note(reasons, type(e).__name__)
            return None

        # 응답이 왔다 = 닿았다. 상태코드가 무엇이든 차단기는 푼다 —
        # 차단기가 재는 것은 데이터 정합성이 아니라 **도달성**이다.
        _STREAKS[key] = 0
        if res.status_code == 200:
            return res
        # 서버가 대답한 실패는 재시도하지 않는다. 다시 던지면 유량제한만 키운다.
        _note(reasons, f'HTTP {res.status_code}')
        return None

    _STREAKS[key] = _STREAKS.get(key, 0) + 1
    _note(reasons, last_conn_reason or 'unknown')
    return None


def get(url: str, **kwargs):
    return request('GET', url, **kwargs)


def post(url: str, **kwargs):
    return request('POST', url, **kwargs)
