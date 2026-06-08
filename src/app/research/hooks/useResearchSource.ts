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
        addSystemLog("🔄 리서치 데이터 새로고침 시작...");
        try {
            // [V8.6.2 Hotfix] GitHub 외부 URL이 아닌 로컬 전용 API 호출로 소스 전환
            const res = await fetch(`/api/stocks/research?v=8.9.9.5&cb=${new Date().getTime()}`);
            if (!res.ok) throw new Error("API 응답 실패");
            
            const data = await res.json();
            if (!data.success) throw new Error(data.error || "데이터 로드 실패");

            // 1. 주요 종목 데이터 (latest_stocks.json)
            const mappedData = (data.stocks || []).map((item: any) => ({
                ...item,
                market: item.market || item['시장'] || item['시장구분'],
                code: item.code,
                name: item.name || item['종목명'],
                price: parseNum(item.price || item['현재가']),
                current_price: parseNum(item.price || item['현재가']),
                prev_close: parseNum(item.prev_close || item['전일종가'] || item['어제_종가']),
                change_rate: parseNum(item.change_rate || item['등락률']),
                recent_posts_count: item.recent_posts_count || item['게시물'] || item['당일_게시글수'] || item['게시글수'] || item['당일 게시글수'],
                foreign_rate: parseNum(item.foreign_rate || item['외인비중'] || item['외인소진율'] || item['현재_외국인비중']),
                prev_foreign_rate: parseNum(item.prev_foreign_rate || item['전일외인'] || item['전일_외국인비중'] || item['어제_외국인비중']),
                posts_summary: item.posts_summary || item['게시물_요약'],
                sentiment: item.sentiment || item['감정'] || item['감정분석'],
                top_keywords: Array.isArray(item.top_keywords) ? item.top_keywords : 
                             (typeof item.top_keywords === 'string' ? item.top_keywords.split(',').map((k: string) => k.trim()) : 
                             (item['키워드'] || item['Top_Keyword'] || item['Top_Keywords'] || [])),
                is_last_captured: item.is_last_captured || (item['연속'] > 1),
                consecutive_days: Number(item.consecutive_days || item['연속']) || (item['연속_등록'] === true ? 2 : 1),
                foreign_change_rate: parseNum(item.foreign_change_rate || item['외인변화'] || item['외국인_변화'] || item['foreign_change'] || 0),
                latest_post: item.latest_posts && item.latest_posts.length > 0 ? item.latest_posts[0].title : (item['latest_post'] || ''),
            }));
            setStocks(mappedData);

            // 2. 상태 정보 (status.json)
            setLastUpdated(data.status?.last_updated || 'Unknown');

            // 3. 리포트 목록 (reports.json)
            const reportsData = data.reports || [];
            setReports([
                ...reportsData.filter((r: any) => r.type === 'monthly'),
                ...reportsData.filter((r: any) => r.type === 'daily' || r.type === 'research').slice(0, 15)
            ]);

            // 4. 5일/3일 누적 데이터
            const mapTrend = (t: any) => ({
                ...t,
                current_price: parseNum(t.current_price || t.price),
                change_rate: parseNum(t.change_rate),
                sparkline_price: Array.isArray(t.sparkline_price) ? t.sparkline_price : [],
                sparkline_posts: Array.isArray(t.sparkline_posts) ? t.sparkline_posts : []
            });

            setFiveDayData((data.analysis_5days || []).map(mapTrend));
            setThreeDayData((data.analysis_3days || []).map(mapTrend));

        } catch (e: any) {
            console.error(e);
            addSystemLog(`❌ 데이터 갱신 ERROR: ${e.message}`);
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
        let lastLine = '';
        let polls = 0;
        const interval = setInterval(async () => {
            polls++;
            try {
                const res = await fetch(`https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/runs?per_page=1`, {
                    headers: { 'Authorization': `Bearer ${githubToken}` }
                });
                if (!res.ok) {
                    setWorkflowLogs(prev => [...prev, `⚠️ 상태 조회 실패 (HTTP ${res.status})`]);
                    if (polls >= 12) { clearInterval(interval); setWorkflowStatus('error'); }
                    return;
                }
                const data = await res.json();
                const run = data.workflow_runs?.[0];
                if (run) {
                    // 같은 상태 줄은 중복 출력하지 않음
                    const line = `🔄 상태: ${run.status} (${run.conclusion || 'Running'})`;
                    if (line !== lastLine) { setWorkflowLogs(prev => [...prev, line]); lastLine = line; }
                    if (run.status === 'completed') {
                        clearInterval(interval);
                        const ok = run.conclusion === 'success';
                        setWorkflowStatus(ok ? 'success' : 'error');
                        setWorkflowLogs(prev => [...prev, ok ? '✅ 실행 완료' : `❌ 실행 종료: ${run.conclusion}`]);
                        if (ok) setTimeout(fetchData, 3000);
                    }
                }
            } catch (e: any) {
                setWorkflowLogs(prev => [...prev, `⚠️ 모니터링 오류: ${e?.message || e}`]);
            }
            if (polls >= 180) { clearInterval(interval); }  // 15분 안전 종료
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
            if (res.ok) {
                setWorkflowLogs(prev => [...prev, "✅ 실행 요청 성공 — 진행 상황 추적 중..."]);
                monitorWorkflow();
            } else {
                // 실패 사유를 로그창에 그대로 노출 (예전처럼 멈춰있지 않도록)
                let detail = '';
                try { const b = await res.json(); detail = b.message || JSON.stringify(b); }
                catch { try { detail = await res.text(); } catch { detail = ''; } }
                setWorkflowLogs(prev => [...prev, `❌ 실행 요청 실패 (HTTP ${res.status}): ${detail}`]);
                setWorkflowStatus('error');
            }
        } catch (e: any) {
            setWorkflowLogs(prev => [...prev, `❌ 네트워크 오류: ${e?.message || e}`]);
            setWorkflowStatus('error');
        }
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
