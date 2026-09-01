"""심이 "왜 안 샀는지"를 남기지 않으면 CI가 막는다.

================================================================
왜 이 테스트가 있는가
================================================================
2026-09-01, 장중 실전 매매 0건의 원인을 찾는 데 로그가 도움이 안 됐다.

    [Sim3 깔때기] 후보 30 | 탈락: amount 17, not_cheap 5, adx 1

30개 중 23개만 설명된다. 나머지 7개는 보유·쿨다운 `continue`로 빠지는데 그
분기에 기록이 없다. 그래서 "조건 미달이라 안 샀다"와 "배선이 죽어 후보가
사라졌다"가 로그에서 똑같이 생겼고, 매번 소급 추론을 해야 했다.

같은 날 전 심을 세어보니 **16개 중 11개가 탈락 사유를 하나도 안 남기고**
있었다. 실전 자금을 쓰는 sim3_risk조차 70%였고, **빠진 30%가 정확히 그날
발동한 경로**였다.

이건 심 하나의 버그가 아니라 계약의 부재다. `_fn`을 부를지 말지가 각 심의
자유재량이면, 새 심은 기본값으로 아무것도 안 남긴다. 그래서 규칙을 코드
바깥(리뷰어의 기억)이 아니라 CI에 둔다.

================================================================
래칫(ratchet)
================================================================
지금 있는 구멍을 한 번에 다 메우려면 11개 심의 매수 로직을 동시에 건드려야
한다 — 실전이 도는 중에 할 일이 아니다. 그래서 **현재 구멍 수를 상한으로
박아두고, 줄어들면 상한도 같이 줄이도록 강제한다.**

  - 구멍이 늘면 실패한다(새 심·새 분기가 기록 없이 들어오는 것을 막는다)
  - 구멍이 줄었는데 목록을 안 고쳐도 실패한다(목록이 낡는 것을 막는다)

허용치를 0으로 만드는 것이 목표다. 목록에 남은 숫자가 곧 남은 빚이다.
"""
import ast
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

SIM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       '..', 'src', 'strategy', 'simulators')

# 탈락 사유를 남기는 호출로 인정하는 이름들. 심마다 헬퍼 이름이 다르다.
_LOGGERS = {'_fn', '_diag', 'log_diag', 'record_decision'}

# 기록 장부로 인정하는 변수명. 헬퍼에 넘기거나(`_avoid(stock, funnel)`)
# 직접 append하는(`diags.append(d)`) 두 형태를 모두 인정한다.
#
# 심1-1은 깔때기 대신 진단 dict를 `diags`에 쌓는다 — 남기는 정보는 오히려 더
# 많은데, 이름만 보고 "기록 안 함"으로 몰면 **정직한 심이 거짓 양성으로 걸린다.**
# 그러면 사람들이 형식적으로 `_fn`을 끼워 넣어 통과시키고, 남은 숫자가 남은
# 빚을 뜻하지 않게 된다.
_LEDGERS = {'funnel', 'diags'}

# 매수 루프를 **이름이 아니라 하는 일로** 찾는다. 본문 어딘가에서 매수를
# 만드는 For 루프만 대상이다.
#
# 처음에는 이터레이터 이름(`candidates`·`stocks`·`rows`…)으로 골랐는데 두
# 방향으로 틀렸다. 이름이 다른 매수 루프를 놓쳤고, 반대로 피처 계산 루프
# (심8의 z-점수·관심도 집계)까지 끌어와 **갚아도 의미 없는 빚**을 만들었다.
# 그 루프의 `continue`는 "후보를 버렸다"가 아니라 "이 행에 필드가 없다"이고,
# 그 결과는 어차피 매수 루프에서 `no_investor_flow` 같은 이유로 다시 잡힌다.
_BUY_MARKERS = ("'action': 'BUY'", '"action": "BUY"', 'self.buy(')

# ── 래칫 ────────────────────────────────────────────────────────────
# 파일명 → 기록 없이 후보를 탈락시키는 분기 수(2026-09-01 실측).
# **줄이는 방향으로만 고친다.** 0이 되면 항목째로 지운다.
KNOWN_UNLOGGED: dict[str, int] = {}
# ── 2026-09-01: 빚을 다 갚았다. 57개/14심 → **0**. ──────────────────
#
# 이 사전이 비어 있다는 것은 "**등재된 모든 심이, 후보를 버릴 때마다 이유를
# 남긴다**"는 뜻이다. 다시 채워지는 순간은 누군가 기록 없는 분기를 새로
# 넣었을 때뿐이고, 그때 CI가 막는다.
#
# 상환 순서: sim3_risk(실전 먼저) → sim4-1·sim6·sim9·sim12·sim13(복제된
# `if held >= MAX_HOLDINGS: break`) → sim5·sim8·sim9-1·sim11 → sim2·sim1-1 →
# us_sim1·2·3 → sim4(진입 + 불타기 두 장부).
#
# 게이트 자체를 **다섯 번** 고쳤고 전부 리뷰나 실측이 잡았다. 숫자가 중간에
# 오르내린 것은 심이 나빠져서가 아니라 검사가 정확해졌기 때문이다.
#   1. "한 번 기록하면 계속 기록됨"이 블록 밖으로 새어, 루프 맨 위의 `_fn`
#      하나가 아래 침묵을 전부 가렸다 — 게이트가 스스로를 무력화했다.
#   2. 파일명 접두사 필터가 미국 심 3개를 빠뜨렸고, 반대로 매니페스트에서 빠진
#      죽은 심까지 세어 갚을 수 없는 빚을 만들었다. 이제 등재 심만 본다.
#   3. 매수 루프를 이터레이터 **이름**으로 고르다 피처 계산 루프까지 끌어왔다.
#      이제 본문에 매수가 있는 루프만 본다.
#   4. `While`을 안 봤다. 후보를 while로 도는 심이 생기면 통째로 감시 밖이었다.
#   5. `diags.append(d)`로 기록하는 심1-1을 "기록 안 함"으로 몰았다 — 정직한
#      심을 거짓 양성으로 잡으면, 사람들이 형식적으로 `_fn`을 끼워 넣어 통과
#      시키고 남은 숫자가 남은 빚을 뜻하지 않게 된다.
#
# **숫자 0보다 중요한 것은 test_every_trading_sim_has_a_detected_buy_loop다.**
# 탐지가 실패하면 구멍 수도 0이 되는데 그건 "깨끗"이 아니라 "안 보고 있다"다.


def _logs_somewhere(node) -> bool:
    """이 구문이 탈락 사유를 남기는가.

    두 가지를 인정한다.
      1. `_fn(funnel, code, '이유')` 처럼 기록 함수를 직접 부르는 것
      2. **기록 장부(funnel)를 인자로 받는 헬퍼 호출** — 심12의
         `_avoid(stock, funnel)` / `_playbook2_entry(stock, funnel)`처럼
         판정과 기록을 함께 하는 관용. 이걸 인정하지 않으면 정직하게 기록하는
         심이 거짓 양성으로 걸리고, 그러면 이 테스트가 신뢰를 잃는다.
    """
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        fn = sub.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, 'attr', '')
        if name in _LOGGERS:
            return True
        passed = list(sub.args) + [k.value for k in sub.keywords]
        if any(isinstance(a, ast.Name) and a.id in _LEDGERS for a in passed):
            return True
        # `diags.append(d)` — 장부에 직접 쌓는 형태
        if (isinstance(fn, ast.Attribute) and fn.attr == 'append'
                and isinstance(fn.value, ast.Name) and fn.value.id in _LEDGERS):
            return True
    return False


def _reads_logged_name(test, names: set) -> bool:
    """조건식이 '기록 호출로 값이 정해진 변수'를 보는가.

    `ok, reason = _playbook2_entry(stock, funnel)` 뒤의 `if not ok: continue`가
    이 형태다 — 판정과 기록을 헬퍼가 함께 하고, 호출부는 결과만 본다.
    """
    return any(isinstance(n, ast.Name) and n.id in names for n in ast.walk(test))


def _unlogged_exits(tree: ast.AST) -> list[int]:
    """후보 루프 안에서 기록 없이 빠져나가는 continue/break의 줄 번호."""
    out = []

    def scan_block(body: list, in_candidate_loop: bool, covered: bool, names: set):
        """한 statement 리스트를 훑는다.

        `continue`/`break`가 기록됐다고 보는 세 가지 관용 — 셋 다 이 레포에
        실재하는 형태다:
          (a) **같은 블록의** 앞선 구문이 기록한다 (`if 조건: _fn(...); continue`)
          (b) 감싸는 `if`의 조건식이 기록한다 (`if _avoid(stock, funnel): continue`)
          (c) 감싸는 `if`의 조건식이, 기록 호출로 값이 정해진 변수를 본다
              (`ok, r = _entry(stock, funnel)` 뒤의 `if not ok: continue`)

        **(a)는 블록 밖으로 새 나가지 않는다.** 처음 만든 버전은 "한 번 기록하면
        그 뒤로 계속 기록된 것"으로 봤는데, 그러면 루프 맨 위의 `_fn` 하나가
        아래 모든 침묵을 가려버린다. 실제로 그 버전은 sim3_risk에 조용한
        `continue`를 새로 넣어도 통과했다 — 검사가 스스로를 무력화한 것이고,
        믿기는 하는데 못 잡는 게이트는 없느니만 못하다.
        """
        local_logged = False
        local_names = set(names)
        for st in body:
            if in_candidate_loop and isinstance(st, (ast.Continue, ast.Break)):
                if not (covered or local_logged):
                    out.append(st.lineno)

            if isinstance(st, ast.If):
                guard = _logs_somewhere(st.test) or _reads_logged_name(st.test, local_names)
                for field in ('body', 'orelse'):
                    # 파이썬은 **블록 스코프가 없다.** `if`/`else` 안에서 기록
                    # 호출의 결과를 받은 이름은 그 뒤에서도 보인다. 심12의
                    #   if regime == 'BULL': ok, r = _playbook1_entry(stock, funnel)
                    #   else:               ok, r = _playbook2_entry(stock, funnel)
                    #   if not ok: continue
                    # 가 정확히 이 형태다. 안에서 정해진 이름을 부모로 올려주지
                    # 않으면 정직하게 기록하는 심이 거짓 양성으로 걸린다.
                    scan_block(getattr(st, field), in_candidate_loop, guard, local_names)
                for sub in ast.walk(st):
                    if isinstance(sub, ast.Assign) and _logs_somewhere(sub):
                        for t in sub.targets:
                            for nm in ast.walk(t):
                                if isinstance(nm, ast.Name):
                                    local_names.add(nm.id)
            elif isinstance(st, (ast.For, ast.While)):
                nested = in_candidate_loop or (isinstance(st, ast.For)
                                               and _is_candidate_loop(st))
                for field in ('body', 'orelse'):
                    scan_block(getattr(st, field), nested, False, local_names)
            else:
                for field in ('body', 'orelse', 'finalbody'):
                    inner = getattr(st, field, None)
                    if isinstance(inner, list):
                        scan_block(inner, in_candidate_loop, covered, local_names)
                for handler in getattr(st, 'handlers', []):
                    scan_block(handler.body, in_candidate_loop, covered, local_names)

            if _logs_somewhere(st):
                local_logged = True
                # 기록 호출의 결과를 받은 변수는 (c)의 근거가 된다
                if isinstance(st, (ast.Assign, ast.AnnAssign)):
                    for t in (st.targets if isinstance(st, ast.Assign) else [st.target]):
                        for nm in ast.walk(t):
                            if isinstance(nm, ast.Name):
                                local_names.add(nm.id)

    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.While)) and _is_candidate_loop(node):
            scan_block(node.body, True, False, set())
    return sorted(set(out))


def _is_candidate_loop(node) -> bool:
    """이 루프가 **매수를 만드는** 루프인가. 청산 루프·피처 루프는 아니다.

    `while`도 본다. 처음에는 `For`만 봐서, 후보를 `while`로 도는 심이 생기면
    통째로 감시 밖이 됐다 — 탐지기의 사각은 조용하다.
    """
    if not isinstance(node, (ast.For, ast.While)):
        return False
    body = '\n'.join(ast.unparse(st) for st in node.body)
    return any(m in body for m in _BUY_MARKERS)


# 매수 루프가 없는 것이 **정상인** 심. 여기 없는데 탐지가 안 되면 실패한다.
NO_BUY_LOOP = {
    'sim0_libero.py': '분석기 — 국면만 판정하고 매매하지 않는다',
    'sim10_orchestrator.py': '오케스트레이터 — 하위 전략에 위임한다(자기 매수 루프가 없다)',
}


def _sim_files() -> list[str]:
    """**매니페스트에 등재된 심만** 본다(국내 + 미국).

    파일명 접두사로 거르던 첫 버전은 두 방향으로 틀렸다. `startswith('sim')`은
    us_sim1/2/3을 통째로 빠뜨렸고(미국 심도 후보를 버린다), 반대로 매니페스트에서
    빠진 죽은 심 파일(sim1_original·sim2_conservative·sim3_aggressive — 마지막
    거래가 2026년 4~5월이다)까지 세어 **갚을 수 없는 빚**을 만들었다.

    돌지 않는 코드에 진단을 붙이는 건 일이 아니라 소음이다. 등재되는 순간
    자동으로 감시 대상이 된다.
    """
    import yaml
    mods = set()
    for name in ('strategy_manifest.yaml', 'us_strategy_manifest.yaml'):
        path = os.path.join(SIM_DIR, '..', name)
        with open(path, encoding='utf-8') as f:
            for entry in yaml.safe_load(f)['simulators']:
                mods.add(entry['module'].rsplit('.', 1)[-1] + '.py')
    return sorted(m for m in mods
                  if os.path.exists(os.path.join(SIM_DIR, m)))


def _measure() -> dict:
    out = {}
    for fn in _sim_files():
        with open(os.path.join(SIM_DIR, fn), encoding='utf-8') as f:
            tree = ast.parse(f.read())
        gaps = _unlogged_exits(tree)
        if gaps:
            out[fn] = gaps
    return out


def test_no_new_silent_rejections():
    """기록 없이 후보를 버리는 분기가 **늘면** 실패한다.

    새 심을 추가하면서 `_fn`을 안 부르거나, 기존 심에 조건을 하나 더 붙이면서
    기록을 빠뜨리면 여기서 걸린다. 2026-09-01의 실전 0건이 정확히 그 형태였다.
    """
    measured = _measure()
    regressions = []
    for fn, lines in sorted(measured.items()):
        allowed = KNOWN_UNLOGGED.get(fn, 0)
        if len(lines) > allowed:
            regressions.append(
                f'  {fn}: 기록 없는 탈락 {len(lines)}개(허용 {allowed}) — 줄 {lines}')
    assert not regressions, (
        '심이 후보를 버리면서 이유를 안 남긴다. 그러면 "조건 미달"과 "배선 고장"이\n'
        '로그에서 같은 모양이 되고, 매번 소급 추론을 해야 한다.\n'
        + '\n'.join(regressions))


def test_ratchet_does_not_go_stale():
    """구멍을 메웠으면 허용치도 같이 줄여야 한다.

    이걸 안 걸면 목록이 낡는다 — 이 레포는 하드코딩된 목록이 조용히 낡아
    생긴 사고가 여러 번 있었다(get_sync_files_list, audit_sim_fields의
    SKIP_SIMS). 목록에 남은 숫자가 남은 빚이므로 정확해야 한다.
    """
    measured = _measure()
    stale = []
    for fn, allowed in sorted(KNOWN_UNLOGGED.items()):
        actual = len(measured.get(fn, []))
        if actual < allowed:
            stale.append(f'  {fn}: 실제 {actual}개인데 허용치가 {allowed} — '
                         f'KNOWN_UNLOGGED를 {actual}로 줄이거나 항목을 지울 것')
    assert not stale, '허용 목록이 실제보다 헐겁다.\n' + '\n'.join(stale)


def test_real_money_sim_records_every_rejection():
    """실전 자금을 쓰는 심에는 예외를 두지 않는다.

    sim3_risk는 실제 주문을 낸다. 이 심이 "왜 안 샀는지"를 못 말하면 그날
    돈이 왜 안 움직였는지 아무도 모른다 — 2026-09-01이 그랬다.
    """
    assert 'sim3_risk.py' not in KNOWN_UNLOGGED, (
        '실전 심은 래칫 예외 대상이 아니다')
    measured = _measure()
    assert 'sim3_risk.py' not in measured, (
        f"sim3_risk가 기록 없이 후보를 버린다 — 줄 {measured.get('sim3_risk.py')}")


def test_the_gate_can_actually_fail():
    """게이트가 스스로를 무력화하지 않는지 확인한다.

    첫 버전은 "한 번 기록하면 그 뒤로 계속 기록된 것"으로 봤다. 그래서 루프 맨
    위의 `_fn` 하나가 아래 모든 침묵을 가렸고, **sim3_risk에 조용한 continue를
    새로 넣어도 통과했다.** 검사를 만든 그 커밋이 검사를 죽인 셈이다.

    이 레포는 같은 형태의 사고를 이미 겪었다 — 2026-08-31에 필드 배선 감사기가
    자기가 잡으라고 만들어진 바로 그 사례를 못 봤다. **진단 도구도 감사 대상이다.**
    """
    src = '''
def run(self, candidates):
    funnel = []
    for stock in candidates:
        if stock['a']:
            _fn(funnel, stock['code'], 'a')
            continue
        if stock['b']:
            continue
        orders.append({'action': 'BUY', 'code': stock['code']})
'''
    gaps = _unlogged_exits(ast.parse(src))
    assert len(gaps) == 1, (
        f'기록 있는 분기 뒤의 조용한 continue를 못 잡는다(찾은 것: {gaps}). '
        f'이 게이트는 통과시키기만 하고 아무것도 막지 못한다.')


def test_the_gate_does_not_cry_wolf():
    """정직하게 기록하는 세 관용은 통과해야 한다.

    거짓 양성이 나면 사람들이 `_fn`을 형식적으로 끼워 넣어 게이트를 통과시키고,
    그러면 남은 숫자가 남은 빚을 뜻하지 않게 된다.
    """
    src = '''
def run(self, candidates):
    funnel = []
    for stock in candidates:
        if _avoid(stock, funnel):
            continue
        ok, reason = _entry(stock, funnel)
        if not ok:
            continue
        if stock['c']:
            _fn(funnel, stock['code'], 'c')
            continue
        orders.append({'action': 'BUY', 'code': stock['code']})
'''
    assert _unlogged_exits(ast.parse(src)) == []


def test_every_trading_sim_has_a_detected_buy_loop():
    """탐지 실패를 **조용하지 않게** 만든다.

    이 게이트는 "본문에 매수가 있는 For/While"로 매수 루프를 찾는다. 그런데
    누군가 `orders.append(_mk_buy(stock))`처럼 헬퍼로 주문을 만들거나,
    후보를 먼저 고르고 루프 밖에서 주문을 조립하도록 바꾸면 **그 심의 매수
    루프가 탐지에서 사라진다.** 그러면 구멍 수가 0으로 떨어지는데, 그건
    "깨끗하다"가 아니라 "안 보고 있다"다 — 게이트가 조용히 무력해진 것이고,
    숫자만 보면 오히려 좋아진 것처럼 보인다.

    그래서 탐지 자체를 단언한다. 탐지기가 못 따라가면 CI가 멈추고, 사람이
    탐지기를 고치거나 여기 예외를 적으면서 **이유를 남기게** 된다.
    """
    missing = []
    for fn in _sim_files():
        if fn in NO_BUY_LOOP:
            continue
        with open(os.path.join(SIM_DIR, fn), encoding='utf-8') as f:
            tree = ast.parse(f.read())
        if not any(_is_candidate_loop(n) for n in ast.walk(tree)):
            missing.append(fn)
    assert not missing, (
        '매수 루프를 못 찾은 심이 있다. 구멍 0은 "깨끗"이 아니라 "미측정"이다. '
        '탐지기(_BUY_MARKERS)를 고치거나, 매매하지 않는 심이면 NO_BUY_LOOP에 '
        '이유와 함께 적을 것: ' + ', '.join(missing))


def test_no_buy_loop_list_is_not_stale():
    """매매를 시작한 심이 예외 목록에 남아 있으면 감시에서 빠진다."""
    stale = []
    for fn in NO_BUY_LOOP:
        path = os.path.join(SIM_DIR, fn)
        if not os.path.exists(path):
            stale.append(f'{fn}(파일 없음)')
            continue
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        if any(_is_candidate_loop(n) for n in ast.walk(tree)):
            stale.append(f'{fn}(이제 매수 루프가 있다)')
    assert not stale, 'NO_BUY_LOOP가 낡았다: ' + ', '.join(stale)
