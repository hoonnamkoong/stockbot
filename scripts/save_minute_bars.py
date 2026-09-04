"""마감 후 당일 1분봉 저장 — eod_data.yml에서 하루 한 번.

왜 필요한가: 2026-08-09 재구성의 신호는 60~120초 격자인데 가격은 diag의 10분
격자에만 있다. 4분짜리 신호를 10분 가격으로 재면 향후 수익률의 대부분이 신호와
무관한 구간이라 신호 대 잡음이 구조적으로 나쁘다. **표본을 늘리지 않고 검정력을
올리는 유일한 항목이 가격 해상도다.**

왜 마감 후인가: KIS 분봉(FHKST03010200)은 **당일치만** 조회된다. 과거로 소급할 수
없으므로 그날 안에 저장해 두어야 하고, eod_data.yml이 이미 마감 후에 돈다.

대상 종목은 그날 순위 스냅샷(money_*.csv)에 오른 것들이다. 전 종목을 받으면
KIS 유량을 태우면서 분석에 쓰이지도 않는다 — 신호가 순위 차분에서 나오기 때문이다.
"""

import csv
import glob
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src import alerts
from src.data.minute_bars import anchor_times, codes_for_date, drop_date, merge_bars

COLUMNS = ['date', 'code', 'hhmm', 'price', 'volume']

# KIS 유량은 초당 20건이다. 종목당 13콜 × 수십 종목이라 한 번에 몰아치면
# 유량 제한에 걸리고, 그 실패는 조용히 빈 응답으로 돌아온다.
CALL_GAP_SEC = 0.06

# 이 수집의 벽시계 상한(초). **일은 종목 수에 비례하는데 잡 예산은 고정이다.**
# 대상은 그날 순위 스냅샷에 오른 종목 전부라 세션이 길수록 늘고(실측 90종목 ×
# 13앵커 = 1,170콜), KIS가 느려지면 콜당 최대 24.9초까지 간다
# (3시도 × (연결 3초 + 읽기 5초) + 백오프). 상한이 없으면 잡 예산을 통째로 먹는다.
#
# 2026-09-01~02 EOD 배치가 정확히 그렇게 죽었다. 이 스텝이 20분 잡 타임아웃에
# 걸리면서 **뒤에 있던 배포 스텝이 통째로 스킵됐다.** 심9-1·심11 계산은 이미
# 끝나 있었는데(로그: '심11 감시 목록 갱신 … 날짜 20260903') db-data로 안 나가
# 감시목록·종가 CSV가 두 세션 낡은 채였다 — 그 세션들은 매매 판단 자체가 없었다.
# 잃은 것은 수집이 아니라 배포다. 그래서 이 스크립트는 자기 몫만 쓰고 비켜준다.
#
# `|| echo`로 감싸도 이건 못 막는다 — 0이 아닌 종료가 아니라 **끝나지 않는 것**이
# 문제이기 때문이다. 예산이 끝나면 받은 데까지 저장하고 정상 종료한다. 분봉은
# 당일치만 조회되므로 일부라도 남기는 것이 0보다 낫다.
BUDGET_SEC = int(os.environ.get('MINUTE_BARS_BUDGET_SEC', '360'))


def month_path(now, data_dir='data') -> str:
    return os.path.join(data_dir, f"minute_{now.strftime('%Y-%m')}.csv")


def append_bars(date_str: str, code: str, bars: list[dict], path: str) -> int:
    if not bars:
        return 0
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    is_new = not os.path.exists(path)
    with open(path, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction='ignore')
        if is_new:
            w.writeheader()
        for b in bars:
            w.writerow({'date': date_str, 'code': code,
                        'hhmm': b['hhmm'], 'price': b['price'], 'volume': b['volume']})
    return len(bars)


def main() -> None:
    now = (datetime.now(timezone.utc) + timedelta(hours=9)).replace(tzinfo=None)
    date_str = now.strftime('%Y%m%d')

    # 파일명을 짚지 않는다. 순위 스냅샷은 2026-09-04에 월별(money_2026-09.csv)에서
    # 일별(money_2026-09-04.csv)로 바뀌었고, 전환일에는 두 형식이 함께 있다.
    # 글롭 + 날짜 필터면 어느 쪽이든 같은 답을 준다.
    money_files = sorted(glob.glob(os.path.join('data', 'money_*.csv')))
    codes = sorted({c for p in money_files for c in codes_for_date(p, date_str)})
    if not codes:
        # 순위 스냅샷이 아직 없는 날(최초 배포)이거나 휴장일. 조용히 끝낸다 —
        # 여기서 죽으면 EOD 잡의 나머지(심9-1·CSV 배포)까지 같이 못 돈다.
        print(f'[분봉] {date_str} 대상 종목 없음 ({len(money_files)}개 파일 확인) — 생략')
        return

    from src.trade.kis_data_provider import KISDataProvider
    p = KISDataProvider()
    path = month_path(now)
    # 재실행분은 덧붙이는 게 아니라 **대체한다.** 이 잡은 `|| echo`로 감싸여 있어
    # 실패해도 워크플로가 초록색이고, 사람이 다시 돌리는 일이 실제로 있다.
    dropped = drop_date(path, date_str)
    if dropped:
        print(f'[분봉] {date_str} 기존 {dropped}행 제거 — 이번 수집분으로 대체합니다')
    anchors = anchor_times()
    total, failed = 0, 0
    # 예산이 끝나 못 받은 종목 수. 0이면 끝까지 돌았다는 뜻이다.
    left = 0
    deadline = time.monotonic() + BUDGET_SEC
    for i, code in enumerate(codes):
        batches = []
        for a in anchors:
            # 앵커 사이에서 본다 — 종목 사이에서만 보면 느린 날 한 종목(13콜 ×
            # 24.9초 = 5.4분)이 예산을 통째로 넘겨 상한이 상한이 아니게 된다.
            if time.monotonic() >= deadline:
                left = len(codes) - i
                break
            try:
                bars = p.get_minute_bars(code, a)
            except Exception as e:
                bars = []
                print(f'[분봉] {code} {a} 실패: {e}')
            # **빈 응답도 실패로 센다.** KISDataProvider._get은 실패해도 예외 없이
            # {}를 준다(토큰 만료·유량 초과·rt_cd≠0) — 예외만 세면 토큰이 죽은 날
            # 13앵커 × 전 종목이 조용히 비는데 아래 로그는 '조회 실패 0콜'이 된다.
            if not bars:
                failed += 1
            else:
                batches.append(bars)
            time.sleep(CALL_GAP_SEC)
        # 중단된 종목도 받은 앵커까지는 저장한다 — 버리면 그만큼이 영구 손실이다.
        n = append_bars(date_str, code, merge_bars(*batches), path)
        total += n
        if left:
            break
    # 결손을 조용히 넘기지 않는다 — 분봉이 비면 신호 검정 자체가 성립하지 않는데
    # 로그가 조용하면 '그날은 신호가 없었다'로 오독된다.
    print(f'[분봉] {len(codes) - left}/{len(codes)}종목 / {total}행 저장 → {path}'
          + (f' (빈 응답·실패 {failed}콜)' if failed else ''))
    if left:
        print(f'[분봉] 예산 {BUDGET_SEC}초 소진 — {left}종목을 남기고 중단합니다. '
              '뒤 스텝(배포)이 돌 수 있도록 여기서 비켜줍니다.')

    if total == 0:
        # 로그만으로는 부족하다. 이 잡은 `|| echo`로 감싸여 있어 워크플로가 초록색이고,
        # KIS 분봉은 **당일치만** 조회되므로 다음 날 알아채도 복구할 방법이 없다.
        alerts.send_alert(
            f"<b>분봉 저장 실패</b>\n\n"
            f"{date_str} — 대상 {len(codes)}종목이 전부 빈 응답({failed}콜)입니다.\n"
            f"KIS 토큰 또는 유량을 확인하세요.\n"
            f"⚠️ 분봉은 당일치만 조회됩니다 — 이 하루의 가격 해상도는 복구할 수 없습니다.")
    elif left:
        # 중단도 결손이다. 로그만 남기면 '그날은 종목이 적었다'로 오독된다 —
        # 이 스크립트가 비켜준 덕에 워크플로는 초록색이라 더더욱 그렇다.
        alerts.send_alert(
            f"<b>분봉 부분 수집</b>\n\n"
            f"{date_str} — {len(codes)}종목 중 {len(codes) - left}종목만 받고 "
            f"예산({BUDGET_SEC}초)이 끝났습니다.\n"
            f"나머지 배포(감시목록·종가 CSV)는 정상 진행됩니다.\n"
            f"⚠️ 분봉은 당일치만 조회됩니다 — 남은 {left}종목은 복구할 수 없습니다.")


if __name__ == '__main__':
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    main()
