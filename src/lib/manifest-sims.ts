/**
 * strategy_manifest.yaml(GitHub main)에서 '매매 가능 심'(active && tradeable) 목록을
 * 실시간 조회한다. 프로그램 매매 선택 목록 + selected_sim 화이트리스트 검증의 공통 소스.
 * js-yaml 미도입 → 이 manifest 전용 경량 파서.
 */

export type Sim = { id: string; name: string; description: string };

const MANIFEST_RAW =
    'https://raw.githubusercontent.com/hoonnamkoong/stockbot/main/src/strategy/strategy_manifest.yaml';

export function parseTradeableSims(yaml: string): Sim[] {
    const simIdx = yaml.indexOf('\nsimulators:');
    if (simIdx === -1) return [];
    const block = yaml.slice(simIdx);
    const chunks = block.split(/\n\s*-\s+id:/).slice(1);
    const sims: Sim[] = [];
    for (const chunkRaw of chunks) {
        const chunk = '- id:' + chunkRaw;
        const idM = chunk.match(/id:\s*"([^"]+)"/);
        if (!idM) continue;
        const id = idM[1].trim();
        const desc = (chunk.match(/description:\s*"([^"]*)"/)?.[1] ?? '').trim();
        const active = /active:\s*true/.test(chunk);
        const tradeable = /tradeable:\s*true/.test(chunk);
        if (!active || !tradeable) continue;
        const name = (desc.split(/[-—(]/)[0] || id).trim() || id;
        sims.push({ id, name, description: desc });
    }
    return sims;
}

/** GitHub에서 manifest를 조회해 매매 가능 심 목록 반환. 실패 시 빈 배열. */
export async function fetchTradeableSims(): Promise<Sim[]> {
    try {
        const res = await fetch(`${MANIFEST_RAW}?t=${Date.now()}`, { cache: 'no-store' });
        if (!res.ok) return [];
        return parseTradeableSims(await res.text());
    } catch {
        return [];
    }
}
