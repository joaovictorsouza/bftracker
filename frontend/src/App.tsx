import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout, Logo } from "./components/Layout";
import { ErrorBox, Field, Loading, Spinner } from "./components/ui";
import { api, ApiError, onUnauthorized } from "./lib/api";
import { disablePush } from "./lib/push";
import type { User } from "./lib/types";
import { Coupons } from "./pages/Coupons";
import { Dashboard } from "./pages/Dashboard";
import { Interests } from "./pages/Interests";
import { Notifications } from "./pages/Notifications";
import { Radar } from "./pages/Radar";
import { Settings } from "./pages/Settings";
import { WatchDetailPage } from "./pages/WatchDetail";
import { Watches } from "./pages/Watches";

function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin(await api.post<User>("/auth/login", { username, password }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-dvh items-center justify-center p-5">
      <div className="card rise w-full max-w-sm p-7 shadow-2xl">
        <div className="mb-1 flex justify-center">
          <Logo />
        </div>
        <p className="mb-6 text-center text-sm text-muted">
          Preços, cupons e relâmpagos vigiados 24 horas.
        </p>
        <ErrorBox message={error} />
        <form onSubmit={submit} className="space-y-4">
          <Field label="Usuário">
            <input
              className="field"
              name="username"
              autoComplete="username"
              autoCapitalize="none"
              required
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </Field>
          <Field label="Senha">
            <input
              className="field"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <button className="btn-primary w-full" disabled={busy}>
            {busy && <Spinner className="size-4" />} Entrar
          </button>
        </form>
      </div>
    </main>
  );
}

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [offline, setOffline] = useState("");

  const check = useCallback(async () => {
    try {
      setUser(await api.get<User>("/me"));
      setOffline("");
    } catch (e) {
      if ((e as ApiError).status !== 401) setOffline((e as Error).message);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    onUnauthorized.handler = () => setUser(null);
    void check();
  }, [check]);

  const logout = async () => {
    // este aparelho deixa de receber avisos da conta que saiu
    await disablePush().catch(() => {});
    await api.post("/auth/logout").catch(() => {});
    setUser(null);
  };

  if (checking) return <Loading />;
  if (!user && offline) {
    return (
      <main className="mx-auto max-w-sm p-6 text-center">
        <ErrorBox message={offline} />
        <button className="btn-primary" onClick={() => void check()}>
          Tentar de novo
        </button>
      </main>
    );
  }
  if (!user) return <Login onLogin={setUser} />;

  return (
    <Routes>
      <Route element={<Layout user={user} onLogout={() => void logout()} />}>
        <Route index element={<Dashboard />} />
        <Route path="monitorados" element={<Watches />} />
        <Route path="monitorados/:id" element={<WatchDetailPage />} />
        <Route path="radar" element={<Radar />} />
        <Route path="cupons" element={<Coupons />} />
        <Route path="alertas" element={<Interests />} />
        <Route path="avisos" element={<Notifications />} />
        <Route path="configuracoes" element={<Settings user={user} onUser={setUser} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
