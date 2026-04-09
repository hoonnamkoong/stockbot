import React, { useMemo } from 'react';
import { NavLink, Title, Stack, Group, Text, Badge, Divider, Anchor } from '@mantine/core';
import { IconFileAnalytics, IconReport, IconExternalLink, IconFileSpreadsheet } from '@tabler/icons-react';

interface ResearchNavBarProps {
    reports: any[];
    repoOwner: string;
    repoName: string;
}

export const ResearchNavBar = ({ reports, repoOwner, repoName }: ResearchNavBarProps) => {
    // 최신 10개 다운로드 항목 생성 (db-data 브랜치 엑셀 직접 링크)
    const GITHUB_BASE = `https://raw.githubusercontent.com/${repoOwner}/${repoName}/db-data/data`;
    
    const downloadItems = useMemo(() => {
        const items = [];
        const now = new Date();
        for (let i = 0; i < 10; i++) {
            const d = new Date(now);
            d.setDate(d.getDate() - i);
            const dateStr = `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')}`;
            const dateKey = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`;
            // 최신 파일을 별도 저장하는 방식도 가능하지만, 현재는 단일 파일로 통일
            items.push({
                label: i === 0 ? `★ 최신 (${dateStr})` : dateStr,
                url: `${GITHUB_BASE}/trending_integrated.xlsx`,
                isLatest: i === 0
            });
        }
        return items.slice(0, 1); // 현재 단일 파일이므로 최신 1개만 (TODO: 다중 날짜별 구현 시 확장)
    }, [GITHUB_BASE]);

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
                    href={`https://github.com/${repoOwner}/${repoName}/blob/db-data/reports/${report.filename}`}
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
                        href="/api/download/excel"
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
