/**
 * 실거래 기록에 찍는 한국 시각 문자열(`YYYY-MM-DD HH:mm:ss`).
 *
 * 주문 기록·턴 시작/종료 시각이 이 형식으로 저장되고, 파이썬 쪽 기록(get_kst_now)과
 * 같은 표기여야 붙는다. 서버(Vercel)는 UTC라 로컬 시각을 쓰면 9시간 어긋난다.
 *
 * 한국은 서머타임이 없어 UTC+9 고정이 정확하다.
 */
export const KST_OFFSET_MS = 9 * 60 * 60 * 1000;

export function kstTimestamp(now: number = Date.now()): string {
  return new Date(now + KST_OFFSET_MS).toISOString().replace('T', ' ').split('.')[0];
}
