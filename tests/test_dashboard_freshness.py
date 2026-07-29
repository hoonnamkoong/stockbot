"""db-data를 읽는 라우트가 CDN을 다시 무력화하지 않는지 지킨다.

대시보드 1회 로드가 GitHub raw를 25회 쳤는데 전부 CDN 미스였다 — URL에
`?t=${Date.now()}`를 붙여 요청마다 주소가 달라졌기 때문이다. 지금은
src/lib/db-data.ts의 신선도 버킷이 그 자리를 대신한다(최대 지연 = FRESHNESS_MS).

캐시버스터는 되살리기 쉽다("왜 옛 값이 보이지?" → Date.now() 추가). 그래서
**db-data 헬퍼를 쓰는 파일**에는 요청마다 달라지는 버스터를 금지한다.
아직 헬퍼로 옮기지 않은 라우트는 이 규칙에 걸리지 않는다 — 옮기는 순간부터 걸린다.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

ROOT = os.path.join(os.path.dirname(__file__), '..')
DB_DATA_TS = os.path.join(ROOT, 'src', 'lib', 'db-data.ts')


def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def _files_using_the_helper():
    out = []
    for base in ('src/app', 'src/lib'):
        for dirpath, _, names in os.walk(os.path.join(ROOT, base)):
            for n in names:
                if not n.endswith(('.ts', '.tsx')) or n.endswith('.test.ts'):
                    continue
                path = os.path.join(dirpath, n)
                if os.path.abspath(path) == os.path.abspath(DB_DATA_TS):
                    continue
                if "from '@/lib/db-data'" in _read(path) or "from './db-data.ts'" in _read(path):
                    out.append(path)
    return out


def test_the_two_dashboard_routes_use_the_helper():
    """전제 확인 — 아래 규칙이 실제로 무언가를 지키고 있는가."""
    users = {os.path.relpath(p, ROOT).replace('\\', '/') for p in _files_using_the_helper()}
    assert 'src/app/api/simulation/stats/route.ts' in users
    assert 'src/app/api/trade/history/route.ts' in users


def test_helper_users_do_not_bust_the_cache_per_request():
    """요청마다 달라지는 버스터가 하나라도 있으면 그 파일은 CDN을 못 쓴다."""
    buster = re.compile(r'\?t=\$\{Date\.now\(\)\}|cacheBuster\s*=\s*Date\.now\(\)')
    for path in _files_using_the_helper():
        found = buster.findall(_read(path))
        assert not found, (
            f"{os.path.relpath(path, ROOT)}에 요청마다 달라지는 캐시버스터가 있다: {found} — "
            'dbDataUrl()을 쓸 것(같은 버킷 안에서는 CDN이 답한다)')


def test_freshness_window_is_stated_in_one_place():
    """최대 지연이 코드 여기저기 흩어지면 '얼마나 늦을 수 있나'에 답할 수 없다."""
    src = _read(DB_DATA_TS)
    m = re.search(r'export const FRESHNESS_MS = ([\d_]+);', src)
    assert m, 'db-data.ts에 FRESHNESS_MS 선언이 없다'
    seconds = int(m.group(1).replace('_', '')) / 1000
    assert 5 <= seconds <= 120, f'신선도 창이 {seconds}초다 — 대시보드 지연으로 납득할 범위를 벗어났다'
