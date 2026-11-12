'use client';

import { useEffect, useMemo, useState } from 'react';

import { Alert, Button, Card, Input, Select, Spinner, Td, Th } from '@/components/ui';
import { Shell } from '@/components/Shell';
import { apiFetch } from '@/lib/api';
import type { Collection, CollectionAttribute, Offer, Settings } from '@/lib/types';

function scopeLabel(scope: Record<string, unknown>): string | null {
  const parts: string[] = [];
  for (const [label, key] of [['Модель', 'models'], ['Фон', 'backdrops'], ['Символ', 'symbols']] as const) {
    const values = scope[key];
    if (Array.isArray(values) && values.length > 0) {
      parts.push(`${label}: ${values.map(String).join(', ')}`);
    }
  }
  return parts.length > 0 ? parts.join(' · ') : null;
}

function normalizedList(values: string[] | undefined): string[] {
  return [...(values ?? [])].sort();
}

function normalizedNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export default function TraderPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [spread, setSpread] = useState('0');
  const [maxRebids, setMaxRebids] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [offers, setOffers] = useState<Offer[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [selectedCollectionId, setSelectedCollectionId] = useState('');
  const [models, setModels] = useState<CollectionAttribute[]>([]);
  const [backdrops, setBackdrops] = useState<CollectionAttribute[]>([]);
  const [backdropsLoading, setBackdropsLoading] = useState(false);
  const [backdropsError, setBackdropsError] = useState<string | null>(null);
  const [symbols, setSymbols] = useState<CollectionAttribute[]>([]);
  const [excludedCollections, setExcludedCollections] = useState<string[]>([]);
  const [excludedModels, setExcludedModels] = useState<string[]>([]);
  const [excludedBackdrops, setExcludedBackdrops] = useState<string[]>([]);
  const [excludedSymbols, setExcludedSymbols] = useState<string[]>([]);
  const [collectionSearch, setCollectionSearch] = useState('');
  const [modelSearch, setModelSearch] = useState('');
  const [backdropSearch, setBackdropSearch] = useState('');
  const [symbolSearch, setSymbolSearch] = useState('');

  async function load() {
    try {
      const value = await apiFetch<Settings>('/api/settings');
      setSettings(value);
      setEnabled(value.smart_trader_enabled);
      setSpread(value.smart_trader_min_spread_percent);
      setMaxRebids(value.smart_trader_max_rebids_per_offer === null ? '' : String(value.smart_trader_max_rebids_per_offer));
      setExcludedCollections(value.smart_trader_excluded_collections);
      setExcludedModels(value.smart_trader_excluded_models);
      setExcludedBackdrops(value.smart_trader_excluded_backdrops);
      setExcludedSymbols(value.smart_trader_excluded_symbols || []);
      const availableCollections = await apiFetch<Collection[]>('/api/collections?only_offers=true');
      setCollections(availableCollections);
      setSelectedCollectionId((current) => (
        value.smart_trader_attribute_collection_id
        && !value.smart_trader_excluded_collections.includes(value.smart_trader_attribute_collection_id)
        && availableCollections.some((collection) => collection.id === value.smart_trader_attribute_collection_id)
          ? value.smart_trader_attribute_collection_id
          : availableCollections.find((collection) => !value.smart_trader_excluded_collections.includes(collection.id))?.id || ''
      ));
      setOffers(await apiFetch<Offer[]>('/api/offers?source=smart_trader'));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки настроек трейдера');
    }
  }

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!selectedCollectionId) {
      setModels([]);
      setBackdrops([]);
      setBackdropsError(null);
      setBackdropsLoading(false);
      setSymbols([]);
      return;
    }
    let active = true;
    setBackdropsLoading(true);
    setBackdropsError(null);
    void Promise.all([
      apiFetch<CollectionAttribute[]>(`/api/collections/${selectedCollectionId}/models`).catch(() => []),
      apiFetch<CollectionAttribute[]>(`/api/collections/${selectedCollectionId}/symbols`).catch(() => []),
    ]).then(([collectionModels, collectionSymbols]) => {
      if (active) {
        setModels(collectionModels.sort((left, right) => left.name.localeCompare(right.name)));
        setSymbols(collectionSymbols.sort((left, right) => left.name.localeCompare(right.name)));
      }
    });
    void apiFetch<CollectionAttribute[]>(`/api/collections/${selectedCollectionId}/backdrops`)
      .then((collectionBackdrops) => {
        if (active) {
          setBackdrops(collectionBackdrops.sort((left, right) => left.name.localeCompare(right.name)));
        }
      })
      .catch((err) => {
        if (active) {
          setBackdrops([]);
          setBackdropsError(err instanceof Error ? err.message : 'Не удалось загрузить фоны');
        }
      })
      .finally(() => {
        if (active) {
          setBackdropsLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [selectedCollectionId]);

  const selectableCollections = collections.filter(
    (collection) => !excludedCollections.includes(collection.id),
  );
  const visibleCollections = collections.filter((collection) =>
    collection.name.toLowerCase().includes(collectionSearch.trim().toLowerCase()),
  );
  const visibleModels = models.filter((model) =>
    model.name.toLowerCase().includes(modelSearch.trim().toLowerCase()),
  );
  const visibleBackdrops = backdrops.filter((backdrop) =>
    backdrop.name.toLowerCase().includes(backdropSearch.trim().toLowerCase()),
  );
  const visibleSymbols = symbols.filter((symbol) =>
    symbol.name.toLowerCase().includes(symbolSearch.trim().toLowerCase()),
  );
  const savedState = useMemo(() => JSON.stringify({
    enabled: settings?.smart_trader_enabled,
    spread: normalizedNumber(settings?.smart_trader_min_spread_percent) ?? 0,
    maxRebids: normalizedNumber(settings?.smart_trader_max_rebids_per_offer),
    excludedCollections: normalizedList(settings?.smart_trader_excluded_collections),
    excludedModels: normalizedList(settings?.smart_trader_excluded_models),
    excludedBackdrops: normalizedList(settings?.smart_trader_excluded_backdrops),
    excludedSymbols: normalizedList(settings?.smart_trader_excluded_symbols),
    selectedCollectionId: settings?.smart_trader_attribute_collection_id,
  }), [settings]);
  const currentState = JSON.stringify({
    enabled,
    spread: normalizedNumber(spread) ?? 0,
    maxRebids: normalizedNumber(maxRebids),
    excludedCollections: normalizedList(excludedCollections),
    excludedModels: normalizedList(excludedModels),
    excludedBackdrops: normalizedList(excludedBackdrops),
    excludedSymbols: normalizedList(excludedSymbols),
    selectedCollectionId,
  });
  const hasUnsavedChanges = settings !== null && savedState !== currentState;

  async function save() {
    setError(null);
    try {
      const value = await apiFetch<Settings>('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({
          smart_trader_enabled: enabled,
          smart_trader_min_spread_percent: spread || '0',
          smart_trader_max_rebids_per_offer: maxRebids === '' ? null : Number(maxRebids),
          smart_trader_excluded_collections: excludedCollections,
          smart_trader_excluded_models: excludedModels,
          smart_trader_excluded_backdrops: excludedBackdrops,
          smart_trader_excluded_symbols: excludedSymbols,
          smart_trader_attribute_collection_id: selectedCollectionId || null,
        }),
      });
      setSettings(value);
      setMessage('Настройки трейдера сохранены');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка сохранения');
    }
  }

  async function cancelOffer(offer: Offer) {
    setError(null);
    try {
      await apiFetch(`/api/offers/${offer.id}/cancel`, { method: 'POST' });
      setMessage('Оффер поставлен на отмену');
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка отмены оффера');
    }
  }

  return (
    <Shell>
      <h1 className="text-lg font-semibold text-slate-100">Умный трейдер</h1>
      {error !== null && <Alert tone="red">{error}</Alert>}
      {message !== null && <Alert tone="green">{message}</Alert>}
      <Card title="Глобальный трейдер">
        {settings === null ? <Spinner className="h-6 w-6" /> : (
          <div className="w-full max-w-none space-y-4">
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
              Включить глобального трейдера
            </label>
            {hasUnsavedChanges && (
              <p className="text-sm text-amber-300">
                Есть несохранённые изменения. Трейдер применит их только после нажатия «Сохранить».
              </p>
            )}
            <p className="text-sm text-slate-400">
              Трейдер не использует правила и не требует выбора коллекции. Он анализирует все доступные коллекции,
              баланс и выбирает максимальную абсолютную разницу между floor и лучшим оффером. Одновременно
              удерживается максимум один оффер.
            </p>
            <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Минимальный разрыв от floor, %</span>
              <Input type="number" min="0" max="100" step="0.01" value={spread} onChange={(event) => setSpread(event.target.value)} />
              <span className="mt-1 block text-xs text-slate-500">0% означает отсутствие минимального порога.</span>
            </label>
            <div className="space-y-2">
              <span className="block text-xs uppercase text-slate-400">Исключить коллекции</span>
              <Input placeholder="Поиск коллекции" value={collectionSearch} onChange={(event) => setCollectionSearch(event.target.value)} />
              <div className="max-h-64 space-y-1 overflow-y-auto rounded border border-slate-800 bg-slate-900/50 p-2">
                {visibleCollections.map((collection) => {
                  const selected = excludedCollections.includes(collection.id);
                  return (
                    <button
                      key={collection.id}
                      type="button"
                      onClick={() => {
                        setExcludedCollections((current) => selected
                          ? current.filter((id) => id !== collection.id)
                          : [...current, collection.id]);
                        if (!selected && selectedCollectionId === collection.id) {
                          setSelectedCollectionId('');
                        }
                      }}
                      className={`flex w-full items-center gap-2 rounded border px-2 py-1 text-left text-xs ${
                        selected ? 'border-red-500 bg-red-700 text-white' : 'border-slate-700 bg-slate-800 text-slate-300'
                      }`}
                    >
                    {collection.photo_url ? <img src={collection.photo_url} alt="" className="h-8 w-8 rounded object-cover" /> : <span className="h-8 w-8 rounded bg-slate-700" />}
                    <span>{collection.name}</span>
                    </button>
                  );
                })}
              </div>
            </div>
            <label className="block max-w-xl text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Коллекция для выбора моделей и фонов</span>
              <Input className="mb-2" placeholder="Поиск коллекции" value={collectionSearch} onChange={(event) => setCollectionSearch(event.target.value)} />
              <div className="max-h-64 space-y-1 overflow-y-auto rounded border border-slate-800 bg-slate-900/50 p-2">
                {selectableCollections.map((collection) => (
                  <button key={collection.id} type="button" onClick={() => setSelectedCollectionId(collection.id)}
                    className={`flex w-full items-center gap-2 rounded border px-2 py-1 text-left text-xs ${selectedCollectionId === collection.id ? 'border-blue-500 bg-blue-600 text-white' : 'border-slate-700 bg-slate-800 text-slate-300'}`}>
                    {collection.photo_url ? <img src={collection.photo_url} alt="" className="h-8 w-8 rounded object-cover" /> : <span className="h-8 w-8 rounded bg-slate-700" />}
                    <span>{collection.name}</span>
                  </button>
                ))}
              </div>
            </label>
            <div className="grid w-full grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="space-y-2">
                <span className="block text-xs uppercase text-slate-400">Исключить модели выбранной коллекции</span>
                <Input placeholder="Поиск модели" value={modelSearch} onChange={(event) => setModelSearch(event.target.value)} />
                <div className="max-h-64 space-y-1 overflow-y-auto rounded border border-slate-800 bg-slate-900/50 p-2">
                  {visibleModels.map((model) => {
                    const key = `${selectedCollectionId}:${model.name}`;
                    const selected = excludedModels.includes(key) || excludedModels.includes(model.name);
                    return (
                      <button
                        key={model.name}
                        type="button"
                        onClick={() => setExcludedModels((current) => selected
                          ? current.filter((name) => name !== key && name !== model.name)
                          : [...current.filter((name) => name !== model.name), key])}
                        className={`flex w-full items-center gap-2 rounded border px-2 py-1 text-left text-xs ${
                          selected ? 'border-red-500 bg-red-700 text-white' : 'border-slate-700 bg-slate-800 text-slate-300'
                        }`}
                      >
                        {model.photo_url ? <img src={model.photo_url} alt="" className="h-8 w-8 rounded object-cover" /> : <span className="h-8 w-8 rounded bg-slate-700" />}
                        <span className="flex-1">{model.name}</span>
                        {model.floor_price && <span className="opacity-60">Floor: {model.floor_price}</span>}
                      </button>
                    );
                  })}
                  {models.length === 0 && <span className="text-xs italic text-slate-500">{selectedCollectionId ? 'Модели не загружены' : 'Сначала выберите коллекцию'}</span>}
                </div>
              </div>
              <div className="space-y-2">
                <span className="block text-xs uppercase text-slate-400">Исключить фоны выбранной коллекции</span>
                <Input placeholder="Поиск фона" value={backdropSearch} onChange={(event) => setBackdropSearch(event.target.value)} />
                <div className="max-h-64 space-y-1 overflow-y-auto rounded border border-slate-800 bg-slate-900/50 p-2">
                  {visibleBackdrops.map((backdrop) => {
                    const key = `${selectedCollectionId}:${backdrop.name}`;
                    const selected = excludedBackdrops.includes(key) || excludedBackdrops.includes(backdrop.name);
                    return (
                      <button
                        key={backdrop.name}
                        type="button"
                        onClick={() => setExcludedBackdrops((current) => selected
                          ? current.filter((name) => name !== key && name !== backdrop.name)
                          : [...current.filter((name) => name !== backdrop.name), key])}
                        className={`flex w-full items-center gap-2 rounded border px-2 py-1 text-left text-xs ${
                          selected ? 'border-red-500 bg-red-700 text-white' : 'border-slate-700 bg-slate-800 text-slate-300'
                        }`}
                      >
                        {backdrop.photo_url ? <img src={backdrop.photo_url} alt="" className="h-8 w-8 rounded object-cover" /> : <span className="h-8 w-8 rounded bg-slate-700" />}
                        <span className="flex-1">{backdrop.name}</span>
                        {backdrop.floor_price && <span className="opacity-60">Floor: {backdrop.floor_price}</span>}
                      </button>
                    );
                  })}
                  {backdrops.length === 0 && (
                    <span className="text-xs italic text-slate-500">
                      {backdropsError
                        ? `Ошибка загрузки фонов: ${backdropsError}`
                        : backdropsLoading
                          ? 'Загрузка фонов из Portals...'
                          : selectedCollectionId
                            ? 'Portals не вернул фоны для этой коллекции'
                            : 'Сначала выберите коллекцию'}
                    </span>
                  )}
                </div>
              </div>
              <div className="space-y-2">
                <span className="block text-xs uppercase text-slate-400">Исключить символы выбранной коллекции</span>
                <Input placeholder="Поиск символа" value={symbolSearch} onChange={(event) => setSymbolSearch(event.target.value)} />
                <div className="max-h-64 space-y-1 overflow-y-auto rounded border border-slate-800 bg-slate-900/50 p-2">
                  {visibleSymbols.map((symbol) => {
                    const key = `${selectedCollectionId}:${symbol.name}`;
                    const selected = excludedSymbols.includes(key) || excludedSymbols.includes(symbol.name);
                    return (
                      <button
                        key={symbol.name}
                        type="button"
                        onClick={() => setExcludedSymbols((current) => selected
                          ? current.filter((name) => name !== key && name !== symbol.name)
                          : [...current.filter((name) => name !== symbol.name), key])}
                        className={`flex w-full items-center gap-2 rounded border px-2 py-1 text-left text-xs ${
                          selected ? 'border-red-500 bg-red-700 text-white' : 'border-slate-700 bg-slate-800 text-slate-300'
                        }`}
                      >
                        {symbol.photo_url ? <img src={symbol.photo_url} alt="" className="h-8 w-8 rounded object-cover" /> : <span className="h-8 w-8 rounded bg-slate-700" />}
                        <span className="flex-1">{symbol.name}</span>
                        {symbol.floor_price && <span className="opacity-60">Floor: {symbol.floor_price}</span>}
                      </button>
                    );
                  })}
                  {symbols.length === 0 && <span className="text-xs italic text-slate-500">{selectedCollectionId ? 'Символы не загружены' : 'Сначала выберите коллекцию'}</span>}
                </div>
              </div>
            </div>
            <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Макс. перебивов на один гифт</span>
              <Input type="number" min="0" step="1" value={maxRebids} onChange={(event) => setMaxRebids(event.target.value)} placeholder="Пусто = без лимита" />
              <span className="mt-1 block text-xs text-slate-500">0 = без лимита. После лимита трейдер отменяет свой оффер на этот гифт.</span>
            </label>
            <Button variant="primary" onClick={() => void save()}>Сохранить</Button>
          </div>
        )}
      </Card>
      <Card title="Офферы глобального трейдера">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead><tr className="border-b border-slate-800"><Th>Коллекция</Th><Th>Модель / атрибуты</Th><Th>Сумма</Th><Th>Позиция</Th><Th>Перебивов</Th><Th>Статус</Th><Th>Причина</Th><Th>Действие</Th></tr></thead>
            <tbody>
              {offers.map((offer) => (
                <tr key={offer.id} className="border-b border-slate-800/60">
                  <Td>{offer.collection_name ?? offer.collection_id}</Td>
                  <Td>{scopeLabel(offer.scope) ?? 'Вся коллекция'}</Td>
                  <Td>{offer.amount}</Td>
                  <Td>{offer.position_rank === null ? '—' : offer.position_rank}</Td>
                  <Td>{offer.rebid_count}</Td>
                  <Td>{offer.status}</Td>
                  <Td className="max-w-xs break-words text-amber-300">{offer.last_error ?? '—'}</Td>
                  <Td>
                    {offer.status === 'pending' && (
                      <Button variant="danger" onClick={() => void cancelOffer(offer)}>
                        Отменить
                      </Button>
                    )}
                  </Td>
                </tr>
              ))}
              {offers.length === 0 && <tr><Td className="text-slate-400">Офферы трейдера не выставлены</Td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
    </Shell>
  );
}
