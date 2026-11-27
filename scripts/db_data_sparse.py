# -*- coding: utf-8 -*-
"""돈 루프가 db-data에서 받을 범위 — 복원과 배포가 **같은 목록**을 쓴다.

db-data `data/`는 2026-11-26에 713MB·2,471파일이 됐다. trading.yml은 2분마다
그 트리를 두 번 실체화한다(복원 `git checkout db-data -- data/` 38초, 배포
`git clone --depth 1` 38초). 3분 예산에 189초가 필요해져 장중 80런 중 **성공
1건**이었고, 매 런이 `Deploy state`에서 잘렸다 — 주문은 나가고 심 상태만 db-data에
도달하지 못하는 모양이다.

예산은 늘릴 수 없다: 이 타임아웃은 원장 락 리스(4분)보다 짧아야 중복 주문이 안 난다.
그래서 받는 양을 줄인다.

**왜 화이트리스트가 아니라 배제 목록인가.** 받을 파일을 열거하면 빠뜨린 파일이
조용히 백지가 된다(2026-08-05 심9-1: 배포 목록과 복원 목록이 갈려 매매기록 8건이
2행만 남았다). 배제 목록은 틀리는 방향이 반대다 — 계열을 빠뜨리면 **느려질 뿐
틀리지 않는다**. 돈 경로에서는 이쪽이 맞는 비대칭이다.

오늘 날짜가 패턴에 드는 이유: `decisions_*`·`money_*`는 과거분이 무겁지만 **오늘
파일은 그 안에서 append**된다. 복원하지 않으면 매 런이 앞부분을 자른다.

쓰는 법(워크플로에서):

    git clone --depth 1 --filter=blob:none --sparse --branch db-data "$URL" repo
    git -C repo sparse-checkout set --no-cone $(python3 scripts/db_data_sparse.py)

실측(2026-11-26, 같은 회선): 713MB/42초 → 146MB/11초.
"""
import fnmatch
import os
import sys

_ROOT = '/data/'

# 루프가 읽지도 쓰지도 않으면서 용량 대부분을 차지하는 계열.
# 각 줄의 숫자는 2026-11-26 db-data 실측이다.
_HEAVY = [
    '!/data/minute_*',       # 165MB — 분봉은 KIS API로 직접 받는다
    '!/data/post_titles_*',  #  84MB — 스크래퍼 산출물, 루프는 안 읽는다
    '!/data/decisions_*',    # 233MB / 652파일 — 오늘 것만 아래에서 되살린다
    '!/data/money_2*',       # 113MB — 월별·과거 일별. 오늘 것만 되살린다
    # 심12·심13은 2026-11-24에 코드에서 제거됐다(PR #158). 남은 진단 파일
    # 75.9MB가 **복원분의 51%**였다 — 더 이상 존재하지 않는 심의 과거 기록을
    # 2분마다 받고 있었다. 매니페스트에도 없다(등록부에서 빠졌으므로).
    '!/data/sim12_diag_*',   #  50MB — 제거된 심
    '!/data/sim13_diag_*',   #  26MB — 제거된 심
]


# 배포 clone이 db-data에서 **읽는** 파일. 나머지는 전부 로컬 사본으로 덮으므로
# 받을 이유가 없다 — 받는 건 `git add`가 "범위 안"이라고 인정해주게 하려는 것뿐이다.
_DEPLOY_READS = (
    'alert_dedup.json',      # merge_alert_dedup.py가 원격 기록과 병합한다
    'sim_reset_epoch.json',  # reset_epoch_guard.py가 원격 마커를 읽는다
)


def deploy_patterns(names) -> list[str]:
    """배포 clone이 받을 범위 — 배포 목록(매니페스트)에서 **파생**한다.

    복원과 배포는 하는 일이 다르다. 복원은 **읽으려고** 받으니 무엇이 필요한지
    미리 다 알 수 없다(그래서 위 배제 목록이다). 배포는 받은 트리를 로컬 사본으로
    **덮으려고** 받고, 덮을 목록은 매니페스트에 이미 적혀 있다.

    그래서 배포 범위는 열거할 수 있고, 열거하면 **"배포 목록 ⊄ 배포 범위"가
    구성적으로 불가능**해진다. 그게 2026-08-05 심9-1 고장의 유형이다(배포 목록과
    복원 목록이 갈려 매매기록 8건이 2행만 남았다). 가드가 잡는 것보다 애초에
    생길 수 없는 쪽이 낫다.

    절감은 부수효과다(2026-11-26 실측: 1,635파일/72MB·sparse set 6.36초 →
    58파일/731KB·0.63초).

    ⚠ 이름에 글롭 메타문자(`*?[`)가 들어가면 패턴이 그 파일을 못 집는다. 그
    경우는 배포 스텝의 `ls-files -v` 가드가 `S`로 잡아 멈춘다 — 조용하지 않다.
    (2026-11-27 등록부·국면·순위 42개 이름 전수 확인: 전부 평범한 basename)
    """
    out = [_ROOT + n.strip() for n in [*_DEPLOY_READS, *names] if n.strip()]
    return list(dict.fromkeys(out))


def patterns(today_ymd: str) -> list[str]:
    """sparse-checkout 패턴(git 비-cone 문법). `today_ymd`는 'YYYYMMDD'.

    git 비-cone 규칙은 **마지막 일치가 이긴다**. 그래서 순서가 의미를 가진다 —
    여는 패턴(`/data/*`)이 맨 앞, 배제가 가운데, 오늘 되살리기가 맨 뒤다.
    """
    if not (len(today_ymd) == 8 and today_ymd.isdigit()):
        raise ValueError(f'날짜는 YYYYMMDD여야 한다: {today_ymd!r}')
    dashed = f'{today_ymd[:4]}-{today_ymd[4:6]}-{today_ymd[6:8]}'
    return [
        '/data/*',
        *_HEAVY,
        f'/data/decisions_{today_ymd}_*',
        f'/data/money_{dashed}.csv',
    ]


def keeps(name: str, today_ymd: str) -> bool:
    """`data/<name>`이 범위에 남는가. 마지막 일치가 이기는 규칙으로 판정한다.

    tests/test_db_data_sparse.py가 이걸로 "배포 목록 ⊆ 복원 범위"를 지킨다.
    git에게 물어보려면 clone이 필요해서 테스트가 네트워크에 매인다.

    ⚠ **git과 동일한 구현이 아니라 근사다.** `fnmatch`의 `*`는 `/`를 넘지만 git
    비-cone(wildmatch + WM_PATHNAME)의 `*`는 못 넘는다. 2026-11-26 db-data의
    2,471경로 전수 대조에서는 결과가 완전히 일치했다(`data/`가 거의 평면이고
    `data/reports/` 12파일은 양쪽 모두 포함). `data/` 아래 중첩 디렉터리가 늘면
    두 규칙이 갈릴 수 있으니, 그때는 이 함수를 wildmatch 쪽으로 맞춰야 한다.
    """
    verdict = False
    for pat in patterns(today_ymd):
        negated = pat.startswith('!')
        body = pat[1:] if negated else pat
        if fnmatch.fnmatchcase(name, body[len(_ROOT):]):
            verdict = not negated
    return verdict


def main() -> int:
    # 배포 범위는 날짜를 안 쓴다 — 매니페스트에 적힌 이름이 이미 확정값이다.
    # 그래서 시계를 부를 이유가 없고, 복원 범위와 날짜가 갈릴 여지도 없다.
    if len(sys.argv) > 2 and sys.argv[1] == '--deploy':
        with open(sys.argv[2], encoding='utf-8') as f:
            print('\n'.join(deploy_patterns(f.read().split('\n'))))
        return 0
    # KST를 직접 만들지 않는다 — 단일 시계(src.core.clock)만 쓴다. 날짜가 하루
    # 밀리면 오늘 append 파일을 복원하지 못해 조용히 잘린다.
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from src.core import clock
    today = clock.now().strftime('%Y%m%d')
    if len(sys.argv) > 1:
        today = sys.argv[1]
    print('\n'.join(patterns(today)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
