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
 * 이 시각에 dispatch할 워크플로 파일명.
 *
 * 기본이 trading.yml인 것이 핵심이다(2026-08-08). 매매가 최상위 경로이고,
 * 스크래핑은 trading.yml이 10분 격자에서 scraper.yml을 깨워 처리한다.
 * 여기를 scraper.yml로 되돌리면 실전 매매가 통째로 멈춘다 — 스크래퍼는
 * 자기를 부르지 않기 때문이다.
 */
export function pickWorkflow(hourKst: number): string {
  if (hourKst === TOKEN_REFRESH_HOUR_KST) return 'token_refresh.yml';
  return 'trading.yml';
}
