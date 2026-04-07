'use client';

import { Suspense, useState, useEffect, useRef, useCallback } from 'react';
import { useDisclosure, useMediaQuery, useInterval } from '@mantine/hooks';
import { useSearchParams } from 'next/navigation';
import {
    Container, Title, Text, Paper, Group, Stack,
    Table, Badge, Button, Tabs, TextInput, NumberInput,
    Select, Notification, LoadingOverlay, Modal, PinInput, Checkbox, Affix, Transition, ScrollArea, Box
} from '@mantine/core';
import { 
    IconCoin, IconClock, IconChartBar, IconActivity, IconCheck, IconX, 
    IconAlertTriangle, IconSearch, IconAdjustments, IconRefresh, 
    IconTimeline, IconRobot, IconAlertCircle, IconTrash, IconPlayerPlay, 
    IconDeviceMobile, IconHistory, IconChevronUp, IconChevronDown, IconPlus, IconDna 
} from '@tabler/icons-react';
import axios from 'axios';
import { signOut } from 'next-auth/react';
import StrategyRadarChart from '../components/StrategyRadarChart';

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

    const pinContainerRef = useRef<HTMLDivElement>(null);
    const searchParams = useSearchParams();

    // Data Fetchers with SSR Safety
    const showNotify = useCallback((title: string, msg: string, color: string) => {
        setNotification({ title, msg, color });
        setTimeout(() => setNotification(null), 5000);
    }, []);

    // Data Fetchers with SSR Safety
    const fetchBalance = useCallback(async (retryCount = 0, silent = false) => {
        if (typeof window === 'undefined') return;
        if (!silent) setLoading(true);
        try {
            const res = await fetch(`/api/portfolio/real?v=57&cb=${Date.now()}`);
            const data = await res.json().catch(() => ({ error: '서버 응답이 JSON이 아닙니다. (HTML 에러 발생)' }));
            console.log("[DEBUG] Real Portfolio Response:", data);
            setBalance(data);
            if (data.error && !silent) {
                showNotify('API Error (KIS)', data.error, 'red');
            }
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
            const res = await fetch(`/api/simulation/stats?v=85&cb=${Date.now()}`);
            const data = await res.json();
            setGeminiBalance(data);
        } catch (e) {
            console.error("Simulation Stats Fetch Error", e);
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
            if (data.success) {
                setHistory(data.data);
            }
        } catch (e) {
            console.error("History Fetch Error", e);
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

    // Polling Intervals
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
            const payload: any = {
                code, qty, price, side: orderType, pin
            };
            if (isReservation) payload.time = `${resHour}:${resMin}`;

            const res = await axios.post(endpoint, payload);
            if (res.data.success) {
                showNotify('주문 성공', isReservation ? '예약이 등록되었습니다.' : '주문이 처결되었습니다.', 'green');
                fetchBalance();
                fetchReservations();
            } else {
                showNotify('주문 실패', res.data.error, 'red');
            }
        } catch (error: any) {
            showNotify('Error', error.response?.data?.error || error.message, 'red');
        } finally {
            setOrderLoading(false);
            setPendingAction(null);
        }
    };

    const cancelReservation = async (id: string) => {
        if (!confirm('예약을 취소하시겠습니까?')) return;
        try {
            await axios.delete(`/api/trade/reservation?id=${id}`);
            showNotify('Success', 'Cancelled', 'green');
            fetchReservations();
        } catch (error) {}
    };

    function renderPortfolio() {
        const deposit = balance?.deposit ?? 0;
        const totalEval = balance?.holdings?.reduce((sum, h) => sum + ((h.price || 0) * (h.qty || 0)), 0) ?? 0;
        const totalPL = balance?.holdings?.reduce((sum, h) => sum + (h.pl_amount || 0), 0) ?? 0;

        return (
            <Paper p="md" withBorder radius="md">
                <Title order={4} mb="sm">My Portfolio (Real)</Title>
                {balance?.error && (
                    <Box mb="md" p="xs" style={{ backgroundColor: '#fff5f5', border: '1px solid #ffa8a8', borderRadius: '4px' }}>
                        <Text size="xs" color="red" fw={700}>⚠️ {balance.error}</Text>
                    </Box>
                )}
                <div style={{ position: 'relative' }}>
                    <LoadingOverlay visible={loading} zIndex={10} overlayProps={{ radius: 'sm', blur: 2 }} />
                    <Group justify="space-between" mb="md" align="flex-end">
                        <Stack gap={0}>
                            <Text size="sm" c="dimmed">예수금</Text>
                            <Title order={3}>{(Number(deposit) || 0).toLocaleString()} 원</Title>
                        </Stack>
                        <Button variant="light" size="xs" onClick={() => fetchBalance()}>Refresh</Button>
                    </Group>

                    <Group grow mb="md">
                        <Stack gap={0}>
                            <Text size="sm" c="dimmed">평가금액</Text>
                            <Text fw={700}>{(Number(totalEval) || 0).toLocaleString()} 원</Text>
                        </Stack>
                        <Stack gap={0}>
                            <Text size="sm" c="dimmed">평가손익</Text>
                            <Text fw={700} c={totalPL >= 0 ? 'red' : 'blue'}>
                                {(Number(totalPL) || 0).toLocaleString()} 원
                            </Text>
                        </Stack>
                    </Group>

                    <ScrollArea>
                        <Table striped highlightOnHover verticalSpacing="xs">
                            <Table.Thead>
                                <Table.Tr>
                                    <Table.Th>종목</Table.Th>
                                    <Table.Th>수량</Table.Th>
                                    <Table.Th>수익률</Table.Th>
                                </Table.Tr>
                            </Table.Thead>
                            <Table.Tbody>
                                {balance?.holdings && Array.isArray(balance.holdings) && balance.holdings.map((h) => (
                                    <Table.Tr key={h.code} style={{ cursor: 'pointer' }} onClick={() => setCode(h.code)}>
                                        <Table.Td>
                                            <Text size="sm" fw={500}>{h.name}</Text>
                                            <Text size="xs" c="dimmed">{h.code}</Text>
                                        </Table.Td>
                                        <Table.Td>{h.qty}</Table.Td>
                                        <Table.Td>
                                            <Badge color={(h.pl_rate ?? 0) > 0 ? 'red' : 'blue'} variant="light">
                                                {h.pl_rate ?? 0}%
                                            </Badge>
                                        </Table.Td>
                                    </Table.Tr>
                                ))}
                            </Table.Tbody>
                        </Table>
                    </ScrollArea>
                </div>
            </Paper>
        );
    }

    function renderHistoryTable(type: 'real' | 'sim') {
        const filtered = history.filter(h => type === 'real' ? h.type === 'real' : h.type.startsWith('sim_'));
        
        if (filtered.length === 0) {
            return (
                <Box py="xl" style={{ textAlign: 'center', border: '1px dashed #ced4da', borderRadius: '8px' }}>
                    <Text c="dimmed">거래 내역이 없습니다.</Text>
                </Box>
            );
        }

        return (
            <ScrollArea h={300} offsetScrollbars>
                <Table striped highlightOnHover stickyHeader verticalSpacing="xs">
                    <Table.Thead>
                        <Table.Tr>
                            <Table.Th>일시</Table.Th>
                            <Table.Th>종목</Table.Th>
                            <Table.Th>구분</Table.Th>
                            <Table.Th>체결가</Table.Th>
                            <Table.Th>수량</Table.Th>
                            <Table.Th>체결금액</Table.Th>
                            {type === 'sim' && <Table.Th>판단 사유</Table.Th>}
                        </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                        {filtered.map((h, i) => (
                            <Table.Tr key={i}>
                                <Table.Td style={{ whiteSpace: 'nowrap' }}>
                                    <Text size="xs" c="dimmed">{h.time.split(' ')[0]}</Text>
                                    <Text size="xs" fw={500}>{h.time.split(' ')[1]}</Text>
                                </Table.Td>
                                <Table.Td>
                                    <Group gap={5}>
                                        {h.type.startsWith('sim_') && (
                                            <Badge size="xs" variant="outline" color={h.type === 'sim_conviction' ? 'grape' : h.type === 'sim_aggressive' ? 'red' : 'blue'}>
                                                {h.type.split('_')[1][0].toUpperCase()}
                                            </Badge>
                                        )}
                                        <Text size="sm" fw={700}>{h.symbol}</Text>
                                    </Group>
                                </Table.Td>
                                <Table.Td>
                                    <Badge color={h.action === 'BUY' ? 'red' : 'blue'} variant="filled" size="sm">
                                        {h.action === 'BUY' ? '매수' : '매도'}
                                    </Badge>
                                </Table.Td>
                                <Table.Td><Text size="sm">{h.price}원</Text></Table.Td>
                                <Table.Td><Text size="sm">{h.qty}주</Text></Table.Td>
                                <Table.Td><Text size="sm" fw={700}>{h.amount}원</Text></Table.Td>
                                {type === 'sim' && (
                                    <Table.Td>
                                        <Button 
                                            variant="subtle" size="compact-xs" 
                                            onClick={() => {
                                                setSelectedReason({ title: `${h.symbol} ${h.action} 판단 근거`, content: h.reason });
                                                setReasonModalOpen(true);
                                            }}
                                        >
                                            <Text size="xs" truncate maw={100}>{h.reason || '사유 없음'}</Text>
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

    function renderSimulationTripod() {
        if (!geminiBalance) return null;
        
        const simData = [
            { key: 'sim1', label: '오리지널', color: 'blue' },
            { key: 'sim2', label: '공격형', color: 'red' },
            { key: 'sim3', label: '컨빅션', color: 'grape' }
        ];

        return (
            <Stack gap="md">
                <Group justify="space-between">
                    <Title order={4} c="dimmed">3-Track 시뮬레이션 현황</Title>
                    <Button variant="subtle" size="xs" leftSection={<IconRefresh size={14}/>} onClick={() => { fetchSimulationStats(); fetchHistory(); }}>새로고침</Button>
                </Group>
                <Group grow align="stretch">
                    {simData.map((sim) => {
                        const stats = geminiBalance[sim.key]?.raw || {};
                        return (
                            <Paper key={sim.key} p="md" withBorder radius="md">
                                <Stack gap="xs">
                                    <Group justify="space-between">
                                        <Text fw={700} c={sim.color}>{sim.label}</Text>
                                        <Badge color={sim.color} variant="light">Sim {(sim.key as string).slice(-1)}</Badge>
                                    </Group>
                                    
                                    <Stack gap={2}>
                                        <Text size="xs" c="dimmed">현재 자산</Text>
                                        <Text fw={700} size="lg">{(Math.round(stats.total_asset || 0)).toLocaleString()} 원</Text>
                                    </Stack>

                                    <Group grow>
                                        <Stack gap={2}>
                                            <Text size="xs" c="dimmed">누적 수익률</Text>
                                            <Text size="sm" fw={700} c={(stats.profit_rate || 0) >= 0 ? 'red' : 'blue'}>
                                                {(stats.profit_rate || 0).toFixed(2)}%
                                            </Text>
                                        </Stack>
                                        <Stack gap={2}>
                                            <Text size="xs" c="dimmed">당일 승률</Text>
                                            <Text size="sm" fw={700} c="orange">
                                                {(stats.daily_win_rate || 0).toFixed(1)}%
                                            </Text>
                                        </Stack>
                                    </Group>

                                    <Group grow>
                                        <Stack gap={2}>
                                            <Text size="xs" c="dimmed">보류 종목</Text>
                                            <Text size="sm" fw={700}>{stats.holdings_count || 0} 개</Text>
                                        </Stack>
                                        <Stack gap={2}>
                                            <Text size="xs" c="dimmed">MDD</Text>
                                            <Text size="sm" fw={700} c="teal">{(stats.mdd || 0).toFixed(2)}%</Text>
                                        </Stack>
                                    </Group>
                                </Stack>
                            </Paper>
                        );
                    })}
                </Group>
                
                <Paper p="md" withBorder radius="md" mt="sm">
                    <Group mb="sm" justify="space-between">
                        <Title order={5}><IconHistory size={18} style={{ marginBottom: -4, marginRight: 8 }}/>시뮬레이션 거래 히스토리</Title>
                    </Group>
                    {renderHistoryTable('sim')}
                </Paper>
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
                            <Select
                                label="Stock"
                                placeholder="Search Stock"
                                searchable
                                data={stocks.map(s => ({ value: s.code, label: `${s.name} (${s.code})` }))}
                                value={code}
                                onChange={(val) => setCode(val || '')}
                            />
                            <NumberInput label="Quantity" min={1} value={qty} onChange={(val) => setQty(Number(val) || 1)} />
                            <NumberInput label="Price (0=Market)" min={0} value={price} onChange={(val) => setPrice(Number(val) || 0)} />
                        </Stack>

                        <Tabs.Panel value="immediate" pt="md">
                            <Stack gap="xs">
                                <Button fullWidth size="lg" onClick={() => handleOrder(false)} color={orderType === 'buy' ? 'red' : 'blue'}>
                                    Submit Real Order
                                </Button>
                            </Stack>
                        </Tabs.Panel>

                        <Tabs.Panel value="reservation" pt="md">
                            <Group grow mb="sm">
                                <NumberInput label="Hour" min={0} max={23} value={resHour} onChange={(val) => setResHour(Number(val) || 15)} />
                                <NumberInput label="Minute" min={0} max={59} value={resMin} onChange={(val) => setResMin(Number(val) || 15)} />
                            </Group>
                            <Button fullWidth size="lg" color="violet" onClick={() => handleOrder(true)}>
                                Schedule Order
                            </Button>
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
                                    <Button size="xs" variant="subtle" color="red" onClick={() => cancelReservation(r.id)}>Cancel</Button>
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
                <Notification
                    title={notification.title} color={notification.color}
                    onClose={() => setNotification(null)}
                    style={{ position: 'fixed', top: 20, right: 20, zIndex: 9999 }}
                >
                    {notification.msg}
                </Notification>
            )}

            <Modal opened={pinModalOpen} onClose={() => setPinModalOpen(false)} title="Security Verification" centered zIndex={2000}>
                <Stack align="center" py="md" ref={pinContainerRef}>
                    <Text>거래 승인을 위해 보안 PIN 번호를 입력하세요.</Text>
                    <PinInput length={4} type="number" mask value={pin} onChange={setPin} onComplete={confirmOrder} />
                    <Group mt="md">
                        <Button variant="default" onClick={() => setPinModalOpen(false)}>Cancel</Button>
                        <Button color="blue" onClick={confirmOrder} disabled={pin.length !== 4}>Confirm</Button>
                    </Group>
                </Stack>
            </Modal>

            <Group justify="space-between" mb="lg">
                <Title order={2}>Stock Trading Dashboard</Title>
                <Group gap="xs">
                    <Badge color="pink" variant="filled">V57-HOTFIX</Badge>
                    <Button component="a" href="/research" size="sm" variant="light">Research</Button>
                    <Button color="gray" variant="subtle" size="sm" onClick={() => signOut({ callbackUrl: '/login' })}>Out</Button>
                </Group>
            </Group>

            <Stack gap="lg" mb="lg">
                <Group grow align="flex-start" gap="lg">
                    <Stack gap="md">
                        {renderPortfolio()}
                        <Paper p="md" withBorder radius="md">
                            <Title order={5} mb="sm"><IconHistory size={18} style={{ marginBottom: -4, marginRight: 8 }}/>실거래 매매 히스토리</Title>
                            {renderHistoryTable('real')}
                        </Paper>
                    </Stack>
                    {renderTrading()}
                </Group>
                {renderSimulationTripod()}
            </Stack>

            <Modal opened={reasonModalOpen} onClose={() => setReasonModalOpen(false)} title={selectedReason.title} size="lg">
                <Paper p="md" withBorder bg="gray.0">
                    <Text style={{ whiteSpace: 'pre-wrap' }}>{selectedReason.content}</Text>
                </Paper>
                <Group justify="flex-end" mt="md">
                    <Button onClick={() => setReasonModalOpen(false)}>닫기</Button>
                </Group>
            </Modal>

            <Box mt="xl">
                <StrategyRadarChart />
            </Box>
        </Container>
    );
}

export default function TradeClient() {
    return (
        <Suspense fallback={<LoadingOverlay visible />}>
            <TradeContent />
        </Suspense>
    );
}
