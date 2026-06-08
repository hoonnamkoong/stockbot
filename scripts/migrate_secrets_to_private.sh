#!/usr/bin/env bash
# 일회성: public db-data의 민감/실거래 데이터를 비공개 레포(stockbot-secret)로 이전하고
# public db-data 브랜치에서 삭제한다. (git-bash에서 실행 권장)
#
# 사용법:  GH_PAT=ghp_xxxx bash scripts/migrate_secrets_to_private.sh
#
# 주의: 원격 public(db-data)·비공개(main) 브랜치에 push한다. 되돌리기 어렵다.
#       git "히스토리"의 과거 노출은 이 스크립트로 제거되지 않는다(현재 파일만 삭제).
set -euo pipefail
: "${GH_PAT:?GH_PAT 환경변수를 설정하세요 (예: GH_PAT=ghp_... bash scripts/migrate_secrets_to_private.sh)}"

OWNER=hoonnamkoong
PUB=stockbot
SEC=stockbot-secret

# 비공개로 이전(누적 보존)할 파일
MIGRATE=(order_history.json trade_history_real.csv history.json)
# public db-data에서 삭제할 민감 파일
PURGE=(kis_token_cache.json token.json kis_token.json token_result.json \
       portfolio.json order_history.json order_status.json \
       trade_history_real.csv history.json scraper_debug.log)

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "[1/4] db-data, stockbot-secret clone..."
git clone --branch db-data --depth 1 "https://x-access-token:${GH_PAT}@github.com/${OWNER}/${PUB}.git" "$tmp/pub"
if ! git clone --depth 1 "https://x-access-token:${GH_PAT}@github.com/${OWNER}/${SEC}.git" "$tmp/sec" 2>/dev/null; then
  mkdir -p "$tmp/sec"; ( cd "$tmp/sec"; git init -q; git checkout -q -b main; \
    git remote add origin "https://x-access-token:${GH_PAT}@github.com/${OWNER}/${SEC}.git" )
fi

echo "[2/4] 누적 기록 비공개 레포로 이전..."
for f in "${MIGRATE[@]}"; do
  if [ -f "$tmp/pub/data/$f" ]; then cp "$tmp/pub/data/$f" "$tmp/sec/$f"; echo "  + $f"; fi
done
( cd "$tmp/sec"
  git add -A
  if ! git diff --cached --quiet; then
    git -c user.email=bot@local -c user.name=migrate commit -q -m "chore: migrate trade records from public db-data"
    git push -q origin main
    echo "  -> stockbot-secret push 완료"
  else echo "  -> 이전할 변경 없음"; fi )

echo "[3/4] public db-data에서 민감 파일 삭제..."
( cd "$tmp/pub"
  for f in "${PURGE[@]}"; do git rm -q -f --ignore-unmatch "data/$f" || true; done
  git rm -q -rf --ignore-unmatch data/stock_data_temp_backup || true
  if ! git diff --cached --quiet; then
    git -c user.email=bot@local -c user.name=cleanup commit -q -m "security: purge credentials/account data from public db-data"
    git push -q origin db-data
    echo "  -> db-data push 완료"
  else echo "  -> 삭제할 파일 없음"; fi )

echo "[4/4] 완료. 검증: stockbot-secret에 트레이드 기록 존재 / db-data에서 민감파일 404 확인."
