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
    posts_summary: string;
    sentiment: string;
    top_keywords: string[];
    is_last_captured: boolean;
    consecutive_days: number;
    latest_post: string;
    price_history?: number[];
}

export interface FiveDayStock {
    code: string;
    name: string;
    current_price: number;
    change_rate: number;
    count: number;
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
