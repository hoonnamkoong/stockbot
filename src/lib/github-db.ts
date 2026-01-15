import axios from 'axios';

const REPO_OWNER = 'hoonnamkoong';
const REPO_NAME = 'stockbot';
const BRANCH = 'db-data';

// Ensure GITHUB_PAT is set in Vercel Environment Variables
const GITHUB_TOKEN = process.env.GITHUB_PAT;

export interface Reservation {
    id: string;
    code: string;
    qty: string;
    price: string;
    side: 'buy' | 'sell';
    targetTime: string;
    createdAt: string;
    pin?: string;
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
                'Accept': 'application/vnd.github.v3+json'
            }
        });

        const content = Buffer.from(res.data.content, 'base64').toString('utf-8');
        return { data: JSON.parse(content), sha: res.data.sha };
    } catch (error: any) {
        if (error.response?.status === 404) {
            return { data: null, sha: '' };
        }
        console.error(`[GitHubDB] Failed to fetch ${path}:`, error.message);
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
                'Accept': 'application/vnd.github.v3+json'
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
