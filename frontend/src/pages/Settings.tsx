import { Mail, MessageCircle, Play, Smartphone, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ErrorBox,
  Field,
  Loading,
  PageHeader,
  Spinner,
  Toggle,
  TrustBadge,
  useAction,
} from "../components/ui";
import { api } from "../lib/api";
import { ago, safeUrl } from "../lib/format";
import { useData, useMeta } from "../lib/hooks";
import { currentSubscription, disablePush, enablePush, isIos, isStandalone } from "../lib/push";
import type { Prefs, SourceRow, User } from "../lib/types";

const CHANNELS = [
  ["push", "Push no celular/navegador", Smartphone],
  ["email", "E-mail", Mail],
  ["whatsapp", "WhatsApp", MessageCircle],
] as const;

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="card p-4 md:p-5">
      <h2 className="font-bold">{title}</h2>
      {hint && <p className="mb-3 text-sm text-muted">{hint}</p>}
      <div className={hint ? "" : "mt-3"}>{children}</div>
    </section>
  );
}

function Devices() {
  const { data, reload } = useData<{
    devices: { endpoint: string; user_agent: string; created_at: string }[];
  }>("/push/key");
  const [here, setHere] = useState<string | null>(null);
  const { busy, run } = useAction();
  const refresh = useCallback(async () => {
    setHere((await currentSubscription())?.endpoint ?? null);
    await reload();
  }, [reload]);
  useEffect(() => {
    currentSubscription().then((s) => setHere(s?.endpoint ?? null));
  }, []);
  const active = data?.devices.some((d) => d.endpoint === here);

  return (
    <Section title="Notificações neste aparelho" hint="Ative em cada celular ou computador que deve receber os avisos.">
      {isIos() && !isStandalone() && (
        <p className="mb-3 rounded-xl bg-amber-500/10 p-3 text-sm text-warn">
          No iPhone/iPad: toque em Compartilhar → “Adicionar à Tela de Início” e abra o BFTracker pelo
          ícone antes de ativar.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {active ? (
          <button className="btn-ghost" disabled={busy} onClick={() => void run(async () => { await disablePush(); await refresh(); }, "Push desativado neste aparelho")}>
            Desativar aqui
          </button>
        ) : (
          <button className="btn-primary" disabled={busy} onClick={() => void run(async () => { await enablePush(); await refresh(); }, "Push ativado neste aparelho")}>
            <Smartphone className="size-4" /> Ativar neste aparelho
          </button>
        )}
      </div>
      {data && data.devices.length > 0 && (
        <ul className="mt-3 space-y-2">
          {data.devices.map((d) => (
            <li key={d.endpoint} className="flex items-center justify-between gap-2 rounded-xl bg-surface-2 p-2.5 text-xs">
              <span className="min-w-0 truncate">
                {d.endpoint === here && <strong className="text-good">Este · </strong>}
                {d.user_agent || "Dispositivo"} <span className="text-muted">· {ago(d.created_at)}</span>
              </span>
              <button
                className="btn-danger !min-h-8 !px-2"
                aria-label="Remover dispositivo"
                onClick={() => void run(async () => { await api.post("/push/unsubscribe", { endpoint: d.endpoint }); await refresh(); })}
              >
                <Trash2 className="size-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function Account({ user, onUser }: { user: User; onUser: (u: User) => void }) {
  const [email, setEmail] = useState(user.email);
  const [whatsapp, setWhatsapp] = useState(user.whatsapp);
  const [key, setKey] = useState(user.callmebot_key);
  const [prefs, setPrefs] = useState<Prefs>(user.prefs);
  const [password, setPassword] = useState({ current: "", new: "", again: "" });
  const { busy, run } = useAction();

  const save = async () => {
    onUser(await api.put<User>("/me", { email, whatsapp, callmebot_key: key, prefs }));
  };

  const changePassword = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      if (password.new !== password.again) throw new Error("As senhas novas não conferem");
      await api.post("/me/password", { current: password.current, new: password.new });
      setPassword({ current: "", new: "", again: "" });
    }, "Senha alterada");
  };

  return (
    <div className="space-y-4">
      <Devices />
      <Section title="Onde receber" hint="Salve antes de testar.">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="E-mail">
            <input className="field" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="voce@exemplo.com" />
          </Field>
          <Field label="WhatsApp" hint="Com DDD, ex.: 11 91234-5678">
            <input className="field" type="tel" value={whatsapp} onChange={(e) => setWhatsapp(e.target.value)} />
          </Field>
          <Field label="Chave do CallMeBot" hint="Só se o servidor usar o CallMeBot." className="sm:col-span-2">
            <input className="field" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" />
          </Field>
        </div>
        <div className="mt-4 space-y-2">
          {CHANNELS.map(([channel, label, Icon]) => (
            <div key={channel} className="rounded-xl bg-surface-2 p-3">
              <div className="flex flex-wrap items-center gap-3">
                <Icon className="size-5 text-accent" />
                <div className="min-w-40 flex-1">
                  <Toggle
                    label={label}
                    checked={prefs.channels[channel]}
                    onChange={(v) => setPrefs({ ...prefs, channels: { ...prefs.channels, [channel]: v } })}
                  />
                </div>
                <select
                  className="field !w-auto"
                  aria-label={`Quais avisos por ${label}`}
                  value={prefs.min_priority[channel]}
                  onChange={(e) =>
                    setPrefs({ ...prefs, min_priority: { ...prefs.min_priority, [channel]: Number(e.target.value) } })
                  }
                >
                  <option value={1}>Todos os avisos</option>
                  <option value={2}>Importantes</option>
                  <option value={3}>Só urgentes</option>
                </select>
                <button
                  className="btn-ghost"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      await save();
                      await api.post("/channels/test", { channel });
                    }, "Teste enviado")
                  }
                >
                  <Play className="size-4" /> Testar
                </button>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Field label="Silêncio a partir de" hint="Horário de Brasília. Deixe vazio para desativar.">
            <input className="field" type="time" value={prefs.quiet_start} onChange={(e) => setPrefs({ ...prefs, quiet_start: e.target.value })} />
          </Field>
          <Field label="Até">
            <input className="field" type="time" value={prefs.quiet_end} onChange={(e) => setPrefs({ ...prefs, quiet_end: e.target.value })} />
          </Field>
        </div>
        <Toggle
          label="Urgentes podem interromper o silêncio"
          hint="Preço-alvo, menor preço histórico e relâmpagos"
          checked={prefs.quiet_allow_urgent}
          onChange={(v) => setPrefs({ ...prefs, quiet_allow_urgent: v })}
        />
        <button className="btn-primary mt-3" disabled={busy} onClick={() => void run(save, "Preferências salvas")}>
          {busy && <Spinner className="size-4" />} Salvar
        </button>
      </Section>

      <Section title="Trocar senha">
        <form onSubmit={changePassword} className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {(
            [
              ["current", "Senha atual", "current-password"],
              ["new", "Nova senha (8+)", "new-password"],
              ["again", "Repita a nova", "new-password"],
            ] as const
          ).map(([name, label, auto]) => (
            <Field key={name} label={label}>
              <input
                className="field"
                type="password"
                autoComplete={auto}
                required
                minLength={name === "current" ? 1 : 8}
                value={password[name]}
                onChange={(e) => setPassword({ ...password, [name]: e.target.value })}
              />
            </Field>
          ))}
          <button className="btn-ghost sm:col-span-3 sm:justify-self-start" disabled={busy}>
            Alterar senha
          </button>
        </form>
      </Section>
    </div>
  );
}

interface ServerSettings {
  values: Record<string, string>;
  configured: Record<string, boolean>;
  secrets: string[];
}

type FieldSpec = [key: string, label: string, placeholder?: string];

const SMTP: FieldSpec[] = [
  ["smtp_host", "Servidor SMTP", "smtp.gmail.com"],
  ["smtp_port", "Porta", "587"],
  ["smtp_user", "Usuário"],
  ["smtp_password", "Senha ou senha de app"],
  ["smtp_from", "Remetente", "alertas@seudominio.com"],
];

const PROVIDERS: Record<string, { label: string; help: string; fields: FieldSpec[] }> = {
  waha: {
    label: "WAHA (no seu servidor, via QR Code)",
    help: "Suba com: docker compose --profile whatsapp up -d. Depois conecte abaixo.",
    fields: [["waha_url", "URL", "http://waha:3000"], ["waha_api_key", "Chave de API"], ["waha_session", "Sessão", "default"]],
  },
  evolution: {
    label: "Evolution API",
    help: "Use uma instância Evolution já conectada.",
    fields: [["evolution_url", "URL"], ["evolution_api_key", "API key"], ["evolution_instance", "Instância"]],
  },
  meta: {
    label: "WhatsApp Cloud API (Meta, oficial)",
    help: "Fora da janela de 24 h a Meta só entrega modelos aprovados com um parâmetro no corpo.",
    fields: [["meta_wa_token", "Token"], ["meta_wa_phone_id", "Phone number ID"], ["meta_wa_template", "Nome do modelo (opcional)"], ["meta_wa_template_lang", "Idioma", "pt_BR"]],
  },
  callmebot: {
    label: "CallMeBot (gratuito, uso pessoal)",
    help: "Cada usuário gera a própria chave em callmebot.com e informa na aba Minha conta.",
    fields: [],
  },
  webhook: {
    label: "Webhook (n8n, Zapier…)",
    help: "Recebe POST com {phone, text, username}.",
    fields: [["whatsapp_webhook_url", "URL do webhook"]],
  },
};

function WahaPanel() {
  const [status, setStatus] = useState("");
  const [qr, setQr] = useState(0);
  const { busy, run } = useAction();
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const result = await api.get<{ status: string }>("/admin/whatsapp/status");
        if (!alive) return;
        setStatus(result.status);
        if (result.status === "SCAN_QR_CODE") setQr(Date.now());
      } catch (e) {
        if (alive) setStatus((e as Error).message);
      }
    };
    void poll();
    const timer = setInterval(poll, 6000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);
  const labels: Record<string, string> = {
    WORKING: "✅ Conectado",
    SCAN_QR_CODE: "Leia o QR Code com o WhatsApp (Aparelhos conectados)",
    STARTING: "Iniciando…",
    STOPPED: "Desconectado",
    FAILED: "Falhou: tente conectar de novo",
  };
  return (
    <div className="mt-4 rounded-xl bg-surface-2 p-4">
      <p className="text-sm font-semibold">{labels[status] ?? status}</p>
      {status === "SCAN_QR_CODE" && (
        <img src={`/api/admin/whatsapp/qr?t=${qr}`} alt="QR Code do WhatsApp" className="mt-3 w-56 rounded-xl bg-white p-2" />
      )}
      {status !== "WORKING" && (
        <button className="btn-ghost mt-3" disabled={busy} onClick={() => void run(() => api.post("/admin/whatsapp/start"), "Conexão iniciada")}>
          Conectar WhatsApp
        </button>
      )}
    </div>
  );
}

function MercadoLivrePanel({ saved }: { saved: boolean }) {
  const [params] = useSearchParams();
  const { data, reload } = useData<{ connected: boolean; ready: boolean; redirect_uri: string }>(
    "/admin/ml/status",
  );
  const { busy, run } = useAction();
  useEffect(() => {
    if (saved) void reload();
  }, [saved, reload]);
  if (!data) return null;
  const result = params.get("ml");
  return (
    <div className="mt-4 rounded-xl bg-surface-2 p-4 text-sm">
      <p className="text-muted">URI de redirecionamento (cadastre exatamente assim no aplicativo):</p>
      <p className="mb-3 font-mono text-xs break-all">{data.redirect_uri}</p>
      <p className="font-semibold">{data.connected ? "✅ Conta conectada" : "Conta não conectada"}</p>
      {result === "erro" && !data.connected && (
        <p className="text-bad">A autorização falhou. Confira as credenciais e a URI e tente de novo.</p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          className="btn-primary"
          disabled={busy || !data.ready}
          onClick={() =>
            void run(async () => {
              const { url } = await api.post<{ url: string }>("/admin/ml/authorize");
              window.location.assign(url);
            })
          }
        >
          Conectar Mercado Livre
        </button>
        {data.connected && (
          <button
            className="btn-danger"
            disabled={busy}
            onClick={() => void run(async () => { await api.del("/admin/ml/connection"); await reload(); })}
          >
            Desconectar
          </button>
        )}
      </div>
      {!data.ready && <p className="mt-2 text-xs text-warn">Salve o Client ID e o Client Secret antes.</p>}
    </div>
  );
}

function Integrations() {
  const { data, error, setData } = useData<ServerSettings>("/admin/settings");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const { busy, run } = useAction();
  if (!data) return error ? <ErrorBox message={error} /> : <Loading />;
  const value = (key: string) => draft[key] ?? data.values[key] ?? "";
  const set = (key: string, v: string) => setDraft({ ...draft, [key]: v });
  const provider = value("whatsapp_provider");

  const input = ([key, label, placeholder]: FieldSpec) => {
    const secret = data.secrets.includes(key);
    return (
      <Field key={key} label={label} hint={secret && data.configured[key] ? "Já configurado; preencha só para trocar." : undefined}>
        <input
          className="field"
          type={secret ? "password" : "text"}
          autoComplete="off"
          value={value(key)}
          placeholder={secret && data.configured[key] ? "••••••••" : placeholder}
          onChange={(e) => set(key, e.target.value)}
        />
      </Field>
    );
  };

  const save = () =>
    run(async () => {
      setData(await api.put<ServerSettings>("/admin/settings", { values: draft }));
      setDraft({});
    }, "Configurações salvas");

  return (
    <div className="space-y-4">
      <Section title="Endereço público" hint="Usado nos links dos e-mails e do WhatsApp.">
        {input(["public_url", "URL do BFTracker", "https://ofertas.seudominio.com"])}
      </Section>
      <Section title="E-mail (SMTP)" hint="Gmail exige uma senha de app.">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {SMTP.map(input)}
          <Field label="Segurança">
            <select className="field" value={value("smtp_security")} onChange={(e) => set("smtp_security", e.target.value)}>
              <option value="starttls">STARTTLS (587)</option>
              <option value="ssl">SSL (465)</option>
              <option value="none">Nenhuma</option>
            </select>
          </Field>
        </div>
      </Section>
      <Section title="WhatsApp">
        <Field label="Provedor">
          <select className="field" value={provider} onChange={(e) => set("whatsapp_provider", e.target.value)}>
            <option value="">Desativado</option>
            {Object.entries(PROVIDERS).map(([key, p]) => (
              <option key={key} value={key}>
                {p.label}
              </option>
            ))}
          </select>
        </Field>
        {PROVIDERS[provider] && (
          <>
            <p className="mt-2 text-sm text-muted">{PROVIDERS[provider].help}</p>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">{PROVIDERS[provider].fields.map(input)}</div>
            {provider === "waha" &&
              (data.values.whatsapp_provider === "waha" ? (
                <WahaPanel />
              ) : (
                <p className="mt-3 text-sm text-warn">Salve para conectar o WhatsApp.</p>
              ))}
          </>
        )}
      </Section>
      <Section title="Mercado Livre (API oficial)" hint="Opcional, para busca direta (inclusive usados). Exige aplicativo aprovado em developers.mercadolivre.com.br.">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {input(["ml_client_id", "Client ID"])}
          {input(["ml_client_secret", "Client Secret"])}
        </div>
        <MercadoLivrePanel saved={Object.keys(draft).length === 0} />
      </Section>
      <button className="btn-primary" disabled={busy || Object.keys(draft).length === 0} onClick={() => void save()}>
        {busy && <Spinner className="size-4" />} Salvar configurações
      </button>
    </div>
  );
}

const STATE_COLOR = { ok: "bg-emerald-500", blocked: "bg-amber-500", error: "bg-rose-500", unconfigured: "bg-slate-400", unknown: "bg-slate-400" };

function Sources() {
  const { data, error, reload } = useData<{
    sources: SourceRow[];
    custom: { kind: string; key: string; name: string; channel?: string; url?: string }[];
  }>("/admin/sources", () => true);
  const [form, setForm] = useState({ kind: "telegram", name: "", value: "" });
  const { busy, run } = useAction();
  if (!data) return error ? <ErrorBox message={error} /> : <Loading />;

  const group = (kind: "store" | "feed", title: string, hint: string) => (
    <Section title={title} hint={hint}>
      <ul className="divide-y divide-line">
        {data.sources
          .filter((s) => s.kind === kind)
          .map((s) => (
            <li key={s.key} className="flex items-center gap-3 py-1.5">
              <span className={`size-2.5 shrink-0 rounded-full ${s.enabled ? STATE_COLOR[s.state] : "bg-line"}`} title={s.state} />
              <div className="min-w-0 flex-1">
                <Toggle
                  label={s.name}
                  checked={s.enabled}
                  onChange={(v) => void run(async () => { await api.put(`/admin/sources/${s.key}/enabled`, { enabled: v }); await reload(); })}
                  hint={
                    s.message ||
                    (s.last_ok_at ? `ok ${ago(s.last_ok_at)} · ${s.last_items} itens` : s.covers || "aguardando primeira execução")
                  }
                />
              </div>
              {kind === "feed" && (
                <button className="btn-ghost !min-h-9 !px-2.5" aria-label={`Executar ${s.name} agora`} onClick={() => void run(() => api.post(`/admin/sources/${s.key}/run`), "Execução solicitada")}>
                  <Play className="size-3.5" />
                </button>
              )}
            </li>
          ))}
      </ul>
    </Section>
  );

  return (
    <div className="space-y-4">
      <Section title="Adicionar fonte" hint="Canal público do Telegram, feed RSS de um site ou loja na plataforma VTEX.">
        <form
          className="grid grid-cols-1 gap-3 sm:grid-cols-[10rem_1fr_1.5fr_auto] sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            void run(async () => {
              await api.post("/admin/custom-sources", form);
              setForm({ ...form, name: "", value: "" });
              await reload();
            }, "Fonte adicionada");
          }}
        >
          <Field label="Tipo">
            <select className="field" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              <option value="telegram">Canal Telegram</option>
              <option value="rss">Feed RSS</option>
              <option value="vtex">Loja VTEX</option>
            </select>
          </Field>
          <Field label="Nome">
            <input className="field" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label={form.kind === "telegram" ? "Canal" : "Endereço"}>
            <input
              className="field"
              required
              value={form.value}
              placeholder={form.kind === "telegram" ? "@canal" : "https://…"}
              onChange={(e) => setForm({ ...form, value: e.target.value })}
            />
          </Field>
          <button className="btn-primary" disabled={busy}>
            Adicionar
          </button>
        </form>
        {data.custom.length > 0 && (
          <ul className="mt-3 space-y-2">
            {data.custom.map((c) => (
              <li key={c.kind + c.key} className="flex items-center justify-between gap-2 rounded-xl bg-surface-2 p-2.5 text-sm">
                <span className="min-w-0 truncate">
                  <strong>{c.name}</strong> <span className="text-muted">{c.channel ? `@${c.channel}` : c.url}</span>
                </span>
                <button className="btn-danger !min-h-8 !px-2" aria-label={`Remover ${c.name}`} onClick={() => void run(async () => { await api.del(`/admin/custom-sources/${c.kind}/${c.key}`); await reload(); })}>
                  <Trash2 className="size-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>
      {group("store", "Lojas pesquisadas nos monitorados", "Se um site bloquear o acesso, o BFTracker espera e tenta mais tarde.")}
      {group("feed", "Fontes do radar", "Atualizadas continuamente.")}
    </div>
  );
}

function Users({ me }: { me: User }) {
  const { data, error, reload } = useData<User[]>("/admin/users");
  const [form, setForm] = useState({ username: "", password: "", is_admin: false });
  const { busy, run } = useAction();
  if (!data) return error ? <ErrorBox message={error} /> : <Loading />;
  return (
    <div className="space-y-4">
      <Section title="Usuários">
        <ul className="divide-y divide-line">
          {data.map((u) => (
            <li key={u.id} className="flex items-center justify-between gap-2 py-2 text-sm">
              <span>
                <strong>{u.username}</strong> {u.is_admin && <span className="chip">admin</span>}
              </span>
              {u.id !== me.id && (
                <button
                  className="btn-danger !min-h-9 !px-2.5"
                  aria-label={`Excluir ${u.username}`}
                  onClick={() => {
                    if (confirm(`Excluir ${u.username} e tudo o que é dele?`))
                      void run(async () => { await api.del(`/admin/users/${u.id}`); await reload(); });
                  }}
                >
                  <Trash2 className="size-4" />
                </button>
              )}
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Novo usuário">
        <form
          className="grid grid-cols-1 gap-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            void run(async () => {
              await api.post("/admin/users", form);
              setForm({ username: "", password: "", is_admin: false });
              await reload();
            }, "Usuário criado");
          }}
        >
          <Field label="Usuário">
            <input className="field" required minLength={3} autoCapitalize="none" autoComplete="off" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
          </Field>
          <Field label="Senha (8+)">
            <input className="field" required minLength={8} type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </Field>
          <Toggle label="Administrador" checked={form.is_admin} onChange={(v) => setForm({ ...form, is_admin: v })} />
          <button className="btn-primary sm:justify-self-end" disabled={busy}>
            Criar
          </button>
        </form>
      </Section>
    </div>
  );
}

function Stores() {
  const meta = useMeta();
  if (!meta) return <Loading />;
  return (
    <Section
      title="Lojas confiáveis"
      hint={`Retrato levantado em ${meta.stores_checked_at.split("-").reverse().join("/")}. A reputação muda: confira antes de comprar e consulte a lista “Evite esses sites” do Procon-SP.`}
    >
      <ul className="grid grid-cols-1 gap-2 md:grid-cols-2">
        {meta.stores.map((s) => (
          <li key={s.key} className="rounded-xl bg-surface-2 p-3">
            <div className="flex items-center justify-between gap-2">
              <strong>{s.name}</strong>
              <TrustBadge trust={{ level: s.trust, score: s.score, note: s.note, reputation_url: "" }} />
            </div>
            {s.note && <p className="mt-1 text-xs text-muted">{s.note}</p>}
            {s.reputation_url && (
              <a className="text-xs font-semibold text-accent" href={safeUrl(s.reputation_url)} target="_blank" rel="noreferrer">
                Ver reputação →
              </a>
            )}
          </li>
        ))}
      </ul>
    </Section>
  );
}

export function Settings({ user, onUser }: { user: User; onUser: (u: User) => void }) {
  const [params, setParams] = useSearchParams();
  const tabs = [
    ["conta", "Minha conta"],
    ...(user.is_admin
      ? [
          ["integracoes", "Integrações"],
          ["fontes", "Fontes"],
          ["usuarios", "Usuários"],
        ]
      : []),
    ["lojas", "Lojas"],
  ];
  const requested = params.get("aba") ?? "conta";
  const tab = tabs.some(([k]) => k === requested) ? requested : "conta";
  return (
    <>
      <PageHeader title="Configurações" />
      <div className="scrollbar-none -mx-4 mb-5 flex gap-2 overflow-x-auto px-4" role="tablist">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            className={`chip shrink-0 cursor-pointer !px-4 !py-2 !text-sm ${tab === key ? "chip-on" : ""}`}
            onClick={() => setParams({ aba: key }, { replace: true })}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "conta" && <Account user={user} onUser={onUser} />}
      {tab === "integracoes" && <Integrations />}
      {tab === "fontes" && <Sources />}
      {tab === "usuarios" && <Users me={user} />}
      {tab === "lojas" && <Stores />}
    </>
  );
}
