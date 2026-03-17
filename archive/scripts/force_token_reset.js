
import axios from 'axios';

const REPO_OWNER = 'hoonnamkoong';
const REPO_NAME = 'stockbot';
const BRANCH = 'db-data';
const PATH = 'data/kis_token.json';
const GITHUB_TOKEN = process.env.GITHUB_PAT || process.env.GITHUB_TOKEN;

async function forceResetToken() {
    if (!GITHUB_TOKEN) {
        console.error("❌ Error: GITHUB_PAT (or GITHUB_TOKEN) environment variable is missing.");
        return;
    }

    try {
        console.log(`[Reset] Fetching current SHA for ${PATH}...`);
        const getUrl = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/${PATH}?ref=${BRANCH}`;
        const res = await axios.get(getUrl, {
            headers: {
                'Authorization': `Bearer ${GITHUB_TOKEN}`,
                'Accept': 'application/vnd.github.v3+json'
            }
        });

        const sha = res.data.sha;
        console.log(`[Reset] Found SHA: ${sha}. Deleting file to force refresh...`);

        const deleteUrl = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/${PATH}`;
        await axios.delete(deleteUrl, {
            headers: {
                'Authorization': `Bearer ${GITHUB_TOKEN}`,
                'Accept': 'application/vnd.github.v3+json'
            },
            data: {
                message: "Force reset KIS token cache",
                sha: sha,
                branch: BRANCH
            }
        });

        console.log("✅ SUCCESS: KIS Token Cache has been cleared.");
        console.log("이제 대시보드를 새로고침하면 새로운 AppSecret으로 토큰을 다시 받아올 것입니다.");
    } catch (error) {
        if (error.response?.status === 404) {
            console.log("ℹ️ Cache file already does not exist (Clean state).");
        } else {
            console.error("❌ Failed to reset token:", error.message);
        }
    }
}

forceResetToken();
