import {
  ArrowDownRight,
  BellRing,
  Plus,
  Radar,
  Smartphone,
  Target,
  Ticket,
  TrendingDown,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { DealCard } from "../components/cards";
import { Empty, ErrorBox, Loading, PageHeader, ProductImage, useAction } from "../components/ui";
import { WatchForm } from "../components/WatchForm";
import { brl, ago } from "../lib/format";
import { useData } from "../lib/hooks";
import { currentSubscription, enablePush, pushSupported } from "../lib/push";
import type { Dashboard as Data } from "../lib/types";

/** Black Friday: quarta sexta-feira de novembro + 1 (dia seguinte à Ação de Graças). */
export function blackFriday(year: number): Date {
  const first = new Date(year, 10, 1);
  const thursday = 1 + ((4 - first.getDay() + 7) % 7) + 21;
  return new Date(year, 10, thursday + 1);
}

function Countdown() {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.round((blackFriday(today.getFullYear()).getTime() - today.getTime()) / 864e5);
  if (days < -3 || days > 45) return null;
  const text =
    days > 1
      ? `Faltam ${days} dias para a Black Friday`
      : days === 1
        ? "A Black Friday é amanhã"
        : days === 0
          ? "Hoje é Black Friday!"
          : "Semana pós-Black Friday e Cyber Monday";
  return (
    <Link
      to="/radar?tipo=blackfriday"
      className="mb-5 block rounded-2xl bg-gradient-to-r from-violet-700 via-fuchsia-700 to-rose-600 p-4 text-white shadow-lg transition hover:brightness-110"
    >
      <p className="text-lg font-extrabold">🖤 {text}</p>
      <p className="text-sm text-white/85">
        O radar está de olho. Veja as ofertas e confira no histórico se o desconto é real.
      </p>
    </Link>
  );
}

function PushPrompt() {
  const [show, setShow] = useState(false);
  const { busy, run } = useAction();
  useEffect(() => {
    if (!pushSupported() || localStorage.getItem("push-dismissed")) return;
    currentSubscription().then((s) => setShow(!s));
  }, []);
  if (!show) return null;
  return (
    <div className="card mb-5 flex flex-wrap items-center gap-3 border-accent/50 p-4">
      <Smartphone className="size-6 text-accent" />
      <div className="min-w-48 flex-1">
        <p className="font-semibold">Receba os avisos neste aparelho</p>
        <p className="text-sm text-muted">Ative o push para saber na hora quando o preço cair.</p>
      </div>
      <button
        className="btn-primary"
        disabled={busy}
        onClick={() =>
          void run(async () => {
            await enablePush();
            setShow(false);
          }, "Push ativado neste aparelho")
        }
      >
        Ativar push
      </button>
      <button
        className="btn-ghost"
        onClick={() => {
          localStorage.setItem("push-dismissed", "1");
          setShow(false);
        }}
      >
        Agora não
      </button>
    </div>
  );
}

export function Dashboard() {
  const { data, error, loading, reload } = useData<Data>("/dashboard", () => true);
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();

  const stats = data && [
    { label: "Monitorados", value: data.stats.watches, icon: Target, to: "/monitorados" },
    { label: "Ofertas acompanhadas", value: data.stats.offers, icon: TrendingDown, to: "/monitorados" },
    { label: "No radar em 24 h", value: data.stats.deals_24h, icon: Radar, to: "/radar" },
    { label: "Cupons ativos", value: data.stats.coupons, icon: Ticket, to: "/cupons" },
    { label: "Avisos em 24 h", value: data.stats.alerts_24h, icon: BellRing, to: "/avisos" },
  ];

  return (
    <>
      <PageHeader
        title="Início"
        subtitle={
          data && (
            <span className="inline-flex items-center gap-1.5">
              <span className={`size-2 rounded-full ${data.worker_online ? "bg-emerald-500" : "bg-rose-500"}`} />
              {data.worker_online ? "Monitoramento em execução" : "Monitor parado: verifique o serviço worker"}
            </span>
          )
        }
      >
        <button className="btn-primary" onClick={() => setCreating(true)}>
          <Plus className="size-4" /> Monitorar produto
        </button>
      </PageHeader>
      <Countdown />
      <PushPrompt />
      <ErrorBox message={error} />
      {loading && !data && <Loading />}
      {data && (
        <>
          <section className="mb-7 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
            {stats!.map(({ label, value, icon: Icon, to }) => (
              <Link key={label} to={to} className="card p-4 transition hover:border-accent">
                <Icon className="mb-2 size-5 text-accent" />
                <p className="text-2xl font-bold">{value.toLocaleString("pt-BR")}</p>
                <p className="text-xs text-muted">{label}</p>
              </Link>
            ))}
          </section>

          <section className="mb-7">
            <h2 className="mb-3 text-lg font-bold">Quedas recentes nos seus produtos</h2>
            {data.drops.length === 0 ? (
              <Empty icon={<ArrowDownRight />} title="Nenhuma queda nos últimos dias">
                {data.stats.watches === 0
                  ? "Cadastre um produto, como “PS5”, para começar."
                  : "Assim que um preço cair, ele aparece aqui e você recebe o aviso."}
              </Empty>
            ) : (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {data.drops.map((d, i) => (
                  <Link key={i} to={`/monitorados/${d.watch_id}`} className="card flex items-center gap-3 p-3 hover:border-accent">
                    <ProductImage src={d.image} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{d.title}</p>
                      <p className="text-xs text-muted">
                        {d.watch} · {d.store} · {ago(d.at)}
                      </p>
                      <p>
                        <strong className="text-lg">{brl(d.price)}</strong>{" "}
                        <span className="text-sm text-muted line-through">{brl(d.previous)}</span>{" "}
                        <span className="text-sm font-bold text-good">
                          -{Math.round((1 - d.price / d.previous) * 100)}%
                        </span>
                      </p>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </section>

          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-lg font-bold">Quentes agora</h2>
              <Link to="/radar" className="text-sm font-semibold text-accent">
                Ver radar →
              </Link>
            </div>
            {data.hot.length === 0 ? (
              <Empty icon={<Radar />} title="O radar está coletando as primeiras ofertas">
                Em poucos minutos aparecem aqui as ofertas publicadas pelos sites e canais.
              </Empty>
            ) : (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {data.hot.map((deal) => (
                  <DealCard key={deal.id} deal={deal} />
                ))}
              </div>
            )}
          </section>
        </>
      )}
      {creating && (
        <WatchForm
          onClose={() => setCreating(false)}
          onSaved={(id) => {
            setCreating(false);
            void reload();
            if (id) navigate(`/monitorados/${id}`);
          }}
        />
      )}
    </>
  );
}
