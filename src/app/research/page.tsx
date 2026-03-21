'use client';

import React, { useState, useEffect } from 'react';
import { AppShell, Burger, Group, Title, Button, Table, Text, Badge, Modal, useMantineTheme, ScrollArea, Tabs, PasswordInput, Paper, UnstyledButton, Center, Tooltip, Popover, Grid, Flex, SegmentedControl, Divider, ActionIcon, Checkbox } from '@mantine/core';
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
        return `${x},${y}`;
    }).join(' ');

    return (
        <Group gap="xs" style={{ width: width + 60 }}> {/* Extra space for labels */}
            <Text size="xs" c="dimmed" style={{ minWidth: 30, textAlign: 'right' }}>
                {data[0].toLocaleString()}
            </Text>
            <svg width={width} height={height} style={{ overflow: 'visible' }}>
                <polyline
                    fill="none"
                    stroke={data[data.length - 1] >= data[0] ? 'red' : 'blue'}
                    strokeWidth="2"
                    points={points}
                />

                {/* Min/Max Text Labels on SVG for better context if needed, but side labels are cleaner */}
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
            <Text size="xs" fw={700} c={data[data.length - 1] >= data[0] ? 'red' : 'blue'} style={{ minWidth: 30 }}>
                {data[data.length - 1].toLocaleString()}
            </Text>
        </Group>
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
    // const [research, setResearch] = useState<any>(null); // Removed V8.0
    const [loading, setLoading] = useState(false);
    const [lastUpdated, setLastUpdated] = useState<string>('');
    const [activeTab, setActiveTab] = useState<string | null>('ALL');

    // Sorting State
    const [sortConfig, setSortConfig] = useState<{ key: string | null; direction: 'asc' | 'desc' }>({ key: 'recent_posts_count', direction: 'desc' });

    // Scraper Control
    const [controlOpened, { open: openControl, close: closeControl }] = useDisclosure(false);
    const [githubToken, setGithubToken] = useState('');
    const [forceRun, setForceRun] = useState(false);
    const [workflowStatus, setWorkflowStatus] = useState<'idle' | 'running' | 'success' | 'error'>('idle');
    const [workflowLogs, setWorkflowLogs] = useState<string[]>([]);

    const theme = useMantineTheme();
    const isMobile = useMediaQuery(`(max-width: ${theme.breakpoints.sm})`);

    // Research Modal (Disabled V8.0)
    // const [researchModalOpened, { open: openResearchModal, close: closeResearchModal }] = useDisclosure(false);
    // const [selectedResearchCategory, setSelectedResearchCategory] = useState<string | null>(null);
    // const [pdfItem, setPdfItem] = useState<any>(null);
    const [reports, setReports] = useState<any[]>([]);

    // Version State
    const [versionInfo, setVersionInfo] = useState<{ version: string, timestamp: string } | null>(null);

    // Quick Order State
    const [quickOrderOpen, setQuickOrderOpen] = useState(false);
    const [selectedQuickStock, setSelectedQuickStock] = useState<{ code: string, name: string }>({ code: '', name: '' });

    const handleCopyAndOpen = (code: string, name: string = '') => {
        navigator.clipboard.writeText(code);

        // Open Quick Order modal for in-app trading
        setSelectedQuickStock({ code, name: name || code });
        setQuickOrderOpen(true);
    };

    const openQuickOrder = (stock: Stock) => {
        setSelectedQuickStock({ code: stock.code, name: stock.name });
        setQuickOrderOpen(true);
    };


    useEffect(() => {
        fetchData();
        fetchVersion();
        const storedToken = localStorage.getItem('github_pat');
        if (storedToken) setGithubToken(storedToken);
    }, []);

    const fetchVersion = async () => {
        try {
            const res = await fetch('/api/version');
            if (res.ok) {
                const data = await res.json();
                setVersionInfo(data);
            }
        } catch (e) {
            console.error('Failed to fetch version:', e);
        }
    };

    const [systemLogs, setSystemLogs] = useState<string[]>([]);

    const addSystemLog = (msg: string) => {
        setSystemLogs(prev => [`[${new Date().toLocaleTimeString()}] ${msg}`, ...prev]);
    };

    const fetchData = async () => {
        setLoading(true);
        addSystemLog("🔄 데이터 새로고침 시작...");
        try {
            const timeMap = new Date().getTime();
                let filename = 'latest_stocks.json';

            const stockUrl = `https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/db-data/data/${filename}?t=${timeMap}`;

            addSystemLog(`📡 Fetching Stocks: ${stockUrl}`);

            const resStocks = await fetch(stockUrl, { cache: 'no-store' });
            addSystemLog(`📩 Stocks Status: ${resStocks.status} ${resStocks.statusText}`);

            if (resStocks.ok) {
                // Parse JSON safely - handle NaN values from Python's json output
                const rawText = await resStocks.text();
                const rawData = JSON.parse(rawText.replace(/\bNaN\b/g, '0').replace(/\bInfinity\b/g, '0').replace(/\b-Infinity\b/g, '0'));
                // Map Korean Keys (from latest_stocks.json) to English Properties (for Component Logic)
                const mappedData = rawData.map((item: any) => ({
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
                    consecutive_days: item.consecutive_days || (item['연속_등록'] === true ? 2 : 1), // Fallback
                    foreign_change_rate: item.foreign_change_rate || item['외국인_변화'] || 0,
                    // Derive latest_post title
                    latest_post: item.latest_posts && item.latest_posts.length > 0 ? item.latest_posts[0].title : (item['latest_post'] || ''),
                }));
                addSystemLog(`✅ Stocks Loaded: ${mappedData.length} items`);
                setStocks(mappedData);
            } else {
                const text = await resStocks.text();
                addSystemLog(`❌ Stocks Fetch Failed: ${text.slice(0, 100)}`);
            }

            // Fetch Research (Removed V8.0)
            // const resResearch = await fetch(`https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/db-data/data/latest_research.json?t=${timeMap}`, { cache: 'no-store' });
            // if (resResearch.ok) {
            //    const data = await resResearch.json();
            //    setResearch(data);
            //    addSystemLog(`✅ Research Loaded`);
            // }

            // Fetch Status (Timestamp)
            try {
                const resStatus = await fetch(`https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/db-data/data/status.json?t=${timeMap}`, { cache: 'no-store' });
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
                const resReports = await fetch(`https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/db-data/data/reports.json?t=${timeMap}`, { cache: 'no-store' });
                if (resReports.ok) {
                    const data = await resReports.json();
                    // Show ALL monthly reports + top 10 daily reports
                    const monthlyReports = data.filter((r: any) => r.type === 'monthly');
                    const dailyReports = data.filter((r: any) => r.type === 'daily').slice(0, 10);
                    setReports([...monthlyReports, ...dailyReports]);
                }
            } catch (e) { console.error(e); }

            // Fetch 5-Day Analysis
            try {
                const res5 = await fetch(`https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/db-data/data/analysis_5days.json?t=${timeMap}`, { cache: 'no-store' });
                if (res5.ok) {
                    const raw5 = await res5.text();
                    const data = JSON.parse(raw5.replace(/\bNaN\b/g, '0').replace(/\bInfinity\b/g, '0').replace(/\b-Infinity\b/g, '0'));
                    setFiveDayData(data);
                }
            } catch (e) { console.error(e); }

            // Fetch 3-Day Analysis
            try {
                const res3 = await fetch(`https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/db-data/data/analysis_3days.json?t=${timeMap}`, { cache: 'no-store' });
                if (res3.ok) {
                    const raw3 = await res3.text();
                    const data = JSON.parse(raw3.replace(/\bNaN\b/g, '0').replace(/\bInfinity\b/g, '0').replace(/\b-Infinity\b/g, '0'));
                    setThreeDayData(data);
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
                body: JSON.stringify({ 
                    ref: 'main',
                    inputs: {
                        force_run: forceRun.toString()
                    }
                })
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

    // Research Logic (V8.0: Direct Links)
    const handleResearchClick = (key: string) => {
        const urls: any = {
            invest: 'https://finance.naver.com/research/market_info_list.naver',
            company: 'https://finance.naver.com/research/company_list.naver',
            industry: 'https://finance.naver.com/research/industry_list.naver',
            economy: 'https://finance.naver.com/research/economy_list.naver'
        };
        const target = urls[key];
        if (target) window.open(target, '_blank');
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
                        {isMobile
                            ? `StockBot ${versionInfo?.version || 'v10.6-stable'}`
                            : `StockBot ${versionInfo?.version || 'v10.6-stable'} (Deployed ${versionInfo?.timestamp ? new Date(versionInfo.timestamp).toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Seoul' }).replace(/\. /g, '/').replace('.', '') : 'N/A'} KST)`
                        }
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
                    const labelMap: any = { invest: '투자정보', company: '종목분석', industry: '산업분석', economy: '경제분석' };
                    return (
                        <Button
                            key={key}
                            fullWidth
                            variant="light"
                            mb="xs"
                            justify="space-between"
                            onClick={() => handleResearchClick(key)}
                        // rightSection={<Badge color="red" size="sm" circle>{count}</Badge>} // Removed count
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
                    {reports.length > 0 ? (
                        <>
                            {/* Monthly Reports */}
                            {reports.filter(r => r.type === 'monthly').map((rpt, idx) => (
                                <Button
                                    key={`monthly-${idx}`}
                                    fullWidth
                                    variant="light"
                                    size="xs"
                                    justify="flex-start"
                                    component="a"
                                    href={`https://github.com/${REPO_OWNER}/${REPO_NAME}/raw/db-data/data/${rpt.filename}`}
                                    target="_blank"
                                    leftSection={<IconRefresh size={14} />}
                                    color="blue"
                                    fw={600}
                                >
                                    {rpt.label || `${rpt.date} 누적`} ({rpt.count}건)
                                </Button>
                            ))}

                            {/* Divider if both types exist */}
                            {reports.some(r => r.type === 'monthly') && reports.some(r => r.type === 'daily') && (
                                <div style={{ borderTop: '1px solid #dee2e6', margin: '8px 0' }} />
                            )}

                            {/* Daily Reports */}
                            {reports.filter(r => r.type === 'daily').map((rpt, idx) => (
                                <Button
                                    key={`daily-${idx}`}
                                    fullWidth
                                    variant="subtle"
                                    size="xs"
                                    justify="flex-start"
                                    component="a"
                                    href={`https://github.com/${REPO_OWNER}/${REPO_NAME}/raw/db-data/data/${rpt.filename}`}
                                    target="_blank"
                                    leftSection={<IconRefresh size={14} />}
                                    color="gray"
                                >
                                    {rpt.date.split(' ')[1]} 리포트 ({rpt.count}건)
                                </Button>
                            ))}
                        </>
                    ) : (
                        <Text size="xs" c="dimmed">리포트 없음</Text>
                    )}
                </div>
            </AppShell.Navbar>

            <AppShell.Main>
                {/* Responsive Navigation Layout */}
                {isMobile ? (
                    <div className="flex flex-col gap-3 mb-4">
                        <Group justify="space-between" align="center" mb={-5}>
                            <Group ms="auto">
                                <Text size="xs" c="dimmed">🕒 Update: {lastUpdated}</Text>
                                {stocks.length > 0 && stocks[0].scraper_version && (
                                    <Badge size="xs" variant="outline" color="blue">
                                        Data v{stocks[0].scraper_version}
                                    </Badge>
                                )}
                            </Group>
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

                            {lastUpdated &&
                                <Group gap="xs" ml="md">
                                    <Text size="xs" c="dimmed">🕒 Update: {lastUpdated}</Text>
                                    {stocks.length > 0 && stocks[0].scraper_version && (
                                        <Badge size="xs" variant="outline" color="blue">
                                            Data v{stocks[0].scraper_version}
                                        </Badge>
                                    )}
                                </Group>
                            }
                        </Group>
                    </Group>
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
                                            <Table.Thead style={{ position: 'sticky', top: 0, zIndex: 3, backgroundColor: 'var(--mantine-color-default)' }}>
                                                <Table.Tr>
                                                    <Table.Th onClick={() => handleSort('name')} style={{ cursor: 'pointer', position: 'sticky', left: 0, zIndex: 4, backgroundColor: 'var(--mantine-color-default)', boxShadow: '2px 0 5px rgba(0,0,0,0.1)' }}>
                                                        <Group gap="xs">
                                                            종목명
                                                            {sortConfig.key === 'name' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}
                                                        </Group>
                                                    </Table.Th>
                                                    <ThSort sortKey="price">현재가</ThSort>
                                                    <ThSort sortKey="change_rate">등락률</ThSort>
                                                    <ThSort sortKey="consecutive_days">연속 등장</ThSort>
                                                    <ThSort sortKey="avg_posts">평균 게시글</ThSort>
                                                    <ThSort sortKey="total_posts">총 게시글</ThSort>
                                                    {/* Sparkline Headers */}
                                                    <Table.Th>주가 추세 (5D)</Table.Th>
                                                    <Table.Th>토론 추세 (5D)</Table.Th>
                                                </Table.Tr>
                                            </Table.Thead>
                                            <Table.Tbody>
                                                {marketData.map((stock) => (
                                                    <Table.Tr key={stock.code} style={{
                                                        backgroundColor: stock.consecutive_days >= 3 ? 'var(--mantine-color-orange-0)' : undefined,
                                                        cursor: 'pointer'
                                                    }}
                                                        onClick={() => handleCopyAndOpen(stock.code, stock.name)}
                                                    >
                                                        <Table.Td style={{ fontWeight: 700, position: 'sticky', left: 0, backgroundColor: 'var(--mantine-color-default)', zIndex: 2, boxShadow: '2px 0 5px rgba(0,0,0,0.1)' }}>
                                                            {stock.name} <Text span c="dimmed" size="xs">{stock.code}</Text>
                                                        </Table.Td>
                                                        <Table.Td>{Number(stock.price).toLocaleString()}원</Table.Td>
                                                        <Table.Td c={Number(stock.period_change_rate) > 0 ? 'red' : 'blue'}>
                                                            {Number(stock.period_change_rate) > 0 ? '+' : ''}{Number(stock.period_change_rate)?.toFixed(2)}%
                                                        </Table.Td>

                                                        <Table.Td>
                                                            <Badge color={stock.consecutive_days >= 3 ? 'red' : 'gray'}>
                                                                {stock.consecutive_days}일 연속
                                                            </Badge>
                                                        </Table.Td>
                                                        <Table.Td>{Math.round(stock.avg_posts)}개</Table.Td>
                                                        <Table.Td>{stock.total_posts}개</Table.Td>
                                                        <Table.Td>
                                                            <Sparkline data={stock.sparkline_price || []} />
                                                            <Group gap={0} mt={4} justify="space-between" style={{ width: 150 }}>
                                                                {(stock.sparkline_price || []).map((v: any, i: number) => (
                                                                    <Text key={i} size="xs" c="dimmed" style={{ fontSize: '10px' }}>{Number(v).toLocaleString()}</Text>
                                                                ))}
                                                            </Group>
                                                        </Table.Td>
                                                        <Table.Td>
                                                            <Sparkline data={stock.sparkline_posts || []} />
                                                            <Group gap={0} mt={4} justify="space-between" style={{ width: 150 }}>
                                                                {(stock.sparkline_posts || []).map((v: any, i: number) => (
                                                                    <Text key={i} size="xs" c="dimmed" style={{ fontSize: '10px' }}>{Number(v).toLocaleString()}</Text>
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
                        // 3-Day Analysis View (Cloned from 5DAYS logic)
                        <ScrollArea type="always" offsetScrollbars>
                            {/* Split KOSPI and KOSDAQ Tables */}
                            {['KOSPI', 'KOSDAQ'].map((marketType) => {
                                const marketData = sortedThreeDayData.filter(s => s.market === marketType);
                                if (marketData.length === 0) return null;

                                return (
                                    <div key={marketType} style={{ marginBottom: 40 }}>
                                        <Text fw={700} size="xl" mb="md" c="cyan.7">{marketType} (3일 누적)</Text>
                                        <Table striped highlightOnHover withTableBorder style={{ minWidth: 1000 }}>
                                            <Table.Thead style={{ position: 'sticky', top: 0, zIndex: 3, backgroundColor: 'var(--mantine-color-default)' }}>
                                                <Table.Tr>
                                                    <Table.Th onClick={() => handleSort('name')} style={{ cursor: 'pointer', position: 'sticky', left: 0, zIndex: 4, backgroundColor: 'var(--mantine-color-default)', boxShadow: '2px 0 5px rgba(0,0,0,0.1)' }}>
                                                        <Group gap="xs">
                                                            종목명
                                                            {sortConfig.key === 'name' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}
                                                        </Group>
                                                    </Table.Th>
                                                    <ThSort sortKey="price">현재가</ThSort>
                                                    <ThSort sortKey="change_rate">등락률 (누적)</ThSort>
                                                    <ThSort sortKey="consecutive_days">연속 등장</ThSort>
                                                    <ThSort sortKey="avg_posts">평균 게시글</ThSort>
                                                    <ThSort sortKey="total_posts">총 게시글</ThSort>
                                                    {/* Sparkline Headers */}
                                                    <Table.Th>주가 추세 (3D)</Table.Th>
                                                    <Table.Th>토론 추세 (3D)</Table.Th>
                                                </Table.Tr>
                                            </Table.Thead>
                                            <Table.Tbody>
                                                {marketData.map((stock) => (
                                                    <Table.Tr key={stock.code} style={{
                                                        backgroundColor: stock.consecutive_days >= 3 ? 'var(--mantine-color-cyan-0)' : undefined,
                                                        cursor: 'pointer'
                                                    }}
                                                        onClick={() => handleCopyAndOpen(stock.code, stock.name)}
                                                    >
                                                        <Table.Td style={{ fontWeight: 700, position: 'sticky', left: 0, backgroundColor: 'var(--mantine-color-default)', zIndex: 2, boxShadow: '2px 0 5px rgba(0,0,0,0.1)' }}>
                                                            {stock.name} <Text span c="dimmed" size="xs">{stock.code}</Text>
                                                        </Table.Td>
                                                        <Table.Td>{Number(stock.price).toLocaleString()}원</Table.Td>
                                                        <Table.Td c={Number(stock.period_change_rate) > 0 ? 'red' : 'blue'}>
                                                            {Number(stock.period_change_rate) > 0 ? '+' : ''}{Number(stock.period_change_rate)?.toFixed(2)}%
                                                        </Table.Td>


                                                        <Table.Td>
                                                            <Badge color={stock.consecutive_days >= 3 ? 'red' : 'gray'}>
                                                                {stock.consecutive_days}일 연속
                                                            </Badge>
                                                        </Table.Td>
                                                        <Table.Td>{Math.round(stock.avg_posts)}개</Table.Td>
                                                        <Table.Td>{stock.total_posts}개</Table.Td>
                                                        <Table.Td>
                                                            <Sparkline data={stock.sparkline_price || []} />
                                                            <Group gap={0} mt={4} justify="space-between" style={{ width: 150 }}>
                                                                {(stock.sparkline_price || []).map((v: any, i: number) => (
                                                                    <Text key={i} size="xs" c="dimmed" style={{ fontSize: '10px' }}>{Number(v).toLocaleString()}</Text>
                                                                ))}
                                                            </Group>
                                                        </Table.Td>
                                                        <Table.Td>
                                                            <Sparkline data={stock.sparkline_posts || []} />
                                                            <Group gap={0} mt={4} justify="space-between" style={{ width: 150 }}>
                                                                {(stock.sparkline_posts || []).map((v: any, i: number) => (
                                                                    <Text key={i} size="xs" c="dimmed" style={{ fontSize: '10px' }}>{Number(v).toLocaleString()}</Text>
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
                    ) : (
                        <Paper withBorder radius="md" style={{ overflow: 'hidden' }}>
                            <ScrollArea>
                                <Table striped highlightOnHover withTableBorder>
                                    <Table.Thead style={{ position: 'sticky', top: 0, zIndex: 3, backgroundColor: 'var(--mantine-color-default)' }}>
                                        <Table.Tr>
                                            <Table.Th onClick={() => handleSort('name')} style={{ cursor: 'pointer', position: 'sticky', left: 0, zIndex: 4, backgroundColor: 'var(--mantine-color-default)', boxShadow: '2px 0 5px rgba(0,0,0,0.1)' }}>
                                                <Group gap="xs">
                                                    종목명
                                                    {sortConfig.key === 'name' && (sortConfig.direction === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />)}
                                                </Group>
                                            </Table.Th>
                                            <ThSort sortKey="market">시장</ThSort>
                                            <ThSort sortKey="code">코드</ThSort>
                                            <ThSort sortKey="price">현재가</ThSort>
                                            <ThSort sortKey="change_rate">등락률</ThSort>
                                            <ThSort sortKey="foreign_change_rate">외인변화</ThSort>
                                            <ThSort sortKey="recent_posts_count">게시글</ThSort>
                                            <ThSort sortKey="sentiment">감정</ThSort>
                                            <ThSort sortKey="consecutive_days">연속</ThSort>
                                            <Table.Th style={{ width: '20%' }}>게시물_요약</Table.Th>
                                            <ThSort sortKey="foreign_rate">외인비중</ThSort>
                                            <ThSort sortKey="prev_close">전일종가</ThSort>
                                            <ThSort sortKey="prev_foreign_rate">전일외인</ThSort>
                                            <ThSort sortKey="top_keywords">Keywords</ThSort>
                                            <Table.Th>Latest Post</Table.Th>
                                        </Table.Tr>
                                    </Table.Thead>
                                    <Table.Tbody>
                                        {sortedStocks.length > 0 ? (
                                            sortedStocks.map((stock) => (
                                                <Table.Tr key={stock.code} style={{ cursor: 'pointer' }} onClick={() => handleCopyAndOpen(stock.code, stock.name)}>
                                                    <Table.Td fw={700} style={{ position: 'sticky', left: 0, zIndex: 2, backgroundColor: 'var(--mantine-color-default)', boxShadow: '2px 0 5px rgba(0,0,0,0.1)' }}>
                                                        <Group gap={8} wrap="nowrap">
                                                            <a
                                                                href={`https://finance.naver.com/item/main.naver?code=${stock.code}`}
                                                                target="_blank"
                                                                rel="noopener noreferrer"
                                                                onClick={(e) => e.stopPropagation()}
                                                                style={{ textDecoration: 'none', color: 'inherit', display: 'flex', alignItems: 'center', gap: '4px' }}
                                                            >
                                                                {stock.name}
                                                            </a>
                                                            <ActionIcon
                                                                size="sm"
                                                                variant="light"
                                                                color="orange"
                                                                onClick={(e) => {
                                                                    e.stopPropagation();
                                                                    openQuickOrder(stock);
                                                                }}
                                                            >
                                                                <IconCoin size={12} />
                                                            </ActionIcon>
                                                        </Group>
                                                    </Table.Td>
                                                    <Table.Td><Badge size="xs" variant="outline" color={stock.market === 'KOSPI' ? 'blue' : 'green'}>{stock.market}</Badge></Table.Td>
                                                    <Table.Td><Text span c="dimmed" size="xs">{stock.code}</Text></Table.Td>
                                                    <Table.Td>{Number(stock.price).toLocaleString()}원</Table.Td>
                                                    <Table.Td c={Number(stock.change_rate.replace('%', '')) > 0 ? 'red' : 'blue'}>
                                                        {stock.change_rate}
                                                    </Table.Td>
                                                    <Table.Td c={Number(stock.foreign_change_rate) > 0 ? 'red' : Number(stock.foreign_change_rate) < 0 ? 'blue' : 'dimmed'}>
                                                        {Number(stock.foreign_change_rate) > 0 ? '+' : ''}{stock.foreign_change_rate}%
                                                    </Table.Td>
                                                    <Table.Td>
                                                        <Badge variant="light" color={stock.recent_posts_count && stock.recent_posts_count >= 50 ? 'red' : 'gray'}>
                                                            {stock.recent_posts_count}
                                                        </Badge>
                                                    </Table.Td>
                                                    <Table.Td style={{ whiteSpace: 'nowrap' }}>
                                                        <Badge
                                                            color={stock.sentiment?.includes("Positive") ? "blue" : stock.sentiment?.includes("Negative") ? "red" : "gray"}
                                                            variant="light"
                                                            size="sm"
                                                        >
                                                            {stock.sentiment?.split(' ')[0] || '-'}
                                                        </Badge>
                                                    </Table.Td>
                                                    <Table.Td>
                                                        {stock.consecutive_days && stock.consecutive_days > 1 ? (
                                                            <Badge color="orange" size="xs">{stock.consecutive_days}일 연속</Badge>
                                                        ) : (
                                                            <Text size="xs" c="dimmed">New</Text>
                                                        )}
                                                    </Table.Td>
                                                    <Table.Td style={{ fontSize: '0.85em', color: 'var(--mantine-color-dimmed)', lineHeight: '1.3', minWidth: '200px' }}>
                                                        {stock.posts_summary}
                                                    </Table.Td>
                                                    <Table.Td>{stock.foreign_rate || '-'}</Table.Td>
                                                    <Table.Td>{stock.prev_close ? Number(stock.prev_close).toLocaleString() + '원' : '-'}</Table.Td>
                                                    <Table.Td>{stock.prev_foreign_rate || '-'}</Table.Td>
                                                    <Table.Td style={{ whiteSpace: 'nowrap', color: 'var(--mantine-color-dimmed)', maxWidth: '150px', overflow: 'hidden', textOverflow: 'ellipsis' }}>{stock.top_keywords}</Table.Td>
                                                    <Table.Td style={{ maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.85em' }}>
                                                        {stock.latest_post || '-'}
                                                    </Table.Td>
                                                </Table.Tr>
                                            ))
                                        ) : (
                                            <Table.Tr>
                                                <Table.Td colSpan={14} style={{ textAlign: 'center', padding: '2rem' }}>
                                                    <Text c="dimmed">데이터가 없습니다.</Text>
                                                </Table.Td>
                                            </Table.Tr>
                                        )}
                                    </Table.Tbody>
                                </Table>
                            </ScrollArea>
                        </Paper>
                    )}

                {/* Scraper Control Modal */}
                <Modal opened={controlOpened} onClose={closeControl} title="Scraper Control Center (GitHub Actions)" centered>
                    <Text size="sm" mb="md" c="dimmed">
                        GitHub Actions 워크플로우를 직접 실행합니다.<br />
                        실행 시 최신 데이터가 수집되며 약 1~2분 소요됩니다.
                    </Text>

                    <PasswordInput
                        label="GitHub Personal Access Token (PAT)"
                        placeholder="ghp_..."
                        value={githubToken}
                        onChange={(event) => setGithubToken(event.currentTarget.value)}
                        mb="md"
                        description="설정 > Developer settings > Tokens (classic) > repo 권한 필요"
                    />

                    <Checkbox
                        label="Bypass market holiday check (Force execution)"
                        checked={forceRun}
                        onChange={(event: React.ChangeEvent<HTMLInputElement>) => setForceRun(event.currentTarget.checked)}
                        mb="md"
                        color="orange"
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

            </AppShell.Main>
        </AppShell>
    );
}
