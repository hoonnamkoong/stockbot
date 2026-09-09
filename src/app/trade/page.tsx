import TradeClient from './TradeClient';

export const dynamic = 'force-dynamic';

// 로그인 벽 뒤라 크롤러가 못 읽지만, 색인에 URL이 남을 이유도 없다.
export const metadata = { robots: { index: false, follow: false } };

export default function TradePage() {
    return <TradeClient />;
}
