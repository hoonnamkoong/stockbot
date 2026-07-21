import { test } from 'node:test';
import assert from 'node:assert';
import { commitFilesAtomically } from './github-tree-commit.ts';

function makeFakeFetch(log: any[]) {
  // 순서: GET ref, GET commit, POST tree, POST commit, PATCH ref
  const responses = [
    { ok: true, json: async () => ({ object: { sha: 'REFSHA' } }) },          // GET ref
    { ok: true, json: async () => ({ tree: { sha: 'BASETREE' } }) },          // GET commit
    { ok: true, json: async () => ({ sha: 'NEWTREE' }) },                     // POST tree
    { ok: true, json: async () => ({ sha: 'NEWCOMMIT' }) },                   // POST commit
    { ok: true, json: async () => ({}) },                                     // PATCH ref
  ];
  let i = 0;
  return async (url: string, init?: any) => {
    log.push({ url, method: init?.method ?? 'GET', body: init?.body });
    return responses[i++] as any;
  };
}

test('원자 커밋: ref→tree→commit→ref, tree에 파일 포함', async () => {
  const log: any[] = [];
  const res = await commitFilesAtomically({
    owner: 'o', repo: 'r', branch: 'db-data', message: 'msg', token: 'T',
    files: [{ path: 'data/a.json', content: '{}' }, { path: 'data/b.csv', content: 'h\n' }],
    fetchImpl: makeFakeFetch(log) as any,
  });
  assert.equal(res.commitSha, 'NEWCOMMIT');
  assert.equal(log.length, 5);
  assert.match(log[0].url, /git\/ref\/heads\/db-data/);
  // POST tree(3번째) body에 두 파일 경로가 담긴다
  const treeBody = JSON.parse(log[2].body);
  assert.equal(treeBody.base_tree, 'BASETREE');
  assert.deepEqual(treeBody.tree.map((t: any) => t.path), ['data/a.json', 'data/b.csv']);
  assert.equal(treeBody.tree[0].mode, '100644');
  // PATCH ref(5번째)가 새 커밋으로 이동
  assert.match(log[4].url, /git\/refs\/heads\/db-data/);
  assert.equal(JSON.parse(log[4].body).sha, 'NEWCOMMIT');
});
