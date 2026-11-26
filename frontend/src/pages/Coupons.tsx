import { ExternalLink, Search, Ticket } from "lucide-react";
import { useEffect, useState } from "react";
import { CouponCode } from "../components/cards";
import { Empty, ErrorBox, Loading, PageHeader } from "../components/ui";
import { ago, safeUrl, shortDate } from "../lib/format";
import { useData } from "../lib/hooks";
import type { Coupon } from "../lib/types";

interface Data {
  items: Coupon[];
  stores: { key: string; name: string; count: number }[];
}

export function Coupons() {
  const [store, setStore] = useState("");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setQ(search.trim()), 350);
    return () => clearTimeout(timer);
  }, [search]);
  const { data, error, loading } = useData<Data>(
    `/coupons?${new URLSearchParams({ store, q })}`,
    (u) => u.deals,
  );

  return (
    <>
      <PageHeader title="Cupons" subtitle="Códigos publicados pelas lojas, sites e canais. Confira as regras no carrinho." />
      <div className="relative mb-3">
        <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
        <input
          type="search"
          className="field !pl-9"
          placeholder="Buscar cupom ou loja…"
          aria-label="Buscar cupons"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <div className="scrollbar-none -mx-4 mb-4 flex gap-2 overflow-x-auto px-4">
        {[{ key: "", name: "Todas", count: 0 }, ...(data?.stores ?? [])].map((s) => (
          <button
            key={s.key}
            aria-pressed={store === s.key}
            className={`chip shrink-0 cursor-pointer !px-3.5 !py-2 !text-sm ${store === s.key ? "chip-on" : ""}`}
            onClick={() => setStore(s.key)}
          >
            {s.name} {s.count > 0 && <span className="opacity-70">{s.count}</span>}
          </button>
        ))}
      </div>
      <ErrorBox message={error} />
      {loading && !data && <Loading />}
      {data?.items.length === 0 && (
        <Empty icon={<Ticket />} title="Nenhum cupom por aqui ainda">
          Os cupons aparecem conforme as fontes publicam.
        </Empty>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {data?.items.map((c) => (
          <article key={c.id} className="card flex flex-col gap-2 p-4">
            <div className="flex items-center justify-between gap-2">
              <strong>{c.store}</strong>
              <span className="text-xs text-muted">{ago(c.first_seen_at)}</span>
            </div>
            {c.discount && <p className="text-xl font-extrabold text-good">{c.discount}</p>}
            <p className="line-clamp-3 text-sm">{c.title}</p>
            {c.conditions && (
              <details className="text-xs text-muted">
                <summary className="cursor-pointer">Regras</summary>
                <p className="mt-1 whitespace-pre-line">{c.conditions}</p>
              </details>
            )}
            <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-1">
              {c.code ? <CouponCode code={c.code} /> : <span className="text-xs text-muted">Resgate no link</span>}
              {c.url && (
                <a className="btn-ghost !min-h-9" href={safeUrl(c.url)} target="_blank" rel="noreferrer">
                  Usar <ExternalLink className="size-3.5" />
                </a>
              )}
            </div>
            {c.expires_at && <p className="text-xs text-warn">Válido até {shortDate(c.expires_at)}</p>}
          </article>
        ))}
      </div>
    </>
  );
}
