/** 리베로 6단계 국면(정본) 표시용. 값은 src/strategy/regime_state.py의 VALID_REGIMES6와 같다.
 * 3단계 current_regime(BULL/SIDEWAYS/BEAR)은 여기서 파생된 값이다.
 * 'BEAR'·'BULL'은 3단계와 철자가 같지만 6단계에서는 '하락'·'상승' 하나만 뜻한다. */
export const REGIME6_ORDER = [
  'STRONG_BEAR', 'BEAR', 'WEAK_SIDEWAYS', 'STRONG_SIDEWAYS', 'BULL', 'STRONG_BULL',
] as const;

const LABEL_KO: Record<string, string> = {
  STRONG_BEAR: '매우하락',
  BEAR: '하락',
  WEAK_SIDEWAYS: '약한횡보',
  STRONG_SIDEWAYS: '강한횡보',
  BULL: '상승',
  STRONG_BULL: '매우상승',
};

/** 한글 라벨. 모르는 값·없음은 null(화면에서 '측정 불가'로 보여야 한다). */
export function regime6Label(v: string | null | undefined): string | null {
  return v != null && Object.prototype.hasOwnProperty.call(LABEL_KO, v) ? LABEL_KO[v] : null;
}
