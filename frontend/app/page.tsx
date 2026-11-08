'use client';

import { useCallback, useEffect, useState } from 'react';

import { Shell } from '@/components/Shell';
import { Alert, Badge, Button, Card, Spinner, StatCard, Td, Th, type Tone } from '@/components/ui';
import { apiFetch, formatDate, formatMoney } from '@/lib/api';
import type { DashboardSummary } from '@/lib/types';

function levelTone(level: string): Tone {
  if (level === 'error') {
    return 'red';
  }
  if (level === 'warning') {
    return 'amber';
  }
  return 'blue';
}

function statusTone(status: string): Tone {
  if (status === 'ok') {
    return 'green';
  }
  if (status === 'error') {
    return 'red';
  }
  return 'amber';
}

function ObjectList({ data }: { data: Record<string, unknown> | null }) {
  if (data === null || Object.keys(data).length === 0) {
    return <span className="text-sm text-slate-400">—</span>;
  }
  return (
    <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
      {Object.entries(data).map(([key, value]) => (
        <div key={key} className="flex justify-between gap-2 border-b border-slate-800/60 py-0.5">
          <dt className="text-slate-400">{key}</dt>
          <dd className="text-slate-200">{String(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const summary = await apiFetch<DashboardSummary>('/api/dashboard');
      setData(summary);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => {
      void load();
    }, 10000);
    return () => {
      clearInterval(timer);
    };
  }, [load]);

  useEffect(() => {
    const source = new EventSource('/api/events/stream');
    source.onmessage = () => {
      void load();
    };
    source.addEventListener('update', () => {
      void load();
    });
    source.onerror = () => {};
    return () => {
      source.close();
    };
  }, [load]);

  return (
    <Shell>
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-lg font-semibold text-slate-100">Мониторинг</h1>
        <Button variant="primary" onClick={() => void load()}>
          Обновить
        </Button>
      </div>

      {error !== null && <Alert tone="red">{error}</Alert>}
      {data === null && loading && <Spinner className="h-6 w-6" />}

      {data !== null && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
            <StatCard
              label="Статус API"
              value={data.api_status}
              tone={statusTone(data.api_status)}
              hint={data.api_message ?? formatDate(data.api_last_check)}
            />
            <StatCard label="Воркер" value={data.worker_state} hint={formatDate(data.worker_last_tick)} />
            <StatCard
              label="Режим"
              value={data.mode === 'live' ? 'LIVE' : 'DRY-RUN'}
              tone={data.mode === 'live' ? 'red' : 'blue'}
              hint={data.automation_enabled ? 'Автоматизация включена' : 'Автоматизация выключена'}
            />
            <StatCard label="Активные правила" value={data.active_rules} tone="green" />
            <StatCard label="Активные офферы" value={data.active_offers} tone="blue" />
            <StatCard label="Первое место" value={data.first_place_confirmed} tone="green" />
            <StatCard label="Перебитые" value={data.outbid_offers} tone="amber" />
            <StatCard label="Достигнут лимит" value={data.limit_reached_offers} tone="amber" />
            <StatCard label="Недостаточно средств" value={data.insufficient_funds_offers} tone="red" />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card title="Баланс">
              <div className="grid grid-cols-3 gap-3">
                <StatCard label="Баланс" value={formatMoney(data.balance)} />
                <StatCard label="Заморожено" value={formatMoney(data.frozen_funds)} />
                <StatCard label="Источник" value={data.balance_source} />
              </div>
            </Card>

            <Card title="Очередь операций">
              {Object.keys(data.queue).length === 0 ? (
                <span className="text-sm text-slate-400">Нет операций в очереди</span>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {Object.entries(data.queue).map(([key, value]) => (
                    <Badge key={key} tone="slate">
                      {key}: {value}
                    </Badge>
                  ))}
                </div>
              )}
            </Card>

            <Card title="Лимит запросов">
              <ObjectList data={data.rate_limit} />
            </Card>

            <Card title="Пропускная способность">
              <ObjectList data={data.throughput} />
            </Card>
          </div>

          <Card title="Последние события">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-800">
                    <Th>Время</Th>
                    <Th>Уровень</Th>
                    <Th>Событие</Th>
                    <Th>Сообщение</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_events.map((event) => (
                    <tr key={event.id} className="border-b border-slate-800/60">
                      <Td>{formatDate(event.created_at)}</Td>
                      <Td>
                        <Badge tone={levelTone(event.level)}>{event.level}</Badge>
                      </Td>
                      <Td>{event.action}</Td>
                      <Td>{event.message}</Td>
                    </tr>
                  ))}
                  {data.recent_events.length === 0 && (
                    <tr>
                      <Td className="text-slate-400">Нет событий</Td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </Shell>
  );
}
