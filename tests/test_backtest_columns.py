"""월별 엑셀이 백테스트에 필요한 필드를 실어 나르는지 고정한다.

이 컬럼들이 없어서 심8은 '리포트 엑셀(추천 상위 2종목)'로 검증할 수밖에 없었다.
심8의 정보축·군중축은 횡단면 z-score라 유니버스가 다르면 같은 종목·같은 날이어도
다른 값이 된다 — 신호 재현 자체가 깨진다. 심9의 거래대금 필터, 심9-1의 거래대금 z도
같은 이유로 백테스트에서 적용하지 못했다.

수집은 이미 하고 있고 엑셀로 내보낼 때만 버려지고 있었다. 다시 빠지면 과거를
되살릴 방법이 없으므로(그때부터 축적이 끊긴다) 테스트로 못 박는다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from src.strategy.analyzer import analyze_discussion_trend


@pytest.fixture(autouse=True)
def chdir_tmp(tmp_path, monkeypatch):
    """analyze_discussion_trend가 과거 이력 비교용으로 data/의 엑셀을 읽는다.
    로컬에 쌓인 파일에 결과가 좌우되지 않도록 빈 디렉터리에서 돌린다."""
    monkeypatch.chdir(tmp_path)

# 심이 실제로 쓰는 필드 → 엑셀 한글 컬럼
REQUIRED = {
    'amount': '거래대금',
    'w52_hgpr': '52주최고',
    'w52_lwpr': '52주최저',
    'frgn_fake_ntby_qty': '외인추정순매수',
    'orgn_fake_ntby_qty': '기관추정순매수',
    'open_price': '시가',
    'day_high': '당일고가',
    'day_low': '당일저가',
    'unique_posters': '고유작성자',
}


def _candidate(**kw):
    s = {
        'code': '002990', 'name': '금호건설', 'price': 5060, 'change_rate': '+3.20%',
        'prev_close': 4900, 'open_price': 5300, 'day_high': 5400, 'day_low': 5010,
        'amount': 12_300_000_000, 'w52_hgpr': 6000, 'w52_lwpr': 3100,
        'frgn_fake_ntby_qty': 12_000, 'orgn_fake_ntby_qty': -3_000,
        'recent_posts_count': 273, 'unique_posters': 91,
        'foreign_rate': 5.1, 'foreign_change': 0.3, 'prev_foreign_rate': 4.8,
        'consecutive_days': 2, 'status': '활성', 'posts_summary': '요약', 'market': 'KOSPI',
    }
    s.update(kw)
    return s


def test_backtest_columns_survive_to_excel():
    df, _ = analyze_discussion_trend([_candidate(), _candidate(code='065170', name='비엘팜텍')])
    missing = [kor for kor in REQUIRED.values() if kor not in df.columns]
    assert not missing, f"엑셀에서 누락된 백테스트 컬럼: {missing}"


def test_backtest_column_values_are_preserved():
    """이름만 살아남고 값이 비면 소용없다."""
    df, _ = analyze_discussion_trend([_candidate()])
    row = df.iloc[0]
    assert row['거래대금'] == 12_300_000_000
    assert row['52주최고'] == 6000 and row['52주최저'] == 3100
    assert row['외인추정순매수'] == 12_000 and row['기관추정순매수'] == -3_000
    assert row['시가'] == 5300 and row['당일고가'] == 5400 and row['당일저가'] == 5010
    assert row['고유작성자'] == 91
