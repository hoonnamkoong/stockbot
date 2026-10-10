"""한국 반도체(HS 8542) 월별 수출 — 관세청 Itemtrade.

심19가 보는 것은 "붐의 질"이다 — 수출금액이 **가격**으로 오르는지 **물량**으로
오르는지. 금액 ÷ 중량이 단가이고, 유료 DRAM 현물가(DRAMeXchange·TrendForce)의
공개 대리변수다.

2026-10-09 실측에서 확인한 함정 셋을 코드에 박아 둔다:
  ① **범위가 1년을 넘으면 179바이트 빈 응답**이다. 10년 범위 요청이 실패한
     원인이었다 — 오류 코드도 안 준다. 연도별로 끊어 받는다.
  ② `type=json`을 줘도 **XML**을 준다. JSON 파서를 붙이면 조용히 0건이 된다.
  ③ 월별로 HS 세부코드가 ~14개씩 온다. **합산**해야 한다. 덮어쓰면 한
     세부코드 값만 남아 300억$가 0.4억$로 읽힌다.
  ④ `year` 필드에 연간 합계 행(`2025`)이 월별 행(`2025.01`)과 섞인다.
     `\\d{4}\\.\\d{2}`만 받는다 — 안 그러면 연간치가 월별에 더해진다.
"""
from __future__ import annotations

import os
import re
import urllib.parse

from src.core import net

BASE = 'https://apis.data.go.kr/1220000/Itemtrade/getItemtradeList'
HS = '8542'                     # 전자집적회로
ENV_KEY = 'DATA_GO_KR_KEY'
_MONTH = re.compile(r'^\d{4}\.\d{2}$')
_ITEM = re.compile(r'<item>(.*?)</item>', re.S)


def _tag(block, name):
    m = re.search(r'<%s>(.*?)</%s>' % (name, name), block)
    return m.group(1).strip() if m else None


def fetch_year(year, *, key=None, reasons=None):
    """한 해의 {'YYYY-MM-01': (수출달러, 수출중량)}. 실패하면 (None, 사유).

    범위를 1년으로 고정한다 — 넘기면 빈 응답이다(함정 ①).
    """
    key = key or os.environ.get(ENV_KEY)
    if not key:
        return None, f'{ENV_KEY} 없음'
    url = ('%s?serviceKey=%s&strtYymm=%d01&endYymm=%d12&hsSgn=%s'
           % (BASE, urllib.parse.quote(key, safe=''), year, year, HS))
    res = net.get(url, policy=net.BULK, target='customs', reasons=reasons)
    if res is None:
        return None, f'{year} fetch failed'
    text = res.text
    if '<item>' not in text:
        # 정상 서비스인데 item이 없으면 그 해 자료가 없는 것이다.
        # 빈 응답(179바이트)과 구분해 사유를 남긴다.
        return {}, None if 'resultCode>00' in text else f'{year} 빈 응답'
    out = {}
    for block in _ITEM.findall(text):
        ym = _tag(block, 'year')
        if not ym or not _MONTH.match(ym):
            continue            # 연간 합계 행 제외 (함정 ④)
        k = ym.replace('.', '-') + '-01'
        exp = _tag(block, 'expDlr')
        wgt = _tag(block, 'expWgt')
        try:
            e = float(exp.replace(',', '')) if exp else 0.0
            w = float(wgt.replace(',', '')) if wgt else 0.0
        except ValueError:
            continue
        pe, pw = out.get(k, (0.0, 0.0))
        out[k] = (pe + e, pw + w)   # 세부코드 합산 (함정 ③)
    return out, None


def fetch_series(years, *, key=None, log=print, reasons=None):
    """여러 해 → ({'YYYY-MM-01': {금액, 중량, 단가}}, errors)."""
    merged, errors = {}, []
    for y in years:
        got, err = fetch_year(y, key=key, reasons=reasons)
        if err:
            errors.append(err)
            continue
        merged.update(got)
    out = {}
    for k, (e, w) in sorted(merged.items()):
        if e <= 0 or w <= 0:
            continue            # 0으로 채우지 않는다 — 그 달을 버린다
        out[k] = {'금액': e, '중량': w, '단가': e / w}
    if not out:
        log('[SemiTrade] 수집 0건 — 판정 보류: %s'
            % ('; '.join(errors) or 'unknown'))
    return out, errors


def yoy(series, field, k):
    """k월의 field 전년동월비(%). 못 내면 None."""
    y, m = int(k[:4]), int(k[5:7])
    prev = '%04d-%02d-01' % (y - 1, m)
    a, b = series.get(k), series.get(prev)
    if not a or not b or not b[field]:
        return None
    return (a[field] / b[field] - 1) * 100
