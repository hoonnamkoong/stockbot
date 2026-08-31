"""발송 슬롯 게이트 — 브리핑 슬롯을 놓치지 않는다.

================================================================
왜 분 창이 아니라 슬롯 상태인가
================================================================
예전 판정은 `PipelineContext.should_notify()`의 "파이썬 시작 분이 0~2인가"
하나였다. 그런데 그 값은 디스패치 + 큐 대기 + 워크플로 셋업(체크아웃·pip·토큰,
실측 약 50초) 뒤의 시각이고, 셋업 시간이 런마다 몇 초씩 흔들린다.

2026-08-07에 스크래핑 격자가 밀리면서 정각 리포트가 하루 7회에서 3회로 줄었다.
57% 누락인데 워크플로는 내내 초록색이었다 — 로그에는 "발송 스킵"만 남는다.

하루 7회 시절에는 한 번 놓쳐도 1시간 뒤에 또 왔다. **하루 2회가 되면 한 번
놓치는 게 50% 손실이다.** 그래서 판정을 시각의 함수에서 상태의 함수로 바꾼다:

    슬롯 시각이 지났고 + 아직 그 슬롯을 안 보냈으면 → 열린다

스크래핑이 10분 격자이므로 40분 창 안에 :00 :10 :20 :30 네 번의 기회가 있다.
셋업이 얼마나 흔들리든 그중 하나는 잡힌다.

================================================================
여기서 하지 않는 것
================================================================
  - **무엇을 보낼지**: 이 모듈은 "지금 보낼 차례인가"만 답한다.
"""
import json
import os
from datetime import datetime

# 2026-08-31: 11:00·14:00 리포트를 폐기하면서 브리핑을 둘로 늘렸다.
# 12:00은 09:00~12:00 구간, 15:00은 하루 전체 마감이다. 슬롯마다 제목과
# 집계 구간이 다르므로 brief_due는 bool이 아니라 **어느 슬롯인지**를 준다.
BRIEF_SLOTS = ('12:00', '15:00')

# 슬롯 시각으로부터 이 시간 안에만 보낸다. 12:40을 넘겨 보내면 그건 '12시
# 브리핑'이 아니다 — 늦은 브리핑보다 없는 편이 낫다. 스크래핑 격자(10분)의
# 네 배라 재시도 기회가 네 번이다.
SLOT_WINDOW_MIN = 40

STATE_FILENAME = 'report_gate_state.json'

DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data')


def _state_path(data_dir: str | None, filename: str = STATE_FILENAME) -> str:
    return os.path.join(data_dir or DEFAULT_DATA_DIR, filename)


def _slot_minutes(slot: str) -> int:
    h, m = slot.split(':')
    return int(h) * 60 + int(m)


def _sent_today(now, data_dir: str | None, filename: str = STATE_FILENAME) -> list[str]:
    """오늘 이미 보낸 슬롯들. 못 읽으면 빈 목록(=보내는 쪽)이다.

    **날짜로 갈라야 한다.** 이 상태는 db-data를 왕복하므로 컨테이너에는 어제
    기록이 들어 있다. 날짜를 안 보면 어제 11시를 보냈다는 이유로 오늘 11시가
    통째로 사라진다.
    """
    try:
        with open(_state_path(data_dir, filename), 'r', encoding='utf-8') as f:
            raw = json.load(f)
        if raw.get('date') != now.strftime('%Y-%m-%d'):
            return []
        sent = raw.get('sent')
        return [str(s) for s in sent] if isinstance(sent, list) else []
    except Exception:
        # 모르면 보내는 쪽으로 fail한다. 하루 2회라 소실 1건이 중복 1건보다
        # 비싸다(scrape_gate가 '모르면 스크래핑'으로 fail하는 것과 같은 방향).
        return []


def _due(now_kst: datetime, slots, data_dir: str | None,
         filename: str = STATE_FILENAME) -> str | None:
    """주어진 슬롯들 중 지금 열려 있는 것. 늦은 슬롯을 우선한다.

    두 슬롯이 동시에 열릴 수는 없다 — 창(40분)이 슬롯 간격(3시간)보다 짧다.
    그래도 늦은 쪽을 먼저 보는 이유는, 12시를 통째로 놓친 채 15시에 들어왔을 때
    3시간 지난 12시 브리핑이 아니라 15시 브리핑이 나가야 하기 때문이다.
    """
    now_min = now_kst.hour * 60 + now_kst.minute
    sent = _sent_today(now_kst, data_dir, filename)
    for slot in sorted(slots, key=_slot_minutes, reverse=True):
        if slot in sent:
            continue
        start = _slot_minutes(slot)
        if start <= now_min < start + SLOT_WINDOW_MIN:
            return slot
    return None


def brief_due(now_kst: datetime, data_dir: str | None = None) -> str | None:
    """지금 열려 있는 브리핑 슬롯('12:00'/'15:00'), 없으면 None.

    두 브리핑은 서로 독립이다 — 12시를 보냈다는 사실이 15시 마감 브리핑을
    막지 않는다.
    """
    return _due(now_kst, BRIEF_SLOTS, data_dir)


def mark_sent(slot: str, now_kst: datetime, data_dir: str | None = None,
              filename: str = STATE_FILENAME) -> None:
    """그 슬롯을 보냈다고 기록한다. **발송에 성공한 직후에만 부른다.**

    실패한 발송을 기록하면 그 회차가 통째로 사라진다 — 창이 아직 열려 있으면
    다음 스크래핑 사이클이 재시도할 수 있어야 한다(scrape_gate.mark_scraped와
    같은 이유로 순서를 뒤집으면 안 된다).
    """
    path = _state_path(data_dir, filename)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    sent = _sent_today(now_kst, data_dir, filename)
    if slot not in sent:
        sent.append(slot)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'date': now_kst.strftime('%Y-%m-%d'),
                   'sent': sorted(sent, key=_slot_minutes),
                   'last_sent_at': now_kst.isoformat()}, f, ensure_ascii=False)
