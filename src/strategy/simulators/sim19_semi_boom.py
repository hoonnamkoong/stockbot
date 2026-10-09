"""Sim19 반도체 붐의 질 — 가격 주도인가 물량 주도인가. 매매하지 않는다.

2026-10-09 탐색에서 **반도체 사이클 변곡을 선행하는 실물 데이터는 없다**는
결론이 났다. 미국 반도체 생산·가동률·수주·고용은 한국 수출을 3~10개월
**후행**하고, 고전적 지표인 재고/출하 비율은 무의미했다(p=0.43).
선행하는 것은 장비·메모리 주식뿐인데 1~2개월이고 반도체지수와 상관
0.84~0.91로 **동행**이라 알파가 없다.

그래서 이 심은 **예측하지 않는다.** 대신 지금 붐의 **질**을 기술한다 —
관세청 HS8542 수출금액을 단가와 중량으로 분해해서, 금액 증가가 가격에서
오는지 물량에서 오는지 알린다. 단가는 유료 DRAM 현물가의 공개 대리변수다.

2026-08 실측: 금액 YoY **+203.1%** · 단가 YoY **+199.3%** · 중량 YoY
**+1.3%**. 즉 이번 붐은 **전부 가격**이다. 그리고 중량 YoY는 6개월 동안
+12.8% → +1.3%로 말라가는 중이고(7월엔 −1.2%) 단가는 +111% → +199%로
가속했다.

이것은 예측이 아니라 **상태**다. "가격만 오르는 붐"이 언제 끝나는지는
위 탐색에서 찾지 못했다. 단가 YoY 국소 고점 12개 뒤 주가 수익률은
12검정 전부 유의하지 않았다(최소 p=0.092). 그 사실을 알림에 같이 싣는다.
"""
from __future__ import annotations

from src.data import semi_trade

from .base_simulator import BaseSimulator, get_kst_now

try:
    from src import alerts
except Exception:
    alerts = None

# 문턱. 2026-10-09 실측 분포를 보고 정했고 예측력 주장이 아니다 — 기술용 구분선이다.
PRICE_SHARE = 0.70      # 단가YoY / 금액YoY 가 이 이상이면 가격 주도
VOLUME_SHARE = 0.50     # 중량YoY / 금액YoY 가 이 이상이면 물량 주도
FLAT_VOLUME = 5.0       # 중량YoY 가 이 미만이면 '물량 제자리'

PRICE_LED = '가격주도'
VOLUME_LED = '물량주도'
MIXED = '혼합'
CONTRACTING = '수축'
UNKNOWN = '판정불가'
ALERT_COOLDOWN_MIN = 24 * 60
YEARS_BACK = 3          # 전년동월비를 내려면 최소 2년, 여유로 3년


def classify(amt, price, wgt):
    """금액·단가·중량 YoY → (질, 사유). 하나라도 없으면 판정불가."""
    if amt is None or price is None or wgt is None:
        return UNKNOWN, '지표 결측'
    if amt <= 0:
        return CONTRACTING, '수출금액 YoY %+.1f%% (감소)' % amt
    ps = price / amt if amt else 0.0
    vs = wgt / amt if amt else 0.0
    if ps >= PRICE_SHARE and wgt < FLAT_VOLUME:
        return PRICE_LED, ('금액 %+.1f%% 중 단가가 %+.1f%%p — 물량은 %+.1f%%로 '
                           '제자리' % (amt, price, wgt))
    if vs >= VOLUME_SHARE:
        return VOLUME_LED, ('금액 %+.1f%% 중 중량이 %+.1f%%p — 물량이 끌고 있다'
                            % (amt, wgt))
    return MIXED, ('금액 %+.1f%% = 단가 %+.1f%% + 중량 %+.1f%%'
                   % (amt, price, wgt))


def format_notice(quality, reason, prev, metrics):
    lines = ['[반도체 붐의 질] %s → %s' % (prev, quality), '', reason, '']
    lines.append('기준월 %s' % metrics.get('month', '?'))
    lines.append('수출금액 %.0f억$ · 단가 %.0f$/kg · 중량 %.0f톤'
                 % (metrics.get('금액', 0) / 1e8,
                    metrics.get('단가', 0),
                    metrics.get('중량', 0) / 1000))
    tr = metrics.get('중량추이')
    if tr:
        lines.append('중량 YoY 추이: ' + ' → '.join('%+.0f%%' % x for x in tr))
    if quality == PRICE_LED:
        lines += ['',
                  '⚠ 물량 없는 가격 붐이다. 금액이 가격에만 얹혀 있으면 '
                  '가격이 꺾이는 순간 금액이 같이 꺾인다.']
    lines += ['',
              '이것은 예측이 아니라 상태 기술이다. 단가 고점이 주가 변곡을 '
              '알려주는지 검정했으나 12검정 전부 유의하지 않았다(최소 p=0.092). '
              '관찰용이고 매매 근거가 아니다.']
    return '\n'.join(lines)


class SemiBoomSimulator(BaseSimulator):
    """매매하지 않는다. 반도체 수출의 가격·물량 분해만 알린다."""

    IS_ANALYZER = True
    IS_EOD = True       # 월별 데이터다 — 하루 한 번도 과하다

    def __init__(self, initial_cash=0):
        super().__init__("SemiBoom", initial_cash)
        self.state.setdefault('quality', UNKNOWN)
        self.state.setdefault('history', [])

    def get_universe(self):
        return []

    def run(self, candidates, current_prices=None):
        now = get_kst_now()
        today = now.strftime('%Y-%m-%d')
        prev = self.state.get('quality', UNKNOWN)
        years = [now.year - i for i in range(YEARS_BACK)]

        series, errors = semi_trade.fetch_series(sorted(years), log=print)
        if not series:
            print('[Sim19 반도체붐] 수집 0건 — 직전 상태 유지: %s' % prev)
            self.state['last_error'] = '; '.join(errors) or 'unknown'
            self.state['checked_at'] = now.strftime('%Y-%m-%d %H:%M:%S')
            self.save_state(current_prices)
            return []

        k = sorted(series)[-1]
        amt = semi_trade.yoy(series, '금액', k)
        price = semi_trade.yoy(series, '단가', k)
        wgt = semi_trade.yoy(series, '중량', k)
        quality, reason = classify(amt, price, wgt)
        trail = []
        for kk in sorted(series)[-6:]:
            w = semi_trade.yoy(series, '중량', kk)
            if w is not None:
                trail.append(round(w, 1))
        metrics = dict(month=k[:7], 금액=series[k]['금액'],
                       단가=series[k]['단가'], 중량=series[k]['중량'],
                       금액YoY=amt, 단가YoY=price, 중량YoY=wgt,
                       중량추이=trail)
        self.state.update(metrics=metrics, reason=reason, last_error=None,
                          checked_at=now.strftime('%Y-%m-%d %H:%M:%S'))
        if quality != prev:
            self.state['quality'] = quality
            self.state['quality_since'] = today
            h = self.state.setdefault('history', [])
            h.append({'date': today, 'month': k[:7], 'quality': quality,
                      'reason': reason})
            del h[:-200]
            self._notify(quality, reason, prev, metrics, now)
            print('[Sim19 반도체붐] %s → %s | %s' % (prev, quality, reason))
        else:
            print('[Sim19 반도체붐] %s 유지 | %s' % (quality, reason))
        self.save_state(current_prices)
        return []

    def _notify(self, quality, reason, prev, metrics, now):
        if alerts is None or quality == UNKNOWN:
            return
        if prev == UNKNOWN and quality == MIXED:
            return      # 기동 시 '혼합'은 사건이 아니다
        try:
            alerts.send_alert_once(
                'semi_boom_%s' % quality,
                format_notice(quality, reason, prev, metrics),
                now, cooldown_min=ALERT_COOLDOWN_MIN)
        except Exception as e:
            print('[Sim19 반도체붐] 알림 실패: %s: %s' % (type(e).__name__, e))
