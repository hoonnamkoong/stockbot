'use client';
import { useState, useEffect, useRef } from 'react';

import { useDisclosure, useMediaQuery, useInterval } from '@mantine/hooks';
import {
    Container, Title, Text, Paper, Group, Stack,
    Table, Badge, Button, Tabs, TextInput, NumberInput,
    Select, Notification, LoadingOverlay, Modal, PinInput, Checkbox, Affix, Transition, ScrollArea
} from '@mantine/core';
import { IconCoin, IconClock, IconChartBar, IconActivity, IconCheck, IconX, IconAlertTriangle } from '@tabler/icons-react';
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
    last_buy_date?: string;
}

interface BalanceData {
    deposit: number;
    total_asset: number;
    holdings: Holding[];
}

interface StockItem {
    code: string;
    name: string;
}

export default function TradePage() {
    const [balance, setBalance] = useState<BalanceData | null>(null);
    const [stocks, setStocks] = useState<StockItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [orderLoading, setOrderLoading] = useState(false);
    const [notification, setNotification] = useState<{ title: string, msg: string, color: string } | null>(null);
    const [geminiBalance, setGeminiBalance] = useState<any>(null);
    const [geminiLoading, setGeminiLoading] = useState(false);

    // Order Form
    const [orderType, setOrderType] = useState<string | null>('buy');
    const [code, setCode] = useState('');
    const [qty, setQty] = useState<number | string>(1);
    const [price, setPrice] = useState<number | string>(0); // 0 = Market

    // Reservation
    const [resHour, setResHour] = useState<number | string>(15);
    const [resMin, setResMin] = useState<number | string>(15);

    // Security (PIN)
    const [pinModalOpen, setPinModalOpen] = useState(false);
    const [pin, setPin] = useState('');
    const [pendingAction, setPendingAction] = useState<{ isReservation: boolean, isBulk?: boolean, bulkMode?: 'sell' | 'reservation' } | null>(null);

    // Bulk Actions
    const [selectedHoldings, setSelectedHoldings] = useState<string[]>([]);
    const pinContainerRef = useRef<HTMLDivElement>(null);

    const [reservations, setReservations] = useState<any[]>([]);

    // Order Status Polling loop (Closed-Loop)
    const [orderStatuses, setOrderStatuses] = useState<Record<string, any>>({});
    const [trackingOrders, setTrackingOrders] = useState<string[]>([]);
    const [notifiedOrders, setNotifiedOrders] = useState<Set<string>>(new Set());

    // Diagnosis State
    const [diagnosisModalOpen, setDiagnosisModalOpen] = useState(false);
    const [diagnosisLoading, setDiagnosisLoading] = useState(false);
    const [diagnosisResults, setDiagnosisResults] = useState<any>(null);

    useEffect(() => {
        if (pinModalOpen) {
            // "Shotgun" focus approach to guarantee input focus
            const focusInput = () => {
                if (pinContainerRef.current) {
                    const input = pinContainerRef.current.querySelector('input:not([type="hidden"])') as HTMLInputElement;
                    if (input) input.focus();
                }
            };

            // Multiple attempts to handle modal animation timing
            focusInput();
            setTimeout(focusInput, 50);
            setTimeout(focusInput, 200);
            setTimeout(focusInput, 500);
        }
    }, [pinModalOpen]);

    const toggleSelectAll = () => {
        if (!balance) return;
        if (selectedHoldings.length === balance.holdings.length) {
            setSelectedHoldings([]);
        } else {
            setSelectedHoldings(balance.holdings.map(h => h.code));
        }
    };

    const toggleSelectRow = (code: string) => {
        if (selectedHoldings.includes(code)) {
            setSelectedHoldings(selectedHoldings.filter(c => c !== code));
        } else {
            setSelectedHoldings([...selectedHoldings, code]);
        }
    };

    const fetchBalance = async (retryCount = 0) => {
        setLoading(true);
        try {
            // Add timestamp to prevent browser caching
            const res = await axios.get(`/api/trade/account-balance?t=${Date.now()}`);
            if (res.data.error) {
                // API returned 200 but with error payload (e.g. "Waiting for sync")
                if (res.data.sync_status === 'waiting') {
                    setBalance(res.data); // This shows "Waiting for mobile sync" in UI
                } else {
                    console.error('[Trade] API Error:', res.data.error);
                    showNotify('API Error', res.data.error, 'red');
                }
            } else {
                setBalance(res.data);
            }
        } catch (error: any) {
            console.error(error);
            if (retryCount < 2) {
                console.log(`Retrying fetchBalance... (${retryCount + 1})`);
                setTimeout(() => fetchBalance(retryCount + 1), 2000);
            } else {
                const detail = error.response?.data?.error || error.message || 'Unknown error';
                showNotify('Fetch Error', `잔고 조회 실패 (GitHub 확인 필요): ${detail}`, 'red');
            }
        } finally {
            setLoading(false);
        }
    };

    const runDiagnosis = async () => {
        setDiagnosisLoading(true);
        setDiagnosisModalOpen(true);
        try {
            const res = await axios.get('/api/debug/test-connection');
            setDiagnosisResults(res.data);
        } catch (e: any) {
            setDiagnosisResults({ error: e.message });
        } finally {
            setDiagnosisLoading(false);
        }
    };

    const fetchStocks = async () => {
        try {
            const res = await axios.get('/api/stocks/list');
            if (res.data.stocks) {
                setStocks(res.data.stocks);
            }
        } catch (error) {
            console.error("Failed to load stocks");
        }
    };

    const fetchReservations = async () => {
        try {
            const res = await axios.get('/api/trade/reservation');
            const resList = res.data.reservations || [];
            setReservations(resList);

            // Auto-track reservations that are dispatched but not yet reported as complete
            const dispatchedIds = resList.filter((r:any) => r.status === 'DISPATCHED').map((r:any) => r.id);
            if (dispatchedIds.length > 0) {
                setTrackingOrders(prev => Array.from(new Set([...prev, ...dispatchedIds])));
            }
        } catch (error) {
            console.error("Failed to load reservations");
        }
    };

    const cancelReservation = async (id: string) => {
        if (!confirm('Are you sure you want to cancel this reservation?')) return;
        try {
            await axios.delete(`/api/trade/reservation?id=${id}`);
            showNotify('Success', 'Reservation Cancelled', 'green');
            fetchReservations();
        } catch (error) {
            showNotify('Error', 'Failed to cancel reservation', 'red');
        }
    };

    const getStockName = (code: string) => {
        const stock = stocks.find(s => s.code === code);
        return stock ? stock.name : code;
    };

    const fetchGeminiBalance = async () => {
        setGeminiLoading(true);
        try {
            const res = await axios.get('/api/portfolio/gemini');
            setGeminiBalance(res.data);
        } catch (e) {
            console.error("Gemini Fetch Error", e);
        } finally {
            setGeminiLoading(false);
        }
    };

    useEffect(() => {
        fetchBalance();
        fetchStocks();
        fetchReservations();
        fetchGeminiBalance();
    }, []);

    // [Real-time Execution] Poll schedule endpoint every 30 seconds while page is open.
    // This ensures trades are executed instantly when user is watching, even if Cron is slow.
    const schedulePoller = useInterval(async () => {
        try {
            await axios.get('/api/trade/schedule');
            fetchReservations(); // Refresh list after check
            fetchBalance();      // Refresh balance if trade happened
            fetchGeminiBalance();
        } catch (e) {
            console.error("Schedule Poller Error", e);
        }
    }, 30000); // 30 seconds

    useEffect(() => {
        schedulePoller.start();
        return () => schedulePoller.stop();
    }, []);

    // [Real-time Status Feed] Poll order_status.json every 5 seconds
    const orderStatusPoller = useInterval(async () => {
        if (trackingOrders.length === 0) return;
        try {
            const res = await axios.get(`/api/trade/order-status?t=${Date.now()}`);
            const data = res.data.data;
            if (data) {
                setOrderStatuses(prev => ({ ...prev, ...data })); // Merge for persistence
                trackingOrders.forEach(odno => {
                    const obj = data[odno];
                    if (obj) {
                        const statusKey = `${odno}-${obj.status}`;
                        if (!notifiedOrders.has(statusKey)) {
                            if (obj.status === 'SUCCESS') showNotify('체결 성공 ✅', `주문번호: ${odno}`, 'teal');
                            else if (obj.status === 'FAILED') showNotify('주문 실패 ❌', `${obj.msg || '알 수 없는 오류'}`, 'red');
                            else if (obj.status === 'PROCESSING') showNotify('주문 진행 중 ⏳', '모바일에서 주문을 접수했습니다.', 'blue');
                            
                            setNotifiedOrders(prev => new Set(prev).add(statusKey));
                            if (obj.status === 'SUCCESS' || obj.status === 'FAILED') {
                                setTimeout(() => fetchBalance(), 1000); // Trigger balance refresh
                            }
                        }
                    }
                });
            }
        } catch (e: any) {
            console.error('Status poll error', e.message);
            // Don't stop poller on single error, just logout
        }
    }, 5000);

    useEffect(() => {
        // Start poller if there are things to track
        if (trackingOrders.length > 0) {
            orderStatusPoller.start();
        } else {
            orderStatusPoller.stop();
        }
        return () => orderStatusPoller.stop();
    }, [trackingOrders]);

    const showNotify = (title: string, msg: string, color: string) => {
        setNotification({ title, msg, color });
        setTimeout(() => setNotification(null), 5000);
    };

    const handleOrder = async (isReservation: boolean) => {
        if (!code || !qty) {
            showNotify('Error', 'Please select Stock and Quantity', 'red');
            return;
        }
        setPendingAction({ isReservation, isBulk: false });
        setPin(''); // Reset PIN
        setPinModalOpen(true);
    };

    const handleBulkOrder = (mode: 'sell' | 'reservation') => {
        if (selectedHoldings.length === 0) return;
        setPendingAction({ isReservation: mode === 'reservation', isBulk: true, bulkMode: mode });
        setPin('');
        setPinModalOpen(true);
    };

    const confirmOrder = async () => {
        if (!pendingAction) return;
        const { isReservation, isBulk, bulkMode } = pendingAction;
        setPinModalOpen(false); // Close Modal

        setOrderLoading(true);
        try {
            if (isBulk && bulkMode) {
                // BULK EXECUTION
                let successCount = 0;
                let failCount = 0;

                for (const code of selectedHoldings) {
                    const holding = balance?.holdings.find(h => h.code === code);
                    if (!holding) continue;

                    try {
                        // Use 0 (Market Price) to ensure execution even if price fluctuates
                        const price = 0;

                        if (bulkMode === 'reservation') {
                            await axios.post('/api/trade/reservation', {
                                code, qty: holding.qty, price, hour: resHour, minute: resMin, side: 'sell', pin
                            });
                        } else {
                            // Immediate Sell
                            await axios.post('/api/trade/order', {
                                code, qty: holding.qty, price, side: 'sell', pin
                            });
                        }
                        successCount++;
                    } catch (e) {
                        console.error(`Failed to bulk sell ${code}`, e);
                        failCount++;
                    }
                }
                showNotify('송신 완료', '명령이 모바일로 전송되었습니다. 체결 결과를 기다립니다.', 'blue');
                fetchBalance();
                if (bulkMode === 'reservation') {
                    fetchReservations(); // Refresh reservation list
                }
                setSelectedHoldings([]); // Clear selection

            } else {
                // SINGLE EXECUTION
                if (isReservation) {
                    const res = await axios.post('/api/trade/reservation', {
                        code, qty, price, hour: resHour, minute: resMin, side: orderType, pin
                    });
                    showNotify('송신 완료', '명령이 모바일로 전송되었습니다. 체결 결과를 기다립니다.', 'blue');
                    fetchReservations(); // Refresh List
                } else {
                    const res = await axios.post('/api/trade/order', {
                        code, qty, price, side: orderType, pin
                    });
                    if (res.data.success) {
                        const odno = res.data.data.ODNO;
                        showNotify('명령 송신 완료', '명령이 모바일로 전송되었습니다. 체결 결과를 기다립니다.', 'blue');
                        fetchBalance(); // Refresh
                        if (odno) setTrackingOrders(prev => [...prev, odno]);
                    }
                }
            }

        } catch (error: any) {
            const msg = error.response?.data?.error || error.message;
            if (error.response?.status === 401) {
                showNotify('Security Error', 'Incorrect PIN Number', 'red');
            } else {
                showNotify('Order Failed', msg, 'red');
            }
        } finally {
            setOrderLoading(false);
            setPendingAction(null);
        }
    };

    const handleSellAll = () => {
        if (!balance || !code) return;
        const holding = balance.holdings.find(h => h.code === code);
        if (holding) {
            setQty(holding.qty);
        } else {
            showNotify('Info', '보유한 주식이 없습니다.', 'blue');
        }
    };

    const isMobile = useMediaQuery('(max-width: 768px)');

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
                    <Text>Please enter your 4-digit PIN to confirm.</Text>
                    <PinInput
                        length={4}
                        type="number"
                        mask
                        value={pin}
                        onChange={setPin}
                        onComplete={confirmOrder}
                    />
                    <Group mt="md">
                        <Button variant="default" onClick={() => setPinModalOpen(false)}>Cancel</Button>
                        <Button color="blue" onClick={confirmOrder} disabled={pin.length !== 4}>Confirm</Button>
                    </Group>
                </Stack>
            </Modal>

            <Modal opened={diagnosisModalOpen} onClose={() => setDiagnosisModalOpen(false)} title="System Diagnostics" size="md">
                <LoadingOverlay visible={diagnosisLoading} />
                <Stack>
                    {diagnosisResults ? (
                        <>
                            <Paper withBorder p="xs">
                                <Group justify="space-between">
                                    <Text fw={500}>GitHub Connection</Text>
                                    <Badge color={diagnosisResults.github?.status === 'ok' ? 'green' : (diagnosisResults.github?.status === 'warning' ? 'orange' : 'red')}>
                                        {diagnosisResults.github?.status?.toUpperCase() || 'N/A'}
                                    </Badge>
                                </Group>
                                <Text size="sm" c="dimmed" mt={4}>{diagnosisResults.github?.message}</Text>
                            </Paper>
                            <Paper withBorder p="xs">
                                <Group justify="space-between">
                                    <Text fw={500}>KIS API Tunnel</Text>
                                    <Badge color={diagnosisResults.kis?.status === 'ok' ? 'green' : (diagnosisResults.kis?.status === 'blocked' ? 'orange' : 'red')}>
                                        {diagnosisResults.kis?.status?.toUpperCase() || 'N/A'}
                                    </Badge>
                                </Group>
                                <Text size="sm" c="dimmed" mt={4}>{diagnosisResults.kis?.message}</Text>
                                {diagnosisResults.kis?.status === 'blocked' && (
                                    <Text size="xs" color="orange" mt={5}>* Vercel IP 차단 중입니다. 주문은 모바일에서 처리되므로 정상이지만, 직접 시세 조회 등은 불가능할 수 있습니다.</Text>
                                )}
                            </Paper>
                            <Paper withBorder p="xs" bg="gray.0">
                                <Text size="xs" fw={700} mb={5}>Environment Check</Text>
                                <Group gap="xs">
                                    <Badge size="xs" color={diagnosisResults.env?.hasGithubPat ? 'green' : 'red'} variant="outline">GITHUB_PAT</Badge>
                                    <Badge size="xs" color={diagnosisResults.env?.hasKisAppKey ? 'green' : 'red'} variant="outline">KIS_APP_KEY</Badge>
                                    <Badge size="xs" color={diagnosisResults.env?.hasKisAppSecret ? 'green' : 'red'} variant="outline">KIS_SECRET</Badge>
                                    <Badge size="xs" color={diagnosisResults.env?.hasKisAccNo ? 'green' : 'red'} variant="outline">KIS_ACC_NO</Badge>
                                </Group>
                            </Paper>
                        </>
                    ) : (
                        <Text ta="center">진단 데이터를 불러오는 중...</Text>
                    )}
                    <Button fullWidth onClick={runDiagnosis}>Re-Run Diagnosis</Button>
                </Stack>
            </Modal>

            <Group justify="space-between" mb="lg">
                <Title order={2}>Stock Trading</Title>
                <Group gap={5}>
                    <Button variant="light" color="indigo" size="sm" leftSection={<IconActivity size={20} />} onClick={runDiagnosis}>
                        Check
                    </Button>
                    <Button
                        component="a"
                        onClick={() => {
                            // "Korea Investment" (HanTo) - com.koreainvestment.stock
                            // "eFriend Smart" - com.truefriend.m.common
                            // Try Intent that targets the package directly
                            const isAndroid = /android/i.test(navigator.userAgent);
                            const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);

                            if (isAndroid) {
                                // Try opening Main HanTo App via Intent
                                // Format: intent://<path>#Intent;scheme=<scheme>;package=<package>;end
                                // If scheme unknown, try launching by package ?
                                window.location.href = "intent://#Intent;package=com.truefriend.neosmartarenewal;end";
                            } else if (isIOS) {
                                window.location.href = "koreainvestment://open";
                            }
                        }}
                        size="sm"
                        variant="light"
                        color="red"
                        leftSection={<IconCoin size={20} />}
                    >
                        App
                    </Button>
                    <Button component="a" href="/research" size="sm" variant="light" leftSection={<IconChartBar size={20} />}>
                        Research
                    </Button>
                    <Button color="gray" variant="subtle" size="sm" onClick={() => signOut({ callbackUrl: '/login' })}>
                        Out
                    </Button>
                </Group>
            </Group>

            {/* Layout: Stack on Mobile, Group on Desktop */}
            {isMobile ? (
                <Stack gap="lg">
                    {/* 1. Portfolio Section */}
                    {renderPortfolio()}
                    {renderGeminiPortfolio()}
                    {/* 2. Trading Section */}
                    {renderTrading()}
                </Stack>
            ) : (
                <Group grow align="flex-start">
                    <Stack>
                        {renderPortfolio()}
                        {renderGeminiPortfolio()}
                    </Stack>
                    {renderTrading()}
                </Group>
            )}
        </Container >
    );

    function renderPortfolio() {
        return (
            <Stack>
                <Paper p="md" withBorder radius="md">
                    <Title order={4} mb="md">My Portfolio</Title>
                    <LoadingOverlay visible={loading} zIndex={100} overlayProps={{ radius: 'sm', blur: 2 }} />

                    <Group justify="space-between" mb="md" align="flex-end">
                        <Stack gap={0}>
                            <Text size="sm" c="dimmed">예수금</Text>
                            <Title order={3}>{balance?.deposit.toLocaleString()} 원</Title>
                        </Stack>
                        <Group gap="xs">
                            <Button variant="light" size="xs" onClick={() => fetchBalance()}>Refresh</Button>
                        </Group>
                    </Group>

                    {/* Summary Row */}
                    <Group grow mb="md">
                        <Stack gap={0}>
                            <Text size="sm" c="dimmed">평가금액</Text>
                            <Text fw={700}>
                                {balance?.holdings.reduce((sum, h) => sum + (h.price * h.qty), 0).toLocaleString()}
                            </Text>
                        </Stack>
                        <Stack gap={0}>
                            <Text size="sm" c="dimmed">평가손익</Text>
                            <Text fw={700} c={
                                (balance?.holdings.reduce((sum, h) => sum + h.pl_amount, 0) || 0) > 0 ? 'red' : 'blue'
                            }>
                                {balance?.holdings.reduce((sum, h) => sum + h.pl_amount, 0).toLocaleString()}
                            </Text>
                        </Stack>
                    </Group>

                    {/* Bulk Action Bar using Transition */}
                    <Transition transition="slide-up" mounted={selectedHoldings.length > 0} duration={200}>
                        {(styles) => (
                            <Paper withBorder p="xs" mb="md" bg="blue.0" style={styles}>
                                <Stack gap="xs">
                                    <Group justify="space-between">
                                        <Text fw={700} c="blue">Selected: {selectedHoldings.length}</Text>
                                        <Group gap={5}>
                                            <Button size="xs" color="violet" onClick={() => handleBulkOrder('reservation')}>Reserve</Button>
                                            <Button size="xs" color="red" onClick={() => handleBulkOrder('sell')}>Sell</Button>
                                        </Group>
                                    </Group>
                                    <Group gap={5} align="center">
                                        <Text size="xs" c="dimmed">Time:</Text>
                                        <NumberInput size="xs" w={60} min={0} max={23} value={resHour} onChange={setResHour} />
                                        <Text>:</Text>
                                        <NumberInput size="xs" w={60} min={0} max={59} value={resMin} onChange={setResMin} />
                                    </Group>
                                </Stack>
                            </Paper>
                        )}
                    </Transition>

                    <ScrollArea>
                        <Table striped highlightOnHover style={{ minWidth: 500 }}>
                            <Table.Thead>
                                <Table.Tr>
                                    <Table.Th>
                                        <Checkbox
                                            checked={balance?.holdings.length! > 0 && selectedHoldings.length === balance?.holdings.length}
                                            indeterminate={selectedHoldings.length > 0 && selectedHoldings.length !== balance?.holdings.length}
                                            onChange={toggleSelectAll}
                                        />
                                    </Table.Th>
                                    <Table.Th>종목</Table.Th>
                                    <Table.Th>수량</Table.Th>
                                    <Table.Th>현재가</Table.Th>
                                    <Table.Th>손익</Table.Th>
                                    <Table.Th>수익률</Table.Th>
                                </Table.Tr>
                            </Table.Thead>
                            <Table.Tbody>
                                {balance?.holdings.length === 0 && (
                                    <Table.Tr>
                                        <Table.Td colSpan={6} align="center">보유 주식 없음</Table.Td>
                                    </Table.Tr>
                                )}
                                {balance?.holdings.map((h) => (
                                    <Table.Tr key={h.code} bg={selectedHoldings.includes(h.code) ? 'blue.0' : undefined}>
                                        <Table.Td>
                                            <Checkbox
                                                checked={selectedHoldings.includes(h.code)}
                                                onChange={() => toggleSelectRow(h.code)}
                                            />
                                        </Table.Td>
                                        <Table.Td>
                                            <Stack gap={0}>
                                                <Text size="sm" fw={500}>{h.name}</Text>
                                                <Text size="xs" c="dimmed">{h.code}</Text>
                                                {reservations.some(r => r.code === h.code) && (
                                                    <Badge size="xs" color="violet" variant="light">Resv</Badge>
                                                )}
                                            </Stack>
                                        </Table.Td>
                                        <Table.Td>{h.qty}</Table.Td>
                                        <Table.Td>{h.price.toLocaleString()}</Table.Td>
                                        <Table.Td>
                                            <Text c={h.pl_amount > 0 ? 'red' : (h.pl_amount < 0 ? 'blue' : 'dimmed')}>
                                                {h.pl_amount.toLocaleString()}
                                            </Text>
                                        </Table.Td>
                                        <Table.Td>
                                            <Badge color={h.pl_rate > 0 ? 'red' : (h.pl_rate < 0 ? 'blue' : 'gray')} variant="light">
                                                {h.pl_rate}%
                                            </Badge>
                                        </Table.Td>
                                    </Table.Tr>
                                ))}
                            </Table.Tbody>
                        </Table>
                    </ScrollArea>
                </Paper>

                {/* Active Reservations Panel */}
                {reservations.length > 0 && (
                    <Paper p="md" withBorder radius="md">
                        <Group justify="space-between" mb="md">
                            <Title order={4}>Active Reservations</Title>
                            <Button size="xs" variant="light" onClick={fetchReservations}>Refresh</Button>
                        </Group>
                        <ScrollArea>
                            <Table style={{ minWidth: 400 }}>
                                <Table.Thead>
                                    <Table.Tr>
                                        <Table.Th>Time</Table.Th>
                                        <Table.Th>Stock</Table.Th>
                                        <Table.Th>Type</Table.Th>
                                        <Table.Th>Status/Action</Table.Th>
                                    </Table.Tr>
                                </Table.Thead>
                                <Table.Tbody>
                                    {reservations.map((r) => {
                                        const liveStatus = orderStatuses[r.id];
                                        const finalStatus = liveStatus?.status || r.status || 'RESERVED';

                                        let statusColor = 'blue';
                                        let statusLabel = '매매 예약 완료 (대기 중)';
                                        
                                        if (finalStatus === 'SUCCESS') { statusColor = 'teal'; statusLabel = '체결 성공'; }
                                        else if (finalStatus === 'FAILED') { statusColor = 'red'; statusLabel = '체결 실패'; }
                                        else if (finalStatus === 'DISPATCHED') { statusColor = 'yellow'; statusLabel = '명령 송신 완료 (모바일 응답 대기)'; }

                                        return (
                                        <Table.Tr key={r.id}>
                                            <Table.Td>
                                                {new Date(r.targetTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                            </Table.Td>
                                            <Table.Td>
                                                <Stack gap={0}>
                                                    <Text size="sm">{getStockName(r.code)}</Text>
                                                    <Badge size="xs" color={r.side === 'buy' ? 'red' : 'blue'}>{r.side}</Badge>
                                                </Stack>
                                            </Table.Td>
                                            <Table.Td>{Number(r.price) === 0 ? 'Mkt' : r.price}</Table.Td>
                                            <Table.Td>
                                                <Stack gap={5}>
                                                    <Badge color={statusColor} variant="light">{statusLabel}</Badge>
                                                    {(!r.status || r.status === 'RESERVED') && (
                                                        <Button color="red" size="xs" variant="outline" onClick={() => cancelReservation(r.id)}>
                                                            Cancel
                                                        </Button>
                                                    )}
                                                </Stack>
                                            </Table.Td>
                                        </Table.Tr>
                                    )})}
                                </Table.Tbody>
                            </Table>
                        </ScrollArea>
                    </Paper>
                )}
            </Stack>
        );
    }

    function renderGeminiPortfolio() {
        // ALWAYS return a Paper shell so the section doesn't visually "disappear"
        const holdingsArr = geminiBalance?.holdings ? Object.entries(geminiBalance.holdings).map(([code, h]: any) => ({
            code,
            ...h
        })) : [];

        const totalInvestment = holdingsArr.reduce((sum, h: any) => sum + (h.qty * h.avg_price), 0);
        const totalAsset = (geminiBalance?.cash || 3000000) + totalInvestment;
        const profitRate = ((totalAsset - 3000000) / 3000000) * 100;

        return (
            <Paper p="md" withBorder radius="md" mt="md" style={{ borderColor: '#e599f7', borderWidth: 2 }}>
                <Group justify="space-between" mb="xs">
                    <Title order={4} c="grape">✨ Gemini Portfolio (Paper Trading)</Title>
                    <Badge color="grape" variant="light">Automated AI</Badge>
                </Group>

                <Text size="sm" c="dimmed" mb="md">
                    가상 자본금 3,000,000원으로 AI가 100% 자동 분산 투자합니다. 실계좌 권한은 없습니다.
                </Text>

                <Group justify="space-between" mb="md" align="flex-end">
                    <Stack gap={0}>
                        <Text size="sm" c="dimmed">예수금 잔액</Text>
                        <Title order={3}>
                            {geminiLoading ? '...' : (Math.round(geminiBalance?.cash || 3000000).toLocaleString() + ' 원')}
                        </Title>
                    </Stack>
                    <Group gap="xs">
                        <Button variant="light" color="grape" size="xs" onClick={fetchGeminiBalance}>Refresh</Button>
                    </Group>
                </Group>

                <Group grow mb="md">
                    <Stack gap={0}>
                        <Text size="sm" c="dimmed">총 자산 평가액 (매입가 기준)</Text>
                        <Text fw={700}>{Math.round(totalAsset).toLocaleString()} 원</Text>
                    </Stack>
                    <Stack gap={0}>
                        <Text size="sm" c="dimmed">가상 수익률</Text>
                        <Text fw={700} c={profitRate > 0 ? 'red' : profitRate < 0 ? 'blue' : 'dimmed'}>
                            {profitRate > 0 ? '+' : ''}{profitRate.toFixed(2)}%
                        </Text>
                    </Stack>
                </Group>

                <Tabs defaultValue="holdings" color="grape">
                    <Tabs.List mb="sm">
                        <Tabs.Tab value="holdings" leftSection={<IconClock size={14} />}>Holdings</Tabs.Tab>
                        <Tabs.Tab value="history" leftSection={<IconChartBar size={14} />}>History</Tabs.Tab>
                    </Tabs.List>

                    <Tabs.Panel value="holdings">
                        <ScrollArea>
                            <Table striped highlightOnHover style={{ minWidth: 400 }}>
                                <Table.Thead>
                                    <Table.Tr>
                                        <Table.Th>종목</Table.Th>
                                        <Table.Th>수량</Table.Th>
                                        <Table.Th>평균매입가</Table.Th>
                                        <Table.Th>보유일수</Table.Th>
                                    </Table.Tr>
                                </Table.Thead>
                                <Table.Tbody>
                                    {holdingsArr.length === 0 && (
                                        <Table.Tr>
                                            <Table.Td colSpan={4} align="center">보유 주식 없음</Table.Td>
                                        </Table.Tr>
                                    )}
                                    {holdingsArr.map((h: any) => (
                                        <Table.Tr key={h.code}>
                                            <Table.Td>
                                                <Stack gap={0}>
                                                    <Text size="sm" fw={500}>{h.name}</Text>
                                                    <Text size="xs" c="dimmed">{h.code}</Text>
                                                </Stack>
                                            </Table.Td>
                                            <Table.Td>{h.qty}</Table.Td>
                                            <Table.Td>{Math.round(h.avg_price).toLocaleString()} 원</Table.Td>
                                            <Table.Td>{h.days_held} 일</Table.Td>
                                        </Table.Tr>
                                    ))}
                                </Table.Tbody>
                            </Table>
                        </ScrollArea>
                    </Tabs.Panel>

                    <Tabs.Panel value="history">
                        <ScrollArea h={300}>
                            <Table striped highlightOnHover style={{ minWidth: 500 }}>
                                <Table.Thead>
                                    <Table.Tr>
                                        <Table.Th>날짜</Table.Th>
                                        <Table.Th>종목</Table.Th>
                                        <Table.Th>구분</Table.Th>
                                        <Table.Th>가격</Table.Th>
                                        <Table.Th>수량</Table.Th>
                                        <Table.Th>수익률/이유</Table.Th>
                                    </Table.Tr>
                                </Table.Thead>
                                <Table.Tbody>
                                    {(!geminiBalance?.trade_log || geminiBalance.trade_log.length === 0) && (
                                        <Table.Tr>
                                            <Table.Td colSpan={6} align="center">
                                                {geminiLoading ? '로딩 중...' : '매매 내역 없음'}
                                            </Table.Td>
                                        </Table.Tr>
                                    )}
                                    {[...(geminiBalance?.trade_log || [])].reverse().map((log: any, idx: number) => (
                                        <Table.Tr key={idx}>
                                            <Table.Td width={100}>
                                                <Text size="xs">{log.date.split(' ')[0]}</Text>
                                                <Text size="xs" c="dimmed">{log.date.split(' ')[1]}</Text>
                                            </Table.Td>
                                            <Table.Td>
                                                <Text size="sm" fw={500}>{log.name}</Text>
                                                <Text size="xs" c="dimmed">{log.code}</Text>
                                            </Table.Td>
                                            <Table.Td>
                                                <Badge size="sm" color={log.type === 'BUY' ? 'red' : 'blue'}>
                                                    {log.type}
                                                </Badge>
                                            </Table.Td>
                                            <Table.Td>{Math.round(log.price).toLocaleString()}</Table.Td>
                                            <Table.Td>{log.qty}</Table.Td>
                                            <Table.Td>
                                                <Stack gap={0}>
                                                    {log.profit_rate !== undefined && (
                                                        <Text size="xs" fw={700} c={log.profit_rate > 0 ? 'red' : 'blue'}>
                                                            {log.profit_rate > 0 ? '+' : ''}{log.profit_rate.toFixed(2)}%
                                                        </Text>
                                                    )}
                                                    <Text size="xs" c="dimmed" style={{ maxWidth: 120, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                                        {log.reason || (log.prob ? `Prob: ${log.prob.toFixed(1)}%` : '')}
                                                    </Text>
                                                </Stack>
                                            </Table.Td>
                                        </Table.Tr>
                                    ))}
                                </Table.Tbody>
                            </Table>
                        </ScrollArea>
                    </Tabs.Panel>
                </Tabs>
            </Paper>
        );
    }

    function renderTrading() {
        return (
            <Stack>
                <Paper p="md" withBorder radius="md">
                    <Title order={4} mb="md">Place Order</Title>

                    <Tabs defaultValue="immediate">
                        <Tabs.List mb="md">
                            <Tabs.Tab value="immediate">Immediate</Tabs.Tab>
                            <Tabs.Tab value="reservation">Reservation</Tabs.Tab>
                        </Tabs.List>

                        <Group mb="sm" grow>
                            <Button
                                variant={orderType === 'buy' ? 'filled' : 'outline'}
                                color="red"
                                onClick={() => setOrderType('buy')}
                            >
                                BUY
                            </Button>
                            <Button
                                variant={orderType === 'sell' ? 'filled' : 'outline'}
                                color="blue"
                                onClick={() => setOrderType('sell')}
                            >
                                SELL
                            </Button>
                        </Group>

                        <Stack>
                            <Select
                                label="Stock"
                                placeholder="Search Stock"
                                searchable
                                data={stocks.map(s => ({ value: s.code, label: `${s.name} (${s.code})` }))}
                                value={code}
                                onChange={(val) => setCode(val || '')}
                                maxDropdownHeight={200}
                            />
                            <NumberInput
                                label="Quantity"
                                min={1}
                                value={qty} onChange={(val) => setQty(val || 1)}
                            />
                            {orderType === 'sell' && (
                                <Group justify="flex-end" mt={5}>
                                    <Badge
                                        size="sm"
                                        variant="outline"
                                        style={{ cursor: 'pointer' }}
                                        onClick={handleSellAll}
                                    >
                                        전액 매도
                                    </Badge>
                                </Group>
                            )}
                            <NumberInput
                                label="Price (0 = Market)"
                                min={0}
                                step={100}
                                value={price} onChange={(val) => setPrice(val || 0)}
                            />
                        </Stack>

                        <Tabs.Panel value="immediate" pt="md">
                            <Button fullWidth size="lg" loading={orderLoading} onClick={() => handleOrder(false)} disabled={orderLoading}>
                                {orderLoading ? '[전송 중...]' : 'Submit Order'}
                            </Button>
                            
                            {/* Live Status Trackers */}
                            {trackingOrders.length > 0 && (
                                <Stack mt="md" gap="xs">
                                    <Text size="sm" fw={500}>실시간 체결 결과 대기 중...</Text>
                                    {trackingOrders.map(odno => {
                                        const statusObj = orderStatuses[odno];
                                        const status = statusObj?.status || 'PENDING';
                                        
                                        const color = status === 'SUCCESS' ? 'teal' : 
                                                      status === 'FAILED' ? 'red' : 
                                                      status === 'PROCESSING' ? 'blue' : 'gray';
                                        const label = status === 'SUCCESS' ? '체결 완료' : 
                                                      status === 'FAILED' ? '거절/오류' : 
                                                      status === 'PROCESSING' ? '모바일 접수' : '명령 송신 완료 (모바일 응답 대기 중...)';
                                        
                                        return (
                                            <Paper key={odno} p="xs" withBorder>
                                                <Group justify="space-between">
                                                    <Text size="xs">{odno}</Text>
                                                    <Badge color={color} variant="light">{label}</Badge>
                                                </Group>
                                            </Paper>
                                        );
                                    })}
                                </Stack>
                            )}
                        </Tabs.Panel>

                        <Tabs.Panel value="reservation" pt="md">
                            <Group grow>
                                <NumberInput label="Hour" min={0} max={23} value={resHour} onChange={setResHour} />
                                <NumberInput label="Minute" min={0} max={59} value={resMin} onChange={setResMin} />
                            </Group>
                            <Text size="xs" c="dimmed" mt="xs">
                                * Local browser reservation.
                            </Text>
                            <Button fullWidth size="lg" mt="md" color="violet" loading={orderLoading} onClick={() => handleOrder(true)} disabled={orderLoading}>
                                {orderLoading ? '[전송 중...]' : 'Schedule Order'}
                            </Button>
                        </Tabs.Panel>
                    </Tabs>
                </Paper>
            </Stack>
        );
    }
}
