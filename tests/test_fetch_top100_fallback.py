"""EOD 종가 수집이 네이버 한 곳에 목숨을 걸면 안 된다.

2026-08-03 EOD 런은 finance.naver.com ConnectTimeout 3연속으로 통째로 죽었고,
그 바람에 심9-1(돈치안)이 실행되지 않았으며 종가·OHLCV CSV도 07-31에서 멈췄다.
종목 구성은 하루 사이 거의 바뀌지 않으므로, 네이버가 막히면 직전 실행이 남긴
CSV 헤더에서 유니버스를 복원하고 OHLCV는 KIS로 정상 수집한다.
(복원되는 것은 '어떤 종목을 볼지'뿐이다. 시세는 전부 그날의 KIS 실측이다.)
"""
import csv
import importlib.util
import os
import sys
from pathlib import Path

import pytest
import requests

SCRIPT = Path(__file__).resolve().parent.parent / 'scratch' / 'fetch_kospi_top100.py'


def load_module():
    os.environ.setdefault('KIS_APP_KEY', 'test-key')
    os.environ.setdefault('KIS_APP_SECRET', 'test-secret')
    spec = importlib.util.spec_from_file_location('fetch_kospi_top100_under_test', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_previous_csv(root: Path, n: int = 100):
    out = root / 'output'
    out.mkdir(parents=True, exist_ok=True)
    header = ['date'] + [f'{i:06d}_종목{i}' for i in range(1, n + 1)]
    with (out / 'kospi_top100_close.csv').open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerow(['20260731'] + ['1000'] * n)


def test_falls_back_to_previous_universe_when_naver_unreachable(monkeypatch, tmp_path):
    """네이버가 막히면 직전 CSV의 종목 구성으로 계속 간다."""
    mod = load_module()
    monkeypatch.chdir(tmp_path)
    write_previous_csv(tmp_path)

    def boom(*a, **kw):
        raise requests.exceptions.ConnectTimeout('naver unreachable from runner')

    monkeypatch.setattr(mod.requests, 'get', boom)
    monkeypatch.setattr(mod.time, 'sleep', lambda *_: None)

    stocks = mod.fetch_top100_by_trade_amount('token')

    assert len(stocks) == 100
    assert stocks[0]['code'] == '000001'
    assert stocks[0]['name'] == '종목1'


def test_raises_when_naver_down_and_no_previous_csv(monkeypatch, tmp_path):
    """복원할 것이 없으면 조용히 빈 목록을 반환하지 않고 그대로 실패한다."""
    mod = load_module()
    monkeypatch.chdir(tmp_path)

    def boom(*a, **kw):
        raise requests.exceptions.ConnectTimeout('naver unreachable from runner')

    monkeypatch.setattr(mod.requests, 'get', boom)
    monkeypatch.setattr(mod.time, 'sleep', lambda *_: None)

    with pytest.raises(requests.RequestException):
        mod.fetch_top100_by_trade_amount('token')


def test_naver_success_path_is_unchanged(monkeypatch, tmp_path):
    """네이버가 살아 있으면 폴백은 개입하지 않는다."""
    mod = load_module()
    monkeypatch.chdir(tmp_path)
    write_previous_csv(tmp_path)

    row = ('<tr><td>1</td><td><a href="/item/main.naver?code=005930">삼성전자</a></td>'
           '<td>239,500</td><td>1</td><td>2</td></tr>')
    html = ('<table class="type_2">' + row + '</table>').encode('euc-kr')

    class Res:
        content = html

    monkeypatch.setattr(mod.requests, 'get', lambda *a, **kw: Res())
    monkeypatch.setattr(mod.time, 'sleep', lambda *_: None)

    stocks = mod.fetch_top100_by_trade_amount('token')

    assert stocks[0]['code'] == '005930'
    assert stocks[0]['name'] == '삼성전자'
