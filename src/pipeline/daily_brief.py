"""15:00 마감 브리핑 메시지 조립.

계산식은 대시보드(TradeClient.tsx renderRealPortfolioSection)와 동일하다.
텔레그램과 웹이 다른 수를 말하면 둘 다 못 믿게 된다.
"""

import csv
import json
import os
from datetime import datetime

from src.strategy.registry import get_sim_registry

_WEEKDAY_KR = '월화수목금토일'


def _won(v) -> str:
    return f"{round(v):,}원"


def _signed_won(v) -> str:
    v = round(v)
    return f"{'+' if v >= 0 else ''}{v:,}원"


def _signed_pct(v) -> str:
    return f"{'+' if v >= 0 else ''}{v:.2f}%"


def _account_block(balance: dict) -> list[str]:
    """실전 계좌 블록. 조회 실패면 숫자를 만들지 않고 실패를 적는다."""
    if balance.get('error'):
        return ['⚠️ 실전 계좌: 조회 실패', f"  {balance['error']}"]

    holdings = [h for h in (balance.get('holdings') or []) if int(h.get('qty', 0)) > 0]
    total_eval = sum(h.get('current_price', 0) * h.get('qty', 0) for h in holdings)
    total_pl = sum(h.get('pl_amount', 0) for h in holdings)
    cost = total_eval - total_pl   # 매입원가

    rate = _signed_pct(total_pl / cost * 100) if cost > 0 else '—'

    return [
        '💼 실전 계좌 (KIS)',
        f"  예수금          {_won(balance.get('deposit', 0))}",
        f"  보유 종목 총액   {_won(total_eval)}",
        f"  총 평가손익      {_signed_won(total_pl)}",
        f"  총 자산수익률    {rate}",
    ]


def _sim_block(sims: list[dict]) -> list[str]:
    lines = ['🤖 심별 현황 (수익률 / 금일 거래)']
    for s in sims:
        rate = s.get('profit_rate')
        rate_str = '측정 불가' if rate is None else _signed_pct(rate)
        lines.append(f"  {s['label']:<20} {rate_str:>9}   {s.get('ticker_count', 0)}종목")
    return lines


def build_daily_brief(balance: dict, sims: list[dict], now_kst: datetime) -> str:
    """마감 브리핑 본문. 순수 함수 — I/O 없음."""
    day = f"{now_kst.strftime('%m/%d')} ({_WEEKDAY_KR[now_kst.weekday()]})"
    parts = [f"📅 15:00 마감 브리핑  {day}", '']
    parts += _account_block(balance)
    parts += ['']
    parts += _sim_block(sims)
    return '\n'.join(parts)


# (표시명, 상태 파일, 거래이력 CSV) — 매니페스트에서 파생한다. 자체 목록을 갖지 않는다.
# 예전에는 여기에 손으로 적어뒀는데 2026-07-28에 추가한 심8·심9·심9-1이 등록되지
# 않아 브리프에서 조용히 빠져 있었다. 이제 심을 추가하면 매니페스트만 고치면 된다.
SIM_BRIEF_TARGETS = [
    (s['label'], s['state_file'], s['csv_file'])
    for s in get_sim_registry()  # 리베로(analyzer)는 매매하지 않아 기본 제외
]


def _profit_rate_from_state(path: str):
    """대시보드(stats/route.ts:34-49)와 동일한 식으로 수익률을 계산한다.

    raw_stats.profit_rate는 읽지 않는다 — 파이썬 쪽 calculate_stats가
    initial_cash를 상태 파일에서 되읽지 않아 생성자 기본값(3,000,000)으로
    고정되는 버그가 있어, 리셋으로 initial_cash를 바꾼 경우 대시보드와
    분모가 달라진다. 대신 cash/portfolio/initial_cash로 그때그때 재계산해서
    대시보드와 항상 같은 값을 낸다.

    portfolio 평가액은 raw_stats.current_prices를 우선하고, 없으면 종목별
    current_price → avg_price → 0 순으로 폴백한다(대시보드 || 체인과 동일 순서).

    initial_cash이 없거나 0 이하이면 분모를 만들 수 없으므로 None(=모름).
    파일이 없으면(FileNotFoundError) 조용히 None을 반환한다(정상: 아직 상태 파일 없음).
    다른 예외(파싱 오류, 권한 오류, 인코딩 오류)는 [Brief] 로그를 남기고 None을 반환한다.
    """
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            state = json.load(f)

        initial_cash = state.get('initial_cash')
        if not initial_cash or initial_cash <= 0:
            return None

        current_prices = (state.get('raw_stats') or {}).get('current_prices') or {}
        portfolio_value = 0
        for code, item in (state.get('portfolio') or {}).items():
            price = current_prices.get(code) or item.get('current_price') or item.get('avg_price') or 0
            qty = item.get('quantity') or item.get('qty') or 0
            portfolio_value += price * qty

        total_asset = (state.get('cash') or 0) + portfolio_value
        return (total_asset - initial_cash) / initial_cash * 100
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"[Brief] 상태 파일 읽기 실패: {path} — {type(e).__name__}: {e}")
        return None


def _count_today_tickers(path: str, today_str: str) -> int:
    """오늘 매매한 종목 수(중복 제거). 파일이 없으면 거래가 없었다는 뜻이므로 0."""
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return len({
                row['symbol'] for row in csv.DictReader(f)
                if (row.get('timestamp') or '').startswith(today_str) and row.get('symbol')
            })
    except FileNotFoundError:
        return 0
    except Exception as e:
        print(f"[Brief] 거래이력 읽기 실패: {path} — {type(e).__name__}: {e}")
        return 0


def collect_sim_brief(data_dir: str, today_str: str) -> list[dict]:
    """9개 심의 (표시명, 수익률, 금일 거래 종목 수)를 모은다."""
    return [
        {
            'label': label,
            'profit_rate': _profit_rate_from_state(os.path.join(data_dir, state_file)),
            'ticker_count': _count_today_tickers(os.path.join(data_dir, csv_file), today_str),
        }
        for label, state_file, csv_file in SIM_BRIEF_TARGETS
    ]


def should_send_brief(should_notify: bool, hour: int) -> bool:
    """15시 정각 회차에서만 True. should_notify() 게이트는 건드리지 않는다."""
    return bool(should_notify) and hour == 15
