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

# 후보 루프로 보는 이터레이터 이름 조각. 청산 루프(portfolio_codes)는 대상이
# 아니다 — 여기서 세는 것은 "왜 이 후보를 안 샀는가"뿐이다.
_CANDIDATE_HINTS = ('candidates', 'stocks', 'universe', 'picks', 'ranked', 'rows')

# ── 래칫 ────────────────────────────────────────────────────────────
# 파일명 → 기록 없이 후보를 탈락시키는 분기 수(2026-09-01 실측).
# **줄이는 방향으로만 고친다.** 0이 되면 항목째로 지운다.
KNOWN_UNLOGGED = {
    'sim11_minervini.py': 4,
    'sim12_regime_dual.py': 1,
    'sim1_original.py': 2,
    'sim1_psych.py': 4,
    'sim2_conservative.py': 2,
    'sim2_spillover.py': 4,
    'sim3_aggressive.py': 2,
    'sim4_bull_momentum.py': 6,
    'sim5_sideways_swing.py': 4,
    'sim8_accumulation.py': 12,
    'sim9_1_donchian.py': 6,
    'us_sim1_minervini.py': 4,
    'us_sim2_donchian.py': 5,
    'us_sim3_liquidity.py': 1,
}
# 2026-09-01: 실측 57개/14심.
# 갚은 것 — sim3_risk(실전, 구멍 0)와, 다섯 심에 같은 모양으로 복제돼 있던
# `if held >= MAX_HOLDINGS: break`(sim4-1·sim6·sim9·sim12·sim13). 같은 결함이
# 다섯 파일에 있었다는 사실 자체가, 이 규칙이 리뷰가 아니라 CI에 있어야 하는
# 이유다.
#
# 숫자가 처음 센 것(43개/10심)보다 늘어난 것은 심이 나빠져서가 아니라
# **검사가 정확해졌기 때문**이다. 첫 버전은 (a)규칙이 블록 밖으로 새어
# 루프 맨 위의 `_fn` 하나가 아래 침묵을 전부 가렸고, 파일명 접두사 필터 탓에
# 미국 심 3개를 통째로 안 봤다. 리뷰에서 잡혔다.


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
        if any(isinstance(a, ast.Name) and a.id == 'funnel' for a in passed):
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
                    scan_block(getattr(st, field), in_candidate_loop, guard, local_names)
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
    it = ast.unparse(node.iter) if isinstance(node, ast.For) else ''
    return any(h in it for h in _CANDIDATE_HINTS)


def _sim_files() -> list[str]:
    # `startswith('sim')`으로 거르면 us_sim1/2/3이 통째로 빠진다 — 미국 심도
    # 후보를 버리고, 버린 이유가 없으면 똑같이 답을 못 한다.
    skip = {'__init__.py', 'base_simulator.py', 'us_base_simulator.py',
            'kr_calendar.py', 'us_calendar.py'}
    return sorted(f for f in os.listdir(SIM_DIR)
                  if f.endswith('.py') and f not in skip)


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
'''
    assert _unlogged_exits(ast.parse(src)) == []
