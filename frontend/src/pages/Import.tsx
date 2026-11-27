import { BookmarkPlus, Check, Copy, Download, KeyRound, Puzzle, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { PageHeader, ProductImage, Spinner, useAction, useToast } from "../components/ui";
import { api } from "../lib/api";
import { capture } from "../lib/capture.js";
import { ago, brl, safeUrl } from "../lib/format";
import { useData } from "../lib/hooks";
import type { ApiTokenInfo } from "../lib/types";

interface Item {
  title: string;
  url: string;
  price: number;
  original_price?: number | null;
  installments?: number | null;
  installment_value?: number | null;
  interest_free?: boolean | null;
  free_shipping?: boolean | null;
  coupon?: string;
  seller?: string;
  condition: string;
  location: string;
  image: string;
}

interface DealPayload {
  source: string;
  source_name: string;
  external_id: string;
  title: string;
  url: string;
  link: string;
  description: string;
  image: string;
  store: string;
  price: number | null;
  old_price: number | null;
  coupon: string;
  is_coupon: boolean;
  is_flash: boolean;
}

interface Result {
  received: number;
  matched: number;
  deals_received?: number;
  deals_new?: number;
  deals_alerts?: number;
  watches: { id: number; name: string; found: number; new: number }[];
}

/** O fragmento vem de outra página: tudo aqui é tratado como dado não confiável. */
function readBundle(hash: string): { items: Item[]; deals: DealPayload[] } | null {
  const encoded = new URLSearchParams(hash.slice(1)).get("d");
  if (!encoded) return null;
  try {
    const bytes = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
    const data = JSON.parse(new TextDecoder().decode(bytes));
    const items: Item[] = (Array.isArray(data.items) ? data.items : [])
      .slice(0, 100)
      .map((raw: Record<string, unknown>) => ({
        title: String(raw.title ?? "").slice(0, 300),
        url: String(raw.url ?? ""),
        price: Number(raw.price),
        original_price: raw.original_price ? Number(raw.original_price) : null,
        installments: raw.installments ? Number(raw.installments) : null,
        installment_value: raw.installment_value ? Number(raw.installment_value) : null,
        interest_free: typeof raw.interest_free === "boolean" ? raw.interest_free : null,
        free_shipping: typeof raw.free_shipping === "boolean" ? raw.free_shipping : null,
        coupon: String(raw.coupon ?? "").slice(0, 200),
        seller: String(raw.seller ?? "").slice(0, 120),
        condition: String(raw.condition ?? "").slice(0, 12),
        location: String(raw.location ?? "").slice(0, 160),
        image: /^https:\/\//.test(String(raw.image)) ? String(raw.image) : "",
      }))
      .filter((i: Item) => i.title.length > 1 && /^https:\/\//.test(i.url) && i.price > 0);

    const deals: DealPayload[] = (Array.isArray(data.deals) ? data.deals : [])
      .slice(0, 100)
      .map((raw: Record<string, unknown>) => ({
        source: String(raw.source ?? "navegador").slice(0, 40),
        source_name: String(raw.source_name ?? "Navegador").slice(0, 80),
        external_id: String(raw.external_id ?? "").slice(0, 240),
        title: String(raw.title ?? "").slice(0, 350),
        url: String(raw.url ?? ""),
        link: /^https:\/\//.test(String(raw.link)) ? String(raw.link) : "",
        description: String(raw.description ?? "").slice(0, 1500),
        image: /^https:\/\//.test(String(raw.image)) ? String(raw.image) : "",
        store: String(raw.store ?? "").slice(0, 80),
        price: Number(raw.price) > 0 ? Number(raw.price) : null,
        old_price: Number(raw.old_price) > 0 ? Number(raw.old_price) : null,
        coupon: String(raw.coupon ?? "").slice(0, 120),
        is_coupon: Boolean(raw.is_coupon),
        is_flash: Boolean(raw.is_flash),
      }))
      .filter((d: DealPayload) => d.title.length > 1 && /^https:\/\//.test(d.url));

    return { items, deals };
  } catch {
    return { items: [], deals: [] };
  }
}

function ExtensionSection() {
  const { data: tokens, reload } = useData<ApiTokenInfo[]>("/tokens");
  const [createdToken, setCreatedToken] = useState("");
  const { busy, run } = useAction();
  const toast = useToast();

  return (
    <section className="card space-y-4 p-4 md:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 font-bold">
            <Puzzle className="size-5 text-accent" /> 1. Extensão BFTracker Companion (automática ao navegar)
          </h2>
          <p className="mt-1 text-sm text-muted">
            No Chrome, Brave ou Edge: enquanto você abre <strong>Mercado Livre</strong>,{" "}
            <strong>OLX</strong>, <strong>hardMOB Promoções</strong> ou <strong>X (Twitter)</strong>,
            a extensão envia os anúncios, cupons e ofertas direto aos seus monitorados e ao radar,
            sem precisar confirmar a cada página e sem compartilhar senhas ou cookies.
          </p>
        </div>
        <a href="/api/extension.zip" download className="btn-primary shrink-0">
          <Download className="size-4" /> Baixar extensão (.zip)
        </a>
      </div>

      <ol className="list-decimal space-y-1 pl-5 text-sm text-muted">
        <li>
          Baixe e descompacte o arquivo <code>bftracker-companion.zip</code> numa pasta fixa.
        </li>
        <li>
          No navegador, abra <code>chrome://extensions</code>, ative o{" "}
          <strong>Modo do desenvolvedor</strong> e clique em{" "}
          <strong>Carregar sem compactação</strong> escolhendo a pasta.
        </li>
        <li>Gere uma chave pessoal abaixo e cole no ícone da extensão.</li>
      </ol>

      <div className="rounded-xl bg-surface-2 p-3.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="flex items-center gap-1.5 text-sm font-semibold">
            <KeyRound className="size-4 text-accent" /> Chaves de acesso da extensão
          </p>
          <button
            type="button"
            className="btn-ghost !min-h-9"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                const res = await api.post<ApiTokenInfo>("/tokens", {
                  name: "BFTracker Companion",
                });
                setCreatedToken(res.token ?? "");
                await reload();
              }, "Chave gerada")
            }
          >
            Gerar nova chave
          </button>
        </div>

        {createdToken && (
          <div className="mt-3 rounded-xl border border-good/60 bg-bg p-3">
            <p className="text-xs font-semibold text-good">
              Copie agora (ela não será exibida completa novamente):
            </p>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <code className="min-w-0 flex-1 break-all text-xs">{createdToken}</code>
              <button
                type="button"
                className="btn-primary !min-h-8 !px-3 !text-xs"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(createdToken);
                    toast({ kind: "ok", text: "Chave copiada" });
                  } catch {
                    toast({ kind: "error", text: "Não foi possível copiar" });
                  }
                }}
              >
                <Copy className="size-3.5" /> Copiar
              </button>
            </div>
          </div>
        )}

        {tokens && tokens.length > 0 && (
          <ul className="mt-3 divide-y divide-line text-xs">
            {tokens.map((t) => (
              <li key={t.id} className="flex items-center justify-between gap-2 py-2">
                <span>
                  <strong>{t.name}</strong> · <code>{t.prefix}…</code>{" "}
                  <span className="text-muted">
                    · {t.last_used_at ? `usada ${ago(t.last_used_at)}` : "ainda não usada"}
                  </span>
                </span>
                <button
                  type="button"
                  className="btn-danger !min-h-7 !px-2"
                  aria-label="Revogar chave"
                  onClick={() =>
                    void run(async () => {
                      await api.del(`/tokens/${t.id}`);
                      await reload();
                    }, "Chave revogada")
                  }
                >
                  <Trash2 className="size-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function Instructions() {
  const toast = useToast();
  const code = useMemo(
    () => `javascript:void((${capture.toString()})(${JSON.stringify(window.location.origin)}))`,
    [],
  );
  return (
    <div className="space-y-4">
      <ExtensionSection />

      <section className="card p-4 md:p-5">
        <h2 className="font-bold">2. Alternativa rápida (celular ou qualquer navegador): Favorito</h2>
        <p className="mt-1 text-sm text-muted">
          Funciona no Safari/Chrome do celular e no Firefox, em páginas do{" "}
          <strong>Mercado Livre, OLX, hardMOB, X (Twitter), Enjoei</strong> ou qualquer loja.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <a
            className="btn-ghost cursor-grab"
            // o React bloqueia "javascript:" em href; aqui é intencional e gerado pelo app
            ref={(node) => node?.setAttribute("href", code)}
            onClick={(e) => {
              e.preventDefault();
              toast({ kind: "info", text: "Arraste este botão para a barra de favoritos" });
            }}
          >
            <BookmarkPlus className="size-4" /> Enviar ao BFTracker
          </a>
          <button
            type="button"
            className="btn-ghost"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(code);
                toast({ kind: "ok", text: "Código copiado" });
              } catch {
                toast({ kind: "error", text: "Não foi possível copiar" });
              }
            }}
          >
            <Copy className="size-4" /> Copiar código
          </button>
        </div>
        <p className="mt-3 text-sm text-muted">
          <strong>No celular:</strong> copie o código, salve qualquer página como favorito, edite o
          favorito, dê o nome “bft” e cole o código no endereço. Na página da loja ou busca no X,
          digite “bft” na barra de endereço e toque no favorito.
        </p>
      </section>
    </div>
  );
}

export function Import() {
  const location = useLocation();
  const navigate = useNavigate();
  const bundle = useMemo(() => readBundle(location.hash), [location.hash]);
  const [result, setResult] = useState<Result | null>(null);
  const { busy, run } = useAction();

  const totalCount = bundle ? bundle.items.length + bundle.deals.length : 0;

  return (
    <>
      <PageHeader
        title="Extensão e captura"
        subtitle="Acompanhe Mercado Livre (sem API oficial), OLX, hardMOB e X pelo seu navegador"
      >
        {bundle && (
          <button
            className="btn-ghost"
            onClick={() => {
              setResult(null);
              navigate("/importar", { replace: true });
            }}
          >
            Extensão e instruções
          </button>
        )}
      </PageHeader>

      {result && (
        <div className="card mb-4 border-good/60 p-4">
          <p className="flex items-center gap-2 font-semibold">
            <Check className="size-5 text-good" />
            {result.received > 0 && (
              <span>
                {result.matched} de {result.received} anúncios entraram nos monitorados
              </span>
            )}
            {result.received > 0 && (result.deals_received ?? 0) > 0 && <span> · </span>}
            {(result.deals_received ?? 0) > 0 && (
              <span>
                {result.deals_new ?? 0} novas ofertas/cupons entraram no radar
              </span>
            )}
          </p>
          <ul className="mt-2 space-y-1 text-sm">
            {result.watches.map((w) => (
              <li key={w.id}>
                <Link className="font-semibold text-accent" to={`/monitorados/${w.id}`}>
                  {w.name}
                </Link>
                : {w.found} anúncios, {w.new} novos
              </li>
            ))}
          </ul>
          {result.matched === 0 && (result.deals_new ?? 0) === 0 && (
            <p className="mt-2 text-sm text-muted">
              Nenhum item novo combinou. Confira os termos, os preços e a região dos seus{" "}
              <Link className="text-accent" to="/monitorados">
                monitorados
              </Link>{" "}
              ou veja o{" "}
              <Link className="text-accent" to="/radar">
                radar
              </Link>
              .
            </p>
          )}
        </div>
      )}

      {bundle === null ? (
        <Instructions />
      ) : totalCount === 0 ? (
        <div className="card p-5 text-sm">
          Não consegui ler anúncios nem ofertas com preço nesta página. Role a página para carregar
          os cartões e tente novamente.
        </div>
      ) : (
        <>
          {!result && (
            <button
              className="btn-primary mb-4 w-full sm:w-auto"
              disabled={busy}
              onClick={() =>
                void run(async () =>
                  setResult(
                    await api.post<Result>("/import", {
                      items: bundle.items,
                      deals: bundle.deals,
                    }),
                  ),
                )
              }
            >
              {busy ? <Spinner className="size-4" /> : <Download className="size-4" />} Importar{" "}
              {bundle.items.length > 0 && `${bundle.items.length} anúncios`}
              {bundle.items.length > 0 && bundle.deals.length > 0 && " e "}
              {bundle.deals.length > 0 && `${bundle.deals.length} ofertas/tópicos`}
            </button>
          )}
          <ul className="space-y-2">
            {bundle.items.map((item) => (
              <li key={item.url} className="card flex items-center gap-3 p-3">
                <ProductImage src={item.image} className="size-14" />
                <div className="min-w-0 flex-1">
                  <a
                    className="line-clamp-2 text-sm font-medium hover:text-accent"
                    href={safeUrl(item.url)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {item.title}
                  </a>
                  <p className="text-xs text-muted">
                    <strong className="text-sm text-text">{brl(item.price)}</strong>{" "}
                    {item.coupon && <span className="text-good">· {item.coupon} </span>}
                    {item.location}
                  </p>
                  <p className="truncate text-xs text-muted">{new URL(item.url).hostname}</p>
                </div>
              </li>
            ))}
            {bundle.deals.map((deal) => (
              <li key={deal.external_id || deal.url} className="card flex items-center gap-3 p-3">
                <ProductImage src={deal.image} className="size-14" />
                <div className="min-w-0 flex-1">
                  <a
                    className="line-clamp-2 text-sm font-medium hover:text-accent"
                    href={safeUrl(deal.link || deal.url)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {deal.title}
                  </a>
                  <p className="text-xs text-muted">
                    {deal.price ? (
                      <strong className="text-sm text-text">{brl(deal.price)} </strong>
                    ) : null}
                    {deal.coupon && <span className="text-good">Cupom: {deal.coupon} · </span>}
                    {deal.source_name}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
