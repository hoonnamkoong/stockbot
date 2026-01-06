import NextAuth from "next-auth"
import CredentialsProvider from "next-auth/providers/credentials"

const handler = NextAuth({
    providers: [
        CredentialsProvider({
            name: 'Admin Access',
            credentials: {
                password: { label: "Password", type: "password" }
            },
            async authorize(credentials) {
                const adminPassword = process.env.ADMIN_PASSWORD;
                // Simple string comparison
                if (credentials?.password && credentials.password === adminPassword) {
                    return { id: "1", name: "Admin" };
                }
                return null; // Login failed
            }
        })
    ],
    pages: {
        signIn: '/login', // Custom login page path
    },
    secret: process.env.NEXTAUTH_SECRET,
})

export { handler as GET, handler as POST }
