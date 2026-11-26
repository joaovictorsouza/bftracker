import { Link2, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api } from "../lib/api";
import { parseNumber } from "../lib/format";
import { useMeta } from "../lib/hooks";
import type { Watch, WatchData } from "../lib/types";
import { Field, Modal, Spinner, Toggle, useAction } from "./ui";

const EMPTY: WatchData = {
  name: "",
  kind: "product",
  query: "",
  url: "",
  include_terms: [],
  exclude_terms: [],
  min_price: null,
  max_price: null,
  target_price: null,
  drop_percent: 3,
  sources: [],
  include_used: true,
  used_state: "",
  used_region: "",
  used_max_price: null,
  interval_minutes: 15,
  active: true,
};

const list = (value: string) =>
  value
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);

const money = (value: number | null) => (value == null ? "" : String(value).replace(".", ","));

export function WatchForm({
  watch,
  onClose,
  onSaved,
}: {
  watch?: Watch;
  onClose: () => void;
  onSaved: (id?: number) => void;
}) {
  const meta = useMeta();
  const { busy, run } = useAction();
  const initial = watch ?? EMPTY;
  const [kind, setKind] = useState(initial.kind);
  const [text, setText] = useState({
    name: initial.name,
    query: initial.query,
    url: initial.url,
    include: initial.include_terms.join(", "),
    exclude: initial.exclude_terms.join(", "),
    min: money(initial.min_price),
    max: money(initial.max_price),
    target: money(initial.target_price),
    usedMax: money(initial.used_max_price),
    region: initial.used_region,
  });
  const [state, setState] = useState(
    watch ? initial.used_state : (localStorage.getItem("uf") ?? ""),
  );
  const [includeUsed, setIncludeUsed] = useState(initial.include_used);
  const [interval, setIntervalValue] = useState(initial.interval_minutes);
  const [drop, setDrop] = useState(initial.drop_percent);
  const [active, setActive] = useState(initial.active);

  const bind = (key: keyof typeof text) => ({
    value: text[key],
    onChange: (e: { target: { value: string } }) => setText({ ...text, [key]: e.target.value }),
    className: "field",
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const payload: WatchData = {
      name: text.name,
      kind,
      query: kind === "product" ? text.query : "",
      url: kind === "url" ? text.url : "",
      include_terms: list(text.include),
      exclude_terms: list(text.exclude),
      min_price: parseNumber(text.min),
      max_price: parseNumber(text.max),
      target_price: parseNumber(text.target),
      used_max_price: parseNumber(text.usedMax),
      used_state: state,
      used_region: text.region,
      include_used: kind === "product" && includeUsed,
      sources: initial.sources,
      interval_minutes: interval,
      drop_percent: drop,
      active,
    };
    localStorage.setItem("uf", state);
    void run(
      async () => {
        if (watch) {
          await api.put(`/watches/${watch.id}`, payload);
          onSaved(watch.id);
        } else {
          const created = await api.post<Watch>("/watches", payload);
          onSaved(created.id);
        }
      },
      watch ? "Alterações salvas" : "Monitoramento criado. Buscando ofertas…",
    );
  };

  return (
    <Modal title={watch ? "Editar monitoramento" : "Monitorar produto"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-5">
        <div className="grid grid-cols-2 gap-2 rounded-xl bg-surface-2 p-1">
          {(
            [
              ["product", "Por nome", Search],
              ["url", "Por link", Link2],
            ] as const
          ).map(([value, label, Icon]) => (
            <button
              key={value}
              type="button"
              aria-pressed={kind === value}
              className={`btn ${kind === value ? "bg-violet-600 text-white" : "text-muted"}`}
              onClick={() => setKind(value)}
            >
              <Icon className="size-4" /> {label}
            </button>
          ))}
        </div>

        {kind === "product" ? (
          <Field
            label="O que você quer monitorar?"
            hint="Todas as palavras precisam aparecer no anúncio. Ex.: PS5, iPhone 17, RTX 5070."
          >
            <input {...bind("query")} required minLength={2} placeholder="PS5" data-autofocus />
          </Field>
        ) : (
          <Field label="Link do produto" hint="Qualquer loja que publique o preço na página.">
            <input {...bind("url")} type="url" required placeholder="https://…" />
          </Field>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Apelido (opcional)">
            <input {...bind("name")} placeholder="Videogame da sala" />
          </Field>
          <Field label="Preço-alvo" hint="Aviso urgente quando chegar nesse valor.">
            <input {...bind("target")} inputMode="decimal" placeholder="R$" />
          </Field>
        </div>

        {kind === "product" && (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Preço mínimo" hint="Ajuda a ignorar acessórios.">
                <input {...bind("min")} inputMode="decimal" placeholder="R$" />
              </Field>
              <Field label="Preço máximo">
                <input {...bind("max")} inputMode="decimal" placeholder="R$" />
              </Field>
              <Field label="Deve conter" hint="Separe por vírgula.">
                <input {...bind("include")} placeholder="slim, 1tb" />
              </Field>
              <Field label="Não pode conter">
                <input {...bind("exclude")} placeholder="portal, controle" />
              </Field>
            </div>

            <fieldset className="card space-y-3 p-4">
              <Toggle
                checked={includeUsed}
                onChange={setIncludeUsed}
                label="Procurar usados e recondicionados"
                hint="OLX da sua região, Mercado Livre, Trocafone e outros"
              />
              {includeUsed && (
                <div className="grid gap-4 sm:grid-cols-3">
                  <Field label="Seu estado">
                    <select className="field" value={state} onChange={(e) => setState(e.target.value)}>
                      <option value="">Brasil todo</option>
                      {meta?.states.map((uf) => (
                        <option key={uf} value={uf}>
                          {uf.toUpperCase()}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Cidade ou região">
                    <input {...bind("region")} placeholder="Campinas" />
                  </Field>
                  <Field label="Usado até">
                    <input {...bind("usedMax")} inputMode="decimal" placeholder="R$" />
                  </Field>
                </div>
              )}
            </fieldset>
          </>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Verificar a cada">
            <select className="field" value={interval} onChange={(e) => setIntervalValue(Number(e.target.value))}>
              {[5, 10, 15, 30, 60, 180, 720].map((m) => (
                <option key={m} value={m}>
                  {m < 60 ? `${m} minutos` : `${m / 60} hora${m > 60 ? "s" : ""}`}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Avisar queda a partir de">
            <select className="field" value={drop} onChange={(e) => setDrop(Number(e.target.value))}>
              {[...new Set([1, 3, 5, 10, 15, 20, drop])]
                .sort((a, b) => a - b)
                .map((p) => (
                  <option key={p} value={p}>
                    {p}%
                  </option>
                ))}
            </select>
          </Field>
        </div>

        {watch && <Toggle checked={active} onChange={setActive} label="Monitoramento ativo" />}
        {watch && (
          <p className="text-xs text-muted">
            Mudar o termo, os filtros ou os preços mínimo/máximo reinicia o histórico.
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn-primary" disabled={busy}>
            {busy && <Spinner className="size-4" />} {watch ? "Salvar" : "Começar a monitorar"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
