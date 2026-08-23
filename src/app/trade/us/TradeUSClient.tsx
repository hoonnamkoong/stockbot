'use client';

import { useEffect, useState } from 'react';
import { Container, Title, Text, Group, Button, NumberInput, Modal, SimpleGrid, Anchor, Alert } from '@mantine/core';
import Link from 'next/link';
import SimCard from '../SimCard';
import { US_SIM_REGISTRY } from '@/lib/us-sim-registry.generated';

export default function TradeUSClient() {
    const [stats, setStats] = useState<any>({});
    const [history, setHistory] = useState<any[]>([]);
    const [resetCash, setResetCash] = useState<number | ''>(20000);
    const [resetConfirmOpen, setResetConfirmOpen] = useState(false);
    const [resetBusy, setResetBusy] = useState(false);

    async function load() {
        const [statsRes, historyRes] = await Promise.all([
            fetch('/api/simulation/stats-us', { cache: 'no-store' }),
            fetch('/api/trade/history-us', { cache: 'no-store' }),
        ]);
        setStats(await statsRes.json());
        const historyBody = await historyRes.json();
        setHistory(historyBody.data ?? []);
    }

    useEffect(() => {
        load();
        const t = setInterval(load, 30_000);
        return () => clearInterval(t);
    }, []);

    async function handleReset() {
        if (typeof resetCash !== 'number' || !Number.isInteger(resetCash) || resetCash < 1000 || resetCash > 500000) {
            return;
        }
        setResetBusy(true);
        try {
            await fetch('/api/simulation/reset-us', {
                method: 'POST',
                body: JSON.stringify({ cash: resetCash }),
            });
            await load();
        } finally {
            setResetBusy(false);
            setResetConfirmOpen(false);
        }
    }

    return (
        <Container size="xl" py="md">
            <Group justify="space-between" mb="md">
                <Title order={2}>미국 트레이딩 (페이퍼)</Title>
                <Anchor component={Link} href="/trade">국내 트레이딩으로</Anchor>
            </Group>
            <Alert color="blue" mb="md">
                페이퍼(관찰) 전용입니다 — 실주문 연동 없음, 자본 이동 없음.
            </Alert>
            <Group mb="lg">
                <NumberInput
                    placeholder="예수금(USD)"
                    value={resetCash}
                    onChange={(v) => setResetCash(typeof v === 'number' ? v : '')}
                    disabled={resetBusy}
                    min={1000}
                    max={500000}
                />
                <Button color="red" size="xs" onClick={() => setResetConfirmOpen(true)} disabled={resetBusy} loading={resetBusy}>
                    전체 리셋
                </Button>
            </Group>
            <SimpleGrid cols={{ base: 1, lg: 2 }}>
                {US_SIM_REGISTRY.map((s) => (
                    <SimCard
                        key={s.id}
                        uiKey={s.uiKey}
                        label={s.label}
                        color={s.color}
                        type={s.id}
                        stats={stats[s.uiKey]?.raw ?? {}}
                        portfolio={stats[s.uiKey]?.portfolio ?? {}}
                        history={history}
                        onPickCode={() => {}}
                        onShowReason={() => {}}
                        currency="USD"
                    />
                ))}
            </SimpleGrid>
            <Modal opened={resetConfirmOpen} onClose={() => setResetConfirmOpen(false)} title="정말 초기화할까요?" centered>
                <Text size="sm" mb="md">
                    US 심 전체를 <b>{typeof resetCash === 'number' ? `$${resetCash.toLocaleString()}` : '-'}</b>로 초기화합니다.
                </Text>
                <Group justify="flex-end">
                    <Button variant="default" onClick={() => setResetConfirmOpen(false)} disabled={resetBusy}>취소</Button>
                    <Button color="red" onClick={handleReset} disabled={resetBusy} loading={resetBusy}>초기화</Button>
                </Group>
            </Modal>
        </Container>
    );
}
