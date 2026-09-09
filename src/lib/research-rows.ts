/**
 * 리서치 표의 행 만들기·정렬 — **공개 페이지와 `/research`가 같은 코드를 쓴다.**
 *
 * 이 매핑을 복제하면 안 되는 이유: 한 필드가 네 가지 이름으로 온다
 * (`recent_posts_count` / `게시물` / `당일_게시글수` / `게시글수`). 스크래퍼가
 * 포맷을 바꾸면 사본 하나만 고쳐지고, 다른 화면은 **빈 칸이 되는 게 아니라
 * 조용히 0으로 보인다.** 이 레포는 그 형태로 여러 번 당했다.
 *
 * 순수 함수만 둔다 — fetch도 상태도 없다. 그래야 node 테스트가 닿는다.
 */

export type SortConfig = { key: string | null; direction: 'asc' | 'desc' };

/** 숫자로 못 읽으면 0. 표는 정렬을 해야 하므로 여기서는 0이 맞다. */
export function parseNum(val: any): number {
    if (typeof val === 'number') return isNaN(val) ? 0 : val;
    if (typeof val === 'string') {
        const cleaned = val.replace(/[^-0-9.]/g, '');
        return parseFloat(cleaned) || 0;
    }
    return 0;
}

/**
 * API 한 행 → 표가 기대하는 모양. 필드 이름이 여러 갈래로 오는 것을 여기서 흡수한다.
 */
export function mapStockRow(item: any): any {
    return {
        ...item,
        market: item.market || item['시장'] || item['시장구분'],
        code: item.code,
        name: item.name || item['종목명'],
        price: parseNum(item.price || item['현재가']),
        current_price: parseNum(item.price || item['현재가']),
        prev_close: parseNum(item.prev_close || item['전일종가'] || item['어제_종가']),
        change_rate: parseNum(item.change_rate || item['등락률']),
        recent_posts_count: item.recent_posts_count || item['게시물']
            || item['당일_게시글수'] || item['게시글수'] || item['당일 게시글수'],
        foreign_rate: parseNum(item.foreign_rate || item['외인비중']
            || item['외인소진율'] || item['현재_외국인비중']),
        prev_foreign_rate: parseNum(item.prev_foreign_rate || item['전일외인']
            || item['전일_외국인비중'] || item['어제_외국인비중']),
        posts_summary: item.posts_summary || item['게시물_요약'],
        sentiment: item.sentiment || item['감정'] || item['감정분석'],
        top_keywords: Array.isArray(item.top_keywords) ? item.top_keywords :
            (typeof item.top_keywords === 'string'
                ? item.top_keywords.split(',').map((k: string) => k.trim())
                : (item['키워드'] || item['Top_Keyword'] || item['Top_Keywords'] || [])),
        is_last_captured: item.is_last_captured || (item['연속'] > 1),
        consecutive_days: Number(item.consecutive_days || item['연속'])
            || (item['연속_등록'] === true ? 2 : 1),
        foreign_change_rate: parseNum(item.foreign_change_rate || item['외인변화']
            || item['외국인_변화'] || item['foreign_change'] || 0),
        latest_post: item.latest_posts && item.latest_posts.length > 0
            ? item.latest_posts[0].title : (item['latest_post'] || ''),
        status: item.status || item['상태'] || '활성',
    };
}

/** 같은 열을 다시 누르면 방향만 뒤집는다. 다른 열이면 내림차순부터. */
export function nextSort(prev: SortConfig, key: string): SortConfig {
    return {
        key,
        direction: prev.key === key && prev.direction === 'desc' ? 'asc' : 'desc',
    };
}

/** 원본을 건드리지 않는다 — 호출부가 같은 배열을 다시 렌더링한다. */
export function sortRows<T extends Record<string, any>>(rows: T[], cfg: SortConfig): T[] {
    if (!cfg.key) return rows;
    const parse = (v: any) =>
        typeof v === 'string' ? (Number(v.replace(/,/g, '').replace('%', '')) || v.toLowerCase()) : v;
    return [...rows].sort((a, b) => {
        const A = parse(a[cfg.key!]);
        const B = parse(b[cfg.key!]);
        return cfg.direction === 'asc' ? (A < B ? -1 : 1) : (A > B ? -1 : 1);
    });
}
