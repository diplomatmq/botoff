'use client';

import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';

import { useSession } from '@/components/SessionProvider';
import { Button, Input } from '@/components/ui';

export default function LoginPage() {
  const router = useRouter();
  const { login } = useSession();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      router.replace('/');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось выполнить вход');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-lg border border-slate-800 bg-slate-900/70 p-6 shadow-xl"
      >
        <h1 className="mb-1 text-lg font-semibold text-slate-100">Portals Auto-Order</h1>
        <p className="mb-5 text-sm text-slate-400">Вход в панель управления</p>

        <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">Логин</label>
        <Input
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          autoComplete="username"
          required
          className="mb-4"
        />

        <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">Пароль</label>
        <Input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          required
          className="mb-4"
        />

        {error !== null && (
          <p className="mb-4 rounded-md border border-red-600/50 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </p>
        )}

        <Button type="submit" variant="primary" disabled={busy} className="w-full">
          {busy ? 'Вход...' : 'Войти'}
        </Button>
      </form>
    </div>
  );
}
