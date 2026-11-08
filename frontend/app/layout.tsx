import type { Metadata } from 'next';

import { SessionProvider } from '@/components/SessionProvider';

import './globals.css';

export const metadata: Metadata = {
  title: 'Portals Auto-Order Manager',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
