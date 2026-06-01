# 텔레그램 딥다이브 리포트 리디자인 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gemini 딥다이브 리포트를 수치 나열식에서 맥락·트렌드 분석 중심으로 전환하고, KIS 투자의견 데이터는 별도 블록으로 병합하여 발송한다.

**Architecture:** (1) 파이프라인 시작 시 네이버에서 업종 평균 PER/PBR을 1회 스크래핑해 JSON 캐시 저장 → (2) 기존 KIS inquire-price 응답에서 종목 업종명 추가 추출 (호출 추가 없음) → (3) KISDataProvider에 뉴스 타이틀 API 메서드 추가 → (4) advisor.py에서 Gemini 프롬프트를 맥락 분석 전용으로 교체하고, 투자 데이터 블록을 별도 포맷팅하여 리포트 뒤에 병합.

**Tech Stack:** Python 3.12, requests, BeautifulSoup4, pytest, 기존 KIS API 인프라

---

## 파일 구조

| 파일 | 역할 |
|------|------|
| `src/data/sector_cache.py` | 신규 — 네이버 업종 평균 PER/PBR 스크래핑 + 1일 캐시 |
| `src/pipeline/workers/data_fetcher.py` | 수정 — sector_cache 호출, bstp_kor_isnm 추출 |
| `src/trade/kis_data_provider.py` | 수정 — get_news_titles() 추가 |
| `src/strategy/advisor.py` | 수정 — generate_deep_dive_report() 전면 재작성 |
| `data/sector_per_pbr.json` | 자동 생성 — 1일 TTL 캐시 파일 |
| `tests/test_sector_cache.py` | 신규 — sector_cache 단위 테스트 |
| `tests/test_kis_news.py` | 신규 — get_news_titles 단위 테스트 |
| `tests/test_report_format.py` | 신규 — 리포트 포맷 단위 테스트 |

---

## Task 1: 업종 평균 PER/PBR 스크래핑 캐시

**Files:**
- Create: `src/data/sector_cache.py`
- Create: `tests/test_sector_cache.py`

네이버 업종별시세 페이지에서 업종명→(평균PER, 평균PBR) 테이블을 스크래핑한다.
- 1단계: `https://finance.naver.com/sise/sise_group.naver?type=upjong` → 업종명 + `no` ID 목록
- 2단계: 각 업종 detail 페이지 → 소속 종목들의 PER/PBR 평균 계산
- TTL 1일. `data/sector_per_pbr.json` 저장.

- [ ] **Step 1: 테스트 파일 생성 및 pytest 확인**

```bash
cd c:\Users\Hoon_DT\gemini\stock
pip install pytest --quiet
```

`tests/__init__.py` 생성:
```python
```
(빈 파일)

- [ ] **Step 2: sector_cache 단위 테스트 작성**

`tests/test_sector_cache.py`:
```python
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from unittest.mock import patch, MagicMock
from src.data.sector_cache import SectorCache

MOCK_GROUP_HTML = b"""
<html><body>
<table class="type_1">
<tr><td class="col_type1"><a href="sise_group_detail.naver?type=upjong&no=2">소프트웨어</a></td></tr>
<tr><td class="col_type1"><a href="sise_group_detail.naver?type=upjong&no=3">반도체</a></td></tr>
</table>
</body></html>
"""

MOCK_DETAIL_HTML = b"""
<html><body>
<table class="type_5">
<tr class="tr_line">
  <td><a href="">종목A</a></td>
  <td>10.5</td><td>2.1</td>
</tr>
<tr class="tr_line">
  <td><a href="">종목B</a></td>
  <td>20.5</td><td>3.1</td>
</tr>
</table>
</body></html>
"""

def test_parse_sector_list():
    cache = SectorCache.__new__(SectorCache)
    result = cache._parse_sector_list(MOCK_GROUP_HTML)
    assert '소프트웨어' in result
    assert result['소프트웨어'] == '2'
    assert result['반도체'] == '3'

def test_parse_sector_detail():
    cache = SectorCache.__new__(SectorCache)
    result = cache._parse_sector_detail(MOCK_DETAIL_HTML)
    assert result['avg_per'] == 15.5   # (10.5 + 20.5) / 2
    assert result['avg_pbr'] == 2.6    # (2.1 + 3.1) / 2

def test_is_stale_true_when_no_file(tmp_path):
    cache = SectorCache(data_dir=str(tmp_path))
    assert cache._is_stale() is True

def test_is_stale_false_when_fresh(tmp_path):
    cache = SectorCache(data_dir=str(tmp_path))
    data = {"updated_at": time.time(), "sectors": {}}
    (tmp_path / "sector_per_pbr.json").write_text(__import__('json').dumps(data))
    assert cache._is_stale() is False

def test_get_sector_avg_returns_data(tmp_path):
    cache = SectorCache(data_dir=str(tmp_path))
    data = {
        "updated_at": time.time(),
        "sectors": {"소프트웨어": {"avg_per": 38.2, "avg_pbr": 4.1}}
    }
    (tmp_path / "sector_per_pbr.json").write_text(__import__('json').dumps(data))
    result = cache.get_sector_avg("소프트웨어")
    assert result == {"avg_per": 38.2, "avg_pbr": 4.1}

def test_get_sector_avg_returns_none_for_unknown(tmp_path):
    cache = SectorCache(data_dir=str(tmp_path))
    data = {"updated_at": time.time(), "sectors": {}}
    (tmp_path / "sector_per_pbr.json").write_text(__import__('json').dumps(data))
    assert cache.get_sector_avg("없는업종") is None
```

- [ ] **Step 3: 테스트 실행 — FAIL 확인**

```bash
cd c:\Users\Hoon_DT\gemini\stock
python -m pytest tests/test_sector_cache.py -v 2>&1 | head -30
```
예상: `ModuleNotFoundError: No module named 'src.data.sector_cache'`

- [ ] **Step 4: sector_cache.py 구현**

`src/data/sector_cache.py`:
```python
import json
import os
import time
import requests
from bs4 import BeautifulSoup


class SectorCache:
    TTL = 86400  # 1일

    def __init__(self, data_dir=None):
        if data_dir is None:
            data_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data'
            )
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.cache_file = os.path.join(data_dir, 'sector_per_pbr.json')

    def _is_stale(self) -> bool:
        if not os.path.exists(self.cache_file):
            return True
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return (time.time() - data.get('updated_at', 0)) > self.TTL
        except Exception:
            return True

    def _parse_sector_list(self, html: bytes) -> dict:
        """업종 목록 페이지 파싱 → {업종명: no코드}"""
        soup = BeautifulSoup(html, 'html.parser')
        result = {}
        for a in soup.select('table.type_1 td.col_type1 a'):
            href = a.get('href', '')
            if 'no=' in href:
                no = href.split('no=')[-1].split('&')[0]
                result[a.get_text(strip=True)] = no
        return result

    def _parse_sector_detail(self, html: bytes) -> dict:
        """업종 상세 페이지 파싱 → {avg_per, avg_pbr}"""
        soup = BeautifulSoup(html, 'html.parser')
        pers, pbrs = [], []
        for row in soup.select('table.type_5 tr.tr_line'):
            cols = row.select('td')
            if len(cols) >= 3:
                try:
                    per = float(cols[1].get_text(strip=True).replace(',', ''))
                    pbr = float(cols[2].get_text(strip=True).replace(',', ''))
                    if per > 0:
                        pers.append(per)
                    if pbr > 0:
                        pbrs.append(pbr)
                except (ValueError, IndexError):
                    pass
        return {
            'avg_per': round(sum(pers) / len(pers), 1) if pers else 0,
            'avg_pbr': round(sum(pbrs) / len(pbrs), 1) if pbrs else 0,
        }

    def refresh(self):
        """네이버에서 전체 업종 평균 PER/PBR 스크래핑 후 저장."""
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            res = requests.get(
                'https://finance.naver.com/sise/sise_group.naver?type=upjong',
                headers=headers, timeout=10
            )
            sector_map = self._parse_sector_list(res.content)
        except Exception as e:
            print(f'[SectorCache] 업종 목록 수집 실패: {e}')
            return

        sectors = {}
        for name, no in sector_map.items():
            try:
                url = f'https://finance.naver.com/sise/sise_group_detail.naver?type=upjong&no={no}'
                r = requests.get(url, headers=headers, timeout=5)
                avg = self._parse_sector_detail(r.content)
                if avg['avg_per'] > 0:
                    sectors[name] = avg
            except Exception:
                pass

        data = {'updated_at': time.time(), 'sectors': sectors}
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f'[SectorCache] {len(sectors)}개 업종 PER/PBR 캐시 저장')

    def ensure_fresh(self):
        """캐시가 오래됐으면 refresh."""
        if self._is_stale():
            self.refresh()

    def get_sector_avg(self, sector_name: str) -> dict | None:
        """업종명으로 평균 PER/PBR 반환. 없으면 None."""
        if not os.path.exists(self.cache_file):
            return None
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('sectors', {}).get(sector_name)
        except Exception:
            return None
```

- [ ] **Step 5: 테스트 실행 — PASS 확인**

```bash
python -m pytest tests/test_sector_cache.py -v
```
예상: 6개 PASS

- [ ] **Step 6: 커밋**

```bash
git add src/data/sector_cache.py tests/test_sector_cache.py tests/__init__.py
git commit -m "feat: 업종 평균 PER/PBR 스크래핑 캐시 (sector_cache.py)"
```

---

## Task 2: DataFetcher — 업종명 추출 + 캐시 갱신 호출

**Files:**
- Modify: `src/pipeline/workers/data_fetcher.py`

- [ ] **Step 1: bstp_kor_isnm 추출 추가**

`src/pipeline/workers/data_fetcher.py` — `_get_stock_details()` 내 KIS 응답 파싱 블록에서 기존 `acml_vol` 추출 바로 아래에 추가:

```python
                        if out.get('bstp_kor_isnm'):
                            details['sector_name'] = out['bstp_kor_isnm'].strip()
```

위치: [data_fetcher.py:229](src/pipeline/workers/data_fetcher.py) — `acml_vol` 추출 직후.

- [ ] **Step 2: 파이프라인 시작 시 캐시 갱신 호출**

`src/pipeline/workers/data_fetcher.py` — `run()` 메서드 최상단 (sync_from_github 호출 전):

```python
        # 업종 평균 PER/PBR 캐시 갱신 (1일 TTL)
        try:
            from src.data.sector_cache import SectorCache
            SectorCache().ensure_fresh()
        except Exception as e:
            self.log_error(f"업종 캐시 갱신 실패 (계속 진행): {e}")
```

- [ ] **Step 3: 동작 확인 (로그 확인)**

```bash
cd c:\Users\Hoon_DT\gemini\stock
python -c "
import sys; sys.path.insert(0, '.')
from src.data.sector_cache import SectorCache
c = SectorCache()
c.ensure_fresh()
result = c.get_sector_avg('소프트웨어')
print('소프트웨어:', result)
result2 = c.get_sector_avg('반도체')
print('반도체:', result2)
" 2>/dev/null
```
예상: `소프트웨어: {'avg_per': XX.X, 'avg_pbr': X.X}` 출력

- [ ] **Step 4: 커밋**

```bash
git add src/pipeline/workers/data_fetcher.py
git commit -m "feat: KIS 응답에서 sector_name 추출 + 파이프라인 시작 시 업종 캐시 갱신"
```

---

## Task 3: KISDataProvider — 뉴스 타이틀 API

**Files:**
- Modify: `src/trade/kis_data_provider.py`
- Create: `tests/test_kis_news.py`

- [ ] **Step 1: 테스트 작성**

`tests/test_kis_news.py`:
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from unittest.mock import patch, MagicMock
from src.trade.kis_data_provider import KISDataProvider


MOCK_NEWS_RESPONSE = {
    "rt_cd": "0",
    "output": [
        {"hts_pbnt_titl_cntt": "카카오, AI 사업 본격화 선언",   "news_ofer_entp_code": "A"},
        {"hts_pbnt_titl_cntt": "카카오페이 실적 개선 기대",     "news_ofer_entp_code": "5"},
        {"hts_pbnt_titl_cntt": "카카오 플랫폼 사용자 역대 최고", "news_ofer_entp_code": "6"},
    ]
}

MOCK_NEWS_DUPLICATE_SRC = {
    "rt_cd": "0",
    "output": [
        {"hts_pbnt_titl_cntt": "카카오 AI 분사 검토",  "news_ofer_entp_code": "A"},
        {"hts_pbnt_titl_cntt": "AI 키우는 카카오",     "news_ofer_entp_code": "A"},  # 같은 출처
        {"hts_pbnt_titl_cntt": "카카오 2분기 실적",    "news_ofer_entp_code": "5"},
    ]
}


def test_get_news_titles_returns_list():
    provider = KISDataProvider.__new__(KISDataProvider)
    provider._cache = {}
    provider._token = "fake"
    provider._base_url = "https://fake"
    provider._app_key = "key"
    provider._app_secret = "secret"

    with patch.object(provider, '_get', return_value=MOCK_NEWS_RESPONSE):
        result = provider.get_news_titles("035720")

    assert isinstance(result, list)
    assert len(result) == 3
    assert result[0] == "카카오, AI 사업 본격화 선언"


def test_get_news_titles_deduplicates_by_source():
    """같은 출처의 두 번째 기사는 제외된다."""
    provider = KISDataProvider.__new__(KISDataProvider)
    provider._cache = {}
    provider._token = "fake"
    provider._base_url = "https://fake"
    provider._app_key = "key"
    provider._app_secret = "secret"

    with patch.object(provider, '_get', return_value=MOCK_NEWS_DUPLICATE_SRC):
        result = provider.get_news_titles("035720")

    assert len(result) == 2                        # 출처 A 1건 + 출처 5 1건
    assert "카카오 AI 분사 검토" in result
    assert "AI 키우는 카카오" not in result        # 같은 출처 A 중복 제거
    assert "카카오 2분기 실적" in result


def test_get_news_titles_returns_empty_on_failure():
    provider = KISDataProvider.__new__(KISDataProvider)
    provider._cache = {}
    provider._token = "fake"
    provider._base_url = "https://fake"
    provider._app_key = "key"
    provider._app_secret = "secret"

    with patch.object(provider, '_get', return_value={}):
        result = provider.get_news_titles("035720")

    assert result == []


def test_get_news_titles_uses_cache():
    provider = KISDataProvider.__new__(KISDataProvider)
    import time
    provider._cache = {"news_035720": (time.time(), ["캐시된 뉴스"])}
    provider._token = "fake"
    provider._base_url = "https://fake"
    provider._app_key = "key"
    provider._app_secret = "secret"

    with patch.object(provider, '_get') as mock_get:
        result = provider.get_news_titles("035720")
        mock_get.assert_not_called()

    assert result == ["캐시된 뉴스"]
```

- [ ] **Step 2: 테스트 실행 — FAIL 확인**

```bash
python -m pytest tests/test_kis_news.py -v 2>&1 | head -20
```
예상: `AttributeError: type object 'KISDataProvider' has no attribute 'get_news_titles'`

- [ ] **Step 3: get_news_titles() 구현**

`src/trade/kis_data_provider.py` — 기존 `get_invest_opbysec()` 메서드 아래에 추가:

```python
    # ──────────────────────────────────────────────────
    # 6. 종목 뉴스 타이틀
    # ──────────────────────────────────────────────────
    def get_news_titles(self, code: str, limit: int = 7) -> list[str]:
        """
        KIS 뉴스 타이틀 API로 종목 관련 최근 뉴스 제목 반환.
        출처(news_ofer_entp_code)별 1건만 선택해 동일 이벤트 중복 방지.
        반환: 제목 문자열 리스트 (최대 limit개)
        TR ID: FHKST01011800
        """
        key = f"news_{code}"
        cached = self._get_cached(key, 1800)  # 30분 캐시
        if cached is not None:
            return cached

        body = self._get(
            "/uapi/domestic-stock/v1/quotations/news-title",
            "FHKST01011800",
            {
                "FID_NEWS_OFER_ENTP_CODE": "",
                "FID_COND_MRKT_CLS_CODE": "",
                "FID_INPUT_ISCD": code,
                "FID_TITL_CNTT": "",
                "FID_INPUT_DATE_1": "",
                "FID_INPUT_HOUR_1": "",
                "FID_RANK_SORT_CLS_CODE": "",
                "FID_INPUT_SRNO": "",
            },
        )
        rows = body.get("output", [])
        if not rows:
            self._set_cache(key, [])
            return []

        if not isinstance(rows, list):
            rows = [rows]

        # 출처별 1건씩 선택 (같은 사건을 여러 언론이 다르게 표현하는 중복 방지)
        seen_sources: set = set()
        titles: list[str] = []
        for r in rows:
            src = r.get("news_ofer_entp_code", "")
            title = r.get("hts_pbnt_titl_cntt", "").strip()
            if title and src not in seen_sources:
                seen_sources.add(src)
                titles.append(title)
            if len(titles) >= limit:
                break

        self._set_cache(key, titles)
        return titles
```

- [ ] **Step 4: 테스트 실행 — PASS 확인**

```bash
python -m pytest tests/test_kis_news.py -v
```
예상: 3개 PASS

- [ ] **Step 5: 커밋**

```bash
git add src/trade/kis_data_provider.py tests/test_kis_news.py
git commit -m "feat: KIS 뉴스 타이틀 API 메서드 추가 (get_news_titles, 30분 캐시)"
```

---

## Task 4: advisor.py — 리포트 재설계

**Files:**
- Modify: `src/strategy/advisor.py`
- Create: `tests/test_report_format.py`

### 4-A: 헬퍼 함수 — 투자 데이터 블록 포맷

- [ ] **Step 1: 테스트 작성**

`tests/test_report_format.py`:
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.advisor import StrategyAdvisor


def make_stock(**kwargs):
    base = {
        'code': '035720', 'name': '카카오', 'price': 46050, 'rank': 1,
        'per': 41.5, 'pbr': 1.8, 'w52_hgpr': 62400, 'w52_lwpr': 39800,
        'invest_opinion': '매수', 'target_price': 58000, 'opinion_divergence': 26.0,
        'consensus_summary': '매수 7/9개사, 평균목표가 61,000원',
        'sector_name': '소프트웨어',
        'foreign_change': 0.12,
        'posts_summary': '[분석] 카카오 AI 전환 기대 150건 포착',
    }
    base.update(kwargs)
    return base


def test_format_investment_block_contains_opinion():
    advisor = StrategyAdvisor.__new__(StrategyAdvisor)
    stock = make_stock()
    sector_avg = {'avg_per': 38.2, 'avg_pbr': 4.1}
    block = advisor._format_investment_block(stock, sector_avg)
    assert '매수' in block
    assert '58,000' in block


def test_format_investment_block_per_with_sector():
    advisor = StrategyAdvisor.__new__(StrategyAdvisor)
    stock = make_stock()
    sector_avg = {'avg_per': 38.2, 'avg_pbr': 4.1}
    block = advisor._format_investment_block(stock, sector_avg)
    assert '41.5x' in block
    assert '소프트웨어' in block
    assert '38.2x' in block


def test_format_investment_block_per_fallback_no_sector():
    advisor = StrategyAdvisor.__new__(StrategyAdvisor)
    stock = make_stock(per=8.0, pbr=0.7)
    block = advisor._format_investment_block(stock, None)
    assert '8.0x' in block
    assert '저평가' in block
    assert '0.7x' in block
    assert '자산가치' in block


def test_format_investment_block_52week():
    advisor = StrategyAdvisor.__new__(StrategyAdvisor)
    stock = make_stock()
    block = advisor._format_investment_block(stock, None)
    assert '62,400' in block
    assert '39,800' in block
    assert '28%' in block  # (46050-39800)/(62400-39800)*100 ≈ 28


def test_format_investment_block_no_emojis():
    advisor = StrategyAdvisor.__new__(StrategyAdvisor)
    stock = make_stock()
    block = advisor._format_investment_block(stock, None)
    for emoji in ['📌', '🏢', '💡', '🎯', '⚠️', '🚀', '📅']:
        assert emoji not in block
```

- [ ] **Step 2: 테스트 실행 — FAIL 확인**

```bash
python -m pytest tests/test_report_format.py -v 2>&1 | head -20
```
예상: `AttributeError: '_format_investment_block' not found`

- [ ] **Step 3: _format_investment_block() 구현**

`src/strategy/advisor.py` — `generate_deep_dive_report()` 메서드 바로 위에 추가:

```python
    def _format_investment_block(self, stock: dict, sector_avg: dict | None) -> str:
        """투자 수치 데이터 블록 — Gemini 리포트 뒤에 병합."""
        lines = ["── 투자 데이터 ─────────────────────────"]

        # 투자의견 + 목표가
        op = stock.get('invest_opinion', '') or ''
        tp = stock.get('target_price', 0) or 0
        div = stock.get('opinion_divergence', 0) or 0
        if op or tp:
            tp_str = f"{tp:,}원 (현재가 대비 {div:+.1f}%)" if tp else "-"
            lines.append(f"종목투자의견: {op or '-'} | 목표가: {tp_str}")

        # 컨센서스
        consensus = stock.get('consensus_summary', '') or ''
        if consensus:
            lines.append(f"컨센서스: {consensus}")

        # PER/PBR + 업종 비교
        per = stock.get('per', 0) or 0
        pbr = stock.get('pbr', 0) or 0
        sector_name = stock.get('sector_name', '') or ''
        if per or pbr:
            if sector_avg and sector_avg.get('avg_per'):
                avg_per = sector_avg['avg_per']
                avg_pbr = sector_avg.get('avg_pbr', 0)
                per_diff = round((per - avg_per) / avg_per * 100) if avg_per else 0
                per_label = f"{sector_name} 업종 평균 {avg_per}x 대비 {per_diff:+d}%"
                pbr_label = f"업종 평균 {avg_pbr}x" if avg_pbr else ""
            else:
                # 절대값 기준 정성 레이블
                if per < 15:
                    per_label = "저평가 구간"
                elif per < 30:
                    per_label = "적정 구간"
                elif per < 50:
                    per_label = "성장주 수준"
                else:
                    per_label = "고평가 / 성장 기대 반영"
                if pbr < 1:
                    pbr_label = "자산가치 이하"
                elif pbr < 3:
                    pbr_label = "적정"
                else:
                    pbr_label = "성장 프리미엄"

            per_str = f"PER {per}x ({per_label})"
            pbr_str = f"PBR {pbr}x ({pbr_label})" if pbr_label else f"PBR {pbr}x"
            lines.append(f"{per_str} | {pbr_str}")

        # 52주 위치
        w52h = stock.get('w52_hgpr', 0) or 0
        w52l = stock.get('w52_lwpr', 0) or 0
        cur = stock.get('price', stock.get('current_price', 0)) or 0
        if w52h and w52l and cur:
            pos = round((cur - w52l) / (w52h - w52l) * 100) if w52h != w52l else 50
            lines.append(f"52주: 고 {w52h:,}원 / 저 {w52l:,}원 (현재 위치 {pos}%)")

        lines.append("────────────────────────────────────────")
        return "\n".join(lines)
```

- [ ] **Step 4: 테스트 실행 — PASS 확인**

```bash
python -m pytest tests/test_report_format.py -v
```
예상: 5개 PASS

### 4-B: generate_deep_dive_report() 재작성

- [ ] **Step 5: generate_deep_dive_report() 수정**

`src/strategy/advisor.py` — `generate_deep_dive_report()` 전체 교체:

```python
    def generate_deep_dive_report(self, final_candidates, sell_candidate=None):
        """
        딥다이브 리포트 — Gemini 맥락 분석 + KIS 투자 데이터 블록 병합
        - Gemini 프롬프트: 뉴스 제목 + 토론 요약 + 52주 위치 (맥락 분석 전용)
        - 수치 데이터: 투자의견/PER/PBR 업종비교 블록으로 분리
        """
        if not final_candidates and not sell_candidate:
            return "분석 대상 종목이 없습니다."

        reports = []

        # KIS 뉴스 API 준비
        try:
            from src.trade.kis_data_provider import KISDataProvider
            kis = KISDataProvider()
        except Exception:
            kis = None

        # 업종 PER/PBR 캐시 준비
        try:
            from src.data.sector_cache import SectorCache
            sector_cache = SectorCache()
        except Exception:
            sector_cache = None

        for stock in final_candidates[:2]:
            cur = stock.get('price', stock.get('current_price', 0)) or 0

            # 뉴스 제목 수집
            news_titles = []
            if kis:
                try:
                    news_titles = kis.get_news_titles(stock['code'])
                except Exception:
                    pass

            # 52주 위치 계산
            w52h = stock.get('w52_hgpr', 0) or 0
            w52l = stock.get('w52_lwpr', 0) or 0
            w52_text = ""
            if w52h and w52l and cur:
                pos = round((cur - w52l) / (w52h - w52l) * 100) if w52h != w52l else 50
                w52_text = f"52주 고가 {w52h:,}원 / 저가 {w52l:,}원 (현재 위치 {pos}%)"

            # 뉴스 섹션 구성
            news_section = ""
            if news_titles:
                news_section = "\n[최근 뉴스 제목]\n" + "\n".join(f"- {t}" for t in news_titles)

            prompt = f"""
당신은 대한민국 주식시장 전문 애널리스트입니다.
아래 정보를 바탕으로 이 종목이 왜 지금 시장의 주목을 받고 있는지,
어떤 트렌드·산업 변화·사회적 맥락이 배경인지를 중심으로 분석하세요.
수치 데이터를 단순 나열하지 말고, 맥락과 인사이트를 제시하세요.

종목: {stock['name']} ({stock['code']})
현재가: {cur:,}원 | 순위: {stock.get('rank', 'N/A')}위
외인변화: {stock.get('foreign_change', 0):+.2f}%p
{w52_text}
[토론 요약]
{stock.get('posts_summary', '정보 없음')}
{news_section}

다음 JSON 형식으로만 답변하세요:
{{
  "rank_and_recommendation": "{stock.get('rank')}위 매수추천 또는 강력매수 등",
  "business_summary": "주요 사업 1~2문장",
  "rationale": "이 종목이 왜 지금 주목받는지, 트렌드·산업 흐름·사회적 변화 기반 맥락 3~5줄",
  "target_price_flow": "현재가 -> 목표가 (근거)",
  "risk": "핵심 리스크 요인"
}}
"""
            try:
                response = self.gemini._call_gemini_safe(
                    prompt, model_type='report',
                    generation_config={"response_mime_type": "application/json"}
                )
                if response and response.text:
                    data = json.loads(response.text)
                    # Gemini 리포트 (아이콘 없음)
                    formatted = f"{stock['name']} ({data.get('rank_and_recommendation')})\n"
                    formatted += f"사업 요약: {data.get('business_summary')}\n"
                    formatted += f"추천 근거: {data.get('rationale')}\n"
                    formatted += f"목표가: {data.get('target_price_flow')}\n"
                    formatted += f"리스크: {data.get('risk')}\n"

                    # 투자 데이터 블록 병합
                    sector_name = stock.get('sector_name', '')
                    sector_avg = sector_cache.get_sector_avg(sector_name) if sector_cache and sector_name else None
                    formatted += "\n" + self._format_investment_block(stock, sector_avg)

                    reports.append(formatted)
            except Exception:
                reports.append(f"{stock['name']} 상세 분석 실패")

        header = f"[Strategic Deep-Dive] 상세 리포트\n"
        header += f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        return header + "\n\n---\n\n".join(reports)
```

- [ ] **Step 6: 전체 테스트 실행**

```bash
python -m pytest tests/ -v
```
예상: 전체 PASS (test_sector_cache 6개 + test_kis_news 3개 + test_report_format 5개)

- [ ] **Step 7: 커밋**

```bash
git add src/strategy/advisor.py tests/test_report_format.py
git commit -m "feat: 딥다이브 리포트 재설계 — Gemini 맥락분석 + KIS 투자데이터 블록 분리"
```

---

## 최종 확인

- [ ] **전체 테스트 통과 확인**

```bash
python -m pytest tests/ -v --tb=short
```

- [ ] **sector_per_pbr.json 실제 생성 확인**

```bash
python -c "
import sys; sys.path.insert(0, '.')
from src.data.sector_cache import SectorCache
c = SectorCache()
c.refresh()
import json
with open('data/sector_per_pbr.json') as f:
    d = json.load(f)
print(f'업종 수: {len(d[\"sectors\"])}')
print(list(d['sectors'].items())[:3])
" 2>/dev/null
```
예상: `업종 수: 40+`, 업종별 avg_per/avg_pbr 출력

- [ ] **최종 커밋**

```bash
git add data/sector_per_pbr.json
git commit -m "chore: 업종 PER/PBR 초기 캐시 파일 추가"
```
