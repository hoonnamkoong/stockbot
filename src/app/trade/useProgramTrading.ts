'use client';

import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import type { LastTurnResult, ProgramTurn } from '@/lib/program-turn';

export type ProgramPositions = Record<string, { name: string; quantity: number; avg_price: number; tag?: string }>;

/**
 * 프로그램 매매(실전 계좌 자동 심 운용)의 상태와 조작.
 *
 * TradeClient.tsx가 들고 있던 `useState` 14개 + 페처·제출·토글이 여기로 왔다.
 * 41개 중 14개라 이걸 빼는 것만으로 TradeContent가 눈에 보이게 얇아진다.
 *
 * **실거래 문이다.** ON은 반드시 PIN을 거치고, OFF는 kill-switch라 PIN 없이 즉시
 * 나간다 — 이 비대칭이 의도다. 서버 쪽 판정은 `src/lib/trade-auth.ts`에 테스트가 있다.
 *
 * `showNotify`만 밖에서 받는다(알림은 화면 전체가 공유하는 것이라 여기 두면 안 된다).
 */
export function useProgramTrading(showNotify: (title: string, msg: string, color: string) => void) {
    const [programEnabled, setProgramEnabled] = useState(false);
    const [programSim, setProgramSim] = useState<string | null>(null);
    const [programBudget, setProgramBudget] = useState<number | ''>('');
    const [programConfirmedBudget, setProgramConfirmedBudget] = useState(0);
    const [programSims, setProgramSims] = useState<{ id: string; name: string; description: string }[]>([]);
    const [programValid, setProgramValid] = useState(true);
    const [programBusy, setProgramBusy] = useState(false);
    const [programPinOpen, setProgramPinOpen] = useState(false);
    const [programPin, setProgramPin] = useState('');
    const [programPositions, setProgramPositions] = useState<ProgramPositions>({});
    const [programRealizedPnl, setProgramRealizedPnl] = useState(0);
    const [programLedgerOk, setProgramLedgerOk] = useState(true);
    const [programTurn, setProgramTurn] = useState<ProgramTurn | null>(null);
    const [programLastTurn, setProgramLastTurn] = useState<LastTurnResult | null>(null);

    const fetchProgram = useCallback(async () => {
        try {
            const res = await axios.get('/api/trade/program');
            const d = res.data || {};
            setProgramEnabled(!!d.enabled);
            setProgramSim(d.selected_sim ?? null);
            setProgramBudget(d.budget ? Number(d.budget) : '');
            setProgramConfirmedBudget(Number(d.budget) || 0);
            setProgramSims(Array.isArray(d.sims) ? d.sims : []);
            setProgramValid(d.selected_valid !== false);
            setProgramPositions(d.positions && typeof d.positions === 'object' ? d.positions : {});
            setProgramRealizedPnl(Number(d.realized_pnl) || 0);
            setProgramLedgerOk(d.ledger_ok !== false);
            setProgramTurn(d.turn && d.turn.id ? d.turn : null);
            setProgramLastTurn(d.last_turn_result ?? null);
        } catch { /* 미로그인/네트워크 실패 시 조용히 무시 */ }
    }, []);

    useEffect(() => { fetchProgram(); }, [fetchProgram]);

    const submitProgram = async (enable: boolean, pinVal?: string) => {
        setProgramBusy(true);
        try {
            const res = await axios.post('/api/trade/program', {
                enabled: enable,
                selected_sim: programSim,
                budget: Number(programBudget) || 0,
                pin: pinVal,
            });
            if (res.data?.success) {
                setProgramEnabled(!!res.data.enabled);
                showNotify('프로그램 매매', res.data.enabled ? `ON — ${programSim} 자동 운용` : 'OFF (수동 매매만)', res.data.enabled ? 'red' : 'gray');
                fetchProgram();
            } else {
                showNotify('프로그램 매매 실패', res.data?.error || '변경 실패', 'red');
            }
        } catch (e: any) {
            showNotify('프로그램 매매 실패', e.response?.data?.error || e.message, 'red');
        } finally {
            setProgramBusy(false);
            setProgramPinOpen(false);
            setProgramPin('');
        }
    };

    const onToggleProgram = (checked: boolean) => {
        if (checked) {
            // arm: 로컬 유효성 확인 후 PIN
            if (!programSim) { showNotify('프로그램 매매', '먼저 매매 심을 선택하세요.', 'yellow'); return; }
            if (!(Number(programBudget) > 0)) { showNotify('프로그램 매매', '프로그램 예산(>0)을 입력하세요.', 'yellow'); return; }
            setProgramPin('');
            setProgramPinOpen(true);
        } else {
            submitProgram(false); // kill-switch: PIN 없이 즉시 OFF
        }
    };

    return {
        programEnabled, programSim, setProgramSim,
        programBudget, setProgramBudget, programConfirmedBudget,
        programSims, programValid, programBusy,
        programPinOpen, setProgramPinOpen, programPin, setProgramPin,
        programPositions, programRealizedPnl, programLedgerOk,
        programTurn, programLastTurn,
        submitProgram, onToggleProgram,
    };
}
