"""KIS 개장일 달력 판정 테스트."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.market_calendar import parse_calendar, lookup


def test_parse_calendar_extracts_opnd_yn():
    """chk-holiday 응답에서 개장일여부(opnd_yn)만 뽑는다."""
    response = {
        'rt_cd': '0',
        'output': [
            {'bass_dt': '20260717', 'wday_dvsn_cd': '06', 'bzdy_yn': 'N',
             'tr_day_yn': 'N', 'opnd_yn': 'N', 'setl_day_yn': 'N'},
            {'bass_dt': '20260720', 'wday_dvsn_cd': '02', 'bzdy_yn': 'Y',
             'tr_day_yn': 'Y', 'opnd_yn': 'Y', 'setl_day_yn': 'Y'},
        ],
    }
    assert parse_calendar(response) == {'20260717': 'N', '20260720': 'Y'}


def test_parse_calendar_ignores_tr_day_yn():
    """개장 판정은 opnd_yn만 본다. tr_day_yn이 달라도 결과는 opnd_yn을 따른다."""
    response = {
        'rt_cd': '0',
        'output': [
            {'bass_dt': '20260717', 'bzdy_yn': 'Y', 'tr_day_yn': 'Y',
             'opnd_yn': 'N', 'setl_day_yn': 'Y'},
        ],
    }
    assert parse_calendar(response) == {'20260717': 'N'}


def test_parse_calendar_empty_output():
    assert parse_calendar({'rt_cd': '0', 'output': []}) == {}


def test_parse_calendar_skips_incomplete_rows():
    """필드가 빠진 행은 버린다 — 가짜 판정을 만들지 않는다."""
    response = {
        'output': [
            {'bass_dt': '20260717'},                  # opnd_yn 없음
            {'opnd_yn': 'Y'},                          # bass_dt 없음
            {'bass_dt': '20260720', 'opnd_yn': 'Y'},   # 정상
        ],
    }
    assert parse_calendar(response) == {'20260720': 'Y'}


def test_lookup_open_day():
    assert lookup({'20260720': 'Y'}, '20260720') is True


def test_lookup_closed_day():
    assert lookup({'20260717': 'N'}, '20260717') is False


def test_lookup_missing_key_is_none():
    """달력에 없는 날은 판정 불가(None)다. False가 아니다."""
    assert lookup({'20260717': 'N'}, '20261231') is None


def test_lookup_empty_calendar_is_none():
    assert lookup({}, '20260717') is None
