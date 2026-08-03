'use client';

import { Suspense, useState, useEffect, useRef, useCallback } from 'react';
import dynamic from 'next/dynamic';
import { useDisclosure, useMediaQuery, useInterval } from '@mantine/hooks';
import { useSearchParams } from 'next/navigation';
import {
    Container, Title, Text, Paper, Group, Stack, SimpleGrid,
    Badge, Button, Tabs, TextInput, NumberInput,
    Select, Switch, Notification, LoadingOverlay, Modal, PinInput, Affix, Transition, Box, Divider, Alert
} from '@mantine/core';
import { 
    IconCoin, IconClock, IconChartBar, IconActivity, IconCheck, IconX, 
    IconAlertTriangle, IconSearch, IconAdjustments, IconRefresh, 
    IconTimeline, IconRobot, IconAlertCircle, IconTrash, IconPlayerPlay, 
    IconDeviceMobile, IconHistory, IconChevronUp, IconChevronDown, IconPlus, IconDna 
} from '@tabler/icons-react';
import axios from 'axios';
import { signOut } from 'next-auth/react';
import { buildPriceMap, summarizeAccount, summarizeProgram, summarizeTurn } from '@/lib/real-account-summary';
import { SIM_REGISTRY } from '@/lib/sim-registry.generated';
import PortfolioTable from './PortfolioTable';
import TradeHistoryTable from './TradeHistoryTable';
import SimCard from './SimCard';
import { useProgramTrading } from './useProgramTrading';
// [V8.9.9.22] 차트 라이브러리 SSR 충돌 방지를 위한 동적 임포트 적용
const StrategyRadarChart = dynamic(() => import('../components/StrategyRadarChart'), { 
    ssr: false,
    loading: () => <div style={{ height: 350, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>차트 로딩 중...</div>
});

interface Holding {
    name: string;
    qty: number;
    price: number;
    avg_price: number;
    pl_rate: number;
    pl_amount: number;
    code: string;
}

interface BalanceData {
    deposit: number;
    deposit_d2?: number;
    total_asset: number;
    holdings: Holding[];
    error?: string;
    sync_status?: string;
}

interface StockItem {
    code: string;
    name: string;
}

function TradeContent() {
    const [balance, setBalance] = useState<BalanceData | null>(null);
    const [stocks, setStocks] = useState<StockItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [orderLoading, setOrderLoading] = useState(false);
    const [notification, setNotification] = useState<{ title: string, msg: string, color: string } | null>(null);
    const [geminiBalance, setGeminiBalance] = useState<any>(null);
    const [geminiLoading, setGeminiLoading] = useState(false);
    const [reservations, setReservations] = useState<any[]>([]);

    // Order Form
    const [orderType, setOrderType] = useState<string | null>('buy');
    const [code, setCode] = useState('');
    const [qty, setQty] = useState<number | string>(1);
    const [price, setPrice] = useState<number | string>(0);

    // Reservation Time
    const [resHour, setResHour] = useState<number | string>(15);
    const [resMin, setResMin] = useState<number | string>(15);

    // Security (PIN)
    const [pinModalOpen, setPinModalOpen] = useState(false);
    const [pin, setPin] = useState('');
    const [pendingAction, setPendingAction] = useState<{ isReservation: boolean } | null>(null);
    const [history, setHistory] = useState<any[]>([]);
    const [historyLoading, setHistoryLoading] = useState(false);
    
    // AI Reason Modal
    const [reasonModalOpen, setReasonModalOpen] = useState(false);
    const [selectedReason, setSelectedReason] = useState({ title: '', content: '' });

    // Multi-select for Portfolio
    const [selectedCodes, setSelectedCodes] = useState<string[]>([]);
    const [bulkActionType, setBulkActionType] = useState<{ type: 'immediate' | 'reservation' } | null>(null);

    // 시뮬레이터 리셋
    const [resetCash, setResetCash] = useState<number | ''>(3000000);
    const [resetConfirmOpen, setResetConfirmOpen] = useState(false);
    const [resetBusy, setResetBusy] = useState(false);

    const pinContainerRef = useRef<HTMLDivElement>(null);
    const searchParams = useSearchParams();

    const showNotify = useCallback((title: string, msg: string, color: string) => {
        setNotification({ title, msg, color });
        setTimeout(() => setNotification(null), 5000);
    }, []);

    // 프로그램 매매(실거래 문)는 상태 14개를 훅이 들고 있다. 이름은 그대로라 JSX는 모른다.
    const {
        programEnabled, programSim, setProgramSim,
        programBudget, setProgramBudget, programConfirmedBudget,
        programSims, programValid, programBusy,
        programPinOpen, setProgramPinOpen, programPin, setProgramPin,
        programPositions, programRealizedPnl, programLedgerOk,
        programTurn, programLastTurn, programUnreconciled,
        submitProgram, onToggleProgram,
    } = useProgramTrading(showNotify);

    const fetchBalance = useCallback(async (retryCount = 0, silent = false) => {
        if (typeof window === 'undefined') return;
        if (!silent) setLoading(true);
        try {
            const res = await fetch(`/api/portfolio/real?v=57&cb=${Date.now()}`);
            const data = await res.json().catch(() => ({ error: '서버 응답이 JSON이 아닙니다.' }));
            setBalance(data);
            if (data.error && !silent) showNotify('API Error', data.error, 'red');
        } catch (error: any) {
            if (retryCount < 1) setTimeout(() => fetchBalance(retryCount + 1, silent), 2000);
            else if (!silent) showNotify('Fetch Error', '실시간 계좌 정보를 가져오지 못했습니다.', 'red');
        } finally {
            if (!silent) setLoading(false);
        }
    }, [showNotify]);

    const fetchSimulationStats = useCallback(async () => {
        if (typeof window === 'undefined') return;
        setGeminiLoading(true);
        try {
            const res = await fetch(`/api/simulation/stats?v=86&cb=${Date.now()}`);
            const data = await res.json();
            setGeminiBalance(data);
        } catch (e) {
            console.error(e);
        } finally {
            setGeminiLoading(false);
        }
    }, []);

    const fetchHistory = useCallback(async () => {
        if (typeof window === 'undefined') return;
        setHistoryLoading(true);
        try {
            const res = await fetch(`/api/trade/history?cb=${Date.now()}`);
            const data = await res.json();
            if (data.success) setHistory(data.data);
        } catch (e) {
            console.error(e);
        } finally {
            setHistoryLoading(false);
        }
    }, []);

    const fetchStocks = useCallback(async () => {
        if (typeof window === 'undefined') return;
        try {
            const res = await axios.get('/api/stocks/list');
            if (res.data.stocks) setStocks(res.data.stocks);
        } catch (error) {}
    }, []);

    const fetchReservations = useCallback(async () => {
        if (typeof window === 'undefined') return;
        try {
            const res = await axios.get('/api/trade/reservation');
            setReservations(res.data.data || []);
        } catch (error) {}
    }, []);

    useEffect(() => {
        if (typeof window === 'undefined') return;
        fetchBalance();
        fetchStocks();
        fetchReservations();
        fetchSimulationStats();
        fetchHistory();
        const codeParam = searchParams.get('code');
        if (codeParam) setCode(codeParam);
    }, [searchParams, fetchBalance, fetchStocks, fetchReservations, fetchSimulationStats, fetchHistory]);

    // [V8.9.9.17] PIN 모달 오픈 시 강제 포커스 보강 (다단계 시도)
    useEffect(() => {
        if (pinModalOpen) {
            const focusInput = () => {
                const el = document.querySelector('input[type="password"]') as HTMLInputElement || 
                           document.getElementById('pin-input-0') as HTMLInputElement;
                if (el) {
                    el.focus();
                    return true;
                }
                return false;
            };

            // 1차: 즉시 시도
            focusInput();
            
            // 2차: 애니메이션 종료 시점(250ms)에 다시 시도
            const timer = setTimeout(focusInput, 250);
            return () => clearTimeout(timer);
        }
    }, [pinModalOpen]);

    const balancePoller = useInterval(() => fetchBalance(0, true), 30000);
    useEffect(() => {
        balancePoller.start();
        return () => balancePoller.stop();
    }, [balancePoller]);

    const handleOrder = async (isReservation: boolean) => {
        if (!code || !qty) {
            showNotify('Error', '종목과 수량을 입력하세요.', 'red');
            return;
        }
        setPendingAction({ isReservation });
        setPin('');
        setPinModalOpen(true);
    };

    const confirmOrder = async () => {
        if (!pendingAction) return;
        const { isReservation } = pendingAction;
        setPinModalOpen(false);
        setOrderLoading(true);
        try {
            const endpoint = isReservation ? '/api/trade/reservation' : '/api/trade/order';
            const payload: any = { code, qty, price, side: orderType, pin };
            if (isReservation) payload.time = `${resHour}:${resMin}`;
            const res = await axios.post(endpoint, payload);
            if (res.data.success) {
                showNotify('성공', isReservation ? '예약 완료' : '주문 완료', 'green');
                fetchBalance();
                fetchReservations();
                fetchHistory();
            } else {
                showNotify('실패', res.data.error, 'red');
            }
        } catch (error: any) {
            showNotify('Error', error.response?.data?.error || error.message, 'red');
        } finally {
            setOrderLoading(false);
            setPendingAction(null);
        }
    };

    const handleBulkOrder = (isReservation: boolean) => {
        if (selectedCodes.length === 0) {
            showNotify('Error', '매도할 종목을 선택하세요.', 'red');
            return;
        }
        setBulkActionType({ type: isReservation ? 'reservation' : 'immediate' });
        setPinModalOpen(true);
    };

    const confirmBulkOrder = async () => {
        if (!bulkActionType || !balance) return;
        setPinModalOpen(false);
        setOrderLoading(true);
        
        let successCount = 0;
        let failCount = 0;

        for (const targetCode of selectedCodes) {
            const holding = balance.holdings.find(h => h.code === targetCode);
            if (!holding) continue;

            try {
                const isReservation = bulkActionType.type === 'reservation';
                const endpoint = isReservation ? '/api/trade/reservation' : '/api/trade/order';
                const payload: any = { 
                    code: targetCode, 
                    qty: holding.qty, 
                    price: 0, // 시장가 전량 매도
                    side: 'sell', 
                    pin 
                };
                if (isReservation) payload.time = `${resHour}:${resMin}`;
                
                const res = await axios.post(endpoint, payload);
                if (res.data.success) successCount++;
                else failCount++;
            } catch (e) {
                failCount++;
            }
        }

        showNotify('일괄 처리 결과', `성공: ${successCount}, 실패: ${failCount}`, failCount > 0 ? 'orange' : 'green');
        setSelectedCodes([]);
        fetchBalance();
        fetchReservations();
        fetchHistory();
        setOrderLoading(false);
        setBulkActionType(null);
    };

    const handleReset = async () => {
        if (typeof resetCash !== 'number' || !Number.isInteger(resetCash) || resetCash < 100000 || resetCash > 1000000000) {
            showNotify('리셋 불가', '예수금은 10만 ~ 10억 사이 정수여야 합니다.', 'red');
            setResetConfirmOpen(false);
            return;
        }
        setResetBusy(true);
        try {
            const res = await fetch('/api/simulation/reset', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cash: resetCash }),
            });
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.error || `HTTP ${res.status}`);
            showNotify('리셋 완료', `${data.sims.length}개 시뮬레이터를 ${resetCash.toLocaleString()}원으로 초기화했습니다. 대시보드 반영까지 잠시 걸릴 수 있습니다.`, 'green');
        } catch (e: any) {
            showNotify('리셋 실패', e?.message ?? String(e), 'red');
        } finally {
            setResetBusy(false);
            setResetConfirmOpen(false);
        }
    };

    const cancelReservation = async (id: string) => {
        if (!confirm('예약을 취소하시겠습니까?')) return;
        try {
            await axios.delete(`/api/trade/reservation?id=${id}`);
            showNotify('성공', '예약이 취소되었습니다.', 'green');
            fetchReservations(); // 취소 후 즉시 목록 갱신
        } catch (error: any) {
            showNotify('실패', error.response?.data?.error || '취소 중 오류 발생', 'red');
        }
    };

    // --- Helper UI Renderers ---

    // 표에서 올라오는 조작 셋. 표 컴포넌트는 상태를 모르고 이 셋만 부른다.
    const toggleSelectedCode = (code: string, checked: boolean) => {
        setSelectedCodes(prev => checked ? [...prev, code] : prev.filter(c => c !== code));
    };
    const pickCode = (code: string, name: string) => {
        setCode(code);
        showNotify('Info', `${name} 종목이 선택되었습니다.`, 'blue');
    };
    const showReason = (title: string, content: string) => {
        setSelectedReason({ title, content });
        setReasonModalOpen(true);
    };

    function renderRealPortfolioSection() {
        // 숫자는 전부 lib이 만든다(테스트 있음). 여기는 배치만 한다.
        const { deposit, holdings, totalEval, totalPL, roiPct } = summarizeAccount(balance);
        const priceMap = buildPriceMap(balance?.holdings);
        const program = summarizeProgram({
            positions: programPositions,
            prices: priceMap,
            realizedPnl: programRealizedPnl,
            budget: programConfirmedBudget,
        });
        const turn = summarizeTurn({
            turn: programTurn,
            lastTurn: programLastTurn,
            positions: programPositions,
            prices: priceMap,
            programEnabled,
        });

        // 태그 → 표시명. 하위 전략도 매매 가능 심이라 programSims에 이름이 들어있다.
        const tagLabel = (tag: string) =>
            tag === 'cash' ? '현금(하락장)' : (programSims.find(s => s.id === tag)?.name ?? tag);

        return (
            <Stack gap="md">
                <Paper p="md" withBorder radius="md" style={{ position: 'relative' }}>
                    <LoadingOverlay visible={loading} zIndex={10} overlayProps={{ radius: 'sm', blur: 2 }} />
                    <Group justify="space-between" mb="sm">
                        <Title order={4}><IconCoin size={20} style={{ marginBottom: -4, marginRight: 8 }}/>실전 계좌 (Main KIS)</Title>
                        <Group gap="xs">
                            <Badge color="blue" variant="light">Real-Time</Badge>
                            <Button variant="subtle" size="xs" leftSection={<IconRefresh size={14}/>} onClick={() => fetchBalance()}>새로고침</Button>
                        </Group>
                    </Group>
                    {/* 프로그램 매매: ON 시 선택 심이 실계좌를 자동 운용 / OFF 시 수동만 */}
                    <Group gap="sm" align="flex-end" mb="sm" wrap="wrap" p={8}
                        style={{ borderRadius: 8, background: programEnabled ? 'var(--mantine-color-red-0)' : 'var(--mantine-color-gray-0)' }}>
                        <Switch
                            checked={programEnabled}
                            onChange={(e) => onToggleProgram(e.currentTarget.checked)}
                            disabled={programBusy}
                            color="red" size="md"
                            label={<Text size="sm" fw={700}>프로그램 매매 {programEnabled ? 'ON' : 'OFF'}</Text>}
                        />
                        <Select
                            label="프로그램 선택" size="xs" w={210} searchable
                            placeholder={programSims.length ? '매매 심 선택' : '목록 로딩...'}
                            data={programSims.map(s => ({ value: s.id, label: s.name }))}
                            value={programSim}
                            onChange={setProgramSim}
                            disabled={programEnabled || programBusy}
                        />
                        <NumberInput
                            label="프로그램 예산(원)" size="xs" w={160}
                            placeholder="예: 1000000"
                            value={programBudget}
                            onChange={(v) => setProgramBudget(typeof v === 'number' ? v : '')}
                            onBlur={() => { if (programEnabled) return; }}
                            disabled={programEnabled || programBusy}
                            min={0} step={100000} thousandSeparator=","
                        />
                        {programEnabled && !programValid && (
                            <Badge color="red" variant="filled">선택 심이 목록에서 사라짐 — 파이프라인 자동 OFF</Badge>
                        )}
                        {programEnabled && programValid && (
                            <Text size="xs" c="red" fw={700}>● 실계좌 자동 운용 중</Text>
                        )}
                    </Group>
                    {/* 계좌 전체 지표 — 프로그램 지표와 같은 4칸 격자를 써서 열이 세로로 정렬된다 */}
                    <Divider mb="sm" label="계좌 전체" labelPosition="left" />
                    <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="md" mb="md">
                        <Stack gap={2}>
                            <Text size="xs" c="dimmed">예수금 (잔고)</Text>
                            <Text fw={700} size="lg">
                                {(Number(deposit) || 0).toLocaleString()} 원
                                {balance?.deposit_d2 != null && (
                                    <Text span size="sm" c="dimmed" fw={400}>
                                        {' '}(D+2 {(Number(balance.deposit_d2) || 0).toLocaleString()} 원)
                                    </Text>
                                )}
                            </Text>
                        </Stack>
                        <Stack gap={2}>
                            <Text size="xs" c="dimmed">총 자산수익률</Text>
                            {roiPct === null ? (
                                <Text fw={800} size="lg" c="dimmed">측정 불가</Text>
                            ) : (
                                <Text fw={800} size="lg" c={totalPL >= 0 ? 'red' : 'blue'}>
                                    {totalPL >= 0 ? '+' : ''}{roiPct.toFixed(2)}%
                                </Text>
                            )}
                        </Stack>
                        <Stack gap={2}>
                            <Text size="xs" c="dimmed">총 평가손익</Text>
                            <Text fw={700} size="lg" c={totalPL >= 0 ? 'red' : 'blue'}>
                                {totalPL >= 0 ? '+' : ''}{(Number(totalPL) || 0).toLocaleString()} 원
                            </Text>
                        </Stack>
                        <Stack gap={2}>
                            <Text size="xs" c="dimmed">보유 종목 총액</Text>
                            <Text fw={700} size="lg">{Math.round(totalEval).toLocaleString()} 원</Text>
                        </Stack>
                    </SimpleGrid>
                    {program.hasData && (
                        <>
                            <Divider mb="sm" label="프로그램 매매" labelPosition="left" />
                            {programUnreconciled.length > 0 && (
                                <Alert color="orange" variant="light" mb="md" title="누적 수익률이 실제와 어긋납니다">
                                    <Text size="sm">
                                        실계좌에서 사라졌지만 손익을 계상하지 못한 청산이 {programUnreconciled.length}건 있습니다.
                                        체결가가 기록에 없어 손익을 계산할 수 없으므로, 아래 누적 수치에는 이 금액이 빠져 있습니다.
                                    </Text>
                                    <Stack gap={2} mt={6}>
                                        {programUnreconciled.map((u, i) => (
                                            <Text key={`${u.code}-${u.date}-${i}`} size="xs" c="dimmed">
                                                {u.date} · {u.name}({u.code}) {u.quantity.toLocaleString()}주 ·
                                                매입원가 {Math.round(u.cost_basis).toLocaleString()}원 — 손익 미정산
                                            </Text>
                                        ))}
                                    </Stack>
                                </Alert>
                            )}
                            <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="md" mb="md">
                                <Stack gap={2}>
                                    <Text size="xs" c="dimmed">수익률 (누적)</Text>
                                    {programLedgerOk && program.ratePct !== null ? (
                                        <Text fw={800} size="lg" c={program.totalPnl >= 0 ? 'red' : 'blue'}>
                                            {program.totalPnl >= 0 ? '+' : ''}{program.ratePct.toFixed(2)}%
                                        </Text>
                                    ) : (
                                        <Text fw={800} size="lg" c="dimmed">측정 불가</Text>
                                    )}
                                </Stack>
                                <Stack gap={2}>
                                    <Text size="xs" c="dimmed">평가손익 (누적)</Text>
                                    {programLedgerOk ? (
                                        <Text fw={700} size="lg" c={program.totalPnl >= 0 ? 'red' : 'blue'}>
                                            {program.totalPnl >= 0 ? '+' : ''}{Math.round(program.totalPnl).toLocaleString()} 원
                                        </Text>
                                    ) : (
                                        <Text fw={700} size="lg" c="dimmed">측정 불가</Text>
                                    )}
                                </Stack>
                                <Stack gap={2}>
                                    <Text size="xs" c="dimmed">보유 종목 총액</Text>
                                    {programLedgerOk ? (
                                        <Text fw={700} size="lg">{Math.round(program.holdingsValue).toLocaleString()} 원</Text>
                                    ) : (
                                        <Text fw={700} size="lg" c="dimmed">측정 불가</Text>
                                    )}
                                </Stack>
                                <Stack gap={2}>
                                    <Text size="xs" c="dimmed">
                                        턴당 수익률{turn.has && !turn.isLive ? ' (직전 턴)' : ''}
                                    </Text>
                                    {!turn.has ? (
                                        <Text size="sm" c="dimmed" mt={4}>턴 없음 — 껐다 켜면 시작</Text>
                                    ) : !turn.measurable ? (
                                        <Text fw={800} size="lg" c="dimmed">측정 불가</Text>
                                    ) : (
                                        <>
                                            <Text fw={800} size="lg" c={turn.pnl >= 0 ? 'red' : 'blue'}>
                                                {turn.pnl >= 0 ? '+' : ''}{turn.ratePct.toFixed(2)}%
                                            </Text>
                                            <Text size="xs" c="dimmed">
                                                {turn.pnl >= 0 ? '+' : ''}{Math.round(turn.pnl).toLocaleString()} 원 / 원금 {Math.round(turn.capital).toLocaleString()} 원
                                            </Text>
                                        </>
                                    )}
                                </Stack>
                            </SimpleGrid>
                        </>
                    )}
                    {turn.has && (
                        <Stack gap={6} mb="md">
                            <Text size="xs" c="dimmed">턴당 SIM별 수익률 (기여도 — 합계 = 턴 수익률)</Text>
                            {turn.pendingFirstRun ? (
                                <Text size="sm" c="dimmed">전략별 집계 대기 — 다음 파이프라인 런부터</Text>
                            ) : !turn.measurable ? (
                                <Text size="sm" c="dimmed">측정 불가</Text>
                            ) : turn.tagRows.length === 0 ? (
                                <Text size="sm" c="dimmed">아직 확정된 손익이 없습니다</Text>
                            ) : (
                                <Group gap="xs" wrap="wrap">
                                    {turn.tagRows.map(([tag, pnl]) => (
                                        <Badge key={tag} size="lg" radius="sm" variant="light"
                                            color={pnl >= 0 ? 'red' : 'blue'}
                                            style={{ textTransform: 'none', fontWeight: 600 }}>
                                            {tagLabel(tag)} {pnl >= 0 ? '+' : ''}
                                            {(turn.capital > 0 ? (pnl / turn.capital) * 100 : 0).toFixed(2)}%
                                            {' · '}{pnl >= 0 ? '+' : ''}{Math.round(pnl).toLocaleString()}원
                                        </Badge>
                                    ))}
                                </Group>
                            )}
                        </Stack>
                    )}
                    <Divider mb="xs" label="보유 포트폴리오 (일괄 매도 가능)" labelPosition="center" />
                    <PortfolioTable
                        holdings={holdings}
                        isReal
                        maxHeight="calc(100vh - 320px)"
                        selectedCodes={selectedCodes}
                        onToggleCode={toggleSelectedCode}
                        onPickCode={pickCode}
                    />
                    {selectedCodes.length > 0 && (
                        <Group mt="md" grow>
                            <Button color="red" leftSection={<IconTrash size={16}/>} onClick={() => handleBulkOrder(false)}>
                                {selectedCodes.length}건 즉시 매도
                            </Button>
                            <Button color="violet" leftSection={<IconClock size={16}/>} onClick={() => handleBulkOrder(true)}>
                                {selectedCodes.length}건 예약 매도
                            </Button>
                        </Group>
                    )}
                </Paper>
                <Paper p="md" withBorder radius="md">
                    <Title order={5} mb="sm"><IconHistory size={18} style={{ marginBottom: -4, marginRight: 8 }}/>실거래 매매 히스토리</Title>
                    <TradeHistoryTable history={history} targetType="real" maxHeight={400} onShowReason={showReason} />
                </Paper>
            </Stack>
        );
    }

    function renderSimulationTripod() {
        if (!geminiBalance) return null;
        // 매니페스트에서 파생한다. type은 매니페스트 id이고 매매 기록 API가 각 행에
        // 붙이는 값과 같아야 한다 — 어긋나면 이 카드의 기록 표가 조용히 빈다.
        const simConfigs = SIM_REGISTRY.map((s) => ({
            id: s.uiKey, key: s.uiKey, label: s.label, color: s.color, type: s.id,
        }));
        return (
            <Stack gap="xl">
                <Group justify="space-between">
                    <Title order={3}><IconRobot size={24} style={{ marginBottom: -4, marginRight: 8 }}/>{simConfigs.length}-Track 지능형 시뮬레이션</Title>
                    <Button variant="outline" size="sm" leftSection={<IconRefresh size={16}/>} onClick={() => { fetchSimulationStats(); fetchHistory(); }}>전체 데이터 갱신</Button>
                </Group>
                <Paper p="sm" withBorder radius="md" style={{ background: 'var(--mantine-color-red-0)' }}>
                    <Group justify="space-between" wrap="wrap" gap="sm">
                        <Text size="sm" fw={700} c="red">시뮬레이터 리셋</Text>
                        <Group gap="sm" wrap="wrap">
                            <NumberInput
                                size="xs" w={160}
                                placeholder="예수금(원)"
                                value={resetCash}
                                onChange={(v) => setResetCash(typeof v === 'number' ? v : '')}
                                min={100000} max={1000000000} step={100000} thousandSeparator=","
                                disabled={resetBusy}
                            />
                            <Button color="red" size="xs" onClick={() => setResetConfirmOpen(true)} disabled={resetBusy} loading={resetBusy}>
                                전체 리셋
                            </Button>
                        </Group>
                    </Group>
                </Paper>
                <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
                    {simConfigs.map((sim) => (
                        <SimCard
                            key={sim.id}
                            uiKey={sim.key}
                            label={sim.label}
                            color={sim.color}
                            type={sim.type}
                            stats={geminiBalance[sim.key]?.raw || {}}
                            portfolio={geminiBalance[sim.key]?.portfolio || {}}
                            history={history}
                            onPickCode={pickCode}
                            onShowReason={showReason}
                        />
                    ))}
                </SimpleGrid>
            </Stack>
        );
    }

    function renderTrading() {
        return (
            <Paper p="md" withBorder radius="md">
                <Title order={4} mb="md">Place Order</Title>
                <Tabs defaultValue="immediate">
                    <Tabs.List mb="md">
                        <Tabs.Tab value="immediate">Immediate</Tabs.Tab>
                        <Tabs.Tab value="reservation">Reservation</Tabs.Tab>
                    </Tabs.List>
                    <div style={{ position: 'relative' }}>
                        <LoadingOverlay visible={orderLoading} zIndex={10} overlayProps={{ radius: 'sm', blur: 2 }} />
                        <Group mb="sm" grow>
                            <Button variant={orderType === 'buy' ? 'filled' : 'outline'} color="red" onClick={() => setOrderType('buy')}>BUY</Button>
                            <Button variant={orderType === 'sell' ? 'filled' : 'outline'} color="blue" onClick={() => setOrderType('sell')}>SELL</Button>
                        </Group>
                        <Stack gap="xs">
                            <Select label="Stock" placeholder="종목 선택" searchable
                                data={stocks.map(s => ({ value: s.code, label: `${s.name} (${s.code})` }))}
                                value={code} onChange={(val) => setCode(val || '')} />
                            <NumberInput label="Quantity" min={1} value={qty} onChange={(val) => setQty(Number(val) || 1)} />
                            <NumberInput label="Price (0=Market)" min={0} value={price} onChange={(val) => setPrice(Number(val) || 0)} />
                        </Stack>
                        <Tabs.Panel value="immediate" pt="md">
                            <Button fullWidth size="lg" onClick={() => handleOrder(false)} color={orderType === 'buy' ? 'red' : 'blue'}>주문 전송</Button>
                        </Tabs.Panel>
                        <Tabs.Panel value="reservation" pt="md">
                            <Group grow mb="sm">
                                <NumberInput label="Hour" min={0} max={23} value={resHour} onChange={(val) => setResHour(Number(val) || 15)} />
                                <NumberInput label="Min" min={0} max={59} value={resMin} onChange={(val) => setResMin(Number(val) || 15)} />
                            </Group>
                            <Button fullWidth size="lg" color="violet" onClick={() => handleOrder(true)}>예약 등록</Button>
                        </Tabs.Panel>
                    </div>
                </Tabs>
                {reservations.length > 0 && (
                    <Stack mt="xl">
                        <Text size="sm" fw={700}>Active Reservations</Text>
                        {reservations.map(r => (
                            <Paper key={r.id} p="xs" withBorder>
                                <Group justify="space-between">
                                    <Text size="xs">{r.time} | {r.code} | {r.side}</Text>
                                    <Button size="xs" variant="subtle" color="red" onClick={() => cancelReservation(r.id)}>취소</Button>
                                </Group>
                            </Paper>
                        ))}
                    </Stack>
                )}
            </Paper>
        );
    }

    return (
        <Container fluid py="xl" px="xl">
            {notification && (
                <Notification title={notification.title} color={notification.color} onClose={() => setNotification(null)}
                    style={{ position: 'fixed', top: 20, right: 20, zIndex: 9999 }}>
                    {notification.msg}
                </Notification>
            )}
            <Modal opened={programPinOpen} onClose={() => setProgramPinOpen(false)} title="프로그램 매매 활성화 — PIN 확인" centered zIndex={2000}>
                <Stack>
                    <Text size="sm" c="dimmed">
                        선택 심 <b>{programSims.find(s => s.id === programSim)?.name ?? programSim}</b> 을(를) 예산{' '}
                        <b>{(Number(programBudget) || 0).toLocaleString()}원</b> 한도로 <b style={{ color: '#fa5252' }}>실계좌에서 자동 운용</b>합니다.
                        수동 보유분은 건드리지 않습니다. PIN을 입력하세요.
                    </Text>
                    <PinInput data-autofocus length={4} type="number" mask value={programPin} onChange={setProgramPin}
                        onComplete={() => submitProgram(true, programPin)} />
                    <Group justify="flex-end">
                        <Button variant="default" onClick={() => setProgramPinOpen(false)}>취소</Button>
                        <Button color="red" onClick={() => submitProgram(true, programPin)} disabled={programPin.length !== 4 || programBusy}>활성화</Button>
                    </Group>
                </Stack>
            </Modal>

            <Modal opened={pinModalOpen} onClose={() => setPinModalOpen(false)} title="Security PIN" centered zIndex={2000}>
                <Stack align="center" py="md" ref={pinContainerRef}>
                    <Text size="sm">보안 PIN 4자리를 입력하세요.</Text>
                    <PinInput id="pin-input" data-autofocus length={4} type="number" mask value={pin} onChange={setPin} onComplete={bulkActionType ? confirmBulkOrder : confirmOrder} />
                    <Group mt="md">
                        <Button variant="default" onClick={() => setPinModalOpen(false)}>취소</Button>
                        <Button color="blue" onClick={bulkActionType ? confirmBulkOrder : confirmOrder} disabled={pin.length !== 4}>확인</Button>
                    </Group>
                </Stack>
            </Modal>

            <Modal opened={resetConfirmOpen} onClose={() => setResetConfirmOpen(false)} title="정말 초기화할까요?" centered zIndex={2000}>
                <Stack>
                    <Text size="sm">
                        {/* 개수·이름을 손으로 적으면 심이 늘 때마다 거짓말이 된다.
                            실제로 "9개(Sim1~7, Sim10)"로 남아 12개를 지우고 있었다. */}
                        <b>{SIM_REGISTRY.length}개</b> 시뮬레이터를{' '}
                        <b>{typeof resetCash === 'number' ? resetCash.toLocaleString() : '-'}원</b>으로 초기화하고
                        모든 거래기록을 삭제합니다. <b style={{ color: '#fa5252' }}>되돌릴 수 없습니다.</b>
                    </Text>
                    <Text size="xs" c="dimmed">
                        {SIM_REGISTRY.map((s) => s.label).join(' · ')}
                    </Text>
                    <Group justify="flex-end">
                        <Button variant="default" onClick={() => setResetConfirmOpen(false)} disabled={resetBusy}>취소</Button>
                        <Button color="red" onClick={handleReset} disabled={resetBusy} loading={resetBusy}>초기화</Button>
                    </Group>
                </Stack>
            </Modal>
            <Group justify="space-between" mb="lg">
                <Title order={2}>Stock Dashboard</Title>
                <Group gap="xs">
                    <Badge color="pink" variant="filled">V8.7.2-UI</Badge>
                    <Button component="a" href="/research" size="sm" variant="light">Research</Button>
                    <Button color="gray" variant="subtle" size="sm" onClick={() => signOut({ callbackUrl: '/login' })}>Out</Button>
                </Group>
            </Group>
            <Stack gap="lg" mb="xl">
                <Group grow align="flex-start" gap="lg" style={{ flexWrap: 'wrap' }}>
                    <Stack gap="md" style={{ flex: 1, minWidth: '320px' }}>
                        {renderRealPortfolioSection()}
                    </Stack>
                    <Stack gap="md" style={{ flex: 1, minWidth: '320px' }}>
                        {renderTrading()}
                    </Stack>
                </Group>
                <Divider my="md" label="Simulation Analysis" labelPosition="center" />
                {renderSimulationTripod()}
            </Stack>
            <Modal opened={reasonModalOpen} onClose={() => setReasonModalOpen(false)} title={selectedReason.title} size="lg">
                <Paper p="md" withBorder bg="gray.0">
                    <Text style={{ whiteSpace: 'pre-wrap' }} size="sm">{selectedReason.content}</Text>
                </Paper>
                <Group justify="flex-end" mt="md"><Button onClick={() => setReasonModalOpen(false)}>닫기</Button></Group>
            </Modal>
            <Box mt="xl">
                <StrategyRadarChart />
            </Box>
        </Container>
    );
}

// [V8.9.9.21] Deployment Re-trigger
export default function TradeClient() {
    return (
        <Suspense fallback={<LoadingOverlay visible />}>
            <TradeContent />
        </Suspense>
    );
}
