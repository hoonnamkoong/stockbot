"""
[V50] StockBot 공유 데이터 스키마 (Pydantic 기반)
=======================================================
이 파일이 시스템 전체의 '데이터 헌법'입니다.
- Python 백엔드 ↔ TypeScript 프론트엔드 간 스키마를 단일 파일로 관리합니다.
- 크롤링된 원시 데이터(문자열, None 등)를 파이프라인 진입 시점에 즉시 정제합니다.
- 스키마 변경이 필요하면 오직 이 파일만 수정합니다.
"""

from pydantic import BaseModel, field_validator, model_validator
from typing import Optional, ClassVar
from enum import Enum


class MarketType(str, Enum):
    """한국 주식 시장 구분"""
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"
    UNKNOWN = "UNKNOWN"


class StockData(BaseModel):
    """
    네이버 금융 크롤링 결과 + 수급 데이터의 통합 스키마.
    파이프라인 진입 즉시 이 객체로 변환되어 타입 안전성을 보장합니다.
    
    TypeScript 대응:
        interface StockData {
            code: string; name: string; market: string;
            price: number; recent_posts_count: number;
            foreign_rate: number; foreign_change: number;
            posts_summary: string; signal?: string;
        }
    """
    code: str
    name: str
    market: MarketType = MarketType.UNKNOWN
    price: int = 0
    recent_posts_count: int = 0
    foreign_rate: float = 0.0
    foreign_change: float = 0.0
    inst_net_buy: int = 0
    prev_close: int = 0
    prev_foreign_rate: float = 0.0
    posts_summary: str = "분석 대기중"
    sentiment: str = "Neutral"
    top_keywords: list = []
    consecutive_days: int = 1
    change_rate: str = ""       # "±X.XX%" 형식
    signal: Optional[str] = None
    current_price: int = 0  # price의 별칭 (호환성 유지)
    volume: int = 0         # [V50.2] 당일 거래량
    amount: int = 0         # [V50.2] 당일 거래대금 (원 단위)
    posts: list = []  # 상세 게시글 목록
    sparkline_price: list = []  # [V50.3] 최근 N일 종가 (과거->최신순)
    tick_power: float = 0.0     # [V60.0] 체결강도 (%)
    bid_ask_ratio: float = 1.0  # [V60.0] 매도호가잔량 / 매수호가잔량 비

    @field_validator('price', 'prev_close', 'current_price', 'volume', 'amount', mode='before')
    @classmethod
    def parse_int_field(cls, v):
        """'50,000원', '5만' 같은 문자열을 정수로 자동 정제합니다."""
        if v is None:
            return 0
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str):
            v = v.replace(',', '').replace('원', '').replace('만', '0000').strip()
            try:
                return int(float(v))
            except (ValueError, TypeError):
                return 0
        return 0

    @field_validator('foreign_rate', 'foreign_change', 'prev_foreign_rate', mode='before')
    @classmethod
    def parse_float_field(cls, v):
        """'3.25%' 같은 문자열을 실수로 자동 정제합니다."""
        if v is None:
            return 0.0
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            v = v.replace('%', '').replace(',', '').strip()
            try:
                return float(v)
            except (ValueError, TypeError):
                return 0.0
        return 0.0

    @field_validator('recent_posts_count', mode='before')
    @classmethod
    def parse_post_count(cls, v):
        """게시글 수를 정수로 정제합니다."""
        try:
            return int(str(v).replace(',', ''))
        except (ValueError, TypeError):
            return 0

    @model_validator(mode='after')
    def sync_price_fields(self):
        """price와 current_price를 상호 동기화합니다."""
        if self.price == 0 and self.current_price != 0:
            self.price = self.current_price
        elif self.current_price == 0 and self.price != 0:
            self.current_price = self.price
        return self

    @classmethod
    def from_dict(cls, d: dict) -> 'StockData':
        """기존 dict 기반 코드와의 호환성을 위한 팩토리 메서드.
        - keywords → top_keywords 자동 매핑
        - change_rate 문자열 보정 (숫자면 문자열로 변환)
        """
        # keywords 필드 호환 처리
        data = dict(d)
        if 'keywords' in data and 'top_keywords' not in data:
            data['top_keywords'] = data.pop('keywords', [])
        # change_rate 숫자→문자열 변환
        if 'change_rate' in data and isinstance(data['change_rate'], (int, float)):
            v = data['change_rate']
            data['change_rate'] = f"+{v:.2f}%" if v >= 0 else f"{v:.2f}%"
        # current_price / price 동기화
        if 'current_price' not in data and 'price' in data:
            data['current_price'] = data['price']
        return cls(**{k: v for k, v in data.items() if k in cls.model_fields})

    def to_dict(self) -> dict:
        """기존 코드와의 호환성을 위한 dict 변환"""
        return self.model_dump()


class TradeRecord(BaseModel):
    """
    매매 기록 스키마. CSV/Excel 컬럼 순서와 1:1 대응합니다.
    ROI 컬럼 추가 등 스키마 변경 시 이 클래스만 수정하면
    CSV·Excel·API 응답이 모두 자동으로 일치합니다.
    
    CSV 컬럼: timestamp, symbol, action, price, quantity, total_amount, roi, reason
    """
    timestamp: str
    symbol: str
    action: str          # 'BUY' | 'SELL'
    price: int
    quantity: int
    total_amount: int
    roi: Optional[float] = None
    reason: str = ""

    @field_validator('price', 'quantity', 'total_amount', mode='before')
    @classmethod
    def parse_numeric(cls, v):
        if isinstance(v, str):
            v = v.replace(',', '').replace('%', '').strip()
            try:
                return int(float(v))
            except (ValueError, TypeError):
                return 0
        return int(v) if v else 0

    def to_csv_row(self) -> dict:
        """
        CSV 저장용 딕셔너리를 반환합니다.
        숫자 포맷(쉼표 구분), ROI 퍼센트 표기 등을 적용합니다.
        """
        return {
            'timestamp': self.timestamp,
            'symbol': self.symbol,
            'action': self.action,
            'price': f"{self.price:,}",
            'quantity': self.quantity,
            'total_amount': f"{self.total_amount:,}",
            'roi': f"{self.roi:.2f}%" if self.roi is not None else "",
            'reason': self.reason
        }

    # CSV 컬럼 순서 (헤더 생성 시 사용) — ClassVar로 선언하여 Pydantic 필드에서 제외
    CSV_COLUMNS: ClassVar[list] = ['timestamp', 'symbol', 'action', 'price', 'quantity', 'total_amount', 'roi', 'reason']


class SyncState(BaseModel):
    """
    매일 초기화되는 Telegram 중복 방지 상태.
    sync_state.json의 스키마입니다.
    """
    last_update_date: str = ""        # 상태 파일이 마지막으로 업데이트된 날짜 (YYYY-MM-DD)
    market_index_healthy: bool = True # [V60.0] 시장 지수 건강 상태
    stocks: dict = {}                 # [Legacy] 종목별 연속일수 등 보관
    reported_codes: list = []         # [Legacy] 전체 기간 중 보고된 적 있는 종목 코드 리스트
    daily_reported_info: list = []    # 당일 텔레그램으로 보고된 전체 종목 리스트 (rank 포함)
    daily_deep_dive_codes: list = []  # 당일 상세 리포트(Deep-Dive)가 발송된 종목 코드 (중복 발송 방지용)
    morning_reported_info: list = []  # 오전 세션(12시 이전) 텔레그램 보고 종목 (최대 9개)
    afternoon_reported_info: list = [] # 오후 세션(12시 이후) 텔레그램 보고 종목 (최대 9개)
    morning_complete: bool = False    # 오전 세션 리포팅 완료 여부
    afternoon_complete: bool = False  # 오후 세션 리포팅 완료 여부
    daily_complete: bool = False      # [Legacy] 전체 완료 여부 (호환성 유지)


class ReportEntry(BaseModel):
    """
    reports.json 목록의 개별 항목 스키마.
    UI의 리서치 리포트 목록에 표시됩니다.
    """
    type: str = "research"
    title: str
    date: str
    filename: str
    month: Optional[str] = None      # YYYY-MM 형식 (월별 그룹화용)
    timestamp: Optional[float] = None
