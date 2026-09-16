/**
 * 태스커 트리거가 어느 GitHub 워크플로로 가는지 정한다.
 *
 * 태스커는 GitHub을 직접 부르지 않는다. `/api/cron`을 부르고, 그 라우트가
 * workflow_dispatch를 보낸다 — 그래서 "태스커 설정"을 아무리 뒤져도 대상
 * 워크플로가 안 나오고, 이 파일이 유일한 진실이다.
 *
 * 순수 함수로 뺀 이유: 이 값이 라우트 안에 한 줄로 박혀 있었고, 라우트는
 * node --test로 import할 수 없어 아무도 검증하지 않았다. 2026-08-07에 정확히
 * 그 모양의 사고가 났다 — 매매를 새 워크플로에 위임했는데 트리거가 그쪽으로
 * 가지 않아, 실행 이력 0건인 워크플로를 아무도 눈치채지 못한 채 하루가 갔다.
 */

/** 장 시작 전 KIS 토큰 선발급. GitHub cron 미발화를 우회해 09:00 첫 런이
 *  항상 유효 토큰을 만나게 한다. */
export const TOKEN_REFRESH_HOUR_KST = 7;

/**
 * 토큰 선발급으로 분기하는 창(분). 태스커가 2분 격자로 부르므로 [0, 2)에는
 * 정확히 한 틱만 들어온다.
 *
 * 시(hour)만 보던 시절, 07시대 30틱이 전부 token_refresh.yml로 갔다 —
 * token_refresh.yml은 FORCE_TOKEN_REFRESH=true라 매번 **진짜 새 토큰**을
 * 발급한다. 2026-09-02 07:00~07:50에 26회 발급됐고, 그 한 시간 동안
 * 매매 트리거는 한 번도 나가지 않았다.
 *
 * 태스커 격자가 2분보다 성기어지면 이 창에 아무 틱도 안 들어올 수 있다.
 * 그래도 봇은 멈추지 않는다 — trading.yml이 token_manager를 force 없이
 * 돌려, 토큰이 실제로 만료됐으면 그때 발급한다.
 */
export const TOKEN_REFRESH_WINDOW_MIN = 2;

/**
 * 이 시각에 dispatch할 워크플로 파일명.
 *
 * 기본이 trading.yml인 것이 핵심이다(2026-08-08). 매매가 최상위 경로이고,
 * 스크래핑은 trading.yml이 10분 격자에서 scraper.yml을 깨워 처리한다.
 * 여기를 scraper.yml로 되돌리면 실전 매매가 통째로 멈춘다 — 스크래퍼는
 * 자기를 부르지 않기 때문이다.
 */
export function pickWorkflow(hourKst: number, minuteKst: number): string {
  if (hourKst === TOKEN_REFRESH_HOUR_KST && minuteKst < TOKEN_REFRESH_WINDOW_MIN) {
    return 'token_refresh.yml';
  }
  return 'trading.yml';
}

/**
 * 장중 생존 감시(heartbeat_watch.yml). "지금 루프가 멎어 있다"를 분 단위로 보는
 * 유일한 감시자다.
 *
 * 원래 네이티브 cron(`0 0-6 * * 1-5`) 전용이었다 — 감시자를 감시 대상과 같은
 * 발화 경로에 두지 않으려는 의도였고 그 의도는 지금도 맞다. 문제는 발화가
 * 실제로 오지 않았다는 것이다: 2026-09-08~09-15 6거래일 실측 발화는 세션당
 * 7회 기대 대비 **하루 정확히 2회**(12/42 = 28.6%)였고, 뒤엣것은 전부 장 마감
 * 뒤라 판정이 off_session이다 — **장중 유효 커버리지 6/42 = 14.3%.**
 * 09:00~11:30과 12:00~15:30이 무감시였다. 이 레포에서 시간당 1회도 고빈도이고,
 * 고빈도 cron은 us_trading에서 이미 통째로 드롭됐다(08-27 이후 0회).
 *
 * 그래서 태스커 경로를 **더한다**(cron은 백업으로 남긴다 — 폰과 무관한 발화는
 * 그것뿐이다). 한계는 남는다: 태스커가 죽으면 감시 대상과 감시자가 같이
 * 조용해진다. 그 느린 그물은 data_audit_backup.yml(13:00 KST cron)이다.
 */
export const HEARTBEAT_WORKFLOW = 'heartbeat_watch.yml';

/**
 * 감시를 깨우는 창(KST). 상한은 판정 세션의 상한(clock.KR_JUDGMENT_CLOSE,
 * 15:50)이다 — 그 밖에서 깨우면 check_heartbeat.py가 off_session을 찍고
 * 아무것도 보지 않는다(초록 런이 쌓이는데 감시는 0이다).
 *
 * 하한이 09:00이 아니라 09:15인 이유: 태스커는 08:00에 잠들고 09:00에 깬다.
 * 09:00 정각의 마지막 완주는 07:5x이라 임계(heartbeat.MAX_AGE_MIN = 15분)를
 * 이미 넘겼다 — 거기서 깨우면 **봇이 정상인 날에도 매일 거짓 경보**가 나간다.
 * 개장 + 임계가 첫 감시의 하한이다.
 *
 * 이 창은 파이썬(src/heartbeat.py, src/session_gate.py)의 판정과 짝이다.
 * 두 언어로 갈라진 상수는 조용히 어긋나므로
 * tests/test_heartbeat_dispatch_window.py가 그 결합을 지킨다.
 */
export const HEARTBEAT_OPEN_HHMM: [number, number] = [9, 15];
export const HEARTBEAT_CLOSE_HHMM: [number, number] = [15, 50];

/**
 * 감시 격자(분). 최대 발견 지연은 격자 + 임계(heartbeat.MAX_AGE_MIN = 15분)이므로
 * 30분 격자면 45분이다 — 실측 장중 유효 발화 1회(= 사실상 세션 전체)에서 내려온다.
 *
 * **임계와 같은 15분으로 좁히지 않은 이유는 알림 볼륨이다.**
 * check_heartbeat.py는 `alerts.send_alert`를 쓴다 — `send_alert_once`의 쿨다운을
 * 타지 않는다. 그 쿨다운 상태(data/alert_dedup.json)는 db-data 배포 경로로만
 * 살아남고, 그 배선은 trading/scraper/us_trading 셋뿐이다. 즉 **격자를 좁히는
 * 것이 곧 고장 한 건당 텔레그램 통수**다: 30분이면 세션당 최대 13통,
 * 15분이면 27통. 도배는 침묵과 같다.
 *
 * 격자를 임계까지 좁히려면 먼저 쿨다운이 필요하다 — check_heartbeat.py를
 * send_alert_once로 바꾸고, 그 상태를 db-data push가 아닌 곳(예: actions/cache)에
 * 두는 것이 짝이다. db-data로 밀면 이 감시자가 15분마다 매매 루프의 배포 락과
 * 다툰다.
 */
export const HEARTBEAT_GRID_MIN = 30;

/**
 * 격자 하나에 허용하는 창(분). TOKEN_REFRESH_WINDOW_MIN과 같은 이유로 2다:
 * 태스커가 2분 격자로 부르므로 폭이 2면 창마다 정확히 한 틱이 들어온다.
 *
 * `minute % 15 === 0`처럼 정각만 보면 안 된다 — 태스커 격자가 홀수 분에 놓이면
 * 15·45분에 틱이 없어 **발화가 절반으로 준다**. 폭 2는 위상을 안 가린다.
 */
export const HEARTBEAT_WINDOW_MIN = 2;

/**
 * 이 틱에 주 대상(pickWorkflow) **말고 추가로** dispatch할 워크플로.
 *
 * 주 대상을 갈라 쓰지 않는 것이 핵심이다. pickWorkflow가 감시로 분기하면
 * 그 틱의 매매 트리거가 사라진다 — 07시대 30틱이 전부 token_refresh.yml로
 * 가서 한 시간의 매매 트리거를 잃은 2026-09-02와 같은 모양이다.
 *
 * 요일 게이트는 여기 없다. 라우트가 주말을 먼저 걸러 이 함수까지 오지
 * 않으며, 설령 오더라도 heartbeat.judge가 주말을 off_session으로 본다.
 */
export function pickSideWorkflows(hourKst: number, minuteKst: number): string[] {
  const t = hourKst * 60 + minuteKst;
  const open = HEARTBEAT_OPEN_HHMM[0] * 60 + HEARTBEAT_OPEN_HHMM[1];
  const close = HEARTBEAT_CLOSE_HHMM[0] * 60 + HEARTBEAT_CLOSE_HHMM[1];
  if (t < open || t >= close) return [];
  if (minuteKst % HEARTBEAT_GRID_MIN >= HEARTBEAT_WINDOW_MIN) return [];
  return [HEARTBEAT_WORKFLOW];
}
