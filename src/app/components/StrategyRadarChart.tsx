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
  real: SimulationStat;
  sim1: SimulationStat;
  sim2: SimulationStat;
  sim3: SimulationStat;
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

        // 5대 지표 (BaseSimulator.get_normalized_stats와 일치됨)
        const subjects = ['승률', '수익팩터', 'MDD', '거래빈도', '자본회전율'];
        const apiKeys = ['win_rate', 'profit_factor', 'mdd', 'frequency', 'turnover'];

        const chartData = subjects.map((subject, idx) => {
          const apiKey = apiKeys[idx];
          return {
            subject,
            fullMark: 100,
            real: stats.real?.normalized[subject] || 0,
            sim1: stats.sim1?.normalized[subject] || 0,
            sim2: stats.sim2?.normalized[subject] || 0,
            sim3: stats.sim3?.normalized[subject] || 0,
            rawValues: {
              real: formatRaw(apiKey, stats.real?.raw[apiKey]),
              sim1: formatRaw(apiKey, stats.sim1?.raw[apiKey]),
              sim2: formatRaw(apiKey, stats.sim2?.raw[apiKey]),
              sim3: formatRaw(apiKey, stats.sim3?.raw[apiKey]),
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
      <Group mb="xs">
        <IconDna size={24} color="#228be6" />
        <Text fw={700}>전략 DNA 분석 (Radar Chart)</Text>
      </Group>
      <Text size="xs" c="dimmed" mb="md">
        • <b>승률</b>: 총 매매 중 익절로 마감한 비율 (성공 확률)<br/>
        • <b>수익팩터</b>: 총 수익금을 총 손실금으로 나눈 값 (1 초과 시 손실보다 수익이 큼)<br/>
        • <b>MDD (최대 낙폭)</b>: 포트폴리오 고점 대비 최대 하락률 (숫자가 낮을수록 방어력이 우수)<br/>
        • <b>거래빈도</b>: 평균적인 일일 매매 횟수<br/>
        • <b>자본회전율</b>: 자본 대비 거래량 (숫자가 클수록 자금 활용도가 높음)
      </Text>

      <div style={{ width: '100%', height: 350 }}>
        <ResponsiveContainer>
          <RadarChart cx="50%" cy="50%" outerRadius="80%" data={data}>
            <PolarGrid stroke="#e9ecef" />
            <PolarAngleAxis dataKey="subject" tick={{ fontSize: 12, fill: '#495057' }} />
            <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} axisLine={false} />
            
            <Radar
              name="안정 지향형 (Sim 1)"
              dataKey="sim1"
              stroke="#228be6" // Blue
              fill="none"
              strokeWidth={3}
            />
            <Radar
              name="보수적 방어형 (Sim 2)"
              dataKey="sim2"
              stroke="#7950f2" // Violet
              fill="none"
              strokeWidth={3}
            />
            <Radar
              name="공격적 추세추종형 (Sim 3)"
              dataKey="sim3"
              stroke="#fa5252" // Red
              fill="none"
              strokeWidth={3}
            />
            
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ paddingTop: 20 }} />
          </RadarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
