import '@mantine/core/styles.css';
import { ColorSchemeScript, MantineProvider } from '@mantine/core';

import AuthSessionProvider from './components/AuthSessionProvider';

export const metadata = {
    title: 'Stock Dashboard',
    description: 'KIS Trading Dashboard',
};

export default function RootLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <html lang="en">
            <head>
                <ColorSchemeScript />
            </head>
            <body>
                <MantineProvider>
                    <AuthSessionProvider>
                        {children}
                    </AuthSessionProvider>
                </MantineProvider>
            </body>
        </html>
    );
}
