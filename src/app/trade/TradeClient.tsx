'use client';

import { Suspense, useState, useEffect, useRef, useCallback } from 'react';
import dynamic from 'next/dynamic';
import { useDisclosure, useMediaQuery, useInterval } from '@mantine/hooks';
import { useSearchParams } from 'next/navigation';
import {
    Container, Title, Text, Paper, Group, Stack,
    Table, Badge, Button, Tabs, TextInput, NumberInput,
    Select, Notification, LoadingOverlay, Modal, PinInput, Checkbox, Affix, Transition, ScrollArea, Box, Divider
} from '@mantine/core';
import { 
    IconCoin, IconClock, IconChartBar, IconActivity, IconCheck, IconX, 
    IconAlertTriangle, IconSearch, IconAdjustments, IconRefresh, 
    IconTimeline, IconRobot, IconAlertCircle, IconTrash, IconPlayerPlay, 
    IconDeviceMobile, IconHistory, IconChevronUp, IconChevronDown, IconPlus, IconDna 
} from '@tabler/icons-react';
import axios from 'axios';
import { signOut } from 'next-auth/react';
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

    const pinContainerRef = useRef<HTMLDivElement>(null);
    const searchParams = useSearchParams();

    const showNotify = useCallback((title: string, msg: string, color: string) => {
        setNotification({ title, msg, color });
        setTimeout(() => setNotification(null), 5000);
    }, []);

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

    function renderPortfolioTable(holdings: any[], isReal: boolean = false) {
        if (!holdings || holdings.length === 0) {
            return (
                <Box h={560} py="xl" style={{ textAlign: 'center', border: '1px dashed #ced4da', borderRadius: '8px', width: '100%', minWidth: isReal ? 650 : 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <Text c="dimmed">보유 종목이 없습니다.</Text>
                </Box>
            );
        }
        return (
            <ScrollArea h={560} offsetScrollbars>
                <Table striped highlightOnHover verticalSpacing="xs" style={{ minWidth: isReal ? 650 : 600 }}>
                    <Table.Thead>
                        <Table.Tr>
                            {isReal && <Table.Th style={{ width: 40, position: 'sticky', left: 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 2 }}></Table.Th>}
                            <Table.Th style={{ width: 120, position: 'sticky', left: isReal ? 40 : 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 1, borderRight: '1px solid #eee' }}>종목명</Table.Th>
                            <Table.Th style={{ textAlign: 'right' }}>수량</Table.Th>
                            <Table.Th style={{ textAlign: 'right' }}>평단가</Table.Th>
                            <Table.Th style={{ textAlign: 'right' }}>현재가</Table.Th>
                            <Table.Th style={{ textAlign: 'right' }}>체결금액</Table.Th>
                            <Table.Th style={{ textAlign: 'center' }}>수익률(%)</Table.Th>
                            <Table.Th style={{ textAlign: 'right' }}>손익(원)</Table.Th>
                        </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                        {holdings.map((h) => {
                            const avgPrice = h.avg_price || h.price || 0;
                            const currentPrice = h.current_price || h.price || 0; 
                            const plRate = h.pl_rate ?? 0;
                            const amount = (h.qty || h.quantity || 0) * avgPrice;
                            const plAmount = h.pl_amount ?? Math.round((currentPrice - avgPrice) * (h.qty || h.quantity || 0));
                            const isSelected = selectedCodes.includes(h.code);

                            return (
                                <Table.Tr key={h.code} style={{ cursor: isReal ? 'pointer' : 'default' }}>
                                    {isReal && (
                                        <Table.Td onClick={(e) => e.stopPropagation()} style={{ position: 'sticky', left: 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 2 }}>
                                            <Checkbox 
                                                checked={isSelected} 
                                                onChange={(event) => {
                                                    const checked = event.currentTarget.checked;
                                                    setSelectedCodes(prev => 
                                                        checked ? [...prev, h.code] : prev.filter(c => c !== h.code)
                                                    );
                                                }}
                                            />
                                        </Table.Td>
                                    )}
                                    <Table.Td 
                                        onClick={() => {
                                            setCode(h.code);
                                            showNotify('Info', `${h.name} 종목이 선택되었습니다.`, 'blue');
                                        }}
                                        style={{ cursor: 'pointer', position: 'sticky', left: isReal ? 40 : 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 1, borderRight: '1px solid #eee' }}
                                    >
                                        <Text size="sm" fw={700} truncate maw={100} c="blue" style={{ textDecoration: 'underline', textUnderlineOffset: '2px' }}>{h.name}</Text>
                                        <Text size="xs" c="dimmed">{h.code}</Text>
                                    </Table.Td>
                                    <Table.Td style={{ textAlign: 'right' }}>
                                        <Text size="sm">{(h.qty || h.quantity || 0).toLocaleString()}주</Text>
                                    </Table.Td>
                                    <Table.Td style={{ textAlign: 'right' }}>
                                        <Text size="sm">{Math.round(avgPrice).toLocaleString()}원</Text>
                                    </Table.Td>
                                    <Table.Td style={{ textAlign: 'right' }}>
                                        <Text size="sm" fw={500} c="teal">{Math.round(currentPrice).toLocaleString()}원</Text>
                                    </Table.Td>
                                    <Table.Td style={{ textAlign: 'right' }}>
                                        <Text size="sm" fw={700}>{Math.round(amount).toLocaleString()}원</Text>
                                    </Table.Td>
                                    <Table.Td style={{ textAlign: 'center' }}>
                                        <Badge color={plRate >= 0 ? 'red' : 'blue'} variant="filled" size="sm" style={{ width: 65 }}>
                                            {plRate >= 0 ? '+' : ''}{plRate.toFixed(2)}%
                                        </Badge>
                                    </Table.Td>
                                    <Table.Td style={{ textAlign: 'right' }}>
                                        <Text size="sm" fw={700} c={plAmount >= 0 ? 'red' : 'blue'}>
                                            {plAmount >= 0 ? '+' : ''}{Math.round(plAmount).toLocaleString()}
                                        </Text>
                                    </Table.Td>
                                </Table.Tr>
                            );
                        })}
                    </Table.Tbody>
                </Table>
            </ScrollArea>
        );
    }

    function renderHistoryTable(targetType: string) {
        const filtered = history.filter(h => h.type === targetType).slice(0, 100);
        if (filtered.length === 0) {
            return (
                <Box h={560} py="md" style={{ textAlign: 'center', width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <Text size="xs" c="dimmed">최근 거래 내역이 없습니다.</Text>
                </Box>
            );
        }
        return (
            <ScrollArea h={560} offsetScrollbars>
                <Table striped highlightOnHover stickyHeader verticalSpacing="xs" style={{ minWidth: 500 }}>
                    <Table.Thead>
                        <Table.Tr>
                            <Table.Th style={{ fontSize: '11px' }}>일시</Table.Th>
                            <Table.Th style={{ fontSize: '11px', position: 'sticky', left: 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 1, borderRight: '1px solid #eee' }}>종목</Table.Th>
                            <Table.Th style={{ fontSize: '11px' }}>구분</Table.Th>
                            <Table.Th style={{ fontSize: '11px', textAlign: 'right' }}>체결가</Table.Th>
                            <Table.Th style={{ fontSize: '11px', textAlign: 'right' }}>수량</Table.Th>
                            {targetType === 'real' && <Table.Th style={{ fontSize: '11px', textAlign: 'center' }}>ROI(%)</Table.Th>}
                            {targetType !== 'real' && <Table.Th style={{ fontSize: '11px' }}>판단 사유</Table.Th>}
                        </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                        {filtered.map((h, i) => (
                            <Table.Tr key={i}>
                                <Table.Td style={{ whiteSpace: 'nowrap' }}>
                                    <Text size="xs" c="dimmed" style={{ fontSize: '10px' }}>{h.time.split(' ')[0].slice(5)}</Text>
                                    <Text size="xs" fw={500} style={{ fontSize: '10px' }}>{h.time.split(' ')[1]}</Text>
                                </Table.Td>
                                <Table.Td style={{ position: 'sticky', left: 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 1, borderRight: '1px solid #eee' }}>
                                    <Text size="xs" fw={700}>{h.symbol.split('(')[0]}</Text>
                                </Table.Td>
                                <Table.Td>
                                    <Badge color={h.action === 'BUY' ? 'red' : 'blue'} variant="light" size="xs">
                                        {h.action === 'BUY' ? '매수' : '매도'}
                                    </Badge>
                                </Table.Td>
                                <Table.Td style={{ textAlign: 'right' }}><Text size="xs">{h.price}</Text></Table.Td>
                                <Table.Td style={{ textAlign: 'right' }}><Text size="xs">{h.qty}</Text></Table.Td>
                                {targetType === 'real' && (
                                    <Table.Td style={{ textAlign: 'center' }}>
                                        {h.roi && h.roi !== '-' ? (
                                            <Badge color={h.roi?.startsWith('+') ? 'red' : h.roi?.startsWith('-') ? 'blue' : 'gray'} variant="light" size="xs">
                                                {h.roi}
                                            </Badge>
                                        ) : (
                                            <Text size="xs" c="dimmed">-</Text>
                                        )}
                                    </Table.Td>
                                )}
                                {targetType !== 'real' && (
                                    <Table.Td>
                                        <Button variant="subtle" size="compact-xs" onClick={() => {
                                            setSelectedReason({ title: `${h.symbol} 판단 근거`, content: h.reason });
                                            setReasonModalOpen(true);
                                        }}>
                                            <Text size="xs" truncate maw={80}>{h.reason || '사유 없음'}</Text>
                                        </Button>
                                    </Table.Td>
                                )}
                            </Table.Tr>
                        ))}
                    </Table.Tbody>
                </Table>
            </ScrollArea>
        );
    }

    function renderRealPortfolioSection() {
        const deposit = balance?.deposit ?? 0;
        // [V8.9.9 Hotfix] 매도 완료되어 잔고가 0주인 종목은 포트폴리오(UI)에서 제외 필터링
        const holdings = (balance?.holdings || []).filter((h: any) => Number(h.qty || h.quantity || 0) > 0);
        const totalEval = holdings.reduce((sum: any, h: any) => sum + ((h.price || 0) * (h.qty || 0)), 0);
        const totalPL = holdings.reduce((sum: any, h: any) => sum + (h.pl_amount || 0), 0);

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
                    <Group grow mb="md" align="flex-end">
                        <Stack gap={2}>
                            <Text size="xs" c="dimmed">예수금 (잔고)</Text>
                            <Text fw={700} size="lg">{(Number(deposit) || 0).toLocaleString()} 원</Text>
                        </Stack>
                        <Stack gap={2}>
                            <Text size="xs" c="dimmed">총 자산수익률</Text>
                            <Text fw={800} size="lg" c={totalPL >= 0 ? 'red' : 'blue'}>
                                {totalPL >= 0 ? '+' : ''}{(totalEval > 0 ? (totalPL / (totalEval - totalPL)) * 100 : 0).toFixed(2)}%
                            </Text>
                        </Stack>
                        <Stack gap={2}>
                            <Text size="xs" c="dimmed">총 평가손익</Text>
                            <Text fw={700} size="lg" c={totalPL >= 0 ? 'red' : 'blue'}>
                                {totalPL >= 0 ? '+' : ''}{(Number(totalPL) || 0).toLocaleString()} 원
                            </Text>
                        </Stack>
                    </Group>
                    <Divider mb="xs" label="보유 포트폴리오 (일괄 매도 가능)" labelPosition="center" />
                    {renderPortfolioTable(holdings, true)}
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
                    {renderHistoryTable('real')}
                </Paper>
            </Stack>
        );
    }

    function renderSimulationTripod() {
        if (!geminiBalance) return null;
        const simConfigs = [
            { id: 'sim1', key: 'sim1', label: '심리 괴리형 (Sim 1)',     color: 'blue',   type: 'sim_psych' },
            { id: 'sim2', key: 'sim2', label: '수급 동승형 (Sim 2)',     color: 'violet', type: 'sim_spillover' },
            { id: 'sim3', key: 'sim3', label: '스마트 리스크형 (Sim 3)', color: 'red',    type: 'sim_risk' },
            { id: 'sim4', key: 'sim4', label: '상승 모멘텀형 (Sim 4)',   color: 'green',  type: 'sim_bull' },
            { id: 'sim5', key: 'sim5', label: '추세 눌림목형 (Sim 5)',   color: 'orange', type: 'sim_sideways' },
            { id: 'sim6', key: 'sim6', label: '하락 줍줍형 (Sim 6)',     color: 'cyan',   type: 'sim_bear' },
        ];
        return (
            <Stack gap="xl">
                <Group justify="space-between">
                    <Title order={3}><IconRobot size={24} style={{ marginBottom: -4, marginRight: 8 }}/>6-Track 지능형 시뮬레이션</Title>
                    <Button variant="outline" size="sm" leftSection={<IconRefresh size={16}/>} onClick={() => { fetchSimulationStats(); fetchHistory(); }}>전체 데이터 갱신</Button>
                </Group>
                <Stack gap="xl">
                    {simConfigs.map((sim) => {
                        const stats = geminiBalance[sim.key]?.raw || {};
                        const portfolio = geminiBalance[sim.key]?.portfolio || {};
                        const holdings = Object.keys(portfolio).map(code => {
                            const p = portfolio[code];
                            const avgVal = p.avg_price || p.price || 0;
                            // current_prices가 있으면 사용, 없으면 avg_price 유지 (||가 아닌 ?? 사용으로 0원 종목 처리)
                            const curVal = stats.current_prices?.[code] ?? avgVal; 
                            // 개별 종목 수익률: 전체 수익률(stats.profit_rate)로 폴백하지 않음
                            const pl = avgVal > 0 ? ((curVal - avgVal) / avgVal) * 100 : 0;
                            
                            return {
                                code,
                                name: p.name,
                                qty: p.quantity,
                                avg_price: avgVal,
                                current_price: curVal,
                                pl_rate: pl
                            };
                        });
                        return (
                            <Group key={sim.id} gap="md" align="stretch" style={{ flexWrap: 'nowrap' }}>
                                <Paper p="md" withBorder radius="md" style={{ borderTop: `4px solid var(--mantine-color-${sim.color}-filled)`, flex: 1, minHeight: 260 }}>
                                    <Group justify="space-between" mb="xs">
                                        <Text fw={800} size="lg" c={sim.color}>{sim.label}</Text>
                                        <Badge color={sim.color}>{sim.id.toUpperCase()}</Badge>
                                    </Group>
                                    <Group grow mb="md">
                                        <Stack gap={2}>
                                            <Text size="xs" c="dimmed">예수금 (잔고)</Text>
                                            <Text fw={700} size="md">{(Math.round(stats.cash || 0)).toLocaleString()}원</Text>
                                        </Stack>
                                        <Stack gap={2}>
                                            <Text size="xs" c="dimmed">수익률</Text>
                                            <Text size="md" fw={800} c={(stats.profit_rate || 0) >= 0 ? 'red' : 'blue'}>
                                                {(stats.profit_rate || 0).toFixed(2)}%
                                            </Text>
                                        </Stack>
                                        <Stack gap={2}>
                                            <Text size="xs" c="dimmed">누적 수수료</Text>
                                            <Text size="md" fw={700} c="gray.6">{(Math.round(stats.total_fees || 0)).toLocaleString()}원</Text>
                                        </Stack>
                                        <Stack gap={2}>
                                            <Text size="xs" c="dimmed">보유 종목</Text>
                                            <Text size="md" fw={800} c={sim.color}>{(holdings?.length || 0)}개</Text>
                                        </Stack>
                                    </Group>
                                    <Divider mb="xs" label="포트폴리오 (NAV)" labelPosition="center" />
                                    {renderPortfolioTable(holdings)}
                                </Paper>
                                <Paper p="md" withBorder radius="md" bg="gray.0" style={{ flex: 1, minHeight: 260 }}>
                                    <Text size="xs" fw={700} mb="xs"><IconHistory size={12} style={{ marginRight: 5 }}/>{sim.label} 기록</Text>
                                    {renderHistoryTable(sim.type)}
                                </Paper>
                            </Group>
                        );
                    })}
                </Stack>
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
        <Container size="lg" py="xl">
            {notification && (
                <Notification title={notification.title} color={notification.color} onClose={() => setNotification(null)}
                    style={{ position: 'fixed', top: 20, right: 20, zIndex: 9999 }}>
                    {notification.msg}
                </Notification>
            )}
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
            <Group justify="space-between" mb="lg">
                <Title order={2}>Stock Dashboard</Title>
                <Group gap="xs">
                    <Badge color="pink" variant="filled">V8.6.2-UI</Badge>
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
