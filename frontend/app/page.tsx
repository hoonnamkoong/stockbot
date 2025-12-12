"use client";

import { useEffect, useState, useMemo } from 'react';
import {
    AppShell, Burger, Group, Title, Button, Table, ScrollArea,
    Card, Text, Badge, Modal, Stack, Grid, Box, ActionIcon,
    useMantineTheme
} from '@mantine/core';
import { useDisclosure, useMediaQuery } from '@mantine/hooks';
import { IconRefresh, IconArrowUp, IconArrowDown, IconFileDescription, IconRobot } from '@tabler/icons-react';

// --- Data Types ---
interface Stock {
    market: string;
    code: string;
    name: string;
    current_price: string;
    change_rate: string;
    count_today: number;
    summary: string;
    sentiment: string;
    foreign_ratio_today: string;
    is_consecutive: boolean;
}

interface ResearchItem {
    title: string;
    link: string;
    date: string;
    pdf_link: string;
    section: string;
}

// --- Icons ---

export default function Home() {
    const [opened, { toggle }] = useDisclosure(); // Sidebar toggle
    const isMobile = useMediaQuery('(max-width: 768px)');

    const [stocks, setStocks] = useState<Stock[]>([]);
    const [research, setResearch] = useState<any>({});

    const [sortKey, setSortKey] = useState<keyof Stock>('count_today');
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

    // Load Data (Simulated fetch from committed JSON)
    // In production, this would fetch from specific URL or relative path if SSG copies it.
    // For Vercel Static, we assume data is generated into `public/data` or fetched from GitHub Raw.
    // OR just fetch local relative path assuming 'cron' commits build the site? 
    // User asked for "Vercel as Frontend", implying data is external.
    // Let's use a PLACEHOLDER URL for now, or relative '/data/latest.json' expecting it to be in public.

    const fetchData = async () => {
        try {
            // Fetch raw data directly from GitHub (Bypasses Vercel build time limitation)
            // Cache-busting with timestamp to ensure fresh data
            const ts = new Date().getTime();

            const resStocks = await fetch(`https://raw.githubusercontent.com/hoonnamkoong/stockbot/main/data/latest_stocks.json?t=${ts}`);
            if (resStocks.ok) {
                setStocks(await resStocks.json());
            }

            const resResearch = await fetch(`https://raw.githubusercontent.com/hoonnamkoong/stockbot/main/data/latest_research.json?t=${ts}`);
            if (resResearch.ok) {
                setResearch(await resResearch.json());
            }
        } catch (e) {
            console.error("Failed to load data", e);
        }
    };

    useEffect(() => {
        fetchData();
    }, []);

    // --- Sorting ---
    const sortedStocks = useMemo(() => {
        return [...stocks].sort((a, b) => {
            let valA = a[sortKey];
            let valB = b[sortKey];

            // Number parsing
            if (typeof valA === 'string' && valA.replace(/,/g, '').match(/^\d/)) {
                valA = parseFloat(valA.replace(/,/g, ''));
                valB = parseFloat(valB.replace(/,/g, ''));
            }

            if (valA < valB) return sortOrder === 'asc' ? -1 : 1;
            if (valA > valB) return sortOrder === 'asc' ? 1 : -1;
            return 0;
        });
    }, [stocks, sortKey, sortOrder]);

    const handleSort = (key: keyof Stock) => {
        if (sortKey === key) {
            setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
        } else {
            setSortKey(key);
            setSortOrder('desc');
        }
    };

    // --- Research Modal ---
    const [researchSection, setResearchSection] = useState<string | null>(null);

    // --- Components ---

    const ResearchButton = ({ section, label, color }: any) => {
        const count = research[section]?.today_count || 0;
        return (
            <Button
                variant="light" color={color || 'blue'}
                fullWidth
                rightSection={<Badge color="red" size="sm" circle>{count}</Badge>}
                onClick={() => setResearchSection(section)}
            >
                {label}
            </Button>
        )
    };

    return (
        <AppShell
            header={{ height: 60 }}
            navbar={{ width: 250, breakpoint: 'sm', collapsed: { mobile: !opened } }}
            padding="md"
        >
            <AppShell.Header>
                <Group h="100%" px="md">
                    <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
                    <IconRobot size={30} color="#228be6" />
                    <Title order={3}>StockBot Dashboard 2.1 (NEW)</Title>
                    <Button variant="subtle" size="xs" onClick={fetchData} leftSection={<IconRefresh size={14} />}>
                        Refresh
                    </Button>
                </Group>
            </AppShell.Header>

            <AppShell.Navbar p="md">
                <Stack>
                    <Text size="sm" fw={500} c="dimmed">Research Reports</Text>
                    <ResearchButton section="invest" label="투자정보" color="grape" />
                    <ResearchButton section="company" label="종목분석" color="indigo" />
                    <ResearchButton section="industry" label="산업분석" color="cyan" />
                    <ResearchButton section="economy" label="경제분석" color="teal" />

                    <Text size="sm" fw={500} c="dimmed" mt="xl">Control</Text>
                    <Button variant="outline" color="gray" component="a" href="https://github.com/USER/REPO/actions">
                        GitHub Actions Link
                    </Button>
                </Stack>
            </AppShell.Navbar>

            <AppShell.Main>
                {/* Mobile Card View */}
                <Box hiddenFrom="sm">
                    <Stack>
                        {sortedStocks.map((s: Stock, i: number) => (
                            <Card key={i} withBorder shadow="sm" radius="md">
                                <Group justify="space-between" mb="xs">
                                    <Text fw={700} size="lg">{s.name}</Text>
                                    <Badge color={s.count_today >= 60 ? 'red' : 'blue'}>{s.count_today} posts</Badge>
                                </Group>
                                <Group grow gap="xs">
                                    <Stack gap={0}>
                                        <Text size="xs" c="dimmed">Current</Text>
                                        <Text fw={500}>{s.current_price}</Text>
                                    </Stack>
                                    <Stack gap={0}>
                                        <Text size="xs" c="dimmed">Foreigner</Text>
                                        <Text fw={500}>{s.foreign_ratio_today}</Text>
                                    </Stack>
                                </Group>
                                <Text size="sm" mt="sm" lineClamp={2}>{s.summary}</Text>
                            </Card>
                        ))}
                    </Stack>
                </Box>

                {/* Desktop Table View */}
                <Box visibleFrom="sm">
                    <ScrollArea type="auto">
                        <Table striped highlightOnHover withTableBorder>
                            <Table.Thead>
                                <Table.Tr>
                                    <Table.Th
                                        style={{ position: 'sticky', left: 0, zIndex: 2, background: 'var(--mantine-color-body)' }}
                                    >
                                        Name
                                    </Table.Th>
                                    <Table.Th onClick={() => handleSort('current_price')}>Price</Table.Th>
                                    <Table.Th onClick={() => handleSort('change_rate')}>Rate</Table.Th>
                                    <Table.Th onClick={() => handleSort('count_today')}>Posts (Today)</Table.Th>
                                    <Table.Th>Foreigner %</Table.Th>
                                    <Table.Th>Sentiment</Table.Th>
                                    <Table.Th>Summary</Table.Th>
                                </Table.Tr>
                            </Table.Thead>
                            <Table.Tbody>
                                {sortedStocks.map((s: Stock, i: number) => (
                                    <Table.Tr key={i}>
                                        <Table.Td
                                            fw={700}
                                            style={{ position: 'sticky', left: 0, zIndex: 1, background: 'var(--mantine-color-body)', borderRight: '1px solid #dee2e6' }}
                                        >
                                            {s.name}
                                        </Table.Td>
                                        <Table.Td>{s.current_price}</Table.Td>
                                        <Table.Td c={s.change_rate.includes('-') ? 'blue' : 'red'}>{s.change_rate}</Table.Td>
                                        <Table.Td fw={700}>{s.count_today}</Table.Td>
                                        <Table.Td>{s.foreign_ratio_today}</Table.Td>
                                        <Table.Td>
                                            <Badge color={s.sentiment === '긍정' ? 'green' : s.sentiment === '부정' ? 'red' : 'gray'} variant="light">
                                                {s.sentiment}
                                            </Badge>
                                        </Table.Td>
                                        <Table.Td style={{ minWidth: 300 }}><Text size="sm" lineClamp={1}>{s.summary}</Text></Table.Td>
                                    </Table.Tr>
                                ))}
                            </Table.Tbody>
                        </Table>
                    </ScrollArea>
                </Box>

                {/* Research Modal */}
                <Modal
                    opened={!!researchSection}
                    onClose={() => setResearchSection(null)}
                    title="Research Reports"
                    fullScreen={isMobile}
                    size="lg"
                >
                    <Stack>
                        {research[researchSection!]?.items?.map((item: any, i: number) => (
                            <Card key={i} withBorder padding="sm">
                                <Text fw={700} size="sm">{item.title}</Text>
                                <Group justify="end" mt="xs">
                                    {item.pdf_link && (
                                        <Button size="xs" variant="light" leftSection={<IconRobot size={14} />}>
                                            AI Summary
                                        </Button>
                                    )}
                                    <Button component="a" href={item.link} target="_blank" size="xs" variant="default">
                                        View
                                    </Button>
                                </Group>
                            </Card>
                        ))}
                    </Stack>
                </Modal>

            </AppShell.Main>
        </AppShell>
    );
}
