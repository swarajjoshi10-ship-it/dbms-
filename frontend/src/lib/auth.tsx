import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, setUnauthorizedHandler, tokenStore, type CustomerProfile, type User } from "./api";

interface Session { user: User; customer: CustomerProfile | null }
interface AuthState {
  session: Session | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (body: Record<string, string>) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  const logout = useCallback(() => {
    tokenStore.set(null);
    setSession(null);
  }, []);

  const loadMe = useCallback(async () => {
    setSession(await api<Session>("/auth/me"));
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    if (!tokenStore.get()) {
      setLoading(false);
      return;
    }
    // Only a rejected token ends the session; a network blip (API restarting) keeps it for the next reload.
    loadMe()
      .catch((e) => {
        if ((e as ApiError).status === 401) logout();
      })
      .finally(() => setLoading(false));
  }, [loadMe, logout]);

  const login = async (username: string, password: string) => {
    const res = await api<{ access_token: string }>("/auth/login", { body: { username, password } });
    tokenStore.set(res.access_token);
    await loadMe();
  };

  const register = async (body: Record<string, string>) => {
    const clean = Object.fromEntries(Object.entries(body).filter(([, v]) => v.trim() !== ""));
    const res = await api<{ access_token: string }>("/auth/register", { body: clean });
    tokenStore.set(res.access_token);
    await loadMe();
  };

  return <AuthContext.Provider value={{ session, loading, login, register, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
