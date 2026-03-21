'use client';

import React, { useState, useEffect } from 'react';
import { AppShell, Burger, Group, Title, Button, Table, Text, Badge, Card, Modal, useMantineTheme, ScrollArea, Tabs, PasswordInput, Paper, UnstyledButton, Center, Tooltip, Popover, Grid, Flex, SegmentedControl, Divider, ActionIcon, Checkbox } from '@mantine/core';
import { useDisclosure, useMediaQuery } from '@mantine/hooks';
import { IconRefresh, IconRobot, IconNews, IconCheck, IconSelector, IconChevronUp, IconChevronDown, IconSettings, IconCoin, IconCopy } from '@tabler/icons-react';
import QuickOrderModal from '../components/QuickOrderModal';
import { clsx } from 'clsx';
import { signOut } from 'next-auth/react';

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
    consecutive_days?: number; // [New] Unlimited consecutive count
    foreign_change_rate?: number; // [New]
    is_consecutive?: boolean; // Legacy fallback
    [key: string]: any; // Index signature for sorting
};

type FiveDayStock = {
    code: string;
    name: string;
    market: string;
    price: string | number;
    change_rate: string;
    daily_change_rate?: number; // New field
    prev_close?: number; // New field
    period_change_rate?: number;
    consecutive_days: number;
    total_posts: number;
    avg_posts: number;
    std_dev: number;
    sparkline: number[];
    sparkline_price: number[];
    sparkline_posts: number[];
    price_start: number;
    trend_stats: { min: number; max: number; avg: number; }; // Legacy (Change Rate)
    price_stats?: { min: number; max: number; avg: number; }; // New (Price Value)
    post_stats?: { min: number; max: number; avg: number; }; // New (Post Value)
    [key: string]: any;
};

const Sparkline = ({ data }: { data: number[] }) => {
    if (!data || data.length === 0) return null;
    const width = 200; // Increased width for better visibility
    const height = 30;

    const dataMin = Math.min(...data);
    const dataMax = Math.max(...data);

    let min = dataMin;
    let max = dataMax;

    // Handle flat line case
    if (min === max) {
        min -= 1;
        max += 1;
    }

    const range = max - min;

    // Scale points
    const points = data.map((val, idx) => {
        const x = (idx / (data.length - 1)) * width;
        const y = height - ((val - min) / range) * height;
        return x + ',' + y;
    }).join(' ');

    return (
        <Group gap='xs' style={{ width: width + 60 }}>
            <Text size='xs' c='dimmed' style={{ minWidth: 30, textAlign: 'right' }}>
                {data[0].toLocaleString()}
            </Text>
            <svg width={width} height={height} style={{ overflow: 'visible' }}>
                <polyline
                    fill='none'
                    stroke={data[data.length - 1] >= data[0] ? 'red' : 'blue'}
                    strokeWidth='2'
                    points={points}
                />
                {min < 0 && max > 0 && (
                    <line
                        x1='0'
                        y1={height - ((0 - min) / range) * height}
                        x2={width}
                        y2={height - ((0 - min) / range) * height}
                        stroke='#ddd'
                        strokeDasharray='2'
                    />
                )}
            </svg>
            <Text size='xs' fw={700} c={data[data.length - 1] >= data[0] ? 'red' : 'blue'} style={{ minWidth: 30 }}>
                {data[data.length - 1].toLocaleString()}
            </Text>
        </Group>
    );
};

const REPO_OWNER = 'hoonnamkoong';
const REPO_NAME = 'stockbot';
const WORKFLOW_ID = 'scraper.yml';

export default function Home() {
    const [opened, { toggle }] = useDisclosure();
    const [stocks, setStocks] = useState([]);
    const [fiveDayData, setFiveDayData] = useState([]);
    const [threeDayData, setThreeDayData] = useState([]);
    const [loading, setLoading] = useState(false);
    const [lastUpdated, setLastUpdated] = useState('');
    const [activeTab, setActiveTab] = useState('ALL');
    const [viewMode, setViewMode] = useState('table');
    const [sortConfig, setSortConfig] = useState({ key: 'recent_posts_count', direction: 'desc' });
    const [controlOpened, { open: openControl, close: closeControl }] = useDisclosure(false);
    const [githubToken, setGithubToken] = useState('');
    const [forceRun, setForceRun] = useState(false);
    const [workflowStatus, setWorkflowStatus] = useState('idle');
    const [workflowLogs, setWorkflowLogs] = useState([]);
    const theme = useMantineTheme();
    const isMobile = useMediaQuery('(max-width: ' + theme.breakpoints.sm + ')');
    const [reports, setReports] = useState([]);
    const [versionInfo, setVersionInfo] = useState(null);
    const [quickOrderOpen, setQuickOrderOpen] = useState(false);
    const [selectedQuickStock, setSelectedQuickStock] = useState({ code: '', name: '' });
    const handleCopyAndOpen = (code: string, name: string = '') => {
        navigator.clipboard.writeText(code);
        setSelectedQuickStock({ code, name: name || code });
        setQuickOrderOpen(true);
    };
    const openQuickOrder = (stock: any) => {
        setSelectedQuickStock({ code: stock.code, name: stock.name });
        setQuickOrderOpen(true);
    };
    const [timeSlot, setTimeSlot] = useState('latest');
    const [timeSlots, setTimeSlots] = useState([
        { label: 'Live 실시간 (Live)', value: 'latest' },
        { label: '10:00', value: '1000' },
        { label: '13:00', value: '1300' },
        { label: '15:00 (마감)', value: '1500' },
    ]);
    useEffect(() => {
        if (reports.length > 0) {
            const newSlots = [
                { label: 'Live 실시간 (Live)', value: 'latest' },
                { label: '10:00', value: '1000' },
                { label: '13:00', value: '1300' },
                { label: '15:00 (마감)', value: '1500' },
            ];
            const parseReportDate = (dateStr: string) => {
                try {
                    const timePart = dateStr.split(' ')[1];
                    const [hour] = timePart.split(':').map(Number);
                    return { hour, timeStr: timePart };
                } catch (e) { return { hour: -1, timeStr: '' }; }
            };
            const slot10 = reports.find(r => {
                const { hour } = parseReportDate(r.date);
                return hour >= 9 && hour <= 10;
            });
            if (slot10) newSlots[1].label = slot10.date.split(' ')[1];
            const slot13 = reports.find(r => {
                const { hour } = parseReportDate(r.date);
                return hour >= 11 && hour <= 13;
            });
            if (slot13) newSlots[2].label = slot13.date.split(' ')[1];
            const slot15 = reports.find(r => {
                const { hour } = parseReportDate(r.date);
                return hour >= 14;
            });
            if (slot15) newSlots[3].label = slot15.date.split(' ')[1];
            setTimeSlots(newSlots);
        }
    }, [reports]);
    useEffect(() => {
        fetchData(timeSlot);
        fetchVersion();
        const storedToken = localStorage.getItem('github_pat');
        if (storedToken) setGithubToken(storedToken);
    }, [timeSlot]);
    const fetchVersion = async () => {
        try {
            const res = await fetch('/api/version');
            if (res.ok) {
                const data = await res.json();
                setVersionInfo(data);
            }
        } catch (e) { console.error('Failed to fetch version:', e); }
    };
    const [systemLogs, setSystemLogs] = useState([]);
    const addSystemLog = (msg) => { setSystemLogs(prev => ['[' + new Date().toLocaleTimeString() + '] ' + msg, ...prev]); };
    const fetchData = async (slot = 'latest') => {
        setLoading(true);
        addSystemLog('데이터 새로고침 시작...');
        try {
            const timeMap = new Date().getTime();
            let filename = 'latest_stocks.json';
            if (slot !== 'latest') filename = 'stocks_' + slot + '.json';
            const stockUrl = 'https://raw.githubusercontent.com/' + REPO_OWNER + '/' + REPO_NAME + '/db-data/data/' + filename + '?t=' + timeMap;
            const resStocks = await fetch(stockUrl, { cache: 'no-store' });
            if (resStocks.ok) {
                const rawText = await resStocks.text();
                const rawData = JSON.parse(rawText.replace(/NaN/g, '0').replace(/Infinity/g, '0').replace(/-Infinity/g, '0'));
                const mappedData = rawData.map((item) => ({
                    ...item,
                    market: item.market || item['시장'] || item['시장구분'],
                    code: item.code,
                    name: item.name || item['종목명'],
                    price: item.price || item['현재가'],
                    current_price: item.price || item['현재가'],
                    prev_close: item.prev_close || item['어제_종가'] || item['전일종가'],
                    change_rate: item.change_rate || item['등락률'],
                    recent_posts_count: item.recent_posts_count || item['게시글수'] || item['당일_게시글수'] || item['당일 게시글수'],
                    foreign_rate: item.foreign_rate || item['외인소진율'] || item['현재_외국인비중'],
                    prev_foreign_rate: item.prev_foreign_rate || item['전일_외국인비중'] || item['어제_외국인비중'],
                    posts_summary: item.posts_summary || item['게시물_요약'],
                    sentiment: item.sentiment || item['감정분석'],
                    top_keywords: item.top_keywords || item['Top_Keyword'] || item['Top_Keywords'],
                    is_last_captured: item.is_last_captured || item['연속_등록'],
                    consecutive_days: item.consecutive_days || (item['연속_등록'] === true ? 2 : 1),
                    foreign_change_rate: item.foreign_change_rate || item['외국인_변화'] || 0,
                    latest_post: item.latest_posts && item.latest_posts.length > 0 ? item.latest_posts[0].title : (item['latest_post'] || ''),
                }));
                setStocks(mappedData);
            }
        } catch (e) { console.error(e); }
        setLoading(false);
    };

    const runScraper = async () => {
        if (!githubToken) {
            alert('GitHub Personal Access Token (PAT)을 먼저 입력해주세요.');
            return;
        }
        localStorage.setItem('github_pat', githubToken);
        setWorkflowStatus('running');
        setWorkflowLogs([]);
        addLog('워크플로우 실행 요청 중...');

        try {
            const res = await fetch('https://api.github.com/repos/' + REPO_OWNER + '/' + REPO_NAME + '/actions/workflows/' + WORKFLOW_ID + '/dispatches', {
                method: 'POST',
                headers: {
                    'Authorization': 'Bearer ' + githubToken,
                    'Accept': 'application/vnd.github.v3+json',
                },
                body: JSON.stringify({ 
                    ref: 'main',
                    inputs: {
                        force_run: forceRun.toString()
                    }
                })
            });

            if (res.ok) {
                addLog('요청 전송 성공! 실행 대기 중...');
                addLog('(GitHub Actions가 켜질 때까지 약 10~20초 소요됩니다)');
                monitorWorkflow();
            } else {
                addLog('요청 실패: ' + res.status + ' ' + res.statusText);
                setWorkflowStatus('error');
            }
        } catch (e) {
            addLog('에러 발생: ' + e.message);
            setWorkflowStatus('error');
        }
    };

    const monitorWorkflow = async () => {
        let attempts = 0;
        const interval = setInterval(async () => {
            attempts++;
            if (attempts > 7200) {
                clearInterval(interval);
                addLog('모니터링 자동 종료 (10시간 경과)');
                setWorkflowStatus('idle');
                return;
            }

            try {
                const res = await fetch('https://api.github.com/repos/' + REPO_OWNER + '/' + REPO_NAME + '/actions/runs?per_page=1', {
                    headers: { 'Authorization': 'Bearer ' + githubToken }
                });
                if (!res.ok) return;

                const data = await res.json();
                if (data.workflow_runs && data.workflow_runs.length > 0) {
                    const run = data.workflow_runs[0];
                    addLog('상태: ' + run.status + ' (' + (run.conclusion || 'Running') + ') - ' + new Date().toLocaleTimeString());

                    if (run.status === 'completed') {
                        clearInterval(interval);
                        addLog(run.conclusion === 'success' ? '실행 성공! 데이터를 갱신합니다.' : '실행 실패. Actions 탭을 확인하세요.');
                        setWorkflowStatus(run.conclusion === 'success' ? 'success' : 'error');
                        if (run.conclusion === 'success') setTimeout(fetchData, 3000);
                    }
                }
            } catch (e) { console.error(e); }
        }, 5000);
    };

    const addLog = (msg) => { setWorkflowLogs(prev => [...prev, msg]); };

    const handleSort = (key) => {
        let direction = 'asc';
        if (sortConfig.key === key && sortConfig.direction === 'desc') direction = 'asc';
        else if (sortConfig.key === key && sortConfig.direction === 'asc') direction = 'desc';
        else if (['recent_posts_count', 'consecutive_days', 'total_posts', 'change_rate'].includes(key)) direction = 'desc';
        setSortConfig({ key, direction });
    };

    const sortedStocks = [...stocks].filter(s => activeTab === 'ALL' ? true : s.market === activeTab).sort((a, b) => {
        if (!sortConfig.key) return 0;
        let valA = a[sortConfig.key];
        let valB = b[sortConfig.key];
        const parseValue = (v) => {
            if (typeof v === 'string') {
                const cleaned = v.replace(/,/g, '').replace('%', '');
                if (!isNaN(Number(cleaned)) && cleaned !== '') return Number(cleaned);
                return v.toLowerCase();
            }
            return v;
        };
        const parsedA = parseValue(valA), parsedB = parseValue(valB);
        if (parsedA < parsedB) return sortConfig.direction === 'asc' ? -1 : 1;
        if (parsedA > parsedB) return sortConfig.direction === 'asc' ? 1 : -1;
        return 0;
    });
    const sortedFiveDayData = [...fiveDayData].sort((a, b) => {
        if (!sortConfig.key) return 0;
        const key = sortConfig.key;
        let valA = a[key], valB = b[key];
        const parseValue = (v) => {
            if (typeof v === 'string') {
                const cleaned = v.replace(/,/g, '').replace('%', '');
                if (!isNaN(Number(cleaned)) && cleaned !== '') return Number(cleaned);
                return v.toLowerCase();
            }
            return v;
        };
        valA = parseValue(valA); valB = parseValue(valB);
        if (valA < valB) return sortConfig.direction === 'asc' ? -1 : 1;
        if (valA > valB) return sortConfig.direction === 'asc' ? 1 : -1;
        return 0;
    });

    const sortedThreeDayData = [...threeDayData].sort((a, b) => {
        if (!sortConfig.key) return 0;
        const key = sortConfig.key;
        let valA = a[key], valB = b[key];
        const parseValue = (v) => {
            if (typeof v === 'string') {
                const cleaned = v.replace(/,/g, '').replace('%', '');
                if (!isNaN(Number(cleaned)) && cleaned !== '') return Number(cleaned);
                return v.toLowerCase();
            }
            return v;
        };
        const parsedA = parseValue(valA), parsedB = parseValue(valB);
        if (parsedA < parsedB) return sortConfig.direction === 'asc' ? -1 : 1;
        if (parsedA > parsedB) return sortConfig.direction === 'asc' ? 1 : -1;
        return 0;
    });

    const handleResearchClick = (key) => {
        const urls = {
            invest: 'https://finance.naver.com/research/market_info_list.naver',
            company: 'https://finance.naver.com/research/company_list.naver',
            industry: 'https://finance.naver.com/research/industry_list.naver',
            economy: 'https://finance.naver.com/research/economy_list.naver'
        };
        const target = urls[key];
        if (target) window.open(target, '_blank');
    };

    const ThSort = ({ children, sortKey }) => {
        const active = sortConfig.key === sortKey;
        const Icon = sortConfig.direction === 'asc' ? IconChevronUp : IconChevronDown;
        return (
            <Table.Th onClick={() => handleSort(sortKey)} style={{ cursor: 'pointer' }}>
                <Group justify='space-between' wrap='nowrap'>
                    <Text fw={700} size='sm'>{children}</Text>
                    {active ? <Icon size={14} /> : <IconSelector size={14} style={{ opacity: 0.3 }} />}
                </Group>
            </Table.Th>
        );
    };

    return (
        <AppShell
            header={{ height: 60 }}
            navbar={{ width: 300, breakpoint: 'sm', collapsed: { mobile: !opened } }}
            padding='md'
        >
            <QuickOrderModal
                opened={quickOrderOpen}
                onClose={() => setQuickOrderOpen(false)}
                initialCode={selectedQuickStock.code}
                initialName={selectedQuickStock.name}
            />
            <AppShell.Header>
                <Group h='100%' px='md'>
                    <Burger opened={opened} onClick={toggle} hiddenFrom='sm' size='sm' />
                    <IconRobot size={isMobile ? 24 : 30} color='#228be6' />
                    <Title order={3} size={isMobile ? 'h5' : 'h3'}>
                        {isMobile
                            ? 'StockBot ' + (versionInfo?.version || 'v28')
                            : 'StockBot ' + (versionInfo?.version || 'v28') + ' (Deployed ' + (versionInfo?.timestamp ? new Date(versionInfo.timestamp).toLocaleString() : 'N/A') + ' KST)'
                        }
                    </Title>
                    <Group ml='auto' gap={isMobile ? 'xs' : 'md'}>
                        <Button variant='light' color='violet' onClick={openControl} leftSection={<IconSettings size={16} />}>
                            스크래퍼 제어
                        </Button>
                        <Button variant='default' onClick={() => fetchData()} leftSection={<IconRefresh size={16} />}>
                            데이터 갱신
                        </Button>
                    </Group>
                </Group>
            </AppShell.Header>

            <AppShell.Navbar p='md'>
                <Button fullWidth color='orange' variant='filled' mb='md' leftSection={<IconCoin size={20} />} onClick={() => window.location.href = '/trade'} size='md'>
                    Trading Dashboard
                </Button>
                <Text fw={700} mb='sm'>Research Reports</Text>
                {['invest', 'company', 'industry', 'economy'].map((key) => (
                    <Button key={key} fullWidth variant='light' mb='xs' justify='space-between' onClick={() => handleResearchClick(key)}>
                        {key}
                    </Button>
                ))}
            </AppShell.Navbar>

            <AppShell.Main>
                <Tabs value={activeTab} onChange={setActiveTab} mb='md'>
                    <Tabs.List>
                        <Tabs.Tab value='ALL'>전체</Tabs.Tab>
                        <Tabs.Tab value='KOSPI'>KOSPI</Tabs.Tab>
                        <Tabs.Tab value='KOSDAQ'>KOSDAQ</Tabs.Tab>
                        <Tabs.Tab value='5DAYS'>5일 누적</Tabs.Tab>
                        <Tabs.Tab value='3DAYS'>3일 누적</Tabs.Tab>
                    </Tabs.List>
                </Tabs>

                <Table striped highlightOnHover>
                    <Table.Thead>
                        <Table.Tr>
                            <ThSort sortKey='name'>종목명</ThSort>
                            <ThSort sortKey='price'>현재가</ThSort>
                            <ThSort sortKey='change_rate'>등락률</ThSort>
                            <ThSort sortKey='recent_posts_count'>게시글</ThSort>
                        </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                        {sortedStocks.map(stock => (
                            <Table.Tr key={stock.code} onClick={() => handleCopyAndOpen(stock.code, stock.name)} style={{ cursor: 'pointer' }}>
                                <Table.Td>{stock.name}</Table.Td>
                                <Table.Td>{stock.price}</Table.Td>
                                <Table.Td>{stock.change_rate}</Table.Td>
                                <Table.Td>{stock.recent_posts_count}</Table.Td>
                            </Table.Tr>
                        ))}
                    </Table.Tbody>
                </Table>

                <Modal opened={controlOpened} onClose={closeControl} title='Scraper Control Center' centered>
                    <PasswordInput
                        label='GitHub Personal Access Token (PAT)'
                        placeholder='ghp_...'
                        value={githubToken}
                        onChange={(event) => setGithubToken(event.currentTarget.value)}
                        mb='md'
                    />
                    <Checkbox
                        label='Bypass market holiday check (Force execution)'
                        checked={forceRun}
                        onChange={(event) => setForceRun(event.currentTarget.checked)}
                        mb='md'
                        color='orange'
                    />
                    <Button fullWidth onClick={runScraper} loading={workflowStatus === 'running'} color='teal'>
                        지금 즉시 실행 (RUN NOW)
                    </Button>
                    <Paper withBorder p='sm' mt='md' bg='gray.1'>
                        <Text size='sm' fw={700} mb='xs'>실시간 상태 로그:</Text>
                        <ScrollArea h={150}>
                            {workflowLogs.map((log, i) => <Text key={i} size='xs'>{log}</Text>)}
                        </ScrollArea>
                    </Paper>
                </Modal>
            </AppShell.Main>
        </AppShell>
    );
}
