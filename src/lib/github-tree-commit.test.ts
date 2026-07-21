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

test('원자 커밋 재시도: PATCH 충돌(422) 후 재시도 성공', async () => {
  const log: any[] = [];
  const responses = [
    // 첫 번째 시도: GET ref, GET commit, POST tree, POST commit, PATCH ref(실패 422)
    { ok: true, json: async () => ({ object: { sha: 'REFSHA1' } }) },          // GET ref
    { ok: true, json: async () => ({ tree: { sha: 'BASETREE1' } }) },          // GET commit
    { ok: true, json: async () => ({ sha: 'NEWTREE1' }) },                     // POST tree
    { ok: true, json: async () => ({ sha: 'NEWCOMMIT1' }) },                   // POST commit
    { ok: false, status: 422, text: async () => 'conflict' },                  // PATCH ref (422 충돌)
    // 재시도: GET ref(신규 ref), GET commit, POST tree, POST commit, PATCH ref(성공)
    { ok: true, json: async () => ({ object: { sha: 'REFSHA2' } }) },          // GET ref (새 ref)
    { ok: true, json: async () => ({ tree: { sha: 'BASETREE2' } }) },          // GET commit
    { ok: true, json: async () => ({ sha: 'NEWTREE2' }) },                     // POST tree
    { ok: true, json: async () => ({ sha: 'NEWCOMMIT2' }) },                   // POST commit
    { ok: true, json: async () => ({}) },                                      // PATCH ref (성공)
  ];
  let i = 0;
  const fakeFetch = async (url: string, init?: any) => {
    log.push({ url, method: init?.method ?? 'GET', body: init?.body });
    return responses[i++] as any;
  };

  const res = await commitFilesAtomically({
    owner: 'o', repo: 'r', branch: 'db-data', message: 'msg', token: 'T',
    files: [{ path: 'data/a.json', content: '{}' }],
    fetchImpl: fakeFetch as any,
  });

  assert.equal(log.length, 10);
  // 6번째 호출(인덱스 5)이 ref 재조회 (재시도의 첫 단계)
  assert.match(log[5].url, /git\/ref\/heads\/db-data/);
  assert.equal(log[5].method, 'GET');
  // 반환된 commitSha는 재시도 후 커밋 (NEWCOMMIT2)
  assert.equal(res.commitSha, 'NEWCOMMIT2');
});

test('원자 커밋: 2차 PATCH 충돌(409)도 throw', async () => {
  const log: any[] = [];
  const responses = [
    // 첫 번째 시도: GET ref, GET commit, POST tree, POST commit, PATCH ref(실패 409)
    { ok: true, json: async () => ({ object: { sha: 'REFSHA1' } }) },          // GET ref
    { ok: true, json: async () => ({ tree: { sha: 'BASETREE1' } }) },          // GET commit
    { ok: true, json: async () => ({ sha: 'NEWTREE1' }) },                     // POST tree
    { ok: true, json: async () => ({ sha: 'NEWCOMMIT1' }) },                   // POST commit
    { ok: false, status: 409, text: async () => 'conflict' },                  // PATCH ref (409 충돌)
    // 재시도: GET ref, GET commit, POST tree, POST commit, PATCH ref(또 실패 409)
    { ok: true, json: async () => ({ object: { sha: 'REFSHA2' } }) },          // GET ref
    { ok: true, json: async () => ({ tree: { sha: 'BASETREE2' } }) },          // GET commit
    { ok: true, json: async () => ({ sha: 'NEWTREE2' }) },                     // POST tree
    { ok: true, json: async () => ({ sha: 'NEWCOMMIT2' }) },                   // POST commit
    { ok: false, status: 409, text: async () => 'conflict' },                  // PATCH ref (409 다시 실패)
  ];
  let i = 0;
  const fakeFetch = async (url: string, init?: any) => {
    log.push({ url, method: init?.method ?? 'GET', body: init?.body });
    return responses[i++] as any;
  };

  await assert.rejects(
    async () => {
      await commitFilesAtomically({
        owner: 'o', repo: 'r', branch: 'db-data', message: 'msg', token: 'T',
        files: [{ path: 'data/a.json', content: '{}' }],
        fetchImpl: fakeFetch as any,
      });
    },
    (err: any) => err.message.includes('ref update')
  );

  // 전체 시퀀스 2회(10 호출) 실행 후 재시도 충돌로 throw
  assert.equal(log.length, 10);
});
