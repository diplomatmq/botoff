'use client';

import { useCallback, useEffect, useState } from 'react';

import { Shell } from '@/components/Shell';
import { Alert, Badge, Button, Card, Select, Spinner, Td, Th, type Tone } from '@/components/ui';
import { apiFetch, formatDate, formatMoney, positionLabel } from '@/lib/api';
import type { MessageResponse, Offer, Operation, Rule } from '@/lib/types';

function operationStateTone(state: string): Tone {
  if (state === 'done') {
    return 'green';
  }
  if (state === 'failed' || state === 'dead') {
    return 'red';
  }
  if (state === 'running') {
    return 'blue';
  }
  return 'amber';
}

export default function OffersPage() {
  const [offers, setOffers] = useState<Offer[]>([]);
  const [operations, setOperations] = useState<Operation[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [ruleId, setRuleId] = useState('');
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const loadOffers = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (ruleId !== '') {
      params.set('rule_id', ruleId);
    }
    if (status !== '') {
      params.set('status', status);
    }
    try {
      const rows = await apiFetch<Offer[]>(`/api/offers?${params.toString()}`);
      setOffers(rows);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки');
    } finally {
      setLoading(false);
    }
  }, [ruleId, status]);

  const loadOperations = useCallback(async () => {
    try {
      const rows = await apiFetch<Operation[]>('/api/operations');
      setOperations(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки очереди');
    }
  }, []);

  const loadRules = useCallback(async () => {
    try {
      const rows = await apiFetch<Rule[]>('/api/rules');
      setRules(rows);
    } catch {
      setRules([]);
    }
  }, []);

  useEffect(() => {
    void loadOffers();
  }, [loadOffers]);

  useEffect(() => {
    void loadOperations();
    void loadRules();
  }, [loadOperations, loadRules]);

  async function cancelOffer(offer: Offer) {
    if (!window.confirm(`Отменить оффер ${offer.external_offer_id}?`)) {
      return;
    }
    setError(null);
    try {
      const res = await apiFetch<MessageResponse>(`/api/offers/${offer.id}/cancel`, {
        method: 'POST',
      });
      setMessage(res.message);
      await loadOffers();
      await loadOperations();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка отмены');
    }
  }

  async function syncOffer(offer: Offer) {
    setError(null);
    try {
      const res = await apiFetch<MessageResponse>(`/api/offers/${offer.id}/sync`, {
        method: 'POST',
      });
      setMessage(res.message);
      await loadOperations();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка синхронизации');
    }

  }

  async function syncRemoteOffers() {
    setError(null);
    try {
      const res = await apiFetch<MessageResponse>('/api/offers/sync-remote', { method: 'POST' });
      setMessage(res.message);
      await loadOffers();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка синхронизации офферов');
    }

  }

  async function markPurchased(offer: Offer) {
    if (!window.confirm(`Подтвердить покупку по офферу ${offer.external_offer_id}?`)) {
      return;
    }
    setError(null);
    try {
      const res = await apiFetch<MessageResponse>(`/api/offers/${offer.id}/mark-purchased`, {
        method: 'POST',
      });
      setMessage(res.message);
      await loadOffers();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка фиксации покупки');
    }
  }

  async function retryOperation(operation: Operation) {
    setError(null);
    try {
      const res = await apiFetch<MessageResponse>(`/api/operations/${operation.id}/retry`, {
        method: 'POST',
      });
      setMessage(res.message);
      await loadOperations();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка повтора');
    }
  }

  return (
    <Shell>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold text-slate-100">Офферы</h1>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => void syncRemoteOffers()}>
            Синхронизировать с Portals
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              void loadOffers();
              void loadOperations();
            }}
          >
            Обновить
          </Button>
        </div>
      </div>

      {error !== null && <Alert tone="red">{error}</Alert>}
      {message !== null && <Alert tone="green">{message}</Alert>}

      <Card title="Фильтры">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Select value={ruleId} onChange={(event) => setRuleId(event.target.value)}>
            <option value="">Все правила</option>
            {rules.map((rule) => (
              <option key={rule.id} value={rule.id}>
                {rule.name}
              </option>
            ))}
          </Select>
          <Select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">Все статусы</option>
            <option value="pending">В ожидании</option>
            <option value="completed">Завершён</option>
            <option value="canceled">Отменён</option>
            <option value="unknown">Неизвестно</option>
          </Select>
        </div>
      </Card>

      <Card title="Список офферов">
        {loading ? (
          <Spinner className="h-6 w-6" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-800">
                  <Th>Коллекция</Th>
                  <Th>Правило</Th>
                  <Th>Внешний ID</Th>
                  <Th>Сумма</Th>
                  <Th>Статус позиции</Th>
                  <Th>Ранг</Th>
                  <Th>Последнее действие</Th>
                  <Th>Ошибка</Th>
                  <Th>Действия</Th>
                </tr>
              </thead>
              <tbody>
                {offers.map((offer) => (
                  <tr key={offer.id} className="border-b border-slate-800/60">
                    <Td>{offer.collection_name ?? offer.collection_id}</Td>
                    <Td>{offer.rule_name ?? '—'}</Td>
                    <Td>{offer.external_offer_id}</Td>
                    <Td>{formatMoney(offer.amount)}</Td>
                    <Td>{positionLabel(offer.position_status)}</Td>
                    <Td>{offer.position_rank === null ? '—' : offer.position_rank}</Td>
                    <Td>
                      {offer.last_action ?? '—'}
                      <div className="text-xs text-slate-500">{formatDate(offer.last_action_at)}</div>
                    </Td>
                    <Td className="max-w-xs break-words text-red-300">{offer.last_error ?? '—'}</Td>
                    <Td>
                      <div className="flex flex-wrap gap-1">
                        <Button variant="danger" onClick={() => void cancelOffer(offer)}>
                          Отменить
                        </Button>
                        <Button variant="ghost" onClick={() => void syncOffer(offer)}>
                          Синхронизировать
                        </Button>
                        {(offer.status === 'canceled' || offer.status === 'unknown') && (
                          <Button variant="ghost" onClick={() => void markPurchased(offer)}>
                            Подтвердить покупку
                          </Button>
                        )}
                      </div>
                    </Td>
                  </tr>
                ))}
                {offers.length === 0 && (
                  <tr>
                    <Td className="text-slate-400">Офферы не найдены</Td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Очередь операций">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-800">
                <Th>Тип</Th>
                <Th>Состояние</Th>
                <Th>Попытки</Th>
                <Th>Запланировано</Th>
                <Th>Ошибка</Th>
                <Th>Действия</Th>
              </tr>
            </thead>
            <tbody>
              {operations.map((operation) => (
                <tr key={operation.id} className="border-b border-slate-800/60">
                  <Td>{operation.operation_type}</Td>
                  <Td>
                    <Badge tone={operationStateTone(operation.state)}>{operation.state}</Badge>
                  </Td>
                  <Td>
                    {operation.attempts} / {operation.max_attempts}
                  </Td>
                  <Td>{formatDate(operation.scheduled_at)}</Td>
                  <Td className="max-w-xs break-words text-red-300">{operation.last_error ?? '—'}</Td>
                  <Td>
                    {(operation.state === 'failed' || operation.state === 'dead') && (
                      <Button variant="ghost" onClick={() => void retryOperation(operation)}>
                        Повторить
                      </Button>
                    )}
                  </Td>
                </tr>
              ))}
              {operations.length === 0 && (
                <tr>
                  <Td className="text-slate-400">Операций нет</Td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </Shell>
  );
}
