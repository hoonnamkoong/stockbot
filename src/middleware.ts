export { default } from "next-auth/middleware"

export const config = { matcher: ["/trade", "/trade/:path*", "/research", "/research/:path*"] }
