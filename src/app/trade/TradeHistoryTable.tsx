'use client';

import { Table, Text, Badge, Button, ScrollArea, Box } from '@mantine/core';
import { roiCells, splitTimestamp, type RoiCell } from '@/lib/trade-display';

/** 값 없음을 그리는 규칙 — 매도는 '측정 불가', 매수는 '-'. 0%로 뭉개지 않는다. */
function RoiText({ cell }: { cell: RoiCell }) {
    if (cell.kind === 'value') return <Text size="xs" c={cell.color} fw={600}>{cell.text}</Text>;
    return <Text size="xs" c="dimmed">{cell.kind === 'unmeasurable' ? '측정 불가' : '-'}</Text>;
}

/**
 * 매매 기록 표. ROI 두 칸은 실거래·시뮬 공통이고, 판단 사유는 시뮬에만 붙는다.
 *
 * TradeClient.tsx의 renderHistoryTable을 옮겼다. 필터링은 여기서 한다 —
 * 호출부가 전체 기록과 보고 싶은 type만 넘긴다.
 *
 * ROI 출처가 둘이다: 실거래는 KIS 실현손익(kis-api.matchRealizedRoi), 시뮬은
 * 심이 매도 시점에 CSV에 쓴 값(base_simulator.sell). 둘 다 없으면 '측정 불가'이고,
 * 시뮬의 구 기록(roi 열 이전)은 값이 없는 것이 정상이다.
 */
export default function TradeHistoryTable({
    history, targetType, maxHeight = 'calc(100vh - 320px)', onShowReason,
}: {
    history: any[];
    targetType: string;
    maxHeight?: string | number;
    onShowReason: (title: string, content: string) => void;
}) {
    const isReal = targetType === 'real';
    const filtered = history.filter((h) => h.type === targetType).slice(0, 100);

    if (filtered.length === 0) {
        return (
            <Box style={{ height: 120, textAlign: 'center', width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Text size="xs" c="dimmed">최근 거래 내역이 없습니다.</Text>
            </Box>
        );
    }
    return (
        <ScrollArea.Autosize mah={maxHeight} offsetScrollbars>
            <Table striped highlightOnHover stickyHeader verticalSpacing="xs" style={{ minWidth: 500 }}>
                <Table.Thead>
                    <Table.Tr>
                        <Table.Th style={{ fontSize: '11px' }}>일시</Table.Th>
                        <Table.Th style={{ fontSize: '11px', position: 'sticky', left: 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 1, borderRight: '1px solid #eee' }}>종목</Table.Th>
                        <Table.Th style={{ fontSize: '11px' }}>구분</Table.Th>
                        <Table.Th style={{ fontSize: '11px', textAlign: 'right' }}>체결가</Table.Th>
                        <Table.Th style={{ fontSize: '11px', textAlign: 'right' }}>수량</Table.Th>
                        <Table.Th style={{ fontSize: '11px', textAlign: 'center' }}>ROI(%)</Table.Th>
                        <Table.Th style={{ fontSize: '11px', textAlign: 'right' }}>ROI(금액)</Table.Th>
                        {!isReal && <Table.Th style={{ fontSize: '11px' }}>판단 사유</Table.Th>}
                    </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                    {filtered.map((h, i) => {
                        const { date, clock } = splitTimestamp(h.time);
                        const roi = roiCells(h);
                        return (
                            <Table.Tr key={i}>
                                <Table.Td style={{ whiteSpace: 'nowrap' }}>
                                    <Text size="xs" c="dimmed" style={{ fontSize: '10px' }}>{date}</Text>
                                    <Text size="xs" fw={500} style={{ fontSize: '10px' }}>{clock}</Text>
                                </Table.Td>
                                <Table.Td style={{ position: 'sticky', left: 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 1, borderRight: '1px solid #eee' }}>
                                    <Text size="xs" fw={700}>{String(h.symbol ?? '').split('(')[0]}</Text>
                                </Table.Td>
                                <Table.Td>
                                    <Badge color={h.action === 'BUY' ? 'red' : 'blue'} variant="light" size="xs">
                                        {h.action === 'BUY' ? '매수' : '매도'}
                                    </Badge>
                                </Table.Td>
                                <Table.Td style={{ textAlign: 'right' }}><Text size="xs">{h.price}</Text></Table.Td>
                                <Table.Td style={{ textAlign: 'right' }}><Text size="xs">{h.qty}</Text></Table.Td>
                                <Table.Td style={{ textAlign: 'center' }}>
                                    {roi.pct.kind === 'value'
                                        ? <Badge color={roi.pct.color} variant="light" size="xs">{roi.pct.text}</Badge>
                                        : <RoiText cell={roi.pct} />}
                                </Table.Td>
                                <Table.Td style={{ textAlign: 'right' }}><RoiText cell={roi.amount} /></Table.Td>
                                {!isReal && (
                                    <Table.Td>
                                        <Button variant="subtle" size="compact-xs" onClick={() => onShowReason(`${h.symbol} 판단 근거`, h.reason)}>
                                            <Text size="xs" truncate maw={80}>{h.reason || '사유 없음'}</Text>
                                        </Button>
                                    </Table.Td>
                                )}
                            </Table.Tr>
                        );
                    })}
                </Table.Tbody>
            </Table>
        </ScrollArea.Autosize>
    );
}
