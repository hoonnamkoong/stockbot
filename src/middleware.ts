import { withAuth } from "next-auth/middleware";

export default withAuth({
    // Matches the pages config in `[...nextauth]`
    pages: {
        signIn: '/login',
    },
});

export const config = { matcher: ["/trade", "/trade/:path*", "/research", "/research/:path*"] }
