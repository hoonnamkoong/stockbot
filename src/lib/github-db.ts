import axios from 'axios';

const REPO_OWNER = 'hoonnamkoong';
const REPO_NAME = 'stockbot';
const BRANCH = 'db-data';

// Ensure GITHUB_PAT is set and cleansed
const GITHUB_TOKEN = (process.env.GITHUB_PAT || '').trim().replace(/[\r\n\s]+/g, '');

if (!GITHUB_TOKEN) {
    console.warn('[GitHubDB] WARNING: GITHUB_PAT is NOT SET or EMPTY.');
} else {
    console.log(`[GitHubDB] GITHUB_PAT detected (Cleaned, Length: ${GITHUB_TOKEN.length})`);
}

export interface Reservation {
    id: string;
    code: string;
    qty: string;
    price: string;
    side: 'buy' | 'sell' | string;
    targetTime: string;
    createdAt: string;
    pin?: string;
    status?: 'RESERVED' | 'DISPATCHED' | 'SUCCESS' | 'FAILED';
    isExecuted?: boolean;
}

interface GitHubFileResponse {
    sha: string;
    content: string;
    encoding: string;
}

// GENERIC FILE OPERATIONS
export async function fetchFile<T>(path: string): Promise<{ data: T | null, sha: string }> {
    if (!GITHUB_TOKEN) {
        console.error(`[GitHubDB] GITHUB_PAT missing, cannot fetch ${path}`);
        return { data: null, sha: '' };
    }

    try {
        const url = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/${path}?ref=${BRANCH}`;
        const res = await axios.get<GitHubFileResponse>(url, {
            headers: {
                'Authorization': `Bearer ${GITHUB_TOKEN}`,
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'StockBot-Vercel/1.0 (https://github.com/hoonnamkoong/stockbot)'
            }
        });

        const content = Buffer.from(res.data.content, 'base64').toString('utf-8');
        let parsedData = null;
        try {
            parsedData = JSON.parse(content);
        } catch (parseError: any) {
            console.warn(`[GitHubDB] JSON parse error for ${path}: ${parseError.message}. Returning null data.`);
        }
        return { data: parsedData, sha: res.data.sha };
    } catch (error: any) {
        if (error.response?.status === 404) {
            console.warn(`[GitHubDB] File NOT FOUND (404): ${path} on branch ${BRANCH}`);
            return { data: null, sha: '' };
        }
        
        if (error.response?.status === 401) {
            console.error(`[GitHubDB] AUTHENTICATION FAILED (401): Check your GITHUB_PAT. Path: ${path}`);
        } else if (error.response?.status === 403) {
            console.error(`[GitHubDB] PERMISSION DENIED (403): Token might lack 'repo' scope. Path: ${path}`);
        } else {
            console.error(`[GitHubDB] Failed to fetch ${path} (${error.response?.status || 'Unknown'}):`, error.message);
        }
        throw error;
    }
}

export async function saveFile(path: string, data: any, message: string, sha?: string): Promise<boolean> {
    if (!GITHUB_TOKEN) return false;

    try {
        let currentSha = sha;
        // Optimistic locking: fetch SHA if not provided
        if (!currentSha) {
            const { sha: fetchedSha } = await fetchFile(path);
            currentSha = fetchedSha;
        }

        const content = Buffer.from(JSON.stringify(data, null, 2)).toString('base64');
        const url = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/${path}`;

        await axios.put(url, {
            message: message,
            content: content,
            sha: currentSha,
            branch: BRANCH
        }, {
            headers: {
                'Authorization': `Bearer ${GITHUB_TOKEN}`,
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'StockBot-Vercel/1.0 (https://github.com/hoonnamkoong/stockbot)'
            }
        });

        return true;
    } catch (error: any) {
        console.error(`[GitHubDB] Failed to save ${path}:`, error.message);
        return false;
    }
}

// RESERVATION SPECIFIC WRAPPERS
const RESERVATIONS_PATH = 'data/reservations.json';

export async function fetchReservations(): Promise<{ list: Reservation[], sha: string }> {
    const { data, sha } = await fetchFile<Reservation[]>(RESERVATIONS_PATH);
    return { list: data || [], sha };
}

export async function updateReservations(newList: Reservation[], message: string, sha?: string): Promise<boolean> {
    return saveFile(RESERVATIONS_PATH, newList, message, sha);
}

// COMMAND SPECIFIC WRAPPERS
const COMMANDS_PATH = 'data/commands.json';

export async function appendCommand(command: any): Promise<boolean> {
    try {
        const { data, sha } = await fetchFile<any[]>(COMMANDS_PATH);
        const list = data || [];
        list.push({ ...command, timestamp: new Date().toISOString() });
        return await saveFile(COMMANDS_PATH, list, "Append trade command");
    } catch (error) {
        console.error("[GitHubDB] Failed to append command", error);
        return false;
    }
}

// ORDER STATUS WRAPPERS (Hybrid Feedback Loop)
const ORDER_STATUS_PATH = 'data/order_status.json';

export async function fetchOrderStatus(): Promise<{ data: Record<string, any> | null, sha: string }> {
    return await fetchFile<Record<string, any>>(ORDER_STATUS_PATH);
}

export async function updateOrderStatus(newStatusDict: Record<string, any>, sha?: string): Promise<boolean> {
    return await saveFile(ORDER_STATUS_PATH, newStatusDict, "Update order status from mobile agent", sha);
}
