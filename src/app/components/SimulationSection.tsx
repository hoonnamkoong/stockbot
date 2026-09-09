'use client';

import { Stack, Group, Title, Button, Paper, Text, NumberInput, SimpleGrid } from '@mantine/core';
import { IconRobot, IconRefresh } from '@tabler/icons-react';
import SimCard from '../trade/SimCard';
import { SIM_REGISTRY } from '@/lib/sim-registry.generated';

/**
 * 심 카드 격자 — `/trade` 하단과 공개 쇼케이스가 **같은 것**을 쓴다.
 *
 * TradeClient.tsx의 renderSimulationTripod을 그대로 옮겼다. 사본을 두지 않은 이유:
 * 심 목록은 매니페스트에서 파생되는데, 화면이 둘로 갈리면 심이 늘 때 한쪽만
 * 고쳐지고 그 사실이 조용하다. 이 레포는 그 방식으로 이미 두 번 당했다
 * (심 목록 3중 하드코딩, 동기화 목록 stale 하드코딩).
 *
 * 공개/비공개의 차이는 **prop 두 개뿐**이다:
 *   - `reset` 없음  → 시뮬레이터 리셋 패널이 없다. 리셋 API는 세션을 요구하지만,
 *                     공개 페이지에 빨간 "전체 리셋" 버튼이 떠 있을 이유가 없다.
 *   - `onPickCode` 없음 → 보유 종목이 읽기 전용이다(채울 주문 폼이 없다).
 */
export type SimResetControls = {
    cash: number | string;
    onCashChange: (v: number | string) => void;
    busy: boolean;
    onOpen: () => void;
};

export default function SimulationSection({
    balances, history, onRefresh, onShowReason, onPickCode, reset,
}: {
    balances: Record<string, any> | null;
    history: any[];
    onRefresh: () => void;
    onShowReason: (title: string, content: string) => void;
    onPickCode?: (code: string, name: string) => void;
    reset?: SimResetControls;
}) {
    if (!balances) return null;

    // 매니페스트에서 파생한다. type은 매니페스트 id이고 매매 기록 API가 각 행에
    // 붙이는 값과 같아야 한다 — 어긋나면 이 카드의 기록 표가 조용히 빈다.
    const simConfigs = SIM_REGISTRY.map((s) => ({
        id: s.uiKey, key: s.uiKey, label: s.label, color: s.color, type: s.id,
    }));

    return (
        <Stack gap="xl">
            <Group justify="space-between">
                <Title order={3}><IconRobot size={24} style={{ marginBottom: -4, marginRight: 8 }} />{simConfigs.length}-Track 지능형 시뮬레이션</Title>
                <Button variant="outline" size="sm" leftSection={<IconRefresh size={16} />} onClick={onRefresh}>전체 데이터 갱신</Button>
            </Group>

            {reset && (
                <Paper p="sm" withBorder radius="md" style={{ background: 'var(--mantine-color-red-0)' }}>
                    <Group justify="space-between" wrap="wrap" gap="sm">
                        <Text size="sm" fw={700} c="red">시뮬레이터 리셋</Text>
                        <Group gap="sm" wrap="wrap">
                            <NumberInput
                                size="xs" w={160}
                                placeholder="예수금(원)"
                                value={reset.cash}
                                onChange={reset.onCashChange}
                                min={100000} max={1000000000} step={100000} thousandSeparator=","
                                disabled={reset.busy}
                            />
                            <Button color="red" size="xs" onClick={reset.onOpen} disabled={reset.busy} loading={reset.busy}>
                                전체 리셋
                            </Button>
                        </Group>
                    </Group>
                </Paper>
            )}

            <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
                {simConfigs.map((sim) => (
                    <SimCard
                        key={sim.id}
                        uiKey={sim.key}
                        label={sim.label}
                        color={sim.color}
                        type={sim.type}
                        stats={balances[sim.key]?.raw || {}}
                        portfolio={balances[sim.key]?.portfolio || {}}
                        history={history}
                        onPickCode={onPickCode}
                        onShowReason={onShowReason}
                    />
                ))}
            </SimpleGrid>
        </Stack>
    );
}
