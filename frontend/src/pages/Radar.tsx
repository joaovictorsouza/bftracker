import { Radar as RadarIcon, RefreshCw, Search } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { DealCard } from "../components/cards";
import { Empty, ErrorBox, Loading, PageHeader, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { LIVE_EVENT, useMeta, type LiveUpdate } from "../lib/hooks";
import type { Deal } from "../lib/types";

const KINDS = [
  ["", "Tudo"],
  ["flash", "⚡ Relâmpago"],
  ["coupon", "🎟️ Com cupom"],
  ["blackfriday", "🖤 Black Friday"],
  ["bug", "🐞 Bugs"],
];

export function Radar() {
  const meta = useMeta();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [items, setItems] = useState<Deal[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [fresh, setFresh] = useState(false);
  const sequence = useRef(0);

  const kind = params.get("tipo") ?? "";
  const category = params.get("categoria") ?? "";
  const store = params.get("loja") ?? "";
  const sort = params.get("ordem") ?? "recent";
  const q = params.get("q") ?? "";

  const set = useCallback(
    (key: string, value: string) =>
      setParams(
        (current) => {
          const copy = new URLSearchParams(current);
          if (value) copy.set(key, value);
          else copy.delete(key);
          return copy;
        },
        { replace: true },
      ),
    [setParams],
  );

  useEffect(() => {
    const timer = setTimeout(() => set("q", search.trim()), 350);
    return () => clearTimeout(timer);
  }, [search, set]);

  const load = useCallback(
    async (offset: number) => {
      const ticket = ++sequence.current;
      setLoading(true);
      const query = new URLSearchParams({ q, category, store, kind, sort, offset: String(offset) });
      try {
        const result = await api.get<{ items: Deal[]; next_offset: number | null }>(`/deals?${query}`);
        if (ticket !== sequence.current) return;
        setItems((old) => (offset ? [...old, ...result.items] : result.items));
        setNext(result.next_offset);
        setError("");
        if (!offset) setFresh(false);
      } catch (e) {
        if (ticket === sequence.current) setError((e as Error).message);
      } finally {
        if (ticket === sequence.current) setLoading(false);
      }
    },
    [q, category, store, kind, sort],
  );

  useEffect(() => {
    void load(0);
  }, [load]);

  useEffect(() => {
    const listener = (event: Event) => {
      if (!(event as CustomEvent<LiveUpdate>).detail.deals) return;
      // não puxa o tapete de quem está lendo mais abaixo
      if (window.scrollY < 200) void load(0);
      else setFresh(true);
    };
    window.addEventListener(LIVE_EVENT, listener);
    return () => window.removeEventListener(LIVE_EVENT, listener);
  }, [load]);

  return (
    <>
      <PageHeader title="Radar de ofertas" subtitle="Sites de tecnologia, fóruns e canais, ao vivo" />
      <div className="mb-4 space-y-3">
        <div className="relative">
          <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
          <input
            type="search"
            className="field !pl-9"
            placeholder="Buscar ofertas ou cupons…"
            aria-label="Buscar ofertas"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="scrollbar-none -mx-4 flex gap-2 overflow-x-auto px-4">
          {KINDS.map(([value, label]) => (
            <button
              key={value}
              aria-pressed={kind === value}
              className={`chip shrink-0 cursor-pointer !px-3.5 !py-2 !text-sm ${kind === value ? "chip-on" : ""}`}
              onClick={() => set("tipo", value)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-3 gap-2">
          <select className="field" value={category} onChange={(e) => set("categoria", e.target.value)} aria-label="Categoria">
            <option value="">Categorias</option>
            {meta?.categories.map((c) => (
              <option key={c.key} value={c.key}>
                {c.name}
              </option>
            ))}
          </select>
          <select className="field" value={store} onChange={(e) => set("loja", e.target.value)} aria-label="Loja">
            <option value="">Lojas</option>
            {meta?.stores.map((s) => (
              <option key={s.key} value={s.key}>
                {s.name}
              </option>
            ))}
          </select>
          <select className="field" value={sort} onChange={(e) => set("ordem", e.target.value)} aria-label="Ordenar">
            <option value="recent">Recentes</option>
            <option value="hot">Mais quentes</option>
            <option value="price">Menor preço</option>
          </select>
        </div>
      </div>
      {fresh && (
        <button
          className="btn-primary fixed top-20 left-1/2 z-40 -translate-x-1/2 shadow-xl"
          onClick={() => {
            window.scrollTo({ top: 0, behavior: "smooth" });
            void load(0);
          }}
        >
          <RefreshCw className="size-4" /> Novas ofertas
        </button>
      )}
      <ErrorBox message={error} />
      {!loading && items.length === 0 && !error && (
        <Empty icon={<RadarIcon />} title="Nenhuma oferta com esses filtros">
          Tente remover algum filtro. O radar atualiza a cada poucos minutos.
        </Empty>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((deal) => (
          <DealCard key={deal.id} deal={deal} />
        ))}
      </div>
      {loading && items.length === 0 && <Loading />}
      {next !== null && items.length > 0 && (
        <button className="btn-ghost mt-4 w-full" disabled={loading} onClick={() => void load(next)}>
          {loading && <Spinner className="size-4" />} Carregar mais
        </button>
      )}
    </>
  );
}
