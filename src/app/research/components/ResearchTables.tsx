import React from 'react';
import { Table, Text, Badge, Group, ActionIcon, ScrollArea, Box, Button, Stack, Tooltip } from '@mantine/core';
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
                        <SortButton label="기관(순)" sortKey="inst_net_buy" />
                        <SortButton label="외인추정" sortKey="frgn_fake_ntby_qty" />
                        <SortButton label="기관추정" sortKey="orgn_fake_ntby_qty" />
                        <SortButton label="ROE%" sortKey="roe" />
                        <SortButton label="부채%" sortKey="debt_ratio" />
                        <Table.Th style={{ fontSize: '11px', textAlign: 'center' }}>투자의견</Table.Th>
                        <SortButton label="목표가" sortKey="target_price" />
                        <Table.Th style={{ fontSize: '11px', textAlign: 'center', minWidth: '180px' }}>컨센서스</Table.Th>
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
                                <Badge 
                                    size="xs" 
                                    color={
                                        (() => {
                                            const sent = s.sentiment;
                                            if (!sent) return 'gray';
                                            if (sent === 'Pos' || (typeof sent === 'string' && sent.includes('긍정'))) return 'red';
                                            if (sent === 'Neg' || (typeof sent === 'string' && sent.includes('부정'))) return 'blue';
                                            
                                            // 수치형 점수 처리 (프롬프트 규칙: -10 ~ 10)
                                            const score = parseFloat(String(sent));
                                            if (!isNaN(score)) {
                                                if (score >= 3) return 'red';
                                                if (score <= -3) return 'blue';
                                            }
                                            return 'gray';
                                        })()
                                    } 
                                    style={{ flexShrink: 0, minWidth: '60px' }}
                                >
                                    {s.sentiment || 'Neutral'}
                                </Badge>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                {s.consecutive_days >= 1 && <Badge size="xs" color="red" variant="filled" style={{ flexShrink: 0, minWidth: '40px' }}>{s.consecutive_days}d</Badge>}
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Tooltip label={s.posts_summary} multiline w={300} withArrow position="top">
                                    <Text size="11px" fw={500} lineClamp={2}>{s.posts_summary}</Text>
                                </Tooltip>
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
                                <Text size="xs" c={s.inst_net_buy && s.inst_net_buy > 0 ? 'red' : s.inst_net_buy && s.inst_net_buy < 0 ? 'blue' : 'gray'}>
                                    {s.inst_net_buy !== undefined ? (s.inst_net_buy > 0 ? `+${s.inst_net_buy.toLocaleString()}` : s.inst_net_buy.toLocaleString()) : '-'}
                                </Text>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Text size="xs" c={(s.frgn_fake_ntby_qty ?? 0) > 0 ? 'red' : (s.frgn_fake_ntby_qty ?? 0) < 0 ? 'blue' : 'gray'}>
                                    {s.frgn_fake_ntby_qty != null ? ((s.frgn_fake_ntby_qty > 0 ? '+' : '') + s.frgn_fake_ntby_qty.toLocaleString()) : '-'}
                                </Text>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Text size="xs" c={(s.orgn_fake_ntby_qty ?? 0) > 0 ? 'red' : (s.orgn_fake_ntby_qty ?? 0) < 0 ? 'blue' : 'gray'}>
                                    {s.orgn_fake_ntby_qty != null ? ((s.orgn_fake_ntby_qty > 0 ? '+' : '') + s.orgn_fake_ntby_qty.toLocaleString()) : '-'}
                                </Text>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Text size="xs" c={(s.roe ?? 0) > 0 ? 'teal' : 'gray'}>
                                    {s.roe != null && s.roe !== 0 ? `${s.roe.toFixed(1)}%` : '-'}
                                </Text>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Text size="xs" c={(s.debt_ratio ?? 0) > 200 ? 'red' : 'gray'}>
                                    {s.debt_ratio != null && s.debt_ratio !== 0 ? `${s.debt_ratio.toFixed(0)}%` : '-'}
                                </Text>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Badge size="xs" color={s.invest_opinion?.includes('매수') ? 'red' : s.invest_opinion?.includes('매도') ? 'blue' : 'gray'} variant="light">
                                    {s.invest_opinion || '-'}
                                </Badge>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Text size="xs" fw={700} c="violet">
                                    {s.target_price ? s.target_price.toLocaleString() : '-'}
                                </Text>
                            </Table.Td>
                            <Table.Td onClick={() => onQuickOrder(s)} style={{ cursor: 'pointer' }}>
                                <Tooltip label={s.consensus_summary || '-'} multiline w={250} withArrow position="top">
                                    <Text size="11px" lineClamp={1} c="dimmed">{s.consensus_summary || '-'}</Text>
                                </Tooltip>
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
                                    <Badge size="sm" color="gray" variant="filled" radius="xl" style={{ minWidth: '60px' }}>{s.consecutive_days || 0}일 연속</Badge>
                                </Table.Td>
                                <Table.Td onClick={() => onCellClick(s.code)} align="center" style={{ cursor: 'pointer' }}>
                                    <Text size="sm" fw={600}>{(Number(s.avg_posts) || 0).toFixed(0)}개</Text>
                                </Table.Td>
                                <Table.Td onClick={() => onCellClick(s.code)} align="center" style={{ cursor: 'pointer' }}>
                                    <Text size="sm" fw={600}>{(s.total_posts || 0).toLocaleString()}개</Text>
                                </Table.Td>
                                <Table.Td onClick={() => onCellClick(s.code)} style={{ cursor: 'pointer' }}>
                                    <Group gap={4} align="flex-end" h={40} wrap="nowrap" justify="center">
                                        {(s.sparkline_price || []).map((p: number, idx: number) => {
                                            const prices = s.sparkline_price || [];
                                            // [Fix] 동적 min-max: 바닥을 min*0.998로 설정하여 작은 변동도 가시화
                                            const minP = prices.length > 1 ? Math.min(...prices) * 0.998 : 0;
                                            const maxP = Math.max(...prices, 1);
                                            const range = maxP - minP || 1;
                                            const height = Math.max(((p - minP) / range) * 25, 2);
                                            return (
                                                <Stack key={idx} gap={2} align="center">
                                                    <Text size="8px" fw={700} c="dimmed" style={{ fontSize: '8px' }}>
                                                        {p > 1000 ? `${(p/1000).toFixed(idx === (s.sparkline_price || []).length - 1 ? 1 : 0)}k` : p}
                                                    </Text>
                                                    <Box 
                                                        bg="#ff4d4f" 
                                                        w={10} 
                                                        h={height} 
                                                        style={{ borderRadius: '2px 2px 0 0', opacity: idx === (s.sparkline_price || []).length - 1 ? 1 : 0.5 }} 
                                                    />
                                                </Stack>
                                            );
                                        })}
                                    </Group>
                                </Table.Td>
                                <Table.Td onClick={() => onCellClick(s.code)} style={{ cursor: 'pointer' }}>
                                    <Group gap={4} align="flex-end" h={40} wrap="nowrap" justify="center">
                                        {(s.sparkline_posts || []).map((p: number, idx: number) => {
                                            const posts = s.sparkline_posts || [];
                                            // [Fix] 동적 min-max: 토론 바닥을 min*0.9로 설정 (0 기준 대비 변화량 강조)
                                            const minN = posts.length > 1 ? Math.max(Math.min(...posts) * 0.9, 0) : 0;
                                            const maxN = Math.max(...posts, 5);
                                            const range = maxN - minN || 1;
                                            const height = Math.max(((p - minN) / range) * 25, 2);
                                            return (
                                                <Stack key={idx} gap={2} align="center">
                                                    <Text size="8px" fw={700} c="dimmed" style={{ fontSize: '8px' }}>{p}</Text>
                                                    <Box 
                                                        bg="#228be6" 
                                                        w={10} 
                                                        h={height} 
                                                        style={{ borderRadius: '2px 2px 0 0', opacity: idx === (s.sparkline_posts || []).length - 1 ? 1 : 0.5 }} 
                                                    />
                                                </Stack>
                                            );
                                        })}
                                    </Group>
                                </Table.Td>
                            </Table.Tr>
                        ))}
                    </Table.Tbody>
                </Table>
            </ScrollArea>

        </Box>
    );
};
