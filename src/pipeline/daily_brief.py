"""15:00 마감 브리핑 메시지 조립.

계산식은 대시보드(TradeClient.tsx renderRealPortfolioSection)와 동일하다.
텔레그램과 웹이 다른 수를 말하면 둘 다 못 믿게 된다.
"""

import csv
import json
import os
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


# (표시명, 상태 파일, 거래이력 CSV) — 리셋 대상 9개와 동일. Sim0 리베로는 매매하지 않아 제외.
# 표시명은 대시보드 라벨(TradeClient.tsx)과 일치시킨다.
SIM_BRIEF_TARGETS = [
    ('심리 괴리형 (Sim 1)',    'sim_psych_state.json',         'trade_history_sim_psych.csv'),
    ('수급 동승형 (Sim 2)',    'sim_spillover_state.json',     'trade_history_sim_spillover.csv'),
    ('가치 페어형 (Sim 3)',    'sim_risk_state.json',          'trade_history_sim_risk.csv'),
    ('상승 모멘텀형 (Sim 4)',  'sim_bull_state.json',          'trade_history_sim_bull.csv'),
    ('상승 단타형 (Sim 4-1)',  'sim_bulldaytrade_state.json',  'trade_history_sim_bulldaytrade.csv'),
    ('추세 눌림목형 (Sim 5)',  'sim_sideways_state.json',      'trade_history_sim_sideways.csv'),
    ('하락 줍줍형 (Sim 6)',    'sim_bear_state.json',          'trade_history_sim_bear.csv'),
    ('리포트 팔로워 (Sim 7)',  'sim_reportfollower_state.json','trade_history_sim_reportfollower.csv'),
    ('오케스트레이터 (Sim 10)', 'sim_orchestrator_state.json',  'trade_history_sim_orchestrator.csv'),
]


def _read_profit_rate(path: str):
    """state의 raw_stats.profit_rate를 읽는다. 없으면 None(=모름).

    재계산하지 않는다. cash+invested로 구하면 invested가 매입원가라서
    대시보드(실시간 시세 평가)와 다른 값이 나온다.
    """
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            raw = json.load(f).get('raw_stats')
        if not isinstance(raw, dict) or 'profit_rate' not in raw:
            return None
        return float(raw['profit_rate'])
    except Exception:
        return None


def _count_today_tickers(path: str, today_str: str) -> int:
    """오늘 매매한 종목 수(중복 제거). 파일이 없으면 거래가 없었다는 뜻이므로 0."""
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return len({
                row['symbol'] for row in csv.DictReader(f)
                if (row.get('timestamp') or '').startswith(today_str) and row.get('symbol')
            })
    except Exception:
        return 0


def collect_sim_brief(data_dir: str, today_str: str) -> list[dict]:
    """9개 심의 (표시명, 수익률, 금일 거래 종목 수)를 모은다."""
    return [
        {
            'label': label,
            'profit_rate': _read_profit_rate(os.path.join(data_dir, state_file)),
            'ticker_count': _count_today_tickers(os.path.join(data_dir, csv_file), today_str),
        }
        for label, state_file, csv_file in SIM_BRIEF_TARGETS
    ]
