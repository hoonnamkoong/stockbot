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
    IconDeviceMobile, IconHistory, IconChevronUp, IconChevronDown, IconPlus 
} from '@tabler/icons-react';
import axios from 'axios';
import { signOut } from 'next-auth/react';

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
    const [isVirtualOrder, setIsVirtualOrder] = useState(false);

    // Security (PIN)
    const [pinModalOpen, setPinModalOpen] = useState(false);
    const [pin, setPin] = useState('');
    const [pendingAction, setPendingAction] = useState<{ isReservation: boolean } | null>(null);

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
            const res = await axios.get(`/api/portfolio/real?cb=${Date.now()}&v=55`);
            console.log("[DEBUG] Real Portfolio Response:", res.data);
            if (res.data.error) {
                if (!silent) showNotify('API Error (KIS)', res.data.error, 'red');
                console.error("KIS API Error:", res.data.error);
            } else {
                setBalance(res.data);
            }
        } catch (error: any) {
            if (retryCount < 1) setTimeout(() => fetchBalance(retryCount + 1, silent), 2000);
            else if (!silent) showNotify('Fetch Error', '실시간 계좌 정보를 가져오지 못했습니다.', 'red');
        } finally {
            if (!silent) setLoading(false);
        }
    }, [showNotify]);

    const fetchGeminiBalance = useCallback(async (type: 'real' | 'virtual' = 'virtual') => {
        if (typeof window === 'undefined') return;
        setGeminiLoading(true);
        try {
            const res = await fetch(`/api/portfolio/${type}?v=57&cb=${Date.now()}`);
            if (!res.ok) {
                const errorData = await res.json().catch(() => ({ error: '서버 응답 오류 (JSON 아님)' }));
                throw new Error(errorData.error || `HTTP ${res.status}`);
            }
            const data = await res.json();
            if (type === 'real') setBalance(data);
            else setGeminiBalance(data);
        } catch (e) {
            console.error("Gemini Fetch Error", e);
        } finally {
            setGeminiLoading(false);
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

    // Initial Data Fetch
    useEffect(() => {
        if (typeof window === 'undefined') return;
        fetchBalance();
        fetchStocks();
        fetchReservations();
        fetchGeminiBalance();
        
        const codeParam = searchParams.get('code');
        if (codeParam) setCode(codeParam);
    }, [searchParams, fetchBalance, fetchStocks, fetchReservations, fetchGeminiBalance]);

    // Polling Intervals
    const balancePoller = useInterval(() => fetchBalance(0, true), 30000);
    useEffect(() => {
        balancePoller.start();
        return () => balancePoller.stop();
    }, [balancePoller]);

    const handleOrder = async (isReservation: boolean, isVirtual = false) => {
        if (!code || !qty) {
            showNotify('Error', '종목과 수량을 입력하세요.', 'red');
            return;
        }
        setIsVirtualOrder(isVirtual);
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
                code, qty, price, side: orderType, pin,
                isVirtual: isVirtualOrder
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
                            <Title order={3}>{(balance?.deposit ?? 0).toLocaleString()} 원</Title>
                        </Stack>
                        <Button variant="light" size="xs" onClick={() => fetchBalance()}>Refresh</Button>
                    </Group>

                    <Group grow mb="md">
                        <Stack gap={0}>
                            <Text size="sm" c="dimmed">평가금액</Text>
                            <Text fw={700}>{(balance?.holdings?.reduce((sum, h) => sum + (h.price * h.qty), 0) ?? 0).toLocaleString()} 원</Text>
                        </Stack>
                        <Stack gap={0}>
                            <Text size="sm" c="dimmed">평가손익</Text>
                            <Text fw={700} c={((balance?.holdings?.reduce((sum, h) => sum + h.pl_amount, 0)) ?? 0) >= 0 ? 'red' : 'blue'}>
                                {(balance?.holdings?.reduce((sum, h) => sum + h.pl_amount, 0) ?? 0).toLocaleString()} 원
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
                                {balance?.holdings?.map((h) => (
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

    function renderGeminiPortfolio() {
        const holdingsArr = geminiBalance?.holdings ? Object.entries(geminiBalance.holdings).map(([code, h]: any) => ({ code, ...h })) : [];
        const totalAsset = (geminiBalance?.cash || 3000000) + holdingsArr.reduce((sum, h: any) => sum + (h.qty * h.avg_price), 0);
        const profitRate = ((totalAsset - 3000000) / 3000000) * 100;

        return (
            <Paper p="md" withBorder radius="md" mt="md" style={{ borderColor: '#e599f7', borderWidth: 2 }}>
                <Group justify="space-between" mb="xs">
                    <Title order={4} c="grape">✨ Gemini Portfolio (Virtual)</Title>
                    <Badge color="grape" variant="light">3.0M Initial</Badge>
                </Group>
                <div style={{ position: 'relative' }}>
                    <LoadingOverlay visible={geminiLoading} zIndex={10} overlayProps={{ radius: 'sm', blur: 2 }} />
                    <Group justify="space-between" mb="md" align="flex-end">
                        <Stack gap={0}>
                            <Text size="sm" c="dimmed">자산총계</Text>
                            <Title order={3}>{Math.round(totalAsset).toLocaleString()} 원</Title>
                        </Stack>
                        <Text fw={700} c={profitRate >= 0 ? 'red' : 'blue'}>{profitRate.toFixed(2)}%</Text>
                    </Group>
                    <Table striped verticalSpacing="xs">
                        <Table.Tbody>
                            {holdingsArr.map((h: any) => (
                                <Table.Tr key={h.code}>
                                    <Table.Td>{h.name}</Table.Td>
                                    <Table.Td>{h.qty}주</Table.Td>
                                    <Table.Td>{Math.round(h.avg_price).toLocaleString()} 원</Table.Td>
                                </Table.Tr>
                            ))}
                        </Table.Tbody>
                    </Table>
                    <Button fullWidth mt="md" size="xs" variant="light" color="grape" onClick={() => fetchGeminiBalance()}>Refresh Simulation</Button>
                </div>
            </Paper>
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
                                <Button fullWidth size="lg" onClick={() => handleOrder(false, false)} color={orderType === 'buy' ? 'red' : 'blue'}>
                                    Submit Real Order
                                </Button>
                                <Button fullWidth variant="light" color="grape" onClick={() => handleOrder(false, true)}>
                                    Submit Virtual Order
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

            <Group grow align="flex-start" gap="lg">
                <Stack>
                    {renderPortfolio()}
                    {renderGeminiPortfolio()}
                </Stack>
                {renderTrading()}
            </Group>
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
