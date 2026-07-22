"""15:00 마감 브리핑 메시지 조립.

계산식은 대시보드(TradeClient.tsx renderRealPortfolioSection)와 동일하다.
텔레그램과 웹이 다른 수를 말하면 둘 다 못 믿게 된다.
"""

from datetime import datetime

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
