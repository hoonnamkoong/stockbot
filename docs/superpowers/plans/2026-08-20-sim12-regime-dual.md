# Sim12(국면이원 반등/추세형) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KOSPI 규칙마이닝(Tier1)에서 확정한 "국면에 따라 최고수익 패턴이 반대"라는 발견을
반영해, Sim0(리베로) 국면에 따라 진입 로직이 바뀌는 신규 페이퍼 심(Sim12)을 만든다 —
BULL이면 모멘텀 지속형, SIDEWAYS/BEAR면 급락반등형으로 전환한다.

**Architecture:** 기존 심들과 같은 순수함수(`decide_sim12`) + `BaseSimulator` 서브클래스
패턴. 유니버스는 KIS 등락률 순위(상승률+하락률 각 30, 두 플레이북 각각의 후보군을
동시에 확보)를 자체 유니버스로 쓴다. 공유 인프라(`_enrich_universe`)에 이번 세션에서
추가로 필요해진 파생 피처(20일 누적 기관 수급, 20일 평균 거래대금, 외인 보유율 5일 변화)를
얹는다 — 이미 받아오는 네이버 frgn.naver 20일 표에서 재활용(추가 호출 0).

**Tech Stack:** Python, pytest. 기존 코드베이스 관례(순수 `decide_*` 함수 + `_apply` +
`funnel` 진단 로그) 그대로 따른다.

**Spec:** `docs/superpowers/specs/2026-08-20-kospi-rule-mining-design.md` (특히 "제안
알고리즘 설계" 절)

## Scope decisions (설계서 대비 단순화한 부분)

설계서의 다음 항목은 이번 구현 범위에서 뺐다 — 필요하면 후속 태스크로 별도 추가한다.

- **B등급 가산점("저PBR+10일급등" 등)**: 하드 게이트가 아니라 순위 가산점이라
  스코어링 시스템이 필요한데, 이번 구현은 다른 심들처럼 단순 게이트 방식으로
  간다(YAGNI). 하드 게이트로 넣기엔 표본(B등급)이 얇다.
- **갭(gap_pct) 관련 게이트**: KIS 등락률 순위 API가 오늘 시가를 안 준다 —
  라이브로 확보 가능한 필드가 아니라 뺐다.
- **버즈 테마 "방금 태깅" 회피**: Sim12 유니버스는 KIS 등락률 순위(버즈 무관)라
  버즈 태깅 여부 자체가 후보에 없다. 버즈 유니버스를 쓰는 심이 아니라서 이 게이트가
  원천적으로 적용 대상이 아니다.

## Global Constraints

- MAX_HOLDINGS=5, POSITION_WEIGHT=0.19 (전 매매심 공통 규격 — NAV×15%×5종목=90%대 투입,
  실제로는 0.19×5=95%로 다른 심들과 동일하게 맞춘다).
- 하드손절 -7.0%, 트레일링 활성 +5.0%/콜백 -3.0% — Sim2(`sim2_spillover.py`)와 동일 값,
  이 세션에서 청산 파라미터를 새로 검증하지 않았으므로 기존 관례를 재사용한다(설계서
  "청산 로직" 절 그대로).
- 신규 심은 `tradeable: false`로 배치한다(Sim11과 동일 관례) — 페이퍼 관찰 단계, 백테스트
  미검증.
- 모든 숫자 임계값(PER 40, 외인/기관 20일 -5.0% 등)은 이번 세션 리서치 분위수 경계의
  **근사치**다 — 정밀 보정이 아니다. 각 상수 옆 주석에 리서치 근거를 남긴다.

---

## 파일 구조

- Create: `src/strategy/simulators/sim12_regime_dual.py` — `decide_sim12` 순수함수 +
  `RegimeDualSimulator` 클래스.
- Modify: `src/pipeline/workers/trade_engine.py` — `_enrich_universe`의 기존
  frgn.naver 파싱 블록(Sim6 진단 때 이미 손댄 자리)에 `orgn_net_20d`·`amount_ma20`·
  `frgn_hold_chg_5d` 3개 필드 추가.
- Modify: `src/strategy/simulators/base_simulator.py` — `_apply()`가 BUY 주문의
  `playbook` 메타데이터를 포트폴리오 항목에 남기도록(기존 SELL의 `mark_partial`과
  같은 패턴).
- Modify: `src/strategy/strategy_manifest.yaml` — Sim12 등록.
- Modify(생성): `src/lib/sim-registry.generated.ts` — `scripts/gen_sim_registry.py`
  재실행 결과.
- Test: `tests/test_enrich_flow_extras.py`, `tests/test_base_simulator_playbook_tag.py`,
  `tests/test_sim12_regime_dual.py`, `tests/test_sim12_universe.py`.

---

### Task 1: 공유 인프라 — 기관 20일 수급·20일 평균 거래대금·외인 보유율 5일 변화

**Files:**
- Modify: `src/pipeline/workers/trade_engine.py` (`_enrich_universe` 내부
  `fetch_sparkline`, `frgn_net_20d`를 추가했던 바로 다음 자리)
- Test: `tests/test_enrich_flow_extras.py`

**Interfaces:**
- Consumes: `fetch_sparkline`이 이미 파싱해 둔 `data_rows`(네이버 frgn.naver 20일 표,
  열 순서 `[0]날짜 [1]종가 [2]등락화살표 [3]등락률 [4]거래량 [5]기관순매매량
  [6]외국인순매매량 [7]외인보유주식수 [8]외인보유율`) — `frgn_net_20d`를 만들 때 쓴
  것과 완전히 같은 재료.
- Produces: 후보 딕셔너리에 `orgn_net_20d`(float, %), `amount_ma20`(float, 원),
  `frgn_hold_chg_5d`(float, %p) — 값을 못 만들면(행 부족 등) 키 자체를 안 붙인다
  (Task 3의 게이트들은 `stock.get(...)`이 `None`이면 그 게이트를 건너뛰도록 짠다).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_enrich_flow_extras.py`:

```python
"""Sim12의 국면별 게이트 재료: 기관 20일 누적 수급·20일 평균 거래대금·외인 보유율
5일 변화. frgn_net_20d와 같은 표에서 재활용한다(추가 호출 0)."""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.workers.trade_engine import TradeEngineWorker

# 열 순서: 날짜 종가 등락화살표 등락률 거래량 기관순매매량 외국인순매매량 외인보유주식수 외인보유율
_ROW = ('<tr><td>2026.08.{d:02d}</td><td>{px:,}</td><td>0</td><td>0</td>'
        '<td>{vol:,}</td><td>{orgn:+,}</td><td>{frgn:+,}</td><td>0</td><td>{hold}%</td></tr>')


def _page(rows):
    """rows: [(px, vol, orgn, frgn, hold), ...] 최신순(오늘이 0번째)."""
    body = ''.join(_ROW.format(d=20 - i, px=r[0], vol=r[1], orgn=r[2], frgn=r[3], hold=r[4])
                    for i, r in enumerate(rows))
    return f'<table class="type2"><tr><td>x</td></tr>{body}</table>'.encode('euc-kr')


def _enrich(html, existing=None):
    res = mock.Mock()
    res.content = html
    kis = mock.MagicMock()
    kis.get_price_quote.return_value = {}
    kis.get_investor_trend_estimate.return_value = {}
    kis.get_tick_power.return_value = 0.0
    cand = existing or {'code': '005930', 'name': '테스트', 'price': 1000}
    with mock.patch('requests.get', return_value=res), \
         mock.patch('src.trade.kis_data_provider.KISDataProvider', return_value=kis):
        return TradeEngineWorker._enrich_universe(None, [cand])[0]


def test_orgn_net_20d_averages_the_daily_ratio():
    rows = [(1000, 1_000_000, 30_000, 50_000, 46.0)] * 20
    out = _enrich(_page(rows))

    assert out['orgn_net_20d'] == 3.0


def test_amount_ma20_is_close_times_volume_averaged():
    rows = [(1000, 1_000_000, 0, 0, 46.0)] * 20
    out = _enrich(_page(rows))

    assert out['amount_ma20'] == 1000 * 1_000_000


def test_frgn_hold_chg_5d_is_today_minus_five_days_ago():
    # index 0(오늘)=46.0%, index 5(5거래일 전)=44.0% → +2.0%p
    rows = [(1000, 1_000_000, 0, 0, 46.0)] * 5 + [(1000, 1_000_000, 0, 0, 44.0)] * 15
    out = _enrich(_page(rows))

    assert round(out['frgn_hold_chg_5d'], 3) == 2.0


def test_missing_fields_when_fewer_than_six_rows():
    """5일 전 값을 못 만들면(행 부족) 지어내지 않는다 — 키 자체가 없어야 한다."""
    rows = [(1000, 1_000_000, 10_000, 10_000, 46.0)] * 3
    out = _enrich(_page(rows))

    assert 'frgn_hold_chg_5d' not in out
    assert 'orgn_net_20d' in out  # 이건 3행만 있어도 계산 가능


def test_existing_values_are_not_overwritten():
    out = _enrich(_page([(1000, 1_000_000, 30_000, 50_000, 46.0)] * 20),
                  existing={'code': '005930', 'name': 'x', 'price': 1000,
                            'orgn_net_20d': -99.0, 'amount_ma20': -1.0,
                            'frgn_hold_chg_5d': -1.0})

    assert out['orgn_net_20d'] == -99.0
    assert out['amount_ma20'] == -1.0
    assert out['frgn_hold_chg_5d'] == -1.0
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_enrich_flow_extras.py -v`
Expected: FAIL — `KeyError: 'orgn_net_20d'` 등(아직 필드가 없음).

- [ ] **Step 3: 구현**

`src/pipeline/workers/trade_engine.py`의 `frgn_net_20d`를 만드는 블록
(`stock.setdefault('frgn_net_20d', sum(ratios) / len(ratios))` 다음 줄) 바로 뒤에 추가:

```python
                    # [Sim12] 기관 20일 누적 수급·20일 평균 거래대금·외인 보유율 5일 변화.
                    # frgn_net_20d와 같은 표에서 재활용(추가 호출 0). 2026-08-20 KOSPI
                    # 규칙마이닝: "기관 20일 순매도 + 고PER" 조합이 단독 효과의 4배가
                    # 넘는 회피 신호였다(fwd_10d -8.78%p/-8.48%p) — 그 게이트의 재료.
                    orgn_ratios = []
                    for row in data_rows:
                        try:
                            vol = float(row[4].get_text().replace(',', '').strip())
                            net = float(row[5].get_text().replace(',', '').replace('+', '').strip())
                            if vol > 0:
                                orgn_ratios.append(net / vol * 100)
                        except Exception:
                            continue
                    if orgn_ratios:
                        stock.setdefault('orgn_net_20d', sum(orgn_ratios) / len(orgn_ratios))

                    amounts = []
                    for row in data_rows:
                        try:
                            close_v = float(row[1].get_text().replace(',', '').strip())
                            vol = float(row[4].get_text().replace(',', '').strip())
                            amounts.append(close_v * vol)
                        except Exception:
                            continue
                    if amounts:
                        stock.setdefault('amount_ma20', sum(amounts) / len(amounts))

                    if len(data_rows) >= 6:
                        try:
                            hold_5d_ago = float(
                                data_rows[5][8].get_text().replace('%', '').replace(',', '').strip() or 0
                            )
                            stock.setdefault('frgn_hold_chg_5d',
                                             round(stock['foreign_rate'] - hold_5d_ago, 3))
                        except Exception:
                            pass
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_enrich_flow_extras.py -v`
Expected: 5 passed

- [ ] **Step 5: 기존 회귀 확인**

Run: `python -m pytest tests/test_enrich_range_history.py tests/test_enrich_frgn_net_20d.py tests/test_shared_universe_enrichment.py -v`
Expected: 전부 PASS (기존 필드에 영향 없음)

- [ ] **Step 6: 커밋**

```bash
git add src/pipeline/workers/trade_engine.py tests/test_enrich_flow_extras.py
git commit -m "feat(sim12): 공유 인프라에 기관20일수급·20일평균거래대금·외인보유율5일변화 추가"
```

---

### Task 2: `_apply`가 BUY 주문의 playbook 메타데이터를 포트폴리오에 남기도록

**Files:**
- Modify: `src/strategy/simulators/base_simulator.py` (`_apply` 메서드)
- Test: `tests/test_base_simulator_playbook_tag.py`

**Interfaces:**
- Consumes: `decide_sim12`가 만드는 BUY 주문 dict에 선택적 키 `'playbook'`(int, 1 또는 2).
- Produces: `self.state['portfolio'][code]['playbook']` — Sim12의 청산 로직(Task 3)이
  "이 포지션이 어느 플레이북으로 들어왔는지" 판단할 때 읽는다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_base_simulator_playbook_tag.py`:

```python
"""_apply가 BUY 주문의 playbook 메타데이터를 포트폴리오에 남긴다 — SELL의
mark_partial과 같은 패턴. Sim12가 '이 포지션이 어느 플레이북으로 들어왔는지'
청산 시점에 알아야 한다(플레이북2만 5일 타임스탑 대상)."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy.simulators.base_simulator import BaseSimulator


def _sim(tmp_path):
    s = BaseSimulator("PlaybookTagTest", initial_cash=3_000_000)
    s.state_file = str(tmp_path / "s.json")
    s.csv_file = str(tmp_path / "s.csv")
    s.log_file = str(tmp_path / "s.log")
    s.state = {'initial_cash': 3_000_000, 'cash': 3_000_000, 'invested': 0,
               'portfolio': {}, 'peak_nav': 3_000_000, 'total_fees': 0,
               'history': [3_000_000], 'daily_trades': [], 'cooldown_codes': {}}
    return s


def test_buy_order_with_playbook_tags_the_position(tmp_path):
    s = _sim(tmp_path)
    order = {'action': 'BUY', 'code': '005930', 'name': '삼성전자', 'price': 1000,
             'quantity': 10, 'playbook': 2, 'reason': 'test'}

    s._apply([order], {'005930': 1000})

    assert s.state['portfolio']['005930']['playbook'] == 2


def test_buy_order_without_playbook_does_not_add_the_key(tmp_path):
    """다른 심들의 기존 BUY 주문(playbook 키가 없음)은 영향받지 않는다."""
    s = _sim(tmp_path)
    order = {'action': 'BUY', 'code': '005930', 'name': '삼성전자', 'price': 1000,
             'quantity': 10, 'reason': 'test'}

    s._apply([order], {'005930': 1000})

    assert 'playbook' not in s.state['portfolio']['005930']
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_base_simulator_playbook_tag.py -v`
Expected: FAIL — `test_buy_order_with_playbook_tags_the_position`에서 KeyError.

- [ ] **Step 3: 구현**

`src/strategy/simulators/base_simulator.py`의 `_apply` 메서드에서 BUY 분기 수정:

```python
    def _apply(self, orders, current_prices=None):
        """decide가 반환한 Order 리스트를 실제 매매로 실행."""
        for o in orders:
            if o['action'] == 'BUY':
                self.buy(o['code'], o['name'], o['price'], o['quantity'], reason=o.get('reason', ''))
                if o.get('playbook') and o['code'] in self.state['portfolio']:
                    self.state['portfolio'][o['code']]['playbook'] = o['playbook']
            elif o['action'] == 'SELL':
                self.sell(o['code'], o['price'], quantity=o.get('quantity'), reason=o.get('reason', ''))
                if o.get('mark_partial') and o['code'] in self.state['portfolio']:
                    self.state['portfolio'][o['code']]['partial_sold'] = True
                    self.state['portfolio'][o['code']]['partial_sold_date'] = get_kst_date().isoformat()
            if o.get('cooldown'):
                self.add_cooldown(o['code'], o['cooldown'])
```

(바뀐 부분은 BUY 분기 안 `if o.get('playbook')...` 두 줄뿐이다.)

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_base_simulator_playbook_tag.py -v`
Expected: 2 passed

- [ ] **Step 5: 기존 심 전체 회귀 확인**

Run: `python -m pytest tests/ -k "sim1 or sim2 or sim3 or sim4 or sim5 or sim6 or sim7 or sim8 or sim9 or sim10 or sim11" -q`
Expected: 전부 PASS(다른 심들은 `playbook` 키를 안 쓰므로 영향 없음)

- [ ] **Step 6: 커밋**

```bash
git add src/strategy/simulators/base_simulator.py tests/test_base_simulator_playbook_tag.py
git commit -m "feat(base): BUY 주문의 playbook 메타데이터를 포트폴리오에 태깅"
```

---

### Task 3: `decide_sim12` 순수함수 — 회피 게이트 + 국면별 진입/청산

**Files:**
- Create: `src/strategy/simulators/sim12_regime_dual.py` (이 태스크에서는 `decide_sim12`
  함수와 상수만; 클래스는 Task 4)
- Test: `tests/test_sim12_regime_dual.py`

**Interfaces:**
- Consumes: `view`(`{'portfolio','cash','initial_cash','nav','cooldown_codes'}`,
  `BaseSimulator._view`가 만드는 표준 shape), `candidates`(list of dict, 각 dict는
  `code,name,price,amount,change_rate,range_history,amount_ma20,orgn_net_20d,
  frgn_net_20d,frgn_hold_chg_5d,per` 키를 가질 수 있음 — 전부 optional, 없으면 해당
  게이트만 건너뜀), `current_prices`(dict), `regime`(`'BULL'|'SIDEWAYS'|'BEAR'|None`),
  `funnel`(list 또는 None).
- Produces: Order 리스트(`{'action','code','name'?,'price','quantity','reason',
  'cooldown','playbook'?}`) — `BaseSimulator._apply`가 그대로 소비하는 표준 shape.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_sim12_regime_dual.py`:

```python
"""Sim12(국면이원 반등/추세형) — decide_sim12 순수함수.

BULL 국면=모멘텀 지속형(이미 오르는 종목 순추세), SIDEWAYS/BEAR=급락반등형(5일
급락 + 거래대금 유지 + 기관 20일 순매수). 2026-08-20 KOSPI 규칙마이닝 실측:
'최고수익 종목 프로파일'이 국면에 따라 정반대였다(강세장 4월엔 모멘텀 지속형이,
약세~횡보 7~8월엔 급락반등형이 대박 패턴)."""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy.simulators.sim12_regime_dual import decide_sim12


def _view(portfolio=None, cash=3_000_000, nav=3_000_000):
    return {'portfolio': portfolio or {}, 'cash': cash, 'initial_cash': 3_000_000,
            'nav': nav, 'cooldown_codes': {}}


def _pos(avg, qty=10, playbook=None, entry_date=None, peak=None):
    p = {'name': 'T', 'quantity': qty, 'avg_price': avg, 'peak_price': peak if peak is not None else avg,
         'entry_date': entry_date or date.today().isoformat(), 'is_scaled_out': False}
    if playbook is not None:
        p['playbook'] = playbook
    return p


def _bull_candidate(code='111111', price=1300):
    """20일치 range_history: 앞 10일은 1000 횡보, 뒤 10일은 1000→1090으로 상승
    (10일 period_chg = (1090-1000)/1000 = +9.0% >= 임계 8.0%). 20일 평균은 1022.5라
    오늘 price=1300과 비교하면 MA20 이격 +27.1% >= 임계 5.0%(둘 다 여유 있게 통과)."""
    hist = [1000] * 10 + [1000, 1010, 1020, 1030, 1040, 1050, 1060, 1070, 1080, 1090]
    return {'code': code, 'name': '상승모멘텀', 'price': price, 'amount': 5_000_000_000,
            'amount_ma20': 4_000_000_000, 'change_rate': '+2.0%',
            'range_history': hist, 'orgn_net_20d': 1.0, 'frgn_net_20d': 1.0,
            'per': 15.0}


def _pb2_candidate(code='222222', price=940):
    """5일 전(hist[-6]) 대비 급락(hist[-1]=940이 5일전보다 -10%대), 거래대금 유지,
    기관 20일 순매수."""
    hist = [1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000,
            1000, 1000, 1000, 1000, 1046, 1000, 970, 960, 950, 940]
    return {'code': code, 'name': '급락반등', 'price': price, 'amount': 4_500_000_000,
            'amount_ma20': 4_000_000_000, 'change_rate': '-1.0%',
            'range_history': hist, 'orgn_net_20d': 2.0, 'frgn_net_20d': 0.5,
            'per': 10.0}


# ── 회피 게이트 ──────────────────────────────────────────────────────

def test_avoids_entry_when_amount_dried_up():
    cand = _bull_candidate()
    cand['amount_ma20'] = cand['amount']  # 비율 1.0으로 만들고
    cand['amount'] = cand['amount_ma20'] * 0.5  # 거래대금이 20일평균의 절반 → 급감
    funnel = []
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BULL', funnel=funnel)

    assert not [o for o in orders if o['action'] == 'BUY']
    assert any(f['reason'] == 'avoid_amount_dry' for f in funnel)


def test_avoids_entry_when_institutions_sell_and_per_is_high():
    cand = _bull_candidate()
    cand['orgn_net_20d'] = -6.0
    cand['per'] = 50.0
    funnel = []
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BULL', funnel=funnel)

    assert not [o for o in orders if o['action'] == 'BUY']
    assert any(f['reason'] == 'avoid_orgn_sell_high_per' for f in funnel)


def test_institutions_selling_alone_without_high_per_does_not_veto():
    """기관 매도만으로는(고PER이 아니면) 이 조합 게이트가 안 걸린다 — 단독
    orgn_net_20d 회피는 이번 구현 범위 밖(조합 게이트만 넣었다)."""
    cand = _bull_candidate()
    cand['orgn_net_20d'] = -6.0
    cand['per'] = 15.0  # 고PER 아님
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BULL')

    assert [o for o in orders if o['action'] == 'BUY']


def test_avoids_entry_when_foreign_20d_sell_regime():
    cand = _bull_candidate()
    cand['frgn_net_20d'] = -6.0
    funnel = []
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BULL', funnel=funnel)

    assert not [o for o in orders if o['action'] == 'BUY']
    assert any(f['reason'] == 'avoid_frgn_sell_20d' for f in funnel)


def test_missing_gate_fields_do_not_block_entry():
    """모르는 값은 '회피'로 지어내지 않는다."""
    cand = _bull_candidate()
    del cand['orgn_net_20d']
    del cand['frgn_net_20d']
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BULL')

    assert [o for o in orders if o['action'] == 'BUY']


# ── 플레이북1: BULL(모멘텀 지속형) ───────────────────────────────────

def test_bull_regime_enters_on_momentum_continuation():
    cand = _bull_candidate()
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BULL')

    buys = [o for o in orders if o['action'] == 'BUY']
    assert len(buys) == 1 and buys[0]['playbook'] == 1


def test_bull_regime_skips_when_momentum_is_weak():
    cand = _bull_candidate(price=1000)  # 이격 거의 없음
    funnel = []
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BULL', funnel=funnel)

    assert not [o for o in orders if o['action'] == 'BUY']


def test_sideways_regime_does_not_use_playbook1_entry():
    """BULL 조건을 만족하는 후보라도 SIDEWAYS 국면이면 플레이북1로 안 산다
    (플레이북2 조건은 못 만족하므로 둘 다 안 산다)."""
    cand = _bull_candidate()
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'SIDEWAYS')

    assert not [o for o in orders if o['action'] == 'BUY']


# ── 플레이북2: SIDEWAYS/BEAR(급락반등형) ─────────────────────────────

def test_sideways_regime_enters_on_crash_rebound_with_institutions_buying():
    cand = _pb2_candidate()
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'SIDEWAYS')

    buys = [o for o in orders if o['action'] == 'BUY']
    assert len(buys) == 1 and buys[0]['playbook'] == 2


def test_bear_regime_also_uses_playbook2():
    cand = _pb2_candidate()
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BEAR')

    assert [o for o in orders if o['action'] == 'BUY']


def test_playbook2_skips_without_institutional_buying():
    cand = _pb2_candidate()
    cand['orgn_net_20d'] = -1.0
    funnel = []
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'SIDEWAYS', funnel=funnel)

    assert not [o for o in orders if o['action'] == 'BUY']
    assert any(f['reason'] == 'pb2_no_inst_buying' for f in funnel)


def test_playbook2_skips_when_liquidity_too_thin():
    """5일 급락 + 거래대금유지 조합 규칙 — 유동성 없으면(하위) 반등 신호가 아니다."""
    cand = _pb2_candidate()
    cand['amount'] = cand['amount_ma20'] * 0.7  # 회피게이트(0.65)는 안 걸리지만 pb2 기준(1.0)엔 미달
    funnel = []
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'SIDEWAYS', funnel=funnel)

    assert not [o for o in orders if o['action'] == 'BUY']
    assert any(f['reason'] == 'pb2_thin_liquidity' for f in funnel)


# ── 국면 판정불가 ────────────────────────────────────────────────────

def test_unknown_regime_makes_no_new_entries():
    cand = _bull_candidate()
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, None)

    assert not [o for o in orders if o['action'] == 'BUY']


# ── 청산 ─────────────────────────────────────────────────────────────

def test_hard_stop_loss_applies_regardless_of_playbook():
    portfolio = {'005930': _pos(avg=1000, playbook=2)}
    orders = decide_sim12(_view(portfolio=portfolio), [], {'005930': 920}, 'SIDEWAYS')

    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '손절' in sells[0]['reason']


def test_playbook2_time_stops_after_five_days_even_at_a_profit():
    old_date = (date.today() - timedelta(days=5)).isoformat()
    portfolio = {'005930': _pos(avg=1000, playbook=2, entry_date=old_date)}
    orders = decide_sim12(_view(portfolio=portfolio), [], {'005930': 1010}, 'SIDEWAYS')

    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '타임스탑' in sells[0]['reason']


def test_playbook1_does_not_time_stop():
    """플레이북1(모멘텀 지속형)은 5일 타임스탑 대상이 아니다 — 추세를 더 태운다."""
    old_date = (date.today() - timedelta(days=10)).isoformat()
    portfolio = {'005930': _pos(avg=1000, playbook=1, entry_date=old_date)}
    orders = decide_sim12(_view(portfolio=portfolio), [], {'005930': 1010}, 'BULL')

    assert not [o for o in orders if o['action'] == 'SELL']


def test_untagged_position_does_not_time_stop():
    """playbook 태그가 없는(레거시/수동) 포지션은 타임스탑 대상이 아니다."""
    old_date = (date.today() - timedelta(days=10)).isoformat()
    portfolio = {'005930': _pos(avg=1000, entry_date=old_date)}
    orders = decide_sim12(_view(portfolio=portfolio), [], {'005930': 1010}, 'SIDEWAYS')

    assert not [o for o in orders if o['action'] == 'SELL']


def test_trailing_stop_triggers_after_activation_and_pullback():
    """고점 1100(+10%)에서 1060으로 빠지면 고점대비 -3.64% → 콜백 3.0% 이상, 매도."""
    portfolio = {'005930': _pos(avg=1000, playbook=1, peak=1100)}
    orders = decide_sim12(_view(portfolio=portfolio), [], {'005930': 1060}, 'BULL')

    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '트레일링' in sells[0]['reason']


def test_trailing_stop_does_not_trigger_before_activation():
    """고점이 아직 +5%(활성화 기준)에 못 미치면 하락해도 트레일링은 안 걸린다."""
    portfolio = {'005930': _pos(avg=1000, playbook=1, peak=1020)}
    orders = decide_sim12(_view(portfolio=portfolio), [], {'005930': 990}, 'BULL')

    assert not [o for o in orders if o['action'] == 'SELL']
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_sim12_regime_dual.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.strategy.simulators.sim12_regime_dual'`

- [ ] **Step 3: 최소 구현**

Create `src/strategy/simulators/sim12_regime_dual.py`:

```python
from .base_simulator import BaseSimulator, get_kst_date

_parse_change_rate = BaseSimulator.parse_change_rate
_cooldown_active = BaseSimulator.cooldown_active
_period_change = BaseSimulator.calc_period_change

# ── 파라미터(2026-08-20 KOSPI 규칙마이닝 분위수 경계의 근사치 — 정밀 보정 아님) ──
MAX_HOLDINGS = 5
POSITION_WEIGHT = 0.19

AMOUNT_RATIO_DRY = 0.65          # 거래대금 급감(회피). 리서치 q1 상한 그대로.
AMOUNT_RATIO_OK = 1.0            # 플레이북2 최소 유동성. 리서치 quantile(0.6)≈1.01 근사.
PER_HIGH = 40.0                  # 고PER(회피 조합용). 리서치 q5 하한 44.6의 보수적 근사.
ORGN_NET_20D_SELL = -5.0         # 기관 20일 매도국면. 리서치 q1 상한 -5.94 근사.
FRGN_NET_20D_SELL = -5.0         # 외국인 20일 매도국면. 리서치 q1 상한 -5.79 근사.
FRGN_HOLD_CHG_5D_DROP = -1.0     # 외인 보유율 5일 급감. 표본이 작아 보수적으로 완화(원 규칙12는 더 좁음).

PERIOD_CHG_10D_BULL_MIN = 8.0    # 플레이북1: 10일간 이미 상승 중(모멘텀 확인).
DEV_MA20_BULL_MIN = 5.0          # 플레이북1: MA20 위로 뚜렷하게 이격.
PERIOD_CHG_5D_CRASH_MAX = -6.0   # 플레이북2: 5일 급락(하위20% 근사, q1 상한 -5.78).

RET_1D_HIGH = 5.0                # 회피(데드캣): 당일 급등 기준.
PERIOD_CHG_10D_CRASH_MAX = -10.0  # 회피(데드캣): 10일간 하락추세였는지.

STOP_PCT = -7.0                  # 하드손절. Sim2와 동일 관례.
TRAIL_ACTIVATION_PCT = 5.0       # 트레일링 활성화 수익률. Sim2와 동일 관례.
TRAIL_CALLBACK_PCT = 3.0         # 트레일링 콜백(고점 대비 하락률). Sim2와 동일 관례.
PLAYBOOK2_TIMESTOP_DAYS = 5       # 급락반등형 최대 보유일(설계서 "3~5일" 상한).


def _fn(funnel, code, reason, **vals):
    """왜 안 샀는지 한 줄 남긴다(심4-1·심6·심9와 같은 방식)."""
    if funnel is None:
        return
    funnel.append({'code': code, 'reason': reason, **vals})


def _holding_days(p_item, today):
    s = p_item.get('entry_date', '')
    try:
        return (today - date_fromiso(s)).days if s else 0
    except Exception:
        return 0


def date_fromiso(s):
    from datetime import datetime
    return datetime.strptime(s, '%Y-%m-%d').date()


def _pchg(range_history, days):
    """N거래일 전 종가 대비 변동률(%). 행이 부족하면 None(모른다 — 0%로 지어내지 않는다)."""
    if not range_history or len(range_history) < days + 1:
        return None
    return _period_change(range_history[-(days + 1):])


def _dev_ma(range_history, price, window):
    """가격이 최근 window일 평균(MA) 대비 몇 % 위/아래인지. 재료 부족하면 None."""
    if not range_history or len(range_history) < window or price <= 0:
        return None
    hist = range_history[-window:]
    ma = sum(hist) / len(hist)
    if ma <= 0:
        return None
    return (price - ma) / ma * 100.0


def _avoid(stock, funnel):
    """국면 무관 공통 회피 게이트. 걸리면 True(신규 진입 금지)."""
    code = stock['code']

    amount = stock.get('amount')
    amount_ma20 = stock.get('amount_ma20')
    amount_ratio = (amount / amount_ma20) if (amount and amount_ma20) else None
    if amount_ratio is not None and amount_ratio <= AMOUNT_RATIO_DRY:
        _fn(funnel, code, 'avoid_amount_dry', amount_ratio=amount_ratio)
        return True

    orgn_20d = stock.get('orgn_net_20d')
    per = stock.get('per')
    if (orgn_20d is not None and orgn_20d <= ORGN_NET_20D_SELL
            and per is not None and per >= PER_HIGH):
        _fn(funnel, code, 'avoid_orgn_sell_high_per', orgn_net_20d=orgn_20d, per=per)
        return True

    frgn_20d = stock.get('frgn_net_20d')
    if frgn_20d is not None and frgn_20d <= FRGN_NET_20D_SELL:
        _fn(funnel, code, 'avoid_frgn_sell_20d', frgn_net_20d=frgn_20d)
        return True

    frgn_hold_chg = stock.get('frgn_hold_chg_5d')
    if frgn_hold_chg is not None and frgn_hold_chg <= FRGN_HOLD_CHG_5D_DROP:
        _fn(funnel, code, 'avoid_frgn_hold_drop', frgn_hold_chg_5d=frgn_hold_chg)
        return True

    ret_1d = _parse_change_rate(stock)
    period_chg_10d = _pchg(stock.get('range_history', []), 10)
    if (ret_1d >= RET_1D_HIGH and period_chg_10d is not None
            and period_chg_10d <= PERIOD_CHG_10D_CRASH_MAX):
        _fn(funnel, code, 'avoid_deadcat', ret_1d=ret_1d, period_chg_10d=period_chg_10d)
        return True

    return False


def _playbook1_entry(stock, funnel):
    """모멘텀 지속형(BULL 전용). (통과여부, 사유문구)."""
    code = stock['code']
    price = float(stock.get('price', 0))
    range_history = stock.get('range_history', [])
    period_chg_10d = _pchg(range_history, 10)
    dev_ma20 = _dev_ma(range_history, price, 20)
    if period_chg_10d is None or dev_ma20 is None:
        _fn(funnel, code, 'pb1_no_history')
        return False, ''
    if period_chg_10d < PERIOD_CHG_10D_BULL_MIN:
        _fn(funnel, code, 'pb1_momentum_weak', period_chg_10d=period_chg_10d)
        return False, ''
    if dev_ma20 < DEV_MA20_BULL_MIN:
        _fn(funnel, code, 'pb1_below_ma20', dev_ma20=dev_ma20)
        return False, ''
    return True, f"[Sim12] 상승국면 모멘텀 지속 (10일 {period_chg_10d:+.1f}%, MA20이격 {dev_ma20:+.1f}%)"


def _playbook2_entry(stock, funnel):
    """급락반등형(SIDEWAYS/BEAR 전용). (통과여부, 사유문구)."""
    code = stock['code']
    range_history = stock.get('range_history', [])
    period_chg_5d = _pchg(range_history, 5)
    if period_chg_5d is None:
        _fn(funnel, code, 'pb2_no_history')
        return False, ''
    if period_chg_5d > PERIOD_CHG_5D_CRASH_MAX:
        _fn(funnel, code, 'pb2_not_crashed', period_chg_5d=period_chg_5d)
        return False, ''

    amount = stock.get('amount')
    amount_ma20 = stock.get('amount_ma20')
    amount_ratio = (amount / amount_ma20) if (amount and amount_ma20) else None
    if amount_ratio is None or amount_ratio < AMOUNT_RATIO_OK:
        _fn(funnel, code, 'pb2_thin_liquidity', amount_ratio=amount_ratio)
        return False, ''

    orgn_20d = stock.get('orgn_net_20d')
    if orgn_20d is None or orgn_20d <= 0:
        _fn(funnel, code, 'pb2_no_inst_buying', orgn_net_20d=orgn_20d)
        return False, ''

    return True, f"[Sim12] 급락반등 (5일 {period_chg_5d:.1f}%, 기관20일 {orgn_20d:+.1f}%)"


def decide_sim12(view, candidates, current_prices, regime, funnel=None):
    """[Sim12] 국면이원(모멘텀 지속형/급락반등형) 결정. 순수 함수. Order 리스트 반환.

    BULL이면 플레이북1(이미 오르는 종목 순추세), SIDEWAYS/BEAR면 플레이북2(5일 급락
    + 거래대금 유지 + 기관 20일 순매수)로 진입 로직 자체가 바뀐다 — 2026-08-20 KOSPI
    규칙마이닝 "최고수익 종목 프로파일" 절 실측(강세장 4월 vs 약세~횡보 7~8월에서
    최고수익 패턴이 정반대였다)을 그대로 반영.
    """
    orders = []
    portfolio = view['portfolio']
    today = get_kst_date()
    sold = set()

    # 1. 청산: 하드손절(공통) + 플레이북2 전용 5일 타임스탑.
    for code in list(portfolio.keys()):
        p = portfolio[code]
        cur = current_prices.get(code, 0)
        if cur <= 0:
            continue
        avg = p.get('avg_price', 0)
        if avg <= 0:
            continue
        pr = (cur - avg) / avg * 100

        if pr <= STOP_PCT:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[Sim12] 하드 손절 ({pr:.1f}%)", 'cooldown': 2, 'mark_partial': False})
            sold.add(code)
            continue

        if p.get('playbook') == 2 and _holding_days(p, today) >= PLAYBOOK2_TIMESTOP_DAYS:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': "[Sim12] 급락반등 타임스탑(5일)", 'cooldown': 1, 'mark_partial': False})
            sold.add(code)
            continue

        # 트레일링 스탑: 수익이 한 번이라도 TRAIL_ACTIVATION_PCT를 찍었고 고점 대비
        # TRAIL_CALLBACK_PCT 하락하면 매도. self.check_trailing_stop과 같은 계산이지만
        # decide_sim12는 순수함수라 상태 메서드를 못 부른다 — 심6과 같은 방식으로
        # portfolio에 이미 있는 peak_price를 직접 계산에 쓴다(run()이 decide 호출 전에
        # update_peak_prices를 먼저 불러 최신 고점을 보장한다).
        peak = p.get('peak_price', avg)
        drop_from_peak = (peak - cur) / peak * 100 if peak > 0 else 0
        activated = pr >= TRAIL_ACTIVATION_PCT or peak > avg * (1 + TRAIL_ACTIVATION_PCT / 100)
        if activated and drop_from_peak >= TRAIL_CALLBACK_PCT:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[Sim12] 트레일링 스탑 (고점대비 -{drop_from_peak:.1f}%)",
                           'cooldown': 2, 'mark_partial': False})
            sold.add(code)
            continue

    # 2. 진입: 국면 판정불가면 신규 진입 없음(청산은 위에서 이미 처리했다).
    if regime not in ('BULL', 'SIDEWAYS', 'BEAR'):
        return orders

    held = len(portfolio) - len(sold)
    for stock in candidates:
        if held >= MAX_HOLDINGS:
            break
        code = stock['code']
        if code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            _fn(funnel, code, 'held_or_cooldown')
            continue

        if _avoid(stock, funnel):
            continue

        price = float(stock.get('price', 0))
        if price <= 0:
            _fn(funnel, code, 'no_price')
            continue

        if regime == 'BULL':
            ok, reason = _playbook1_entry(stock, funnel)
            playbook = 1
        else:
            ok, reason = _playbook2_entry(stock, funnel)
            playbook = 2
        if not ok:
            continue

        invest = view['nav'] * POSITION_WEIGHT
        qty = int(invest / price)
        if qty <= 0:
            _fn(funnel, code, 'qty_zero', price=price)
            continue

        orders.append({'action': 'BUY', 'code': code, 'name': stock.get('name', code), 'price': price,
                       'quantity': qty, 'cooldown': None, 'playbook': playbook, 'reason': reason})
        held += 1

    return orders
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_sim12_regime_dual.py -v`
Expected: 19 passed

(`_bull_candidate`의 10일 변동 +9.0%·MA20 이격 +27.1%, `_pb2_candidate`의 5일 변동
-10.1%는 위 임계값 `PERIOD_CHG_10D_BULL_MIN=8.0`/`DEV_MA20_BULL_MIN=5.0`/
`PERIOD_CHG_5D_CRASH_MAX=-6.0`을 여유 있게 만족하도록 미리 계산해 둔 숫자다.)

- [ ] **Step 5: 커밋**

```bash
git add src/strategy/simulators/sim12_regime_dual.py tests/test_sim12_regime_dual.py
git commit -m "feat(sim12): 국면이원(모멘텀 지속형/급락반등형) 순수 판단함수"
```

---

### Task 4: `RegimeDualSimulator` 클래스 + 유니버스 + 매니페스트 등록

**Files:**
- Modify: `src/strategy/simulators/sim12_regime_dual.py` (클래스 추가)
- Modify: `src/strategy/strategy_manifest.yaml`
- Modify(생성): `src/lib/sim-registry.generated.ts` (`gen_sim_registry.py` 재실행)
- Test: `tests/test_sim12_universe.py`

**Interfaces:**
- Consumes: `KISDataProvider.get_fluctuation_rank(market, sort, limit)`(기존 메서드,
  Task 신설 없음), `regime_state.read_regime(data_dir)`(기존, Sim6이 이미 씀).
- Produces: 매니페스트 등록 완료(`get_sim_registry()`에 `sim12_regime_dual` 등장),
  `RegimeDualSimulator.run(candidates, current_prices)` — 다른 심들과 동일 시그니처.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_sim12_universe.py`:

```python
"""Sim12 유니버스: KIS 등락률 상승률·하락률 각 30을 합쳐서 두 플레이북 후보를
동시에 확보한다(상승률만 보면 플레이북2용 급락 후보가 원천적으로 안 잡힌다)."""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy.simulators.sim12_regime_dual import RegimeDualSimulator


def test_universe_merges_gainers_and_decliners():
    gainers = [{'code': '111111', 'name': '상승주', 'price': 1000, 'amount': 1_000}]
    decliners = [{'code': '222222', 'name': '하락주', 'price': 900, 'amount': 900}]

    def fake_rank(market='0001', sort='0', limit=30):
        return gainers if sort == '0' else decliners

    kis = mock.MagicMock()
    kis.get_fluctuation_rank.side_effect = fake_rank
    with mock.patch('src.trade.kis_data_provider.KISDataProvider', return_value=kis):
        sim = RegimeDualSimulator(initial_cash=3_000_000)
        universe = sim.get_universe()

    codes = {s['code'] for s in universe}
    assert codes == {'111111', '222222'}


def test_universe_returns_none_on_failure():
    with mock.patch('src.trade.kis_data_provider.KISDataProvider',
                     side_effect=Exception('boom')):
        sim = RegimeDualSimulator(initial_cash=3_000_000)
        assert sim.get_universe() is None


def test_regime_none_when_libero_state_missing(tmp_path):
    sim = RegimeDualSimulator(initial_cash=3_000_000)
    sim.data_dir = str(tmp_path)  # sim_libero_state.json이 없는 빈 디렉터리
    assert sim._read_regime() is None
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_sim12_universe.py -v`
Expected: FAIL — `ImportError: cannot import name 'RegimeDualSimulator'`

- [ ] **Step 3: 구현**

`src/strategy/simulators/sim12_regime_dual.py` 맨 아래에 추가:

```python
from ..regime_state import read_regime


class RegimeDualSimulator(BaseSimulator):
    """
    [Sim 12] 국면이원 반등/추세형 (Regime-Dual Momentum/Rebound)
    - 2026-08-20 KOSPI 규칙마이닝(Tier1) 기반. Sim0(리베로) 국면에 따라 진입 로직
      자체가 바뀐다.
    - BULL: 플레이북1(모멘텀 지속형) — 10일간 이미 강하게 상승 + MA20 위로 크게 이격.
    - SIDEWAYS/BEAR: 플레이북2(급락반등형) — 5일 급락 + 거래대금 유지 + 기관 20일
      순매수.
    - 공통 회피 게이트: 거래대금 급감/기관·외국인 20일 지속 순매도/외인 보유율
      급감/데드캣(당일급등+10일 하락추세)은 국면 무관하게 신규 진입 금지.
    - 청산: 하드손절 -7% + 트레일링(+5% 활성/-3% 콜백, 둘 다 공통·Sim2와 동일 관례).
      플레이북2는 추가로 5일 타임스탑(반등이 10일 시계에서 재하락하는 경향 — 설계서
      참고). 플레이북1은 타임스탑 없음(추세를 더 태움).
    - 페이퍼 관찰 단계(tradeable: false) — 백테스트 미검증, 임계값은 리서치 분위수
      경계의 근사치다.
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("RegimeDual", initial_cash)

    def get_universe(self):
        """코스피 등락률 상승률·하락률 각 30개를 합친다. 상승률만 보면 플레이북2
        (급락반등형)의 후보가 원천적으로 안 잡힌다 — 두 플레이북이 정반대 방향의
        종목을 필요로 하므로 양쪽 다 확보해야 한다."""
        try:
            from src.trade.kis_data_provider import KISDataProvider
            kis = KISDataProvider()
            gainers = kis.get_fluctuation_rank(market='0001', sort='0', limit=30)
            decliners = kis.get_fluctuation_rank(market='0001', sort='1', limit=30)
            merged = {s['code']: s for s in (gainers or [])}
            for s in (decliners or []):
                merged.setdefault(s['code'], s)
            return list(merged.values()) or None
        except Exception:
            return None

    def _read_regime(self):
        """Sim0(리베로)의 국면 판단을 읽는다. 판단 불가면 None — 신규 진입을
        건너뛴다(Sim6과 같은 원칙: 모르는 국면으로 실제 주문을 내지 않는다)."""
        return read_regime(self.data_dir)[0]

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        regime = self._read_regime()
        funnel = []
        orders = decide_sim12(self._view(current_prices), candidates, current_prices,
                              regime, funnel=funnel)
        self._log_funnel(candidates, funnel, orders, regime)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)

    @staticmethod
    def _log_funnel(candidates, funnel, orders, regime) -> None:
        """어느 국면에서 어느 게이트에 막혔는지 남긴다 — 심6·심9와 같은 방식
        (sim_diag)으로 db-data에 남아야 다음 사이클 이후에도 확인 가능하다."""
        try:
            from collections import Counter
            if not funnel and not orders:
                return
            try:
                from src.data import sim_diag
                sim_diag.append('sim12', [dict(f, decision='skip') for f in funnel]
                                + [dict(code=o.get('code'), reason='entry', decision='entry')
                                   for o in orders], log=lambda *_: None)
            except Exception:
                pass
            c = Counter(f['reason'] for f in funnel)
            parts = ', '.join(f'{k} {v}' for k, v in c.most_common())
            print(f"[Sim12 깔때기] 국면={regime} 후보 {len(candidates)} → 매수 {len(orders and [o for o in orders if o['action']=='BUY'])} | 탈락: {parts}")
        except Exception as e:
            print(f'[Sim12 깔때기] 기록 실패(무시): {e}')
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_sim12_universe.py -v`
Expected: 3 passed

- [ ] **Step 5: 매니페스트 등록**

`src/strategy/strategy_manifest.yaml`의 Sim11 항목(`id: "sim11_minervini"`) 블록 바로
뒤에 추가:

```yaml
  - id: "sim12_regime_dual"
    module: "src.strategy.simulators.sim12_regime_dual"
    class: "RegimeDualSimulator"
    description: "Sim12 국면이원 반등/추세형 — BULL은 모멘텀 지속, SIDEWAYS/BEAR는 5일 급락+거래대금유지+기관순매수 반등"
    state_file: "sim_regimedual_state.json"
    csv_file: "trade_history_sim_regimedual.csv"
    label: "국면이원 반등/추세형 (Sim 12)"
    display_order: 120
    ui_key: "sim12"
    short_desc: "BULL=모멘텀 지속 / SIDEWAYS·BEAR=급락반등(거래대금+기관수급 확인)"
    chart_group: 4
    color: "teal"
    active: true
    tradeable: false  # 신규(2026-08-20), 백테스트 없음 — 페이퍼 관찰 단계(Sim11과 동일 관례)
    needs_buzz: false  # KIS 등락률 순위 자체 유니버스 — 60초 매매 루프에서 돈다
```

- [ ] **Step 6: 레지스트리 생성물 갱신**

Run: `python scripts/gen_sim_registry.py`

- [ ] **Step 7: 진단 CSV 배포 목록에 sim12 추가**

Sim12는 이 60초 매매 루프에서만 돌고(scraper.yml의 넓은 `data/*.csv` 배포 대상이
아니다), `sim_diag.append('sim12', ...)`로 남긴 진단 CSV는 명시적 배포 매니페스트에
없으면 컨테이너 종료와 함께 사라진다 — Sim6·Sim9에서 2026-08-20에 이미 겪은 함정과
같다. `scripts/trade_loop.py`의 `diag_ids` 딕셔너리에 한 줄만 추가:

```python
diag_ids = {'sim6_bear': 'sim6', 'sim9_gap_fade': 'sim9', 'sim12_regime_dual': 'sim12'}
```

`tests/test_trade_loop.py`에 아래 테스트 추가(기존 `test_sim9_extra_sim_id_also_carries_its_diag_file`
바로 뒤):

```python
def test_sim12_extra_sim_id_also_carries_its_diag_file(tmp_path, monkeypatch):
    from src.data.sim_diag import month_path
    monkeypatch.chdir(tmp_path)
    now = _Ctx().now_kst
    trade_loop._write_deploy_manifest(
        None, log=lambda *a: None, now=now, extra_sim_ids={'sim12_regime_dual'})
    lines = (tmp_path / 'data' / '.lite_deploy_manifest').read_text(
        encoding='utf-8').split()
    assert 'sim_regimedual_state.json' in lines
    assert os.path.basename(month_path('sim12', now.strftime('%Y%m%d'))) in lines
```

Run: `python -m pytest tests/test_trade_loop.py -v`
Expected: 기존 통과 건수 + 1건(신규) 모두 PASS

- [ ] **Step 8: 매니페스트 정합성 회귀 확인**

Run: `python -m pytest tests/test_sim_registry_consistency.py tests/test_sim12_regime_dual.py tests/test_sim12_universe.py tests/test_needs_buzz_registry.py tests/test_all_sims_can_trade.py tests/test_trade_loop.py -v`
Expected: 전부 PASS

- [ ] **Step 9: 커밋**

```bash
git add src/strategy/simulators/sim12_regime_dual.py tests/test_sim12_universe.py \
        src/strategy/strategy_manifest.yaml src/lib/sim-registry.generated.ts \
        scripts/trade_loop.py tests/test_trade_loop.py
git commit -m "feat(sim12): 국면이원 반등/추세형 신규 심 등록 (페이퍼 관찰 단계)"
```

---

### Task 5: 전체 회귀 확인

**Files:** 없음(검증만)

- [ ] **Step 1: 전체 스위트 실행**

Run: `python -m pytest tests/ -q`
Expected: 이전 통과 건수(1283) + 이번에 추가한 테스트(5+2+19+3=29) = 1312건 모두 PASS,
4 skipped 유지.

- [ ] **Step 2: Sim12가 실제로 사이클을 도는지 스모크 테스트**

```bash
python -c "
from src.strategy.simulators.sim12_regime_dual import RegimeDualSimulator
s = RegimeDualSimulator(initial_cash=3_000_000)
print(s.run([], {}))
"
```

Expected: 예외 없이 통계 dict가 출력된다(빈 후보·빈 가격이라 매매는 없지만 국면
파일이 없어도(`_read_regime` None) 죽지 않아야 한다).
