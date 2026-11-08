'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useCallback, useEffect, useState, type ReactNode } from 'react';

import { useSession } from '@/components/SessionProvider';
import { Badge, Button, Spinner } from '@/components/ui';
import { apiFetch } from '@/lib/api';
import type { NotificationItem, Settings } from '@/lib/types';

const NAV_ITEMS = [
  { href: '/', label: 'Главная' },
  { href: '/collections', label: 'Коллекции' },
  { href: '/rules', label: 'Правила' },
  { href: '/offers', label: 'Офферы' },
  { href: '/gifts', label: 'Мои подарки' },
  { href: '/trader', label: 'Умный трейдер' },
  { href: '/history', label: 'История' },
  { href: '/settings', label: 'Настройки' },
];

export function Shell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, loading, logout } = useSession();
  const [mode, setMode] = useState('dry_run');
  const [unread, setUnread] = useState(0);

  const refreshHeader = useCallback(async () => {
    try {
      const settings = await apiFetch<Settings>('/api/settings');
      setMode(settings.mode);
    } catch {
      setUnread((current) => current);
    }
    try {
      const items = await apiFetch<NotificationItem[]>('/api/notifications?unread_only=true');
      setUnread(items.length);
    } catch {
      setUnread((current) => current);
    }
  }, []);

  useEffect(() => {
    if (!loading && user === null) {
      router.replace('/login');
    }
  }, [loading, user, router]);

  useEffect(() => {
    if (user === null) {
      return undefined;
    }
    void refreshHeader();
    const timer = setInterval(() => {
      void refreshHeader();
    }, 30000);
    return () => {
      clearInterval(timer);
    };
  }, [user, refreshHeader]);

  async function emergencyStop() {
    if (!window.confirm('Включить аварийную остановку? Автоматизация будет остановлена.')) {
      return;
    }
    try {
      await apiFetch('/api/settings/emergency-stop', {
        method: 'POST',
        body: JSON.stringify({
          enabled: true,
          reason: 'Ручная остановка из панели',
          cancel_offers: false,
        }),
      });
      await refreshHeader();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : 'Не удалось включить аварийную остановку');
    }
  }

  async function handleLogout() {
    await logout();
    router.replace('/login');
  }

  if (loading || user === null) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  const isLive = mode === 'live';

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <aside className="border-b border-slate-800 bg-slate-900/70 p-3 lg:w-56 lg:shrink-0 lg:border-b-0 lg:border-r">
        <div className="mb-3 px-2 text-sm font-semibold text-slate-100">Portals Auto-Order</div>
        <nav className="flex flex-wrap gap-1 lg:flex-col">
          {NAV_ITEMS.concat(user.is_admin ? [{ href: '/admin/users', label: 'Пользователи' }] : []).map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`rounded-md px-3 py-1.5 text-sm transition ${
                  active
                    ? 'bg-blue-600 text-white'
                    : 'text-slate-300 hover:bg-slate-800 hover:text-slate-100'
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>

      <div className="flex flex-1 flex-col">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 bg-slate-900/70 px-4 py-3">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm text-slate-300">
              Пользователь: <span className="font-medium text-slate-100">{user.username}</span>
            </span>
            <Badge tone={isLive ? 'red' : 'blue'}>{isLive ? 'LIVE' : 'DRY-RUN'}</Badge>
            <Link
              href="/notifications"
              className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
            >
              Уведомления: {unread}
            </Link>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="danger" onClick={emergencyStop}>
              АВАРИЙНАЯ ОСТАНОВКА
            </Button>
            <Button variant="ghost" onClick={handleLogout}>
              Выйти
            </Button>
          </div>
        </header>

        <main className="flex-1 space-y-4 p-4">{children}</main>
      </div>
    </div>
  );
}
