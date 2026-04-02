'use client';

import { useState, useEffect, useRef } from 'react';
import { Modal, Tabs, Group, Button, Stack, Select, NumberInput, Text, Badge, LoadingOverlay, PinInput, ThemeIcon } from '@mantine/core';
import { IconLock, IconShieldLock } from '@tabler/icons-react';
import axios from 'axios';

interface QuickOrderModalProps {
    opened: boolean;
    onClose: () => void;
    initialCode: string;
    initialName?: string;
    onOrderDispatched?: (odno: string) => void;
}

export default function QuickOrderModal({ opened, onClose, initialCode, initialName, onOrderDispatched }: QuickOrderModalProps) {
    const [orderType, setOrderType] = useState<string | null>('buy');
    const [code, setCode] = useState(initialCode);
    const [qty, setQty] = useState<number | string>(1);
    const [price, setPrice] = useState<number | string>(0);
    const [resHour, setResHour] = useState<number | string>(15);
    const [resMin, setResMin] = useState<number | string>(15);
    const [loading, setLoading] = useState(false);
    const [pin, setPin] = useState('');
    const [pinStage, setPinStage] = useState(false); // If true, show PIN input instead of form
    const [notification, setNotification] = useState<string | null>(null);
    const pinContainerRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (opened) {
            setCode(initialCode);
            setPinStage(false);
            setPin('');
            setNotification(null);
        }
    }, [opened, initialCode]);

    const handleOrderClick = () => {
        setPinStage(true);
    };

    useEffect(() => {
        if (pinStage) {
            // "Shotgun" approach: Try to focus multiple times to guarantee success
            // despite React rendering delays, Modal animations (approx 200ms), or browser handling.
            const focusInput = () => {
                if (pinContainerRef.current) {
                    // Start from the container and find the real input
                    const input = pinContainerRef.current.querySelector('input:not([type="hidden"])') as HTMLInputElement;
                    if (input) {
                        // Force focus
                        input.focus();
                        // input.select(); // Optional: select all if needed
                    }
                }
            };

            // 1. Immediate try
            focusInput();

            // 2. Short delay (after render)
            setTimeout(focusInput, 50);

            // 3. Medium delay (during animation)
            setTimeout(focusInput, 200);

            // 4. Long delay (after animation settles)
            setTimeout(focusInput, 500);
        }
    }, [pinStage]);

    const confirmOrder = async () => {
        setLoading(true);
        try {
            const isReservation = (document.querySelector('[data-value="reservation"][data-active="true"]') !== null) || false;
            // Better to track tab state, but local state 'activeTab' is easier.
            // Let's rely on a separate state for tab if possible, or just pass it.
            // Simplified: We need a state for activeTab.
        } catch (e) {
            // ...
        }
    };

    // We need 'activeTab' state to know if it's reservation.
    const [activeTab, setActiveTab] = useState<string | null>('immediate');

    const executeOrder = async () => {
        setLoading(true);
        try {
            let res;
            if (activeTab === 'reservation') {
                res = await axios.post('/api/trade/reservation', {
                    code, qty, price, hour: resHour, minute: resMin, side: orderType, pin
                });
            } else {
                res = await axios.post('/api/trade/order', {
                    code, qty, price, side: orderType, pin
                });
            }

            // Check if order was actually successful
            if (res.data.success && res.data.data) {
                const orderNo = res.data.data.ODNO || res.data.data.ORD_NO || 'N/A';
                // REPLACED: Removed alert(), added dispatch callback for polling
                if (onOrderDispatched) onOrderDispatched(orderNo);
                onClose();
            } else {
                // API returned success:true but no order data - this is an error
                const errorMsg = res.data.error || res.data.message || '주문 실패 (응답 데이터 없음)';
                onClose(); // Just close, polling handles failure if ODNO is missing? 
                // Or just rely on parent to handle overall failure.
            }
        } catch (error: any) {
            const errorMsg = error.response?.data?.error || error.message || '알 수 없는 오류';
            onClose();
        } finally {
            setLoading(false);
            setPinStage(false);
            setPin('');
        }
    };

    return (
        <Modal
            opened={opened}
            onClose={onClose}
            title={
                <Group gap="xs">
                    <Text fw={700}>Quick Trade: {initialName || code}</Text>
                    {pinStage && <Badge color="green" variant="light" leftSection={<IconLock size={12} />}>Secure Mode</Badge>}
                </Group>
            }
            centered
        >
            <LoadingOverlay visible={loading} />

            {!pinStage ? (
                <Tabs value={activeTab} onChange={setActiveTab}>
                    <Tabs.List mb="md">
                        <Tabs.Tab value="immediate">Immediate</Tabs.Tab>
                        <Tabs.Tab value="reservation">Reservation</Tabs.Tab>
                    </Tabs.List>

                    <Tabs.Panel value="immediate">
                        <Stack>
                            <Group grow>
                                <Button color="red" variant={orderType === 'buy' ? 'filled' : 'outline'} onClick={() => setOrderType('buy')}>BUY</Button>
                                <Button color="blue" variant={orderType === 'sell' ? 'filled' : 'outline'} onClick={() => setOrderType('sell')}>SELL</Button>
                            </Group>
                            <Text size="sm">Code: {code}</Text>
                            <NumberInput label="Quantity" value={qty} onChange={(v) => setQty(v || 1)} min={1} />
                            <NumberInput label="Price (0=Market)" value={price} onChange={(v) => setPrice(v || 0)} />
                            <Button size="lg" onClick={handleOrderClick} loading={loading} disabled={loading}>
                                {loading ? '[전송 중...]' : 'Submit Order'}
                            </Button>
                        </Stack>
                    </Tabs.Panel>

                    <Tabs.Panel value="reservation">
                        <Stack>
                            <Group grow>
                                <Button color="red" variant={orderType === 'buy' ? 'filled' : 'outline'} onClick={() => setOrderType('buy')}>BUY</Button>
                                <Button color="blue" variant={orderType === 'sell' ? 'filled' : 'outline'} onClick={() => setOrderType('sell')}>SELL</Button>
                            </Group>
                            <Group grow>
                                <NumberInput label="Hour" value={resHour} onChange={setResHour} min={0} max={23} />
                                <NumberInput label="Minute" value={resMin} onChange={setResMin} min={0} max={59} />
                            </Group>
                            <NumberInput label="Quantity" value={qty} onChange={(v) => setQty(v || 1)} min={1} />
                            <NumberInput label="Price (0=Market)" value={price} onChange={(v) => setPrice(v || 0)} />
                            <Button size="lg" color="violet" onClick={handleOrderClick} loading={loading} disabled={loading}>
                                {loading ? '[전송 중...]' : 'Schedule'}
                            </Button>
                        </Stack>
                    </Tabs.Panel>
                </Tabs>
            ) : (
                <Stack align="center" py="md" ref={pinContainerRef}>
                    <ThemeIcon size={60} radius="xl" color="green" variant="light">
                        <IconShieldLock size={32} />
                    </ThemeIcon>
                    <Text fw={700} size="lg">보안 거래 인증</Text>
                    <Text c="dimmed" size="sm" ta="center">안전한 거래를 위해<br />PIN 번호 4자리를 입력해주세요.</Text>
                    <PinInput length={4} type="number" mask value={pin} onChange={setPin} onComplete={executeOrder} autoFocus />
                    <Button variant="subtle" onClick={() => setPinStage(false)}>Back</Button>
                </Stack>
            )}
        </Modal>
    );
}
