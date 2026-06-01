"""
[V50] 파이프라인 실행 컨텍스트 (PipelineContext)
=======================================================
파이프라인의 모든 Stage/Worker가 공유하는 실행 환경 객체입니다.
- 실행 시각(KST)을 시작 시점에 고정 → 재실행 시 시간 불일치 방지
- 텔레그램 발송 조건, 시간대별 임계값을 중앙 관리
- GitHub Actions 이벤트명으로 실행 컨텍스트 구분
"""

import os
from datetime import datetime, timedelta


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

    def is_trading_day(self) -> bool:
        """오늘이 거래일인지 확인합니다 (KIS API 우선, holidays 패키지 폴백)."""
        if self.now_kst.weekday() >= 5:
            return False

        # KIS API로 거래일 확인 (1차)
        try:
            result = self._check_trading_day_via_kis()
            if result is not None:
                if not result:
                    self.log(f"[KIS API] 오늘({self.today_display})은 비거래일입니다.")
                return result
        except Exception as e:
            self.log(f"[경고] KIS API 거래일 확인 실패, holidays 폴백: {e}")

        # holidays 패키지로 공휴일 확인 (폴백)
        try:
            import holidays
            if self.now_kst.strftime('%Y-%m-%d') in holidays.KR():
                self.log(f"[공휴일] 달력상 법정 공휴일입니다: {self.now_kst.strftime('%Y-%m-%d')}")
                return False
        except Exception as e:
            self.log(f"[경고] holidays 패키지 확인 실패: {e}")

        return True

    def _check_trading_day_via_kis(self):
        """KIS chk-holiday API로 오늘이 거래일인지 확인합니다. 실패 시 None 반환."""
        import json
        import requests

        app_key = os.environ.get('KIS_APP_KEY', '').strip()
        app_secret = os.environ.get('KIS_APP_SECRET', '').strip()
        if not app_key or not app_secret:
            return None

        # token_manager.py가 사전에 실행되어 캐시를 보장함
        token_path = 'data/kis_token_cache.json'
        try:
            with open(token_path, 'r', encoding='utf-8') as f:
                access_token = json.load(f).get('access_token')
        except Exception:
            return None
        if not access_token:
            return None

        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/chk-holiday"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {access_token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": "CTCA0903R",
            "custtype": "P",
        }
        params = {"BASS_DT": self.today_str, "CTX_AREA_NK": "", "CTX_AREA_FK": ""}

        res = requests.get(url, headers=headers, params=params, timeout=5)
        data = res.json()

        if data.get('rt_cd') != '0':
            self.log(f"[KIS API] chk-holiday 오류: {data.get('msg1', '')}")
            return None

        output = data.get('output', [])
        entry = next((x for x in output if x.get('bass_dt') == self.today_str), output[0] if output else None)
        if not entry:
            return None

        bzdy_tp_cd = entry.get('bzdy_tp_cd', '')
        self.log(f"[KIS API] 거래일 조회: {self.today_str} bzdy_tp_cd={bzdy_tp_cd}")
        if bzdy_tp_cd:
            return bzdy_tp_cd == '1'
        tr_day_yn = entry.get('tr_day_yn', '')
        if tr_day_yn:
            return tr_day_yn == 'Y'
        return None

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
        """장중 시간대(09:00~15:50)에 해당하는지 확인합니다."""
        return (
            self.is_trading_day() and
            9 <= self.now_kst.hour < 16 and
            not (self.now_kst.hour == 15 and self.now_kst.minute >= 50)
        )

    def log(self, msg: str) -> None:
        """타임스탬프가 포함된 로그를 출력합니다."""
        print(f"[{self.now_kst.strftime('%H:%M:%S')}] {msg}")
