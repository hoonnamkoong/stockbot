import React from 'react';
import { Table, Text, Badge, Group, ActionIcon, ScrollArea, Box, Button, Stack } from '@mantine/core';
import { IconChevronUp, IconChevronDown, IconSelector, IconCoin } from '@tabler/icons-react';
import { Stock, FiveDayStock, SortConfig } from '../types';
import { Sparkline } from './Sparkline';

const parseRate = (val: any) => {
    if (typeof val === 'number') return isNaN(val) ? 0 : val;
    if (typeof val === 'string') return parseFloat(val.replace(/[^-0-9.]/g, '')) || 0;
    return 0;
};

interface StockTableProps {
    stocks: Stock[];
    sortConfig: SortConfig;
    onSort: (key: string) => void;
    onCellClick: (code: string) => void;
    onQuickOrder: (stock: Stock) => void;
}

export const StockTable = ({ stocks, sortConfig, onSort, onCellClick, onQuickOrder }: StockTableProps) => {
    const SortButton = ({ label, sortKey }: { label: string, sortKey: string }) => (
        <Table.Th 
            style={{ 
                cursor: 'pointer', 
                textAlign: 'center', 
                fontSize: '11px',
                whiteSpace: 'nowrap',
                fontWeight: 800
            }} 
            onClick={() => onSort(sortKey)}
        >
            <Group gap={4} wrap="nowrap" justify="center">
                <Text size="xs" fw={800}>{label}</Text>
                {sortConfig.key === sortKey ? (
                    sortConfig.direction === 'asc' ? <IconChevronUp size={12} /> : <IconChevronDown size={12} />
                ) : <IconSelector size={12} />}
            </Group>
        </Table.Th>
    );

    return (
        <ScrollArea h="calc(100vh - 120px)" offsetScrollbars>
            <Table highlightOnHover verticalSpacing="xs">
                <Table.Thead style={{ position: 'sticky', top: 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 11 }}>
                    <Table.Tr>
                        <Table.Th style={{ position: 'sticky', left: 0, zIndex: 12, backgroundColor: 'var(--mantine-color-body)', borderRight: '1px solid #eee', fontSize: '11px', textAlign: 'center' }}>종목명</Table.Th>
                        <SortButton label="시장" sortKey="market" />
                        <SortButton label="코드" sortKey="code" />
                        <SortButton label="현재가" sortKey="current_price" />
                        <SortButton label="등락률" sortKey="change_rate" />
                        <SortButton label="외인변화" sortKey="foreign_change_rate" />
                        <SortButton label="게시글" sortKey="recent_posts_count" />
                        <Table.Th style={{ fontSize: '11px', textAlign: 'center' }}>감정</Table.Th>
                        <Table.Th style={{ fontSize: '11px', textAlign: 'center' }}>연속</Table.Th>
                        <Table.Th style={{ fontSize: '11px', textAlign: 'center' }}>게시물_요약</Table.Th>
                        <Table.Th style={{ fontSize: '11px', textAlign: 'center' }}>외인비중</Table.Th>
                        <Table.Th style={{ fontSize: '11px', textAlign: 'center' }}>전일종가</Table.Th>
                        <Table.Th style={{ fontSize: '11px', textAlign: 'center' }}>전일외인</Table.Th>
                        <Table.Th style={{ fontSize: '11px', textAlign: 'center' }}>Keywords</Table.Th>
                    </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                    {stocks.map((s) => (
                        <Table.Tr key={s.code}>
                            <Table.Td style={{ cursor: 'pointer', position: 'sticky', left: 0, zIndex: 5, backgroundColor: 'var(--mantine-color-body)', borderRight: '1px solid #eee' }}>
                                <Text size="sm" fw={700} component="a" href={`https://finance.naver.com/item/main.naver?code=${s.code}`} target="_blank">
                                    {s.name}
                                </Text>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Badge size="xs" variant="outline" color={s.market === 'KOSPI' ? 'blue' : 'cyan'}>{s.market}</Badge>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Text size="xs" c="dimmed">{s.code}</Text>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Text size="sm" fw={800}>{s.current_price?.toLocaleString()}</Text>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Text size="sm" fw={700} c={parseRate(s.change_rate) > 0 ? 'red' : parseRate(s.change_rate) < 0 ? 'blue' : 'gray'}>
                                    {parseRate(s.change_rate) > 0 ? '+' : ''}{parseRate(s.change_rate).toFixed(2)}%
                                </Text>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Text size="xs" c={parseRate(s.foreign_change_rate) > 0 ? 'red' : parseRate(s.foreign_change_rate) < 0 ? 'blue' : 'gray'}>
                                    {parseRate(s.foreign_change_rate) > 0 ? '+' : ''}{parseRate(s.foreign_change_rate)}
                                </Text>
                            </Table.Td>
                            <Table.Td align="center" onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Badge size="md" color="blue" radius="sm" style={{ flexShrink: 0, minWidth: '40px' }}>{s.recent_posts_count}</Badge>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Badge size="xs" color={s.sentiment === 'Pos' ? 'red' : s.sentiment === 'Neg' ? 'blue' : 'gray'} style={{ flexShrink: 0, minWidth: '60px' }}>
                                    {s.sentiment || 'Neutral'}
                                </Badge>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                {s.consecutive_days > 1 && <Badge size="xs" color="red" variant="filled" style={{ flexShrink: 0, minWidth: '40px' }}>{s.consecutive_days}d</Badge>}
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Text size="11px" fw={500} lineClamp={2}>{s.posts_summary}</Text>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Text size="xs" fw={700}>{s.foreign_rate}%</Text>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Text size="xs" c="dimmed">{s.prev_close?.toLocaleString()}</Text>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Text size="xs" c="dimmed">{s.prev_foreign_rate}%</Text>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Text size="10px" c="dimmed" lineClamp={1}>
                                    {Array.isArray(s.top_keywords) ? s.top_keywords.join(', ') : s.top_keywords}
                                </Text>
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
            <ScrollArea h="calc(100vh - 200px)" offsetScrollbars>
                <Table highlightOnHover verticalSpacing="xs">
                    <Table.Thead style={{ position: 'sticky', top: 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 11 }}>
                        <Table.Tr>
                            <Table.Th style={{ position: 'sticky', left: 0, zIndex: 12, backgroundColor: 'var(--mantine-color-body)', borderRight: '1px solid #eee', fontSize: '11px', textAlign: 'center' }}>종목명</Table.Th>
                            <Table.Th onClick={() => onSort('current_price')} style={{ cursor: 'pointer', textAlign: 'center', fontSize: '11px', fontWeight: 800 }}>현재가</Table.Th>
                            <Table.Th onClick={() => onSort('change_rate')} style={{ cursor: 'pointer', textAlign: 'center', fontSize: '11px', fontWeight: 800 }}>등락률</Table.Th>
                            <Table.Th onClick={() => onSort('count')} style={{ cursor: 'pointer', textAlign: 'center', fontSize: '11px', fontWeight: 800 }}>연속 등장</Table.Th>
                            <Table.Th onClick={() => onSort('avg_posts')} style={{ cursor: 'pointer', textAlign: 'center', fontSize: '11px', fontWeight: 800 }}>평균 게시글</Table.Th>
                            <Table.Th onClick={() => onSort('total_posts')} style={{ cursor: 'pointer', textAlign: 'center', fontSize: '11px', fontWeight: 800 }}>총 게시글</Table.Th>
                            <Table.Th style={{ textAlign: 'center', fontSize: '11px', fontWeight: 800 }}>주가 추세 (5D)</Table.Th>
                            <Table.Th style={{ textAlign: 'center', fontSize: '11px', fontWeight: 800 }}>토론 추세 (5D)</Table.Th>
                        </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                        {data.map((s) => (
                            <Table.Tr key={s.code}>
                                <Table.Td style={{ position: 'sticky', left: 0, zIndex: 5, backgroundColor: 'var(--mantine-color-body)', borderRight: '1px solid #eee' }}>
                                    <Text size="sm" fw={800} component="a" href={`https://finance.naver.com/item/main.naver?code=${s.code}`} target="_blank" style={{ color: 'inherit', textDecoration: 'none', cursor: 'pointer' }}>
                                        {s.name} <Text span size="xs" c="dimmed" fw={400}>{s.code}</Text>
                                    </Text>
                                </Table.Td>
                                <Table.Td onClick={() => onCellClick(s.code)} align="center" style={{ cursor: 'pointer' }}>
                                    <Text size="sm" fw={700}>{s.current_price?.toLocaleString()}원</Text>
                                </Table.Td>
                                <Table.Td onClick={() => onCellClick(s.code)} align="center" style={{ cursor: 'pointer' }}>
                                    <Text size="sm" fw={700} c={parseRate(s.change_rate) > 0 ? 'red' : parseRate(s.change_rate) < 0 ? 'blue' : 'gray'}>
                                        {parseRate(s.change_rate) > 0 ? '+' : ''}{parseRate(s.change_rate).toFixed(2)}%
                                    </Text>
                                </Table.Td>
                                <Table.Td onClick={() => onCellClick(s.code)} align="center" style={{ cursor: 'pointer' }}>
                                    <Badge size="sm" color="gray" variant="filled" radius="xl" style={{ minWidth: '60px' }}>{s.count}일 연속</Badge>
                                </Table.Td>
                                <Table.Td onClick={() => onCellClick(s.code)} align="center" style={{ cursor: 'pointer' }}>
                                    <Text size="sm" fw={600}>{(Number(s.avg_posts) || 0).toFixed(0)}개</Text>
                                </Table.Td>
                                <Table.Td onClick={() => onCellClick(s.code)} align="center" style={{ cursor: 'pointer' }}>
                                    <Text size="sm" fw={600}>{s.total_posts?.toLocaleString()}개</Text>
                                </Table.Td>
                                <Table.Td onClick={() => onCellClick(s.code)} style={{ cursor: 'pointer' }}>
                                    <Stack gap={0} style={{ minWidth: '100px' }}>
                                        <Sparkline data={s.sparkline_price || []} color="#ff4d4f" />
                                        {s.sparkline_price && s.sparkline_price.length > 0 && (
                                            <Group gap={4} wrap="nowrap" justify="center">
                                                <Text size="9px" c="dimmed">{s.sparkline_price[0]?.toLocaleString()}</Text>
                                                <Text size="9px" c="dimmed">→</Text>
                                                <Text size="9px" c="blue" fw={700}>{s.sparkline_price[s.sparkline_price.length - 1]?.toLocaleString()}</Text>
                                            </Group>
                                        )}
                                    </Stack>
                                </Table.Td>
                                <Table.Td onClick={() => onCellClick(s.code)} style={{ cursor: 'pointer' }}>
                                    <Stack gap={0} style={{ minWidth: '100px' }}>
                                        <Sparkline data={s.sparkline_posts || []} color="#228be6" />
                                        {s.sparkline_posts && s.sparkline_posts.length > 0 && (
                                            <Group gap={4} wrap="nowrap" justify="center">
                                                <Text size="9px" c="dimmed">{s.sparkline_posts[0]}</Text>
                                                <Text size="9px" c="dimmed">→</Text>
                                                <Text size="9px" c="blue" fw={700}>{s.sparkline_posts[s.sparkline_posts.length - 1]}</Text>
                                            </Group>
                                        )}
                                    </Stack>
                                </Table.Td>
                            </Table.Tr>
                        ))}
                    </Table.Tbody>
                </Table>
            </ScrollArea>

        </Box>
    );
};
