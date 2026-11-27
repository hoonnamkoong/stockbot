#!/usr/bin/env bash
# db-data에서 **이름이 정해진 파일만** 받는다.
#
# 네 워크플로가 db-data에서 파일 한두 개를 읽는다. 그 자리들이 쓰던 방식은
#
#     git fetch --depth 1 origin db-data
#     git checkout FETCH_HEAD -- data/<파일>
#
# 인데, 앞줄이 **그 커밋의 블롭 전부**를 받는다. 2026-11-27 실측으로 그게
# 42초 / 130MB다(작업 트리로 펴면 713MB). 달력 1,982바이트를 읽으려고 그걸 낸다.
#
#   · heartbeat_watch.yml  — 예산 5분. 그 중 42초를 여기 쓴다. 이 워크플로가
#     잘리면 **고장을 알려줄 사람 경로가 사라진다**(2026-11-26 MTTR 6.5시간).
#   · dart_fundamentals.yml — 2026-11-25 첫 채움 런이 119분에 타임아웃으로
#     잘렸다. 다음 보충 런은 11-29 05:00 KST 하나뿐이고 그 뒤는 2027-03-16이다.
#   · token_refresh.yml · us_eod_watchlist.yml — 같은 42초.
#
# 왜 `git fetch --filter=blob:none`을 그 자리에 붙이지 않는가: 붙여도 fetch는
# 1초로 줄지만 **뒤의 `git checkout`이 깨진다**.
#
#     error: unable to read sha1 file of data/market_calendar.json (d29978f3…)
#
# actions/checkout이 만든 저장소는 부분 클론이 아니라서 빠진 블롭을 나중에
# 받아올 promisor가 없다. `extensions.partialClone`·`remote.origin.promisor`를
# 손으로 넣어도 같은 오류가 났다(2026-11-27 둘 다 실측). 그래서 **별도
# 디렉터리에 부분 클론을 따로 만든다** — trading.yml이 쓰는 것과 같은 방식이고,
# 받은 범위가 호출한 경로뿐이라 **2초 / 426KB**다.
#
# 쓰는 법:
#
#     scripts/fetch_db_data_files.sh data/market_calendar.json [data/other.json ...]
#
# 경로는 레포 루트 기준이고, 같은 상대 경로로 작업 트리에 놓인다.
# 종료코드: 0=클론 성공(요청 파일이 하나도 없어도 0이다 — 첫 실행이 그 모양이다)
#           1=인자 없음 2=클론 실패
#
# **없는 파일과 못 받은 파일을 구분해서 찍는다.** 호출부는 지금까지
# `|| echo "없음"` 하나로 둘을 같이 삼켰고, 그러면 "첫 실행이라 없다"와
# "받기에 실패했다"가 로그에서 같은 모양이 된다.
set -uo pipefail

if [ "$#" -eq 0 ]; then
  echo "[db-data] 받을 파일을 하나 이상 적어야 한다" >&2
  exit 1
fi

repo="${GITHUB_REPOSITORY:-hoonnamkoong/stockbot}"
if [ -n "${GITHUB_TOKEN:-}" ]; then
  url="https://x-access-token:${GITHUB_TOKEN}@github.com/${repo}.git"
else
  # public 레포라 토큰 없이도 읽힌다. 로컬에서 손으로 돌릴 때의 경로다.
  url="https://github.com/${repo}.git"
fi

# 레포 루트가 아니라 RUNNER_TEMP에 둔다 — 작업 트리에 섞이면 언젠가
# `git add`에 걸려 db-data로 올라간다(trading.yml이 같은 이유로 그렇게 한다).
tmp="${RUNNER_TEMP:-.}/_db_named_$$"
trap 'rm -rf "$tmp"' EXIT
rm -rf "$tmp"

if ! git clone --depth 1 --filter=blob:none --sparse --branch db-data \
     "$url" "$tmp" 2>&1 | sed 's/x-access-token:[^@]*@/x-access-token:***@/'; then
  echo "[db-data] 부분 클론 실패 — 아무 파일도 받지 못했다"
  exit 2
fi

# 비-cone 패턴은 선두 `/`가 저장소 루트를 뜻한다. 요청 경로를 그대로 쓴다.
pats=()
for p in "$@"; do pats+=("/$p"); done
if ! git -C "$tmp" sparse-checkout set --no-cone "${pats[@]}"; then
  echo "[db-data] sparse 범위 설정 실패 — 아무 파일도 받지 못했다"
  exit 2
fi

got=0 absent=0
for p in "$@"; do
  if [ -f "$tmp/$p" ]; then
    mkdir -p "$(dirname "$p")"
    cp "$tmp/$p" "$p"
    got=$((got + 1))
    echo "[db-data] 받음: $p ($(wc -c < "$p") 바이트)"
  else
    absent=$((absent + 1))
    echo "[db-data] db-data에 없음: $p"
  fi
done
echo "[db-data] 받음 ${got}개 · 없음 ${absent}개"
exit 0
