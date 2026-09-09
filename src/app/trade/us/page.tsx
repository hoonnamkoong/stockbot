import TradeUSClient from './TradeUSClient';

export const dynamic = 'force-dynamic';

export const metadata = { robots: { index: false, follow: false } };

export default function TradeUSPage() {
    return <TradeUSClient />;
}
