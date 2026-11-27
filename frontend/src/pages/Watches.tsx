import { ExternalLink, Pause, Plus, Target } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Sparkline } from "../components/Chart";
import { Empty, ErrorBox, Loading, PageHeader, ProductImage, VerdictBadge } from "../components/ui";
import { WatchForm } from "../components/WatchForm";
import { ago, brl } from "../lib/format";
import { useData } from "../lib/hooks";
import type { Watch } from "../lib/types";

export function Watches() {
  const { data, error, loading, reload } = useData<Watch[]>("/watches", (u) => u.watches);
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();

  const productQueries = (data ?? [])
    .filter((w) => w.active && w.kind === "product" && w.query)
    .map((w) => `"${w.query.trim()}"`)
    .slice(0, 8);
  const xAllUrl = productQueries.length
    ? `https://x.com/search?q=${encodeURIComponent(`(${productQueries.join(" OR ")}) ("R$" OR cupom OR oferta OR promo) lang:pt`)}&src=typed_query&f=live`
    : "";

  return (
    <>
      <PageHeader title="Monitorados" subtitle="Seus produtos vigiados continuamente">
        {xAllUrl && (
          <a href={xAllUrl} target="_blank" rel="noreferrer" className="btn-ghost">
            🐦 Ofertas no X <ExternalLink className="size-3.5" />
          </a>
        )}
        <button className="btn-primary" onClick={() => setCreating(true)}>
          <Plus className="size-4" /> Novo
        </button>
      </PageHeader>
      <ErrorBox message={error} />
      {loading && !data && <Loading />}
      {data?.length === 0 && (
        <Empty icon={<Target />} title="Nada sendo monitorado ainda">
          <p>Cadastre “PS5”, um celular ou cole o link de um produto.</p>
          <button className="btn-primary mt-4" onClick={() => setCreating(true)}>
            <Plus className="size-4" /> Monitorar meu primeiro produto
          </button>
        </Empty>
      )}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {data?.map((watch) => (
          <Link
            key={watch.id}
            to={`/monitorados/${watch.id}`}
            className={`card rise flex min-w-0 flex-col gap-3 p-4 transition hover:border-accent ${watch.active ? "" : "opacity-60"}`}
          >
            <div className="flex gap-3">
              <ProductImage src={watch.image} className="size-20" />
              <div className="min-w-0 flex-1">
                <h2 className="flex items-center gap-2 font-bold">
                  <span className="truncate">{watch.name}</span>
                  {!watch.active && <Pause className="size-4 shrink-0 text-muted" aria-label="Pausado" />}
                </h2>
                {watch.best ? (
                  <>
                    <p className="text-2xl font-extrabold">{brl(watch.best.price)}</p>
                    <p className="truncate text-xs text-muted">
                      na {watch.best.store} · {watch.best.variant_label}
                    </p>
                  </>
                ) : (
                  <p className="mt-1 text-sm text-muted">
                    {watch.last_checked_at ? "Nenhuma oferta encontrada" : "Primeira busca em andamento…"}
                  </p>
                )}
              </div>
              <Sparkline values={watch.spark} />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
              <VerdictBadge verdict={watch.verdict} />
              <span>
                {watch.offers} ofertas · {watch.stores} lojas · {ago(watch.last_checked_at)}
              </span>
            </div>
            {(watch.cheapest_used || watch.target_price) && (
              <div className="flex flex-wrap gap-2 border-t border-line pt-2 text-xs">
                {watch.target_price && <span className="chip">🎯 Alvo {brl(watch.target_price)}</span>}
                {watch.cheapest_used && (
                  <span className="chip">♻️ Usado desde {brl(watch.cheapest_used.price)}</span>
                )}
              </div>
            )}
          </Link>
        ))}
      </div>
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
