import { useState, useEffect, useMemo, useCallback } from 'react';
import axios from 'axios';
import { useInterval } from '@mantine/hooks';
import { Stock, FiveDayStock, VersionInfo, SortConfig } from '../types';

const REPO_OWNER = "hoonnamkoong";
const REPO_NAME = "stockbot";
const WORKFLOW_ID = "scraper.yml";

const parseNum = (val: any): number => {
    if (typeof val === 'number') return isNaN(val) ? 0 : val;
    if (typeof val === 'string') {
        const cleaned = val.replace(/[^-0-9.]/g, '');
        return parseFloat(cleaned) || 0;
    }
    return 0;
};

export const useResearchSource = () => {
    const [stocks, setStocks] = useState<Stock[]>([]);
    const [fiveDayData, setFiveDayData] = useState<FiveDayStock[]>([]);
    const [threeDayData, setThreeDayData] = useState<FiveDayStock[]>([]);
    const [loading, setLoading] = useState(false);
    const [lastUpdated, setLastUpdated] = useState<string>('');
    const [versionInfo, setVersionInfo] = useState<VersionInfo | null>(null);
    const [reports, setReports] = useState<any[]>([]);
    const [githubToken, setGithubToken] = useState('');
    const [workflowStatus, setWorkflowStatus] = useState<'idle' | 'running' | 'success' | 'error'>('idle');
    const [workflowLogs, setWorkflowLogs] = useState<string[]>([]);
    const [systemLogs, setSystemLogs] = useState<string[]>([]);
    const [sortConfig, setSortConfig] = useState<SortConfig>({ key: 'recent_posts_count', direction: 'desc' });
    const [trackingOrders, setTrackingOrders] = useState<string[]>([]);
    const [orderStatuses, setOrderStatuses] = useState<Record<string, any>>({});
    const [notifiedOrders, setNotifiedOrders] = useState<Set<string>>(new Set());
    const [notification, setNotification] = useState<{ title: string, msg: string, color: string } | null>(null);

    const showNotify = (title: string, msg: string, color: string) => {
        setNotification({ title, msg, color });
        setTimeout(() => setNotification(null), 5000);
    };

    const addSystemLog = useCallback((msg: string) => {
        setSystemLogs(prev => [`[${new Date().toLocaleTimeString()}] ${msg}`, ...prev]);
    }, []);

    const fetchData = useCallback(async () => {
        if (typeof window === 'undefined') return;
        setLoading(true);
        addSystemLog("🔄 데이터 새로고침 시작...");
        try {
            const timeMap = new Date().getTime();
            const filename = 'latest_stocks.json';
            const stockUrl = `https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/db-data/data/${filename}?t=${timeMap}`;

            const resStocks = await fetch(stockUrl, { cache: 'no-store' });
            if (resStocks.ok) {
                const rawText = await resStocks.text();
                const rawData = JSON.parse(rawText.replace(/\bNaN\b/g, '0').replace(/\bInfinity\b/g, '0').replace(/\b-Infinity\b/g, '0'));
                const mappedData = rawData.map((item: any) => ({
                    ...item,
                    market: item.market || item['시장'] || item['시장구분'],
                    code: item.code,
                    name: item.name || item['종목명'],
                    price: parseNum(item.price || item['현재가']),
                    current_price: parseNum(item.price || item['현재가']),
                    prev_close: parseNum(item.prev_close || item['어제_종가'] || item['전일종가']),
                    change_rate: parseNum(item.change_rate || item['등락률']),
                    recent_posts_count: item.recent_posts_count || item['게시글수'] || item['당일_게시글수'] || item['당일 게시글수'],
                    foreign_rate: parseNum(item.foreign_rate || item['외인소진율'] || item['현재_외국인비중']),
                    prev_foreign_rate: parseNum(item.prev_foreign_rate || item['전일_외국인비중'] || item['어제_외국인비중']),
                    posts_summary: item.posts_summary || item['게시물_요약'],
                    sentiment: item.sentiment || item['감정분석'],
                    top_keywords: Array.isArray(item.top_keywords) ? item.top_keywords : 
                                 (typeof item.top_keywords === 'string' ? item.top_keywords.split(',').map((k: string) => k.trim()) : 
                                 (item['Top_Keyword'] || item['Top_Keywords'] || [])),
                    is_last_captured: item.is_last_captured || item['연속_등록'],
                    consecutive_days: Number(item.consecutive_days) || (item['연속_등록'] === true ? 2 : 1),
                    foreign_change_rate: parseNum(item.foreign_change_rate || item['외국인_변화'] || 0),
                    latest_post: item.latest_posts && item.latest_posts.length > 0 ? item.latest_posts[0].title : (item['latest_post'] || ''),
                }));
                setStocks(mappedData);
            }

            // Sync other sources
            const resStatus = await fetch(`https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/db-data/data/status.json?t=${timeMap}`, { cache: 'no-store' });
            if (resStatus.ok) {
                const statusData = await resStatus.json();
                setLastUpdated(statusData.last_updated);
            }

            const resReports = await fetch(`https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/db-data/data/reports.json?t=${timeMap}`, { cache: 'no-store' });
            if (resReports.ok) {
                const data = await resReports.json();
                setReports([...data.filter((r: any) => r.type === 'monthly'), ...data.filter((r: any) => r.type === 'daily').slice(0, 10)]);
            }

            const res5 = await fetch(`https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/db-data/data/analysis_5days.json?t=${timeMap}`, { cache: 'no-store' });
            if (res5.ok) {
                const raw5 = await res5.text();
                const mapped5 = JSON.parse(raw5.replace(/\bNaN\b/g, '0')).map((item: any) => ({
                    ...item,
                    current_price: parseNum(item.current_price || item.price),
                    change_rate: parseNum(item.change_rate),
                    sparkline_price: Array.isArray(item.sparkline_price) ? item.sparkline_price : [],
                    sparkline_posts: Array.isArray(item.sparkline_posts) ? item.sparkline_posts : []
                }));
                setFiveDayData(mapped5);
            }

            const res3 = await fetch(`https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/db-data/data/analysis_3days.json?t=${timeMap}`, { cache: 'no-store' });
            if (res3.ok) {
                const raw3 = await res3.text();
                const mapped3 = JSON.parse(raw3.replace(/\bNaN\b/g, '0')).map((item: any) => ({
                    ...item,
                    current_price: parseNum(item.current_price || item.price),
                    change_rate: parseNum(item.change_rate),
                    sparkline_price: Array.isArray(item.sparkline_price) ? item.sparkline_price : [],
                    sparkline_posts: Array.isArray(item.sparkline_posts) ? item.sparkline_posts : []
                }));
                setThreeDayData(mapped3);
            }
        } catch (e: any) {
            console.error(e);
            addSystemLog(`❌ ERROR: ${e.message}`);
        }
        setLoading(false);
    }, [addSystemLog]);

    const fetchVersion = useCallback(async () => {
        if (typeof window === 'undefined') return;
        try {
            const res = await fetch('/api/version');
            if (res.ok) setVersionInfo(await res.json());
        } catch (e) { console.error(e); }
    }, []);

    const monitorWorkflow = useCallback(async () => {
        const interval = setInterval(async () => {
            try {
                const res = await fetch(`https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/runs?per_page=1`, {
                    headers: { 'Authorization': `Bearer ${githubToken}` }
                });
                if (!res.ok) return;
                const data = await res.json();
                if (data.workflow_runs?.[0]) {
                    const run = data.workflow_runs[0];
                    setWorkflowLogs(prev => [...prev, `🔄 상태: ${run.status} (${run.conclusion || 'Running'})`]);
                    if (run.status === 'completed') {
                        clearInterval(interval);
                        setWorkflowStatus(run.conclusion === 'success' ? 'success' : 'error');
                        if (run.conclusion === 'success') setTimeout(fetchData, 3000);
                    }
                }
            } catch (e) { console.error(e); }
        }, 5000);
    }, [githubToken, fetchData]);

    const runScraper = useCallback(async (forceRun: boolean) => {
        if (!githubToken) return alert("GitHub Token을 입력해주세요.");
        localStorage.setItem('github_pat', githubToken);
        setWorkflowStatus('running');
        setWorkflowLogs(["🚀 워크플로우 실행 요청 중..."]);
        try {
            const res = await fetch(`https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${WORKFLOW_ID}/dispatches`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${githubToken}`, 'Accept': 'application/vnd.github.v3+json' },
                body: JSON.stringify({ ref: 'main', inputs: { force_run: forceRun.toString() } })
            });
            if (res.ok) monitorWorkflow();
            else setWorkflowStatus('error');
        } catch (e) { setWorkflowStatus('error'); }
    }, [githubToken, monitorWorkflow]);

    const handleSort = (key: string) => {
        setSortConfig(prev => ({
            key,
            direction: prev.key === key && prev.direction === 'desc' ? 'asc' : 'desc'
        }));
    };

    const sortData = (data: any[]) => {
        if (!sortConfig.key) return data;
        return [...data].sort((a, b) => {
            const parse = (v: any) => typeof v === 'string' ? Number(v.replace(/,/g, '').replace('%', '')) || v.toLowerCase() : v;
            const A = parse(a[sortConfig.key!]);
            const B = parse(b[sortConfig.key!]);
            return sortConfig.direction === 'asc' ? (A < B ? -1 : 1) : (A > B ? -1 : 1);
        });
    };

    useEffect(() => {
        fetchData();
        fetchVersion();
        const tk = typeof window !== 'undefined' ? localStorage.getItem('github_pat') : null;
        if (tk) setGithubToken(tk);
    }, [fetchData, fetchVersion]);

    return {
        stocks: sortData(stocks),
        fiveDayData: sortData(fiveDayData),
        threeDayData: sortData(threeDayData),
        loading,
        lastUpdated,
        versionInfo,
        reports,
        githubToken,
        setGithubToken,
        workflowStatus,
        workflowLogs,
        systemLogs,
        sortConfig,
        handleSort,
        runScraper,
        fetchData,
        notification,
        setNotification,
        setTrackingOrders
    };
};
