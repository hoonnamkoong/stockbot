"""09:00 KST 미국장 마감 브리핑 조립.

국내 브리핑(daily_brief.py)과 형태를 맞추되 **실계좌 블록이 없다** — 미국 심은
전부 페이퍼다. 심 목록은 us_strategy_manifest에서 파생한다. 자체 목록을 갖지
않는다: 손으로 적어두면 새 심이 조용히 빠진다(daily_brief가 같은 이유로
매니페스트 파생이다).
"""
import csv
import json
import os
from datetime import datetime, timedelta

from src.strategy.us_registry import get_us_sim_registry

_WEEKDAY_KR = '월화수목금토일'

# 미국장은 22:30~05:00 KST(서머타임 기준)다. 창을 22:00~09:00으로 넉넉히 잡아
# 서머타임 전환(23:30~06:00)에도 세션 전체가 들어오게 한다. 이 창에는 국내장이
# 없으므로 국내 거래를 잘못 셀 위험이 없다.
_WINDOW_START_HHMM = '22:00'
_WINDOW_END_HHMM = '09:00'


def _signed_pct(v) -> str:
    return f"{'+' if v >= 0 else ''}{v:.2f}%"


def overnight_window(now_kst: datetime) -> tuple[str, str]:
    """간밤 미국 세션의 (시작, 끝) — 'YYYY-MM-DD HH:MM' 두 개.

    미국 거래이력의 timestamp는 KST다(2026-08-31 22:31:41 = 개장 직후).

    창 시작은 **직전 평일 22:00**이다(주말이면 금요일까지 되돌아간다). 전일
    22:00으로 잡으면 두 곳에서 틀린다:
      (a) 금요일 밤 세션(금 22:30~토 05:00 KST)은 토요일 09:00에 보고돼야 하는데
          trading.yml이 kr_session_open으로 게이트해 토요일엔 런이 아예 없다 —
          **매주 통째로 유실된다.**
      (b) 월요일 09:00의 창(일 22:00~월 09:00)에는 미국 세션이 하나도 없어서
          세 심 모두 '0종목'을 찍는다. 그건 '거래가 없었다'가 아니라 '세션이
          없었다'인데 같은 0으로 뭉개진다 — 이 레포가 금지하는 조작이다.
    월요일 창은 금 22:00~월 09:00이 되고 화~금은 종전과 같다. 평일만 세는
    규칙은 us_calendar.next_us_trading_date와 동일하다.

    **미국 공휴일은 판정하지 않는다** — 이 레포에 미국 휴장 달력이 없고, 없는
    달력을 지어내지 않는다. 대신 브리핑 본문에 이 구간을 그대로 찍어서 독자가
    '세션 없음'과 '거래 없음'을 직접 가를 수 있게 한다(build_us_brief).
    """
    start = now_kst - timedelta(days=1)
    while start.weekday() >= 5:  # 토(5)·일(6)
        start -= timedelta(days=1)
    return (f"{start.strftime('%Y-%m-%d')} {_WINDOW_START_HHMM}",
            f"{now_kst.strftime('%Y-%m-%d')} {_WINDOW_END_HHMM}")


def _profit_rate_from_state(path: str):
    """대시보드와 같은 식으로 수익률을 계산한다. 모르면 None(0.0이 아니다)."""
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            state = json.load(f)
        initial_cash = state.get('initial_cash')
        if not initial_cash or initial_cash <= 0:
            return None
        current_prices = (state.get('raw_stats') or {}).get('current_prices') or {}
        portfolio_value = 0
        for code, item in (state.get('portfolio') or {}).items():
            price = (current_prices.get(code) or item.get('current_price')
                     or item.get('avg_price') or 0)
            qty = item.get('quantity') or item.get('qty') or 0
            portfolio_value += price * qty
        total = (state.get('cash') or 0) + portfolio_value
        return (total - initial_cash) / initial_cash * 100
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"[USBrief] 상태 파일 읽기 실패: {path} — {type(e).__name__}: {e}")
        return None


def _count_tickers(path: str, since: str, until: str) -> int:
    """창 안에서 매매한 종목 수(중복 제거). 파일이 없으면 거래가 없었다는 뜻이라 0."""
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return len({
                row['symbol'] for row in csv.DictReader(f)
                if row.get('symbol') and since <= (row.get('timestamp') or '') < until
            })
    except FileNotFoundError:
        return 0
    except Exception as e:
        print(f"[USBrief] 거래이력 읽기 실패: {path} — {type(e).__name__}: {e}")
        return 0


def collect_us_sim_brief(data_dir: str, now_kst: datetime) -> list[dict]:
    """미국 심별 (표시명, 누적 수익률, 간밤 거래 종목 수)."""
    since, until = overnight_window(now_kst)
    return [
        {
            'label': s['label'],
            'profit_rate': _profit_rate_from_state(
                os.path.join(data_dir, s['state_file'])),
            'ticker_count': _count_tickers(
                os.path.join(data_dir, s['csv_file']), since, until),
        }
        for s in get_us_sim_registry()
    ]


def build_us_brief(sims: list[dict], now_kst: datetime) -> str:
    """마감 브리핑 본문. 순수 함수 — I/O 없음."""
    day = f"{now_kst.strftime('%m/%d')} ({_WEEKDAY_KR[now_kst.weekday()]})"
    # 커버 구간을 본문에 적는다. 미국 공휴일 달력이 없어 휴장일에는 여전히
    # '0종목'이 찍히는데, 구간이 같이 보이면 독자가 '세션이 없었다'와
    # '거래가 없었다'를 가를 수 있다. 없는 달력을 지어내는 것보다 정직하다.
    since, until = overnight_window(now_kst)
    lines = [f"🇺🇸 미국장 마감 브리핑  {day}", '',
             f"🕒 대상 구간 {since} ~ {until} (KST)", '',
             '🤖 US 심별 현황 (누적 수익률 / 간밤 거래)']
    for s in sims:
        rate = s.get('profit_rate')
        rate_str = '측정 불가' if rate is None else _signed_pct(rate)
        lines.append(f"  {s['label']:<28} {rate_str:>9}   {s.get('ticker_count', 0)}종목")
    return '\n'.join(lines)
