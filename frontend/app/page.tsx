'use client';

import { useState, useEffect } from 'react';
import { AppShell, Burger, Group, Title, Button, Table, Text, Badge, Card, Modal, useMantineTheme, ScrollArea, Tabs, PasswordInput, Paper, UnstyledButton, Center, Tooltip, Popover } from '@mantine/core';
import { useDisclosure, useMediaQuery } from '@mantine/hooks';
import { IconRefresh, IconRobot, IconNews, IconCheck, IconSelector, IconChevronUp, IconChevronDown } from '@tabler/icons-react';
import { clsx } from 'clsx';

// --- Types ---
type Stock = {
    market: string;
    code: string;
    name: string;
    current_price: string;
    yesterday_close?: string;
    change_rate: string;
    volume?: string;
    count_today: number;
    foreign_ratio_today: string;
    foreign_ratio_yesterday?: string;
    summary: string;
    sentiment: string;
    is_consecutive: boolean;
    [key: string]: any; // Index signature for sorting
};

// --- Constants ---
const REPO_OWNER = "hoonnamkoong";
const REPO_NAME = "stockbot";
const WORKFLOW_ID = "daily_scrape.yml";

export default function Home() {
    const [opened, { toggle }] = useDisclosure();
    const [stocks, setStocks] = useState<Stock[]>([]);
    const [research, setResearch] = useState<any>(null);
    const [loading, setLoading] = useState(false);
    const [lastUpdated, setLastUpdated] = useState<string>('');
    const [activeTab, setActiveTab] = useState<string | null>('ALL');

    // Sorting State
    const [sortConfig, setSortConfig] = useState<{ key: string | null; direction: 'asc' | 'desc' }>({ key: 'count_today', direction: 'desc' });

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

            setLastUpdated(new Date().toLocaleTimeString());
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
                    <IconRobot size={30} color="#228be6" />
                    <Title order={3}>StockBot V3.2 (Sorting)</Title>
                    <Group ml="auto">
                        <Button variant="light" color="violet" onClick={openControl} leftSection={<IconRefresh size={16} />}>
                            Control
                        </Button>
                        <Button variant="subtle" size="xs" onClick={fetchData} leftSection={<IconRefresh size={14} />}>
                            Refresh
                        </Button>
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
            </AppShell.Navbar>

            <AppShell.Main>
                <Tabs value={activeTab} onChange={setActiveTab} mb="md">
                    <Tabs.List>
                        <Tabs.Tab value="ALL">전체 (ALL)</Tabs.Tab>
                        <Tabs.Tab value="KOSPI">KOSPI</Tabs.Tab>
                        <Tabs.Tab value="KOSDAQ">KOSDAQ</Tabs.Tab>
                    </Tabs.List>
                </Tabs>

                {isMobile ? (
                    <div className="flex flex-col gap-3">
                        {sortedStocks.map((stock) => (
                            <Card key={stock.code} shadow="sm" padding="lg" radius="md" withBorder>
                                <Group justify="space-between" mb="xs">
                                    <Text fw={500}>{stock.name}</Text>
                                    <Badge color={stock.change_rate.includes('+') ? 'red' : 'blue'}>{stock.change_rate}</Badge>
                                </Group>
                                <Group gap="xs" mb="xs">
                                    <Text size="sm" c="dimmed">Posts: <b>{stock.count_today}</b></Text>
                                    <Text size="sm" c="dimmed">For.: {stock.foreign_ratio_today}</Text>
                                </Group>
                                <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{stock.summary}</Text>
                            </Card>
                        ))}
                    </div>
                ) : (
                    <ScrollArea>
                        {!isMobile ? (
                            <Table striped highlightOnHover withTableBorder>
                                <Table.Thead>
                                    <Table.Tr>
                                        {/* Headers */}
                                        <Table.Th onClick={() => handleSort('name')} style={{ cursor: 'pointer' }}>종목명 (코드) {sortConfig?.key === 'name' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}</Table.Th>
                                        <Table.Th onClick={() => handleSort('current_price')} style={{ cursor: 'pointer' }}>현재가 {sortConfig?.key === 'current_price' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}</Table.Th>
                                        <Table.Th>어제가</Table.Th>
                                        <Table.Th onClick={() => handleSort('change_rate')} style={{ cursor: 'pointer' }}>등락률 {sortConfig?.key === 'change_rate' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}</Table.Th>
                                        <Table.Th onClick={() => handleSort('volume')} style={{ cursor: 'pointer' }}>거래량 {sortConfig?.key === 'volume' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}</Table.Th>
                                        <Table.Th onClick={() => handleSort('count_today')} style={{ cursor: 'pointer' }}>토론글 {sortConfig?.key === 'count_today' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}</Table.Th>
                                        <Table.Th>외인비(현)</Table.Th>
                                        <Table.Th>외인비(전)</Table.Th>
                                        <Table.Th>감성</Table.Th>
                                        <Table.Th>연속</Table.Th>
                                        <Table.Th>요약</Table.Th>
                                    </Table.Tr>
                                </Table.Thead>
                                <Table.Tbody>
                                    {sortedStocks.map((stock) => (
                                        <Table.Tr key={stock.code}>
                                            <Table.Td>
                                                <Text fw={700}>{stock.name}</Text>
                                                <Text size="xs" c="dimmed">{stock.code}</Text>
                                            </Table.Td>
                                            <Table.Td>{stock.current_price}</Table.Td>
                                            <Table.Td>{stock.yesterday_close}</Table.Td>
                                            <Table.Td style={{ color: stock.change_rate.includes('+') ? 'red' : 'blue' }}>{stock.change_rate}</Table.Td>
                                            <Table.Td>{stock.volume}</Table.Td>
                                            <Table.Td>{stock.count_today}</Table.Td>
                                            <Table.Td>{stock.foreign_ratio_today}</Table.Td>
                                            <Table.Td>{stock.foreign_ratio_yesterday}</Table.Td>
                                            <Table.Td>
                                                <Badge color={stock.sentiment === '긍정' ? 'green' : stock.sentiment === '부정' ? 'red' : 'gray'}>
                                                    {stock.sentiment}
                                                </Badge>
                                            </Table.Td>
                                            <Table.Td>{stock.is_consecutive ? <IconCheck size={16} color="green" /> : '-'}</Table.Td>
                                            <Table.Td style={{ maxWidth: 300 }}>
                                                <Tooltip label={stock.summary} multiline w={300} withArrow transitionProps={{ duration: 200 }}>
                                                    <Text truncate style={{ cursor: 'help' }}>{stock.summary}</Text>
                                                </Tooltip>
                                            </Table.Td>
                                        </Table.Tr>
                                    ))}
                                </Table.Tbody>
                            </Table>
                        ) : (
                            /* Mobile Card View */
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                {sortedStocks.map((stock) => (
                                    <Paper key={stock.code} shadow="xs" p="md" withBorder>
                                        <Group justify="space-between" mb="xs">
                                            <div>
                                                <Text fw={700} size="lg">{stock.name} <Text span size="xs" c="dimmed">({stock.code})</Text></Text>
                                            </div>
                                            <Badge color={stock.sentiment === '긍정' ? 'green' : stock.sentiment === '부정' ? 'red' : 'gray'}>
                                                {stock.sentiment}
                                            </Badge>
                                        </Group>

                                        <Group grow mb="xs">
                                            <div>
                                                <Text size="xs" c="dimmed">현재가</Text>
                                                <Text fw={700} size="lg" c={stock.change_rate.includes('+') ? 'red' : 'blue'}>
                                                    {stock.current_price} ({stock.change_rate})
                                                </Text>
                                            </div>
                                            <div style={{ textAlign: 'right' }}>
                                                <Text size="xs" c="dimmed">토론글</Text>
                                                <Text fw={700}>{stock.count_today}개</Text>
                                            </div>
                                        </Group>

                                        <Group gap="xl" mb="sm">
                                            <div>
                                                <Text size="xs" c="dimmed">거래량</Text>
                                                <Text size="sm">{stock.volume}</Text>
                                            </div>
                                            <div>
                                                <Text size="xs" c="dimmed">외인비</Text>
                                                <Text size="sm">{stock.foreign_ratio_today}</Text>
                                            </div>
                                            {stock.is_consecutive && <Badge variant="outline" color="green" leftSection={<IconCheck size={12} />}>연속 포착</Badge>}
                                        </Group>

                                        <Paper bg="gray.0" p="xs" radius="md">
                                            <Text size="xs" fw={700} mb={2}>🗣️ 토론 요약</Text>
                                            <Text size="sm" lineClamp={2}>{stock.summary}</Text>
                                        </Paper>
                                    </Paper>
                                ))}
                            </div>
                        )}
                    </ScrollArea>
                )}

                {/* DEBUG CONSOLE */}
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
            </AppShell.Main>

            {/* Scraper Control Modal */}
            <Modal opened={controlOpened} onClose={closeControl} title="스크래퍼 제어 센터 (Scraper Control)" centered>
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
            </Modal>

            {/* Research List Modal */}
            <Modal opened={researchModalOpened} onClose={closeResearchModal} title={`오늘의 리포트 (${selectedResearchCategory && research?.[selectedResearchCategory]?.today_count}건)`} centered size="xl">
                {selectedResearchCategory && research?.[selectedResearchCategory]?.items?.length > 0 ? (
                    <div style={{ display: 'flex', gap: '20px', flexDirection: isMobile ? 'column' : 'row' }}>
                        {/* LEFT: Overall Summary (Daily Briefing) */}
                        <Paper withBorder p="md" bg="blue.0" flex={1} style={{ height: 'fit-content' }}>
                            <Title order={4} mb="sm" c="blue.9">📢 오늘의 시장 브리핑</Title>
                            <Text size="sm" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }} fw={500}>
                                {research[selectedResearchCategory].summary}
                            </Text>
                            <Text size="xs" c="dimmed" mt="xl">
                                * AI가 오늘 발행된 리포트들의 핵심 내용(매수의견, 목표주가 등)을 종합하여 작성했습니다.
                            </Text>
                        </Paper>

                        {/* RIGHT: List with Visible Summary */}
                        <ScrollArea h={600} flex={1.5}>
                            {research[selectedResearchCategory].items.map((item: any, idx: number) => (
                                <Paper key={idx} withBorder p="md" mb="md" shadow="sm">
                                    <Group justify="space-between" mb="xs">
                                        <Text fw={700} size="md" style={{ flex: 1 }}>{item.title}</Text>
                                        <Badge size="sm" color="gray" variant="light">{item.date}</Badge>
                                    </Group>

                                    {/* Visible Body Summary (5 lines max) */}
                                    <Text size="sm" c="dimmed" lineClamp={5} mb="sm" style={{ lineHeight: 1.5 }}>
                                        {item.body_summary || "요약 내용이 없습니다."}
                                    </Text>

                                    <Group justify="flex-end">
                                        <Button component="a" href={item.link} target="_blank" size="xs" variant="default">
                                            본문 전체보기
                                        </Button>

                                        {item.pdf_analysis ? (
                                            <Button size="xs" color="blue" variant="light" onClick={() => setPdfItem(item)}>
                                                📄 PDF 심층 분석
                                            </Button>
                                        ) : (
                                            item.pdf_link && (
                                                <Button component="a" href={item.pdf_link} target="_blank" size="xs" color="red" variant="outline">
                                                    PDF 원문
                                                </Button>
                                            )
                                        )}
                                    </Group>
                                </Paper>
                            ))}
                        </ScrollArea>
                    </div>
                ) : (
                    <Text ta="center" c="dimmed" py="xl">데이터를 불러오는 중이거나 휴장일입니다.</Text>
                )}
            </Modal>

            {/* PDF Analysis Detail Modal */}
            <Modal opened={!!pdfItem} onClose={() => setPdfItem(null)} title="📄 리포트 심층 분석 (AI)" centered size="lg">
                {pdfItem && pdfItem.pdf_analysis && (
                    <ScrollArea h={500}>
                        <Group mb="md" grow>
                            <Paper withBorder p="sm" bg="gray.0">
                                <Text size="xs" c="dimmed" ta="center">투자의견</Text>
                                <Text fw={900} size="lg" ta="center" c={pdfItem.pdf_analysis.opinion === 'BUY' ? 'red' : 'gray'}>
                                    {pdfItem.pdf_analysis.opinion}
                                </Text>
                            </Paper>
                            <Paper withBorder p="sm" bg="gray.0">
                                <Text size="xs" c="dimmed" ta="center">목표주가</Text>
                                <Text fw={900} size="lg" ta="center">
                                    {pdfItem.pdf_analysis.target_price}
                                </Text>
                            </Paper>
                        </Group>

                        <Title order={5} mb="xs">💡 핵심 결론 & 투자 포인트</Title>
                        <Paper withBorder p="md" mb="xl">
                            <Text size="sm" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                                {pdfItem.pdf_analysis.summary}
                            </Text>
                        </Paper>
                    </ScrollArea>
                )}
            </Modal>
        </AppShell >
    );
}
