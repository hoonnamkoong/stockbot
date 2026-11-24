"""종목별 '평상시 게시글 수' 누적 저장소 — 심1의 비율 게이트 입력.

## 왜 생겼나

심1의 진입 조건은 "평상시 대비 2.2배"(`BUZZ_RATIO_MIN`)인데, 2026-11-24 라이브
`sim1_diag_*.csv` 54파일 37,032행 전수에서 `avg_posts`가 **100% 전부 1.0**이었다.
`buzz_ratio == posts`가 되어 그 게이트는 사실상 `posts >= 2.2`였고 바로 뒤의
`posts >= 30`에 흡수됐다 — 배포 이래 한 번도 작동하지 않았다. 남은 절대 개수
조건이 대형주 필터라 진입 18건 중 12건이 삼성전자였다.

원인은 **단계 순서**였다. `orchestrator`에서 Stage 3이 심을 돌리고, Stage 4의
`NotifierWorker._aggregate_multi_day`가 그 키를 만든다 — 생산자가 소비자보다 한
단계 뒤라 구조적으로 도달할 수 없었다.

## 그 함정을 설계로 없앤다

기준선은 **항상 오늘을 뺀** 이전 거래일들에서 계산한다. 그래서 `record()`와
`apply()`의 **순서가 결과를 바꾸지 않는다** — 같은 자리에서 연달아 불러도 된다
(`tests/test_buzz_baseline.py::test_order_of_record_and_apply_does_not_matter`).
오늘을 포함하면 폭발이 자기 기준선을 희석해 배수가 1에 수렴한다. notifier의
`avg_posts`가 정확히 그 모양이었다(삼성전자 `sparkline_posts=[800]*5`, 평균 800,
글 800 → 배수 1.0).

## 소유권과 보존

writer는 `trade_engine.run()`(=scraper.yml의 Stage 3) **하나**다. trading.yml의
60초 루프는 버즈 불필요 심만 돌리므로 이 파일을 쓰지 않는다 — 두 워크플로가
같은 누적 파일을 쓰면 lost update가 난다.

- 복원: scraper.yml·trading.yml 모두 런 시작에 `git checkout db-data -- data/`로
  **data/ 전체**를 받는다. 그래서 별도 조회 목록에 넣을 필요가 없다.
- 배포: scraper.yml이 `for f in data/*.json`으로 올린다(제외 목록에 없다).
- `record()`는 **반드시 먼저 load()** 한다. 새로 시작하면 누적 파일이 매 런
  잘린다 — 배포 목록과 복원 목록이 갈렸을 때 심9-1 매매기록 8건이 2행으로
  줄었던 사고와 같은 모양이다.

파일은 compact JSON으로 쓴다. 후보 유니버스가 날마다 바뀌어 코드가 계속 쌓이고,
db-data 크기가 이미 매매 사이클을 끌어내리고 있다(644MB).

## 측정 불가를 지어내지 않는다

- 이전 거래일이 `MIN_DAYS` 미달이면 `avg_posts`를 **주지 않는다**. 심1이
  `no_buzz_baseline`으로 거른다.
- 과거가 전부 0이면 배수가 무한이다. 바닥값(예: 1.0)을 두면 방금 제거한
  `or 1` 폴백이 그대로 돌아오므로 **측정 불가로 둔다**. 이건 문턱이 아니라
  전략 결정이라 사용자 판단 전까지 손대지 않는다.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta

FILENAME = 'buzz_baseline.json'

# 기준선 창(거래일). notifier의 5일 누적 보드와 같은 길이 — `BUZZ_RATIO_MIN=2.2`가
# 그 창을 전제로 정해진 값이다.
WINDOW_DAYS = 5
# 이보다 적으면 평균을 믿지 않는다. 1~2일 표본으로 '평상시'를 말할 수 없다.
MIN_DAYS = 3
# 창을 완전히 벗어난 코드를 걷어내는 달력 기준. 유니버스 churn으로 코드가
# 무한히 쌓이는 것을 막는다.
RETENTION_DAYS = 30


def _path(data_dir: str) -> str:
    return os.path.join(data_dir, FILENAME)


def load(data_dir: str = 'data') -> dict:
    """저장소를 읽는다. 없거나 깨졌으면 빈 저장소 — 기준선 없음과 같게 다룬다."""
    try:
        with open(_path(data_dir), 'r', encoding='utf-8') as f:
            store = json.load(f)
        codes = store.get('codes')
        return {'codes': codes if isinstance(codes, dict) else {}}
    except Exception:
        return {'codes': {}}


def save(store: dict, data_dir: str = 'data') -> None:
    os.makedirs(data_dir, exist_ok=True)
    with open(_path(data_dir), 'w', encoding='utf-8') as f:
        json.dump(store, f, ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def _prune(codes: dict, today: str) -> dict:
    try:
        cutoff = (date.fromisoformat(today) - timedelta(days=RETENTION_DAYS)).isoformat()
    except ValueError:
        return codes
    out: dict = {}
    for code, by_date in codes.items():
        if not isinstance(by_date, dict):
            continue
        kept = {d: v for d, v in by_date.items() if d >= cutoff}
        for d in sorted(kept, reverse=True)[WINDOW_DAYS + 1:]:
            kept.pop(d)
        if kept:
            out[code] = kept
    return out


def record(candidates: list[dict], today: str, data_dir: str = 'data') -> None:
    """오늘의 종목별 글 수를 적는다. 하루에 한 칸이고, 장중 누적이므로
    마지막 값(그 날 총계에 가장 가까운 값)이 남는다."""
    store = load(data_dir)          # 먼저 읽는다 — 안 그러면 매 런 잘린다
    codes = store['codes']
    for s in candidates or []:
        code = s.get('code')
        n = s.get('recent_posts_count')
        if not code or n is None:
            continue                # 모르는 값을 0으로 적지 않는다(0은 실제 0이다)
        codes.setdefault(code, {})[today] = float(n)
    store['codes'] = _prune(codes, today)
    save(store, data_dir)


def baseline_for(by_date: dict, today: str) -> float | None:
    """오늘을 뺀 최근 `WINDOW_DAYS` 거래일의 평균. 표본 미달이면 None."""
    prior = sorted((d for d in by_date if d != today), reverse=True)[:WINDOW_DAYS]
    if len(prior) < MIN_DAYS:
        return None
    vals = [float(by_date[d]) for d in prior]
    return sum(vals) / len(vals)


def apply(candidates: list[dict], today: str, data_dir: str = 'data') -> tuple[int, int]:
    """후보 dict에 `avg_posts`를 **제자리에서** 넣는다. (적용 수, 전체 수) 반환.

    제자리인 것이 중요하다 — `trade_engine`이 같은 리스트를 페이퍼
    (`_run_simulators`)와 실전(`run_program_trading`) 양쪽에 넘기므로, 여기서
    보강하면 두 경로가 같은 입력을 본다(심 선택 = 실전 동일 동작).
    """
    codes = load(data_dir)['codes']
    applied = total = 0
    for s in candidates or []:
        if not s.get('code'):
            continue
        total += 1
        avg = baseline_for(codes.get(s['code']) or {}, today)
        if avg is not None and avg > 0:
            s['avg_posts'] = avg
            applied += 1
    return applied, total
