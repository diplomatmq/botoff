'use client';

import { useCallback, useEffect, useState, type FormEvent } from 'react';

import { Shell } from '@/components/Shell';
import {
  Alert,
  Badge,
  Button,
  Card,
  Input,
  Select,
  Spinner,
  Toggle,
  type Tone,
} from '@/components/ui';
import { apiFetch, formatDate, formatMoney } from '@/lib/api';
import type {
  Credential,
  MessageResponse,
  Settings as SettingsModel,
  SystemStatus,
} from '@/lib/types';

function credentialTone(status: string): Tone {
  if (status === 'active') {
    return 'green';
  }
  if (status === 'invalid') {
    return 'red';
  }
  return 'slate';
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<SettingsModel | null>(null);
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [minStep, setMinStep] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [token, setToken] = useState('');
  const [label, setLabel] = useState('default');
  const [rateLimit, setRateLimit] = useState('1');
  const [rateLimits, setRateLimits] = useState<Record<string, string>>({});

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');

  const loadSettings = useCallback(async () => {
    try {
      const data = await apiFetch<SettingsModel>('/api/settings');
      setSettings(data);
      setMinStep(data.default_min_step);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки настроек');
    }
  }, []);

  const loadSystem = useCallback(async () => {
    try {
      const data = await apiFetch<SystemStatus>('/api/system/status');
      setSystem(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки диагностики');
    }
  }, []);

  const loadCredentials = useCallback(async () => {
    try {
      const rows = await apiFetch<Credential[]>('/api/credentials');
      setCredentials(rows);
      setRateLimits((current) => {
        const next: Record<string, string> = {};
        for (const row of rows) {
          next[row.id] = current[row.id] ?? String(row.rate_limit_per_second);
        }
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки ключей');
    }
  }, []);

  useEffect(() => {
    void loadSettings();
    void loadSystem();
    void loadCredentials();
  }, [loadSettings, loadSystem, loadCredentials]);

  async function updateSetting(body: Record<string, unknown>) {
    setError(null);
    try {
      const data = await apiFetch<SettingsModel>('/api/settings', {
        method: 'PUT',
        body: JSON.stringify(body),
      });
      setSettings(data);
      setMinStep(data.default_min_step);
      setMessage('Настройки обновлены');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка сохранения');
    }
  }

  async function changeMode(mode: string) {
    if (mode === 'live') {
      const confirmed = window.confirm('Переключить режим в LIVE? Офферы будут отправлены реально.');
      if (!confirmed) {
        return;
      }
      await updateSetting({ mode: 'live', confirm_live: true });
      return;
    }
    await updateSetting({ mode });
  }

  async function releaseEmergency() {
    setError(null);
    try {
      const data = await apiFetch<SettingsModel>('/api/settings/emergency-stop', {
        method: 'POST',
        body: JSON.stringify({ enabled: false }),
      });
      setSettings(data);
      setMessage('Аварийная остановка снята');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка снятия остановки');
    }
  }

  async function addCredential(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      await apiFetch<Credential>('/api/credentials', {
        method: 'POST',
        body: JSON.stringify({
          token,
          label,
          rate_limit_per_second: Number(rateLimit) || 1,
        }),
      });
      setToken('');
      setLabel('default');
      setRateLimit('1');
      setMessage('API-ключ добавлен');
      await loadCredentials();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка добавления ключа');
    }
  }

  async function checkCredential(credential: Credential) {
    setError(null);
    try {
      await apiFetch<Credential>(`/api/credentials/${credential.id}/check`, { method: 'POST' });
      await loadCredentials();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка проверки ключа');
    }
  }

  async function activateCredential(credential: Credential) {
    setError(null);
    try {
      await apiFetch<Credential>(`/api/credentials/${credential.id}/activate`, { method: 'POST' });
      await loadCredentials();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка активации ключа');
    }
  }

  async function saveRateLimit(credential: Credential) {
    setError(null);
    try {
      await apiFetch<Credential>(`/api/credentials/${credential.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ rate_limit_per_second: Number(rateLimits[credential.id]) || 1 }),
      });
      await loadCredentials();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка изменения лимита');
    }
  }

  async function disableCredential(credential: Credential) {
    if (!window.confirm(`Отключить ключ «${credential.label}»?`)) {
      return;
    }
    setError(null);
    try {
      await apiFetch<MessageResponse>(`/api/credentials/${credential.id}`, { method: 'DELETE' });
      await loadCredentials();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка отключения ключа');
    }
  }

  async function resetRateLimit() {
    setError(null);
    try {
      const res = await apiFetch<MessageResponse>('/api/system/rate-limit/reset', { method: 'POST' });
      setMessage(res.message);
      await loadSystem();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка сброса лимита');
    }
  }

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (newPassword.length < 10) {
      setError('Новый пароль должен содержать минимум 10 символов');
      return;
    }
    try {
      const res = await apiFetch<MessageResponse>('/api/auth/password', {
        method: 'POST',
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      setCurrentPassword('');
      setNewPassword('');
      setMessage(res.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка смены пароля');
    }
  }

  return (
    <Shell>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold text-slate-100">Настройки</h1>
        <Button
          variant="ghost"
          onClick={() => {
            void loadSettings();
            void loadSystem();
            void loadCredentials();
          }}
        >
          Обновить
        </Button>
      </div>

      {error !== null && <Alert tone="red">{error}</Alert>}
      {message !== null && <Alert tone="green">{message}</Alert>}

      <Card title="Автоматизация">
        {settings === null ? (
          <Spinner className="h-6 w-6" />
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-4">
              <Toggle
                checked={settings.automation_enabled}
                onChange={(value) => void updateSetting({ automation_enabled: value })}
                label="Автоматизация включена"
              />
              {settings.emergency_stop && (
                <Badge tone="red">
                  Аварийная остановка{settings.emergency_stop_reason === null ? '' : `: ${settings.emergency_stop_reason}`}
                </Badge>
              )}
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <label className="block text-sm">
                <span className="mb-1 block text-xs uppercase text-slate-400">Режим</span>
                <Select value={settings.mode} onChange={(event) => void changeMode(event.target.value)}>
                  <option value="dry_run">DRY-RUN</option>
                  <option value="live">LIVE</option>
                </Select>
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-xs uppercase text-slate-400">Минимальный шаг по умолчанию</span>
                <Input value={minStep} onChange={(event) => setMinStep(event.target.value)} />
              </label>
              <div className="flex items-end gap-2">
                <Button variant="primary" onClick={() => void updateSetting({ default_min_step: minStep })}>
                  Сохранить шаг
                </Button>
              </div>
            </div>

            {settings.emergency_stop && (
              <div className="flex items-center gap-2">
                <Button variant="primary" onClick={() => void releaseEmergency()}>
                  Снять аварийную остановку
                </Button>
              </div>
            )}
          </div>
        )}
      </Card>

      <Card title="API-ключ Portals">
        <form onSubmit={addCredential} className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-4">
          <label className="block text-sm">
            <span className="mb-1 block text-xs uppercase text-slate-400">Токен</span>
            <Input
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              required
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-xs uppercase text-slate-400">Название</span>
            <Input value={label} onChange={(event) => setLabel(event.target.value)} />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-xs uppercase text-slate-400">Лимит, зап/сек</span>
            <Input value={rateLimit} onChange={(event) => setRateLimit(event.target.value)} />
          </label>
          <div className="flex items-end">
            <Button type="submit" variant="primary">
              Добавить ключ
            </Button>
          </div>
        </form>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-800">
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase text-slate-400">Название</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase text-slate-400">Токен</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase text-slate-400">Статус</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase text-slate-400">Sender ID</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase text-slate-400">Лимит</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase text-slate-400">Проверка</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase text-slate-400">Действия</th>
              </tr>
            </thead>
            <tbody>
              {credentials.map((credential) => (
                <tr key={credential.id} className="border-b border-slate-800/60">
                  <td className="px-3 py-2 text-sm text-slate-200">
                    {credential.label}
                    {credential.is_primary && <Badge tone="green">Основной</Badge>}
                  </td>
                  <td className="px-3 py-2 text-sm text-slate-300">{credential.token_hint}</td>
                  <td className="px-3 py-2">
                    <Badge tone={credentialTone(credential.status)}>{credential.status}</Badge>
                  </td>
                  <td className="px-3 py-2 text-sm text-slate-300">
                    {credential.sender_id === null ? '—' : credential.sender_id}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1">
                      <Input
                        value={rateLimits[credential.id] ?? String(credential.rate_limit_per_second)}
                        onChange={(event) =>
                          setRateLimits((current) => ({
                            ...current,
                            [credential.id]: event.target.value,
                          }))
                        }
                        className="w-20"
                      />
                      <Button variant="ghost" onClick={() => void saveRateLimit(credential)}>
                        Сохранить
                      </Button>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-400">
                    {credential.last_check_message ?? '—'}
                    <div className="text-slate-500">{formatDate(credential.last_checked_at)}</div>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1">
                      <Button variant="ghost" onClick={() => void checkCredential(credential)}>
                        Проверить
                      </Button>
                      <Button variant="ghost" onClick={() => void activateCredential(credential)}>
                        Сделать основным
                      </Button>
                      <Button variant="danger" onClick={() => void disableCredential(credential)}>
                        Удалить
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
              {credentials.length === 0 && (
                <tr>
                  <td className="px-3 py-2 text-sm text-slate-400">Ключи не добавлены</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <Card
        title="Диагностика"
        actions={
          <Button variant="ghost" onClick={() => void resetRateLimit()}>
            Сбросить лимит
          </Button>
        }
      >
        {system === null ? (
          <Spinner className="h-6 w-6" />
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div className="text-sm">
              <div className="text-slate-400">База данных</div>
              <Badge tone={system.database === 'ok' ? 'green' : 'red'}>{system.database}</Badge>
            </div>
            <div className="text-sm">
              <div className="text-slate-400">Portals доступен</div>
              <Badge tone={system.portals_reachable ? 'green' : 'red'}>
                {system.portals_reachable ? 'Да' : 'Нет'}
              </Badge>
            </div>
            <div className="text-sm">
              <div className="text-slate-400">Ключ</div>
              <div className="text-slate-200">
                {system.credential_status ?? '—'} {system.credential_hint ?? ''}
              </div>
            </div>
            <div className="text-sm">
              <div className="text-slate-400">Запросов всего</div>
              <div className="text-slate-200">{system.requests_total}</div>
            </div>
            <div className="text-sm">
              <div className="text-slate-400">Ошибок</div>
              <div className="text-slate-200">{system.errors_total}</div>
            </div>
            <div className="text-sm">
              <div className="text-slate-400">Ограничено лимитом</div>
              <div className="text-slate-200">{system.rate_limited_total}</div>
            </div>
            <div className="text-sm">
              <div className="text-slate-400">Остаток лимита</div>
              <div className="text-slate-200">
                {system.remaining_limit === null ? '—' : system.remaining_limit} / {system.limit_per_second ?? '—'}
              </div>
            </div>
            <div className="text-sm">
              <div className="text-slate-400">Последний успех</div>
              <div className="text-slate-200">{formatDate(system.last_success_at)}</div>
            </div>
            <div className="text-sm">
              <div className="text-slate-400">Последняя ошибка</div>
              <div className="text-slate-200">{formatDate(system.last_error_at)}</div>
            </div>
            <div className="text-sm md:col-span-3">
              <div className="text-slate-400">Воркер</div>
              <div className="text-slate-200">
                {Object.keys(system.worker).length === 0
                  ? '—'
                  : Object.entries(system.worker)
                      .map(([key, value]) => `${key}: ${String(value)}`)
                      .join(', ')}
              </div>
            </div>
            <div className="text-sm md:col-span-3">
              <div className="text-slate-400">Очередь</div>
              <div className="flex flex-wrap gap-2">
                {Object.keys(system.queue).length === 0 ? (
                  <span className="text-slate-200">—</span>
                ) : (
                  Object.entries(system.queue).map(([key, value]) => (
                    <Badge key={key} tone="slate">
                      {key}: {value}
                    </Badge>
                  ))
                )}
              </div>
            </div>
            <div className="text-sm">
              <div className="text-slate-400">Несинхронизированные офферы</div>
              <div className="text-slate-200">{system.unsynced_offers}</div>
            </div>
            <div className="text-sm">
              <div className="text-slate-400">Синхронизация</div>
              <div className="text-slate-200">{formatDate(system.offers_synced_at)}</div>
            </div>
            <div className="text-sm">
              <div className="text-slate-400">Версия / окружение</div>
              <div className="text-slate-200">
                {system.app_version} / {system.environment}
              </div>
            </div>
            <div className="text-sm md:col-span-3">
              <div className="text-slate-400">Последнее сообщение об ошибке</div>
              <div className="text-slate-200">{system.last_error_message ?? '—'}</div>
            </div>
          </div>
        )}
      </Card>

      <Card title="Смена пароля">
        <form onSubmit={changePassword} className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <label className="block text-sm">
            <span className="mb-1 block text-xs uppercase text-slate-400">Текущий пароль</span>
            <Input
              type="password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              required
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-xs uppercase text-slate-400">Новый пароль</span>
            <Input
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              minLength={10}
              required
            />
          </label>
          <div className="flex items-end">
            <Button type="submit" variant="primary">
              Изменить пароль
            </Button>
          </div>
        </form>
      </Card>

      {settings !== null && (
        <p className="text-xs text-slate-500">
          Минимальный шаг по умолчанию: {formatMoney(settings.default_min_step)}
        </p>
      )}
    </Shell>
  );
}
