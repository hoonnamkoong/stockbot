"""상투(열망) 표현 사전 — 게시글을 LLM에 보내기 전 로컬로 거른다.

배치 프롬프트는 이미 "감정적 단어 및 선동 문구는 무조건 배제하고 0점 처리"라고
지시한다. 즉 열망 표현뿐인 글은 Gemini가 받아서 버린다. 버릴 걸 보내느라 토큰을
쓰고 있었다 — 사전이 같은 판정을 로컬에서 공짜로 한다.

사전 근거: 2026-07-27 db-data 원문 875건(37종목) 검증. 통합 lift 2.1~2.9로
라벨 임계 −3%~−20% 전 구간에서 안정적. 항복군은 상투가 아니라 바닥권 신호라
역신호(lift 0.30~0.60)지만, '보낼 가치 없는 잡담'이라는 점은 열망군과 같다.

⛔ 정치 잡담군은 사전에서 뺐다. lift 0.12~0.43이 나왔지만 정치글 79건 중 75건이
삼성전자·SK하이닉스라 국면 신호가 아니라 종목 고정효과였다.

⚠️ 위 lift는 종목 고정효과를 통제하지 않은 값이고 표본이 3거래일이다. 아카이브가
쌓이면 같은 종목 내 시점 비교로 재검증할 것.
"""

import re

# 상투(열망) 7개군 — 값은 검증 당시 lift
HYPE_GROUPS = {
    'target_price': r'\d+\s*[만천]\s*원.{0,12}(가자|가즈아|간다|까지|돌파|가나)',
    'all_in':       r'풀매수|몰빵|풀미수|미수|영끌|올인|묻따',
    'euphoria':     r'대박|소오름|꿈이냐|날라가|쩐다|축하|가즈아',
    'limit_up':     r'쩜상|점상|상한가|따상|상\s*간다|낼\s*상',
    'manipulation': r'안티|찬티|세력|작전|설거지|개미털',
    'gap_up':       r'갭상승|갭상|시초가|양봉|이빠이',
    'profit_take':  r'매도했|하차|익절|정리했|팔았',
}

# 항복·손실군 — 부호는 반대(바닥권 신호)지만 팩트가 없기는 마찬가지
CAPITULATION = r'물렸|존버|손절|본전|반토막|털렸|호구'

# 배치 프롬프트가 "반드시 우대"하라고 지시하는 키워드.
# 이 중 하나라도 있으면 잡담이 아니라 근거 있는 글일 수 있으므로 보낸다.
FACT_HINTS = r'분석|추세|전망|공시|뉴스|따르면|의하면'

_HYPE_RE = re.compile('|'.join(f'(?:{p})' for p in HYPE_GROUPS.values()))
_CAPIT_RE = re.compile(CAPITULATION)
_FACT_RE = re.compile(FACT_HINTS)


def match_groups(text: str) -> list:
    """텍스트가 걸린 열망군 이름 목록. Sim1 열망축이 쓸 자리."""
    t = str(text or '')
    return [name for name, pat in HYPE_GROUPS.items() if re.search(pat, t)]


def is_noise(text: str) -> bool:
    """LLM에 보낼 가치가 없는 글인가.

    열망·항복 표현이 있고 팩트 힌트가 하나도 없을 때만 True다. 팩트 힌트가
    있으면 보낸다 — 사전이 프롬프트보다 앞서 판단하지 않게 하려는 것이다.
    """
    t = str(text or '')
    if _FACT_RE.search(t):
        return False
    return bool(_HYPE_RE.search(t) or _CAPIT_RE.search(t))


def hype_score(titles) -> float:
    """열망 히트율 − 항복 히트율. -1.0 ~ +1.0.

    Sim1 열망축이 쓴다. 항복군을 빼는 이유: 상투가 아니라 바닥권 신호라
    부호가 반대다(lift 0.30~0.60, 임계 전 구간에서 재현).
    """
    ts = [str(t or '') for t in (titles or []) if str(t or '').strip()]
    if not ts:
        return 0.0
    hype = sum(1 for t in ts if _HYPE_RE.search(t))
    capit = sum(1 for t in ts if _CAPIT_RE.search(t))
    return (hype - capit) / len(ts)


def filter_posts(posts: list) -> tuple:
    """(보낼 글, 걸러낸 수). 제목만 본다 — 본문은 100% 수집 실패 중이다."""
    kept = [p for p in (posts or []) if not is_noise(p.get('title', ''))]
    return kept, len(posts or []) - len(kept)
