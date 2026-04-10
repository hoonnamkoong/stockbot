'use client';

import React, { useState } from 'react';
import { AppShell, Burger, Group, Title, Button, Text, ActionIcon, Tabs, Notification, Stack, useMantineTheme } from '@mantine/core';
import { useDisclosure, useMediaQuery } from '@mantine/hooks';
import { IconRefresh, IconRobot, IconSettings, IconCoin } from '@tabler/icons-react';
import { useRouter } from 'next/navigation';
import { signOut } from 'next-auth/react';

import { useResearchSource } from './hooks/useResearchSource';
import { ResearchNavBar } from './components/ResearchNavBar';
import { StockTable, TrendTable } from './components/ResearchTables';
import { ScraperModal } from './components/ScraperModal';
import QuickOrderModal from '../components/QuickOrderModal';

export default function ResearchClient() {
    const router = useRouter();
    const theme = useMantineTheme();
    const isMobile = useMediaQuery(`(max-width: ${theme.breakpoints.sm})`);
    const [opened, { toggle }] = useDisclosure();
    const [controlOpened, { open: openControl, close: closeControl }] = useDisclosure(false);
    const [activeTab, setActiveTab] = useState<string | null>('ALL');
    const [quickOrderOpen, setQuickOrderOpen] = useState(false);
    const [selectedQuickStock, setSelectedQuickStock] = useState({ code: '', name: '' });

    const {
        stocks, fiveDayData, threeDayData, loading, lastUpdated, versionInfo,
        reports, githubToken, setGithubToken, workflowStatus, workflowLogs,
        sortConfig, handleSort, runScraper, fetchData, notification, setNotification, setTrackingOrders
    } = useResearchSource();

    const handleCellClick = (code: string) => {
        navigator.clipboard.writeText(code);
        router.push(`/trade?code=${code}`);
    };

    const handleQuickOrder = (stock: any) => {
        setSelectedQuickStock({ code: stock.code, name: stock.name });
        setQuickOrderOpen(true);
    };

    return (
        <AppShell header={{ height: 60 }} navbar={{ width: 300, breakpoint: 'sm', collapsed: { mobile: !opened } }} padding="md">
            <QuickOrderModal
                opened={quickOrderOpen} onClose={() => setQuickOrderOpen(false)}
                initialCode={selectedQuickStock.code} initialName={selectedQuickStock.name}
                onOrderDispatched={(odno) => {
                    setNotification({ title: '주문 전송 완료', msg: '한국투자증권 API로 주문이 직접 전송되었습니다.', color: 'teal' });
                    if (odno) setTrackingOrders(prev => [...prev, odno]);
                }}
            />
            {notification && (
                <Notification
                    title={notification.title} color={notification.color} onClose={() => setNotification(null)}
                    style={{ position: 'fixed', top: 20, right: 20, zIndex: 9999 }}
                >
                    {notification.msg}
                </Notification>
            )}

            <AppShell.Header>
                <Group h="100%" px="md">
                    <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
                    <IconRobot size={isMobile ? 24 : 30} style={{ color: '#228be6' }} />
                    <Title order={3} size={isMobile ? 'h5' : 'h3'}>
                        StockBot {(versionInfo && typeof versionInfo !== 'string') ? versionInfo.version : 'v10.6-stable'}
                    </Title>
                    <Group ml="auto" gap={isMobile ? 4 : 'xs'}>
                        <Button
                            variant="light" color="blue" onClick={() => router.push('/trade')}
                            leftSection={<IconCoin size={16} />}
                            px={isMobile ? 8 : 'md'}
                        >
                            {!isMobile && '트레이딩 보드'}
                        </Button>
                        <Button 
                            variant="light" color="violet" onClick={openControl} 
                            leftSection={<IconSettings size={16} />}
                            px={isMobile ? 8 : 'md'}
                        >
                            {!isMobile && '스크래퍼 제어'}
                        </Button>
                        <Button 
                            variant="default" onClick={() => fetchData()} 
                            leftSection={<IconRefresh size={16} className={loading ? 'animate-spin' : ''} />}
                            px={isMobile ? 8 : 'md'}
                        >
                            {isMobile ? '' : (loading ? '...' : '갱신')}
                        </Button>
                        {!isMobile && <Button variant="subtle" color="gray" onClick={() => signOut({ callbackUrl: '/login' })}>Sign Out</Button>}
                    </Group>
                </Group>
            </AppShell.Header>

            <AppShell.Navbar p="md">
                <ResearchNavBar reports={reports} repoOwner="hoonnamkoong" repoName="stockbot" lastUpdated={lastUpdated} />
            </AppShell.Navbar>

            <AppShell.Main>
                <Stack gap="xs" mb="md">
                    <Group justify="space-between" align="center">
                        <Tabs value={activeTab} onChange={setActiveTab} style={{ flex: 1 }}>
                            <Tabs.List grow={isMobile}>
                                <Tabs.Tab value="ALL">전체</Tabs.Tab>
                                <Tabs.Tab value="KOSPI">KOSPI</Tabs.Tab>
                                <Tabs.Tab value="KOSDAQ">KOSDAQ</Tabs.Tab>
                                <Tabs.Tab value="5DAYS">📅 5일</Tabs.Tab>
                                <Tabs.Tab value="3DAYS">📅 3일</Tabs.Tab>
                            </Tabs.List>
                        </Tabs>
                    </Group>
                    <Text size="xs" c="dimmed" ta={isMobile ? 'left' : 'right'}>🕒 Update: {lastUpdated}</Text>
                </Stack>

                {activeTab === '5DAYS' ? (
                    <TrendTable data={fiveDayData} sortConfig={sortConfig} onSort={handleSort} onCellClick={handleCellClick} title="5일 누적 분석" titleColor="blue" />
                ) : activeTab === '3DAYS' ? (
                    <TrendTable data={threeDayData} sortConfig={sortConfig} onSort={handleSort} onCellClick={handleCellClick} title="3일 누적 분석" titleColor="cyan" />
                ) : (
                    <StockTable
                        stocks={stocks.filter(s => activeTab === 'ALL' ? true : s.market === activeTab)}
                        sortConfig={sortConfig} onSort={handleSort} onCellClick={handleCellClick} onQuickOrder={handleQuickOrder}
                    />
                )}

                <ScraperModal
                    opened={controlOpened} onClose={closeControl} token={githubToken}
                    onTokenChange={setGithubToken} onRun={runScraper} status={workflowStatus} logs={workflowLogs}
                />
            </AppShell.Main>
        </AppShell>
    );
}
