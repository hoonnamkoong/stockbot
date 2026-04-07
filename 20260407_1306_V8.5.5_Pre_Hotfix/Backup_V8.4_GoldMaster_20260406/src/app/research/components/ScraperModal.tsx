import React from 'react';
import { Modal, PasswordInput, Button, Alert, Group, Text, Stack, ScrollArea, Code, Box } from '@mantine/core';
import { IconInfoCircle, IconPlayerPlay } from '@tabler/icons-react';

interface ScraperModalProps {
    opened: boolean;
    onClose: () => void;
    token: string;
    onTokenChange: (val: string) => void;
    onRun: (force: boolean) => void;
    status: 'idle' | 'running' | 'success' | 'error';
    logs: string[];
}

export const ScraperModal = ({ opened, onClose, token, onTokenChange, onRun, status, logs }: ScraperModalProps) => {
    return (
        <Modal opened={opened} onClose={onClose} title="스크래퍼 수동 제어" size="lg">
            <Stack>
                <Alert icon={<IconInfoCircle size={16} />} title="GitHub Actions 제어" color="blue">
                    GitHub Actions를 통해 네이버 금융 스크래퍼를 직접 실행합니다.
                </Alert>
                
                <PasswordInput
                    label="GitHub Personal Access Token"
                    placeholder="ghp_..."
                    value={token}
                    onChange={(e) => onTokenChange(e.currentTarget.value)}
                    description="권한: repo, workflow 가 필요합니다."
                />

                <Group grow>
                    <Button 
                        leftSection={<IconPlayerPlay size={18} />} 
                        onClick={() => onRun(false)} 
                        loading={status === 'running'}
                        color="blue"
                    >
                        일반 실행
                    </Button>
                    <Button 
                        variant="light" 
                        onClick={() => onRun(true)} 
                        loading={status === 'running'}
                        color="red"
                    >
                        강제 새로고침
                    </Button>
                </Group>

                {logs.length > 0 && (
                    <Box mt="md">
                        <Text size="xs" fw={700} mb={5}>실행 로그:</Text>
                        <ScrollArea h={150} offsetScrollbars styles={{ viewport: { backgroundColor: '#f8f9fa', borderRadius: '4px', border: '1px solid #dee2e6' } }}>
                            <Code block style={{ backgroundColor: 'transparent' }}>
                                {logs.map((log, i) => <div key={i}>{log}</div>)}
                            </Code>
                        </ScrollArea>
                    </Box>
                )}
            </Stack>
        </Modal>
    );
};

// Also defining other small components here to save time if they were simple
export function Sparkline({ data, color }: { data: number[], color: string }) {
    if (!data || data.length < 2) return <div style={{width: 60, height: 20, backgroundColor: '#eee'}} />;
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;
    const width = 60;
    const height = 20;
    const pts = data.map((v, i) => `${(i / (data.length - 1)) * width},${height - ((v - min) / range) * height}`).join(' ');
    
    return (
        <svg width={width} height={height} style={{ display: 'block' }}>
            <polyline fill="none" stroke={color} strokeWidth="1.5" points={pts} strokeLinejoin="round" />
        </svg>
    );
}
