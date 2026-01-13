'use client';

import { useState, useEffect } from 'react';
import { AppShell, Burger, Group, Title, Button, Table, Text, Badge, Card, Modal, useMantineTheme, ScrollArea, Tabs, PasswordInput, Paper, UnstyledButton, Center, Tooltip, Popover, Grid, Flex, SegmentedControl, Divider, ActionIcon } from '@mantine/core';
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
    is_consecutive?: boolean; // Legacy fallback
    [key: string]: any; // Index signature for sorting
};

type FiveDayStock = {
    code: string;
    name: string;
    market: string;
    price: string | number;
    change_rate: string;
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
    const width = 100;
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
        return `${x},${y}`;
    }).join(' ');

    return (
        <svg width={width} height={height} style={{ overflow: 'visible' }}>
            <polyline
                fill="none"
                stroke={data[data.length - 1] >= data[0] ? 'red' : 'blue'}
                strokeWidth="2"
                points={points}
            />
            {/* Zero line only if within range */}
            {min < 0 && max > 0 && (
                <line
                    x1="0"
                    y1={height - ((0 - min) / range) * height}
                    x2={width}
                    y2={height - ((0 - min) / range) * height}
                    stroke="#ddd"
                    strokeDasharray="2"
                />
            )}
        </svg>
    );
};

// --- Constants ---
const REPO_OWNER = "hoonnamkoong";
const REPO_NAME = "stockbot";
const WORKFLOW_ID = "scraper.yml";

export default function Home() {
    const [opened, { toggle }] = useDisclosure();
    const [stocks, setStocks] = useState<Stock[]>([]);
    const [fiveDayData, setFiveDayData] = useState<FiveDayStock[]>([]);
    const [threeDayData, setThreeDayData] = useState<FiveDayStock[]>([]); // 3-Day State (Fixed duplicate)
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
    const [reports, setReports] = useState<any[]>([]);

    // Quick Order State
    const [quickOrderOpen, setQuickOrderOpen] = useState(false);
    const [selectedQuickStock, setSelectedQuickStock] = useState<{ code: string, name: string }>({ code: '', name: '' });

    const handleCopyAndOpen = (code: string) => {
        navigator.clipboard.writeText(code);

        // Context-aware notification
        const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);

        if (isMobile) {
            alert(`Code ${code} Copied!\n\nTrying to open KIS App...`);
            // Attempt generic scheme
            window.location.href = "neosmartaf://";
        } else {
            // Desktop: just notify
            // Using simple alert or console for now, or could use Mantine notification if available
            // But to avoid 'notifications' dependency if not present, simple alert for now
            alert(`Code ${code} Copied to clipboard!`);
        }
    };

    const openQuickOrder = (stock: any) => {
        setSelectedQuickStock({ code: stock.code, name: stock.name });
        setQuickOrderOpen(true);
    };

    // [User Request V7.3] Time Slot Filtering
    const [timeSlot, setTimeSlot] = useState<string>('latest');
    const [timeSlots, setTimeSlots] = useState([
        { label: '🔴 실시간 (Live)', value: 'latest' },
        { label: '🕙 10:00', value: '1000' },
        { label: '🕐 13:00', value: '1300' },
        { label: '🕒 15:00 (마감)', value: '1500' },
    ]);

    // Update Time Slots labels based on actual reports
    useEffect(() => {
        if (reports.length > 0) {
            const newSlots = [
                { label: '🔴 실시간 (Live)', value: 'latest' },
                { label: '🕙 10:00', value: '1000' },
                { label: '🕐 13:00', value: '1300' },
                { label: '🕒 15:00 (마감)', value: '1500' },
            ];

            const parseReportDate = (dateStr: string) => {
                try {
                    const timePart = dateStr.split(' ')[1]; // "2024-12-24 10:42" -> "10:42"
                    const [hour] = timePart.split(':').map(Number);
                    return { hour, timeStr: timePart };
                } catch (e) { return { hour: -1, timeStr: '' }; }
            };

            // Find latest report for each slot category
            // 10:00 Slot (09:00 - 10:59)
            const slot10 = reports.find(r => {
                const { hour } = parseReportDate(r.date);
                return hour >= 9 && hour <= 10;
            });
            if (slot10) newSlots[1].label = `🕙 ${slot10.date.split(' ')[1]}`;

            // 13:00 Slot (11:00 - 13:59) - Covers new 11:30 and 13:30 schedules
            const slot13 = reports.find(r => {
                const { hour } = parseReportDate(r.date);
                return hour >= 11 && hour <= 13;
            });
            if (slot13) newSlots[2].label = `🕐 ${slot13.date.split(' ')[1]}`;

            // 15:00 Slot (14:00+)
            const slot15 = reports.find(r => {
                const { hour } = parseReportDate(r.date);
                return hour >= 14;
            });
            if (slot15) newSlots[3].label = `🕒 ${slot15.date.split(' ')[1]}`;

            setTimeSlots(newSlots);
        }
    }, [reports]);

    useEffect(() => {
        fetchData(timeSlot);
        const storedToken = localStorage.getItem('github_pat');
        if (storedToken) setGithubToken(storedToken);
    }, [timeSlot]);

    const [systemLogs, setSystemLogs] = useState<string[]>([]);

    const addSystemLog = (msg: string) => {
        setSystemLogs(prev => [`[${new Date().toLocaleTimeString()}] ${msg}`, ...prev]);
    };

    const fetchData = async (slot: string = 'latest') => {
        setLoading(true);
        addSystemLog("🔄 데이터 새로고침 시작...");
        try {
            const timeMap = new Date().getTime();
            // Mapping slot to filename
            let filename = 'latest_stocks.json';
            if (slot !== 'latest') {
                filename = `stocks_${slot}.json`;
            }

            const stockUrl = `https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/main/data/${filename}?t=${timeMap}`;

            addSystemLog(`📡 Fetching Stocks: ${stockUrl}`);

            const resStocks = await fetch(stockUrl, { cache: 'no-store' });
            addSystemLog(`📩 Stocks Status: ${resStocks.status} ${resStocks.statusText}`);

            if (resStocks.ok) {
                const data = await resStocks.json();
                addSystemLog(`✅ Stocks Loaded: ${data.length} items`);
                setStocks(data);
            } else {
                if (slot !== 'latest') {
                    alert(`해당 시간대(${slot})의 데이터가 아직 없습니다.`);
                    setTimeSlot('latest'); // Revert logic handled by effect? No, manual revert safest.
                }
                const text = await resStocks.text();
                addSystemLog(`❌ Stocks Fetch Failed: ${text.slice(0, 100)}`);
            }

            // Fetch Research (Always latest for now, or match slot?) 
            // Keep latest for research as it's daily.
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

            // Fetch Reports Index
            try {
                const resReports = await fetch(`https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/main/data/reports.json?t=${timeMap}`, { cache: 'no-store' });
                if (resReports.ok) {
                    const data = await resReports.json();
                    setReports(data.slice(0, 5)); // Top 5
                }
            } catch (e) { console.error(e); }

            // Fetch 5-Day Analysis
            try {
                const res5 = await fetch(`https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/main/data/analysis_5days.json?t=${timeMap}`, { cache: 'no-store' });
                if (res5.ok) {
                    const data = await res5.json();
                    // Enforce consistency: Calculate registered days from sparkline data
                    const fixedData = data.map((item: any) => ({
                        ...item,
                        consecutive_days: item.sparkline_price ? item.sparkline_price.filter((p: number) => p > 0).length : item.consecutive_days
                    }));
                    setFiveDayData(fixedData);
                }
            } catch (e) { console.error(e); }

            // Fetch 3-Day Analysis
            try {
                const res3 = await fetch(`https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/main/data/analysis_3days.json?t=${timeMap}`, { cache: 'no-store' });
                if (res3.ok) {
                    const data = await res3.json();
                    // Enforce consistency here too
                    const fixedData = data.map((item: any) => ({
                        ...item,
                        consecutive_days: item.sparkline_price ? item.sparkline_price.filter((p: number) => p > 0).length : item.consecutive_days
                    }));
                    setThreeDayData(fixedData);
                }
            } catch (e) { console.error(e); }

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
        // Toggle direction if clicking same key, else default desc for numbers usually?
        // Let's stick to toggle.
        if (sortConfig.key === key && sortConfig.direction === 'desc') {
            direction = 'asc';
        } else if (sortConfig.key === key && sortConfig.direction === 'asc') {
            direction = 'desc';
        } else {
            // Default for new numeric keys -> desc
            if (['recent_posts_count', 'consecutive_days', 'total_posts', 'change_rate'].includes(key)) {
                direction = 'desc';
            }
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
        if (parsedA > parsedB) return sortConfig.direction === 'asc' ? 1 : -1;
        return 0;
    });

    const sortedFiveDayData = [...fiveDayData].sort((a, b) => {
        if (!sortConfig.key) return 0; // Default sort logic in backend (consecutive desc)
        // But if user clicks header...
        // If sortConfig matches a 5-day key, sort it.

        const key = sortConfig.key;
        let valA = a[key];
        let valB = b[key];

        const parseValue = (v: any) => {
            if (typeof v === 'string') {
                const cleaned = v.replace(/,/g, '').replace('%', '');
                if (!isNaN(Number(cleaned)) && cleaned !== '') return Number(cleaned);
                return v.toLowerCase();
            }
            return v;
        };

        valA = parseValue(valA);
        valB = parseValue(valB);

        if (valA < valB) return sortConfig.direction === 'asc' ? -1 : 1;
        if (valA > valB) return sortConfig.direction === 'asc' ? 1 : -1;
        return 0;
    });

    const sortedThreeDayData = [...threeDayData].sort((a, b) => {
        if (!sortConfig.key) return 0;
        const key = sortConfig.key;
        let valA = a[key];
        let valB = b[key];

        const parseValue = (v: any) => {
            if (typeof v === 'string') {
                const cleaned = v.replace(/,/g, '').replace('%', '');
                if (!isNaN(Number(cleaned)) && cleaned !== '') return Number(cleaned);
                return v.toLowerCase();
            }
            return v;
        };

        const parsedA = parseValue(valA);
        const parsedB = parseValue(valB);

        if (parsedA < parsedB) return sortConfig.direction === 'asc' ? -1 : 1;
        if (parsedA > parsedB) return sortConfig.direction === 'asc' ? 1 : -1;
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
            <QuickOrderModal
                opened={quickOrderOpen}
                onClose={() => setQuickOrderOpen(false)}
                initialCode={selectedQuickStock.code}
                initialName={selectedQuickStock.name}
            />
            <AppShell.Header>
                <Group h="100%" px="md">
                    <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
                    <IconRobot size={isMobile ? 24 : 30} color="#228be6" />
                    <Title order={3} size={isMobile ? 'h5' : 'h3'}>
                        {isMobile ? 'StockBot v2026.01.06' : 'StockBot v2026.01.06 (Deployed 16:44 KST)'}
                    </Title>
                    <Group ml="auto" gap={isMobile ? 'xs' : 'md'}>
                        {isMobile ? (
                            /* Mobile: Icon Only Buttons */
                            <>
                                <ActionIcon variant="light" color="violet" size="lg" onClick={openControl}>
                                    <IconRefresh size={18} />
                                </ActionIcon>
                                <ActionIcon variant="subtle" size="lg" onClick={() => fetchData()}>
                                    {loading ? '...' : <IconRefresh size={18} />}
                                </ActionIcon>
                            </>
                        ) : (
                            /* Desktop: Full Buttons */
                            <Group gap="xs">
                                <Button
                                    variant="light"
                                    color="violet"
                                    onClick={openControl}
                                    leftSection={<IconSettings size={16} />}
                                >
                                    스크래퍼 제어
                                </Button>
                                <Button
                                    variant="default"
                                    onClick={() => fetchData()}
                                    leftSection={<IconRefresh size={16} className={loading ? 'animate-spin' : ''} />}
                                >
                                    데이터 갱신
                                </Button>
                                <Button
                                    variant="subtle"
                                    color="gray"
                                    onClick={() => signOut({ callbackUrl: '/login' })}
                                >
                                    Sign Out
                                </Button>
                            </Group>

                        )}

                    </Group>
                </Group>
            </AppShell.Header>

            <AppShell.Navbar p="md">
                <Button
                    fullWidth
                    color="orange"
                    variant="filled"
                    mb="md"
                    leftSection={<IconCoin size={20} />}
                    onClick={() => window.location.href = '/trade'}
                    size="md"
                >
                    Trading Dashboard
                </Button>
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
                    variant="default"
                    leftSection={<IconNews size={16} />}
                    justify="flex-start"
                    component="a"
                    href="https://www.tossinvest.com/feed/news"
                    target="_blank"
                    mb="md"
                >
                    토스증권 뉴스 (Toss)
                </Button>

                <Text fw={700} mb="sm">Downloads (Excel)</Text>
                <div className="flex flex-col gap-2">
                    {reports.length > 0 ? reports.map((rpt, idx) => (
                        <Button
                            key={idx}
                            fullWidth
                            variant="subtle"
                            size="xs"
                            justify="flex-start"
                            component="a"
                            href={`https://github.com/${REPO_OWNER}/${REPO_NAME}/raw/main/${rpt.filename}`}
                            target="_blank"
                            leftSection={<IconRefresh size={14} />} // IconDownload replacement if not imported
                            color="gray"
                        >
                            {rpt.date.split(' ')[1]} 리포트 ({rpt.count}건)
                        </Button>
                    )) : (
                        <Text size="xs" c="dimmed">리포트 없음</Text>
                    )}
                </div>
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
                                <Tabs.Tab value="5DAYS">📅 5일 누적</Tabs.Tab>
                                <Tabs.Tab value="3DAYS">📅 3일 누적</Tabs.Tab>
                            </Tabs.List>
                        </Tabs>

                        {/* Time Slot Selector (Mobile) */}
                        <div className="flex flex-col gap-1 mb-2">
                            <Text size="xs" fw={700} c="dimmed">🕒 타임슬립 (과거 시점 조회)</Text>
                            <SegmentedControl
                                size="xs"
                                color="blue"
                                value={timeSlot}
                                onChange={(val) => setTimeSlot(val)}
                                data={timeSlots}
                                mb="xs"
                            />
                        </div>

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
                                    <Tabs.Tab value="5DAYS">📅 5일 누적 (Trends)</Tabs.Tab>
                                    <Tabs.Tab value="3DAYS">📅 3일 누적 (Trends)</Tabs.Tab>
                                </Tabs.List>
                            </Tabs>

                            {lastUpdated && <Text size="xs" c="dimmed" ml="md">🕒 Update: {lastUpdated}</Text>}
                        </Group >

                        <Group>
                            {/* Time Slot Selector (Desktop) */}
                            <Group gap="xs" mr="xl" bg="gray.0" p={4} style={{ borderRadius: 8, border: '1px solid #eee' }}>
                                <Text size="xs" fw={700} c="dimmed" ml="xs">🕒 타임슬립:</Text>
                                <SegmentedControl
                                    size="xs"
                                    color="blue"
                                    value={timeSlot}
                                    onChange={(val) => setTimeSlot(val)}
                                    data={timeSlots}
                                />
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
                    </Group >
                )}

                {
                    activeTab === '5DAYS' ? (
                        <ScrollArea type="always" offsetScrollbars>
                            {/* Split KOSPI and KOSDAQ Tables */}
                            {['KOSPI', 'KOSDAQ'].map((marketType) => {
                                const marketData = sortedFiveDayData.filter(s => s.market === marketType);
                                if (marketData.length === 0) return null;

                                return (
                                    <div key={marketType} style={{ marginBottom: 40 }}>
                                        <Text fw={700} size="xl" mb="md" c="blue.7">{marketType} (5일 누적)</Text>
                                        <Table striped highlightOnHover withTableBorder style={{ minWidth: 1000 }}>
                                            <Table.Thead style={{ position: 'sticky', top: 0, zIndex: 3, backgroundColor: 'var(--mantine-color-body)' }}>
                                                <Table.Tr>
                                                    <Table.Th onClick={() => handleSort('name')} style={{ cursor: 'pointer', position: 'sticky', left: 0, zIndex: 4, backgroundColor: 'var(--mantine-color-body)', boxShadow: '2px 0 5px rgba(0,0,0,0.1)' }}>
                                                        종목명 {sortConfig?.key === 'name' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}
                                                    </Table.Th>
                                                    <Table.Th onClick={() => handleSort('consecutive_days')} style={{ cursor: 'pointer' }}>등록일 {sortConfig?.key === 'consecutive_days' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}</Table.Th>
                                                    <Table.Th onClick={() => handleSort('total_posts')} style={{ cursor: 'pointer' }}>누적 토론글 {sortConfig?.key === 'total_posts' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}</Table.Th>
                                                    <Table.Th onClick={() => handleSort('avg_posts')} style={{ cursor: 'pointer' }}>평균 글수 {sortConfig?.key === 'avg_posts' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}</Table.Th>
                                                    <Table.Th onClick={() => handleSort('std_dev')} style={{ cursor: 'pointer' }}>표준편차 {sortConfig?.key === 'std_dev' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}</Table.Th>
                                                    <Table.Th>5일 전 주가</Table.Th>
                                                    <Table.Th>현재가</Table.Th>
                                                    <Table.Th>주가 추세 (5일) (단위: 천원)</Table.Th>
                                                    <Table.Th>토론글 추세 (5일)</Table.Th>
                                                </Table.Tr>
                                            </Table.Thead>
                                            <Table.Tbody>
                                                {marketData.map((stock) => (
                                                    <Table.Tr key={stock.code}>
                                                        <Table.Td style={{ position: 'sticky', left: 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 2, boxShadow: '2px 0 5px rgba(0,0,0,0.1)' }}>
                                                            <Text fw={700}>
                                                                <Group gap={4}>
                                                                    <a href={`https://finance.naver.com/item/main.naver?code=${stock.code}`} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'underline' }}>
                                                                        {stock.name}
                                                                    </a>
                                                                    <ActionIcon size="sm" variant="subtle" color="blue" onClick={() => openQuickOrder(stock)}>
                                                                        <IconCoin size={16} />
                                                                    </ActionIcon>
                                                                </Group>
                                                            </Text>
                                                            <Text size="xs" c="dimmed">{stock.code}</Text>
                                                        </Table.Td>
                                                        <Table.Td>
                                                            <Badge color="red" variant="filled">{stock.consecutive_days}일</Badge>
                                                        </Table.Td>
                                                        <Table.Td>{stock.total_posts.toLocaleString()}</Table.Td>
                                                        <Table.Td>{stock.avg_posts}</Table.Td>
                                                        <Table.Td>{stock.std_dev}</Table.Td>
                                                        <Table.Td>
                                                            <Text size="sm" fw={500} c="dimmed">{stock.price_start?.toLocaleString() || '-'}</Text>
                                                        </Table.Td>
                                                        <Table.Td>
                                                            <Text fw={700}>{stock.price.toLocaleString()}</Text>
                                                            <Text size="xs" c={stock.period_change_rate && stock.period_change_rate > 0 ? 'red' : 'blue'}>
                                                                {stock.period_change_rate && stock.period_change_rate > 0 ? '+' : ''}{stock.period_change_rate}%
                                                            </Text>
                                                        </Table.Td>
                                                        <Table.Td>
                                                            <Sparkline data={stock.sparkline_price || []} />
                                                            <Group gap={0} mt={4} justify="space-between" style={{ width: 100 }}>
                                                                {(stock.sparkline_price || []).map((v, i) => (
                                                                    <Text key={i} size="xs" c="dimmed" style={{ fontSize: '10px' }}>{v > 0 ? (v / 1000).toFixed(1) : '-'}</Text>
                                                                ))}
                                                            </Group>
                                                        </Table.Td>
                                                        <Table.Td>
                                                            <Sparkline data={stock.sparkline_posts || []} />
                                                            <Group gap={0} mt={4} justify="space-between" style={{ width: 100 }}>
                                                                {(stock.sparkline_posts || []).map((v, i) => (
                                                                    <Text key={i} size="xs" c="dimmed" style={{ fontSize: '10px' }}>{v?.toLocaleString()}</Text>
                                                                ))}
                                                            </Group>
                                                        </Table.Td>
                                                    </Table.Tr>
                                                ))}
                                            </Table.Tbody>
                                        </Table>
                                    </div>
                                );
                            })}
                        </ScrollArea>
                    ) : activeTab === '3DAYS' ? (
                        <ScrollArea type="always" offsetScrollbars>
                            {/* 3-Day Analysis View */}
                            {['KOSPI', 'KOSDAQ'].map((marketType) => {
                                const marketData = sortedThreeDayData.filter(s => s.market === marketType);
                                if (marketData.length === 0) return null;

                                return (
                                    <div key={marketType} style={{ marginBottom: 40 }}>
                                        <Text fw={700} size="xl" mb="md" c="blue.7">{marketType} (3일 누적)</Text>
                                        <Table striped highlightOnHover withTableBorder style={{ minWidth: 1000 }}>
                                            <Table.Thead style={{ position: 'sticky', top: 0, zIndex: 3, backgroundColor: 'var(--mantine-color-body)' }}>
                                                <Table.Tr>
                                                    <Table.Th onClick={() => handleSort('name')} style={{ cursor: 'pointer', position: 'sticky', left: 0, zIndex: 4, backgroundColor: 'var(--mantine-color-body)', boxShadow: '2px 0 5px rgba(0,0,0,0.1)' }}>
                                                        종목명 {sortConfig?.key === 'name' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}
                                                    </Table.Th>
                                                    <Table.Th onClick={() => handleSort('consecutive_days')} style={{ cursor: 'pointer' }}>연속 등록일 {sortConfig?.key === 'consecutive_days' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}</Table.Th>
                                                    <Table.Th onClick={() => handleSort('total_posts')} style={{ cursor: 'pointer' }}>누적 토론글 {sortConfig?.key === 'total_posts' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}</Table.Th>
                                                    <Table.Th onClick={() => handleSort('avg_posts')} style={{ cursor: 'pointer' }}>평균 글수 {sortConfig?.key === 'avg_posts' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}</Table.Th>
                                                    <Table.Th onClick={() => handleSort('std_dev')} style={{ cursor: 'pointer' }}>표준편차 {sortConfig?.key === 'std_dev' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}</Table.Th>
                                                    <Table.Th>3일 전 주가</Table.Th>
                                                    <Table.Th>현재가</Table.Th>
                                                    <Table.Th>주가 추세 (3일) (단위: 천원)</Table.Th>
                                                    <Table.Th>토론글 추세 (3일)</Table.Th>
                                                </Table.Tr>
                                            </Table.Thead>
                                            <Table.Tbody>
                                                {marketData.map((stock) => (
                                                    <Table.Tr key={stock.code}>
                                                        <Table.Td style={{ position: 'sticky', left: 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 2, boxShadow: '2px 0 5px rgba(0,0,0,0.1)' }}>
                                                            <Text fw={700}>
                                                                <Group gap={4}>
                                                                    <a href={`https://finance.naver.com/item/main.naver?code=${stock.code}`} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'underline' }}>
                                                                        {stock.name}
                                                                    </a>
                                                                    <ActionIcon size="sm" variant="subtle" color="blue" onClick={() => openQuickOrder(stock)}>
                                                                        <IconCoin size={16} />
                                                                    </ActionIcon>
                                                                </Group>
                                                            </Text>
                                                            <Text size="xs" c="dimmed">{stock.code}</Text>
                                                        </Table.Td>
                                                        <Table.Td>
                                                            <Badge color="red" variant="filled">{stock.consecutive_days}일</Badge>
                                                        </Table.Td>
                                                        <Table.Td>{stock.total_posts.toLocaleString()}</Table.Td>
                                                        <Table.Td>{stock.avg_posts}</Table.Td>
                                                        <Table.Td>{stock.std_dev}</Table.Td>
                                                        <Table.Td>
                                                            <Text size="sm" fw={500} c="dimmed">{stock.price_start?.toLocaleString() || '-'}</Text>
                                                        </Table.Td>
                                                        <Table.Td>
                                                            <Text fw={700}>{stock.price.toLocaleString()}</Text>
                                                            <Text size="xs" c={stock.period_change_rate && stock.period_change_rate > 0 ? 'red' : 'blue'}>
                                                                {stock.period_change_rate && stock.period_change_rate > 0 ? '+' : ''}{stock.period_change_rate}%
                                                            </Text>
                                                        </Table.Td>
                                                        <Table.Td>
                                                            <Sparkline data={stock.sparkline_price || []} />
                                                            <Group gap={0} mt={4} justify="space-between" style={{ width: 100 }}>
                                                                {(stock.sparkline_price || []).map((v, i) => (
                                                                    <Text key={i} size="xs" c="dimmed" style={{ fontSize: '10px' }}>{(v / 1000).toFixed(1)}</Text>
                                                                ))}
                                                            </Group>
                                                        </Table.Td>
                                                        <Table.Td>
                                                            <Sparkline data={stock.sparkline_posts || []} />
                                                            <Group gap={0} mt={4} justify="space-between" style={{ width: 100 }}>
                                                                {(stock.sparkline_posts || []).map((v, i) => (
                                                                    <Text key={i} size="xs" c="dimmed" style={{ fontSize: '10px' }}>{v?.toLocaleString()}</Text>
                                                                ))}
                                                            </Group>
                                                        </Table.Td>
                                                    </Table.Tr>
                                                ))}
                                            </Table.Tbody>
                                        </Table>
                                    </div>
                                );
                            })}
                        </ScrollArea>
                    ) : (isMobile && viewMode === 'card') ? (
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
                                    <Text size="sm" style={{ whiteSpace: 'pre-wrap' }} mb="xs">{stock.posts_summary || stock.summary}</Text>

                                    <Group grow>
                                        <Button
                                            variant="light"
                                            color="teal"
                                            size="xs"
                                            leftSection={<IconCopy size={14} />}
                                            onClick={() => handleCopyAndOpen(stock.code)}
                                        >
                                            Copy Code
                                        </Button>
                                        <Button
                                            variant="light"
                                            color="blue"
                                            size="xs"
                                            leftSection={<IconCoin size={14} />}
                                            onClick={() => openQuickOrder(stock)}
                                        >
                                            Trade Order
                                        </Button>
                                    </Group>
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
                                                    <Group gap={4}>
                                                        <a href={`https://finance.naver.com/item/main.naver?code=${stock.code}`} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'underline' }}>
                                                            {stock.name}
                                                        </a>
                                                        <Group gap={2}>
                                                            <ActionIcon size="sm" variant="subtle" color="teal" onClick={() => handleCopyAndOpen(stock.code)}>
                                                                <IconCopy size={16} />
                                                            </ActionIcon>
                                                            <ActionIcon size="sm" variant="subtle" color="blue" onClick={() => openQuickOrder(stock)}>
                                                                <IconCoin size={16} />
                                                            </ActionIcon>
                                                        </Group>
                                                    </Group>
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
                                                        <Button variant="light" size="xs" color="grape" onClick={() => {
                                                            setPdfItem(item);
                                                        }}>AI 분석</Button>
                                                        <Button variant="outline" size="xs" component="a" href={item.pdf_link} target="_blank">PDF</Button>
                                                    </>
                                                )}
                                            </Group>
                                        </Card>
                                    ))}
                                </div>
                            </div>
                        </ScrollArea>
                    ) : (
                        // --- Desktop View (Split) ---
                        <Grid h="100%" gutter={0}>
                            {/* Left: List */}
                            <Grid.Col span={4} style={{ borderRight: '1px solid #eee', height: '100%' }}>
                                <ScrollArea h="100%" p="md">
                                    {/* Insight Summary */}
                                    <Paper withBorder p="sm" bg="blue.0" radius="md" mb="md">
                                        <Group mb="xs">
                                            <IconNews size={20} color="#228be6" />
                                            <Text fw={700} size="sm" c="blue.8">오늘의 시장 인사이트</Text>
                                        </Group>
                                        <Text size="xs" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                                            {research[selectedResearchCategory].summary}
                                        </Text>
                                    </Paper>

                                    <div className="flex flex-col gap-2">
                                        {research[selectedResearchCategory].items.map((item: any, idx: number) => (
                                            <UnstyledButton
                                                key={idx}
                                                onClick={() => {
                                                    if (item.pdf_link) {
                                                        setPdfItem(item);
                                                    } else {
                                                        window.open(item.link, '_blank');
                                                    }
                                                }}
                                                style={{
                                                    padding: '12px',
                                                    borderRadius: '8px',
                                                    border: '1px solid #eee',
                                                    backgroundColor: 'white',
                                                    transition: 'all 0.2s',
                                                }}
                                                className="hover:bg-gray-50 hover:shadow-sm"
                                            >
                                                <Text fw={600} size="sm" mb={4} lineClamp={1}>{item.title}</Text>
                                                <Group gap={4} mb={4}>
                                                    <Badge size="xs" variant="dot" color="gray">{item.date}</Badge>
                                                    {item.pdf_analysis?.opinion && item.pdf_analysis.opinion !== 'N/A' && (
                                                        <Badge size="xs" variant="light" color={item.pdf_analysis.opinion === 'BUY' ? 'red' : 'orange'}>
                                                            {item.pdf_analysis.opinion}
                                                        </Badge>
                                                    )}
                                                </Group>
                                                <Text size="xs" c="dimmed" lineClamp={2}>{item.body_summary}</Text>
                                            </UnstyledButton>
                                        ))}
                                    </div>
                                </ScrollArea>
                            </Grid.Col>
                            {/* Right: PDF Viewer or Placeholder */}
                            <Grid.Col span={8} h="100%" bg="gray.0">
                                <Center h="100%">
                                    <div className="text-center text-gray-400">
                                        <IconNews size={48} className="mx-auto mb-2 opacity-50" />
                                        <Text>왼쪽 리스트에서 리포트를 선택하세요</Text>
                                    </div>
                                </Center>
                            </Grid.Col>
                        </Grid>
                    )
                ) : (
                    <Center h="100%"><Text c="dimmed">등록된 리포트가 없습니다.</Text></Center>
                )}
            </Modal>


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
