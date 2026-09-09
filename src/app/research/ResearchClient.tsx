'use client';

import React, { useState } from 'react';
import { AppShell, Burger, Group, Title, Button, Text, ActionIcon, Tabs, Notification, Stack, useMantineTheme } from '@mantine/core';
import { useDisclosure, useMediaQuery } from '@mantine/hooks';
import { IconRefresh, IconRobot, IconSettings, IconCoin } from '@tabler/icons-react';
import { useRouter } from 'next/navigation';
import { signOut, useSession } from 'next-auth/react';

import { useResearchSource } from './hooks/useResearchSource';
import { ResearchNavBar } from './components/ResearchNavBar';
import { StockTable, TrendTable } from './components/ResearchTables';
import { ScraperModal } from './components/ScraperModal';
import QuickOrderModal from '../components/QuickOrderModal';

/**
 * 리서치 보드 — **공개 페이지다.** 표는 누구나 보고, 조작은 세션이 있을 때만 뜬다.
 *
 * 표 데이터(/api/stocks/research)는 db-data(공개 브랜치)가 원본이라 가릴 것이 없다.
 * 세션 뒤에 두는 것들:
 *   - 퀵 주문 / 셀 클릭 → /trade 이동 : 실거래 경로다.
 *   - 스크래퍼 제어 : `runScraper`는 **방문자가 자기 GitHub PAT를 입력**하는
 *     방식이라 남이 실행할 수는 없다(권한 없는 PAT는 GitHub이 거부한다).
 *     보안 문제가 아니라 **인상**의 문제다 — 공개 페이지가 "GitHub Token을
 *     입력해주세요"라고 요구하면 피싱 페이지와 똑같이 생겼다.
 *   - 엑셀/리포트 다운로드 : 공개 데이터지만 "표만" 보여주기로 했다.
 */
export default function ResearchClient() {
    const { status } = useSession();
    const isAdmin = status === 'authenticated';
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
        // 공개 방문자를 로그인 벽으로 보내지 않는다. 복사는 그대로 동작한다.
        if (isAdmin) router.push(`/trade?code=${code}`);
    };

    const handleQuickOrder = (stock: any) => {
        setSelectedQuickStock({ code: stock.code, name: stock.name });
        setQuickOrderOpen(true);
    };

    return (
        <AppShell header={{ height: 60 }} navbar={{ width: 300, breakpoint: 'sm', collapsed: { mobile: !opened } }} padding="md">
            {isAdmin && <QuickOrderModal
                opened={quickOrderOpen} onClose={() => setQuickOrderOpen(false)}
                initialCode={selectedQuickStock.code} initialName={selectedQuickStock.name}
                onOrderDispatched={(odno) => {
                    setNotification({ title: '주문 전송 완료', msg: '한국투자증권 API로 주문이 직접 전송되었습니다.', color: 'teal' });
                    if (odno) setTrackingOrders(prev => [...prev, odno]);
                }}
            />}
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
                    <div>
                        <Title order={3} size={isMobile ? 'h5' : 'h3'} style={{ lineHeight: 1.2 }}>
                            KOSPI / KOSDAQ StockBot
                        </Title>
                        <Text size="xs" c="dimmed">{(versionInfo && typeof versionInfo !== 'string') ? versionInfo.version : 'V50.1'}</Text>
                    </div>
                    <Group ml="auto" gap={isMobile ? 4 : 'xs'}>
                        {isAdmin && <Button
                            variant="light" color="blue" onClick={() => router.push('/trade')}
                            leftSection={<IconCoin size={16} />}
                            px={isMobile ? 8 : 'md'}
                        >
                            {!isMobile && '트레이딩 보드'}
                        </Button>}
                        {isAdmin && <Button
                            variant="light" color="violet" onClick={openControl}
                            leftSection={<IconSettings size={16} />}
                            px={isMobile ? 8 : 'md'}
                        >
                            {!isMobile && '스크래퍼 제어'}
                        </Button>}
                        <Button 
                            variant="default" onClick={() => fetchData()} 
                            leftSection={<IconRefresh size={16} className={loading ? 'animate-spin' : ''} />}
                            px={isMobile ? 8 : 'md'}
                        >
                            {isMobile ? '' : (loading ? '...' : '갱신')}
                        </Button>
                        {isAdmin && !isMobile && <Button variant="subtle" color="gray" onClick={() => signOut({ callbackUrl: '/login' })}>Sign Out</Button>}
                    </Group>
                </Group>
            </AppShell.Header>

            <AppShell.Navbar p="md">
                <ResearchNavBar reports={reports} repoOwner="hoonnamkoong" repoName="stockbot" lastUpdated={lastUpdated} showDownloads={isAdmin} />
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
                        sortConfig={sortConfig} onSort={handleSort} onCellClick={handleCellClick}
                        onQuickOrder={isAdmin ? handleQuickOrder : undefined}
                    />
                )}

                {isAdmin && <ScraperModal
                    opened={controlOpened} onClose={closeControl} token={githubToken}
                    onTokenChange={setGithubToken} onRun={runScraper} status={workflowStatus} logs={workflowLogs}
                />}
            </AppShell.Main>
        </AppShell>
    );
}
