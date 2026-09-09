"""네이버 종목뉴스를 (분 단위 시각과 함께) 긁는다. 키 불필요.

왜 필요한가 (2026-08-16 실측): 개장 전 뉴스는 **건수가 아니라 내용**이 가른다.
신제품·승인 +0.36% / 실적호조 +0.16% vs M&A·지분 −1.10% / 시황잡음 −0.64%
(시가→종가, 수수료 후). 건수로는 안 갈리던 것이 카테고리로는 0.87%p 갈린다.
그래서 제목을 시각과 함께 보존한다 — 분류는 나중에 바꿔 다시 돌릴 수 있어야 한다.

목표일까지 페이지를 넘기다가, 도달하면 멈춘다. 도달 못 하고 상한에 걸리면
`covered=0`으로 남긴다 — 커버리지 실패를 '뉴스 없음'으로 바꾸면 그게 곧
조용한 결손이다(대형주는 하루에 수십 페이지라 반드시 걸린다).
"""
import csv, os, sys, time, collections
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.core import net   # noqa: E402

H = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'}
MAX_PAGES = 40


def page(sess, code, p):
    """못 닿으면 None. 빈 리스트로 접으면 `fetch`가 '더 없다'로 읽어 covered=True를
    찍는다 — 커버리지 실패가 '뉴스 없음'으로 위장되는 바로 그 형태다.

    타임아웃·재시도·차단기는 `net`이 갖는다(BULK: read 8초). 이관 전 `timeout=8`과
    같은 값이지만, 여기서 숫자를 고르지 않는 것이 요점이다.
    """
    r = net.get('https://finance.naver.com/item/news_news.naver',
                policy=net.SCRAPE, target='naver_news', session=sess,
                params={'code': code, 'page': p}, headers=H)
    if r is None:
        return None
    s = BeautifulSoup(r.content.decode('euc-kr', 'replace'), 'html.parser')
    out = []
    for tr in s.select('table.type5 tr'):
        t = tr.select_one('td.title a')
        d = tr.select_one('td.date')
        src = tr.select_one('td.info')
        if t and d:
            out.append((d.get_text(strip=True), src.get_text(strip=True) if src else '',
                        t.get_text(strip=True)))
    return out


def fetch(code, until):
    """until(YYYY.MM.DD) 이전까지 긁는다. (rows, covered)."""
    sess = requests.Session()
    rows, covered = [], False
    for p in range(1, MAX_PAGES + 1):
        got = page(sess, code, p)
        if got is None:
            # 못 닿았다 — '더 없음'과 구분한다. covered는 그대로 False로 남는다.
            continue
        if not got:
            covered = True     # 더 없으면 그 종목은 전부 본 것
            break
        rows += got
        if min(g[0] for g in got)[:10] <= until:
            covered = True
            break
        time.sleep(0.05)
    return rows, covered


def main():
    codes = []
    with open(sys.argv[1], encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['code'] not in codes:
                codes.append(r['code'])
    until = sys.argv[2]          # 예: 2026.05.28
    out_path = sys.argv[3]
    print(f'{len(codes)}종목, {until}까지', flush=True)

    rows, cov = [], {}
    def one(code):
        got, c = fetch(code, until)
        return code, got, c
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, (code, got, c) in enumerate(ex.map(one, codes)):
            cov[code] = c
            for d, src, t in got:
                rows.append(dict(code=code, dt=d, src=src, title=t))
            if (i + 1) % 40 == 0:
                print(f'  {i+1}/{len(codes)} (기사 {len(rows)}건, 커버 실패 {sum(1 for v in cov.values() if not v)})', flush=True)

    with open(out_path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['code', 'dt', 'src', 'title'])
        w.writeheader()
        w.writerows(rows)
    with open(out_path.replace('.csv', '_coverage.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f); w.writerow(['code', 'covered'])
        w.writerows(cov.items())
    print(f'기사 {len(rows)}건 / 종목 {len(codes)} | 커버 성공 {sum(cov.values())} 실패 {len(cov)-sum(cov.values())}')
    print('저장', out_path)


if __name__ == '__main__':
    main()
