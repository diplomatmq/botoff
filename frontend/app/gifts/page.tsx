'use client';

import { useCallback, useEffect, useState } from 'react';

import { Shell } from '@/components/Shell';
import { Alert, Button, Card, Spinner, Td, Th } from '@/components/ui';
import { apiFetch, formatDate, formatMoney } from '@/lib/api';
import type { PurchasedGift } from '@/lib/types';

export default function GiftsPage() {
  const [gifts, setGifts] = useState<PurchasedGift[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setGifts(await apiFetch<PurchasedGift[]>('/api/offers/purchased'));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки подарков');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Shell>
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-lg font-semibold text-slate-100">Мои подарки</h1>
        <Button variant="ghost" onClick={() => void load()}>Обновить</Button>
      </div>
      {error !== null && <Alert tone="red">{error}</Alert>}
      <Card title="Подарки, купленные по моим офферам">
        {loading ? <Spinner className="h-6 w-6" /> : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead><tr className="border-b border-slate-800">
                <Th>Коллекция</Th><Th>Подарок</Th><Th>Цена покупки</Th><Th>Дата</Th>
              </tr></thead>
              <tbody>
                {gifts.map((gift) => (
                  <tr key={gift.id} className="border-b border-slate-800/60">
                    <Td>{gift.collection_name}</Td>
                    <Td>
                      {gift.portals_url ? (
                        <a
                          className="text-cyan-300 underline"
                          href={gift.portals_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {gift.gift_id ?? 'Открыть подарок'}
                        </a>
                      ) : (gift.gift_id ?? 'ID не передан Portals')}
                    </Td>
                    <Td>{formatMoney(gift.amount)}</Td>
                    <Td>{formatDate(gift.purchased_at)}</Td>
                  </tr>
                ))}
                {gifts.length === 0 && <tr><Td className="text-slate-400">Покупок пока не зафиксировано</Td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </Shell>
  );
}
