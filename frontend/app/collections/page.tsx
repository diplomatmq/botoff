'use client';

import { useCallback, useEffect, useState } from 'react';

import { Shell } from '@/components/Shell';
import { Alert, Badge, Button, Card, Input, Select, Spinner, Td, Th } from '@/components/ui';
import { apiFetch, formatDate, formatMoney } from '@/lib/api';
import type { Collection, CollectionModel, MessageResponse } from '@/lib/types';

export default function CollectionsPage() {
  const [items, setItems] = useState<Collection[]>([]);
  const [search, setSearch] = useState('');
  const [onlyOffers, setOnlyOffers] = useState(false);
  const [sortBy, setSortBy] = useState('name');
  const [sortOrder, setSortOrder] = useState('asc');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [selected, setSelected] = useState<Collection | null>(null);
  const [models, setModels] = useState<CollectionModel[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (search.trim().length > 0) {
      params.set('search', search.trim());
    }
    if (onlyOffers) {
      params.set('only_offers', 'true');
    }
    params.set('sort_by', sortBy);
    params.set('sort_order', sortOrder);
    try {
      const rows = await apiFetch<Collection[]>(`/api/collections?${params.toString()}`);
      setItems(rows);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки');
    } finally {
      setLoading(false);
    }
  }, [search, onlyOffers, sortBy, sortOrder]);

  useEffect(() => {
    void load();
  }, [load]);

  async function refreshCatalog() {
    setMessage(null);
    setError(null);
    try {
      const res = await apiFetch<MessageResponse>('/api/collections/refresh', { method: 'POST' });
      setMessage(res.message);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка обновления');
    }
  }

  async function loadModels(collection: Collection) {
    setSelected(collection);
    setModels([]);
    setModelsLoading(true);
    try {
      const rows = await apiFetch<CollectionModel[]>(`/api/collections/${collection.id}/models`);
      setModels(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки моделей');
    } finally {
      setModelsLoading(false);
    }
  }

  async function refreshModels() {
    if (selected === null) {
      return;
    }
    setModelsLoading(true);
    try {
      const res = await apiFetch<MessageResponse>(
        `/api/collections/${selected.id}/models/refresh`,
        { method: 'POST' },
      );
      setMessage(res.message);
      const rows = await apiFetch<CollectionModel[]>(`/api/collections/${selected.id}/models`);
      setModels(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка обновления моделей');
    } finally {
      setModelsLoading(false);
    }
  }

  return (
    <Shell>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold text-slate-100">Коллекции</h1>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" onClick={() => void load()}>
            Обновить
          </Button>
          <Button variant="primary" onClick={() => void refreshCatalog()}>
            Обновить каталог
          </Button>
        </div>
      </div>

      {error !== null && <Alert tone="red">{error}</Alert>}
      {message !== null && <Alert tone="green">{message}</Alert>}

      <Card
        title="Фильтры"
        actions={
          <span className="text-xs text-slate-400">Найдено: {items.length}</span>
        }
      >
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <Input
            placeholder="Поиск по названию"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <Select value={sortBy} onChange={(event) => setSortBy(event.target.value)}>
            <option value="name">Сортировка по названию</option>
            <option value="floor_price">Сортировка по полу</option>
          </Select>
          <Select value={sortOrder} onChange={(event) => setSortOrder(event.target.value)}>
            <option value="asc">По возрастанию</option>
            <option value="desc">По убыванию</option>
          </Select>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={onlyOffers}
              onChange={(event) => setOnlyOffers(event.target.checked)}
              className="h-4 w-4 rounded border-slate-700 bg-slate-950"
            />
            Только с офферами
          </label>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <Card title="Список коллекций">
            {loading ? (
              <Spinner className="h-6 w-6" />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-slate-800">
                      <Th>Коллекция</Th>
                      <Th>Floor</Th>
                      <Th>Макс. оффер</Th>
                      <Th>Моделей</Th>
                      <Th>Офферы</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => (
                      <tr
                        key={item.id}
                        onClick={() => void loadModels(item)}
                        className={`cursor-pointer border-b border-slate-800/60 hover:bg-slate-800/50 ${
                          selected?.id === item.id ? 'bg-slate-800/60' : ''
                        }`}
                      >
                        <Td>
                          <div className="flex items-center gap-2">
                            {item.photo_url ? (
                              <img src={item.photo_url} alt="" className="h-10 w-10 rounded object-cover" />
                            ) : (
                              <div className="h-10 w-10 rounded bg-slate-800" />
                            )}
                            <span>{item.name}</span>
                          </div>
                        </Td>
                        <Td>{formatMoney(item.floor_price)}</Td>
                        <Td>{formatMoney(item.max_offer)}</Td>
                        <Td>{item.models_count}</Td>
                        <Td>
                          <Badge tone={item.offers_supported ? 'green' : 'slate'}>
                            {item.offers_supported ? 'Да' : 'Нет'}
                          </Badge>
                        </Td>
                      </tr>
                    ))}
                    {items.length === 0 && (
                      <tr>
                        <Td className="text-slate-400">Коллекции не найдены</Td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>

        <div>
          <Card
            title={selected !== null ? `Модели: ${selected.name}` : 'Модели'}
            actions={
              selected !== null ? (
                <Button variant="ghost" onClick={() => void refreshModels()}>
                  Обновить модели
                </Button>
              ) : undefined
            }
          >
            {selected === null ? (
              <span className="text-sm text-slate-400">Выберите коллекцию в списке</span>
            ) : modelsLoading ? (
              <Spinner className="h-6 w-6" />
            ) : (
              <div className="max-h-96 overflow-y-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-slate-800">
                      <Th>Модель</Th>
                      <Th>Floor</Th>
                      <Th>Макс. оффер</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {models.map((model) => (
                      <tr key={model.name} className="border-b border-slate-800/60">
                        <Td>
                          <div className="flex items-center gap-2">
                            {model.photo_url ? (
                              <img src={model.photo_url} alt="" className="h-9 w-9 rounded object-cover" />
                            ) : (
                              <div className="h-9 w-9 rounded bg-slate-800" />
                            )}
                            <span>{model.name}</span>
                          </div>
                        </Td>
                        <Td>{formatMoney(model.floor_price)}</Td>
                        <Td>{formatMoney(model.max_offer)}</Td>
                      </tr>
                    ))}
                    {models.length === 0 && (
                      <tr>
                        <Td className="text-slate-400">Модели не найдены</Td>
                      </tr>
                    )}
                  </tbody>
                </table>
                <p className="mt-2 text-xs text-slate-500">
                  Обновлено: {formatDate(selected.updated_at)}
                </p>
              </div>
            )}
          </Card>
        </div>
      </div>
    </Shell>
  );
}
