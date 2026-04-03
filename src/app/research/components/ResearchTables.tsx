import React from 'react';
import { Table, Text, Badge, Group, ActionIcon, ScrollArea, Box } from '@mantine/core';
import { IconChevronUp, IconChevronDown, IconSelector, IconCoin } from '@tabler/icons-react';
import { Stock, FiveDayStock, SortConfig } from '../types';
import { Sparkline } from './Sparkline';

interface StockTableProps {
    stocks: Stock[];
    sortConfig: SortConfig;
    onSort: (key: string) => void;
    onCellClick: (code: string) => void;
    onQuickOrder: (stock: Stock) => void;
}

export const StockTable = ({ stocks, sortConfig, onSort, onCellClick, onQuickOrder }: StockTableProps) => {
    const SortButton = ({ label, sortKey }: { label: string, sortKey: string }) => (
        <Table.Th style={{ cursor: 'pointer' }} onClick={() => onSort(sortKey)}>
            <Group gap="xs" wrap="nowrap">
                <Text size="xs" fw={700}>{label}</Text>
                {sortConfig.key === sortKey ? (
                    sortConfig.direction === 'asc' ? <IconChevronUp size={12} /> : <IconChevronDown size={12} />
                ) : <IconSelector size={12} />}
            </Group>
        </Table.Th>
    );

    return (
        <ScrollArea h={600} offsetScrollbars>
            <Table highlightOnHover verticalSpacing="xs">
                <Table.Thead style={{ position: 'sticky', top: 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 10 }}>
                    <Table.Tr>
                        <Table.Th>종목명</Table.Th>
                        <SortButton label="시장" sortKey="market" />
                        <SortButton label="코드" sortKey="code" />
                        <SortButton label="현재가" sortKey="current_price" />
                        <SortButton label="등락률" sortKey="change_rate" />
                        <SortButton label="외인변화" sortKey="foreign_change_rate" />
                        <SortButton label="게시글" sortKey="recent_posts_count" />
                        <Table.Th>감정</Table.Th>
                        <Table.Th>연속</Table.Th>
                        <Table.Th>게시물_요약</Table.Th>
                        <Table.Th>외인비중</Table.Th>
                        <Table.Th>전일종가</Table.Th>
                        <Table.Th>전일외인</Table.Th>
                        <Table.Th>Keywords</Table.Th>
                        <Table.Th>Latest Post</Table.Th>
                        <Table.Th>주문</Table.Th>
                    </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                    {stocks.map((s) => (
                        <Table.Tr key={s.code}>
                            <Table.Td onClick={() => onCellClick(s.code)} style={{ cursor: 'pointer' }}>
                                <Text size="sm" fw={500}>{s.name}</Text>
                            </Table.Td>
                            <Table.Td>
                                <Badge size="xs" variant="outline" color={s.market === 'KOSPI' ? 'blue' : 'cyan'}>{s.market}</Badge>
                            </Table.Td>
                            <Table.Td>
                                <Text size="xs" c="dimmed">{s.code}</Text>
                            </Table.Td>
                            <Table.Td>
                                <Text size="sm" fw={600}>{s.current_price?.toLocaleString()}</Text>
                            </Table.Td>
                            <Table.Td>
                                <Text size="sm" fw={600} c={s.change_rate > 0 ? 'red' : s.change_rate < 0 ? 'blue' : 'gray'}>
                                    {s.change_rate > 0 ? '+' : ''}{s.change_rate}%
                                </Text>
                            </Table.Td>
                            <Table.Td>
                                <Text size="xs" c={s.foreign_change_rate > 0 ? 'red' : s.foreign_change_rate < 0 ? 'blue' : 'gray'}>
                                    {s.foreign_change_rate > 0 ? '+' : ''}{s.foreign_change_rate}
                                </Text>
                            </Table.Td>
                            <Table.Td align="center">
                                <Badge size="md" color="blue" radius="sm">{s.recent_posts_count}</Badge>
                            </Table.Td>
                            <Table.Td>
                                <Badge size="xs" color={s.sentiment === 'Pos' ? 'red' : s.sentiment === 'Neg' ? 'blue' : 'gray'}>{s.sentiment || 'Neutral'}</Badge>
                            </Table.Td>
                            <Table.Td>
                                {s.consecutive_days > 1 && <Badge size="xs" color="red" variant="filled">{s.consecutive_days}d</Badge>}
                            </Table.Td>
                            <Table.Td>
                                <Text size="10px" lineClamp={1} style={{ maxWidth: '150px' }}>{s.posts_summary}</Text>
                            </Table.Td>
                            <Table.Td>
                                <Text size="xs">{s.foreign_rate}%</Text>
                            </Table.Td>
                            <Table.Td>
                                <Text size="xs" c="dimmed">{s.prev_close?.toLocaleString()}</Text>
                            </Table.Td>
                            <Table.Td>
                                <Text size="xs" c="dimmed">{s.prev_foreign_rate}%</Text>
                            </Table.Td>
                            <Table.Td>
                                <Text size="10px" c="dimmed" lineClamp={1}>
                                    {Array.isArray(s.top_keywords) ? s.top_keywords.join(', ') : s.top_keywords}
                                </Text>
                            </Table.Td>
                            <Table.Td>
                                <Text size="10px" lineClamp={1} style={{ maxWidth: '120px' }}>{s.latest_post}</Text>
                            </Table.Td>
                            <Table.Td>
                                <ActionIcon variant="light" color="blue" onClick={() => onQuickOrder(s)}>
                                    <IconCoin size={16} />
                                </ActionIcon>
                            </Table.Td>
                        </Table.Tr>
                    ))}
                </Table.Tbody>
            </Table>
        </ScrollArea>
    );
};

interface TrendTableProps {
    data: FiveDayStock[];
    sortConfig: SortConfig;
    onSort: (key: string) => void;
    onCellClick: (code: string) => void;
    title: string;
    titleColor: string;
}

export const TrendTable = ({ data, sortConfig, onSort, onCellClick, title, titleColor }: TrendTableProps) => {
    return (
        <Box>
            <Group mb="xs">
                <Badge color={titleColor} variant="filled">{title}</Badge>
                <Text size="xs" c="dimmed">{data.length} stocks</Text>
            </Group>
            <ScrollArea h={500}>
                <Table highlightOnHover verticalSpacing="xs">
                    <Table.Thead>
                        <Table.Tr>
                            <Table.Th>종목명</Table.Th>
                            <Table.Th onClick={() => onSort('current_price')} style={{ cursor: 'pointer' }}>현재가</Table.Th>
                            <Table.Th onClick={() => onSort('change_rate')} style={{ cursor: 'pointer' }}>등락률</Table.Th>
                            <Table.Th onClick={() => onSort('count')} style={{ cursor: 'pointer' }}>연속 등장</Table.Th>
                            <Table.Th onClick={() => onSort('avg_posts')} style={{ cursor: 'pointer' }}>평균 게시글</Table.Th>
                            <Table.Th onClick={() => onSort('total_posts')} style={{ cursor: 'pointer' }}>총 게시글</Table.Th>
                            <Table.Th>주가 추세 (5D)</Table.Th>
                            <Table.Th>토론 추세 (5D)</Table.Th>
                        </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                        {data.map((s) => (
                            <Table.Tr key={s.code} onClick={() => onCellClick(s.code)} style={{ cursor: 'pointer' }}>
                                <Table.Td>
                                    <Text size="sm" fw={700}>{s.name} <Text span size="xs" c="dimmed" fw={400}>{s.code}</Text></Text>
                                </Table.Td>
                                <Table.Td>
                                    <Text size="sm" fw={600}>{s.current_price?.toLocaleString()}원</Text>
                                </Table.Td>
                                <Table.Td>
                                    <Text size="sm" fw={600} c={s.change_rate > 0 ? 'red' : s.change_rate < 0 ? 'blue' : 'gray'}>
                                        {s.change_rate > 0 ? '+' : ''}{s.change_rate?.toFixed(2)}%
                                    </Text>
                                </Table.Td>
                                <Table.Td>
                                    <Badge size="sm" color="gray" variant="filled" radius="xl">{s.count}일 연속</Badge>
                                </Table.Td>
                                <Table.Td>
                                    <Text size="sm" fw={500}>{s.avg_posts?.toFixed(0)}개</Text>
                                </Table.Td>
                                <Table.Td>
                                    <Text size="sm" fw={500}>{s.total_posts?.toLocaleString()}개</Text>
                                </Table.Td>
                                <Table.Td>
                                    <Sparkline data={s.price_history || []} color="#ff4d4f" />
                                </Table.Td>
                                <Table.Td>
                                    <Sparkline data={s.post_history || []} color="#ff4d4f" />
                                </Table.Td>
                            </Table.Tr>
                        ))}
                    </Table.Tbody>
                </Table>
            </ScrollArea>
        </Box>
    );
};
