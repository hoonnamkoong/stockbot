'use client';

import { useState, useEffect, useRef } from 'react';
import { Modal, Tabs, Group, Button, Stack, NumberInput, Text, Badge, LoadingOverlay, PinInput, ThemeIcon, Notification } from '@mantine/core';
import { IconLock, IconShieldLock, IconCheck, IconX } from '@tabler/icons-react';
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
    const [pinStage, setPinStage] = useState(false);
    const [notification, setNotification] = useState<{ color: string; msg: string } | null>(null);
    const [activeTab, setActiveTab] = useState<string | null>('immediate');
    const pinContainerRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (opened) {
            setCode(initialCode);
            setPinStage(false);
            setPin('');
            setNotification(null);
            setLoading(false);
        }
    }, [opened, initialCode]);

    useEffect(() => {
        if (pinStage) {
            const focusInput = () => {
                if (pinContainerRef.current) {
                    const input = pinContainerRef.current.querySelector('input:not([type="hidden"])') as HTMLInputElement;
                    if (input) input.focus();
                }
            };
            focusInput();
            setTimeout(focusInput, 50);
            setTimeout(focusInput, 200);
            setTimeout(focusInput, 500);
        }
    }, [pinStage]);

    const handleOrderClick = () => {
        setNotification(null);
        setPinStage(true);
    };

    const executeOrder = async (completedPin?: string) => {
        const pinToUse = completedPin || pin;
        if (pinToUse.length !== 4) return;

        setLoading(true);
        try {
            let res;
            if (activeTab === 'reservation') {
                res = await axios.post('/api/trade/reservation', {
                    code, qty, price, hour: resHour, minute: resMin, side: orderType, pin: pinToUse
                });
            } else {
                res = await axios.post('/api/trade/order', {
                    code,
                    name: initialName || code,
                    qty,
                    price,
                    side: orderType,
                    pin: pinToUse
                });
            }

            if (res.data.success) {
                const odno = res.data.data?.ODNO || `SIM-${Date.now()}`;
                if (onOrderDispatched) onOrderDispatched(odno);
                onClose();
            } else {
                const errorMsg = res.data.error || '주문 실패';
                setNotification({ color: 'red', msg: errorMsg });
                setPinStage(false);
                setPin('');
            }
        } catch (error: any) {
            const errorMsg = error.response?.data?.error || error.message || '알 수 없는 오류';
            if (error.response?.status === 401) {
                setNotification({ color: 'red', msg: 'PIN 번호가 올바르지 않습니다' });
            } else {
                setNotification({ color: 'red', msg: `주문 실패: ${errorMsg}` });
            }
            setPinStage(false);
            setPin('');
        } finally {
            setLoading(false);
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

            {notification && (
                <Notification
                    color={notification.color}
                    mb="md"
                    onClose={() => setNotification(null)}
                    icon={notification.color === 'red' ? <IconX size={14} /> : <IconCheck size={14} />}
                >
                    {notification.msg}
                </Notification>
            )}

            {!pinStage ? (
                <Tabs value={activeTab} onChange={setActiveTab}>
                    <Tabs.List mb="md">
                        <Tabs.Tab value="immediate">즉시 주문</Tabs.Tab>
                        <Tabs.Tab value="reservation">예약 주문</Tabs.Tab>
                    </Tabs.List>

                    <Tabs.Panel value="immediate">
                        <Stack>
                            <Group grow>
                                <Button color="red" variant={orderType === 'buy' ? 'filled' : 'outline'} onClick={() => setOrderType('buy')}>매수 (BUY)</Button>
                                <Button color="blue" variant={orderType === 'sell' ? 'filled' : 'outline'} onClick={() => setOrderType('sell')}>매도 (SELL)</Button>
                            </Group>
                            <Text size="sm" c="dimmed">종목코드: {code} {initialName ? `(${initialName})` : ''}</Text>
                            <NumberInput label="수량" value={qty} onChange={(v) => setQty(v || 1)} min={1} />
                            <NumberInput label="가격 (0 = 시장가)" value={price} onChange={(v) => setPrice(v || 0)} />
                            <Button size="lg" color={orderType === 'buy' ? 'red' : 'blue'} onClick={handleOrderClick} loading={loading} disabled={loading}>
                                {orderType === 'buy' ? '매수 주문' : '매도 주문'}
                            </Button>
                        </Stack>
                    </Tabs.Panel>

                    <Tabs.Panel value="reservation">
                        <Stack>
                            <Group grow>
                                <Button color="red" variant={orderType === 'buy' ? 'filled' : 'outline'} onClick={() => setOrderType('buy')}>매수 (BUY)</Button>
                                <Button color="blue" variant={orderType === 'sell' ? 'filled' : 'outline'} onClick={() => setOrderType('sell')}>매도 (SELL)</Button>
                            </Group>
                            <Group grow>
                                <NumberInput label="시 (Hour)" value={resHour} onChange={setResHour} min={0} max={23} />
                                <NumberInput label="분 (Minute)" value={resMin} onChange={setResMin} min={0} max={59} />
                            </Group>
                            <NumberInput label="수량" value={qty} onChange={(v) => setQty(v || 1)} min={1} />
                            <NumberInput label="가격 (0 = 시장가)" value={price} onChange={(v) => setPrice(v || 0)} />
                            <Button size="lg" color="violet" onClick={handleOrderClick} loading={loading} disabled={loading}>
                                예약 등록
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
                    <PinInput
                        length={4}
                        type="number"
                        mask
                        value={pin}
                        onChange={setPin}
                        onComplete={(val) => executeOrder(val)}
                        autoFocus
                    />
                    <Button variant="subtle" onClick={() => { setPinStage(false); setPin(''); }}>취소</Button>
                </Stack>
            )}
        </Modal>
    );
}
