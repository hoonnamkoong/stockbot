'use client';
import { Container, Paper, PasswordInput, Button, Title, Center, Text, Code, Box } from '@mantine/core';
import { signIn } from 'next-auth/react';
import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function LoginPage() {
    const [password, setPassword] = useState('');
    const [deviceId, setDeviceId] = useState('');
    const router = useRouter();
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        let id = localStorage.getItem('stockbot_device_id');
        if (!id) {
            id = crypto.randomUUID();
            localStorage.setItem('stockbot_device_id', id);
        }
        setDeviceId(id);
    }, []);

    const handleLogin = async () => {
        setLoading(true);
        const res = await signIn('credentials', {
            password,
            deviceId,
            redirect: false,
        });
        setLoading(false);

        if (res?.ok) {
            router.push('/trade');
        } else {
            alert(res?.error || 'Invalid Password or Device not trusted');
        }
    };

    return (
        <Container size="xs" mt={100}>
            <Center>
                <Title order={1} mb="xl">Stock Dashboard</Title>
            </Center>

            <Box bg="gray.1" p="md" style={{ borderRadius: 8, marginBottom: 20, border: '1px solid #ddd' }}>
                <Text size="sm" c="dimmed" mb={5}>Your Device ID</Text>
                <Code block>{deviceId || 'Generating...'}</Code>
                <Text size="xs" c="dimmed" mt={10}>
                    * 이 브라우저에서 접근하려면 이 ID가 Vercel <b>TRUSTED_DEVICES</b>에 등록되어 있어야 합니다.
                </Text>
            </Box>

            <Paper p="xl" withBorder radius="md">
                <Title order={3} mb="md" ta="center">Admin Login</Title>
                <PasswordInput
                    label="Password"
                    placeholder="Enter Admin Password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
                    mb="lg"
                />
                <Button fullWidth onClick={handleLogin} loading={loading}>
                    Login
                </Button>
            </Paper>
        </Container>
    );
}
