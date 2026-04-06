import React from 'react';
import { NavLink, Title, Stack, Group, Text, Badge } from '@mantine/core';
import { IconFileAnalytics, IconReport, IconExternalLink } from '@tabler/icons-react';

interface ResearchNavBarProps {
    reports: any[];
    repoOwner: string;
    repoName: string;
}

export const ResearchNavBar = ({ reports, repoOwner, repoName }: ResearchNavBarProps) => {
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

            <Stack gap={5} mt="xl">
                <Text size="xs" c="dimmed" fw={700} px="md">Data Resources</Text>
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
