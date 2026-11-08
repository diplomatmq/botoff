'use client';

import { useCallback, useEffect, useState } from 'react';

import { Shell } from '@/components/Shell';
import { Alert, Badge, Button, Card, Input, Select, Spinner, Td, Th, type Tone } from '@/components/ui';
import { apiFetch, formatDate } from '@/lib/api';
import type { HistoryEntry } from '@/lib/types';

function levelTone(level: string): Tone {
  if (level === 'error') {
    return 'red';
  }
  if (level === 'warning') {
    return 'amber';
  }
  return 'blue';
}

export default function HistoryPage() {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [level, setLevel] = useState('');
  const [action, setAction] = useState('');
  const [limit, setLimit] = useState('100');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (level !== '') {
      params.set('level', level);
    }
    if (action.trim() !== '') {
      params.set('action', action.trim());
    }
    params.set('limit', limit === '' ? '100' : limit);
    try {
      const rows = await apiFetch<HistoryEntry[]>(`/api/history?${params.toString()}`);
      setEntries(rows);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки');
    } finally {
      setLoading(false);
    }
  }, [level, action, limit]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Shell>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold text-slate-100">История</h1>
        <Button variant="ghost" onClick={() => void load()}>
          Обновить
        </Button>
      </div>

      {error !== null && <Alert tone="red">{error}</Alert>}

      <Card title="Фильтры">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Select value={level} onChange={(event) => setLevel(event.target.value)}>
            <option value="">Все уровни</option>
            <option value="info">Информация</option>
            <option value="warning">Предупреждение</option>
            <option value="error">Ошибка</option>
          </Select>
          <Input
            placeholder="Действие"
            value={action}
            onChange={(event) => setAction(event.target.value)}
          />
          <Input
            placeholder="Лимит"
            value={limit}
            onChange={(event) => setLimit(event.target.value)}
          />
        </div>
      </Card>

      <Card title="Записи">
        {loading ? (
          <Spinner className="h-6 w-6" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-800">
                  <Th>Время</Th>
                  <Th>Уровень</Th>
                  <Th>Автор</Th>
                  <Th>Действие</Th>
                  <Th>Сообщение</Th>
                  <Th>Объект</Th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.id} className="border-b border-slate-800/60">
                    <Td>{formatDate(entry.created_at)}</Td>
                    <Td>
                      <Badge tone={levelTone(entry.level)}>{entry.level}</Badge>
                    </Td>
                    <Td>{entry.actor}</Td>
                    <Td>{entry.action}</Td>
                    <Td>{entry.message}</Td>
                    <Td>
                      {entry.entity_type === null
                        ? '—'
                        : `${entry.entity_type}${entry.entity_id === null ? '' : `: ${entry.entity_id}`}`}
                    </Td>
                  </tr>
                ))}
                {entries.length === 0 && (
                  <tr>
                    <Td className="text-slate-400">Записей нет</Td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </Shell>
  );
}
