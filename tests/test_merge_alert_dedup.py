# -*- coding: utf-8 -*-
"""알림 쿨다운 기록은 덮어쓰기가 아니라 **키별 병합**으로 배포돼야 한다.

2026-09-02 실측: eod_batch_stale(쿨다운 480분)이 09:00:34 발송 → 09:02:44 억제
→ 09:04:31 **또 발송**. 사이에 scraper.yml의 `cp data/*.json`이 런 시작 사본을
밀어넣어 09:02의 기록을 지웠다. writer가 셋인 파일(trading/scraper/us_trading)을
각자 통째로 덮어쓰면 마지막 사본만 남는다.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import merge_alert_dedup as m


def test_원격에만_있는_쿨다운_기록을_지우지_않는다():
    """이게 도배의 직접 원인이었다."""
    remote = {"eod_batch_stale": "2026-09-02T09:02:44"}
    local = {"field_outage": "2026-09-02T08:00:00"}

    out = m.merge(remote, local)

    assert out["eod_batch_stale"] == "2026-09-02T09:02:44"
    assert out["field_outage"] == "2026-09-02T08:00:00"


def test_같은_키는_더_나중_기록이_이긴다():
    """되돌림은 항상 더 자주 울리는 방향으로 틀린다. 늦은 쪽을 택하면
    최악이라도 '덜 울림'이다 — bump_outage_streak가 택한 것과 같은 방향."""
    remote = {"eod_batch_stale": "2026-09-02T09:04:31"}
    local = {"eod_batch_stale": "2026-09-02T09:00:34"}   # 런 시작 사본

    assert m.merge(remote, local)["eod_batch_stale"] == "2026-09-02T09:04:31"


def test_로컬이_더_나중이면_로컬이_이긴다():
    remote = {"eod_batch_stale": "2026-09-02T09:00:34"}
    local = {"eod_batch_stale": "2026-09-02T09:04:31"}

    assert m.merge(remote, local)["eod_batch_stale"] == "2026-09-02T09:04:31"


def test_결손_연속_카운터는_로컬이_이긴다():
    """`_outage_streak`는 지금 동작을 바꾸지 않는다.

    alerts.bump_outage_streak의 주석이 '밀리면 덜 울리는 쪽으로 틀린다'를 의도로
    적어 뒀다. max로 병합하면 정상 복구(0으로 리셋)가 영원히 안 남아 **없는 장애를
    알리는** 반대 방향으로 틀린다. 이번 수정 범위는 쿨다운 타임스탬프뿐이다.
    """
    remote = {"_outage_streak": {"field_outage": 5}}
    local = {"_outage_streak": {"field_outage": 0}}      # 이번 런은 정상

    assert m.merge(remote, local)["_outage_streak"] == {"field_outage": 0}


def test_깨진_원격_파일은_로컬로_대체한다():
    assert m.merge(None, {"a": "1"}) == {"a": "1"}
    assert m.merge({"a": "1"}, None) == {"a": "1"}


def test_파일_병합_왕복(tmp_path):
    remote = tmp_path / "remote.json"
    local = tmp_path / "local.json"
    remote.write_text(json.dumps({"eod_batch_stale": "2026-09-02T09:04:31"}), encoding="utf-8")
    local.write_text(json.dumps({"field_outage": "2026-09-02T08:00:00"}), encoding="utf-8")

    m.merge_files(str(remote), str(local))

    out = json.loads(remote.read_text(encoding="utf-8"))
    assert out["eod_batch_stale"] == "2026-09-02T09:04:31"
    assert out["field_outage"] == "2026-09-02T08:00:00"
