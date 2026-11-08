'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';

import { apiFetch, setCsrfToken } from '@/lib/api';
import type { AuthResponse, MessageResponse, User } from '@/lib/types';

interface SessionContextValue {
  user: User | null;
  loading: boolean;
  refresh: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const res = await apiFetch<AuthResponse>('/api/auth/me');
      setUser(res.user);
      setCsrfToken(res.csrf_token);
    } catch {
      setUser(null);
      setCsrfToken(null);
    }
  }, []);

  useEffect(() => {
    let active = true;
    void (async () => {
      await refresh();
      if (active) {
        setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    const res = await apiFetch<AuthResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
    setUser(res.user);
    setCsrfToken(res.csrf_token);
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiFetch<MessageResponse>('/api/auth/logout', { method: 'POST' });
    } catch {
      setUser(null);
    }
    setUser(null);
    setCsrfToken(null);
  }, []);

  return (
    <SessionContext.Provider value={{ user, loading, refresh, login, logout }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (ctx === null) {
    throw new Error('useSession must be used within SessionProvider');
  }
  return ctx;
}
