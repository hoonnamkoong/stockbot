'use client';

import { useState, useEffect } from 'react';
import { AppShell, Burger, Group, Title, Button, Table, Text, Badge, Card, Modal, useMantineTheme, ScrollArea, Tabs, PasswordInput, Paper } from '@mantine/core';
import { useDisclosure, useMediaQuery } from '@mantine/hooks';
import { IconRefresh, IconRobot, IconNews } from '@tabler/icons-react';
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
    summary: string;
    sentiment: string;
    is_consecutive: boolean;
};

// --- Constants ---
const REPO_OWNER = "hoonnamkoong";
const REPO_NAME = "stockbot";
// Important: File name of workflow must match exactly.
const WORKFLOW_ID = "daily_scrape.yml";

export default function Home() {
    const [opened, { toggle }] = useDisclosure();
    const [stocks, setStocks] = useState<Stock[]>([]);
    const [research, setResearch] = useState<any>(null);
    const [loading, setLoading] = useState(false);
    const [lastUpdated, setLastUpdated] = useState<string>('');
    const [activeTab, setActiveTab] = useState<string | null>('ALL');

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

    const fetchData = async () => {
        setLoading(true);
        try {
            const timeMap = new Date().getTime();
            // Fetch Stocks
            const resStocks = await fetch(`https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/main/data/latest_stocks.json?t=${timeMap}`);
            if (resStocks.ok) {
                const data = await resStocks.json();
                setStocks(data);
            }
            // Fetch Research
            const resResearch = await fetch(`https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/main/data/latest_research.json?t=${timeMap}`);
            if (resResearch.ok) {
                const data = await resResearch.json();
                setResearch(data);
            }
            setLastUpdated(new Date().toLocaleTimeString());
        } catch (e) {
            console.error(e);
        }
        setLoading(false);
    };

    // --- Scraper Trigger Logic ---
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
            if (attempts > 30) { // Poll for ~2.5 mins
                clearInterval(interval);
                addLog("⚠️ 모니터링 시간 초과 (수동으로 확인해주세요)");
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
                            setTimeout(fetchData, 3000); // Wait a bit for raw CDN update
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


    // --- Sort Logic for Table ---
    const [sortedStocks, setSortedStocks] = useState<Stock[]>([]);

    // Default sorting / filtering state
    useEffect(() => {
        let filtered = activeTab === 'ALL'
            ? stocks
            : stocks.filter(s => s.market === activeTab);

        // Default sort: Count Today DESC
        filtered.sort((a, b) => b.count_today - a.count_today);
        setSortedStocks(filtered);
    }, [stocks, activeTab]);

    // Research Modal Logic
    const handleResearchClick = (key: string) => {
        setSelectedResearchCategory(key);
        openResearchModal();
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
                    <Title order={3}>StockBot V3.0</Title>
                    <Group ml="auto">
                        <Button variant="light" color="violet" onClick={openControl} leftSection={<IconRefresh size={16} />}>
                            Scraper Control
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
                        <Table striped highlightOnHover withTableBorder>
                            <Table.Thead>
                                <Table.Tr>
                                    <Table.Th style={{ position: 'sticky', left: 0, background: 'var(--mantine-color-body)', zIndex: 1 }}>종목명</Table.Th>
                                    <Table.Th>현재가</Table.Th>
                                    <Table.Th>등락률</Table.Th>
                                    <Table.Th>토론글(오늘)</Table.Th>
                                    <Table.Th>거래량</Table.Th>
                                    <Table.Th>외인비율</Table.Th>
                                    <Table.Th>감성분석</Table.Th>
                                    <Table.Th>요약</Table.Th>
                                </Table.Tr>
                            </Table.Thead>
                            <Table.Tbody>
                                {sortedStocks.map((stock) => (
                                    <Table.Tr key={stock.code}>
                                        <Table.Td style={{ position: 'sticky', left: 0, background: 'var(--mantine-color-body)', fontWeight: 'bold' }}>
                                            {stock.name} ({stock.code})
                                        </Table.Td>
                                        <Table.Td>{stock.current_price}</Table.Td>
                                        <Table.Td style={{ color: stock.change_rate.includes('+') ? 'red' : 'blue' }}>{stock.change_rate}</Table.Td>
                                        <Table.Td>{stock.count_today}</Table.Td>
                                        <Table.Td>{stock.volume || '-'}</Table.Td>
                                        <Table.Td>{stock.foreign_ratio_today}</Table.Td>
                                        <Table.Td>{stock.sentiment}</Table.Td>
                                        <Table.Td style={{ maxWidth: 300 }}><Text truncate>{stock.summary}</Text></Table.Td>
                                    </Table.Tr>
                                ))}
                            </Table.Tbody>
                        </Table>
                    </ScrollArea>
                )}
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
            <Modal opened={researchModalOpened} onClose={closeResearchModal} title="리포트 목록 (오늘)" centered size="lg">
                <ScrollArea h={400}>
                    {selectedResearchCategory && research?.[selectedResearchCategory]?.items?.length > 0 ? (
                        research[selectedResearchCategory].items.map((item: any, idx: number) => (
                            <Paper key={idx} withBorder p="sm" mb="sm">
                                <Text fw={700} size="sm">{item.title}</Text>
                                <Group mt="xs">
                                    <Text size="xs" c="dimmed">{item.date}</Text>
                                    <Button component="a" href={item.link} target="_blank" size="compact-xs" variant="light">Naver View</Button>
                                    {item.pdf_link && <Button component="a" href={item.pdf_link} target="_blank" size="compact-xs" color="red" variant="outline">PDF</Button>}
                                    <Button size="compact-xs" color="grape" variant="subtle" onClick={() => alert("AI 요약 기능은 준비 중입니다.")}>AI 요약</Button>
                                </Group>
                            </Paper>
                        ))
                    ) : (
                        <Text align="center" c="dimmed" py="xl">오늘 올라온 리포트가 없습니다.</Text>
                    )}
                </ScrollArea>
            </Modal>
        </AppShell>
    );
}
