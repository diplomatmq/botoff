let csrfToken: string | null = null;

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

function extractDetail(payload: unknown, fallback: string): string {
  if (payload !== null && typeof payload === 'object' && 'detail' in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === 'string') {
      return detail;
    }
    if (Array.isArray(detail)) {
      const parts = detail.map((item) => {
        if (item !== null && typeof item === 'object' && 'msg' in item) {
          return String((item as { msg: unknown }).msg);
        }
        return String(item);
      });
      if (parts.length > 0) {
        return parts.join('; ');
      }
    }
  }
  return fallback;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? 'GET').toUpperCase();
  const headers = new Headers(init?.headers);

  if (init?.body !== undefined && init?.body !== null && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (!SAFE_METHODS.has(method) && csrfToken !== null) {
    headers.set('X-CSRF-Token', csrfToken);
  }

  const res = await fetch(path, { ...init, method, headers, credentials: 'include' });
  const text = await res.text();
  const payload = text.length > 0 ? parseJson(text) : undefined;

  if (!res.ok) {
    throw new ApiError(extractDetail(payload, res.statusText), res.status);
  }

  return (payload as T) ?? (undefined as T);
}

export function formatMoney(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  return value;
}

export function formatDate(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '—';
  }
  return date.toLocaleString('ru-RU');
}

const POSITION_LABELS: Record<string, string> = {
  FIRST_CONFIRMED: 'Первое место подтверждено',
  OUTBID: 'Перебит',
  LIMIT_REACHED: 'Достигнут лимит',
  INSUFFICIENT_FUNDS: 'Недостаточно средств',
  DATA_INCOMPLETE: 'Неполные данные',
  STALE_DATA: 'Устаревшие данные',
  API_ERROR: 'Ошибка API',
  RATE_LIMITED: 'Лимит запросов',
  ATTRIBUTE_OFFERS_UNAVAILABLE: 'Офферы по атрибутам недоступны',
  UNKNOWN: 'Неизвестно',
};

export function positionLabel(status: string): string {
  return POSITION_LABELS[status] ?? status;
}

const RULE_STATE_LABELS: Record<string, string> = {
  ACTIVE: 'Активно',
  DRY_RUN: 'Пробный режим',
  PAUSED: 'Пауза',
  ERROR: 'Ошибка',
  DISABLED: 'Выключено',
};

export function ruleStateLabel(state: string): string {
  return RULE_STATE_LABELS[state] ?? state;
}
