import { ArrowLeft, CreditCard, ExternalLink, Pencil, RefreshCw, Trash2, Trophy } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { PriceChart } from "../components/Chart";
import { installmentText, OfferRow } from "../components/cards";
import {
  Empty,
  ErrorBox,
  Loading,
  PageHeader,
  Spinner,
  TrustBadge,
  useAction,
  VerdictBadge,
} from "../components/ui";
import { WatchForm } from "../components/WatchForm";
import { api } from "../lib/api";
import { ago, brl, safeUrl } from "../lib/format";
import { useData } from "../lib/hooks";
import type { Offer, SourceReport, WatchDetail } from "../lib/types";

const STATE: Record<SourceReport["state"], [string, string]> = {
  ok: ["bg-emerald-500", "ok"],
  blocked: ["bg-amber-500", "bloqueou o acesso"],
  error: ["bg-rose-500", "falhou"],
  unconfigured: ["bg-slate-400", "não configurada"],
  unknown: ["bg-slate-400", "aguardando"],
};

/** Atalhos para conferir à mão os sites de usados (útil quando um deles bloqueia robôs). */
function UsedLinks({ watch }: { watch: WatchDetail }) {
  const q = encodeURIComponent(watch.query);
  const area = watch.used_state ? `estado-${watch.used_state}` : "brasil";
  const slug = watch.query.trim().toLowerCase().replace(/\s+/g, "-");
  const links = [
    ["OLX", `https://www.olx.com.br/${area}?q=${q}&sf=1`],
    ["Mercado Livre usados", `https://lista.mercadolivre.com.br/${encodeURIComponent(slug)}_ITEM*CONDITION_2230581`],
    ["Enjoei", `https://www.enjoei.com.br/s?q=${q}`],
    ["Facebook Marketplace", `https://www.facebook.com/marketplace/search/?query=${q}`],
  ];
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted">
      Abrir e capturar:
      {links.map(([name, url]) => (
        <a key={name} className="chip !py-1.5 hover:border-accent" href={url} target="_blank" rel="noreferrer">
          {name} <ExternalLink className="size-3" />
        </a>
      ))}
      <Link to="/importar" className="font-semibold text-accent">
        Como enviar os anúncios →
      </Link>
    </div>
  );
}

function Highlight({
  title,
  icon,
  offer,
  detail,
}: {
  title: string;
  icon: React.ReactNode;
  offer: Offer;
  detail?: string;
}) {
  return (
    <a
      href={safeUrl(offer.url)}
      target="_blank"
      rel="noreferrer"
      className="card block p-4 transition hover:border-accent"
    >
      <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-accent uppercase">
        {icon} {title}
      </p>
      <p className="text-2xl font-extrabold">{brl(offer.price)}</p>
      <p className="flex items-center gap-1 text-sm font-semibold">
        {offer.store} <ExternalLink className="size-3.5" />
      </p>
      <p className="text-xs text-muted">{detail || installmentText(offer) || offer.variant_label}</p>
      <div className="mt-1">
        <TrustBadge trust={{ ...offer.trust, reputation_url: "" }} />
      </div>
    </a>
  );
}

export function WatchDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data, error, loading, reload } = useData<WatchDetail>(`/watches/${id}`, (u) => u.watches);
  const [variant, setVariant] = useState("");
  const [tab, setTab] = useState<"new" | "used" | "hidden">("new");
  const [sort, setSort] = useState("price");
  const [editing, setEditing] = useState(false);
  const [shown, setShown] = useState(30);
  const { busy, run } = useAction();

  // enquanto a primeira busca não termina, atualiza sozinho
  const pending = data && data.active && !data.last_checked_at;
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => void reload(), 4000);
    return () => clearInterval(timer);
  }, [pending, reload]);

  if (loading && !data) return <Loading />;
  if (!data) return <ErrorBox message={error || "Não encontrado"} />;

  const selected = data.variant_list.find((v) => v.key === variant) ?? data.variant_list[0];
  const pool = tab === "hidden" ? data.hidden_list : data.offer_list;
  const offers = pool
    .filter((o) => tab === "hidden" || (tab === "new" ? o.condition === "new" : o.condition !== "new"))
    .filter((o) => !variant || o.variant_key === variant)
    .sort((a, b) =>
      sort === "recent"
        ? b.first_seen_at.localeCompare(a.first_seen_at)
        : sort === "installments"
          ? (b.interest_free ? (b.installments ?? 0) : 0) - (a.interest_free ? (a.installments ?? 0) : 0) || a.price - b.price
          : a.price - b.price,
    );
  const rec = variant ? selected?.new : data.recommendation;
  const sources = Object.entries(data.report.sources ?? {});
  const count = (kind: "new" | "used") =>
    data.offer_list.filter(
      (o) => (kind === "new" ? o.condition === "new" : o.condition !== "new") && (!variant || o.variant_key === variant),
    ).length;

  return (
    <>
      <Link to="/monitorados" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-accent">
        <ArrowLeft className="size-4" /> Monitorados
      </Link>
      <PageHeader
        title={data.name}
        subtitle={
          <>
            {data.kind === "url" ? "Monitorado por link" : `Busca: “${data.query}”`} · verificado{" "}
            {ago(data.last_checked_at)} · a cada {data.interval_minutes} min
            {data.target_price && <> · alvo {brl(data.target_price)}</>}
          </>
        }
      >
        <button
          className="btn-ghost"
          disabled={busy || !data.active}
          onClick={() =>
            void run(() => api.post(`/watches/${data.id}/run`), "Verificação solicitada")
          }
        >
          <RefreshCw className="size-4" /> Verificar agora
        </button>
        <button className="btn-ghost" onClick={() => setEditing(true)}>
          <Pencil className="size-4" /> Editar
        </button>
        <button
          className="btn-danger"
          aria-label="Excluir monitoramento"
          onClick={() => {
            if (!confirm(`Excluir “${data.name}” e todo o histórico?`)) return;
            void run(async () => {
              await api.del(`/watches/${data.id}`);
              navigate("/monitorados");
            }, "Monitoramento excluído");
          }}
        >
          <Trash2 className="size-4" />
        </button>
      </PageHeader>
      <ErrorBox message={error} />

      {pending && (
        <div className="card mb-5 flex items-center gap-3 p-4">
          <Spinner className="size-5 text-accent" />
          <p className="text-sm">Buscando ofertas nas lojas. A primeira busca leva até um minuto.</p>
        </div>
      )}

      {data.variant_list.length > 1 && (
        <div className="scrollbar-none -mx-4 mb-5 flex gap-2 overflow-x-auto px-4 pb-1">
          <button
            className={`card shrink-0 cursor-pointer px-4 py-2 text-left ${!variant ? "!border-accent" : ""}`}
            aria-pressed={!variant}
            onClick={() => setVariant("")}
          >
            <span className="block text-sm font-semibold">Todas as variantes</span>
            <span className="text-xs text-muted">{data.variant_list.length} encontradas</span>
          </button>
          {data.variant_list.map((v) => (
            <button
              key={v.key}
              className={`card shrink-0 cursor-pointer px-4 py-2 text-left ${variant === v.key ? "!border-accent" : ""}`}
              aria-pressed={variant === v.key}
              onClick={() => setVariant(v.key)}
            >
              <span className="block text-sm font-semibold">{v.label}</span>
              <span className="text-xs text-muted">
                {v.new ? brl(v.new.best.price) : v.used ? `usado ${brl(v.used.best.price)}` : "—"} ·{" "}
                {v.stores} loja{v.stores > 1 ? "s" : ""}
              </span>
            </button>
          ))}
        </div>
      )}

      {rec && (
        <section className="mb-5">
          <h2 className="mb-2 text-lg font-bold">Onde comprar agora</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Highlight title="Melhor compra" icon={<Trophy className="size-4" />} offer={rec.best} />
            {rec.installment && (
              <Highlight
                title="Melhor parcelado"
                icon={<CreditCard className="size-4" />}
                offer={rec.installment}
                detail={`${installmentText(rec.installment)} · total ${brl(rec.installment.card_price ?? rec.installment.price)}`}
              />
            )}
            {rec.cheapest && (
              <Highlight title="Mais barata (confira a loja)" icon={<span>⚠️</span>} offer={rec.cheapest} />
            )}
          </div>
        </section>
      )}

      {selected && (
        <section className="card mb-5 p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-bold">
              Histórico · <span className="text-muted">{selected.label}</span>
            </h2>
            <VerdictBadge verdict={selected.verdict} />
          </div>
          <PriceChart history={selected.history} />
        </section>
      )}

      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-1 rounded-xl bg-surface-2 p-1">
          {(
            [
              ["new", `Novos (${count("new")})`],
              ["used", `Usados (${count("used")})`],
              ...(data.hidden_list.length ? [["hidden", "Ocultas"]] : []),
            ] as [typeof tab, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              className={`btn !min-h-9 ${tab === key ? "bg-violet-600 text-white" : "text-muted"}`}
              aria-pressed={tab === key}
              onClick={() => {
                setTab(key);
                setShown(30);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <select className="field !w-auto" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Ordenar">
          <option value="price">Menor preço</option>
          <option value="installments">Mais parcelas sem juros</option>
          <option value="recent">Mais recentes</option>
        </select>
      </div>

      {tab === "used" && data.kind === "product" && <UsedLinks watch={data} />}

      {offers.length === 0 ? (
        <Empty icon={<RefreshCw />} title="Nenhuma oferta aqui">
          {tab === "used" && !data.include_used
            ? "A busca de usados está desligada neste monitoramento."
            : "Veja abaixo a situação das fontes ou ajuste os filtros."}
        </Empty>
      ) : (
        <div className="space-y-2">
          {offers.slice(0, shown).map((offer) => (
            <OfferRow
              key={offer.id}
              offer={offer}
              onHide={(o) =>
                void run(async () => {
                  await api.post(`/offers/${o.id}/hidden`);
                  await reload();
                })
              }
            />
          ))}
          {offers.length > shown && (
            <button className="btn-ghost w-full" onClick={() => setShown(shown + 30)}>
              Mostrar mais ({offers.length - shown})
            </button>
          )}
        </div>
      )}

      {sources.length > 0 && (
        <details className="card mt-6 p-4">
          <summary className="cursor-pointer text-sm font-semibold">
            Fontes consultadas ({sources.filter(([, s]) => s.state === "ok").length} de {sources.length}{" "}
            responderam)
          </summary>
          <ul className="mt-3 grid gap-2 sm:grid-cols-2">
            {sources.map(([key, source]) => (
              <li key={key} className="flex items-start gap-2 text-xs">
                <span className={`mt-1 size-2 shrink-0 rounded-full ${STATE[source.state][0]}`} />
                <span>
                  <strong>{source.name}</strong>{" "}
                  <span className="text-muted">
                    {source.state === "ok" ? `${source.items} ofertas` : STATE[source.state][1]}
                    {source.message && ` — ${source.message}`}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {editing && (
        <WatchForm
          watch={data}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            setVariant("");
            void reload();
          }}
        />
      )}
    </>
  );
}
