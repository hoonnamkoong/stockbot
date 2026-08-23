'use client';

import { Table, Text, Badge, Checkbox, ScrollArea, Box } from '@mantine/core';
import { derivePosition, pnlColor } from '@/lib/trade-display';
import { formatMoney } from '@/lib/currency-format';

/**
 * 보유 종목 표. 실계좌(isReal)일 때만 일괄매도용 체크박스 열이 붙는다.
 *
 * TradeClient.tsx 안의 renderPortfolioTable을 그대로 옮겼다 — 그 함수는 인자 셋을
 * 받으면서도 선택 상태·종목 선택·알림을 클로저로 끌고 있었다. 여기서는 전부 prop이라
 * 이 표가 무엇에 의존하는지가 시그니처에 다 적혀 있다.
 */
export default function PortfolioTable({
    holdings, isReal = false, maxHeight = 560, selectedCodes = [], onToggleCode, onPickCode,
    currency = 'KRW',
}: {
    holdings: any[];
    isReal?: boolean;
    maxHeight?: string | number;
    /** 일괄매도 선택 상태. isReal일 때만 쓰인다 — 심 카드는 넘기지 않는다. */
    selectedCodes?: string[];
    onToggleCode?: (code: string, checked: boolean) => void;
    onPickCode: (code: string, name: string) => void;
    currency?: 'KRW' | 'USD';
}) {
    if (!holdings || holdings.length === 0) {
        return (
            <Box style={{ height: 120, textAlign: 'center', border: '1px dashed #ced4da', borderRadius: '8px', width: '100%', minWidth: isReal ? 650 : 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Text c="dimmed">보유 종목이 없습니다.</Text>
            </Box>
        );
    }
    return (
        <ScrollArea.Autosize mah={maxHeight} offsetScrollbars>
            <Table striped highlightOnHover verticalSpacing="xs" style={{ minWidth: isReal ? 650 : 600 }}>
                <Table.Thead>
                    <Table.Tr>
                        {isReal && <Table.Th style={{ width: 40, position: 'sticky', left: 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 2 }}></Table.Th>}
                        <Table.Th style={{ width: 120, position: 'sticky', left: isReal ? 40 : 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 1, borderRight: '1px solid #eee' }}>종목명</Table.Th>
                        <Table.Th style={{ textAlign: 'right' }}>수량</Table.Th>
                        <Table.Th style={{ textAlign: 'right' }}>평단가</Table.Th>
                        <Table.Th style={{ textAlign: 'right' }}>현재가</Table.Th>
                        <Table.Th style={{ textAlign: 'right' }}>체결금액</Table.Th>
                        <Table.Th style={{ textAlign: 'center' }}>수익률(%)</Table.Th>
                        <Table.Th style={{ textAlign: 'right' }}>손익({currency === 'USD' ? '$' : '원'})</Table.Th>
                    </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                    {holdings.map((h) => {
                        const { qty, avgPrice, currentPrice, amount, plRate, plAmount, priceKnown } = derivePosition(h);
                        const isSelected = selectedCodes.includes(h.code);

                        return (
                            <Table.Tr key={h.code} style={{ cursor: isReal ? 'pointer' : 'default' }}>
                                {isReal && (
                                    <Table.Td onClick={(e) => e.stopPropagation()} style={{ position: 'sticky', left: 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 2 }}>
                                        <Checkbox
                                            checked={isSelected}
                                            onChange={(event) => onToggleCode?.(h.code, event.currentTarget.checked)}
                                        />
                                    </Table.Td>
                                )}
                                <Table.Td
                                    onClick={() => onPickCode(h.code, h.name)}
                                    style={{ cursor: 'pointer', position: 'sticky', left: isReal ? 40 : 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 1, borderRight: '1px solid #eee' }}
                                >
                                    <Text size="sm" fw={700} truncate maw={100} c="blue" style={{ textDecoration: 'underline', textUnderlineOffset: '2px' }}>{h.name}</Text>
                                    <Text size="xs" c="dimmed">{h.code}</Text>
                                </Table.Td>
                                <Table.Td style={{ textAlign: 'right' }}>
                                    <Text size="sm">{qty.toLocaleString()}주</Text>
                                </Table.Td>
                                <Table.Td style={{ textAlign: 'right' }}>
                                    <Text size="sm">{formatMoney(avgPrice, currency)}</Text>
                                </Table.Td>
                                <Table.Td style={{ textAlign: 'right' }}>
                                    {priceKnown
                                        ? <Text size="sm" fw={500} c="teal">{formatMoney(currentPrice, currency)}</Text>
                                        : <Text size="sm" c="dimmed">시세 미확인</Text>}
                                </Table.Td>
                                <Table.Td style={{ textAlign: 'right' }}>
                                    <Text size="sm" fw={700}>{formatMoney(amount, currency)}</Text>
                                </Table.Td>
                                <Table.Td style={{ textAlign: 'center' }}>
                                    {/* 시세를 모르면 등락률도 모른다. 0%로 그리면 '안 움직였다'는 거짓이 된다. */}
                                    {priceKnown ? (
                                        <Badge color={pnlColor(plRate)} variant="filled" size="sm" style={{ width: 65 }}>
                                            {plRate >= 0 ? '+' : ''}{plRate.toFixed(2)}%
                                        </Badge>
                                    ) : (
                                        <Text size="xs" c="dimmed">측정 불가</Text>
                                    )}
                                </Table.Td>
                                <Table.Td style={{ textAlign: 'right' }}>
                                    {priceKnown
                                        ? <Text size="sm" fw={700} c={pnlColor(plAmount)}>{plAmount >= 0 ? '+' : ''}{formatMoney(plAmount, currency)}</Text>
                                        : <Text size="xs" c="dimmed">측정 불가</Text>}
                                </Table.Td>
                            </Table.Tr>
                        );
                    })}
                </Table.Tbody>
            </Table>
        </ScrollArea.Autosize>
    );
}
