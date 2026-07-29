/**
 * db-data 브랜치(= 이 시스템의 DB)를 읽을 때의 신선도 규칙.
 *
 * 대시보드 1회 로드가 GitHub raw를 25회 친다(심 상태 13 + 매매 CSV 12). 병렬이라
 * 느리진 않지만 **전부 CDN 미스**였다 — URL에 `?t=${Date.now()}`를 붙여 요청마다
 * 주소가 달라졌기 때문이다. 캐시버스터가 있던 이유는 GitHub CDN이 방금 커밋한
 * 파일 대신 옛 사본을 주는 일이 있어서다.
 *
 * 그래서 없애지 않고 **버킷으로 만든다.** 같은 30초 안의 요청은 같은 URL을 쓰므로
 * CDN이 대신 답하고, 30초가 지나면 주소가 바뀌어 새 파일을 확실히 받는다.
 * 생산자(파이프라인)는 10분마다 도니 30초 지연은 화면에 보이지 않는다.
 *
 * 라우트의 메모리 캐시도 같은 버킷 번호를 키로 쓴다. 두 장치의 지연이 더해지지
 * 않게 하려는 것이다 — **이 파일의 FRESHNESS_MS 하나가 대시보드가 볼 수 있는
 * 최대 지연이다.**
 */
export const DB_DATA_BASE = 'https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data';

/** 대시보드가 감수하는 최대 지연. 이 값 하나만 보면 된다. */
export const FRESHNESS_MS = 30_000;

export function dbDataBucket(now: number = Date.now()): number {
  return Math.floor(now / FRESHNESS_MS);
}

/** db-data 파일 URL. 같은 버킷 안에서는 항상 같은 주소 → CDN이 답한다. */
export function dbDataUrl(file: string, bucket: number = dbDataBucket()): string {
  return `${DB_DATA_BASE}/${file}?t=${bucket}`;
}

/**
 * 같은 버킷 동안 build()의 결과를 재사용한다. 재로드·동시 접속이 오리진을 다시 치지 않는다.
 *
 * 서버리스 인스턴스 메모리라 완벽한 공유 캐시가 아니다(인스턴스마다 하나) — '같은
 * 순간의 재요청을 흡수하는' 용도다. **실패는 캐시하지 않는다.** 한 번의 조회 실패가
 * 30초짜리 빈 화면으로 굳으면 [[no-fabricated-financial-values]]의 '측정 불가'가
 * 실제보다 오래 남는다.
 */
export function createBucketCache<T>(
  build: () => Promise<T>,
  now: () => number = Date.now,
): () => Promise<T> {
  let cached: { bucket: number; value: Promise<T> } | null = null;
  return () => {
    const bucket = dbDataBucket(now());
    if (!cached || cached.bucket !== bucket) {
      const value = build().catch((e) => {
        cached = null;
        throw e;
      });
      cached = { bucket, value };
    }
    return cached.value;
  };
}
