"""신호 관측 스파인 — 선정에 이미 쓰이는 값 대신 계산만 되고 버려지는 신호를
한 곳에 모은다. 계산은 순수 함수, 기록은 sim_diag.py와 같은 모양(월별 CSV +
헤더 변경 시 옆으로 비켜놓기)을 그대로 따르되 별도 파일을 쓴다.

Design: ~/.gstack/projects/hoonnamkoong-stockbot/Hoon_DT-main-design-20260811-222707.md

**여기 쓰는 값에 sim_diag.COLUMNS를 확장하지 않는다.** 그건 전 심 공용
단일 리스트라, 새 컬럼을 얹으면 모든 심의 이번 달 진단 CSV가 통째로
`_v1`로 회전한다(Sim1-1 설계에서 확인된 함정) — Constraints 참고.

2단계 범위: Stage 3 후보 전수 관측 로깅까지. `rank_and_recommendation`
(딥다이브 산출물, Stage 3.5)과의 조인은 별도 증분(Open Question 3의
as-of 조인 방식 확정 후)이다 — 여기서는 아직 하지 않는다.

[2026-08-11] 사용자가 로그 축적을 기다리지 않고 선정 랭킹 적용을 앞당기기로
결정 — `rank_top()`이 그 배선이다. 원값을 안 더한다: fact_score(0~1)와
tick_power(원 단위 % 스케일)를 그대로 합치면 스케일이 큰 쪽이 지배해
대형주 상수를 만든 것과 같은 함정(횡단면 절대값 z 금지 원칙)이 재현된다.
대신 신호별 순위를 매기고 순위를 더한다(Borda count).
"""

import csv
import os
from datetime import datetime, timedelta, timezone

DATA_DIR = 'data'

COLUMNS = [
    'cycle_id', 'ts', 'code', 'name',
    'fact_score', 'sentiment', 'tick_power', 'consecutive_days', 'change_rate',
    'engine_signal', 'engine_reason',
]


def _parse_change_rate(v) -> float:
    """'+5.23%' 같은 문자열을 실수로. algo_04_v2.py의 같은 파싱과 동일 규칙."""
    try:
        return float(str(v or '0').replace('%', '').replace('+', ''))
    except (TypeError, ValueError):
        return 0.0


def build_features(candidates: list[dict], simulation_results: list[dict], cycle_id: int) -> list[dict]:
    """후보 전수에 대해 피처 벡터를 만든다. 신규 계산 없음 — Stage 1·2·3이 이미
    계산해둔 값을 모으기만 한다.

    candidates: Stage 3 진입 시점의 dict 목록(StockData.to_dict() 결과).
        fact_score/sentiment/tick_power/consecutive_days가 이미 들어있어야 한다
        (fact_score는 llm_analyzer.py의 Stage2→StockData 동기화에 의존한다).
    simulation_results: StrategyEngine.execute_simulation()의 반환값
        ({'code', 'signal', 'reason', ...} 목록).
    cycle_id: PipelineContext.cycle_id — 다른 로그(sim_diag, money_*)와
        (cycle_id, code)로 조인하기 위한 키.
    """
    reason_map = {r['code']: r for r in simulation_results if r.get('code')}
    features = []
    for c in candidates:
        code = c.get('code')
        if not code:
            continue
        sim = reason_map.get(code, {})
        features.append({
            'cycle_id': cycle_id,
            'code': code,
            'name': c.get('name', ''),
            'fact_score': c.get('fact_score', 0.0),
            'sentiment': c.get('sentiment', 'Neutral'),
            'tick_power': c.get('tick_power', 0.0),
            'consecutive_days': c.get('consecutive_days', 1),
            'change_rate': _parse_change_rate(c.get('change_rate')),
            'engine_signal': sim.get('signal', ''),
            'engine_reason': sim.get('reason', ''),
        })
    return features


def rank_top(candidates: list[dict], n: int = 5) -> list[dict]:
    """fact_score·tick_power·change_rate를 순위로 결합해 상위 n개를 고르고
    rank(1~n)를 붙인다.

    ⚠ **이건 수익률 예측이 아니다.** 이 코드베이스 어디에도 검증된 수익률
    예측 모델이 없다(2026-08-11 확인 — algo_04_v2.py의 BUY/WATCH는 AND
    필터 통과 여부일 뿐, 통과한 종목 사이의 우열을 매기지 않는다). 여기
    세 신호는 각각 "근거가 얼마나 탄탄한가"(fact_score), "지금 매수세가
    얼마나 강한가"(tick_power), "지금 유리한 방향으로 움직이고 있는가"
    (change_rate)의 대리지표일 뿐이다. 실제로 이 랭킹이 수익률과 상관이
    있는지는 아직 검증되지 않았다 — build_features()가 남기는 로그가
    쌓여야 검증할 수 있다.

    candidates: code를 가진 dict 목록(이미 BUY/WATCH·중복제거 필터를 거친 것).
    빈 입력이면 빈 리스트. 동석 순위는 원래 순서를 유지한다(Python sort는
    안정 정렬이라 추가 처리 불필요).
    """
    if not candidates:
        return []

    def _rank_by(key_fn) -> dict:
        """값이 같으면 같은 순위를 준다(dense rank). 리스트에 들어온 순서로
        동석을 가르면, 신호가 전혀 없는(0인) 다수 종목이 우연히 앞쪽 순서에
        있다는 이유만으로 진짜 신호를 이긴다 — 실측으로 확인된 함정이다."""
        values = sorted({key_fn(c) for c in candidates}, reverse=True)
        value_rank = {v: i for i, v in enumerate(values)}
        return {c['code']: value_rank[key_fn(c)] for c in candidates}

    fact_rank = _rank_by(lambda c: c.get('fact_score', 0.0) or 0.0)
    tick_rank = _rank_by(lambda c: c.get('tick_power', 0.0) or 0.0)
    momentum_rank = _rank_by(lambda c: _parse_change_rate(c.get('change_rate')))

    def combined_rank(c: dict) -> int:
        code = c.get('code')
        worst = len(candidates)
        return (fact_rank.get(code, worst) + tick_rank.get(code, worst)
                + momentum_rank.get(code, worst))

    top = sorted(candidates, key=combined_rank)[:n]
    for i, c in enumerate(top):
        c['rank'] = i + 1
    return top


def _today() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d')


def month_path(today: str = None) -> str:
    """이번 달 로그의 쓰기 경로. sim_diag.month_path()와 같은 이유로 월별 분할."""
    d = ''.join(ch for ch in str(today or _today()) if ch.isdigit())
    ym = f"{d[:4]}-{d[4:6]}" if len(d) >= 6 else 'unknown'
    return os.path.join(DATA_DIR, f"pick_features_{ym}.csv")


def _move_stale_if_needed(path) -> bool:
    """헤더가 현재 COLUMNS와 다르면 옆으로 비켜놓는다. sim_diag.py와 동일 로직 —
    컬럼이 늘어난 뒤 옛 파일에 이어 쓰면 열이 조용히 어긋난다."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return True
    try:
        with open(path, encoding='utf-8') as f:
            head = f.readline().strip().lstrip('﻿').split(',')
    except Exception:
        return True
    if head == COLUMNS:
        return True
    base, ext = os.path.splitext(path)
    for i in range(1, 100):
        alt = f"{base}_v{i}{ext}"
        if not os.path.exists(alt):
            try:
                os.rename(path, alt)
                return True
            except Exception:
                return False
    return False


def _say(log, msg: str) -> None:
    try:
        log(msg)
    except Exception:
        pass


def log_features(features: list[dict], path: str = None, log=print) -> int:
    """피처 행들을 CSV에 이어 쓴다. 기록된 행 수 반환.

    Stage 3 나머지 로직(선정·시뮬레이터·프로그램 매매)을 절대 막지 않는다 —
    모든 예외를 삼키되, sim_diag.append()와 같은 이유로 실패 원인은
    조용히 넘기지 않고 로그에 남긴다(0을 돌려주는 세 갈래를 구분).
    """
    if not features:
        _say(log, '[pick_features] 기록할 행이 없습니다(후보 0개)')
        return 0
    try:
        path = path or month_path()
        if not _move_stale_if_needed(path):
            _say(log, f'[pick_features] 옛 헤더 파일을 비켜놓지 못해 이번 기록을 '
                      f'생략합니다 — {path}')
            return 0
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        ts = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S')
        is_new = not os.path.exists(path) or os.path.getsize(path) == 0
        with open(path, 'a', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            if is_new:
                w.writeheader()
            for r in features:
                row = {c: r.get(c, '') for c in COLUMNS}
                row['ts'] = ts
                w.writerow(row)
        return len(features)
    except Exception as e:
        _say(log, f'[pick_features] 기록 실패 — {type(e).__name__}: {e} (경로 {path})')
        return 0
