import { AlertTriangle, Check, Loader2, ShieldCheck, ShieldQuestion, X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { Trust, Verdict } from "../lib/types";

export function PageHeader({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold tracking-tight md:text-3xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {children && <div className="flex flex-wrap gap-2">{children}</div>}
    </header>
  );
}

export const Spinner = ({ className = "size-5" }: { className?: string }) => (
  <Loader2 className={`animate-spin ${className}`} aria-label="Carregando" />
);

export const Loading = () => (
  <div className="flex justify-center py-16 text-muted">
    <Spinner className="size-7" />
  </div>
);

export const ErrorBox = ({ message }: { message: string }) =>
  message ? (
    <div role="alert" className="card mb-4 flex items-center gap-2 border-bad/50 p-4 text-bad">
      <AlertTriangle className="size-5 shrink-0" />
      <span className="text-sm">{message}</span>
    </div>
  ) : null;

export function Empty({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="card flex flex-col items-center px-6 py-12 text-center">
      <div className="mb-3 rounded-2xl bg-surface-2 p-4 text-accent">{icon}</div>
      <h3 className="font-semibold">{title}</h3>
      {children && <div className="mt-1 max-w-md text-sm text-muted">{children}</div>}
    </div>
  );
}

const TRUST_STYLE: Record<Trust["level"], [string, string]> = {
  alta: ["text-good", "Loja confiável"],
  boa: ["text-accent", "Loja conhecida"],
  atencao: ["text-warn", "Atenção"],
  desconhecida: ["text-warn", "Loja desconhecida"],
};

export function TrustBadge({ trust }: { trust: Trust }) {
  const [color, label] = TRUST_STYLE[trust.level];
  const Icon =
    trust.level === "alta" || trust.level === "boa"
      ? ShieldCheck
      : trust.level === "atencao"
        ? AlertTriangle
        : ShieldQuestion;
  const badge = (
    <span className={`inline-flex items-center gap-1 text-xs font-medium ${color}`}>
      <Icon className="size-3.5" /> {label}
    </span>
  );
  return trust.reputation_url ? (
    <a href={trust.reputation_url} target="_blank" rel="noreferrer" title={trust.note}>
      {badge}
    </a>
  ) : (
    <span title={trust.note}>{badge}</span>
  );
}

const VERDICT_STYLE: Record<Verdict["level"], string> = {
  record: "bg-emerald-500/15 text-good",
  great: "bg-emerald-500/15 text-good",
  good: "bg-emerald-500/10 text-good",
  fair: "bg-surface-2 text-muted",
  learning: "bg-surface-2 text-muted",
  none: "bg-surface-2 text-muted",
  expensive: "bg-amber-500/15 text-warn",
  fake: "bg-rose-500/15 text-bad",
};

export const VerdictBadge = ({ verdict }: { verdict: Verdict }) => (
  <span
    className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${VERDICT_STYLE[verdict.level]}`}
    title={
      verdict.median
        ? `Menor: ${verdict.lowest} · mediana: ${verdict.median} · ${verdict.days} dias`
        : undefined
    }
  >
    {verdict.label}
  </span>
);

export function ProductImage({ src, className = "size-16" }: { src: string; className?: string }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  return (
    <div className={`shrink-0 overflow-hidden rounded-xl bg-white ${className}`}>
      {src && !failed ? (
        <img
          src={src}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
          className="size-full object-contain p-1"
        />
      ) : (
        <div className="flex size-full items-center justify-center bg-surface-2 text-xl">🛍️</div>
      )}
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  hint?: string;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-4 py-1.5">
      <span>
        <span className="block text-sm font-medium">{label}</span>
        {hint && <span className="block text-xs text-muted">{hint}</span>}
      </span>
      <input
        type="checkbox"
        role="switch"
        className="peer sr-only"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="relative h-6 w-11 shrink-0 rounded-full bg-line transition peer-checked:bg-violet-600 peer-focus-visible:ring-2 peer-focus-visible:ring-accent after:absolute after:top-0.5 after:left-0.5 after:size-5 after:rounded-full after:bg-white after:transition peer-checked:after:translate-x-5" />
    </label>
  );
}

export function Field({
  label,
  hint,
  children,
  className = "",
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1 block text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export function ChipSelect({
  options,
  value,
  onChange,
}: {
  options: { key: string; name: string }[];
  value: string[];
  onChange: (value: string[]) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((option) => {
        const on = value.includes(option.key);
        return (
          <button
            key={option.key}
            type="button"
            aria-pressed={on}
            className={`chip cursor-pointer py-1.5 ${on ? "chip-on" : "hover:border-accent"}`}
            onClick={() =>
              onChange(on ? value.filter((v) => v !== option.key) : [...value, option.key])
            }
          >
            {option.name}
          </button>
        );
      })}
    </div>
  );
}

export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
    // showModal foca o primeiro botão; leva o foco ao campo principal
    dialog?.querySelector<HTMLElement>("[data-autofocus]")?.focus();
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, []);
  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      className="card rise m-0 mt-auto max-h-[92dvh] w-full max-w-full overflow-y-auto rounded-b-none p-0 text-text backdrop:bg-black/60 backdrop:backdrop-blur-sm sm:m-auto sm:max-w-2xl sm:rounded-b-2xl"
    >
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-surface px-5 py-3">
        <h2 className="text-lg font-bold">{title}</h2>
        <button type="button" className="btn-ghost size-10 !p-0" onClick={onClose} aria-label="Fechar">
          <X className="size-5" />
        </button>
      </div>
      <div className="p-5">{children}</div>
    </dialog>
  );
}

type Toast = { id: number; text: string; kind: "ok" | "error" | "info"; onClick?: () => void };
const ToastContext = createContext<(t: Omit<Toast, "id">) => void>(() => {});
export const useToast = () => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const next = useRef(0);
  const push = useCallback((toast: Omit<Toast, "id">) => {
    const id = ++next.current;
    setItems((list) => [...list.slice(-3), { ...toast, id }]);
    setTimeout(() => setItems((list) => list.filter((t) => t.id !== id)), 6000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-3 top-[calc(env(safe-area-inset-top)+0.75rem)] z-[100] flex flex-col items-end gap-2"
      >
        {items.map((t) => (
          <button
            key={t.id}
            onClick={() => {
              t.onClick?.();
              setItems((list) => list.filter((x) => x.id !== t.id));
            }}
            className={`card rise pointer-events-auto flex w-full max-w-sm items-start gap-2 p-3 text-left text-sm shadow-xl ${t.kind === "error" ? "border-bad/60" : t.kind === "ok" ? "border-good/60" : "border-accent/60"}`}
          >
            {t.kind === "error" ? (
              <AlertTriangle className="size-4 shrink-0 text-bad" />
            ) : (
              <Check className="size-4 shrink-0 text-good" />
            )}
            <span>{t.text}</span>
          </button>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

/** Executa uma ação mostrando carregamento e o resultado. */
export function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const run = useCallback(
    async (action: () => Promise<unknown>, success?: string) => {
      setBusy(true);
      try {
        await action();
        if (success) toast({ kind: "ok", text: success });
        return true;
      } catch (e) {
        toast({ kind: "error", text: (e as Error).message });
        return false;
      } finally {
        setBusy(false);
      }
    },
    [toast],
  );
  return { busy, run };
}
