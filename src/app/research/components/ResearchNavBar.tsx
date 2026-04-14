import React, { useMemo } from 'react';
import { NavLink, Title, Stack, Group, Text, Badge, Divider, Anchor } from '@mantine/core';
import { IconFileAnalytics, IconReport, IconExternalLink, IconFileSpreadsheet } from '@tabler/icons-react';

interface ResearchNavBarProps {
    reports: any[];
    repoOwner: string;
    repoName: string;
    lastUpdated?: string;
}

export const ResearchNavBar = ({ reports, repoOwner, repoName, lastUpdated }: ResearchNavBarProps) => {
    // 최신 10개 다운로드 항목 생성 (db-data 브랜치 엑셀 직접 링크)
    const GITHUB_BASE = `https://raw.githubusercontent.com/${repoOwner}/${repoName}/db-data/data`;
    
    const downloadItems = useMemo(() => {
        const items = [];
        const baseDateStr = lastUpdated ? lastUpdated.split(' ')[0].replace(/-/g, '/') : null;
        const now = baseDateStr ? new Date(baseDateStr) : new Date();

        // 1. 최신 파일 (고정)
        const dateStr = `${now.getFullYear()}.${String(now.getMonth() + 1).padStart(2, '0')}.${String(now.getDate()).padStart(2, '0')}`;
        items.push({
            label: `★ 최신 (${dateStr})`,
            url: `/api/download/excel`,
            isLatest: true
        });

        // 2. 월간 누적 파일 (최근 5개월)
        for (let i = 0; i < 5; i++) {
            const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
            const monthKey = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
            const monthLabel = `${d.getFullYear()}년 ${d.getMonth() + 1}월 데이터`;
            
            items.push({
                label: monthLabel,
                url: `/api/download/excel?month=${monthKey}`,
                isLatest: false
            });
        }
        return items;
    }, [lastUpdated]);

    return (
        <Stack gap="xs">
            <Group mb="xs">
                <IconFileAnalytics size={20} color="#228be6" />
                <Title order={4}>리서치 리포트</Title>
            </Group>

            {reports.map((report, idx) => (
                <NavLink
                    key={idx}
                    label={report.title}
                    description={report.date}
                    leftSection={<IconReport size={16} stroke={1.5} />}
                    rightSection={<IconExternalLink size={14} />}
                    component="a"
                    href={`https://github.com/${repoOwner}/${repoName}/blob/db-data/data/reports/${report.filename}`}
                    target="_blank"
                    variant="light"
                    color={report.type === 'monthly' ? 'violet' : 'blue'}
                    styles={{
                        label: { fontWeight: 500 },
                        root: { borderRadius: '8px' }
                    } as any}
                />
            ))}

            {/* [V8.9.9.5] 데이터 다운로드 섹션 */}
            <Divider my="sm" />
            <Stack gap={5}>
                <Text size="xs" c="dimmed" fw={700} px="md">엑셀 데이터</Text>
                {downloadItems.map((item, idx) => (
                    <NavLink
                        key={idx}
                        label={item.label}
                        description=".xlsx 형식"
                        leftSection={<IconFileSpreadsheet size={16} color={item.isLatest ? '#2f9e44' : '#868e96'} />}
                        component="a"
                        href={item.url}
                        download={`stockbot_${new Date().toISOString().slice(0,10)}.xlsx`}
                        variant={item.isLatest ? 'light' : 'subtle'}
                        color="green"
                        styles={{
                            label: { fontWeight: item.isLatest ? 700 : 400 },
                            root: { borderRadius: '8px' }
                        } as any}
                    />
                ))}
                <NavLink
                    label="Raw Data (JSON)"
                    component="a"
                    href={`https://github.com/${repoOwner}/${repoName}/tree/db-data/data`}
                    target="_blank"
                    leftSection={<Badge size="xs" variant="outline">DB</Badge>}
                />
            </Stack>
        </Stack>
    );
};
