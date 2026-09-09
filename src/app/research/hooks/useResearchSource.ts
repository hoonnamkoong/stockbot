import { useState, useEffect, useMemo, useCallback } from 'react';
import axios from 'axios';
import { useInterval } from '@mantine/hooks';
import { Stock, FiveDayStock, VersionInfo, SortConfig } from '../types';
// 행 매핑·정렬은 공개 페이지와 **같은 코드**를 쓴다. 사본을 두면 스크래퍼가
// 포맷을 바꿀 때 한쪽만 고쳐지고 다른 화면이 조용히 0으로 보인다.
import { mapStockRow, sortRows, nextSort, parseNum } from '@/lib/research-rows';

const REPO_OWNER = "hoonnamkoong";
const REPO_NAME = "stockbot";
const WORKFLOW_ID = "scraper.yml";

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
            const mappedData = (data.stocks || []).map(mapStockRow);
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

    const handleSort = (key: string) => setSortConfig(prev => nextSort(prev, key));

    const sortData = (data: any[]) => sortRows(data, sortConfig);

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
