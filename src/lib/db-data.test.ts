import { test } from 'node:test';
import assert from 'node:assert';
import { FRESHNESS_MS, createBucketCache, dbDataBucket, dbDataUrl } from './db-data.ts';

test('같은 버킷 안에서는 URL이 같다 — CDN이 답할 수 있다', () => {
  const t = 1_800_000_000_000;
  assert.equal(dbDataUrl('a.json', dbDataBucket(t)), dbDataUrl('a.json', dbDataBucket(t + FRESHNESS_MS - 1)));
});

test('버킷이 지나면 URL이 바뀐다 — 옛 사본에 갇히지 않는다', () => {
  const t = 1_800_000_000_000;
  assert.notEqual(dbDataUrl('a.json', dbDataBucket(t)), dbDataUrl('a.json', dbDataBucket(t + FRESHNESS_MS)));
});

test('파일마다 URL이 다르다', () => {
  assert.notEqual(dbDataUrl('a.json'), dbDataUrl('b.json'));
});

test('같은 버킷이면 build를 한 번만 부른다', async () => {
  let calls = 0;
  let now = 1_800_000_000_000;
  const get = createBucketCache(async () => ++calls, () => now);

  assert.equal(await get(), 1);
  now += FRESHNESS_MS - 1;
  assert.equal(await get(), 1);
  assert.equal(calls, 1);
});

test('버킷이 바뀌면 다시 부른다', async () => {
  let calls = 0;
  let now = 1_800_000_000_000;
  const get = createBucketCache(async () => ++calls, () => now);

  await get();
  now += FRESHNESS_MS;
  assert.equal(await get(), 2);
});

test('동시 요청은 한 번의 build를 나눠 쓴다', async () => {
  let calls = 0;
  const get = createBucketCache(async () => { calls++; return 'x'; });
  await Promise.all([get(), get(), get()]);
  assert.equal(calls, 1);
});

test('실패는 캐시하지 않는다 — 한 번의 조회 실패가 30초 빈 화면으로 굳지 않는다', async () => {
  let calls = 0;
  const get = createBucketCache(async () => {
    calls++;
    if (calls === 1) throw new Error('GitHub 조회 실패');
    return 'ok';
  });

  await assert.rejects(get(), /GitHub 조회 실패/);
  assert.equal(await get(), 'ok', '같은 버킷이어도 실패 뒤에는 다시 시도해야 한다');
  assert.equal(calls, 2);
});
