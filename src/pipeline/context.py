"""
[V50] 파이프라인 실행 컨텍스트 (PipelineContext)
=======================================================
파이프라인의 모든 Stage/Worker가 공유하는 실행 환경 객체입니다.
- 실행 시각(KST)을 시작 시점에 고정 → 재실행 시 시간 불일치 방지
- 텔레그램 발송 조건, 시간대별 임계값을 중앙 관리
- GitHub Actions 이벤트명으로 실행 컨텍스트 구분
"""

import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

# 이 비율을 넘는 페이지가 실패하면 그 런의 게시글 수는 실제보다 작다.
DEGRADED_PAGE_FAIL_RATIO = 0.10

# KRX 정규장 마감 (종가 단일가 종료)
MARKET_CLOSE_HHMM = (15, 30)


class PipelineContext:
    """
    파이프라인 실행에 필요한 모든 공유 상태를 담는 컨텍스트 객체.
    Worker 생성 시 주입됩니다 (의존성 주입 패턴).
    """
    VERSION = "50.0"

    def __init__(self):
        # 실행 시각을 생성 시점에 고정 (KST)
        self.now_kst: datetime = datetime.utcnow() + timedelta(hours=9)
        self.start_minute: int = self.now_kst.minute
        self.today_str: str = self.now_kst.strftime('%Y%m%d')
        self.today_display: str = self.now_kst.strftime('%Y.%m.%d')

        # GitHub Actions 이벤트명
        self.github_event: str = os.environ.get('GITHUB_EVENT_NAME', 'manual')

        # 시간대별 게시글 수 임계값
        self.threshold: int = self._calc_threshold()

        # 수집 건전성 (Stage 1이 채운다). 페이지 실패는 게시글 수를 조용히 깎는다.
        self.scrape_pages_total: int = 0
        self.scrape_pages_failed: int = 0

    def scrape_degraded(self) -> bool:
        """페이지 실패율이 기준을 넘으면 이번 런의 게시글 수를 믿을 수 없다."""
        if self.scrape_pages_total <= 0:
            return False
        return (self.scrape_pages_failed / self.scrape_pages_total) > DEGRADED_PAGE_FAIL_RATIO

    @classmethod
    def from_env(cls) -> 'PipelineContext':
        """환경변수를 로드하고 컨텍스트를 생성합니다."""
        ctx = cls()
        ctx._load_env()
        return ctx

    def _load_env(self) -> None:
        """우선순위에 따라 .env 파일을 로드합니다."""
        for filepath in [".env.production", ".env.final", ".env", ".env.local"]:
            if os.path.exists(filepath):
                try:
                    from dotenv import load_dotenv
                    load_dotenv(filepath)
                    if os.environ.get('GEMINI_KEY') or os.environ.get('GOOGLE_API_KEY'):
                        self.log(f"환경변수 로드: {filepath}")
                        break
                except Exception:
                    continue

    def _calc_threshold(self) -> int:
        """현재 시각(KST)에 따른 게시글 수 임계값을 반환합니다."""
        h = self.now_kst.hour
        if h < 9:   return 20
        elif h < 11: return 40
        elif h < 14: return 80
        elif h < 16: return 120
        return 130

    def is_trading_day(self):
        """오늘이 개장일인지 판정한다.

        True=개장, False=휴장, None=판정 불가.

        [주의] None은 개장이 아니다. 호출부는 fail-closed로 닫아야 한다.
        판정 실패를 True로 폴백하면 휴장일에 봇이 돈다 (2026-07-17 사고).

        판정 소스는 KIS chk-holiday 하나다. holidays 패키지는 신규 지정·
        임시공휴일을 모르므로(0.86이 2026-07-17을 놓쳤다) 쓰지 않는다.
        """
        if os.environ.get('FORCE_RUN', '').strip().lower() == 'true':
            self.log("[FORCE_RUN] 휴장일 게이트를 우회합니다.")
            return True

        if self.now_kst.weekday() >= 5:
            return False

        from src.market_calendar import load_calendar, lookup, refresh_calendar

        result = lookup(load_calendar(), self.today_str)
        if result is not None:
            return result

        # 달력에 오늘이 없다 (07시 갱신 런 실패 등) → 직접 조회
        self.log(f"[휴장 판정] 달력에 {self.today_str}이 없어 직접 조회합니다.")
        try:
            days = refresh_calendar(self.today_str)
        except Exception as e:
            self.log(f"[휴장 판정 실패] chk-holiday 조회 실패: {e}")
            return None

        result = lookup(days, self.today_str)
        if result is None:
            self.log(f"[휴장 판정 실패] 조회한 달력에 {self.today_str}이 없습니다.")
        else:
            self.log(f"[휴장 판정] {self.today_str} 개장={result}")
        return result

    def should_notify(self) -> bool:
        """
        텔레그램 발송 조건을 판단합니다. (정각 알림 강화)
        - push 이벤트: 발송하지 않음
        - 태스커 호출 시: 분 단위가 0~2분(정각)인 경우에만 발송
        - 그 외의 시간(15, 30, 45분 등)은 스크래퍼만 돌고 알림은 생략
        """
        if self.github_event == 'push':
            return False
            
        minute = self.start_minute
        
        # 정각(0~2분 부근)인 경우에만 리포트 발송 허용
        if 0 <= minute <= 2:
            return True
            
        # 그 외의 시간(스케줄된 15, 30, 45분 등)은 발송 생략
        return False

    def is_market_hours(self) -> bool:
        """장중 시간대(09:00~15:50)에 해당하는지 확인합니다.

        [주의] 실거래 게이트다 (trade_engine의 allow_buy, program_trader).
        장은 15:30에 닫지만 이 상한은 15:50이다. 마감 후 판정에는
        is_after_market_close()를 쓸 것 — 여기를 낮추면 매수 허용 시간대가 바뀐다.

        거래일 판정 불가(None)면 닫는다. 거래일인지 모르는 채로 매수하지 않는다.
        """
        return bool(
            self.is_trading_day() is True and
            9 <= self.now_kst.hour < 16 and
            not (self.now_kst.hour == 15 and self.now_kst.minute >= 50)
        )

    def is_buy_window(self) -> bool:
        """신규 매수가 허용되는 시간대(09:00~15:29)인지.

        `is_market_hours()`와 다르다. 그쪽 상한은 15:50이고 매도·기타 판단까지
        포괄하는데, **신규 매수는 정규장이 닫히는 15:30에 멈춰야 한다.**
        15:30 이후에 낸 지정가는 정규장에서 체결될 수 없고, 브로커가 익일로
        이월하면 신호를 다시 확인하지 않은 채 익일 시가에 사게 된다 —
        전략이 결정하지 않은 포지션이다. 태스커의 마지막 신호가 정확히 15:30이라
        실제로 그 창에 런이 하나 떨어진다.

        매도는 좁히지 않는다: 리스크를 줄이는 행동이고, 안 채워지면 아무 일도 없다.

        거래일 판정 불가(None)면 닫는다.
        """
        return bool(
            self.is_trading_day() is True and
            self.now_kst.hour >= 9 and
            (self.now_kst.hour, self.now_kst.minute) < MARKET_CLOSE_HHMM
        )

    def is_after_market_close(self) -> bool:
        """거래일의 장 마감(15:30) 이후인지 확인합니다.

        is_market_hours()와 15:30~15:49 구간이 겹친다. 둘을 함께 쓰는 곳은
        이쪽을 먼저 판정해야 한다.

        거래일 판정 불가(None)면 닫는다.
        """
        if self.now_kst.weekday() >= 5:
            return False
        if (self.now_kst.hour, self.now_kst.minute) < MARKET_CLOSE_HHMM:
            return False
        return self.is_trading_day() is True

    def log(self, msg: str) -> None:
        """타임스탬프가 포함된 로그를 출력합니다.

        now_kst(런 시작 시각으로 고정)가 아니라 실제 시계를 찍는다. 고정 시각을 찍으면
        한 런의 모든 줄이 같은 시각이 되어, 6~11분 걸리는 런에서 어느 단계가 시간을
        먹는지 알 수 없다. now_kst 자체는 그대로 둔다 — 날짜·거래일 판정이 한 런
        안에서 흔들리면 안 된다.
        """
        wall = datetime.utcnow() + timedelta(hours=9)
        print(f"[{wall.strftime('%H:%M:%S')}] {msg}")

    @contextmanager
    def stage(self, label: str):
        """단계 시작·종료를 소요와 함께 남긴다.

        예외로 죽어도 종료 줄을 남긴다 — 느려서 터진 것인지 즉시 터진 것인지
        구분해야 다음에 어디를 볼지 정할 수 있다.
        """
        t0 = time.monotonic()
        self.log(f"▶ {label}")
        try:
            yield
        finally:
            self.log(f"◀ {label} ({time.monotonic() - t0:.1f}초)")
