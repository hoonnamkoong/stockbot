# -*- coding: utf-8 -*-
"""프리마켓 뉴스 적재 — 커버리지 실패를 '뉴스 없음'으로 바꾸지 않는다.

2026-09-18부터 item/news_news가 HTTP 410이었다. 수집기는 페이지마다 None을 받아
covered=False로 **정직하게** 적었지만, 기사 0건 CSV가 매일 배포됐고 아무도 몰랐다.
이제 naver_api.news_page(JSON)로 긁는다.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import scripts.fetch_naver_news as fnn  # noqa: E402


def _serve(monkeypatch, pages):
    """pages: {page번호: news_page 반환값}. 없는 페이지는 빈 목록(목록 끝)."""
    calls = []

    def fake(code, page, **kw):
        calls.append(page)
        return pages.get(page, [])

    monkeypatch.setattr(fnn.naver_api, 'news_page', fake)
    monkeypatch.setattr(fnn.time, 'sleep', lambda _s: None)
    return calls


def _row(dt):
    return {'dt': dt, 'src': '언론사', 'title': '제목'}


def test_목표일에_닿으면_멈추고_커버로_친다(monkeypatch):
    calls = _serve(monkeypatch, {1: [_row('2026.09.21 08:00'), _row('2026.09.18 10:00')],
                                 2: [_row('2026.09.13 09:00')],
                                 3: [_row('2026.09.10 09:00')]})
    rows, covered = fnn.fetch('005930', '2026.09.14')
    assert covered is True
    assert calls == [1, 2]
    assert rows[0] == ('2026.09.21 08:00', '언론사', '제목')


def test_목록_끝은_전부_본_것이다(monkeypatch):
    _serve(monkeypatch, {1: [_row('2026.09.21 08:00')]})
    rows, covered = fnn.fetch('043260', '2026.09.14')
    assert covered is True and len(rows) == 1


def test_못_얻은_페이지는_커버로_치지_않는다(monkeypatch):
    """410 시절의 모양 — 전 페이지 None. '뉴스 없음'이 아니라 커버 실패다."""
    _serve(monkeypatch, {p: None for p in range(1, fnn.MAX_PAGES + 1)})
    rows, covered = fnn.fetch('005930', '2026.09.14')
    assert covered is False and rows == []
