'use client';

import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';

import { Shell } from '@/components/Shell';
import { Alert, Badge, Button, Card, Input, Modal, Select, Spinner, Td, Th, Toggle, type Tone } from '@/components/ui';
import { apiFetch, formatDate, formatMoney, positionLabel, ruleStateLabel } from '@/lib/api';
import type { Collection, CollectionAttribute, CollectionModel, Credential, DryRunPreview, MessageResponse, PreviewScope, Rule } from '@/lib/types';

interface RuleForm {
  name: string;
  collection_id: string;
  scope_mode: string;
  models: string;
  backdrops: string;
  excluded_backdrops: string;
  symbols: string;
  scope_guard: boolean;
  strategy: string;
  hold_first_place: boolean;
  pause_on_uncertainty: boolean;
  discount_percent: string;
  max_price_percent: string;
  fixed_price: string;
  min_step: string;
  max_price_per_offer: string;
  max_budget: string;
  max_active_offers: string;
  max_nfts: string;
  expiration_days: string;
  check_interval_seconds: string;
  on_limit_behavior: string;
  credential_id: string;
  state: string;
}

const EMPTY_FORM: RuleForm = {
  name: '',
  collection_id: '',
  scope_mode: 'collection',
  models: '',
  backdrops: '',
  excluded_backdrops: '',
  symbols: '',
  scope_guard: true,
  strategy: 'floor_relative',
  hold_first_place: false,
  pause_on_uncertainty: false,
  discount_percent: '0',
  max_price_percent: '',
  fixed_price: '',
  min_step: '0.00001',
  max_price_per_offer: '',
  max_budget: '',
  max_active_offers: '1',
  max_nfts: '1',
  expiration_days: '',
  check_interval_seconds: '60',
  on_limit_behavior: 'keep',
  credential_id: '',
  state: 'disabled',
};

function splitList(value: string): string[] {
  return value
    .split(',')
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

function ruleStateTone(state: string): Tone {
  if (state === 'active') {
    return 'green';
  }
  if (state === 'dry_run') {
    return 'blue';
  }
  if (state === 'paused') {
    return 'amber';
  }
  if (state === 'error') {
    return 'red';
  }
  return 'slate';
}

export default function RulesPage() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<RuleForm>(EMPTY_FORM);
  const [availableModels, setAvailableModels] = useState<CollectionModel[]>([]);
  const [availableBackdrops, setAvailableBackdrops] = useState<CollectionAttribute[]>([]);
  const [availableSymbols, setAvailableSymbols] = useState<CollectionAttribute[]>([]);
  const [backdropsLoading, setBackdropsLoading] = useState(false);
  const [backdropsError, setBackdropsError] = useState<string | null>(null);
  const backdropRequestId = useRef(0);
  const [collectionSearch, setCollectionSearch] = useState('');
  const [modelSearch, setModelSearch] = useState('');
  const [backdropSearch, setBackdropSearch] = useState('');
  const [excludedBackdropSearch, setExcludedBackdropSearch] = useState('');
  const [symbolSearch, setSymbolSearch] = useState('');
  const [refreshingCatalog, setRefreshingCatalog] = useState(false);
  const [saving, setSaving] = useState(false);

  const [preview, setPreview] = useState<DryRunPreview | null>(null);
  const isFirstPlace = form.strategy === 'hold_first_place';
  const visibleCollections = collections.filter((item) =>
    item.name.toLowerCase().includes(collectionSearch.trim().toLowerCase()),
  );
  const visibleModels = availableModels.filter((item) =>
    item.name.toLowerCase().includes(modelSearch.trim().toLowerCase()),
  );
  const visibleBackdrops = availableBackdrops.filter((item) =>
    item.name.toLowerCase().includes(backdropSearch.trim().toLowerCase()),
  );
  const visibleExcludedBackdrops = availableBackdrops.filter((item) =>
    item.name.toLowerCase().includes(excludedBackdropSearch.trim().toLowerCase()),
  );
  const visibleSymbols = availableSymbols.filter((item) =>
    item.name.toLowerCase().includes(symbolSearch.trim().toLowerCase()),
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await apiFetch<Rule[]>('/api/rules');
      setRules(rows);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadOptions = useCallback(async () => {
    try {
      const cols = await apiFetch<Collection[]>('/api/collections?only_offers=true');
      setCollections(cols);
    } catch {
      setCollections([]);
    }
    try {
      const creds = await apiFetch<Credential[]>('/api/credentials');
      setCredentials(creds);
    } catch {
      setCredentials([]);
    }
  }, []);

  const refreshCatalog = async () => {
    setRefreshingCatalog(true);
    setError(null);
    try {
      const res = await apiFetch<MessageResponse>('/api/collections/refresh', { method: 'POST' });
      alert(res.message);
      await loadOptions();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка обновления каталога');
    } finally {
      setRefreshingCatalog(false);
    }
  };

  const loadModels = useCallback(async (collectionId: string) => {
    if (!collectionId) {
      setAvailableModels([]);
      setAvailableSymbols([]);
      return;
    }
    try {
      const [models, symbols] = await Promise.all([
        apiFetch<CollectionModel[]>(`/api/collections/${collectionId}/models`).catch(() => []),
        apiFetch<CollectionAttribute[]>(`/api/collections/${collectionId}/symbols`).catch(() => []),
      ]);
      setAvailableModels(models);
      setAvailableSymbols(symbols);
    } catch {
      setAvailableModels([]);
      setAvailableSymbols([]);
    }
  }, []);

  const loadBackdrops = useCallback(async (collectionId: string, models: string[] = []) => {
    const requestId = ++backdropRequestId.current;
    if (!collectionId) {
      setAvailableBackdrops([]);
      setBackdropsError(null);
      setBackdropsLoading(false);
      return;
    }

    setBackdropsLoading(true);
    setBackdropsError(null);
    const query = models.length > 0
      ? `?models=${encodeURIComponent(models.join(','))}`
      : '';
    try {
      const rows = await apiFetch<CollectionAttribute[]>(
        `/api/collections/${collectionId}/backdrops${query}`,
      );
      if (requestId === backdropRequestId.current) {
        setAvailableBackdrops(rows);
      }
    } catch (err) {
      if (requestId === backdropRequestId.current) {
        setAvailableBackdrops([]);
        setBackdropsError(err instanceof Error ? err.message : 'Не удалось загрузить фоны');
      }
    } finally {
      if (requestId === backdropRequestId.current) {
        setBackdropsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void load();
    void loadOptions();
  }, [load, loadOptions]);

  useEffect(() => {
    if (form.collection_id) {
      void loadModels(form.collection_id);
    } else {
      setAvailableModels([]);
      setAvailableSymbols([]);
    }
  }, [form.collection_id, loadModels]);

  useEffect(() => {
    void loadBackdrops(form.collection_id, splitList(form.models));
  }, [form.collection_id, form.models, loadBackdrops]);

  function openCreate() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setFormOpen(true);
  }

  function openEdit(rule: Rule) {
    setEditingId(rule.id);
    setForm({
      name: rule.name,
      collection_id: rule.collection_id,
      scope_mode: rule.scope_mode,
      models: rule.models.join(', '),
      backdrops: rule.backdrops.join(', '),
      excluded_backdrops: rule.excluded_backdrops.join(', '),
      symbols: rule.symbols.join(', '),
      scope_guard: rule.scope_guard,
      strategy: rule.strategy,
      hold_first_place: rule.hold_first_place,
      pause_on_uncertainty: rule.pause_on_uncertainty,
      discount_percent: rule.discount_percent,
      max_price_percent: rule.max_price_percent ?? '',
      fixed_price: rule.fixed_price ?? '',
      min_step: rule.min_step,
      max_price_per_offer: rule.max_price_per_offer ?? '',
      max_budget: rule.max_budget ?? '',
      max_active_offers: String(rule.max_active_offers),
      max_nfts: String(rule.max_nfts),
      expiration_days: rule.expiration_days === null ? '' : String(rule.expiration_days),
      check_interval_seconds: String(rule.check_interval_seconds),
      on_limit_behavior: rule.on_limit_behavior,
      credential_id: '',
      state: rule.state,
    });
    setFormOpen(true);
  }

  async function saveRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const payload = {
      name: form.name,
      collection_id: form.collection_id,
      scope_mode: form.scope_mode,
      models: splitList(form.models),
      backdrops: splitList(form.backdrops),
      excluded_backdrops: splitList(form.excluded_backdrops),
      symbols: splitList(form.symbols),
      scope_guard: form.scope_guard,
      strategy: form.strategy,
      hold_first_place: form.hold_first_place || isFirstPlace,
      pause_on_uncertainty: form.pause_on_uncertainty,
      discount_percent: form.discount_percent === '' ? '0' : form.discount_percent,
      max_price_percent: form.max_price_percent.trim() === '' ? null : form.max_price_percent.trim(),
      fixed_price: form.fixed_price.trim() === '' ? null : form.fixed_price.trim(),
      min_step: form.min_step.trim() === '' ? '0.00001' : form.min_step.trim(),
      max_price_per_offer:
        form.max_price_per_offer.trim() === '' ? null : form.max_price_per_offer.trim(),
      max_budget: form.max_budget.trim() === '' ? null : form.max_budget.trim(),
      max_active_offers: Number(form.max_active_offers) || 1,
      max_nfts: Number(form.max_nfts) || 1,
      expiration_days: form.expiration_days === '' ? null : Number(form.expiration_days),
      check_interval_seconds: Number(form.check_interval_seconds) || 60,
      on_limit_behavior: form.on_limit_behavior,
      credential_id: form.credential_id === '' ? null : form.credential_id,
      state: form.state,
    };
    try {
      if (editingId === null) {
        await apiFetch<Rule>('/api/rules', { method: 'POST', body: JSON.stringify(payload) });
      } else {
        await apiFetch<Rule>(`/api/rules/${editingId}`, {
          method: 'PUT',
          body: JSON.stringify(payload),
        });
      }
      setFormOpen(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка сохранения');
    } finally {
      setSaving(false);
    }
  }

  async function toggleState(rule: Rule) {
    setError(null);
    try {
      await apiFetch<Rule>(`/api/rules/${rule.id}/state`, {
        method: 'POST',
        body: JSON.stringify({ enabled: !rule.enabled }),
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка смены состояния');
    }
  }

  async function runPreview(rule: Rule) {
    setError(null);
    try {
      const result = await apiFetch<DryRunPreview>(`/api/rules/${rule.id}/preview`, {
        method: 'POST',
      });
      setPreview(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка проверки');
    }
  }

  async function removeRule(rule: Rule) {
    if (!window.confirm(`Удалить правило «${rule.name}»?`)) {
      return;
    }
    setError(null);
    try {
      await apiFetch<MessageResponse>(`/api/rules/${rule.id}`, { method: 'DELETE' });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка удаления');
    }
  }

  function setField<K extends keyof RuleForm>(key: K, value: RuleForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function toggleModel(name: string) {
    const current = splitList(form.models);
    const next = current.includes(name) ? current.filter((m) => m !== name) : [...current, name];
    setField('models', next.join(', '));
  }

  function toggleBackdrop(name: string) {
    const current = splitList(form.backdrops);
    const next = current.includes(name) ? current.filter((item) => item !== name) : [...current, name];
    setField('backdrops', next.join(', '));
  }

  function toggleExcludedBackdrop(name: string) {
    const current = splitList(form.excluded_backdrops);
    const next = current.includes(name) ? current.filter((item) => item !== name) : [...current, name];
    setField('excluded_backdrops', next.join(', '));
  }

  function toggleSymbol(name: string) {
    const current = splitList(form.symbols);
    const next = current.includes(name) ? current.filter((item) => item !== name) : [...current, name];
    setField('symbols', next.join(', '));
  }

  return (
    <Shell>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold text-slate-100">Правила</h1>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" onClick={() => void load()}>
            Обновить
          </Button>
          <Button variant="ghost" onClick={refreshCatalog} disabled={refreshingCatalog}>
            {refreshingCatalog ? 'Синхронизация...' : 'Синхронизировать каталог'}
          </Button>
          <Button variant="primary" onClick={openCreate}>
            Создать правило
          </Button>
        </div>
      </div>

      {error !== null && <Alert tone="red">{error}</Alert>}

      <Card title="Список правил">
        {loading ? (
          <Spinner className="h-6 w-6" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-800">
                  <Th>Название</Th>
                  <Th>Коллекция</Th>
                  <Th>Стратегия</Th>
                  <Th>Состояние</Th>
                  <Th>Офферы</Th>
                  <Th>Позиция</Th>
                  <Th>Ошибка</Th>
                  <Th>Проверен</Th>
                  <Th>Действия</Th>
                </tr>
              </thead>
              <tbody>
                {rules.map((rule) => (
                  <tr key={rule.id} className="border-b border-slate-800/60">
                    <Td>{rule.name}</Td>
                    <Td>{rule.collection_name ?? rule.collection_id}</Td>
                    <Td>{rule.strategy}</Td>
                    <Td>
                      <Badge tone={ruleStateTone(rule.state)}>{ruleStateLabel(rule.state)}</Badge>
                    </Td>
                    <Td>{rule.active_offers}</Td>
                    <Td>{rule.last_position_status === null ? '—' : positionLabel(rule.last_position_status)}</Td>
                    <Td className="max-w-xs break-words text-red-300">{rule.last_error ?? '—'}</Td>
                    <Td>{formatDate(rule.last_run_at)}</Td>
                    <Td>
                      <div className="flex flex-wrap gap-1">
                        <Button variant="ghost" onClick={() => void toggleState(rule)}>
                          {rule.enabled ? 'Выключить' : 'Включить'}
                        </Button>
                        <Button variant="ghost" onClick={() => void runPreview(rule)}>
                          Проверить
                        </Button>
                        <Button variant="ghost" onClick={() => openEdit(rule)}>
                          Изменить
                        </Button>
                        <Button variant="danger" onClick={() => void removeRule(rule)}>
                          Удалить
                        </Button>
                      </div>
                    </Td>
                  </tr>
                ))}
                {rules.length === 0 && (
                  <tr>
                    <Td className="text-slate-400">Правил нет</Td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Modal
        open={formOpen}
        title={editingId === null ? 'Новое правило' : 'Изменение правила'}
        onClose={() => setFormOpen(false)}
      >
        <form onSubmit={saveRule} className="space-y-3">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {!isFirstPlace && <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Название</span>
              <Input
                value={form.name}
                onChange={(event) => setField('name', event.target.value)}
                required
              />
            </label>}
            {!isFirstPlace && <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Коллекция</span>
              <Input className="mb-2" placeholder="Поиск коллекции" value={collectionSearch} onChange={(event) => setCollectionSearch(event.target.value)} />
              <Select
                value={form.collection_id}
                onChange={(event) => {
                  setForm((current) => ({
                    ...current,
                    collection_id: event.target.value,
                    models: '',
                    backdrops: '',
                    excluded_backdrops: '',
                    symbols: '',
                  }));
                  setAvailableBackdrops([]);
                  setBackdropsError(null);
                }}
                required
              >
                <option value="">Выберите коллекцию</option>
                {visibleCollections.map((collection) => (
                  <option key={collection.id} value={collection.id}>
                    {collection.name}
                  </option>
                ))}
              </Select>
            </label>}
            {!isFirstPlace && <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Область</span>
              <Select
                value={form.scope_mode}
                onChange={(event) => setField('scope_mode', event.target.value)}
              >
                <option value="collection">Коллекция</option>
                <option value="models">Только выбранные модели</option>
              </Select>
            </label>}
            {!isFirstPlace && <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Стратегия</span>
              <Select
                value={form.strategy}
                onChange={(event) => setField('strategy', event.target.value)}
              >
                <option value="floor_relative">Относительно пола</option>
                <option value="hold_first_place">Удержание первого места</option>
                <option value="fixed">Фиксированная цена</option>
                <option value="models_only">Только выбранные модели</option>
                <option value="safe_pause">Безопасная пауза</option>
              </Select>
            </label>}
            <div className="md:col-span-2">
              <span className="mb-1 block text-xs uppercase text-slate-400">Модели (выберите из списка)</span>
              <Input className="mb-2" placeholder="Поиск модели" value={modelSearch} onChange={(event) => setModelSearch(event.target.value)} />
              {availableModels.length > 0 ? (
                <div className="max-h-64 space-y-1 overflow-y-auto rounded border border-slate-800 bg-slate-900/50 p-2">
                  {visibleModels.map((m) => {
                    const selected = splitList(form.models).includes(m.name);
                    return (
                      <button
                        key={m.name}
                        type="button"
                        onClick={() => toggleModel(m.name)}
                        className={`flex w-full items-center gap-2 rounded border px-2 py-1 text-left text-xs transition-colors ${
                          selected
                            ? 'bg-blue-600 border-blue-500 text-white'
                            : 'bg-slate-800 border-slate-700 text-slate-300 hover:border-slate-500'
                        }`}
                      >
                        {m.photo_url ? <img src={m.photo_url} alt="" className="h-8 w-8 rounded object-cover" /> : <span className="h-8 w-8 rounded bg-slate-700" />}
                        <span className="flex-1">{m.name}</span>
                        {m.floor_price && <span className="opacity-60">Floor: {m.floor_price}</span>}
                      </button>
                    );
                  })}
                </div>
              ) : (
                <div className="text-xs text-slate-500 italic p-2 border border-slate-800 rounded">
                  {form.collection_id ? 'Загрузка моделей...' : 'Выберите коллекцию, чтобы увидеть модели'}
                </div>
              )}
            </div>
            {!isFirstPlace && <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Ручной ввод моделей</span>
              <Input
                value={form.models}
                onChange={(event) => setField('models', event.target.value)}
                placeholder="Модель1, Модель2..."
              />
            </label>}
            <div className="md:col-span-2">
              <span className="mb-1 block text-xs uppercase text-slate-400">Фоны (выберите из списка)</span>
              <Input className="mb-2" placeholder="Поиск фона" value={backdropSearch} onChange={(event) => setBackdropSearch(event.target.value)} />
              {availableBackdrops.length > 0 ? (
                <div className="max-h-64 space-y-1 overflow-y-auto rounded border border-slate-800 bg-slate-900/50 p-2">
                  {visibleBackdrops.map((backdrop) => {
                    const selected = splitList(form.backdrops).includes(backdrop.name);
                    return (
                      <button
                        key={backdrop.name}
                        type="button"
                        onClick={() => toggleBackdrop(backdrop.name)}
                        className={`flex w-full items-center gap-2 rounded border px-2 py-1 text-left text-xs transition-colors ${
                          selected
                            ? 'border-blue-500 bg-blue-600 text-white'
                            : 'border-slate-700 bg-slate-800 text-slate-300 hover:border-slate-500'
                        }`}
                      >
                        {backdrop.photo_url ? <img src={backdrop.photo_url} alt="" className="h-8 w-8 rounded object-cover" /> : <span className="h-8 w-8 rounded bg-slate-700" />}
                        <span className="flex-1">{backdrop.name}</span>
                        {backdrop.floor_price && <span className="opacity-60">Floor: {backdrop.floor_price}</span>}
                      </button>
                    );
                  })}
                </div>
              ) : (
                <div className="rounded border border-slate-800 p-2 text-xs italic text-slate-500">
                  {backdropsError
                    ? `Ошибка загрузки фонов: ${backdropsError}`
                    : backdropsLoading
                      ? 'Загрузка фонов из Portals...'
                      : form.collection_id
                        ? 'Portals не вернул фоны для коллекции или выбранной модели'
                        : 'Выберите коллекцию, чтобы увидеть фоны'}
                </div>
              )}
              <Input
                className="mt-2"
                value={form.backdrops}
                onChange={(event) => setField('backdrops', event.target.value)}
                placeholder="Можно также ввести вручную через запятую"
              />
            </div>
            <div className="md:col-span-2">
              <span className="mb-1 block text-xs uppercase text-slate-400">Исключённые фоны</span>
              <p className="mb-2 text-xs text-slate-500">
                Конкуренты, офферы которых ограничены только этими фонами, не учитываются. Если фоны выше не выбраны, оффер создаётся по всем фонам, кроме исключённых.
              </p>
              <Input className="mb-2" placeholder="Поиск фона" value={excludedBackdropSearch} onChange={(event) => setExcludedBackdropSearch(event.target.value)} />
              {availableBackdrops.length > 0 ? (
                <div className="max-h-64 space-y-1 overflow-y-auto rounded border border-slate-800 bg-slate-900/50 p-2">
                  {visibleExcludedBackdrops.map((backdrop) => {
                    const selected = splitList(form.excluded_backdrops).includes(backdrop.name);
                    return (
                      <button
                        key={backdrop.name}
                        type="button"
                        onClick={() => toggleExcludedBackdrop(backdrop.name)}
                        className={`flex w-full items-center gap-2 rounded border px-2 py-1 text-left text-xs transition-colors ${
                          selected
                            ? 'border-red-500 bg-red-600 text-white'
                            : 'border-slate-700 bg-slate-800 text-slate-300 hover:border-slate-500'
                        }`}
                      >
                        {backdrop.photo_url ? <img src={backdrop.photo_url} alt="" className="h-8 w-8 rounded object-cover" /> : <span className="h-8 w-8 rounded bg-slate-700" />}
                        <span className="flex-1">{backdrop.name}</span>
                        {backdrop.floor_price && <span className="opacity-60">Floor: {backdrop.floor_price}</span>}
                      </button>
                    );
                  })}
                </div>
              ) : (
                <div className="rounded border border-slate-800 p-2 text-xs italic text-slate-500">
                  {backdropsError
                    ? `Ошибка загрузки фонов: ${backdropsError}`
                    : backdropsLoading
                      ? 'Загрузка фонов из Portals...'
                      : form.collection_id
                        ? 'Portals не вернул фоны для коллекции или выбранной модели'
                        : 'Выберите коллекцию, чтобы увидеть фоны'}
                </div>
              )}
              <Input
                className="mt-2"
                value={form.excluded_backdrops}
                onChange={(event) => setField('excluded_backdrops', event.target.value)}
                placeholder="Можно также ввести вручную через запятую"
              />
            </div>
            <div className="md:col-span-2">
              <span className="mb-1 block text-xs uppercase text-slate-400">Символы (выберите из списка)</span>
              <Input className="mb-2" placeholder="Поиск символа" value={symbolSearch} onChange={(event) => setSymbolSearch(event.target.value)} />
              {availableSymbols.length > 0 ? (
                <div className="max-h-64 space-y-1 overflow-y-auto rounded border border-slate-800 bg-slate-900/50 p-2">
                  {visibleSymbols.map((symbol) => {
                    const selected = splitList(form.symbols).includes(symbol.name);
                    return (
                      <button
                        key={symbol.name}
                        type="button"
                        onClick={() => toggleSymbol(symbol.name)}
                        className={`flex w-full items-center gap-2 rounded border px-2 py-1 text-left text-xs transition-colors ${
                          selected
                            ? 'border-blue-500 bg-blue-600 text-white'
                            : 'border-slate-700 bg-slate-800 text-slate-300 hover:border-slate-500'
                        }`}
                      >
                        {symbol.photo_url ? <img src={symbol.photo_url} alt="" className="h-8 w-8 rounded object-cover" /> : <span className="h-8 w-8 rounded bg-slate-700" />}
                        <span className="flex-1">{symbol.name}</span>
                        {symbol.floor_price && <span className="opacity-60">Floor: {symbol.floor_price}</span>}
                      </button>
                    );
                  })}
                </div>
              ) : (
                <div className="rounded border border-slate-800 p-2 text-xs italic text-slate-500">
                  {form.collection_id ? 'Символы не загружены или отсутствуют' : 'Выберите коллекцию, чтобы увидеть символы'}
                </div>
              )}
              <Input
                className="mt-2"
                value={form.symbols}
                onChange={(event) => setField('symbols', event.target.value)}
                placeholder="Можно также ввести вручную через запятую"
              />
            </div>
            <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Макс. цена (% от пола)</span>
              <Input
                type="number"
                min="0"
                max="100"
                step="0.01"
                value={form.max_price_percent}
                onChange={(event) => setField('max_price_percent', event.target.value)}
                placeholder="Напр. 90"
              />
            </label>
            {!isFirstPlace && <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Скидка от пола, %</span>
              <Input
                value={form.discount_percent}
                onChange={(event) => setField('discount_percent', event.target.value)}
              />
            </label>}
            <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Минимальный шаг</span>
              <Input value={form.min_step} onChange={(event) => setField('min_step', event.target.value)} />
            </label>
            {!isFirstPlace && <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Макс. цена оффера (фикс)</span>
              <Input
                value={form.max_price_per_offer}
                onChange={(event) => setField('max_price_per_offer', event.target.value)}
              />
            </label>}
            {!isFirstPlace && <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Фиксированная цена</span>
              <Input
                value={form.fixed_price}
                onChange={(event) => setField('fixed_price', event.target.value)}
              />
            </label>}
            {!isFirstPlace && <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Макс. бюджет</span>
              <Input
                value={form.max_budget}
                onChange={(event) => setField('max_budget', event.target.value)}
              />
            </label>}
            <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Макс. офферов на модель</span>
              <Input
                value={form.max_active_offers}
                onChange={(event) => setField('max_active_offers', event.target.value)}
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Количество NFT</span>
              <Input
                value={form.max_nfts}
                onChange={(event) => setField('max_nfts', event.target.value)}
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Срок действия</span>
              <Select
                value={form.expiration_days}
                onChange={(event) => setField('expiration_days', event.target.value)}
              >
                <option value="">Пусто</option>
                <option value="1">1 день</option>
                <option value="7">7 дней</option>
              </Select>
            </label>
            <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Интервал проверки, сек</span>
              <Input
                value={form.check_interval_seconds}
                onChange={(event) => setField('check_interval_seconds', event.target.value)}
              />
            </label>
            {!isFirstPlace && <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">При достижении лимита</span>
              <Select
                value={form.on_limit_behavior}
                onChange={(event) => setField('on_limit_behavior', event.target.value)}
              >
                <option value="keep">Оставить</option>
                <option value="pause">Поставить на паузу</option>
                <option value="cancel">Отменить оффер</option>
              </Select>
            </label>}
            <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">API-ключ</span>
              <Select
                value={form.credential_id}
                onChange={(event) => setField('credential_id', event.target.value)}
              >
                <option value="">Основной</option>
                {credentials.map((credential) => (
                  <option key={credential.id} value={credential.id}>
                    {credential.label} ({credential.token_hint})
                  </option>
                ))}
              </Select>
            </label>
            <label className="block text-sm">
              <span className="mb-1 block text-xs uppercase text-slate-400">Состояние</span>
              <Select value={form.state} onChange={(event) => setField('state', event.target.value)}>
                <option value="disabled">Выключено</option>
                <option value="dry_run">Пробный режим</option>
              </Select>
            </label>
          </div>

          <div className="flex flex-wrap gap-4">
            {!isFirstPlace && <Toggle
              checked={form.scope_guard}
              onChange={(value) => setField('scope_guard', value)}
              label="Защита области"
            />}
            {!isFirstPlace && (
              <Toggle
                checked={form.hold_first_place}
                onChange={(value) => setField('hold_first_place', value)}
                label="Удерживать первое место"
              />
            )}
            <Toggle
              checked={form.pause_on_uncertainty}
              onChange={(value) => setField('pause_on_uncertainty', value)}
              label="Пауза при неопределённости"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="ghost" onClick={() => setFormOpen(false)}>
              Отмена
            </Button>
            <Button type="submit" variant="primary" disabled={saving}>
              Сохранить
            </Button>
          </div>
        </form>
      </Modal>

      <Modal open={preview !== null} title="Результат проверки" onClose={() => setPreview(null)}>
        {preview !== null && (
          <div className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
            <p>
              <span className="text-slate-400">Действие: </span>
              {preview.action}
            </p>
            <p>
              <span className="text-slate-400">Статус: </span>
              {preview.status}
            </p>
            <p className="sm:col-span-2">
              <span className="text-slate-400">Причина: </span>
              {preview.reason}
            </p>
            <p>
              <span className="text-slate-400">Целевая цена: </span>
              {formatMoney(preview.target_price)}
            </p>
            <p>
              <span className="text-slate-400">Потолок: </span>
              {formatMoney(preview.cap)}
            </p>
            <p>
              <span className="text-slate-400">Макс. цена от floor: </span>
              {preview.floor_price !== null && preview.cap !== null
                ? `${((Number(preview.cap) / Number(preview.floor_price)) * 100).toFixed(2)}%`
                : '—'}
            </p>
            <p>
              <span className="text-slate-400">Пол: </span>
              {formatMoney(preview.floor_price)}
            </p>
            <p>
              <span className="text-slate-400">Конкурент: </span>
              {formatMoney(preview.competitor_amount)}
            </p>
            <p>
              <span className="text-slate-400">Макс. конкурент: </span>
              {formatMoney(preview.competitor_amount)}
            </p>
            {preview.cap !== null &&
              preview.competitor_amount !== null &&
              Number(preview.competitor_amount) >= Number(preview.cap) && (
                <p className="sm:col-span-2 text-amber-300">
                  Первое место недостижимо: конкурент уже выше установленного потолка.
                </p>
              )}
            <p>
              <span className="text-slate-400">Свой оффер: </span>
              {formatMoney(preview.own_amount)}
            </p>
            <p>
              <span className="text-slate-400">Ранг: </span>
              {preview.own_rank === null ? '—' : preview.own_rank}
            </p>
            <p>
              <span className="text-slate-400">Всего офферов: </span>
              {preview.total_offers}
            </p>
            {Array.isArray(preview.detail.scopes) &&
              (preview.detail.scopes as PreviewScope[]).length > 1 && (
                <div className="mt-2 border-t border-slate-700 pt-3 sm:col-span-2">
                  <p className="mb-2 text-slate-400">
                    Отдельный оффер на каждую модель (свой floor у каждой):
                  </p>
                  <table className="w-full">
                    <thead>
                      <tr>
                        <Th>Модель</Th>
                        <Th>Действие</Th>
                        <Th>Floor</Th>
                        <Th>Целевая цена</Th>
                        <Th>Потолок</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {(preview.detail.scopes as PreviewScope[]).map((scope) => (
                        <tr key={scope.model}>
                          <Td>{scope.model}</Td>
                          <Td>{scope.action}</Td>
                          <Td>{formatMoney(scope.floor_price)}</Td>
                          <Td>{formatMoney(scope.target_price)}</Td>
                          <Td>{formatMoney(scope.cap)}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
          </div>
        )}
      </Modal>
    </Shell>
  );
}
