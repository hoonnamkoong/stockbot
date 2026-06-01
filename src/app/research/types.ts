export interface Stock {
    code: string;
    name: string;
    market: string;
    price: number;
    current_price: number;
    prev_close: number;
    change_rate: number;
    recent_posts_count: number;
    foreign_rate: number;
    prev_foreign_rate: number;
    foreign_change_rate: number;
    inst_net_buy?: number;
    posts_summary: string;
    sentiment: string;
    top_keywords: string[];
    is_last_captured: boolean;
    consecutive_days: number;
    latest_post: string;
    price_history?: number[];
    tick_power?: number;
    bid_ask_ratio?: number;
    // KIS API 보강 필드
    frgn_fake_ntby_qty?: number;   // 외국인 추정 순매수
    orgn_fake_ntby_qty?: number;   // 기관 추정 순매수
    roe?: number;                   // ROE (%)
    debt_ratio?: number;            // 부채비율 (%)
    invest_opinion?: string;        // 투자의견
    target_price?: number;          // HTS 목표가
    opinion_divergence?: number;    // 목표가 괴리율 (%)
    consensus_summary?: string;     // 증권사 컨센서스 요약
    // inquire-price 확장 필드
    per?: number;
    pbr?: number;
    eps?: number;
    bps?: number;
    w52_hgpr?: number;
    w52_lwpr?: number;
    mkt_cap?: number;
}

export interface FiveDayStock {
    code: string;
    name: string;
    current_price: number;
    change_rate: number;
    count: number;
    consecutive_days: number;
    avg_posts: number;
    total_posts: number;
    price_history?: number[];
    post_history?: number[];
    sparkline_price?: number[];
    sparkline_posts?: number[];
}

export interface VersionInfo {
    version: string;
    last_commit: string;
    deploy_time: string;
}

export interface SortConfig {
    key: string | null;
    direction: 'asc' | 'desc';
}
