'use client';

import React, { useEffect, useState } from 'react';
import {
  Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer, Tooltip, Legend
} from 'recharts';
import { Card, Text, Group, Loader, Badge, Stack, Table } from '@mantine/core';
import { IconDna, IconTrendingUp } from '@tabler/icons-react';

interface SimulationStat {
  raw: Record<string, number>;
  normalized: Record<string, number>;
}

interface LiberoInfo {
  current_regime: string | null;
  bull_score: number | null;
  regime_confidence: number | null;
  recommended_sims: string[];
  metrics: Record<string, number>;
  last_run: string | null;
}

// 차트에 그릴 시뮬레이터 정의 (단일 소스). 색상/라벨/설명을 여기서 관리.
const SERIES = [
  { key: 'sim1', label: '심리 괴리형 (Sim 1)', color: '#228be6', desc: 'Buzz 급증·가격 정체 종목 매집' },
  { key: 'sim2', label: '수급 동승형 (Sim 2)', color: '#7950f2', desc: '외인 수급 + 감정 발산 스코어' },
  { key: 'sim3', label: '스마트 리스크형 (Sim 3)', color: '#fa5252', desc: '추세 돌파 / 횡보 반등 + 트레일링' },
  { key: 'sim4', label: '상승 모멘텀형 (Sim 4)', color: '#2f9e44', desc: '주도주 탑승·불타기, 고정익절 없이 라이딩' },
  { key: 'sim5', label: '추세 눌림목형 (Sim 5)', color: '#f08c00', desc: '상승추세 속 MA5 이하 눌림 저가매수 + 빠른 익절' },
  { key: 'sim6', label: '하락 줍줍형 (Sim 6)', color: '#0c8599', desc: '폭락 후 데드캣 반등 2.5% 빠른 익절' },
];

// Sim7 리베로 recommended_sims의 manifest id → 라벨
const ID_LABEL: Record<string, string> = {
  sim_psych: '심리 괴리형(S1)',
  sim_spillover: '수급 동승형(S2)',
  sim_risk: '스마트 리스크형(S3)',
  sim4_bull: '상승 모멘텀형(S4)',
  sim5_sideways: '횡보 스윙형(S5)',
  sim6_bear: '하락 줍줍형(S6)',
};

const REGIME_STYLE: Record<string, { color: string; label: string }> = {
  BULL: { color: '#2f9e44', label: '상승장 (BULL)' },
  SIDEWAYS: { color: '#f08c00', label: '횡보장 (SIDEWAYS)' },
  BEAR: { color: '#fa5252', label: '하락장 (BEAR)' },
};

// 5대 지표 축 정의 (BaseSimulator.get_normalized_stats와 일치)
const METRICS = [
  { subject: '승률', apiKey: 'win_rate', desc: '총 매매 중 익절로 마감한 비율 (성공 확률)' },
  { subject: '수익팩터', apiKey: 'profit_factor', desc: '총수익 ÷ 총손실. 1 초과면 손실보다 수익이 큼' },
  { subject: 'MDD', apiKey: 'mdd', desc: '고점 대비 최대 낙폭. 차트 바깥쪽일수록 방어 우수(낙폭 작음)' },
  { subject: '거래빈도', apiKey: 'frequency', desc: '일 평균 매매 횟수 (회전 속도)' },
  { subject: '자본회전율', apiKey: 'turnover', desc: '초기자본 대비 누적 거래대금 (자금 활용도)' },
];

const CustomTooltip = ({ active, payload }: any) => {
  if (active && payload && payload.length) {
    return (
      <Card shadow="sm" padding="xs" radius="md" withBorder>
        <Text size="xs" fw={700} mb={5}>{payload[0].payload.subject}</Text>
        {payload.map((entry: any, index: number) => (
          <Group key={index} justify="apart" wrap="nowrap" gap="xs">
            <Badge color={entry.color} size="xs" variant="filled" circle />
            <Text size="xs" style={{ minWidth: 120 }}>{entry.name}:</Text>
            <Text size="xs" fw={500} c={entry.color}>
              {entry.payload.rawValues[entry.dataKey]}
            </Text>
          </Group>
        ))}
      </Card>
    );
  }
  return null;
};

const formatRaw = (key: string, value: number | undefined) => {
  if (value === undefined) return '0';
  if (key === 'win_rate' || key === 'mdd') return `${value.toFixed(1)}%`;
  if (key === 'profit_factor') return value.toFixed(2);
  if (key === 'frequency') return `${value.toFixed(1)}회/일`;
  return `${value.toFixed(1)}배`;
};

const pct = (v: number | undefined) => {
  if (v === undefined || v === null || isNaN(v)) return '0.00%';
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
};

export default function StrategyRadarChart() {
  const [data, setData] = useState<any[]>([]);
  const [ranking, setRanking] = useState<any[]>([]);
  const [libero, setLibero] = useState<LiberoInfo | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const response = await fetch('/api/simulation/stats');
        const stats = await response.json() as Record<string, any>;

        // 레이더용 5축 데이터
        const chartData = METRICS.map(({ subject, apiKey }) => {
          const row: any = { subject, fullMark: 100, rawValues: {} };
          for (const s of SERIES) {
            row[s.key] = stats[s.key]?.normalized?.[subject] || 0;
            row.rawValues[s.key] = formatRaw(apiKey, stats[s.key]?.raw?.[apiKey]);
          }
          return row;
        });
        setData(chartData);

        // 수익률 순위표 (단기 최대 성과 핵심 지표)
        const rank = SERIES.map((s) => {
          const raw = stats[s.key]?.raw || {};
          return {
            ...s,
            profit_rate: raw.profit_rate ?? 0,
            win_rate: raw.win_rate ?? 0,
            profit_factor: raw.profit_factor ?? 0,
            mdd: raw.mdd ?? 0,
          };
        }).sort((a, b) => b.profit_rate - a.profit_rate);
        setRanking(rank);

        setLibero(stats.libero ?? null);
      } catch (error) {
        console.error('Failed to load simulation stats:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchStats();
  }, []);

  const toggleSeries = (key: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  if (loading) return <Group justify="center" p="xl"><Loader size="sm" /></Group>;

  const regime = libero?.current_regime ?? null;
  const regimeStyle = regime ? REGIME_STYLE[regime] : null;

  return (
    <Card shadow="sm" padding="lg" radius="md" withBorder>
      <Group mb="xs">
        <IconDna size={24} color="#228be6" />
        <Text fw={700}>전략 DNA 분석 (Radar Chart)</Text>
        <Text size="xs" c="dimmed">· 동일 초기자본 300만원 기준</Text>
      </Group>

      {/* ① 리베로 시장 국면 배너 */}
      <Card withBorder radius="md" padding="sm" mb="md"
        style={{ background: regimeStyle ? `${regimeStyle.color}10` : '#f8f9fa' }}>
        <Group justify="space-between" wrap="wrap" gap="xs">
          <Group gap="xs">
            <Text size="sm" fw={700}>🧭 리베로 시장 국면</Text>
            {regimeStyle ? (
              <Badge color={regimeStyle.color} variant="filled" size="lg">{regimeStyle.label}</Badge>
            ) : (
              <Badge color="gray" variant="light" size="lg">분석 대기</Badge>
            )}
            {libero?.bull_score != null && (
              <Text size="sm">방향성 점수 <b>{libero.bull_score.toFixed(1)}</b>/100</Text>
            )}
            {libero?.regime_confidence != null && (
              <Text size="xs" c="dimmed">신뢰도 {(libero.regime_confidence * 100).toFixed(0)}%</Text>
            )}
          </Group>
          {libero?.recommended_sims && libero.recommended_sims.length > 0 && (
            <Group gap={4}>
              <Text size="xs" c="dimmed">추천 전략:</Text>
              {libero.recommended_sims.map((id) => (
                <Badge key={id} variant="outline" size="sm" color="dark">{ID_LABEL[id] ?? id}</Badge>
              ))}
            </Group>
          )}
        </Group>
      </Card>

      {/* ② 수익률 순위표 */}
      <Group gap={6} mb={4}>
        <IconTrendingUp size={18} color="#2f9e44" />
        <Text size="sm" fw={700}>누적 수익률 순위 (단기 성과)</Text>
      </Group>
      <Table withTableBorder withColumnBorders highlightOnHover mb="md" fz="xs" verticalSpacing={4}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>#</Table.Th>
            <Table.Th>전략</Table.Th>
            <Table.Th ta="right">수익률</Table.Th>
            <Table.Th ta="right">승률</Table.Th>
            <Table.Th ta="right">수익팩터</Table.Th>
            <Table.Th ta="right">MDD</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {ranking.map((r, i) => (
            <Table.Tr key={r.key}>
              <Table.Td fw={700}>{i + 1}</Table.Td>
              <Table.Td>
                <Group gap={6} wrap="nowrap">
                  <span style={{ width: 9, height: 9, borderRadius: '50%', background: r.color, flexShrink: 0 }} />
                  <Text size="xs">{r.label}</Text>
                </Group>
              </Table.Td>
              <Table.Td ta="right" fw={700} c={r.profit_rate >= 0 ? 'teal' : 'red'}>{pct(r.profit_rate)}</Table.Td>
              <Table.Td ta="right">{r.win_rate.toFixed(1)}%</Table.Td>
              <Table.Td ta="right">{r.profit_factor.toFixed(2)}</Table.Td>
              <Table.Td ta="right" c="dimmed">{r.mdd.toFixed(1)}%</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>

      {/* ③ 레이더(범례 클릭 토글) + 옆 주석 패널 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'stretch' }}>
        <div style={{ flex: '1 1 420px', minWidth: 320, height: 380 }}>
          <ResponsiveContainer>
            <RadarChart cx="50%" cy="50%" outerRadius="78%" data={data}>
              <PolarGrid stroke="#e9ecef" />
              <PolarAngleAxis dataKey="subject" tick={{ fontSize: 12, fill: '#495057' }} />
              <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} axisLine={false} />
              {SERIES.map((s) => (
                <Radar
                  key={s.key}
                  name={s.label}
                  dataKey={s.key}
                  stroke={s.color}
                  fill={s.color}
                  fillOpacity={0.06}
                  strokeWidth={2}
                  hide={hidden.has(s.key)}
                />
              ))}
              <Tooltip content={<CustomTooltip />} />
              <Legend
                wrapperStyle={{ paddingTop: 12, fontSize: 11, cursor: 'pointer' }}
                onClick={(e: any) => toggleSeries(e.dataKey as string)}
              />
            </RadarChart>
          </ResponsiveContainer>
          <Text size="xs" c="dimmed" ta="center">※ 범례를 클릭하면 해당 전략 선을 켜고 끌 수 있습니다.</Text>
        </div>

        <Stack gap="md" style={{ flex: '1 1 280px', minWidth: 260 }}>
          <div>
            <Text size="xs" fw={700} mb={4} c="dark">📊 축(지표)의 의미 — 바깥쪽일수록 우수</Text>
            <Stack gap={3}>
              {METRICS.map((m) => (
                <Text key={m.subject} size="xs" c="dimmed">
                  • <b>{m.subject}</b>: {m.desc}
                </Text>
              ))}
            </Stack>
          </div>

          <div>
            <Text size="xs" fw={700} mb={4} c="dark">🧬 전략(선) 색상</Text>
            <Stack gap={3}>
              {SERIES.map((s) => (
                <Group key={s.key} gap={6} wrap="nowrap" align="flex-start">
                  <span style={{
                    display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
                    background: s.color, marginTop: 4, flexShrink: 0,
                  }} />
                  <Text size="xs" c="dimmed">
                    <b style={{ color: s.color }}>{s.label}</b> — {s.desc}
                  </Text>
                </Group>
              ))}
            </Stack>
          </div>
        </Stack>
      </div>
    </Card>
  );
}
