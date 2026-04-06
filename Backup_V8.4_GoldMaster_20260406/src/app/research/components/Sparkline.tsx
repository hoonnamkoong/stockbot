import React from 'react';

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
