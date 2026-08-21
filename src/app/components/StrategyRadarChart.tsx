'use client';

import React, { useEffect, useState } from 'react';
import {
  Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer, Tooltip, Legend,
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  ReferenceLine, ReferenceArea,
} from 'recharts';
import { Card, Text, Group, Loader, Badge, Stack, Table, Divider } from '@mantine/core';
import { IconDna, IconTrendingUp, IconActivity } from '@tabler/icons-react';
import {
  SIM_REGISTRY, chartHex, isPaper, simsInChartGroup, type SimRegistryEntry,
} from '@/lib/sim-registry.generated';

interface LiberoInfo {
  current_regime: string | null;
  bull_score: number | null;
  regime_confidence: number | null;
  recommended_sims: string[];
  metrics: Record<string, number>;
  last_run: string | null;
  regime_history: string[];
  daily_regime_log: { date: string; regime: string; bull_score: number; breadth?: number }[];
}

// 전략 시리즈는 매니페스트에서 파생한다(src/lib/sim-registry.generated.ts).
// paper: tradeable=false인 관찰 단계 전략. 순위표에서 실전 전략과 구분해 표시한다.
type Series = { key: string; label: string; color: string; desc: string; paper?: boolean };

const toSeries = (s: SimRegistryEntry): Series => ({
  key: s.uiKey,
  label: s.label,
  color: chartHex(s),
  desc: s.shortDesc,
  paper: isPaper(s) || undefined,
});

const SERIES: Series[] = SIM_REGISTRY.map(toSeries);

const SERIES_G1 = simsInChartGroup(1).map(toSeries);
const SERIES_G2 = simsInChartGroup(2).map(toSeries);
const SERIES_G3 = simsInChartGroup(3).map(toSeries);
const SERIES_G4 = simsInChartGroup(4).map(toSeries);
const SERIES_G5 = simsInChartGroup(5).map(toSeries);

// 나우캐스트 시간축: 장 시간대 고정 슬롯 (sim0_libero의 _hour_label과 동일한 'HH:00' 포맷)
const HOUR_SLOTS = ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00'];

// 매니페스트 id → 라벨. 리베로의 recommended_sims가 매니페스트 id로 오는데,
// 이 표를 손으로 적으면 리베로가 추천 대상을 넓힐 때 날 id가 그대로 화면에 뜬다.
const ID_LABEL: Record<string, string> = Object.fromEntries(
  SIM_REGISTRY.map((s) => [s.id, s.label]),
);

const REGIME_STYLE: Record<string, { color: string; label: string }> = {
  BULL:     { color: '#2f9e44', label: '상승장 (BULL)' },
  SIDEWAYS: { color: '#f08c00', label: '횡보장 (SIDEWAYS)' },
  BEAR:     { color: '#fa5252', label: '하락장 (BEAR)' },
};

const METRICS = [
  { subject: '승률',    apiKey: 'win_rate',      desc: '총 매매 중 익절로 마감한 비율 (성공 확률)' },
  { subject: '수익팩터', apiKey: 'profit_factor', desc: '총수익 ÷ 총손실. 1 초과면 손실보다 수익이 큼' },
  { subject: 'MDD',    apiKey: 'mdd',            desc: '고점 대비 최대 낙폭. 바깥쪽일수록 방어 우수' },
  { subject: '거래빈도', apiKey: 'frequency',     desc: '일 평균 매매 횟수 (회전 속도)' },
  { subject: '자본회전율', apiKey: 'turnover',    desc: '초기자본 대비 누적 거래대금 (자금 활용도)' },
];

const CustomTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <Card shadow="sm" padding="xs" radius="md" withBorder>
      <Text size="xs" fw={700} mb={5}>{payload[0].payload.subject}</Text>
      {payload.map((entry: any, i: number) => (
        <Group key={i} justify="apart" wrap="nowrap" gap="xs">
          <Badge color={entry.color} size="xs" variant="filled" circle />
          <Text size="xs" style={{ minWidth: 130 }}>{entry.name}:</Text>
          <Text size="xs" fw={500} c={entry.color}>
            {entry.payload.rawValues?.[entry.dataKey] ?? entry.value}
          </Text>
        </Group>
      ))}
    </Card>
  );
};

const Sim7Tooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <Card shadow="sm" padding="xs" radius="md" withBorder>
      <Text size="xs" fw={700} mb={4}>{label}</Text>
      {payload.map((p: any, i: number) => (
        <Text key={i} size="xs" c={p.color}>
          {p.name}: <b>{p.value}</b>
        </Text>
      ))}
    </Card>
  );
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

function RadarPanel({
  title,
  series,
  data,
  hidden,
  onToggle,
}: {
  title: string;
  series: typeof SERIES;
  data: any[];
  hidden: Set<string>;
  onToggle: (key: string) => void;
}) {
  return (
    <div style={{ flex: '1 1 420px', minWidth: 300 }}>
      <Text size="sm" fw={700} mb={6} ta="center">{title}</Text>
      <div style={{ height: 340 }}>
        <ResponsiveContainer>
          <RadarChart cx="50%" cy="50%" outerRadius="78%" data={data}>
            <PolarGrid stroke="#e9ecef" />
            <PolarAngleAxis dataKey="subject" tick={{ fontSize: 11, fill: '#495057' }} />
            <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} axisLine={false} />
            {series.map((s) => (
              <Radar
                key={s.key}
                name={s.label}
                dataKey={s.key}
                stroke={s.color}
                fill={s.color}
                fillOpacity={0.07}
                strokeWidth={2}
                hide={hidden.has(s.key)}
              />
            ))}
            <Tooltip content={<CustomTooltip />} />
            <Legend
              wrapperStyle={{ paddingTop: 10, fontSize: 10, cursor: 'pointer' }}
              onClick={(e: any) => onToggle(e.dataKey as string)}
            />
          </RadarChart>
        </ResponsiveContainer>
      </div>
      <Text size="xs" c="dimmed" ta="center" mt={4}>※ 범례 클릭 시 해당 전략 선 토글</Text>
    </div>
  );
}

export default function StrategyRadarChart() {
  const [data, setData] = useState<any[]>([]);
  const [ranking, setRanking] = useState<any[]>([]);
  const [libero, setLibero] = useState<LiberoInfo | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [sim7Data, setSim7Data] = useState<any[]>([]);
  const [sim7Loading, setSim7Loading] = useState(true);
  const [sim7HitRate, setSim7HitRate] = useState<{ hits: number; total: number; pct: number } | null>(null);
  const [intradayData, setIntradayData] = useState<any[]>([]);
  const [intradayDate, setIntradayDate] = useState<string | null>(null);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await fetch('/api/simulation/stats');
        const stats = await res.json() as Record<string, any>;

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

        // 수익률 순위표
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
      } catch (e) {
        console.error('Failed to load simulation stats:', e);
      } finally {
        setLoading(false);
      }
    };

    const fetchSim7 = async () => {
      setSim7Loading(true);
      try {
        const res = await fetch(`/api/simulation/libero-history?cb=${Date.now()}`);
        const d = await res.json();

        // [v2] 나우캐스트 재설계 이후 calibration_log = "그날 첫 EOD 예측 vs 마감 확정 실측".
        // v2 항목이 있으면 그것만 사용 (이전 항목은 actual이 낡은 CSV 고정값이라 무효).
        const calV2 = (d.calibration_log ?? []).filter((e: any) => e.v === 2);
        let merged: any[];
        if (calV2.length > 0) {
          // X축은 예측이 있는 날이 아니라 실제 거래일(market_data)을 기준으로 깐다.
          const marketMap: Record<string, number> = {};
          for (const m of (d.market_data ?? [])) marketMap[m.date] = m.breadth;

          const calMap: Record<string, any> = {};
          for (const e of calV2) calMap[e.date] = e;

          const allDates = Array.from(new Set([
            ...Object.keys(marketMap),
            ...Object.keys(calMap),
          ])).sort().slice(-14);

          merged = allDates.map((date) => {
            const c = calMap[date];
            return {
              date: date.slice(5),
              sim7Score: c?.libero_breadth ?? null,
              marketBreadth: c?.actual_kospi_breadth ?? marketMap[date] ?? null,
              gap: c?.gap ?? null,
            };
          });
        } else {
          // 레거시 폴백: daily_regime_log(추정) vs CSV breadth
          const marketMap: Record<string, number> = {};
          for (const m of (d.market_data ?? [])) marketMap[m.date] = m.breadth;

          const liberoMap: Record<string, number> = {};
          for (const l of (d.libero_log ?? [])) {
            const val = l.breadth ?? l.bull_score;
            if (val != null) liberoMap[l.date] = val;
          }

          const allDates = Array.from(new Set([
            ...Object.keys(marketMap),
            ...Object.keys(liberoMap),
          ])).sort().slice(-14);

          merged = allDates.map(date => ({
            date: date.slice(5),
            sim7Score: liberoMap[date] ?? null,
            marketBreadth: marketMap[date] ?? null,
            gap: (liberoMap[date] != null && marketMap[date] != null)
              ? parseFloat((liberoMap[date] - marketMap[date]).toFixed(1))
              : null,
          }));
        }
        setSim7Data(merged);

        // 당일 시간 단위 나우캐스트 (실측 / +1h 예측 / EOD 예측)
        const intr = d.intraday;
        if (intr?.measurements?.length || intr?.predictions?.length) {
          const meas: Record<string, number> = {};
          for (const m of (intr.measurements ?? [])) meas[m.t] = m.breadth;
          const predH1: Record<string, number> = {};
          const predEOD: Record<string, number> = {};
          for (const p of (intr.predictions ?? [])) {
            if (p.type === 'h1') predH1[p.target] = p.value;
            else if (p.type === 'eod') predEOD[p.made_at] = p.value;
          }
          // 장 시간대(09~15시)를 항상 축에 깐다. 16:00 실측 등 슬롯 밖 기록도 잃지 않도록 합집합.
          const ts = Array.from(new Set([
            ...HOUR_SLOTS,
            ...Object.keys(meas), ...Object.keys(predH1), ...Object.keys(predEOD),
          ])).sort();
          setIntradayData(ts.map(t => ({
            t,
            actual: meas[t] ?? null,
            predH1: predH1[t] ?? null,
            predEOD: predEOD[t] ?? null,
          })));
          setIntradayDate(intr.date ?? null);
        }

        // 방향 적중률: 60이상=BULL, 40이하=BEAR, 사이=SIDEWAYS
        const zone = (v: number) => v >= 60 ? 'BULL' : v <= 40 ? 'BEAR' : 'SIDEWAYS';
        const comparable = merged.filter(r => r.sim7Score !== null && r.marketBreadth !== null);
        const hits = comparable.filter(r => zone(r.sim7Score!) === zone(r.marketBreadth!));
        if (comparable.length > 0) {
          setSim7HitRate({ hits: hits.length, total: comparable.length, pct: Math.round(hits.length / comparable.length * 100) });
        }
      } catch {
        setSim7Data([]);
      } finally {
        setSim7Loading(false);
      }
    };

    fetchStats();
    fetchSim7();
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

      {/* ② 수익률 순위표 (Sim4-1 포함) */}
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
                  {r.paper && <Badge size="xs" variant="light" color="gray">관찰</Badge>}
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

      {/* ③ 레이더 차트 — 3그룹 분리 */}
      <Divider mb="md" label="Radar Chart (전략 프로파일)" labelPosition="center" />
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24, alignItems: 'flex-start' }}>
        <RadarPanel
          title="Sim 1~3 (심리·수급·리스크)"
          series={SERIES_G1}
          data={data}
          hidden={hidden}
          onToggle={toggleSeries}
        />
        <RadarPanel
          title="Sim 4~5 (모멘텀·단타·눌림목)"
          series={SERIES_G2}
          data={data}
          hidden={hidden}
          onToggle={toggleSeries}
        />
        <RadarPanel
          title="Sim 6~8 (줍줍·리포트·선행매집)"
          series={SERIES_G3}
          data={data}
          hidden={hidden}
          onToggle={toggleSeries}
        />
        <RadarPanel
          title="Sim 9~10 (갭소진·돈치안·오케스트레이터)"
          series={SERIES_G4}
          data={data}
          hidden={hidden}
          onToggle={toggleSeries}
        />
        <RadarPanel
          title="Sim 11~13 (신규 페이퍼 관찰)"
          series={SERIES_G5}
          data={data}
          hidden={hidden}
          onToggle={toggleSeries}
        />

        {/* 우측 범례 설명 */}
        <Stack gap="md" style={{ flex: '0 1 260px', minWidth: 220 }}>
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
                    <b style={{ color: s.color }}>{s.label}</b>
                    {s.paper && <span style={{ color: '#868e96' }}> (관찰)</span>} — {s.desc}
                  </Text>
                </Group>
              ))}
            </Stack>
          </div>
        </Stack>
      </div>

      {/* ④-0 Sim0 리베로 — 오늘 시간 단위 나우캐스트 */}
      <Divider mt="xl" mb="md" label={`Sim0 리베로 — 오늘 시간 단위 나우캐스트${intradayDate ? ` (${intradayDate})` : ''}`} labelPosition="center" />
      <Text size="xs" c="dimmed" mb={8}>
        · <b style={{ color: '#868e96' }}>회색 실선</b>: 실측 Breadth (top100 라이브) &nbsp;
        · <b style={{ color: '#7950f2' }}>보라선</b>: +1h 예측 (1시간 전 시점) &nbsp;
        · <b style={{ color: '#f08c00' }}>주황 점선</b>: EOD 예측 (그 시각 기준) &nbsp;
        · 매시 스크래퍼 런마다 실측 1건 + 예측 2건 기록, 다음 런에서 채점
      </Text>
      {intradayData.length === 0 ? (
        <Text size="xs" c="dimmed" ta="center" p="lg">오늘 나우캐스트 데이터가 아직 없습니다. 장중 스크래퍼가 돌면 채워집니다.</Text>
      ) : (
        <div style={{ height: 220 }}>
          <ResponsiveContainer>
            <LineChart data={intradayData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
              <ReferenceArea y1={60} y2={100} fill="#2f9e44" fillOpacity={0.07} />
              <ReferenceArea y1={40} y2={60} fill="#f08c00" fillOpacity={0.07} />
              <ReferenceArea y1={0} y2={40} fill="#fa5252" fillOpacity={0.07} />
              <CartesianGrid stroke="#e9ecef" strokeDasharray="3 3" />
              <XAxis dataKey="t" tick={{ fontSize: 10 }} interval={0} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} tickCount={6} width={30} />
              <Tooltip content={<Sim7Tooltip />} />
              <ReferenceLine y={60} stroke="#2f9e44" strokeDasharray="4 2" strokeWidth={1} label={{ value: 'BULL', position: 'insideTopRight', fontSize: 9, fill: '#2f9e44' }} />
              <ReferenceLine y={40} stroke="#fa5252" strokeDasharray="4 2" strokeWidth={1} label={{ value: 'BEAR', position: 'insideBottomRight', fontSize: 9, fill: '#fa5252' }} />
              <Line type="monotone" dataKey="actual" name="실측 Breadth" stroke="#868e96" strokeWidth={2} dot={{ r: 3, fill: '#868e96' }} connectNulls />
              <Line type="monotone" dataKey="predH1" name="+1h 예측" stroke="#7950f2" strokeWidth={2} dot={{ r: 3, fill: '#7950f2' }} connectNulls />
              <Line type="monotone" dataKey="predEOD" name="EOD 예측" stroke="#f08c00" strokeWidth={2} strokeDasharray="5 3" dot={{ r: 3, fill: '#f08c00' }} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ④ Sim0 리베로 2주 판단 vs 실제 시장 차트 */}
      <Divider mt="xl" mb="md" label="Sim0 리베로 — 2주 EOD 예측 vs 실제 장" labelPosition="center" />
      <Group gap={6} mb={4}>
        <IconActivity size={18} color="#7950f2" />
        <Text size="sm" fw={700}>리베로 EOD 예측 vs KOSPI 실제 Breadth (최근 14 거래일)</Text>
        {sim7HitRate && (
          <Badge
            color={sim7HitRate.pct >= 60 ? 'green' : sim7HitRate.pct >= 40 ? 'yellow' : 'red'}
            variant="light" size="sm"
          >
            방향 적중 {sim7HitRate.hits}/{sim7HitRate.total}일 ({sim7HitRate.pct}%)
          </Badge>
        )}
      </Group>
      <Text size="xs" c="dimmed" mb={8}>
        · <b style={{ color: '#7950f2' }}>보라선</b>: 리베로 EOD 예측 (그날 첫 나우캐스트) &nbsp;
        · <b style={{ color: '#868e96' }}>회색 점선</b>: KOSPI top100 확정 Breadth &nbsp;
        · 각 점 위 숫자: 갭 (예측 − 실제, 보라=양수 / 빨강=음수) &nbsp;
        · 60 이상 = BULL, 40 이하 = BEAR
      </Text>
      {sim7Loading ? (
        <Group justify="center" p="lg"><Loader size="xs" /></Group>
      ) : sim7Data.length === 0 ? (
        <Text size="xs" c="dimmed" ta="center" p="lg">데이터가 아직 없습니다. 리베로가 실행되면 자동으로 채워집니다.</Text>
      ) : (
        <div style={{ height: 260 }}>
          <ResponsiveContainer>
            <LineChart data={sim7Data} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
              {/* 배경 구역 */}
              <ReferenceArea y1={60} y2={100} fill="#2f9e44" fillOpacity={0.07} />
              <ReferenceArea y1={40} y2={60} fill="#f08c00" fillOpacity={0.07} />
              <ReferenceArea y1={0} y2={40} fill="#fa5252" fillOpacity={0.07} />
              <CartesianGrid stroke="#e9ecef" strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} tickCount={6} width={30} />
              <Tooltip content={<Sim7Tooltip />} />
              <ReferenceLine y={0} stroke="#ced4da" strokeDasharray="2 2" strokeWidth={1} />
              <ReferenceLine y={60} stroke="#2f9e44" strokeDasharray="4 2" strokeWidth={1} label={{ value: 'BULL', position: 'insideTopRight', fontSize: 9, fill: '#2f9e44' }} />
              <ReferenceLine y={40} stroke="#fa5252" strokeDasharray="4 2" strokeWidth={1} label={{ value: 'BEAR', position: 'insideBottomRight', fontSize: 9, fill: '#fa5252' }} />
              <Line
                type="monotone"
                dataKey="sim7Score"
                name="리베로 EOD 예측"
                stroke="#7950f2"
                strokeWidth={2}
                dot={{ r: 3, fill: '#7950f2' }}
                connectNulls
                label={({ x, y, index }: any) => {
                  const gap = sim7Data[index]?.gap;
                  if (gap == null) return <g />;
                  const color = gap > 0 ? '#7950f2' : gap < 0 ? '#fa5252' : '#868e96';
                  const text = gap > 0 ? `+${gap}` : `${gap}`;
                  return (
                    <text x={x} y={y - 8} textAnchor="middle" fontSize={9} fill={color} fontWeight={600}>
                      {text}
                    </text>
                  );
                }}
              />
              <Line
                type="monotone"
                dataKey="marketBreadth"
                name="실제 Breadth"
                stroke="#868e96"
                strokeWidth={2}
                strokeDasharray="5 3"
                dot={{ r: 3, fill: '#868e96' }}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
