'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function LoginPage() {
    const [password, setPassword] = useState('');
    const [deviceId, setDeviceId] = useState('');
    const [error, setError] = useState('');
    const router = useRouter();

    useEffect(() => {
        try {
            // Generate or retrieve persistent Device ID
            let id = localStorage.getItem('stockbot_device_id');
            if (!id) {
                // Robust UUID generation with fallback
                if (typeof crypto !== 'undefined' && crypto.randomUUID) {
                    id = crypto.randomUUID();
                } else {
                    // Fallback for environments without crypto.randomUUID
                    id = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
                        var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
                        return v.toString(16);
                    });
                }
                localStorage.setItem('stockbot_device_id', id);
            }
            setDeviceId(id);
        } catch (e) {
            console.error("Device ID Generation Error:", e);
            setDeviceId("error-generating-id");
        }
    }, []);

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');

        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password, deviceId }),
            });

            const data = await res.json();

            if (res.ok) {
                router.push('/trade');
            } else {
                setError(data.error || 'Login failed');
            }
        } catch (err) {
            setError('Login failed');
        }
    };

    return (
        <div style={{ padding: '50px', maxWidth: '500px', margin: '0 auto', textAlign: 'center', fontFamily: 'sans-serif' }}>
            <h1>StockBot Secure Access</h1>
            <p style={{ fontSize: '12px', color: '#999' }}>Client v47</p>

            <div style={{ background: '#f5f5f5', padding: '15px', borderRadius: '8px', marginBottom: '20px', border: '1px solid #ddd' }}>
                <p style={{ margin: '0 0 10px 0', fontSize: '14px', color: '#666' }}>Your Device ID</p>
                <code style={{ background: '#fff', padding: '5px 10px', borderRadius: '4px', fontWeight: 'bold', display: 'block', wordBreak: 'break-all', fontSize: '1.2em' }}>
                    {deviceId || 'Generating...'}
                </code>
                <p style={{ fontSize: '12px', color: '#888', marginTop: '10px' }}>
                    * Add this ID to <b>TRUSTED_DEVICES</b> in Vercel Environment Variables.
                </p>
            </div>

            <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
                <input
                    type="password"
                    placeholder="Enter Admin Password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    style={{ padding: '12px', fontSize: '16px', borderRadius: '4px', border: '1px solid #ccc' }}
                />
                <button
                    type="submit"
                    style={{ padding: '12px', background: '#0070f3', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '16px', fontWeight: 'bold' }}
                >
                    Authenticate Device
                </button>
            </form>

            {error && (
                <div style={{ marginTop: '20px', padding: '10px', background: '#fff0f0', color: '#d32f2f', borderRadius: '4px', border: '1px solid #ffcdd2' }}>
                    {error}
                </div>
            )}
        </div>
    );
}
