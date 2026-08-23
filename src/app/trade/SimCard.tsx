'use client';

import { Paper, Group, Stack, SimpleGrid, Text, Badge, Divider } from '@mantine/core';
import { IconHistory } from '@tabler/icons-react';
import PortfolioTable from './PortfolioTable';
import TradeHistoryTable from './TradeHistoryTable';
import { computeNetPL, countTodayTickers, deriveSimHoldings, todayKST } from '@/lib/sim-card';
import { formatMoney } from '@/lib/currency-format';

/**
 * 심 하나의 카드 — 요약 6칸 + 포트폴리오 표 + 기록 표.
 *
 * TradeClient.tsx의 renderSimulationTripod 안 map 본문을 그대로 옮겼다.
 * 숫자는 전부 `@/lib/sim-card`가 만든다(테스트 있음). 여기는 배치만 한다.
 *
 * `type`은 매니페스트 id이고 매매 기록 API가 각 행에 붙이는 값과 같아야 한다 —
 * 어긋나면 기록 표가 조용히 빈다.
 */
export default function SimCard({
    uiKey, label, color, type, stats, portfolio, history, onPickCode, onShowReason,
    currency = 'KRW',
}: {
    uiKey: string;
    label: string;
    color: string;
    type: string;
    stats: any;
    portfolio: Record<string, any>;
    history: any[];
    onPickCode: (code: string, name: string) => void;
    onShowReason: (title: string, content: string) => void;
    currency?: 'KRW' | 'USD';
}) {
    const holdings = deriveSimHoldings(portfolio, stats.current_prices);
    const netPL = computeNetPL(stats);
    const todayTickerCount = countTodayTickers(history, type, todayKST());

    return (
        <Stack gap="sm">
            <Paper p="md" withBorder radius="md" style={{ borderTop: `4px solid var(--mantine-color-${color}-filled)` }}>
                <Group justify="space-between" mb="xs">
                    <Text fw={800} size="lg" c={color}>{label}</Text>
                    <Badge color={color}>{uiKey.toUpperCase()}</Badge>
                </Group>
                <SimpleGrid cols={{ base: 3, sm: 6 }} mb="md">
                    <Stack gap={2}>
                        <Text size="xs" c="dimmed">예수금</Text>
                        <Text fw={700} size="sm">{formatMoney(stats.cash || 0, currency)}</Text>
                    </Stack>
                    <Stack gap={2}>
                        <Text size="xs" c="dimmed">수익률</Text>
                        <Text size="sm" fw={800} c={(stats.profit_rate || 0) >= 0 ? 'red' : 'blue'}>
                            {(stats.profit_rate || 0).toFixed(2)}%
                        </Text>
                    </Stack>
                    <Stack gap={2}>
                        <Text size="xs" c="dimmed">누적 수익</Text>
                        <Text size="sm" fw={800} c={netPL >= 0 ? 'red' : 'blue'}>
                            {netPL >= 0 ? '+' : ''}{formatMoney(netPL, currency)}
                        </Text>
                    </Stack>
                    <Stack gap={2}>
                        <Text size="xs" c="dimmed">누적 수수료</Text>
                        <Text size="sm" fw={700} c="gray.6">{formatMoney(stats.total_fees || 0, currency)}</Text>
                    </Stack>
                    <Stack gap={2}>
                        <Text size="xs" c="dimmed">보유 종목</Text>
                        <Text size="sm" fw={800} c={color}>{holdings.length}개</Text>
                    </Stack>
                    <Stack gap={2}>
                        <Text size="xs" c="dimmed">금일 거래</Text>
                        <Text size="sm" fw={800} c={todayTickerCount > 0 ? 'dark' : 'dimmed'}>{todayTickerCount}종목</Text>
                    </Stack>
                </SimpleGrid>
                <Divider mb="xs" label="포트폴리오 (NAV)" labelPosition="center" />
                {/* 5행(행 ~61px + 헤더)까지 표시 후 스크롤 */}
                <PortfolioTable holdings={holdings} maxHeight={360} onPickCode={onPickCode} currency={currency} />
            </Paper>
            <Paper p="md" withBorder radius="md" bg="gray.0">
                <Text size="xs" fw={700} mb="xs"><IconHistory size={12} style={{ marginRight: 5 }}/>{label} 기록</Text>
                {/* 5행(행 ~52px + 헤더)까지 표시 후 스크롤 */}
                <TradeHistoryTable history={history} targetType={type} maxHeight={305} onShowReason={onShowReason} currency={currency} />
            </Paper>
        </Stack>
    );
}
