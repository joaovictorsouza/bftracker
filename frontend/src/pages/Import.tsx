import { BookmarkPlus, Check, Copy, Download } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { PageHeader, ProductImage, Spinner, useAction, useToast } from "../components/ui";
import { api } from "../lib/api";
import { capture } from "../lib/capture.js";
import { brl, safeUrl } from "../lib/format";

interface Item {
  title: string;
  url: string;
  price: number;
  condition: string;
  location: string;
  image: string;
}

interface Result {
  received: number;
  matched: number;
  watches: { id: number; name: string; found: number; new: number }[];
}

/** O fragmento vem de outra página: tudo aqui é tratado como dado não confiável. */
function readItems(hash: string): Item[] | null {
  const encoded = new URLSearchParams(hash.slice(1)).get("d");
  if (!encoded) return null;
  try {
    const bytes = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
    const data = JSON.parse(new TextDecoder().decode(bytes));
    return (Array.isArray(data.items) ? data.items : [])
      .slice(0, 100)
      .map((raw: Record<string, unknown>) => ({
        title: String(raw.title ?? "").slice(0, 300),
        url: String(raw.url ?? ""),
        price: Number(raw.price),
        condition: String(raw.condition ?? "").slice(0, 12),
        location: String(raw.location ?? "").slice(0, 160),
        image: /^https:\/\//.test(String(raw.image)) ? String(raw.image) : "",
      }))
      .filter((i: Item) => i.title.length > 1 && /^https:\/\//.test(i.url) && i.price > 0);
  } catch {
    return [];
  }
}

function Instructions() {
  const toast = useToast();
  const code = useMemo(
    () => `javascript:void((${capture.toString()})(${JSON.stringify(window.location.origin)}))`,
    [],
  );
  return (
    <div className="space-y-4">
      <section className="card p-4 md:p-5">
        <h2 className="font-bold">1. Instale o favorito</h2>
        <p className="mt-1 text-sm text-muted">
          <strong>No computador:</strong> arraste o botão abaixo para a barra de favoritos.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <a
            className="btn-primary cursor-grab"
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
          favorito, dê o nome “bft” e cole o código no endereço. Na página da loja, digite “bft” na
          barra de endereço e toque no favorito.
        </p>
      </section>
      <section className="card p-4 md:p-5">
        <h2 className="font-bold">2. Navegue e envie</h2>
        <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm text-muted">
          <li>Abra a busca na OLX ou no Mercado Livre (os atalhos ficam na aba Usados do produto).</li>
          <li>Toque no favorito “Enviar ao BFTracker”.</li>
          <li>Confira a lista e confirme. Os anúncios entram nos seus monitorados que combinarem.</li>
        </ol>
        <p className="mt-3 text-sm text-muted">
          Isto não é automático: só chega o que você enviar. Para avisos automáticos de usados,
          salve também a busca no aplicativo da OLX. Anúncios enviados saem da lista após 7 dias sem
          serem reenviados.
        </p>
      </section>
    </div>
  );
}

export function Import() {
  const location = useLocation();
  const navigate = useNavigate();
  const items = useMemo(() => readItems(location.hash), [location.hash]);
  const [result, setResult] = useState<Result | null>(null);
  const { busy, run } = useAction();

  return (
    <>
      <PageHeader
        title="Capturar do navegador"
        subtitle="Para sites que não permitem consulta automática, como OLX e Mercado Livre"
      >
        {items && (
          <button
            className="btn-ghost"
            onClick={() => {
              setResult(null);
              navigate("/importar", { replace: true });
            }}
          >
            Como instalar
          </button>
        )}
      </PageHeader>

      {result && (
        <div className="card mb-4 border-good/60 p-4">
          <p className="flex items-center gap-2 font-semibold">
            <Check className="size-5 text-good" />
            {result.matched} de {result.received} anúncios combinam com seus monitorados
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
          {result.matched === 0 && (
            <p className="mt-2 text-sm text-muted">
              Nenhum combinou. Confira os termos, os preços e a região dos seus{" "}
              <Link className="text-accent" to="/monitorados">
                monitorados
              </Link>
              .
            </p>
          )}
        </div>
      )}

      {items === null ? (
        <Instructions />
      ) : items.length === 0 ? (
        <div className="card p-5 text-sm">
          Não consegui ler os anúncios enviados. Tente capturar a página novamente.
        </div>
      ) : (
        <>
          {!result && (
            <button
              className="btn-primary mb-4 w-full sm:w-auto"
              disabled={busy}
              onClick={() =>
                void run(async () => setResult(await api.post<Result>("/import", { items })))
              }
            >
              {busy ? <Spinner className="size-4" /> : <Download className="size-4" />} Importar{" "}
              {items.length} anúncios
            </button>
          )}
          <ul className="space-y-2">
            {items.map((item) => (
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
                    {item.location}
                  </p>
                  <p className="truncate text-xs text-muted">{new URL(item.url).hostname}</p>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
