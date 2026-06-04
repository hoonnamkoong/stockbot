"""
[Sim5 조건 검토] 엑셀 스냅샷 → 일봉 근사 → 진입 조건 민감도 스윕.

목적: "한 달 5건 이상" 체결을 위해 sim5 진입 조건을 어디까지 완화해야 하는지 검토.

[데이터 한계 — 결과 해석 시 필수 인지]
- 엑셀에 일봉 5일 종가·거래대금·체결강도 컬럼 없음 → 가격 기반 조건만 검토.
- 일봉 = 날짜(YYYYMMDD)별 종목당 마지막 스냅샷 종가 (인트라데이 노이즈 제거).
- 당일 등락률 = (오늘 일봉 - 어제 일봉)/어제 일봉 (스냅샷 등락률 대신 일봉 기준).
- amount(유동성)·tick_power(체결강도) 게이트는 데이터 부재로 '통과' 가정하고 제외.
- 가용 거래일 17일(1월 집중), 일봉≥3 종목 46개 → 표본 빈약, 방향성 참고용.
"""
import os, re, glob, json, collections
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def calc_adx(sp):
    if len(sp) < 2: return 0.0
    direction = abs(sp[-1] - sp[0])
    vol = sum(abs(sp[i] - sp[i-1]) for i in range(1, len(sp)))
    return 0.0 if vol == 0 else direction / vol * 100.0


def calc_period(sp):
    if len(sp) < 2 or sp[0] <= 0: return 0.0
    return (sp[-1] - sp[0]) / sp[0] * 100.0


def pullback_pct(sp, price):
    hist = sp[:-1] if len(sp) > 1 else sp
    rh = max(hist[-4:]) if len(hist) >= 4 else (max(hist) if hist else price)
    return (rh - price) / rh * 100 if rh > 0 else 0.0


def build_daily():
    """[통합] YYYYMMDD 스냅샷 + 월별 파일(수집시각 컬럼)을 모두 합쳐 일봉 근사.
    daily[code][YYYY-MM-DD] = 그날 마지막 종가. (날짜,종목) 기준 자동 dedup.
    """
    files = glob.glob(os.path.join(ROOT, 'data', 'trending_integrated_*.xlsx'))
    daily = collections.defaultdict(dict)  # code -> {date: price}

    def norm_code(s):
        return str(s).replace('.0', '').strip().zfill(6)

    for f in files:
        b = os.path.basename(f)
        try: df = pd.read_excel(f)
        except Exception: continue
        if 'code' not in df.columns or '현재가' not in df.columns: continue
        df['code'] = df['code'].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(6)

        # 날짜 소스: 파일명 \d{8} 우선, 없으면 수집시각 컬럼
        m = re.search(r'trending_integrated_(\d{8})', b)
        date_col = next((c for c in df.columns if any(k in str(c) for k in ['수집', '시각', '일시'])), None)
        for _, r in df.iterrows():
            try: p = float(str(r['현재가']).replace(',', '').strip())
            except Exception: continue
            if p <= 0: continue
            if m:
                d = m.group(1)  # YYYYMMDD
            elif date_col is not None:
                ts = pd.to_datetime(r[date_col], errors='coerce')
                if pd.isna(ts): continue
                d = ts.strftime('%Y%m%d')
            else:
                continue
            daily[r['code']][d] = p

    all_dates = set()
    for dmap in daily.values():
        all_dates.update(dmap.keys())
    series = {}
    for code, dmap in daily.items():
        seq = [dmap[k] for k in sorted(dmap.keys())]
        if len(seq) >= 3:
            series[code] = seq
    return series, len(all_dates)


# 평가할 조건 세트: (라벨, adx_min, period_min, pb_lo, pb_hi, daily_min)
# daily_min=None 이면 당일 등락률 조건 면제.
SETS = [
    ("현재(baseline)",         20.0, 0.0,  1.5, 10.0, 0.0),
    ("ADX>=15",               15.0, 0.0,  1.5, 10.0, 0.0),
    ("ADX>=10",               10.0, 0.0,  1.5, 10.0, 0.0),
    ("pullback 1.0~12",       20.0, 0.0,  1.0, 12.0, 0.0),
    ("pullback 0.5~15",       20.0, 0.0,  0.5, 15.0, 0.0),
    ("period>=-1",            20.0, -1.0, 1.5, 10.0, 0.0),
    ("당일 >=-1%",            20.0, 0.0,  1.5, 10.0, -1.0),
    ("당일 >=-2%",            20.0, 0.0,  1.5, 10.0, -2.0),
    ("당일상승 면제",           20.0, 0.0,  1.5, 10.0, None),
    # --- 현재 적용(당일>=-2%) 위에서 pullback 추가 완화 분해 ---
    ("[현재] 당일>=-2%",            20.0, 0.0, 1.5, 10.0, -2.0),
    ("+하한완화 pb1.0~10",         20.0, 0.0, 1.0, 10.0, -2.0),
    ("+상한완화 pb1.5~12",         20.0, 0.0, 1.5, 12.0, -2.0),
    ("+상한완화 pb1.5~15",         20.0, 0.0, 1.5, 15.0, -2.0),
    ("+하한+상한 pb1.0~12",        20.0, 0.0, 1.0, 12.0, -2.0),
]


def evaluate(series, n_dates):
    # 각 종목의 각 시점 t(>=2, 즉 3일째부터)에서 조건 평가.
    # 진입 신호 = 모든 조건 통과. "신호 건수" = (code, t) 통과 수.
    results = []
    # 탈락 사유 집계는 baseline 기준으로만
    fail_counter = collections.Counter()
    total_points = 0

    for label, adx_min, period_min, pb_lo, pb_hi, daily_min in SETS:
        signals = 0
        for code, seq in series.items():
            for t in range(2, len(seq)):
                sp = seq[:t+1][-5:]      # 최근 5일 (과거->현재)
                price = seq[t]
                prev = seq[t-1]
                adx = calc_adx(sp)
                period = calc_period(sp)
                pb = pullback_pct(sp, price)
                daily = (price - prev) / prev * 100 if prev > 0 else 0.0

                c_adx = adx >= adx_min
                c_period = period > period_min
                c_pb = pb_lo <= pb <= pb_hi
                c_daily = True if daily_min is None else (daily > daily_min)

                if label == "현재(baseline)":
                    total_points += 1
                    if not c_adx: fail_counter['ADX<20'] += 1
                    if not c_period: fail_counter['period<=0'] += 1
                    if not c_pb: fail_counter['pullback 범위밖'] += 1
                    if not c_daily: fail_counter['당일하락'] += 1

                if c_adx and c_period and c_pb and c_daily:
                    signals += 1
        # 월(20거래일) 환산: 신호수 / 가용거래일 * 20
        per_month = signals / n_dates * 20
        results.append({
            '조건': label,
            '진입신호': signals,
            '월환산(약)': round(per_month, 1),
        })
    return results, fail_counter, total_points


def main():
    series, n_dates = build_daily()
    print(f'[표본] 일봉>=3 종목 {len(series)}개, 가용 거래일 {n_dates}일')
    results, fails, total = evaluate(series, n_dates)
    out = {
        'sample_codes_ge3': len(series),
        'available_trading_days': n_dates,
        'total_eval_points': total,
        'baseline_fail_breakdown': dict(fails),
        'sweep': results,
    }
    with open(os.path.join(ROOT, 'scratch', '_sim5_sweep.json'), 'w', encoding='utf-8') as w:
        json.dump(out, w, ensure_ascii=False, indent=2)
    print('saved scratch/_sim5_sweep.json')
    for r in results:
        print(r)


if __name__ == '__main__':
    main()
