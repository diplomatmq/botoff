'use client';

import { useCallback, useEffect, useState, type FormEvent } from 'react';

import { Shell } from '@/components/Shell';
import { Alert, Badge, Button, Card, Input, Toggle } from '@/components/ui';
import { apiFetch } from '@/lib/api';
import type { AdminUser, MessageResponse } from '@/lib/types';

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [chatId, setChatId] = useState('');
  const [telegramEnabled, setTelegramEnabled] = useState(true);
  const [isAdmin, setIsAdmin] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const loadUsers = useCallback(async () => {
    try {
      setUsers(await apiFetch<AdminUser[]>('/api/admin/users'));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить пользователей');
    }
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    try {
      await apiFetch<AdminUser>('/api/admin/users', {
        method: 'POST',
        body: JSON.stringify({
          username,
          password,
          is_admin: isAdmin,
          telegram_chat_id: chatId || null,
          telegram_enabled: telegramEnabled,
        }),
      });
      setUsername('');
      setPassword('');
      setChatId('');
      setIsAdmin(false);
      setMessage('Пользователь создан');
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось создать пользователя');
    }
  }

  async function updateUser(user: AdminUser, body: Record<string, unknown>, success: string) {
    setError(null);
    try {
      await apiFetch<AdminUser>(`/api/admin/users/${user.id}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      });
      setMessage(success);
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось обновить пользователя');
    }
  }

  async function deactivate(user: AdminUser) {
    if (!window.confirm(`Отключить пользователя «${user.username}»?`)) return;
    try {
      await apiFetch<MessageResponse>(`/api/admin/users/${user.id}`, { method: 'DELETE' });
      setMessage('Пользователь отключён');
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось отключить пользователя');
    }
  }

  return (
    <Shell>
      <h1 className="text-lg font-semibold text-slate-100">Пользователи</h1>
      {error && <Alert tone="red">{error}</Alert>}
      {message && <Alert tone="green">{message}</Alert>}
      <Card title="Создать аккаунт">
        <form className="grid gap-3 md:grid-cols-2" onSubmit={createUser}>
          <Input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="Логин" required />
          <Input value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Пароль (минимум 10 символов)" minLength={10} required type="password" />
          <Input value={chatId} onChange={(event) => setChatId(event.target.value)} placeholder="Telegram chat ID (необязательно)" />
          <div className="flex flex-wrap items-center gap-4">
            <Toggle checked={telegramEnabled} onChange={setTelegramEnabled} label="Telegram включён" />
            <Toggle checked={isAdmin} onChange={setIsAdmin} label="Администратор" />
          </div>
          <Button className="md:col-span-2 md:w-fit" variant="primary" type="submit">Создать</Button>
        </form>
      </Card>
      <Card title="Аккаунты">
        <div className="space-y-3">
          {users.map((user) => (
            <div key={user.id} className="grid gap-3 rounded-md border border-slate-800 p-3 lg:grid-cols-[1fr_auto_1.5fr_auto] lg:items-center">
              <div>
                <div className="font-medium text-slate-100">{user.username}</div>
                <div className="text-xs text-slate-400">{user.telegram_chat_id ? `Telegram: ${user.telegram_chat_id}` : 'Telegram ID не задан'}</div>
              </div>
              <div className="flex gap-2">
                <Badge tone={user.is_active ? 'green' : 'red'}>{user.is_active ? 'Активен' : 'Отключён'}</Badge>
                {user.is_admin && <Badge tone="blue">Админ</Badge>}
              </div>
              <div className="flex flex-wrap gap-2">
                <Input
                  className="min-w-40"
                  defaultValue={user.telegram_chat_id ?? ''}
                  placeholder="Telegram chat ID"
                  onBlur={(event) => {
                    if (event.target.value !== (user.telegram_chat_id ?? '')) {
                      void updateUser(user, { telegram_chat_id: event.target.value }, 'Telegram ID сохранён');
                    }
                  }}
                />
                <Toggle
                  checked={user.telegram_enabled}
                  onChange={(value) => void updateUser(user, { telegram_enabled: value }, 'Настройки Telegram сохранены')}
                  label="Уведомления"
                />
              </div>
              <div className="flex gap-2">
                {user.is_active && <Button variant="danger" onClick={() => void deactivate(user)}>Отключить</Button>}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </Shell>
  );
}
