/**
 * 종료된 턴의 이력. 화면의 '지난 턴' 목록이 읽는다.
 *
 * 모든 지표가 현재 턴 기준이 되면서, 껐다 켠 순간 이전 성과가 화면에서 사라진다.
 * 이 목록이 그걸 받는다.
 */
import type { LastTurnResult } from './program-turn.ts';

/** config는 secret repo의 GitHub 파일이다 — 무한히 키우면 매 OFF마다 커밋이 무거워진다. */
export const TURN_HISTORY_MAX = 20;

/** 최신을 앞에 넣고 상한까지 자른다. `pnl: null`(측정 불가) 턴도 그대로 남긴다. */
export function pushTurnHistory(
    history: LastTurnResult[] | null | undefined,
    entry: LastTurnResult,
): LastTurnResult[] {
    return [entry, ...(history || [])].slice(0, TURN_HISTORY_MAX);
}
