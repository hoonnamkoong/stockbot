interface CommitOpts {
  owner: string; repo: string; branch: string; message: string;
  files: { path: string; content: string }[];
  token: string; fetchImpl?: typeof fetch;
}

export async function commitFilesAtomically(opts: CommitOpts): Promise<{ commitSha: string }> {
  const f = opts.fetchImpl ?? fetch;
  const base = `https://api.github.com/repos/${opts.owner}/${opts.repo}`;
  const headers = {
    Authorization: `token ${opts.token}`,
    Accept: 'application/vnd.github.v3+json',
    'Content-Type': 'application/json',
  };

  const doCommit = async (): Promise<string> => {
    // 1. 브랜치 ref → 최신 커밋 sha
    const refRes = await f(`${base}/git/ref/heads/${opts.branch}`, { headers, cache: 'no-store' } as any);
    if (!refRes.ok) throw new Error(`ref read ${refRes.status}`);
    const refSha = (await refRes.json()).object.sha as string;

    // 2. 커밋 → base tree sha
    const cRes = await f(`${base}/git/commits/${refSha}`, { headers, cache: 'no-store' } as any);
    if (!cRes.ok) throw new Error(`commit read ${cRes.status}`);
    const baseTree = (await cRes.json()).tree.sha as string;

    // 3. 새 tree (파일 inline content, blob 자동 생성)
    const treeRes = await f(`${base}/git/trees`, {
      method: 'POST', headers,
      body: JSON.stringify({
        base_tree: baseTree,
        tree: opts.files.map(file => ({ path: file.path, mode: '100644', type: 'blob', content: file.content })),
      }),
    } as any);
    if (!treeRes.ok) throw new Error(`tree ${treeRes.status}: ${await treeRes.text()}`);
    const newTree = (await treeRes.json()).sha as string;

    // 4. 커밋 생성
    const commitRes = await f(`${base}/git/commits`, {
      method: 'POST', headers,
      body: JSON.stringify({ message: opts.message, tree: newTree, parents: [refSha] }),
    } as any);
    if (!commitRes.ok) throw new Error(`commit create ${commitRes.status}`);
    const newCommit = (await commitRes.json()).sha as string;

    // 5. ref 이동 (fast-forward만)
    const patchRes = await f(`${base}/git/refs/heads/${opts.branch}`, {
      method: 'PATCH', headers,
      body: JSON.stringify({ sha: newCommit, force: false }),
    } as any);
    if (!patchRes.ok) {
      const err: any = new Error(`ref update ${patchRes.status}`);
      err.conflict = patchRes.status === 422 || patchRes.status === 409;
      throw err;
    }
    return newCommit;
  };

  try {
    return { commitSha: await doCommit() };
  } catch (e: any) {
    if (e?.conflict) return { commitSha: await doCommit() }; // 1회 재시도(최신 ref로)
    throw e;
  }
}
