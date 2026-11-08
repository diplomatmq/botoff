'use client';

import {
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TdHTMLAttributes,
  type ThHTMLAttributes,
} from 'react';

export type Tone = 'slate' | 'green' | 'red' | 'amber' | 'blue';

const toneClasses: Record<Tone, string> = {
  slate: 'border-slate-600 bg-slate-800/60 text-slate-200',
  green: 'border-emerald-600/50 bg-emerald-500/10 text-emerald-300',
  red: 'border-red-600/50 bg-red-500/10 text-red-300',
  amber: 'border-amber-600/50 bg-amber-500/10 text-amber-300',
  blue: 'border-blue-600/50 bg-blue-500/10 text-blue-300',
};

export function Card({
  title,
  actions,
  children,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      {(title !== undefined || actions !== undefined) && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-300">{title}</h2>
          {actions !== undefined && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function StatCard({
  label,
  value,
  hint,
  tone = 'slate',
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
}) {
  return (
    <div className={`rounded-lg border p-3 ${toneClasses[tone]}`}>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-xl font-semibold text-slate-100">{value}</div>
      {hint !== undefined && <div className="mt-1 text-xs text-slate-400">{hint}</div>}
    </div>
  );
}

const buttonVariants: Record<'primary' | 'ghost' | 'danger', string> = {
  primary: 'bg-blue-600 text-white hover:bg-blue-500',
  ghost: 'border border-slate-700 bg-slate-800 text-slate-200 hover:bg-slate-700',
  danger: 'bg-red-600 text-white hover:bg-red-500',
};

export function Button({
  variant = 'ghost',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'ghost' | 'danger' }) {
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${buttonVariants[variant]} ${className}`}
    />
  );
}

export function Input({ className = '', ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm text-slate-100 outline-none focus:border-blue-500 ${className}`}
    />
  );
}

export function Select({
  className = '',
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={`w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm text-slate-100 outline-none focus:border-blue-500 ${className}`}
    >
      {children}
    </select>
  );
}

export function Badge({ tone = 'slate', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${toneClasses[tone]}`}
    >
      {children}
    </span>
  );
}

export function Th({ className = '', ...props }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      {...props}
      className={`whitespace-nowrap px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-400 ${className}`}
    />
  );
}

export function Td({ className = '', ...props }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td {...props} className={`px-3 py-2 align-top text-sm text-slate-200 ${className}`} />;
}

export function Spinner({ className = '' }: { className?: string }) {
  return (
    <span
      className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-slate-600 border-t-blue-400 ${className}`}
    />
  );
}

export function Alert({ tone = 'slate', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <div className={`rounded-md border px-3 py-2 text-sm ${toneClasses[tone]}`}>{children}</div>
  );
}

export function Modal({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  if (!open) {
    return null;
  }
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4">
      <div className="mt-10 w-full max-w-2xl rounded-lg border border-slate-800 bg-slate-900 shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
          <Button variant="ghost" onClick={onClose} type="button">
            Закрыть
          </Button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: ReactNode;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-200">
      <span
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-5 w-9 items-center rounded-full transition ${
          checked ? 'bg-blue-600' : 'bg-slate-700'
        }`}
      >
        <span
          className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition ${
            checked ? 'translate-x-4' : 'translate-x-1'
          }`}
        />
      </span>
      <span>{label}</span>
    </label>
  );
}
