'use client';

import { useState, useEffect, useRef } from 'react';
import {
    Container, Title, Text, Paper, Group, Stack,
    Table, Badge, Button, Tabs, TextInput, NumberInput,
    Select, Notification, LoadingOverlay, Modal, PinInput, Checkbox, Affix, Transition
} from '@mantine/core';
import { IconCoin, IconClock, IconChartBar } from '@tabler/icons-react';
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
    market: string;
}

export default function TradePage() {
    const [balance, setBalance] = useState<BalanceData | null>(null);
    const [stocks, setStocks] = useState<StockItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [orderLoading, setOrderLoading] = useState(false);
    const [notification, setNotification] = useState<{ title: string, msg: string, color: string } | null>(null);

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

    // Reservations
    const [reservations, setReservations] = useState<any[]>([]);

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

    const fetchBalance = async () => {
        setLoading(true);
        try {
            // Add timestamp to prevent browser caching
            const res = await axios.get(`/api/trade/balance?t=${Date.now()}`);
            setBalance(res.data);
        } catch (error) {
            console.error(error);
            showNotify('Error', 'Failed to fetch balance', 'red');
        } finally {
            setLoading(false);
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
            setReservations(res.data.reservations || []);
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

    useEffect(() => {
        fetchBalance();
        fetchStocks();
        fetchReservations();
    }, []);

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
                showNotify('Bulk Action Complete', `Success: ${successCount}, Failed: ${failCount}`, 'teal');
                fetchBalance();
                setSelectedHoldings([]); // Clear selection

            } else {
                // SINGLE EXECUTION
                if (isReservation) {
                    const res = await axios.post('/api/trade/reservation', {
                        code, qty, price, hour: resHour, minute: resMin, side: orderType, pin
                    });
                    showNotify('Success', res.data.message, 'green');
                    fetchReservations(); // Refresh List
                } else {
                    const res = await axios.post('/api/trade/order', {
                        code, qty, price, side: orderType, pin
                    });
                    if (res.data.success) {
                        showNotify('Success', `Order Placed! No: ${res.data.data.ODNO}`, 'teal');
                        fetchBalance(); // Refresh
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

            <Modal opened={pinModalOpen} onClose={() => setPinModalOpen(false)} title="Security Verification" centered>
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

            <Group justify="space-between" mb="lg">
                <Title order={2}>Stock Trading</Title>
                <Group>
                    <Button component="a" href="/research" size="sm" variant="light" leftSection={<IconChartBar size={20} />}>
                        StockBot Research
                    </Button>
                    <Button color="gray" variant="subtle" size="sm" onClick={() => signOut({ callbackUrl: '/login' })}>
                        Sign Out
                    </Button>
                </Group>
            </Group>

            <Group grow align="flex-start">
                {/* 1. Portfolio Section */}
                <Stack>
                    <Paper p="md" withBorder radius="md">
                        <Title order={4} mb="md">My Portfolio</Title>
                        <LoadingOverlay visible={loading} />

                        <Group justify="space-between" mb="md" align="flex-end">
                            <Stack gap={0}>
                                <Text size="sm" c="dimmed">예수금 (Cash)</Text>
                                <Title order={3}>{balance?.deposit.toLocaleString()} KRW</Title>
                            </Stack>

                            <Stack gap={0}>
                                <Text size="sm" c="dimmed">주식 총액 (Stock Value)</Text>
                                <Title order={3}>
                                    {balance?.holdings.reduce((sum, h) => sum + (h.price * h.qty), 0).toLocaleString()} KRW
                                </Title>
                            </Stack>

                            <Stack gap={0}>
                                <Text size="sm" c="dimmed">주식 수익 (Stock P/L)</Text>
                                <Title order={3} c={
                                    (balance?.holdings.reduce((sum, h) => sum + h.pl_amount, 0) || 0) > 0 ? 'red' :
                                        (balance?.holdings.reduce((sum, h) => sum + h.pl_amount, 0) || 0) < 0 ? 'blue' : 'dimmed'
                                }>
                                    {balance?.holdings.reduce((sum, h) => sum + h.pl_amount, 0).toLocaleString()} KRW
                                </Title>
                            </Stack>

                            <Group gap="xs">
                                <Button variant="light" size="xs" onClick={fetchBalance}>Refresh</Button>
                            </Group>
                        </Group>

                        {/* Bulk Action Bar using Transition to smooth appearance */}
                        <Transition transition="slide-up" mounted={selectedHoldings.length > 0} duration={200}>
                            {(styles) => (
                                <Paper withBorder p="xs" mb="md" bg="blue.0" style={styles}>
                                    <Group justify="space-between">
                                        <Group>
                                            <Text fw={700} c="blue">Selected: {selectedHoldings.length} stocks</Text>
                                            {/* Reservation Time Picker for Bulk */}
                                            <Group gap={5} align="center">
                                                <Text size="xs" c="dimmed">Res. Time:</Text>
                                                <NumberInput size="xs" w={50} min={0} max={23} value={resHour} onChange={setResHour} placeholder="HH" />
                                                <Text>:</Text>
                                                <NumberInput size="xs" w={50} min={0} max={59} value={resMin} onChange={setResMin} placeholder="MM" />
                                            </Group>
                                        </Group>
                                        <Group gap="xs">
                                            <Button size="xs" color="violet" leftSection={<IconClock size={14} />} onClick={() => handleBulkOrder('reservation')}>
                                                Bulk Reserve Sell
                                            </Button>
                                            <Button size="xs" color="red" leftSection={<IconCoin size={14} />} onClick={() => handleBulkOrder('sell')}>
                                                Bulk Sell Now
                                            </Button>
                                        </Group>
                                    </Group>
                                </Paper>
                            )}
                        </Transition>

                        <Table striped highlightOnHover>
                            <Table.Thead>
                                <Table.Tr>
                                    <Table.Th>
                                        <Checkbox
                                            checked={balance?.holdings.length! > 0 && selectedHoldings.length === balance?.holdings.length}
                                            indeterminate={selectedHoldings.length > 0 && selectedHoldings.length !== balance?.holdings.length}
                                            onChange={toggleSelectAll}
                                        />
                                    </Table.Th>
                                    <Table.Th>Stock</Table.Th>
                                    <Table.Th>Qty</Table.Th>
                                    <Table.Th>Cur. Price</Table.Th>
                                    <Table.Th>Avg. Price</Table.Th>
                                    <Table.Th>Last Buy</Table.Th>
                                    <Table.Th>P/L Amt</Table.Th>
                                    <Table.Th>P/L %</Table.Th>
                                </Table.Tr>
                            </Table.Thead>
                            <Table.Tbody>
                                {balance?.holdings.length === 0 && (
                                    <Table.Tr>
                                        <Table.Td colSpan={8} align="center">No holdings</Table.Td>
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
                                                {/* Show if reserved */}
                                                {reservations.some(r => r.code === h.code) && (
                                                    <Badge size="xs" color="violet" variant="light">Reserved</Badge>
                                                )}
                                            </Stack>
                                        </Table.Td>
                                        <Table.Td>{h.qty}</Table.Td>
                                        <Table.Td>{h.price.toLocaleString()}</Table.Td>
                                        <Table.Td>{h.avg_price.toLocaleString()}</Table.Td>
                                        <Table.Td>
                                            <Text size="xs" c="dimmed">{h.last_buy_date || '-'}</Text>
                                        </Table.Td>
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
                    </Paper>

                    {/* Active Reservations Panel */}
                    {reservations.length > 0 && (
                        <Paper p="md" withBorder radius="md">
                            <Group justify="space-between" mb="md">
                                <Title order={4}>Active Reservations ({reservations.length})</Title>
                                <Button size="xs" variant="light" onClick={fetchReservations}>Refresh</Button>
                            </Group>
                            <Table>
                                <Table.Thead>
                                    <Table.Tr>
                                        <Table.Th>Time</Table.Th>
                                        <Table.Th>Stock</Table.Th>
                                        <Table.Th>Type</Table.Th>
                                        <Table.Th>Qty</Table.Th>
                                        <Table.Th>Price</Table.Th>
                                        <Table.Th>Action</Table.Th>
                                    </Table.Tr>
                                </Table.Thead>
                                <Table.Tbody>
                                    {reservations.map((r) => (
                                        <Table.Tr key={r.id}>
                                            <Table.Td>
                                                {new Date(r.targetTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                            </Table.Td>
                                            <Table.Td>
                                                <Text size="sm">{getStockName(r.code)}</Text>
                                                <Text size="xs" c="dimmed">{r.code}</Text>
                                            </Table.Td>
                                            <Table.Td>
                                                <Badge color={r.side === 'buy' ? 'red' : 'blue'}>{r.side.toUpperCase()}</Badge>
                                            </Table.Td>
                                            <Table.Td>{r.qty}</Table.Td>
                                            <Table.Td>{Number(r.price) === 0 ? 'Market' : r.price}</Table.Td>
                                            <Table.Td>
                                                <Button color="red" size="xs" variant="outline" onClick={() => cancelReservation(r.id)}>
                                                    Cancel
                                                </Button>
                                            </Table.Td>
                                        </Table.Tr>
                                    ))}
                                </Table.Tbody>
                            </Table>
                        </Paper>
                    )}
                </Stack>

                {/* 2. Trading Section */}
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
                                    placeholder="Search Stock (e.g. Samsung)"
                                    searchable
                                    data={stocks.map(s => ({ value: s.code, label: `${s.name} (${s.code})` }))}
                                    value={code}
                                    onChange={(val) => setCode(val || '')}
                                    nothingFoundMessage="No stock found"
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
                                            전액 매도 (Sell All)
                                        </Badge>
                                    </Group>
                                )}
                                <NumberInput
                                    label="Price (0 = Market Price)"
                                    min={0}
                                    step={100}
                                    value={price} onChange={(val) => setPrice(val || 0)}
                                />
                            </Stack>

                            <Tabs.Panel value="immediate" pt="md">
                                <Button fullWidth size="lg" loading={orderLoading} onClick={() => handleOrder(false)}>
                                    Submit Order
                                </Button>
                            </Tabs.Panel>

                            <Tabs.Panel value="reservation" pt="md">
                                <Group grow>
                                    <NumberInput label="Hour" min={0} max={23} value={resHour} onChange={setResHour} />
                                    <NumberInput label="Minute" min={0} max={59} value={resMin} onChange={setResMin} />
                                </Group>
                                <Text size="xs" c="dimmed" mt="xs">
                                    * Order will be executed locally at the specified time.
                                </Text>
                                <Button fullWidth size="lg" mt="md" color="violet" loading={orderLoading} onClick={() => handleOrder(true)}>
                                    Schedule Order
                                </Button>
                            </Tabs.Panel>
                        </Tabs>
                    </Paper>
                </Stack>
            </Group>
        </Container >
    );
}
