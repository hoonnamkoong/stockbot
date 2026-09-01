"""결과 감시 — "오늘 이 시스템이 존재 이유대로 동작했는가".

================================================================
왜 이게 따로 필요한가
================================================================
2026-08-30에 고장이 세 종류라는 걸 정리했다.
  ① 런이 빨갛다        → 실패 알림이 잡는다
  ② 초록인데 안 돌았다  → cron 미발화 감지기가 잡는다
  ③ 돌았는데 산출물이 없다 → 신선도 감사가 잡는다

그런데 신선도 감사(config/data_freshness.yaml)가 보는 10개는 **전부 입력·중간
산출물**이다(유니버스·감시목록·지수·국면). 매매 결과는 하나도 없다. 심 상태
파일을 일부러 뺐기 때문이다 — "값이 바뀔 때만 커밋돼 안 사고 안 판 심이 정지처럼
보인다"는 이유였고, 그 관찰은 옳았다.

**옳은 관찰이었지만 잘못된 결론이었다.** 개별 심의 0건은 정상이다. 하지만
**전 심 합계 0건**은 다르다. 개장일에 열몇 개 심이 서로 다른 전략으로 돌면서
단 한 건도 못 샀다면, 그건 시장이 그런 게 아니라 배선이 죽은 것이다. 지표를
고치는 대신 지표를 없앤 자리가 여기다.

2026-09-01 실전 매매 0건도 이 감시가 있었으면 장중에 알았다.

================================================================
여기서 하지 않는 것
================================================================
  - **개별 심 판정.** 심 하나가 0건인 건 정상이라 알리지 않는다.
  - **원인 규명.** "왜 안 샀나"는 각 심의 깔때기 로그가 답한다. 여기는
    "아무도 안 샀다"만 말한다.
  - **숫자 지어내기.** 거래이력을 못 읽으면 0이 아니라 None이다. 파일이 없어서
    0인 것과 못 읽어서 모르는 것은 다르다.
"""
import csv
import os

from src.strategy.registry import get_sim_registry

# 이 시각을 지나야 판정한다. 개장 직후의 0건은 정상이다 — 아직 아무 일도 안
# 일어났을 뿐이다. 14:00이면 정규장 5시간이 지났고, 마감(15:30)까지 아직
# 사람이 손쓸 시간이 남는다.
CHECKPOINT_HHMM = '14:00'


def _count_rows(path: str, today_str: str):
    """오늘 거래 건수. 파일이 없으면 0(정상: 아직 안 샀다), 못 읽으면 None."""
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return sum(1 for row in csv.DictReader(f)
                       if (row.get('timestamp') or '').startswith(today_str))
    except FileNotFoundError:
        return 0
    except Exception:
        return None


def count_trades_by_sim(data_dir: str, today_str: str) -> dict:
    """심별 오늘 거래 건수. 값이 None이면 **측정 불가**(0이 아니다).

    심 목록은 매니페스트에서 파생한다 — 자체 목록을 들면 새 심이 조용히 빠진다.
    """
    return {
        s['label']: _count_rows(os.path.join(data_dir, s['csv_file']), today_str)
        for s in get_sim_registry()
    }


def outcome_verdict(counts: dict, now_hhmm: str) -> str | None:
    """알려야 하면 메시지, 아니면 None. 순수 함수 — I/O 없음.

    조건은 셋 다 만족해야 한다.
      1. 체크포인트 시각을 지났다
      2. **읽을 수 있었던** 심이 하나라도 있다(전부 측정 불가면 이건 매매 문제가
         아니라 데이터 문제다 — 다른 알림이 잡을 일이고, 여기서 "0건"이라고
         말하면 거짓말이 된다)
      3. 읽힌 심의 합계가 0이다
    """
    if now_hhmm < CHECKPOINT_HHMM:
        return None

    readable = {k: v for k, v in counts.items() if v is not None}
    unreadable = [k for k, v in counts.items() if v is None]

    if not readable:
        return None
    if sum(readable.values()) > 0:
        return None

    lines = [
        '<b>매매 0건</b>',
        '',
        f'{now_hhmm} 기준 심 {len(readable)}개가 오늘 단 한 건도 매매하지 않았습니다.',
        '개별 심의 0건은 정상이지만 전 심 합계 0건은 배선 고장일 가능성이 큽니다.',
        '',
        '확인 순서:',
        '  1. trading.yml 최근 런에서 kr=true가 찍혔는가',
        '  2. 국면(읽기 전용) 로그가 SIDEWAYS/BULL/BEAR 중 하나인가 (판정 불가 아님)',
        '  3. 각 심의 깔때기 로그에 후보 수가 0이 아닌가',
    ]
    if unreadable:
        lines += ['', f'⚠️ 측정 불가 {len(unreadable)}개: {", ".join(unreadable[:5])}']
    return '\n'.join(lines)
