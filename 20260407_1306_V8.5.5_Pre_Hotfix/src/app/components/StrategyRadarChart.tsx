'use client';

import React, { useEffect, useState } from 'react';
import {
  Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer, Tooltip, Legend
} from 'recharts';
import { Card, Text, Group, Loader, Badge } from '@mantine/core';
import { IconDna } from '@tabler/icons-react';

interface SimulationStat {
  raw: Record<string, number>;
  normalized: Record<string, number>;
}

interface StatsData {
  Real: SimulationStat;
  Sim1: SimulationStat;
  Sim2: SimulationStat;
  Sim3: SimulationStat;
}

const CustomTooltip = ({ active, payload }: any) => {
  if (active && payload && payload.length) {
    return (
      <Card shadow="sm" padding="xs" radius="md" withBorder>
        <Text size="xs" fw={700} mb={5}>{payload[0].payload.subject}</Text>
        {payload.map((entry: any, index: number) => (
          <Group key={index} justify="apart" wrap="nowrap" gap="xs">
            <Badge color={entry.color} size="xs" variant="filled" circle />
            <Text size="xs" style={{ minWidth: 60 }}>{entry.name}:</Text>
            <Text size="xs" fw={500} c={entry.color}>
              {/* Raw 데이터 표시 (예: 승률 65%) */}
              {entry.payload.rawValues[entry.dataKey]}
            </Text>
          </Group>
        ))}
      </Card>
    );
  }
  return null;
};

export default function StrategyRadarChart() {
  const [data, setData] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const response = await fetch('/api/simulation/stats');
        const stats: StatsData = await response.json();

        // 5대 지표 (subject 명칭은 BaseSimulator.get_normalized_stats와 일치해야 함)
        const subjects = ['승률', '수익팩터', 'MDD', '거래빈도', '자본회전율'];
        const apiKeys = ['win_rate', 'profit_factor', 'mdd', 'frequency', 'turnover'];

        const chartData = subjects.map((subject, idx) => {
          const apiKey = apiKeys[idx];
          return {
            subject,
            fullMark: 100,
            real: stats.Real?.normalized[subject] || 0,
            sim1: stats.Sim1?.normalized[subject] || 0,
            sim2: stats.Sim2?.normalized[subject] || 0,
            sim3: stats.Sim3?.normalized[subject] || 0,
            rawValues: {
              real: formatRaw(apiKey, stats.Real?.raw[apiKey]),
              sim1: formatRaw(apiKey, stats.Sim1?.raw[apiKey]),
              sim2: formatRaw(apiKey, stats.Sim2?.raw[apiKey]),
              sim3: formatRaw(apiKey, stats.Sim3?.raw[apiKey]),
            }
          };
        });

        setData(chartData);
      } catch (error) {
        console.error('Failed to load simulation stats:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchStats();
  }, []);

  const formatRaw = (key: string, value: number | undefined) => {
    if (value === undefined) return '0';
    if (key === 'win_rate' || key === 'mdd') return `${value.toFixed(1)}%`;
    if (key === 'profit_factor') return value.toFixed(2);
    if (key === 'frequency') return `${value.toFixed(1)}회/일`;
    return `${value.toFixed(1)}배`;
  };

  if (loading) return <Group justify="center" p="xl"><Loader size="sm" /></Group>;

  return (
    <Card shadow="sm" padding="lg" radius="md" withBorder>
      <Group mb="md">
        <IconDna size={24} color="#228be6" />
        <Text fw={700}>전략 DNA 분석 (Radar Chart)</Text>
      </Group>

      <div style={{ width: '100%', height: 350 }}>
        <ResponsiveContainer>
          <RadarChart cx="50%" cy="50%" outerRadius="80%" data={data}>
            <PolarGrid stroke="#e9ecef" />
            <PolarAngleAxis dataKey="subject" tick={{ fontSize: 12, fill: '#495057' }} />
            <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} axisLine={false} />
            
            <Radar
              name="실전 계좌"
              dataKey="real"
              stroke="#228be6" // Blue
              fill="#228be6"
              fillOpacity={0.6}
            />
            <Radar
              name="Sim 1 (균등)"
              dataKey="sim1"
              stroke="#fab005" // Yellow/Amber
              fill="#fab005"
              fillOpacity={0.4}
            />
            <Radar
              name="Sim 2 (AI)"
              dataKey="sim2"
              stroke="#7950f2" // Violet/Indigo
              fill="#7950f2"
              fillOpacity={0.3}
            />
            <Radar
              name="Sim 3 (Frame)"
              dataKey="sim3"
              stroke="#fa5252" // Red/Rose
              fill="#fa5252"
              fillOpacity={0.2}
            />
            
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ paddingTop: 20 }} />
          </RadarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
