import ShowcaseClient from './ShowcaseClient';

export const dynamic = 'force-dynamic';

/**
 * 예전에는 여기가 `/trade`로 리다이렉트했다 — 그래서 사이트 전체가 사실상
 * 로그인 뒤에 있었고, 들어와도 볼 것이 없었다. 이제 공개 쇼케이스가 여기 있다.
 * `/trade`는 그대로 미들웨어가 지킨다.
 */
export default function Home() {
    return <ShowcaseClient />;
}
