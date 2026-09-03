import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { fetchCurrentUser, login as loginRequest } from "../api/auth";
import { getAuthToken, setAuthToken } from "../api/client";
import type { CurrentUser } from "../api/types";

interface AuthContextValue {
  user: CurrentUser | null;
  organizationId: string | null;
  isAuthenticated: boolean;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  setOrganizationId: (organizationId: string) => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [organizationId, setOrganizationId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const login = useCallback(async (email: string, password: string) => {
    setLoading(true);
    try {
      const { access_token } = await loginRequest(email, password);
      setAuthToken(access_token);
      const me = await fetchCurrentUser();
      setUser(me);
      setOrganizationId(me.memberships[0]?.organization_id ?? null);
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(() => {
    setAuthToken(null);
    setUser(null);
    setOrganizationId(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      organizationId,
      isAuthenticated: Boolean(getAuthToken() && user),
      loading,
      login,
      logout,
      setOrganizationId,
    }),
    [user, organizationId, loading, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth debe usarse dentro de <AuthProvider>");
  return context;
}
