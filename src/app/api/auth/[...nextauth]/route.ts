import NextAuth from "next-auth"
import CredentialsProvider from "next-auth/providers/credentials"

const handler = NextAuth({
    providers: [
        CredentialsProvider({
            name: 'Admin Access',
            credentials: {
                password: { label: "Password", type: "password" },
                deviceId: { label: "Device ID", type: "text" }
            },
            async authorize(credentials) {
                const adminPassword = process.env.ADMIN_PASSWORD;
                const trustedDevices = process.env.TRUSTED_DEVICES || '';

                // 1. Password Check
                if (!credentials?.password || credentials.password !== adminPassword) {
                    throw new Error("Invalid password");
                }

                // 2. Trusted Device Check
                if (!trustedDevices) {
                    throw new Error("Security Error: TRUSTED_DEVICES not configured on server");
                }

                const allowedDevices = trustedDevices.split(',').map(d => d.trim()).filter(Boolean);
                if (!credentials?.deviceId || !allowedDevices.includes(credentials.deviceId)) {
                    throw new Error("Device Not Allowed. Please add Device ID to TRUSTED_DEVICES env var.");
                }

                return { id: "1", name: "Admin" };
            }
        })
    ],
    session: {
        strategy: 'jwt'
    },
    pages: {
        signIn: '/login', // Custom login page path
    },
    secret: process.env.NEXTAUTH_SECRET,
})

export { handler as GET, handler as POST }
