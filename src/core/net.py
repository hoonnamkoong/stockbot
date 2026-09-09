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

## 차단기는 스스로 풀린다

복구 경로가 없으면 차단기는 런을 끝장낸다. 열린 뒤에는 `request()`가 호출 전에
`None`을 주므로 `_STREAKS`를 리셋할 응답이 **영영 오지 않는다**. 2026-09-09 실측에서
네이버 게시글 수집 실패율이 같은 날 0.2% ↔ 69.5%로 널뛰었다(전부 ReadTimeout) —
버스트가 지나가면 다시 멀쩡한데, 복구가 없으면 10분짜리 버스트가 **런 전체의
수집 중단**이 된다. `recovery_sec`이 지나면 한 번 탐침을 보내고, 성공하면 닫고
실패하면 다시 그만큼 기다린다.

## 청산은 막지 않는다

`CRITICAL`은 차단기를 걸지 않는다(`breaker_streak=0`). "청산은 무조건 나가야
한다"가 이 레포의 규칙이고, 매도를 차단기가 막으면 리스크를 줄이는 행동이
봉쇄된다. 못 닿으면 어차피 실패하지만, **시도조차 안 하는 것과는 다르다.**

## 값을 지어내지 않는다

실패하면 `None`을 돌려준다. 호출부가 그걸 0이나 빈 값으로 접으면 "측정 못 함"이
"값이 0이다"로 위장된다 — 이 레포가 반복해서 당한 형태다.

## 계약은 호출부가 고른다 (`required=`)

`None`이 늘 옳지는 않다. 미국 EOD 배치는 `raise_for_status()`로 **예외를 올리는**
계약이고, 그 예외 객체가 곧 알림 본문이다:

    except Exception as e:
        alerts.send_alert(f'{type(e).__name__}: {e} ...'); raise

2026-08-24·25에 그 배치가 이틀 죽었는데 아무도 몰랐고, 그래서 저 알림이 붙었다.
`None`으로 통일하면 저 문자열이 사라지고 배치가 **빈 결과로 정상 종료**한다.

그래서 두 계약을 다 준다:
  - 값을 못 얻은 것을 **세는** 경로(스크래핑 페이지 등) → `None`
  - 못 얻으면 그 위가 통째로 무의미해지는 경로 → `required=True` → `NetError`

같은 함수 안에서도 갈린다. `us_ohlcv.fetch_daily_ohlcv`는 예외이고
`fetch_current_quote`는 None이다 — 전자는 그 종목을 판단할 수 없다는 뜻이고,
후자는 "지금 값을 모른다"이기 때문이다.
"""
import time
from dataclasses import dataclass

import requests

__all__ = ['Policy', 'NetError', 'FAST', 'BULK', 'SCRAPE', 'CRITICAL',
           'get', 'post', 'request']


class NetError(Exception):
    """못 닿았다. `required=True`일 때만 올라온다.

    문장에 **이유와 URL**을 담는다. 호출부의 알림이
    `f'{type(e).__name__}: {e}'`로 그대로 찍기 때문이다 — 이유가 없으면
    '실패했다'만 남아 429인지 소프트 차단인지 못 가린다.
    """

    def __init__(self, url: str, reason: str, *, status: int | None = None):
        self.url = url
        self.reason = reason
        self.status = status
        super().__init__(f'{reason} — {url}')


@dataclass(frozen=True)
class Policy:
    """호출 등급. 호출부는 숫자가 아니라 이 이름을 고른다."""
    name: str
    connect: float          # 연결은 빨리 포기한다
    read: float             # 응답은 기다린다
    attempts: int           # 연결 계열 실패에만 쓴다
    backoff: float
    breaker_streak: int     # 0이면 차단하지 않는다
    recovery_sec: float = 30.0   # 열린 뒤 이만큼 지나면 탐침을 한 번 보낸다

    def budget_sec(self) -> float:
        """이 정책이 한 호출에 태울 수 있는 최대 시간(대략). 예산 계산용."""
        waits = sum(self.backoff * (i + 1) for i in range(self.attempts - 1))
        return self.attempts * (self.connect + self.read) + waits


# 시세·지표처럼 **자주, 많이** 부르는 것. 여기가 곱해져서 사고가 났다.
FAST = Policy('FAST', connect=3, read=5, attempts=3, backoff=0.3, breaker_streak=3,
              recovery_sec=30)

# 스크래핑처럼 느려도 되지만 양이 많은 것. 실패가 쌓이면 빨리 포기하는 편이
# 낫다 — 어차피 하류에 '수집 실패율 초과 → 기록 안 함' 게이트가 있다.
# 스크래핑 실패는 버스트로 온다(2026-09-09: 0.2% ↔ 69.5%). 복구를 짧게 잡아
# 버스트가 지나간 뒤를 놓치지 않는다.
BULK = Policy('BULK', connect=3, read=8, attempts=2, backoff=0.5, breaker_streak=3,
              recovery_sec=20)

# 병렬 전수 스캔. BULK와 시간 예산은 같지만 **차단기를 걸지 않는다.**
#
# 2026-09-09 실측이 이유다. fetch_page를 BULK로 옮긴 첫 런에서:
#     페이지 수집 실패 348/395 (88.1%) — breaker_open 324, ReadTimeout 24
# 실제 타임아웃은 24건인데 324건이 차단기에 막혔고, 하류의 '수집 실패율 초과'
# 게이트가 그 런을 통째로 버렸다.
#
# 이유는 명확하다. `_STREAKS`는 프로세스 공유 상태인데 이 경로는 8스레드가 동시에
# 친다 — **동시에 진행 중인 실패 3건**이 "연속 3회 실패"로 읽힌다. 그건 장애
# 신호가 아니라 병렬성의 부산물이다. 게다가 한 번 열리면 recovery_sec 동안
# 8스레드가 쏟아내는 수백 건이 전부 즉시 실패한다.
#
# 이 경로의 "못 닿으면 그만둔다"는 차단기가 아니라 **청크 전멸 감지**가 이미
# 한다(2026-09-08, tests/test_scrape_failure_amplification.py). 두 겹이 필요 없고,
# 겹치면 병렬성 때문에 잘못 발동하는 쪽이 이긴다.
SCRAPE = Policy('SCRAPE', connect=3, read=8, attempts=2, backoff=0.5,
                breaker_streak=0)

# 주문·취소. 차단하지 않는다(위 독스트링 참고).
CRITICAL = Policy('CRITICAL', connect=5, read=10, attempts=3, backoff=0.5,
                  breaker_streak=0)


# 대상별 연속 소진 횟수. 프로세스 상태다 — 테스트는 conftest가 아니라
# 각 테스트 파일이 초기화한다(대상 키가 테스트마다 다르기 때문).
_STREAKS: dict[str, int] = {}

# 차단기가 열린 시각(monotonic). 벽시계를 쓰면 NTP 보정 한 번에 차단이
# 영구화되거나 즉시 풀린다.
_OPENED_AT: dict[str, float] = {}

_CONN_ERRORS = (requests.exceptions.Timeout, requests.exceptions.ConnectionError)


def _note(reasons, key):
    if reasons is not None:
        reasons[key] = reasons.get(key, 0) + 1


def _fail(url, reason, required, *, status=None):
    """실패를 호출부가 고른 계약으로 돌려준다."""
    if required:
        raise NetError(url, reason, status=status)
    return None


def request(method: str, url: str, *, policy: Policy = FAST,
            target: str | None = None, reasons: dict | None = None,
            session=None, required: bool = False, **kwargs):
    """정책에 따라 호출한다. 실패하면 None — 없는 값을 지어내지 않는다.

    required: True면 실패에 `NetError`를 올린다. 못 얻으면 그 위가 통째로
      무의미해지는 경로용이다(위 독스트링의 `required=` 절 참고). 성공 경로는
      두 계약이 완전히 같다.

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
        opened = _OPENED_AT.get(key)
        if opened is not None and time.monotonic() - opened < policy.recovery_sec:
            _note(reasons, 'breaker_open')
            return _fail(url, 'breaker_open', required)
        # 복구 시간이 지났다 — 탐침을 하나 내보낸다. 실패하면 아래에서
        # `_OPENED_AT`이 다시 찍혀 또 그만큼 기다린다.

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
            return _fail(url, type(e).__name__, required)

        # 응답이 왔다 = 닿았다. 상태코드가 무엇이든 차단기는 푼다 —
        # 차단기가 재는 것은 데이터 정합성이 아니라 **도달성**이다.
        _STREAKS[key] = 0
        _OPENED_AT.pop(key, None)
        if res.status_code == 200:
            return res
        # 서버가 대답한 실패는 재시도하지 않는다. 다시 던지면 유량제한만 키운다.
        _note(reasons, f'HTTP {res.status_code}')
        return _fail(url, f'HTTP {res.status_code}', required, status=res.status_code)

    _STREAKS[key] = _STREAKS.get(key, 0) + 1
    if policy.breaker_streak and _STREAKS[key] >= policy.breaker_streak:
        # 탐침이 실패한 경우도 여기다 — 시각을 다시 찍어 또 recovery_sec을 기다린다.
        # 안 찍으면 매 호출이 탐침이 되어 차단기가 없는 것과 같아진다.
        _OPENED_AT[key] = time.monotonic()
    reason = last_conn_reason or 'unknown'
    _note(reasons, reason)
    return _fail(url, reason, required)


def get(url: str, **kwargs):
    return request('GET', url, **kwargs)


def post(url: str, **kwargs):
    return request('POST', url, **kwargs)
