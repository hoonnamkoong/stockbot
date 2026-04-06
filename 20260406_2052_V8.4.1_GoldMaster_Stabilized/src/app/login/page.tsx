'use client';
import { Container, Paper, PasswordInput, Button, Title, Center } from '@mantine/core';
import { signIn } from 'next-auth/react';
import { useState } from 'react';
import { useRouter } from 'next/navigation';

export default function LoginPage() {
    const [password, setPassword] = useState('');
    const router = useRouter();
    const [loading, setLoading] = useState(false);

    const handleLogin = async () => {
        setLoading(true);
        const res = await signIn('credentials', {
            password,
            redirect: false,
        });
        setLoading(false);

        if (res?.ok) {
            router.push('/trade');
        } else {
            alert('Invalid Password');
        }
    };

    return (
        <Container size="xs" mt={100}>
            <Center>
                <Title order={1} mb="xl">Stock Dashboard</Title>
            </Center>
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
