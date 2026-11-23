# -*- coding: utf-8 -*-
"""국면 판정의 채점표 — 확정된 하루를 한 줄로 쌓는다.

왜 필요했나: 2026-11-23에 "시장 판단 정확도는 확인했어?"라는 질문에 답이
'아니오'였다. 손으로 79일을 재생해서야 "단계가 이후 수익률을 가르지 못한다"를
알았다. **재는 루틴이 없었기 때문**이다 —
  - `calibration_log`는 breadth만 쟀고, 그 값은 이제 국면 결정에 쓰이지 않는다
  - `regime_observations_*.csv`는 옛 3단계 필드(breadth/momentum/trend)만 적는다
  - regime6의 level·vol10과 그 **이후에 실제로 일어난 일**을 잇는 기록이 없었다

루틴이 없으면 다섯 달 뒤에 같은 질문이 또 손계산으로 돌아온다.

**왜 그날의 일간수익률(ret1)까지 적나.** `kospi_top100_close.csv`는 100행
롤링이라 창 밖으로 밀린 날의 수익률은 **되계산할 수 없다**. 반면 하루치 등가중
수익률 한 숫자만 보존하면 임의 구간의 누적수익률도 실현변동성도 전부 복원된다.
판정과 결과를 잇는 데 필요한 최소 숫자다.

읽는 쪽은 `scripts/score_regime.py`다.
"""
import os

FILENAME = 'regime6_scorecard.csv'
HEADER = 'date,level,label,D,ab20,ret10,vol10,ret1,confirmed_since'

# 지표가 없는 날(판정 불가)은 **빈 칸**이다. 0으로 채우면 '변동성 0인 날'이 되어
# 채점이 거짓말을 한다 — 이 레포의 금융 수치 원칙과 같다.
_FIELDS = ('D', 'ab20', 'ret10', 'vol10', 'ret1')


def _num(x):
    if x is None:
        return ''
    try:
        return repr(round(float(x), 6)) if float(x) % 1 else repr(float(x))
    except (TypeError, ValueError):
        return ''


def build_row(base, label) -> str | None:
    """확정 상태 한 날치 → CSV 한 줄. 날짜가 없으면 None(쓸 것이 없다).

    `base`는 `advance_regime6`가 돌려주는 `state['base']`다.
    `label`은 `regime6_label(level, vol10)` 결과이며 vol10을 모르면 None일 수 있다 —
    그때도 단계는 남길 가치가 있으므로 라벨 칸만 비운다.
    """
    if not isinstance(base, dict):
        return None
    date = str(base.get('date') or '')
    if len(date) != 10:
        return None
    m = base.get('metrics')
    if not isinstance(m, dict):
        m = {}
    cells = [date, str(base.get('level', '')), str(label or '')]
    cells += [_num(m.get(k)) for k in _FIELDS]
    cells.append(str(base.get('confirmed_since') or ''))
    return ','.join(cells)


def append_row(path: str, row: str | None, header: str = HEADER) -> bool:
    """하루 한 줄만 쌓는다. 이미 그 날짜가 있으면 쓰지 않는다(False).

    루프는 2분 격자로 돌고 같은 확정일을 여러 번 본다. 중복을 쌓으면 채점이
    그날에 가중된다.

    **예외를 올리지 않는다.** 이 함수는 국면 갱신 경로에서 돌기 때문에, 여기서
    터지면 채점표 하나 때문에 국면이 멈춘다 — 원래 막으려던 것보다 나쁘다.
    """
    if not row:
        return False
    try:
        date = row.split(',', 1)[0]
        existing = ''
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                existing = f.read()
            for line in existing.splitlines():
                if line.split(',', 1)[0] == date:
                    return False
        with open(path, 'a', encoding='utf-8', newline='') as f:
            if not existing.strip():
                f.write(header + '\n')
            f.write(row + '\n')
        return True
    except Exception:
        return False
