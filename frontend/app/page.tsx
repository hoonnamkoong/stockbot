'use client';

import { useState, useEffect } from 'react';
import { AppShell, Burger, Group, Title, Button, Table, Text, Badge, Card, Modal, useMantineTheme, ScrollArea, Tabs, PasswordInput, Paper, UnstyledButton, Center, Tooltip, Popover, Grid, Flex, SegmentedControl, Divider, ActionIcon } from '@mantine/core';
import { useDisclosure, useMediaQuery } from '@mantine/hooks';
import { IconRefresh, IconRobot, IconNews, IconCheck, IconSelector, IconChevronUp, IconChevronDown } from '@tabler/icons-react';
import { clsx } from 'clsx';

// --- Types ---
type Stock = {
    market: string;
    code: string;
    name: string;
    price?: string;
    current_price?: string; // Legacy fallback
    prev_close?: string;
    yesterday_close?: string; // Legacy fallback
    change_rate: string;
    volume?: string;
    recent_posts_count?: number;
    count_today?: number; // Legacy fallback
    foreign_rate?: string;
    foreign_ratio_today?: string; // Legacy fallback
    prev_foreign_rate?: string;
    foreign_ratio_yesterday?: string; // Legacy fallback
    posts_summary?: string;
    summary?: string; // Legacy fallback
    sentiment: string;
    is_last_captured?: boolean;
    is_consecutive?: boolean; // Legacy fallback
    [key: string]: any; // Index signature for sorting
};

// --- Constants ---
const REPO_OWNER = "hoonnamkoong";
const REPO_NAME = "stockbot";
const WORKFLOW_ID = "scraper.yml";

export default function Home() {
    const [opened, { toggle }] = useDisclosure();
    const [stocks, setStocks] = useState<Stock[]>([]);
    const [research, setResearch] = useState<any>(null);
    const [loading, setLoading] = useState(false);
    const [lastUpdated, setLastUpdated] = useState<string>('');
    const [activeTab, setActiveTab] = useState<string | null>('ALL');
    const [viewMode, setViewMode] = useState<'card' | 'table'>('card'); // 'card' or 'table'

    // Sorting State
    const [sortConfig, setSortConfig] = useState<{ key: string | null; direction: 'asc' | 'desc' }>({ key: 'recent_posts_count', direction: 'desc' });

    // Scraper Control
    const [controlOpened, { open: openControl, close: closeControl }] = useDisclosure(false);
    const [githubToken, setGithubToken] = useState('');
    const [workflowStatus, setWorkflowStatus] = useState<'idle' | 'running' | 'success' | 'error'>('idle');
    const [workflowLogs, setWorkflowLogs] = useState<string[]>([]);

    const theme = useMantineTheme();
    const isMobile = useMediaQuery(`(max-width: ${theme.breakpoints.sm})`);

    // Research Modal
    const [researchModalOpened, { open: openResearchModal, close: closeResearchModal }] = useDisclosure(false);
    const [selectedResearchCategory, setSelectedResearchCategory] = useState<string | null>(null);
    const [pdfItem, setPdfItem] = useState<any>(null);

    useEffect(() => {
        fetchData();
        const storedToken = localStorage.getItem('github_pat');
        if (storedToken) setGithubToken(storedToken);
    }, []);

    const [systemLogs, setSystemLogs] = useState<string[]>([]);

    const addSystemLog = (msg: string) => {
        setSystemLogs(prev => [`[${new Date().toLocaleTimeString()}] ${msg}`, ...prev]);
    };

    const fetchData = async () => {
        setLoading(true);
        addSystemLog("🔄 데이터 새로고침 시작...");
        try {
            const timeMap = new Date().getTime();
            const stockUrl = `https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/main/data/latest_stocks.json?t=${timeMap}`;

            addSystemLog(`📡 Fetching Stocks: ${stockUrl}`);

            const resStocks = await fetch(stockUrl, { cache: 'no-store' });
            addSystemLog(`📩 Stocks Status: ${resStocks.status} ${resStocks.statusText}`);

            if (resStocks.ok) {
                const data = await resStocks.json();
                addSystemLog(`✅ Stocks Loaded: ${data.length} items`);
                setStocks(data);
            } else {
                const text = await resStocks.text();
                addSystemLog(`❌ Stocks Fetch Failed: ${text.slice(0, 100)}`);
            }

            // Fetch Research
            const resResearch = await fetch(`https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/main/data/latest_research.json?t=${timeMap}`, { cache: 'no-store' });
            if (resResearch.ok) {
                const data = await resResearch.json();
                setResearch(data);
                addSystemLog(`✅ Research Loaded`);
            }

            // Fetch Status (Timestamp)
            try {
                const resStatus = await fetch(`https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/main/data/status.json?t=${timeMap}`, { cache: 'no-store' });
                if (resStatus.ok) {
                    const statusData = await resStatus.json();
                    setLastUpdated(statusData.last_updated);
                } else {
                    setLastUpdated(new Date().toLocaleTimeString()); // Fallback
                }
            } catch (e) {
                setLastUpdated(new Date().toLocaleTimeString());
            }

        } catch (e: any) {
            console.error(e);
            addSystemLog(`❌ CRITICAL ERROR: ${e.message}`);
        }
        setLoading(false);
    };


    const runScraper = async () => {
        if (!githubToken) {
            alert("GitHub Personal Access Token (PAT)을 먼저 입력해주세요.");
            return;
        }
        localStorage.setItem('github_pat', githubToken);
        setWorkflowStatus('running');
        setWorkflowLogs([]); // Reset logs
        addLog("🚀 워크플로우 실행 요청 중...");

        try {
            const res = await fetch(`https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${WORKFLOW_ID}/dispatches`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${githubToken}`,
                    'Accept': 'application/vnd.github.v3+json',
                },
                body: JSON.stringify({ ref: 'main' })
            });

            if (res.ok) {
                addLog("✅ 요청 전송 성공! 실행 대기 중...");
                addLog("(GitHub Actions가 켜질 때까지 약 10~20초 소요됩니다)");
                monitorWorkflow(); // Start polling
            } else {
                addLog(`❌ 요청 실패: ${res.status} ${res.statusText}`);
                setWorkflowStatus('error');
            }
        } catch (e: any) {
            addLog(`❌ 에러 발생: ${e.message}`);
            setWorkflowStatus('error');
        }
    };

    const monitorWorkflow = async () => {
        let attempts = 0;
        const interval = setInterval(async () => {
            attempts++;
            if (attempts > 7200) { // Practically no limit (10 hours)
                clearInterval(interval);
                addLog("⚠️ 모니터링 자동 종료 (10시간 경과)");
                setWorkflowStatus('idle');
                return;
            }

            try {
                const res = await fetch(`https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/runs?per_page=1`, {
                    headers: { 'Authorization': `Bearer ${githubToken}` }
                });
                if (!res.ok) return;

                const data = await res.json();
                if (data.workflow_runs && data.workflow_runs.length > 0) {
                    const run = data.workflow_runs[0];
                    addLog(`🔄 상태: ${run.status} (${run.conclusion || 'Running'}) - ${new Date().toLocaleTimeString()}`);

                    if (run.status === 'completed') {
                        clearInterval(interval);
                        addLog(run.conclusion === 'success' ? "✨ 실행 성공! 데이터를 갱신합니다." : "❌ 실행 실패. Actions 탭을 확인하세요.");
                        setWorkflowStatus(run.conclusion === 'success' ? 'success' : 'error');
                        if (run.conclusion === 'success') {
                            setTimeout(fetchData, 3000);
                        }
                    }
                }
            } catch (e) {
                console.error(e);
            }
        }, 5000);
    };

    const addLog = (msg: string) => {
        setWorkflowLogs(prev => [...prev, msg]);
    };


    // --- Sort Logic ---
    const handleSort = (key: string) => {
        let direction: 'asc' | 'desc' = 'asc';
        if (sortConfig.key === key && sortConfig.direction === 'asc') {
            direction = 'desc';
        }
        setSortConfig({ key, direction });
    };

    const sortedStocks = [...stocks].filter(s => activeTab === 'ALL' ? true : s.market === activeTab).sort((a, b) => {
        if (!sortConfig.key) return 0;

        let valA = a[sortConfig.key];
        let valB = b[sortConfig.key];

        // Handle numeric strings (remove commas, %)
        const parseValue = (v: any) => {
            if (typeof v === 'string') {
                // Check if it looks like a number (comma separated, percentage)
                const cleaned = v.replace(/,/g, '').replace('%', '');
                if (!isNaN(Number(cleaned)) && cleaned !== '') {
                    return Number(cleaned);
                }
                return v.toLowerCase(); // String comparison
            }
            return v; // number or boolean
        };

        const parsedA = parseValue(valA);
        const parsedB = parseValue(valB);

        if (parsedA < parsedB) {
            return sortConfig.direction === 'asc' ? -1 : 1;
        }
        if (parsedA > parsedB) {
            return sortConfig.direction === 'asc' ? 1 : -1;
        }
        return 0;
    });

    // Research Modal Logic
    const handleResearchClick = (key: string) => {
        setSelectedResearchCategory(key);
        openResearchModal();
    };

    // Helper for Sort Header
    const ThSort = ({ children, sortKey }: { children: React.ReactNode, sortKey: string }) => {
        const active = sortConfig.key === sortKey;
        const Icon = sortConfig.direction === 'asc' ? IconChevronUp : IconChevronDown;
        return (
            <Table.Th onClick={() => handleSort(sortKey)} style={{ cursor: 'pointer' }}>
                <Group justify="space-between" wrap="nowrap">
                    <Text fw={700} size="sm">{children}</Text>
                    {active ? <Icon size={14} /> : <IconSelector size={14} style={{ opacity: 0.3 }} />}
                </Group>
            </Table.Th>
        );
    };


    return (
        <AppShell
            header={{ height: 60 }}
            navbar={{ width: 300, breakpoint: 'sm', collapsed: { mobile: !opened } }}
            padding="md"
        >
            <AppShell.Header>
                <Group h="100%" px="md">
                    <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
                    <IconRobot size={isMobile ? 24 : 30} color="#228be6" />
                    <Title order={3} size={isMobile ? 'h5' : 'h3'}>
                        {isMobile ? 'StockBot V6.10' : 'StockBot V6.10 (SQ Verified)'}
                    </Title>
                    <Group ml="auto" gap={isMobile ? 'xs' : 'md'}>
                        {isMobile ? (
                            /* Mobile: Icon Only Buttons */
                            <>
                                <ActionIcon variant="light" color="violet" size="lg" onClick={openControl}>
                                    <IconRefresh size={18} />
                                </ActionIcon>
                                <ActionIcon variant="subtle" size="lg" onClick={fetchData}>
                                    {loading ? '...' : <IconRefresh size={18} />}
                                </ActionIcon>
                            </>
                        ) : (
                            /* Desktop: Full Buttons */
                            <>
                                <Button variant="light" color="violet" onClick={openControl} leftSection={<IconRefresh size={16} />}>
                                    Control
                                </Button>
                                <Button variant="subtle" size="xs" onClick={fetchData} leftSection={<IconRefresh size={14} />}>
                                    {loading ? '...' : <IconRefresh />}
                                </Button>
                            </>
                        )}
                    </Group>
                </Group>
            </AppShell.Header>

            <AppShell.Navbar p="md">
                <Text fw={700} mb="sm">Research Reports</Text>
                {['invest', 'company', 'industry', 'economy'].map((key) => {
                    const count = research?.[key]?.today_count || 0;
                    const labelMap: any = { invest: '투자정보', company: '종목분석', industry: '산업분석', economy: '경제분석' };
                    return (
                        <Button
                            key={key}
                            fullWidth
                            variant="light"
                            mb="xs"
                            justify="space-between"
                            onClick={() => handleResearchClick(key)}
                            rightSection={<Badge color="red" size="sm" circle>{count}</Badge>}
                        >
                            {labelMap[key]}
                        </Button>
                    );
                })}

                <Text fw={700} mt="md" mb="sm">News Feed</Text>
                <Button
                    fullWidth
                    variant="default" // distinct from Research
                    leftSection={<IconNews size={16} />}
                    justify="flex-start"
                    component="a"
                    href="https://www.tossinvest.com/feed/news"
                    target="_blank"
                >
                    토스증권 뉴스 (Toss)
                </Button>
            </AppShell.Navbar>

            <AppShell.Main>
                {/* Responsive Navigation Layout */}
                {isMobile ? (
                    <div className="flex flex-col gap-3 mb-4">
                        <Group justify="space-between" align="center" mb={-5}>
                            <Text size="xs" c="dimmed">🕒 Update: {lastUpdated}</Text>
                        </Group>
                        <Tabs value={activeTab} onChange={setActiveTab}>
                            <Tabs.List grow>
                                <Tabs.Tab value="ALL">전체</Tabs.Tab>
                                <Tabs.Tab value="KOSPI">KOSPI</Tabs.Tab>
                                <Tabs.Tab value="KOSDAQ">KOSDAQ</Tabs.Tab>
                            </Tabs.List>
                        </Tabs>
                        <SegmentedControl
                            fullWidth
                            size="sm"
                            value={viewMode}
                            onChange={(val: any) => setViewMode(val)}
                            data={[
                                { label: '카드형 (Card)', value: 'card' },
                                { label: '표 (Table)', value: 'table' },
                            ]}
                        />
                    </div>
                ) : (
                    <Group justify="space-between" mb="md" align="center">
                        <Group>
                            <Tabs value={activeTab} onChange={setActiveTab}>
                                <Tabs.List>
                                    <Tabs.Tab value="ALL">전체 (ALL)</Tabs.Tab>
                                    <Tabs.Tab value="KOSPI">KOSPI</Tabs.Tab>
                                    <Tabs.Tab value="KOSDAQ">KOSDAQ</Tabs.Tab>
                                </Tabs.List>
                            </Tabs>
                            {lastUpdated && <Text size="xs" c="dimmed" ml="md">🕒 Update: {lastUpdated}</Text>}
                        </Group>

                        {/* Desktop View Toggle */}
                        <SegmentedControl
                            size="xs"
                            value={viewMode}
                            onChange={(val: any) => setViewMode(val)}
                            data={[
                                { label: '카드형', value: 'card' },
                                { label: '표 (Table)', value: 'table' },
                            ]}
                        />
                    </Group>
                )
                }

                {
                    (isMobile && viewMode === 'card') ? (
                        <div className="flex flex-col gap-3">
                            {sortedStocks.map((stock) => (
                                <Card key={stock.code} shadow="sm" padding="lg" radius="md" withBorder>
                                    <Group justify="space-between" mb="xs">
                                        <Text fw={500}>{stock.name}</Text>
                                        <Badge color={stock.change_rate.includes('+') ? 'red' : 'blue'}>{stock.change_rate}</Badge>
                                    </Group>
                                    <Group gap="xs" mb="xs">
                                        <Text size="sm" c="dimmed">Posts: <b>{stock.recent_posts_count || stock.count_today}</b></Text>
                                        <Text size="sm" c="dimmed">For.: {stock.foreign_rate || stock.foreign_ratio_today}</Text>
                                    </Group>
                                    {(stock.is_last_captured || stock.is_consecutive) && <Badge variant="outline" mb="xs" color="green" size="sm" leftSection={<IconCheck size={12} />}>연속 포착</Badge>}
                                    <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{stock.posts_summary || stock.summary}</Text>
                                </Card>
                            ))}
                        </div>
                    ) : (
                        <ScrollArea type="always" offsetScrollbars>
                            <Table striped highlightOnHover withTableBorder style={{ minWidth: 1000 }}> {/* Ensure width for sticky behavior */}
                                <Table.Thead style={{ position: 'sticky', top: 0, zIndex: 3, backgroundColor: 'var(--mantine-color-body)' }}>
                                    <Table.Tr>
                                        {/* Sticky First Column Header */}
                                        <Table.Th
                                            onClick={() => handleSort('name')}
                                            style={{
                                                cursor: 'pointer',
                                                position: 'sticky',
                                                left: 0,
                                                zIndex: 4,
                                                backgroundColor: 'var(--mantine-color-body)',
                                                boxShadow: '2px 0 5px rgba(0,0,0,0.1)'
                                            }}
                                        >
                                            종목명 (코드) {sortConfig?.key === 'name' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}
                                        </Table.Th>
                                        <Table.Th onClick={() => handleSort('price')} style={{ cursor: 'pointer' }}>현재가 {sortConfig?.key === 'price' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}</Table.Th>
                                        <Table.Th>어제가</Table.Th>
                                        <Table.Th onClick={() => handleSort('change_rate')} style={{ cursor: 'pointer' }}>등락률 {sortConfig?.key === 'change_rate' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}</Table.Th>
                                        <Table.Th onClick={() => handleSort('volume')} style={{ cursor: 'pointer' }}>거래량 {sortConfig?.key === 'volume' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}</Table.Th>
                                        <Table.Th onClick={() => handleSort('recent_posts_count')} style={{ cursor: 'pointer' }}>토론글 {sortConfig?.key === 'recent_posts_count' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}</Table.Th>
                                        <Table.Th>외인비(현)</Table.Th>
                                        <Table.Th>외인비(전)</Table.Th>
                                        <Table.Th>감성</Table.Th>
                                        <Table.Th>연속</Table.Th>
                                        <Table.Th>요약 (Click)</Table.Th>
                                    </Table.Tr>
                                </Table.Thead>
                                <Table.Tbody>
                                    {sortedStocks.map((stock) => (
                                        <Table.Tr key={stock.code}>
                                            {/* Sticky First Column Data */}
                                            <Table.Td
                                                style={{
                                                    position: 'sticky',
                                                    left: 0,
                                                    backgroundColor: 'var(--mantine-color-body)',
                                                    zIndex: 2,
                                                    boxShadow: '2px 0 5px rgba(0,0,0,0.1)'
                                                }}
                                            >
                                                <Text fw={700}>
                                                    <a href={`https://finance.naver.com/item/main.naver?code=${stock.code}`} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'underline' }}>
                                                        {stock.name} 🔗
                                                    </a>
                                                </Text>
                                                <Text size="xs" c="dimmed">{stock.code}</Text>
                                            </Table.Td>
                                            <Table.Td>{stock.price || stock.current_price}</Table.Td>
                                            <Table.Td>{stock.prev_close || stock.yesterday_close}</Table.Td>
                                            <Table.Td style={{ color: stock.change_rate.includes('+') ? 'red' : 'blue' }}>{stock.change_rate}</Table.Td>
                                            <Table.Td>{stock.volume}</Table.Td>
                                            <Table.Td>{stock.recent_posts_count || stock.count_today}</Table.Td>
                                            <Table.Td>{stock.foreign_rate || stock.foreign_ratio_today}</Table.Td>
                                            <Table.Td>{stock.prev_foreign_rate || stock.foreign_ratio_yesterday}</Table.Td>
                                            <Table.Td>
                                                <Badge color={stock.sentiment === '긍정' ? 'green' : stock.sentiment === '부정' ? 'red' : 'gray'}>
                                                    {stock.sentiment}
                                                </Badge>
                                            </Table.Td>
                                            <Table.Td>{(stock.is_last_captured || stock.is_consecutive) ? <IconCheck size={16} color="green" /> : '-'}</Table.Td>
                                            <Table.Td style={{ maxWidth: 200 }}>
                                                <Popover width={300} position="bottom" withArrow shadow="md">
                                                    <Popover.Target>
                                                        <Text truncate style={{ cursor: 'pointer', textDecoration: 'underline' }}>
                                                            {stock.posts_summary || stock.summary}
                                                        </Text>
                                                    </Popover.Target>
                                                    <Popover.Dropdown>
                                                        <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{stock.posts_summary || stock.summary}</Text>
                                                    </Popover.Dropdown>
                                                </Popover>
                                            </Table.Td>
                                        </Table.Tr>
                                    ))}
                                </Table.Tbody>
                            </Table>
                        </ScrollArea>
                    )
                }


                {/* DEBUG CONSOLE (Hidden by User Request V6.3)
                <Paper withBorder p="md" mt="xl" bg="gray.0">
                    <Text fw={700} size="sm" mb="xs">🛠️ 시스템 로그 (Debug Console)</Text>
                    <ScrollArea h={150} type="always" bg="black" style={{ borderRadius: 8 }}>
                        <div style={{ padding: 10 }}>
                            {systemLogs.length === 0 ? <Text c="dimmed" size="xs">로그 대기 중...</Text> :
                                systemLogs.map((log, i) => (
                                    <Text key={i} c="green" size="xs" style={{ fontFamily: 'monospace' }}>{log}</Text>
                                ))
                            }
                        </div>
                    </ScrollArea>
                </Paper>
                */}
            </AppShell.Main >

            {/* Scraper Control Modal */}
            < Modal opened={controlOpened} onClose={closeControl} title="스크래퍼 제어 센터 (Scraper Control)" centered >
                <PasswordInput
                    label="GitHub Personal Access Token (PAT)"
                    placeholder="ghp_..."
                    value={githubToken}
                    onChange={(e) => setGithubToken(e.target.value)}
                    description="Actions 실행 권한이 필요합니다 (브라우저 저장됨)"
                    mb="md"
                />
                <Button fullWidth onClick={runScraper} loading={workflowStatus === 'running'} color="teal">
                    지금 즉시 실행 (RUN NOW)
                </Button>

                <Paper withBorder p="sm" mt="md" bg="gray.1">
                    <Text size="sm" fw={700} mb="xs">실시간 상태 로그:</Text>
                    <ScrollArea h={150}>
                        {workflowLogs.length === 0 ? <Text size="xs" c="dimmed">대기 중...</Text> : workflowLogs.map((log, i) => <Text key={i} size="xs">{log}</Text>)}
                    </ScrollArea>
                </Paper>
            </Modal >

            {/* Research List Modal */}
            < Modal opened={researchModalOpened} onClose={closeResearchModal} title={`오늘의 리포트 (${selectedResearchCategory && research?.[selectedResearchCategory]?.today_count}건)`} centered size="90%" styles={{ body: { height: '80vh', overflow: 'hidden', padding: 0 } }}>
                {selectedResearchCategory && research?.[selectedResearchCategory]?.items?.length > 0 ? (
                    isMobile ? (
                        // --- Mobile View (Stacked) ---
                        <ScrollArea h="100%" p="md">
                            <div className="flex flex-col gap-4">
                                {/* Insight Summary Top */}
                                <Paper withBorder p="sm" bg="blue.0" radius="md">
                                    <Group mb="xs">
                                        <IconNews size={20} color="#228be6" />
                                        <Text fw={700} size="md" c="blue.8">오늘의 시장 인사이트</Text>
                                    </Group>
                                    <Text size="sm" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                                        {research[selectedResearchCategory].summary}
                                    </Text>
                                </Paper>

                                {/* List Area */}
                                <div className="flex flex-col gap-3">
                                    {research[selectedResearchCategory].items.map((item: any, idx: number) => (
                                        <Card key={idx} shadow="sm" padding="md" radius="md" withBorder>
                                            <Text fw={700} size="md" mb="xs">{item.title}</Text>

                                            {/* Tags */}
                                            <Group gap={6} mb="sm">
                                                <Badge color="gray" size="xs">{item.date}</Badge>
                                                {item.pdf_analysis?.opinion && item.pdf_analysis.opinion !== 'N/A' && (
                                                    <Badge size="xs" color={item.pdf_analysis.opinion === 'BUY' ? 'red' : 'orange'}>
                                                        {item.pdf_analysis.opinion}
                                                    </Badge>
                                                )}
                                            </Group>

                                            {/* Summary */}
                                            <Paper bg="gray.1" p="xs" radius="sm" mb="sm">
                                                <Text size="xs" c="dimmed" lineClamp={4}>
                                                    {item.body_summary || "요약 내용이 없습니다."}
                                                </Text>
                                            </Paper>

                                            {/* Buttons */}
                                            <Group justify="end" gap="xs">
                                                <Button variant="light" size="xs" component="a" href={item.link} target="_blank">본문</Button>
                                                {item.pdf_link && (
                                                    <>
                                                        <Button variant="default" size="xs" component="a" href={item.pdf_link} target="_blank">PDF</Button>
                                                        <Button variant="filled" color="violet" size="xs" onClick={() => setPdfItem(item)}>분석</Button>
                                                    </>
                                                )}
                                            </Group>
                                        </Card>
                                    ))}
                                </div>
                            </div>
                        </ScrollArea>
                    ) : (
                        // --- Desktop View (Grid) ---
                        <Grid h="90%" gutter="xl" p="md">
                            {/* LEFT: Daily Briefing (Expanded) */}
                            <Grid.Col span={4}>
                                <Paper withBorder p="md" bg="blue.0" h="100%" radius="md">
                                    <Group mb="md">
                                        <IconNews size={24} color="#228be6" />
                                        <Text fw={700} size="lg" c="blue.8">오늘의 시장 인사이트</Text>
                                    </Group>
                                    <ScrollArea h="65vh" offsetScrollbars>
                                        <Text size="sm" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                                            {research[selectedResearchCategory].summary}
                                        </Text>
                                        <Text size="xs" c="dimmed" mt="xl" pt="xl">
                                            * AI가 오늘 발행된 리포트들의 핵심 내용(매수의견, 목표주가, 산업동향)을 종합하여 도출한 인사이트입니다.
                                        </Text>
                                    </ScrollArea>
                                </Paper>
                            </Grid.Col>

                            {/* RIGHT: List (Scrollable) */}
                            <Grid.Col span={8}>
                                <ScrollArea h="75vh" offsetScrollbars>
                                    {research[selectedResearchCategory].items.map((item: any, idx: number) => (
                                        <Card key={idx} shadow="sm" padding="lg" radius="md" withBorder mb="md">
                                            <Group justify="space-between" mb="xs">
                                                <div style={{ flex: 1 }}>
                                                    <Text fw={700} size="md" mb={4}>{item.title}</Text>
                                                    <Group gap="xs">
                                                        <Badge color="gray" size="sm">{item.date}</Badge>
                                                        {item.pdf_analysis?.opinion && item.pdf_analysis.opinion !== 'N/A' && (
                                                            <Badge color={item.pdf_analysis.opinion === 'BUY' ? 'red' : 'orange'}>
                                                                {item.pdf_analysis.opinion}
                                                            </Badge>
                                                        )}
                                                        {item.pdf_analysis?.target_price && item.pdf_analysis.target_price !== 'N/A' && (
                                                            <Badge variant="outline" color="gray">
                                                                TP: {item.pdf_analysis.target_price}
                                                            </Badge>
                                                        )}
                                                    </Group>
                                                </div>
                                            </Group>

                                            {/* 6-line Summary Area */}
                                            <Paper bg="gray.1" p="sm" radius="sm" mb="sm">
                                                {item.body_summary ? (
                                                    <Text size="sm" c="dimmed" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }} lineClamp={6}>
                                                        {item.body_summary}
                                                    </Text>
                                                ) : (
                                                    <Text size="sm" c="dimmed">요약 내용이 없습니다.</Text>
                                                )}
                                            </Paper>

                                            <Group>
                                                <Button variant="light" size="xs" component="a" href={item.link} target="_blank">
                                                    본문 전체보기
                                                </Button>
                                                {item.pdf_link && (
                                                    <>
                                                        <Button variant="default" size="xs" component="a" href={item.pdf_link} target="_blank">
                                                            PDF 원문
                                                        </Button>
                                                        <Button
                                                            variant="filled"
                                                            color="violet"
                                                            size="xs"
                                                            leftSection={<IconRobot size={14} />}
                                                            onClick={() => {
                                                                setPdfItem(item);
                                                            }}
                                                        >
                                                            PDF 심층 분석
                                                        </Button>
                                                    </>
                                                )}
                                            </Group>
                                        </Card>
                                    ))}
                                </ScrollArea>
                            </Grid.Col>
                        </Grid>
                    )
                ) : (
                    <Text ta="center" c="dimmed" py="xl">데이터를 불러오는 중이거나 휴장일입니다.</Text>
                )}
            </Modal >

            {/* PDF Analysis Modal */}
            < Modal opened={!!pdfItem} onClose={() => setPdfItem(null)} title="AI 심층 리포트 분석" centered size="xl" >
                {pdfItem && (
                    <div className="flex flex-col gap-4">
                        <Group justify="space-between" align="center" style={{ borderBottom: '1px solid #eee', paddingBottom: 10 }}>
                            <div>
                                <Text fw={700} size="xl">{pdfItem.title}</Text>
                                <Text size="sm" c="dimmed">발행일: {pdfItem.date}</Text>
                            </div>
                            <Group>
                                <Badge size="lg" color={pdfItem.pdf_analysis?.opinion === 'BUY' ? 'red' : 'gray'}>
                                    {pdfItem.pdf_analysis?.opinion || 'N/A'}
                                </Badge>
                                <Badge size="lg" variant="outline">
                                    TP: {pdfItem.pdf_analysis?.target_price || 'N/A'}
                                </Badge>
                            </Group>
                        </Group>

                        <div className="flex gap-4" style={{ height: '60vh' }}>
                            {/* Left: Structured Analysis */}
                            <ScrollArea className="w-1/2 bg-gray-50 p-4 rounded-md">
                                <Text fw={700} size="lg" mb="md" c="violet.8">💡 핵심 투자 포인트</Text>
                                <Text style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }} size="sm">
                                    {pdfItem.pdf_analysis?.summary || "PDF 분석 데이터가 없습니다."}
                                </Text>
                            </ScrollArea>

                            {/* Right: Context & Tables */}
                            <ScrollArea className="w-1/2 bg-white p-4 rounded-md border border-gray-200">
                                <Text fw={700} size="lg" mb="md" c="teal.8">📊 핵심 재무 데이터 (Table)</Text>

                                {/* PDF Tables (New) */}
                                {pdfItem.pdf_analysis?.tables && pdfItem.pdf_analysis.tables.length > 0 ? (
                                    <div className="flex flex-col gap-4 mb-6">
                                        {pdfItem.pdf_analysis.tables.map((table: string, i: number) => (
                                            <Paper key={i} withBorder p="xs" bg="gray.1">
                                                <Text size="xs" fw={700} mb={1} c="dimmed">Table {i + 1}</Text>
                                                <ScrollArea>
                                                    <div style={{ whiteSpace: 'pre', fontFamily: 'monospace', fontSize: 11, lineHeight: 1.2 }}>
                                                        {table}
                                                    </div>
                                                </ScrollArea>
                                            </Paper>
                                        ))}
                                    </div>
                                ) : (
                                    <Text size="sm" c="dimmed" mb="md">PDF에서 추출된 표가 없습니다.</Text>
                                )}

                                <Divider my="sm" />

                                <Paper withBorder p="sm" mb="md" bg="blue.0">
                                    <Text size="xs" fw={700} c="blue.8" mb={1}>웹 게시글 요약 (Cross-Check)</Text>
                                    <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{pdfItem.body_summary || "웹 요약 없음"}</Text>
                                </Paper>

                                <Text fw={700} size="sm" mb="xs">📄 원문 발췌 (Snippet)</Text>
                                <Paper withBorder p="sm" bg="gray.0">
                                    <Text size="xs" style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace' }}>
                                        {pdfItem.pdf_analysis?.raw_text_snippet || "원문 텍스트 없음"}
                                    </Text>
                                </Paper>
                            </ScrollArea>
                        </div>

                        <Group justify="flex-end" mt="md">
                            <Button component="a" href={pdfItem.pdf_link} target="_blank" variant="default">
                                PDF 원본 열기
                            </Button>
                            <Button onClick={() => setPdfItem(null)} color="gray">닫기</Button>
                        </Group>
                    </div>
                )}
            </Modal >
        </AppShell >
    );
}
