import axios from 'axios';

const REPO_OWNER = 'hoonnamkoong';
const REPO_NAME = 'stockbot';
const FILE_PATH = 'data/reservations.json';
const BRANCH = 'db-data';

// Ensure GITHUB_PAT is set in Vercel Environment Variables
const GITHUB_TOKEN = process.env.GITHUB_PAT;

interface Reservation {
    id: string;
    code: string;
    qty: string;
    price: string;
    side: 'buy' | 'sell';
    targetTime: string;
    createdAt: string;
    pin?: string; // Optional, might not want to store this if possible, or encrypt
}

interface GitHubFileResponse {
    sha: string;
    content: string;
    encoding: string;
}

export async function fetchReservations(): Promise<{ list: Reservation[], sha: string }> {
    if (!GITHUB_TOKEN) {
        console.error("GITHUB_PAT is missing");
        return { list: [], sha: '' };
    }

    try {
        const url = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/${FILE_PATH}?ref=${BRANCH}`;
        const res = await axios.get<GitHubFileResponse>(url, {
            headers: {
                'Authorization': `Bearer ${GITHUB_TOKEN}`,
                'Accept': 'application/vnd.github.v3+json'
            }
        });

        const content = Buffer.from(res.data.content, 'base64').toString('utf-8');
        const list = JSON.parse(content);
        return { list, sha: res.data.sha };
    } catch (error: any) {
        if (error.response?.status === 404) {
            // File doesn't exist yet, return empty
            return { list: [], sha: '' };
        }
        console.error("Failed to fetch reservations from GitHub:", error.message);
        throw error;
    }
}

export async function updateReservations(newList: Reservation[], message: string, sha?: string): Promise<boolean> {
    if (!GITHUB_TOKEN) return false;

    try {
        // If SHA not provided, fetch it first (optimistic locking)
        let currentSha = sha;
        if (!currentSha) {
            const { sha: fetchedSha } = await fetchReservations();
            currentSha = fetchedSha;
        }

        const content = Buffer.from(JSON.stringify(newList, null, 2)).toString('base64');
        const url = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/${FILE_PATH}`;

        await axios.put(url, {
            message: message,
            content: content,
            sha: currentSha, // Required to update (unless creating new)
            branch: BRANCH
        }, {
            headers: {
                'Authorization': `Bearer ${GITHUB_TOKEN}`,
                'Accept': 'application/vnd.github.v3+json'
            }
        });

        return true;
    } catch (error: any) {
        console.error("Failed to update reservations on GitHub:", error.message);
        return false;
    }
}
