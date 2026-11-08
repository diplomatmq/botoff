'use client';

import { useCallback, useEffect, useState, type FormEvent } from 'react';

import { Shell } from '@/components/Shell';
import { Alert, Badge, Button, Card, Input, Spinner, Toggle, type Tone } from '@/components/ui';
import { apiFetch, formatDate } from '@/lib/api';
import type { MessageResponse, NotificationItem, NotificationSettings } from '@/lib/types';

function levelTone(level: string): Tone {
  if (level === 'error') {
    return 'red';
  }
  if (level === 'warning') {
    return 'amber';
  }
  return 'blue';
}

export default function NotificationsPage() {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [settings, setSettings] = useState<NotificationSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [chatId, setChatId] = useState('');
  const [minInterval, setMinInterval] = useState('0');
  const [maxPerHour, setMaxPerHour] = useState('10');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await apiFetch<NotificationItem[]>('/api/notifications');
      setItems(rows);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadSettings = useCallback(async () => {
    try {
      const data = await apiFetch<NotificationSettings>('/api/notifications/settings');
      setSettings(data);
      setChatId(data.telegram_chat_id ?? '');
      setMinInterval(String(data.min_interval_seconds));
      setMaxPerHour(String(data.max_per_hour));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки настроек');
    }
  }, []);

  useEffect(() => {
    void load();
    void loadSettings();
  }, [load, loadSettings]);

  async function markRead(item: NotificationItem) {
    setError(null);
    try {
      await apiFetch<MessageResponse>(`/api/notifications/${item.id}/read`, { method: 'POST' });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка отметки');
    }
  }

  async function markAllRead() {
    setError(null);
    try {
      const res = await apiFetch<MessageResponse>('/api/notifications/read-all', { method: 'POST' });
      setMessage(res.message);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка отметки');
    }
  }

  async function saveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (settings === null) {
      return;
    }
    setError(null);
    try {
      const data = await apiFetch<NotificationSettings>('/api/notifications/settings', {
        method: 'PUT',
        body: JSON.stringify({
          in_app_enabled: settings.in_app_enabled,
          telegram_enabled: settings.telegram_enabled,
          telegram_chat_id: chatId,
          min_interval_seconds: Number(minInterval) || 0,
          max_per_hour: Number(maxPerHour) || 1,
        }),
      });
      setSettings(data);
      setChatId(data.telegram_chat_id ?? '');
      setMinInterval(String(data.min_interval_seconds));
      setMaxPerHour(String(data.max_per_hour));
      setMessage('Настройки уведомлений сохранены');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка сохранения');
    }
  }

  return (
    <Shell>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold text-slate-100">Уведомления</h1>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" onClick={() => void load()}>
            Обновить
          </Button>
          <Button variant="primary" onClick={() => void markAllRead()}>
            Прочитать все
          </Button>
        </div>
      </div>

      {error !== null && <Alert tone="red">{error}</Alert>}
      {message !== null && <Alert tone="green">{message}</Alert>}

      <Card title="Список уведомлений">
        {loading ? (
          <Spinner className="h-6 w-6" />
        ) : (
          <ul className="space-y-2">
            {items.map((item) => (
              <li
                key={item.id}
                className={`rounded-md border p-3 ${
                  item.read_at === null ? 'border-slate-700 bg-slate-800/40' : 'border-slate-800'
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={levelTone(item.level)}>{item.level}</Badge>
                    <span className="font-medium text-slate-100">{item.title}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-500">{formatDate(item.created_at)}</span>
                    {item.read_at === null && (
                      <Button variant="ghost" onClick={() => void markRead(item)}>
                        Прочитано
                      </Button>
                    )}
                  </div>
                </div>
                <p className="mt-1 text-sm text-slate-300">{item.message}</p>
              </li>
            ))}
            {items.length === 0 && <li className="text-sm text-slate-400">Уведомлений нет</li>}
          </ul>
        )}
      </Card>

      <Card title="Настройки уведомлений">
        {settings === null ? (
          <Spinner className="h-6 w-6" />
        ) : (
          <form onSubmit={saveSettings} className="space-y-3">
            <div className="flex flex-wrap gap-4">
              <Toggle
                checked={settings.in_app_enabled}
                onChange={(value) => setSettings({ ...settings, in_app_enabled: value })}
                label="В приложении"
              />
              <Toggle
                checked={settings.telegram_enabled}
                onChange={(value) => setSettings({ ...settings, telegram_enabled: value })}
                label="Telegram"
              />
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <label className="block text-sm">
                <span className="mb-1 block text-xs uppercase text-slate-400">Telegram Chat ID</span>
                <Input value={chatId} onChange={(event) => setChatId(event.target.value)} />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-xs uppercase text-slate-400">Мин. интервал, сек</span>
                <Input value={minInterval} onChange={(event) => setMinInterval(event.target.value)} />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-xs uppercase text-slate-400">Максимум в час</span>
                <Input value={maxPerHour} onChange={(event) => setMaxPerHour(event.target.value)} />
              </label>
            </div>
            <div className="flex justify-end">
              <Button type="submit" variant="primary">
                Сохранить
              </Button>
            </div>
          </form>
        )}
      </Card>
    </Shell>
  );
}
