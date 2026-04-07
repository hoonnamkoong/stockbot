import { GET as CronGET } from '../route';

export const dynamic = 'force-dynamic';
export const maxDuration = 60;

export async function GET(request: Request) {
    return CronGET(request);
}
