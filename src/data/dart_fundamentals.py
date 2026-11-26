"""OpenDART 재무 — 심3 TTM 밸류·심11 성장률의 원천.

## 왜 생겼나

KIS 종목분석 7종이 2026-11-11 16:00에 막혔다(`FHKST66430300` → 404). 그날부터
심3은 25,380 판정을 **전부** skip(`no_ttm_val`)하고, 심11은 추세템플릿 통과분
**100%가 `no_eps`** 다 — 둘 다 전략이 아니라 입력이 끊겨서 멈춴 것이다.

## 계산식은 기존 KIS 메서드와 같다

    TTM = 최근분기누적 + (직전연간 − 직전년도 같은분기 누적)

연간 결산 기준을 쓰면 **실적 개선주가 비싸 보여 걸러지고 정체주가 싸 보여
뽑힌다** — 심3의 저평가 필터가 정확히 반대로 작동한다(2026-08-17에 그래서
TTM으로 옮겼다). 누적만 쓰면 반대로 3분기치가 1년으로 둔갑해 PER이 1/4로
보인다. 어느 쪽도 폴백으로 쓰지 않는다.

2026-11-25 실측 검증(삼성전자, 실제 응답):

    EPS TTM = 29,381 + (6,605 − 3,724) = 32,262
    EPS YoY = 29,381 / 3,724 − 1 = +689.0%
    매출 YoY = 500,626,123 / 164,148,387 − 1 = +205.0%

## 한 번의 호출에 네 값이 다 온다

응답 행마다 `thstrm_amount`(당분기) · `thstrm_add_amount`(당기누적) ·
`frmtrm_q_amount`(전년동분기) · `frmtrm_add_amount`(전년동기누적)가 있다. 그래서
**성장률은 호출 1회**로 끝나고, TTM만 직전연간을 위해 1회를 더 쓴다.

계정은 한글 라벨이 아니라 **IFRS 표준 태그(`account_id`)** 로 고른다 — 회사마다
라벨이 다르고 바뀐다. 100개 묶음 조회(`fnlttMultiAcnt`)는 주요계정 14개뿐이라
**EPS가 없고** 누적 필드도 없다 — 심11을 만들 수 없다.

## 주식수를 따로 조회하지 않는다

주식수 = 지배주주순이익누적 / EPS누적 이므로

    BPS = 지배주주자본 × (EPS누적 / 지배주주순이익누적)

⚠ **근사다.** EPS는 가중평균 보통주 기준이고 자본은 기말 지배주주지분이라
우선주·기중 변동만큼 어긋난다(삼성전자에서 약 3%). 밸류 **필터**용으로만 쓰고
가격 산정에는 쓰지 않는다.

## 운용

인증키는 환경변수 `DART_API_KEY`에서만 읽는다 — public 레포이므로 값은 GitHub
Secrets·Vercel env에만 둔다. 한도는 인증키당 일일 20,000회(분당 수치는 공개
가이드에 없다). 분기 보고서는 분기당 한 번만 바뀌므로 수집은 분기 1회면 되고,
심은 `data/dart_fundamentals.json` 캐시만 읽는다 — **사이클당 API 호출 0**이다.

조회 실패·데이터 없음은 **키를 넣지 않는 것**으로 표현한다. 0을 넣으면 심3이
'싸다'로 읽는다.
"""
from __future__ import annotations

import io
import json
import os
import re
import zipfile
from datetime import date

from src.core import net

API_URL = 'https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json'
CORP_CODE_URL = 'https://opendart.fss.or.kr/api/corpCode.xml'
CACHE_FILE = 'dart_fundamentals.json'
CORP_CODES_FILE = 'dart_corp_codes.json'

# IFRS 표준 태그. 한글 라벨은 회사마다 다르다.
EPS_ID = 'ifrs-full_BasicEarningsLossPerShare'
REVENUE_ID = 'ifrs-full_Revenue'
PROFIT_OWNERS_ID = 'ifrs-full_ProfitLossAttributableToOwnersOfParent'
EQUITY_OWNERS_ID = 'ifrs-full_EquityAttributableToOwnersOfParent'

_REPRT_BY_QUARTER = {1: '11013', 2: '11012', 3: '11014', 4: '11011'}

# 손익 항목이 사는 곳. 삼성전자는 `IS`와 `CIS`를 둘 다 내지만, SK하이닉스·
# NAVER·KB금융·신한지주·삼성바이오는 **`IS`가 없고 `CIS`만** 낸다 —
# 2026-11-25 실측에서 `IS`만 보던 코드가 대형주 12개 중 7개를 놓쳤다.
_IS_DIVS = ('IS', 'CIS')


def api_key() -> str | None:
    """인증키. 없으면 None — 조회를 시도하지 않는다."""
    return (os.environ.get('DART_API_KEY') or '').strip() or None


def reprt_code(quarter: int) -> str:
    """분기 → 보고서 코드. 1Q 11013 / 2Q 11012 / 3Q 11014 / 4Q(사업보고서) 11011."""
    return _REPRT_BY_QUARTER[int(quarter)]


def latest_report(today: date) -> tuple[int, int]:
    """그 날짜에 **이미 제출됐을** 가장 최근 보고서 (연도, 분기).

    분기보고서는 분기말 +45일, 사업보고서는 +90일이 제출 기한이다. 기한 전에
    조회하면 전 분기 자료가 '최신'으로 캐시돼 분기 하나가 통째로 밀린다.
    여유를 하루씩 두지 않는다 — 없으면 `fetch`가 빈 dict를 주고 그 종목은
    측정 불가로 남는다(지어낸 값보다 낫다).
    """
    y, md = today.year, (today.month, today.day)
    if md >= (11, 15):
        return y, 3
    if md >= (8, 15):
        return y, 2
    if md >= (5, 16):
        return y, 1
    if md >= (4, 1):
        return y - 1, 4
    return y - 1, 3


def _num(v) -> float | None:
    s = str(v if v is not None else '').replace(',', '').strip()
    if s in ('', '-', 'None'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _row(rows: list[dict], account_id: str, sj_div) -> dict | None:
    """`sj_div`는 문자열 하나 또는 **우선순위 튜플**이다(앞쪽을 먼저 쓴다)."""
    divs = (sj_div,) if isinstance(sj_div, str) else tuple(sj_div)
    for d in divs:
        for r in rows or []:
            if r.get('account_id') == account_id and r.get('sj_div') == d:
                return r
    return None


def _cum_and_prior(rows, account_id, sj_div=_IS_DIVS):
    """(당기누적, 전년동기누적, 분기보고서인가).

    사업보고서(11011)에는 누적 필드가 없다 — 당기 금액이 곧 1년이다. 그 구분이
    TTM을 만들지 말지를 가른다.
    """
    r = _row(rows, account_id, sj_div)
    if not r:
        return None, None, False
    add = _num(r.get('thstrm_add_amount'))
    if add is not None:
        return add, _num(r.get('frmtrm_add_amount')), True
    return _num(r.get('thstrm_amount')), _num(r.get('frmtrm_amount')), False


def derive(quarter_rows: list[dict], prior_annual_rows: list[dict]) -> dict:
    """두 보고서 → 심이 읽는 지표. 못 내는 값은 **키를 넣지 않는다**."""
    out: dict = {}
    eps_cum, eps_prev, is_quarterly = _cum_and_prior(quarter_rows, EPS_ID)
    rev_cum, rev_prev, _ = _cum_and_prior(quarter_rows, REVENUE_ID)

    if eps_cum is not None:
        if not is_quarterly:
            out['eps_ttm'] = eps_cum
        else:
            annual, _, _ = _cum_and_prior(prior_annual_rows, EPS_ID)
            if annual is not None and eps_prev is not None:
                out['eps_ttm'] = eps_cum + (annual - eps_prev)

    for key, cum, prev in (('eps_growth_yoy', eps_cum, eps_prev),
                           ('revenue_growth_yoy', rev_cum, rev_prev)):
        # 전년동기가 0이나 적자면 배수가 뜻을 잃는다 → 측정 불가.
        if cum is not None and prev is not None and prev > 0:
            out[key] = (cum / prev - 1) * 100

    profit_cum, _, _ = _cum_and_prior(quarter_rows, PROFIT_OWNERS_ID)
    equity = _num((_row(quarter_rows, EQUITY_OWNERS_ID, 'BS') or {}).get('thstrm_amount'))
    if equity and profit_cum and eps_cum and profit_cum > 0 and eps_cum > 0:
        out['bps'] = equity * (eps_cum / profit_cum)

    return out


def _rows(corp_code: str, year: int, rc: str, key: str) -> list[dict] | None:
    """해당 보고서의 계정 목록. 연결(CFS)이 없으면 개별(OFS)로 받는다.

    못 받으면 None(네트워크 실패), 응답은 왔지만 자료가 없으면 [].
    """
    answered = False
    for fs_div in ('CFS', 'OFS'):
        res = net.get(API_URL, params={
            'crtfc_key': key, 'corp_code': corp_code, 'bsns_year': str(year),
            'reprt_code': rc, 'fs_div': fs_div,
        }, timeout=20)
        if res is None:
            continue
        answered = True
        try:
            body = res.json()
        except ValueError:
            continue
        if body.get('status') == '000' and body.get('list'):
            return body['list']
    return [] if answered else None


def fetch(corp_code: str, year: int, quarter: int, key: str | None = None) -> dict:
    """한 종목의 파생 지표. 호출 2회(해당 분기 + 직전 사업보고서)."""
    key = key or api_key()
    if not key:
        return {}
    rc = reprt_code(quarter)
    quarter_rows = _rows(corp_code, year, rc, key)
    if not quarter_rows:
        return {}
    prior = _rows(corp_code, year - 1, reprt_code(4), key) or []
    out = derive(quarter_rows, prior)
    if out:
        out['report'] = f'{year}-{rc}'
    return out


def parse_corp_codes(xml_text: str) -> dict:
    """<list> 중 `stock_code`가 있는 것만 → {종목코드: 법인코드}.

    전체는 12만 법인인데 상장사는 4천여 개다. 종목코드가 없으면 심이 조회할
    열쇠가 없으므로 버린다 — 캐시가 30배로 불어나는 것을 막는다.
    """
    out: dict = {}
    for block in re.findall(r'<list>(.*?)</list>', xml_text, re.S):
        stock = re.search(r'<stock_code>([^<]*)</stock_code>', block)
        corp = re.search(r'<corp_code>([^<]*)</corp_code>', block)
        if not stock or not corp or not stock.group(1).strip():
            continue
        out[stock.group(1).strip()] = corp.group(1).strip()
    return out


def build_corp_code_map(key: str | None = None) -> dict:
    """OpenDART에서 법인코드 전체(zip)를 받아 상장사만 남긴다. 호출 1회."""
    key = key or api_key()
    if not key:
        return {}
    res = net.get(CORP_CODE_URL, params={'crtfc_key': key}, timeout=60)
    if res is None:
        return {}
    try:
        with zipfile.ZipFile(io.BytesIO(res.content)) as z:
            xml_text = z.read(z.namelist()[0]).decode('utf-8')
    except Exception as e:
        print(f'[dart] 법인코드 압축 해제 실패: {e}')
        return {}
    return parse_corp_codes(xml_text)


def load_corp_codes(data_dir: str = 'data') -> dict:
    try:
        with open(os.path.join(data_dir, CORP_CODES_FILE), 'r', encoding='utf-8') as f:
            m = json.load(f)
        return m if isinstance(m, dict) else {}
    except Exception:
        return {}


def _save_json(path: str, payload: dict) -> None:
    """임시 파일에 쓰고 `os.replace`로 바꾼다 — 잘린 파일이 남지 않는다.

    `open(..., 'w')`는 **먼저 잘라낸 뒤** 쓴다. 잡 타임아웃의 취소 신호가 그 창에
    떨어지면 잘린 JSON이 남고, 배포 스텝은 `if: always()`라 그걸 db-data에 올린다.
    그러면 `load_cache`가 예외를 삼켜 `{}`를 돌려주므로(아래) 다음 런이 **조용히
    0에서 다시 시작**한다 — 한 분기 수집이 사라진다.

    창은 넓지 않다: 저장 80회(`SAVE_EVERY=50` × 상장사 약 4,020) × 약 15ms =
    총 1.2초로 런(4,800초)의 **0.025%**다. 그래도 막는 이유는 비용이 세 줄이고
    이 잡이 **분기에 한 번**뿐이라 한 번 잃으면 다음 기회가 멀다는 것이다.

    임시 파일을 같은 디렉터리에 두는 이유: `os.replace`는 같은 파일시스템에서만
    원자적이다. 실패하면 지운다 — 남기면 `git add -A data/`가 db-data에 올린다.
    """
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = f'{path}.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False,
                      separators=(',', ':'), sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_corp_codes(mapping: dict, data_dir: str = 'data') -> None:
    _save_json(os.path.join(data_dir, CORP_CODES_FILE), mapping)


def load_cache(data_dir: str = 'data') -> dict:
    try:
        with open(os.path.join(data_dir, CACHE_FILE), 'r', encoding='utf-8') as f:
            cache = json.load(f)
        return cache if isinstance(cache, dict) else {}
    except Exception:
        return {}


def save_cache(cache: dict, data_dir: str = 'data') -> None:
    _save_json(os.path.join(data_dir, CACHE_FILE), cache)


def apply(candidates: list[dict], data_dir: str = 'data') -> tuple[int, int]:
    """후보 dict에 심이 읽는 키를 **제자리로** 넣는다. (적용 수, 전체 수) 반환.

    심3·심11의 코드는 바뀌지 않는다 — 심3은 후보에 실린 `per_ttm`/`pbr_ttm`을
    우선 쓰고(없으면 죽은 KIS 경로로 간다), 심11은 `eps_growth_yoy`를 읽는다.
    제자리라서 `trade_engine`이 같은 리스트를 넘기는 페이퍼·실전 두 경로가
    같은 입력을 본다.
    """
    cache = load_cache(data_dir)
    applied = total = 0
    for s in candidates or []:
        code = s.get('code')
        if not code:
            continue
        total += 1
        entry = cache.get(code)
        if not isinstance(entry, dict):
            continue
        hit = False
        price = _num(s.get('price')) or 0.0
        eps_ttm, bps = entry.get('eps_ttm'), entry.get('bps')
        # 적자(eps<=0)면 PER이 음수다 — 비교축이 깨지므로 넣지 않는다.
        if price > 0 and eps_ttm and eps_ttm > 0 and 'per_ttm' not in s:
            s['per_ttm'] = round(price / eps_ttm, 2)
            hit = True
        if price > 0 and bps and bps > 0 and 'pbr_ttm' not in s:
            s['pbr_ttm'] = round(price / bps, 2)
            hit = True
        for k in ('eps_growth_yoy', 'revenue_growth_yoy'):
            if entry.get(k) is not None and k not in s:
                s[k] = entry[k]
                hit = True
        if hit:
            applied += 1
    return applied, total
