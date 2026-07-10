import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from src.data import adopted_registry as reg


@pytest.fixture(autouse=True)
def chdir_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_no_file_returns_empty():
    assert reg.load('20260710') == {}


def test_roundtrip_same_day():
    reg.save('20260710', {'002990': {'name': '금호건설'}})
    assert reg.load('20260710') == {'002990': {'name': '금호건설'}}


def test_date_change_resets():
    """어제 채택분이 오늘로 넘어오면 안 된다."""
    reg.save('20260709', {'002990': {'name': '금호건설'}})
    assert reg.load('20260710') == {}


def test_corrupt_file_returns_empty():
    os.makedirs('data', exist_ok=True)
    with open(reg.PATH, 'w', encoding='utf-8') as f:
        f.write('{ broken')
    assert reg.load('20260710') == {}


def test_valid_json_non_dict_list_returns_empty():
    """유효한 JSON이지만 dict가 아닌 경우 (배열)"""
    os.makedirs('data', exist_ok=True)
    with open(reg.PATH, 'w', encoding='utf-8') as f:
        json.dump([], f)
    assert reg.load('20260710') == {}


def test_valid_json_non_dict_null_returns_empty():
    """유효한 JSON이지만 dict가 아닌 경우 (null)"""
    os.makedirs('data', exist_ok=True)
    with open(reg.PATH, 'w', encoding='utf-8') as f:
        json.dump(None, f)
    assert reg.load('20260710') == {}
