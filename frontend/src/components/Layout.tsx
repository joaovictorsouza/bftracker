import {
  Bell,
  BookmarkPlus,
  BellRing,
  Home,
  LogOut,
  Moon,
  Radar,
  Settings,
  Sun,
  Tags,
  Target,
  Ticket,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { LIVE_EVENT, type LiveUpdate } from "../lib/hooks";
import type { Notice, User } from "../lib/types";
import { useToast } from "./ui";

const NAV = [
  { to: "/", label: "Início", icon: Home },
  { to: "/monitorados", label: "Monitorados", short: "Produtos", icon: Target },
  { to: "/radar", label: "Radar de ofertas", short: "Radar", icon: Radar },
  { to: "/cupons", label: "Cupons", icon: Ticket },
  { to: "/alertas", label: "Meus interesses", icon: Tags, desktop: true },
  { to: "/avisos", label: "Avisos", icon: Bell },
  { to: "/importar", label: "Capturar do navegador", icon: BookmarkPlus, desktop: true },
  { to: "/configuracoes", label: "Configurações", icon: Settings, desktop: true },
];

function toggleTheme() {
  const dark = document.documentElement.classList.toggle("dark");
  localStorage.setItem("theme", dark ? "dark" : "light");
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", dark ? "#0b0d17" : "#f4f5fb");
  return dark;
}

export const Logo = () => (
  <span className="flex items-center gap-2.5 text-lg font-extrabold tracking-tight">
    <img src="/icon.svg" alt="" className="size-9" />
    <span>
      BF
      <span className="bg-gradient-to-r from-violet-500 to-fuchsia-500 bg-clip-text text-transparent">
        Tracker
      </span>
    </span>
  </span>
);

export function Layout({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [unread, setUnread] = useState(0);
  const [dark, setDark] = useState(document.documentElement.classList.contains("dark"));
  const [online, setOnline] = useState(true);
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    api
      .get<{ unread: number }>("/notifications?limit=1")
      .then((d) => setUnread(d.unread))
      .catch(() => {});
  }, [location.pathname]);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);

  // tempo real
  useEffect(() => {
    const source = new EventSource("/api/events");
    source.onopen = () => setOnline(true);
    source.onerror = () => {
      setOnline(false);
      // descobre se a sessão expirou
      api.get("/me").catch(() => {});
    };
    source.addEventListener("update", (event) => {
      const update = JSON.parse((event as MessageEvent).data) as LiveUpdate;
      update.notifications.forEach((n: Notice) =>
        toast({ kind: "info", text: n.title, onClick: () => navigate(n.path) }),
      );
      if (update.notifications.length) setUnread((u) => u + update.notifications.length);
      window.dispatchEvent(new CustomEvent(LIVE_EVENT, { detail: update }));
    });
    return () => source.close();
  }, [navigate, toast]);

  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    const listener = (event: MessageEvent) => {
      if (event.data?.type === "navigate") navigate(event.data.path);
    };
    navigator.serviceWorker.addEventListener("message", listener);
    return () => navigator.serviceWorker.removeEventListener("message", listener);
  }, [navigate]);

  const badge = unread > 0 && (
    <span className="min-w-5 rounded-full bg-fuchsia-600 px-1.5 text-center text-[11px] font-bold text-white">
      {unread > 99 ? "99+" : unread}
    </span>
  );

  const themeButton = (
    <button
      className="btn-ghost size-10 !p-0"
      onClick={() => setDark(toggleTheme())}
      aria-label={dark ? "Usar tema claro" : "Usar tema escuro"}
    >
      {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );

  return (
    <div className="lg:pl-64">
      <aside className="fixed inset-y-0 left-0 hidden w-64 flex-col border-r border-line bg-surface/70 p-4 backdrop-blur lg:flex">
        <div className="px-2 py-2">
          <Logo />
        </div>
        <nav className="mt-6 flex flex-1 flex-col gap-1">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition ${
                  isActive
                    ? "bg-gradient-to-r from-violet-600/20 to-fuchsia-600/10 text-accent"
                    : "text-muted hover:bg-surface-2 hover:text-text"
                }`
              }
            >
              <Icon className="size-5" />
              <span className="flex-1">{label}</span>
              {to === "/avisos" && badge}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center gap-2 border-t border-line pt-3">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold">{user.username}</p>
            <p className="flex items-center gap-1.5 text-xs text-muted">
              <span className={`size-2 rounded-full ${online ? "bg-emerald-500" : "bg-amber-500"}`} />
              {online ? "Ao vivo" : "Reconectando"}
            </p>
          </div>
          {themeButton}
          <button className="btn-ghost size-10 !p-0" onClick={onLogout} aria-label="Sair">
            <LogOut className="size-4" />
          </button>
        </div>
      </aside>

      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-bg/85 px-4 pt-[calc(env(safe-area-inset-top)+0.6rem)] pb-2.5 backdrop-blur lg:hidden">
        <Logo />
        <div className="flex gap-2">
          <NavLink to="/alertas" className="btn-ghost size-10 !p-0" aria-label="Meus interesses">
            <Tags className="size-4" />
          </NavLink>
          {themeButton}
          <NavLink to="/configuracoes" className="btn-ghost size-10 !p-0" aria-label="Configurações">
            <Settings className="size-4" />
          </NavLink>
          <button className="btn-ghost size-10 !p-0" onClick={onLogout} aria-label="Sair">
            <LogOut className="size-4" />
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 pt-5 pb-28 lg:px-8 lg:pt-8 lg:pb-12">
        <Outlet />
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
        {NAV.filter((n) => !n.desktop).map(({ to, label, short, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              `relative flex flex-col items-center gap-0.5 py-2.5 text-[11px] font-medium ${isActive ? "text-accent" : "text-muted"}`
            }
          >
            {to === "/avisos" && unread > 0 ? (
              <>
                <BellRing className="size-5" />
                <span className="absolute top-1 left-1/2 ml-1">{badge}</span>
              </>
            ) : (
              <Icon className="size-5" />
            )}
            {short ?? label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
