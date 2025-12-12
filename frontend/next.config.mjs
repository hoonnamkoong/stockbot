/** @type {import('next').NextConfig} */
const nextConfig = {
    output: 'export', // Static Export for Vercel Backend-less
    images: { unoptimized: true }
};

export default nextConfig;
