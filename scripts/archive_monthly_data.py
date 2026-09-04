# -*- coding: utf-8 -*-
"""월간 아카이브 — 지난달 데이터를 메일로 내보내고, 보낸 것만 지운다.

왜 필요한가 (2026-09-04 실측):

    레포 전체        1.0 GB    public, GitHub 권장 상한 1GB
    db-data HEAD    138.6 MB   실제로 쓰는 데이터
    db-data 커밋     6737개    절반이 최근 15일치

계속 쌓으면 상한을 넘는다. 서버에는 **2개월치만** 두고 지난달치는 메일로 내보낸다.

## 두 가지 불변식

**보낸 것만 지운다(fail-closed).** KIS 분봉·체결은 당일치만 조회되므로 지운 달은
복구할 방법이 없다. 메일이 안 나갔는데 지우면 그 달이 영영 사라진다. 그래서
`data/archive_log.json`에 발송 기록이 있는 달만 삭제 대상이 된다.

**크기로 묶어 나눠 보낸다.** 2026-08 한 달치가 96.3MB인데(minute 33.8 +
post_titles 24.8 + money 24.4 + diag 7.4 …) Gmail 첨부 한도는 25MB이고 base64가
33%를 더한다. 한 통에 못 넣는다.

그렇다고 파일당 한 통도 안 된다 — 2026-06은 파일이 **180개**다(작은 일별 파일들).
그래서 gzip한 크기 기준으로 묶어 통당 한도 아래로 맞춘다. 실측 기준 8월은 2~3통,
6월은 1통이다.

## 보관 정책

    9월 1일 실행 → 8월치 발송 → 7월 이전 중 **발송 기록이 있는 달**만 삭제

이번 달(9월)과 지난달(8월)은 남는다. 8월은 보냈어도 한 달 더 두는 유예다 —
메일이 실제로 도착했는지 사람이 확인할 시간이다.

## 상태 파일은 건드리지 않는다

파일명에 YYYY-MM이 없는 것은 대상이 아니다(`rank_state.json`,
`sim_*_state.json`, `sim11_watchlist.json`, `kospi_top100_close.csv` …).
그것들을 지우면 심이 백지 상태에서 시작해 보유를 잊는다.
"""
import argparse
import datetime as dt
import glob
import gzip
import json
import os
import re
import smtplib
import sys
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

RECIPIENT = 'hoon.namkoong@gmail.com'
ARCHIVE_LOG = 'archive_log.json'
KEEP_MONTHS = 2          # 이번 달 + 지난달
GMAIL_ATTACH_LIMIT = 25 * 1024 * 1024
# base64가 33%를 더하므로 실제 여유는 한도의 3/4다. 거기서 더 낮춰 잡는다 —
# 헤더·본문·MIME 경계도 같은 봉투에 들어간다.
BATCH_CAP = 15 * 1024 * 1024

# 파일명 안의 YYYY-MM 또는 YYYYMM. 실제로 네 형식이 섞여 있다:
#   money_2026-09.csv          월별(일별 분할 이전)
#   money_2026-09-04.csv       일별(2026-09-04 이후)
#   sim1_diag_2026-08_v1.csv   컬럼 변경으로 갈라진 파일
#   post_titles_2026072.csv    구분자 없는 레거시(끝에 군더더기 숫자가 붙는다)
#
# **첫 번째** 날짜 토큰을 쓴다. 마지막에서 찾으면 `trending_integrated_20260209_225705.csv`
# 의 시각(225705)을 2257-05로 읽는다 — 실측에서 실제로 나왔다.
_MONTH_RE = re.compile(r'_(\d{4})-?(\d{2})')


def month_of(filename: str) -> str | None:
    """파일명에서 'YYYY-MM'. 달을 못 읽으면 None — 아카이브 대상이 아니다.

    월별(`money_2026-09.csv`)·일별(`money_2026-09-04.csv`)·컬럼분기(`..._v1.csv`)·
    구분자 없는 레거시(`post_titles_2026072.csv`)가 모두 섞여 있다.
    """
    for m in _MONTH_RE.finditer(os.path.basename(filename)):
        year, month = m.group(1), m.group(2)
        if '2000' <= year <= '2099' and '01' <= month <= '12':
            return f'{year}-{month}'
    return None


def group_by_month(paths: list) -> dict:
    """{'YYYY-MM': [경로…]}. 달을 못 읽는 파일은 빠진다(상태 파일 보호)."""
    out: dict = {}
    for p in paths:
        m = month_of(p)
        if m:
            out.setdefault(m, []).append(p)
    for v in out.values():
        v.sort()
    return out


def month_to_archive(today: dt.date) -> str:
    """지난달. 이번 달은 아직 안 끝났으니 보내지 않는다."""
    first = today.replace(day=1)
    prev = first - dt.timedelta(days=1)
    return prev.strftime('%Y-%m')


def months_to_delete(today: dt.date, archive_log: dict, months: list) -> list:
    """지울 달 = 보관 창 밖 + **발송 기록 있음**.

    기록이 없으면 남긴다. 조용히 지우면 복구가 없다 — 이 함수가 그 방어다.
    """
    keep = set()
    cur = today.replace(day=1)
    for _ in range(KEEP_MONTHS):
        keep.add(cur.strftime('%Y-%m'))
        cur = (cur - dt.timedelta(days=1)).replace(day=1)
    return sorted(m for m in months
                  if m not in keep and (archive_log.get(m) or {}).get('sent_at'))


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def _load_log(data_dir: str, local_log: str) -> dict:
    """db-data의 기록 + **러너 로컬 기록**을 합친다.

    배포 push가 충돌하면 워크플로가 다시 clone해서 재시도한다. 그때 원격 기록에는
    이번 발송이 아직 없으므로, 로컬 사본이 없으면 **메일을 다시 보낸다.**
    로컬 사본이 그 재발송을 막는다.
    """
    merged = dict(_read_json(os.path.join(data_dir, ARCHIVE_LOG)))
    merged.update(_read_json(local_log))
    return merged


def _save_log(data_dir: str, local_log: str, log: dict) -> None:
    blob = json.dumps(log, ensure_ascii=False, indent=2, sort_keys=True)
    for path in (os.path.join(data_dir, ARCHIVE_LOG), local_log):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(blob)


def plan_batches(sized: list, cap: int = BATCH_CAP) -> list:
    """[(이름, 압축크기)] → 통당 cap 아래로 묶은 배치 목록.

    파일당 한 통이면 2026-06처럼 작은 파일 180개인 달에 180통이 나간다.
    한 통에 다 넣으면 2026-08(96.3MB)이 첨부 한도를 넘는다. 그 사이다.

    혼자서도 cap을 넘는 파일은 **자기 혼자 한 배치**가 된다 — 쪼개지 않는다.
    쪼갠 조각은 사람이 다시 붙여야 하고, 그 절차가 없으면 복구가 안 된다.
    """
    batches, cur, cur_size = [], [], 0
    for name, size in sized:
        if cur and cur_size + size > cap:
            batches.append(cur)
            cur, cur_size = [], 0
        cur.append(name)
        cur_size += size
    if cur:
        batches.append(cur)
    return batches


def _send_batch(blobs: dict, names: list, month: str, part: int, total: int,
                log=print) -> bool:
    """배치 하나를 메일 한 통으로. 성공하면 True."""
    user = os.environ.get('EMAIL_USER')
    pw = os.environ.get('EMAIL_PASS')
    if not user or not pw:
        log('[Archive] EMAIL_USER/EMAIL_PASS 없음 — 발송 불가')
        return False

    size = sum(len(blobs[n]) for n in names)
    if size * 4 // 3 > GMAIL_ATTACH_LIMIT:
        # 조용히 넘기지 않는다 — 이 달은 삭제 대상에서 빠지고 사람이 봐야 한다.
        log(f'[Archive] {month} part{part}: 압축 후에도 첨부 한도 초과 '
            f'({size/1024/1024:.1f}MB, 파일 {len(names)}개) — 발송하지 않는다')
        return False

    msg = MIMEMultipart()
    msg['From'] = user
    msg['To'] = RECIPIENT
    msg['Subject'] = f'[StockBot] {month} 데이터 아카이브 ({part}/{total})'
    listing = '\n'.join(f'  {os.path.basename(n)}  '
                        f'{len(blobs[n]) / 1024 / 1024:.2f}MB' for n in names)
    body = (
        f'{month} 데이터 아카이브 {part}/{total}통입니다.\n\n'
        f'파일 {len(names)}개 / 압축 {size / 1024 / 1024:.1f}MB\n\n'
        f'{listing}\n\n'
        f'서버에는 최근 {KEEP_MONTHS}개월치만 남습니다. 이 메일이 그 달의 원본입니다.\n'
    )
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    for n in names:
        base = os.path.basename(n) + '.gz'
        part_mime = MIMEApplication(blobs[n], Name=base)
        part_mime['Content-Disposition'] = f'attachment; filename="{base}"'
        msg.attach(part_mime)

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=120)
        server.starttls()
        server.login(user, pw)
        server.send_message(msg)
        server.quit()
        log(f'[Archive] 발송 {month} ({part}/{total}) '
            f'{len(names)}개 / {size/1024/1024:.1f}MB')
        return True
    except Exception as e:
        log(f'[Archive] 발송 실패 {month} ({part}/{total}): {e}')
        return False


def send_month(files: list, month: str, dry_run: bool = False, log=print) -> bool:
    """그 달 전체를 보낸다. **한 통이라도 실패하면 False** — 부분 발송은 삭제 허가가 아니다."""
    blobs = {}
    for p in files:
        with open(p, 'rb') as f:
            blobs[p] = gzip.compress(f.read(), 6)
    batches = plan_batches([(p, len(blobs[p])) for p in files])
    log(f'[Archive] {month}: 파일 {len(files)}개 → 메일 {len(batches)}통')
    if dry_run:
        return True
    return all(_send_batch(blobs, names, month, i + 1, len(batches), log)
               for i, names in enumerate(batches))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', default='data')
    ap.add_argument('--today', default='', help='YYYY-MM-DD (테스트용)')
    ap.add_argument('--local-log', default='.archive_sent.json',
                    help='러너 로컬 발송 기록 — 재시도 시 재발송을 막는다')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)

    today = (dt.date.fromisoformat(a.today) if a.today
             else (dt.datetime.utcnow() + dt.timedelta(hours=9)).date())
    groups = group_by_month(sorted(glob.glob(os.path.join(a.data_dir, '*'))))
    log = _load_log(a.data_dir, a.local_log)

    target = month_to_archive(today)
    files = groups.get(target, [])
    if not files:
        print(f'[Archive] {target} 대상 파일 없음 — 발송 생략')
    elif log.get(target, {}).get('sent_at'):
        print(f'[Archive] {target} 이미 발송됨({log[target]["sent_at"]}) — 생략')
    else:
        if send_month(files, target, a.dry_run):
            log[target] = {
                'sent_at': dt.datetime.now().astimezone().isoformat(timespec='seconds'),
                'files': len(files),
                'bytes': sum(os.path.getsize(f) for f in files),
            }
            if not a.dry_run:
                _save_log(a.data_dir, a.local_log, log)
            print(f'[Archive] {target} {len(files)}개 발송 완료')
        else:
            # 한 통이라도 실패하면 기록하지 않는다 — 기록이 곧 삭제 허가다.
            print(f'[Archive] {target} 발송 실패 — 기록하지 않는다(다음 실행에서 재시도)')

    deletable = months_to_delete(today, log, list(groups))
    removed = 0
    for m in deletable:
        for p in groups[m]:
            print(f'[Archive] 삭제 {os.path.basename(p)} ({m})')
            if not a.dry_run:
                os.remove(p)
            removed += 1
    print(f'[Archive] 보관 {KEEP_MONTHS}개월 — {len(deletable)}개 달 / {removed}개 파일 삭제')
    return 0


if __name__ == '__main__':
    sys.exit(main())
