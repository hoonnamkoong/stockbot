/** 심 카드·포트폴리오 표에서 쓰는 통화 표시. KRW는 국내 심(정수 원),
 * USD는 US 심(소수점 2자리) — 기본값 KRW로 기존 화면과 100% 동일하게 유지한다. */
export function formatMoney(value: number, currency: 'KRW' | 'USD' = 'KRW'): string {
  if (currency === 'USD') {
    const sign = value < 0 ? '-' : '';
    const abs = Math.abs(value);
    return `${sign}$${abs.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  return `${Math.round(value).toLocaleString()}원`;
}
