/**
 * 심 매매 기록 CSV(db-data) → 화면이 쓰는 행.
 *
 * 라우트에 인라인돼 있던 파싱이다. 옮긴 이유는 실버그 때문이다:
 * 기존 파서가 `text.split(',')`이라 **따옴표 안의 콤마를 필드 구분자로 봤다.**
 * 판단 사유에는 콤마가 흔하다(`"[레인지] 트레일링 청산 (고점대비 -2%, +38.3%)"`)
 * → 사유가 첫 콤마에서 잘려 나왔고, 사유 뒤에 열을 붙이면 그 열까지 밀린다.
 *
 * 파이썬 기록기(`base_simulator.log_trade`)와 열 순서를 공유하는 경계다.
 * 한쪽만 바꾸면 조용히 어긋난다 — docs/ARCHITECTURE_DEBT.md 2-A절.
 */

/** RFC4180 최소 구현: 따옴표 필드, `""` 이스케이프, 필드 안 콤마. */
export function parseCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = '';
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quoted) {
      if (ch === '"') {
        if (line[i + 1] === '"') { cur += '"'; i++; }  // "" → 리터럴 따옴표
        else quoted = false;
      } else cur += ch;
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ',') {
      out.push(cur.trim());
      cur = '';
    } else cur += ch;
  }
  out.push(cur.trim());
  return out;
}

export type SimHistoryEntry = {
  type: string; time: string; symbol: string; action: string;
  price: string; qty: string; amount: string; reason: string;
  /** 매도 실현 수익률. 파이썬이 부호까지 넣어 쓴다(`+38.31`). 없으면 null. */
  roi: string | null;
  /** 매도 실현 손익(원). 없으면 null 이고 0원과 구분된다. */
  roiAmount: number | null;
  /**
   * 이 파일이 ROI를 기록하는 포맷인가. false면 값이 없는 것이 정상이다 —
   * '측정 불가'(계산 실패)와 '기록 이전'을 화면이 구분하기 위한 플래그다.
   */
  roiTracked: boolean;
};

/** `1,234` 같은 천단위 표기를 숫자로. 빈 값·해석 불가는 null(0으로 만들지 않는다). */
function toNumberOrNull(v: string | undefined): number | null {
  if (v === undefined || v.trim() === '') return null;
  const n = Number(v.replace(/,/g, ''));
  return Number.isFinite(n) ? n : null;
}

/**
 * CSV 텍스트 → 기록 행.
 *
 * 헤더 이름으로 매핑한다(위치가 아니라). `roi`·`roi_amount`가 없는 구 포맷 파일은
 * 그 두 값이 null로 남는다 — 매도인데 ROI가 없는 것은 '기록 이전'이라는 뜻이고,
 * 화면은 이를 0%로 그리지 않는다.
 */
export function parseSimHistoryCsv(text: string, type: string): SimHistoryEntry[] {
  const lines = text.split('\n').filter((l) => l.trim().length > 0);
  if (lines.length <= 1) return [];

  // BOM(utf-8-sig)이 첫 헤더 이름에 붙어 오면 timestamp를 못 찾는다.
  const headers = parseCsvLine(lines[0].replace(/^﻿/, ''));
  const roiTracked = headers.includes('roi');
  const entries: SimHistoryEntry[] = [];

  for (let i = 1; i < lines.length; i++) {
    const values = parseCsvLine(lines[i]);
    if (values.length < 2) continue;

    const at = (name: string) => {
      const idx = headers.indexOf(name);
      return idx < 0 ? undefined : values[idx];
    };

    const price = at('price') || '';
    const qty = at('quantity') || '';
    let amount = at('total_amount') || '';
    if (!amount && price && qty) {
      const p = parseInt(price.replace(/,/g, ''), 10);
      const q = parseInt(qty, 10);
      if (!isNaN(p) && !isNaN(q)) amount = (p * q).toLocaleString();
    }

    const roi = at('roi');
    entries.push({
      type,
      time: at('timestamp') || '',
      symbol: at('symbol') || '',
      action: (at('action') || '').toUpperCase(),
      price, qty, amount,
      reason: at('reason') || '',
      roi: roi === undefined || roi.trim() === '' ? null : roi.trim(),
      roiAmount: toNumberOrNull(at('roi_amount')),
      roiTracked,
    });
  }
  return entries;
}
