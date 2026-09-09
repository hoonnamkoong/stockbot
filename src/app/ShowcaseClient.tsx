'use client';

import { useCallback, useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import {
    Container, Title, Text, Group, Stack, Button, Divider, Box, Modal, Paper, Loader, Center,
} from '@mantine/core';
import SimulationSection from './components/SimulationSection';
import { StockTable } from './research/components/ResearchTables';
import { mapStockRow, sortRows, nextSort, type SortConfig } from '@/lib/research-rows';

const StrategyRadarChart = dynamic(() => import('./components/StrategyRadarChart'), {
    ssr: false,
    loading: () => <Center py="xl"><Loader /></Center>,
});

/**
 * 공개 쇼케이스 — 로그인 없이 볼 수 있는 유일한 화면.
 *
 * `/trade` 하단과 **같은 `SimulationSection`**을 쓴다. 다른 것은 prop 두 개뿐:
 * `reset` 없음(빨간 전체 리셋 패널 없음), `onPickCode` 없음(보유 종목 읽기 전용).
 *
 * **여기서 부르는 API는 전부 db-data(공개 브랜치)가 원본이다.**
 *   - /api/simulation/stats : 심 상태 JSON
 *   - /api/trade/history    : 세션이 없으면 심 기록만 온다(2026-09-09 수정).
 *                             이 페이지가 공개될 수 있는 것은 그 수정 덕분이다.
 * 실계좌를 만지는 경로(/api/portfolio/real, /api/trade/order, program)는 이 화면
 * 어디에서도 부르지 않는다.
 */
export default function ShowcaseClient() {
    const [balances, setBalances] = useState<Record<string, any> | null>(null);
    const [history, setHistory] = useState<any[]>([]);
    const [stocks, setStocks] = useState<any[]>([]);
    const [updatedAt, setUpdatedAt] = useState('');
    const [sort, setSort] = useState<SortConfig>({ key: 'recent_posts_count', direction: 'desc' });
    const [loading, setLoading] = useState(true);
    const [reason, setReason] = useState({ title: '', content: '' });
    const [reasonOpen, setReasonOpen] = useState(false);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const [statsRes, histRes, researchRes] = await Promise.all([
                fetch(`/api/simulation/stats?cb=${Date.now()}`),
                fetch(`/api/trade/history?cb=${Date.now()}`),
                fetch(`/api/stocks/research?cb=${Date.now()}`),
            ]);
            setBalances(await statsRes.json());
            const hist = await histRes.json();
            if (hist.success) setHistory(hist.data);
            const research = await researchRes.json();
            if (research.success) {
                // 행 매핑은 `/research`와 **같은 함수**를 쓴다 — 사본을 두면
                // 스크래퍼가 필드 이름을 바꿀 때 한쪽만 고쳐진다.
                setStocks((research.stocks || []).map(mapStockRow));
                setUpdatedAt(research.status?.last_updated || '');
            }
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const showReason = (title: string, content: string) => {
        setReason({ title, content });
        setReasonOpen(true);
    };

    return (
        <Container size="xl" py="xl">
            <Group justify="space-between" align="flex-start" mb="xl" wrap="wrap">
                <Stack gap={4}>
                    <Title order={1}>StockBot</Title>
                    <Text c="dimmed" size="sm" maw={640}>
                        국내 주식 자동매매 시스템. 여러 전략을 동시에 시뮬레이션하고, 시장 국면에 따라
                        전략을 전환한다. 아래 숫자는 실제로 매일 장중에 돌고 있는 시뮬레이터의 상태다.
                    </Text>
                </Stack>
                {/* **비공개 페이지로 가는 링크는 두지 않는다.** 공개 방문자에게
                    보이는 링크가 로그인 벽으로 이어지면 고장으로 읽히고, 관리자
                    경로가 어디인지 알려 주기만 한다. 바깥으로 나가는 GitHub만 둔다. */}
                <Button
                    component="a"
                    href="https://github.com/hoonnamkoong/stockbot"
                    target="_blank" rel="noopener noreferrer"
                    variant="subtle" size="sm"
                >
                    GitHub
                </Button>
            </Group>

            <Divider my="md" label="Market Research" labelPosition="center" />
            <Text c="dimmed" size="xs" mb="sm">
                매 거래일 수집한 종목별 관심도·수급 데이터. 열 머리를 눌러 정렬할 수 있다.
                {updatedAt && ` · 갱신 ${updatedAt}`}
            </Text>

            {loading && !stocks.length ? (
                <Center py="xl"><Loader /></Center>
            ) : (
                <StockTable
                    stocks={sortRows(stocks, sort)}
                    sortConfig={sort}
                    onSort={(key) => setSort((prev) => nextSort(prev, key))}
                    // 종목코드 복사만 한다. `/research`처럼 매매 화면으로 보내면
                    // 공개 방문자가 로그인 벽에 부딪히고, 그 경로를 알려 주게 된다.
                    onCellClick={(code) => navigator.clipboard?.writeText(code)}
                    // onQuickOrder 없음 = 주문 경로가 없다(클릭도 커서도 안 붙는다)
                />
            )}

            <Divider my="xl" label="Simulation Analysis" labelPosition="center" />

            {loading && !balances ? (
                <Center py="xl"><Loader /></Center>
            ) : (
                <SimulationSection
                    balances={balances}
                    history={history}
                    onRefresh={load}
                    onShowReason={showReason}
                />
            )}

            <Modal opened={reasonOpen} onClose={() => setReasonOpen(false)} title={reason.title} size="lg">
                <Paper p="md" withBorder bg="gray.0">
                    <Text style={{ whiteSpace: 'pre-wrap' }} size="sm">{reason.content}</Text>
                </Paper>
                <Group justify="flex-end" mt="md"><Button onClick={() => setReasonOpen(false)}>닫기</Button></Group>
            </Modal>

            <Box mt="xl">
                <StrategyRadarChart />
            </Box>
        </Container>
    );
}
