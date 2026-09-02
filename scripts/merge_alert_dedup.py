# -*- coding: utf-8 -*-
"""알림 쿨다운 기록(`data/alert_dedup.json`)을 db-data에 **병합**해 올린다.

    python3 scripts/merge_alert_dedup.py <db-data쪽 파일> <이번 런의 파일>

왜 cp가 아니라 병합인가:

이 파일은 **writer가 셋이다** — trading.yml·scraper.yml·us_trading.yml이 모두
알림을 낸다. 셋이 각자 `cp`로 통째로 밀면 마지막에 push한 런의 **시작 시점 사본**만
남고, 그 사이 다른 워크플로가 적은 쿨다운은 사라진다(lost update). 그러면 억제가
무력화돼 같은 장애가 2분마다 나간다 — 도배는 침묵과 같다.

2026-09-02 실측: eod_batch_stale(쿨다운 480분)이 09:00:34 발송 → 09:02:44 억제
→ 09:04:31 **또 발송**. src/alerts.py의 state_was_written()이 "정확히 고치려면
배포가 cp가 아니라 키별 병합이어야 한다"고 적어 둔 그 자리다.

병합 규칙:
  - 쿨다운 타임스탬프: **더 나중 것이 이긴다.** 되돌림은 항상 '더 자주 울림'
    방향으로 틀린다. 늦은 쪽을 택하면 최악이라도 '덜 울림'이고, 그건
    bump_outage_streak가 이미 택한 방향이다.
  - `_outage_streak`: **로컬이 이긴다(지금 동작 유지).** max로 병합하면 정상
    복구(0 리셋)가 영원히 안 남아 *없는 장애를 알리는* 반대 방향으로 틀린다.
    이번 수정 범위는 쿨다운 타임스탬프뿐이다.

표준 라이브러리만 쓴다 — 배포 스텝은 pip install 앞에 있을 수 있다.
"""
import json
import sys

STREAK_KEY = '_outage_streak'


def merge(remote, local) -> dict:
    """db-data의 기록(remote)과 이번 런의 기록(local)을 키별로 합친다."""
    if not isinstance(remote, dict):
        return local if isinstance(local, dict) else {}
    if not isinstance(local, dict):
        return remote

    out = dict(remote)
    for key, value in local.items():
        if key == STREAK_KEY:
            out[key] = value          # 지금 동작 유지 — 위 주석 참고
            continue
        previous = out.get(key)
        # 타임스탬프는 ISO 8601이라 문자열 비교가 곧 시각 비교다.
        if isinstance(previous, str) and isinstance(value, str):
            out[key] = max(previous, value)
        else:
            out[key] = value
    return out


def _load(path: str):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def merge_files(remote_path: str, local_path: str, log=print) -> bool:
    """local을 remote에 병합해 remote_path에 쓴다. 로컬이 없으면 아무것도 안 한다."""
    local = _load(local_path)
    if local is None:
        log('[MergeDedup] 이번 런의 쿨다운 기록 없음 — 병합 생략')
        return False
    merged = merge(_load(remote_path), local)
    with open(remote_path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False)
    log(f'[MergeDedup] 쿨다운 기록 병합 완료 (키 {len(merged)}개)')
    return True


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    merge_files(sys.argv[1], sys.argv[2])
