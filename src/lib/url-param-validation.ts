// node --test가 확장자 없는 상대경로를 못 찾는다(sim-reset-targets.ts와 같은 이유) — .ts를 붙인다.
import { SIM_REGISTRY, ANALYZERS } from './sim-registry.generated.ts';

/**
 * `/api/trade/state`(type)와 `/api/download/excel`(month)은 받은 파라미터를 그대로
 * `sim_${type}_state.json` / `trending_integrated_${month}.xlsx`로 문자열 보간해
 * raw.githubusercontent URL을 만든다. 검증이 없으면 `type=../..` 같은 값으로 그
 * URL의 경로가 이탈한다 — 둘 다 세션 뒤라 위험은 낮지만(원본도 공개 브랜치다),
 * 검증 자체가 없었다는 게 보안 검토 지적이다.
 */

/** 등록된 심/분석기의 stateFile에서 실제로 유효한 `type` 값만 뽑는다(예: sim_psych_state.json → psych). */
const VALID_STATE_TYPES = new Set(
    [...SIM_REGISTRY, ...ANALYZERS].map((s) => s.stateFile.replace(/^sim_/, '').replace(/_state\.json$/, '')),
);

export type ParamResult = { ok: true; value: string } | { ok: false; error: string };

/** `type`이 등록부(SIM_REGISTRY/ANALYZERS)에 있는 심의 상태 파일을 가리키는지 검사한다. */
export function validateSimStateType(type: string): ParamResult {
    if (!VALID_STATE_TYPES.has(type)) {
        return { ok: false, error: `알 수 없는 시뮬레이터 type: ${type}` };
    }
    return { ok: true, value: type };
}

/** `month`가 `YYYY-MM` 형식인지 검사한다(월 미지정 = 최신 파일은 라우트에서 별도 처리). */
export function validateMonthParam(month: string): ParamResult {
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) {
        return { ok: false, error: `month는 YYYY-MM 형식이어야 합니다: ${month}` };
    }
    return { ok: true, value: month };
}
