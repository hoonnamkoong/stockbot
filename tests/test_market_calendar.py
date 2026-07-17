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


import json

import pytest

import src.market_calendar as mc


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_fetch_calendar_sends_correct_tr_id(monkeypatch):
    """chk-holiday는 TR CTCA0903R로 실전 도메인에 조회한다."""
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        captured['url'] = url
        captured['headers'] = headers
        captured['params'] = params
        return _FakeResponse({
            'rt_cd': '0',
            'output': [{'bass_dt': '20260717', 'opnd_yn': 'N'}],
        })

    monkeypatch.setattr(mc.requests, 'get', fake_get)

    days = mc.fetch_calendar('TOKEN', 'KEY', 'SECRET', '20260717')

    assert days == {'20260717': 'N'}
    assert captured['headers']['tr_id'] == 'CTCA0903R'
    assert captured['headers']['authorization'] == 'Bearer TOKEN'
    assert captured['headers']['appkey'] == 'KEY'
    assert captured['params']['BASS_DT'] == '20260717'
    assert 'openapi.koreainvestment.com:9443' in captured['url']


def test_fetch_calendar_raises_on_api_error(monkeypatch):
    """rt_cd가 0이 아니면 예외다 — 빈 달력으로 폴백하지 않는다."""
    monkeypatch.setattr(mc.requests, 'get', lambda *a, **k: _FakeResponse(
        {'rt_cd': '1', 'msg1': 'EGW00123 토큰 오류'}
    ))
    with pytest.raises(RuntimeError, match='EGW00123'):
        mc.fetch_calendar('TOKEN', 'KEY', 'SECRET', '20260717')


def test_fetch_calendar_raises_on_empty_calendar(monkeypatch):
    """rt_cd=0인데 달력이 비면 예외다 — 판정 불가로 이어져야 한다."""
    monkeypatch.setattr(mc.requests, 'get', lambda *a, **k: _FakeResponse(
        {'rt_cd': '0', 'output': []}
    ))
    with pytest.raises(RuntimeError, match='비어'):
        mc.fetch_calendar('TOKEN', 'KEY', 'SECRET', '20260717')


def test_save_then_load_roundtrip(tmp_path):
    path = str(tmp_path / 'market_calendar.json')
    mc.save_calendar({'20260717': 'N', '20260720': 'Y'}, path=path)

    assert mc.load_calendar(path=path) == {'20260717': 'N', '20260720': 'Y'}

    saved = json.loads(open(path, encoding='utf-8').read())
    assert 'updated_at' in saved
    assert saved['days']['20260717'] == 'N'


def test_load_calendar_missing_file_returns_empty(tmp_path):
    """파일이 없으면 빈 맵 — lookup이 None(판정 불가)을 내도록."""
    assert mc.load_calendar(path=str(tmp_path / 'nope.json')) == {}


def test_load_calendar_corrupt_file_returns_empty(tmp_path):
    path = tmp_path / 'broken.json'
    path.write_text('{not json', encoding='utf-8')
    assert mc.load_calendar(path=str(path)) == {}


def test_load_access_token_missing_file(tmp_path):
    assert mc.load_access_token(path=str(tmp_path / 'nope.json')) is None


def test_load_access_token_reads_cache(tmp_path):
    path = tmp_path / 'token.json'
    path.write_text(json.dumps({'access_token': 'ABC'}), encoding='utf-8')
    assert mc.load_access_token(path=str(path)) == 'ABC'


def test_refresh_calendar_raises_without_credentials(monkeypatch):
    monkeypatch.delenv('KIS_APP_KEY', raising=False)
    monkeypatch.delenv('KIS_APP_SECRET', raising=False)
    with pytest.raises(RuntimeError, match='KIS_APP_KEY'):
        mc.refresh_calendar('20260717')


def test_refresh_calendar_raises_without_token(monkeypatch):
    monkeypatch.setenv('KIS_APP_KEY', 'KEY')
    monkeypatch.setenv('KIS_APP_SECRET', 'SECRET')
    monkeypatch.setattr(mc, 'load_access_token', lambda *a, **k: None)
    with pytest.raises(RuntimeError, match='토큰'):
        mc.refresh_calendar('20260717')


def test_refresh_calendar_fetches_and_saves(monkeypatch, tmp_path):
    path = str(tmp_path / 'market_calendar.json')
    monkeypatch.setenv('KIS_APP_KEY', 'KEY')
    monkeypatch.setenv('KIS_APP_SECRET', 'SECRET')
    monkeypatch.setattr(mc, 'load_access_token', lambda *a, **k: 'TOKEN')
    monkeypatch.setattr(mc, 'CALENDAR_PATH', path)
    monkeypatch.setattr(mc, 'fetch_calendar',
                        lambda *a, **k: {'20260717': 'N'})

    days = mc.refresh_calendar('20260717')

    assert days == {'20260717': 'N'}
    assert mc.load_calendar(path=path) == {'20260717': 'N'}
