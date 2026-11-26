import { Pencil, Plus, Tags, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import {
  ChipSelect,
  Empty,
  ErrorBox,
  Field,
  Loading,
  Modal,
  PageHeader,
  Spinner,
  Toggle,
  useAction,
} from "../components/ui";
import { api } from "../lib/api";
import { brl, parseNumber } from "../lib/format";
import { useData, useMeta } from "../lib/hooks";
import type { Interest } from "../lib/types";

type Draft = Omit<Interest, "id">;

const EMPTY: Draft = {
  name: "",
  categories: [],
  keywords: [],
  exclude_terms: [],
  stores: [],
  max_price: null,
  min_discount: null,
  only_flash: false,
  only_coupons: false,
  max_per_hour: 6,
  active: true,
};

const SUGGESTIONS: [string, Partial<Draft>][] = [
  ["Cupons relâmpago do Mercado Livre", { stores: ["mercadolivre"], only_coupons: true }],
  ["Celulares com 20% ou mais", { categories: ["celulares"], min_discount: 20 }],
  ["Games em relâmpago", { categories: ["games"], only_flash: true }],
  ["TVs até R$ 2.500", { categories: ["tvs"], max_price: 2500 }],
];

const words = (v: string) =>
  v
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

function Form({
  initial,
  id,
  onClose,
  onSaved,
}: {
  initial: Draft;
  id?: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const meta = useMeta();
  const { busy, run } = useAction();
  const [draft, setDraft] = useState(initial);
  const [keywords, setKeywords] = useState(initial.keywords.join(", "));
  const [exclude, setExclude] = useState(initial.exclude_terms.join(", "));
  const [max, setMax] = useState(initial.max_price ? String(initial.max_price) : "");
  const [discount, setDiscount] = useState(initial.min_discount ? String(initial.min_discount) : "");
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((d) => ({ ...d, [key]: value }));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const payload: Draft = {
      ...draft,
      keywords: words(keywords),
      exclude_terms: words(exclude),
      max_price: parseNumber(max),
      min_discount: parseNumber(discount),
    };
    void run(async () => {
      if (id) await api.put(`/interests/${id}`, payload);
      else await api.post("/interests", payload);
      onSaved();
    }, "Interesse salvo");
  };

  return (
    <Modal title={id ? "Editar interesse" : "Novo interesse"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-5">
        <Field label="Nome">
          <input className="field" required value={draft.name} onChange={(e) => set("name", e.target.value)} placeholder="Notebooks baratos" />
        </Field>
        <div>
          <p className="mb-2 text-sm font-medium">Categorias (nenhuma = todas)</p>
          <ChipSelect
            options={meta?.categories ?? []}
            value={draft.categories}
            onChange={(v) => set("categories", v)}
          />
        </div>
        <div>
          <p className="mb-2 text-sm font-medium">Lojas (nenhuma = todas)</p>
          <ChipSelect
            options={(meta?.stores ?? []).slice(0, 18)}
            value={draft.stores}
            onChange={(v) => set("stores", v)}
          />
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Palavras-chave (qualquer uma)" hint="Separe por vírgula.">
            <input className="field" value={keywords} onChange={(e) => setKeywords(e.target.value)} placeholder="rtx, ryzen" />
          </Field>
          <Field label="Ignorar se contiver">
            <input className="field" value={exclude} onChange={(e) => setExclude(e.target.value)} placeholder="usado, capa" />
          </Field>
          <Field label="Preço máximo">
            <input className="field" inputMode="decimal" value={max} onChange={(e) => setMax(e.target.value)} placeholder="R$" />
          </Field>
          <Field label="Desconto mínimo (%)">
            <input className="field" inputMode="numeric" value={discount} onChange={(e) => setDiscount(e.target.value)} />
          </Field>
        </div>
        <div>
          <Toggle label="Só ofertas relâmpago e bugs" checked={draft.only_flash} onChange={(v) => set("only_flash", v)} />
          <Toggle label="Só cupons" checked={draft.only_coupons} onChange={(v) => set("only_coupons", v)} />
          <Toggle label="Ativo" checked={draft.active} onChange={(v) => set("active", v)} />
        </div>
        <Field label="Máximo de avisos por hora">
          <input
            className="field"
            type="number"
            min={1}
            max={60}
            value={draft.max_per_hour}
            onChange={(e) => set("max_per_hour", Number(e.target.value))}
          />
        </Field>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn-primary" disabled={busy}>
            {busy && <Spinner className="size-4" />} Salvar
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function Interests() {
  const meta = useMeta();
  const { data, error, loading, reload } = useData<Interest[]>("/interests");
  const { run } = useAction();
  const [editing, setEditing] = useState<{ draft: Draft; id?: number } | null>(null);
  const categoryName = (key: string) => meta?.categories.find((c) => c.key === key)?.name ?? key;
  const storeName = (key: string) => meta?.stores.find((s) => s.key === key)?.name ?? key;

  return (
    <>
      <PageHeader title="Meus interesses" subtitle="Categorias, lojas e palavras que merecem um aviso quando surgir oferta">
        <button className="btn-primary" onClick={() => setEditing({ draft: EMPTY })}>
          <Plus className="size-4" /> Novo
        </button>
      </PageHeader>
      <div className="mb-4 flex flex-wrap gap-2">
        {SUGGESTIONS.map(([name, values]) => (
          <button key={name} className="chip cursor-pointer !py-1.5 hover:border-accent" onClick={() => setEditing({ draft: { ...EMPTY, ...values, name } })}>
            + {name}
          </button>
        ))}
      </div>
      <ErrorBox message={error} />
      {loading && !data && <Loading />}
      {data?.length === 0 && (
        <Empty icon={<Tags />} title="Nenhum interesse cadastrado">
          Escolha uma sugestão acima ou crie o seu.
        </Empty>
      )}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {data?.map(({ id, ...interest }) => (
          <article key={id} className={`card p-4 ${interest.active ? "" : "opacity-60"}`}>
            <div className="flex items-start justify-between gap-2">
              <h2 className="font-bold">{interest.name}</h2>
              <div className="flex gap-1">
                <button className="btn-ghost size-9 !min-h-9 !p-0" aria-label={`Editar ${interest.name}`} onClick={() => setEditing({ draft: interest, id })}>
                  <Pencil className="size-4" />
                </button>
                <button
                  className="btn-danger size-9 !min-h-9 !p-0"
                  aria-label={`Excluir ${interest.name}`}
                  onClick={() => {
                    if (confirm(`Excluir “${interest.name}”?`))
                      void run(async () => {
                        await api.del(`/interests/${id}`);
                        await reload();
                      });
                  }}
                >
                  <Trash2 className="size-4" />
                </button>
              </div>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {interest.categories.map((c) => <span key={c} className="chip">{categoryName(c)}</span>)}
              {interest.stores.map((s) => <span key={s} className="chip">🏬 {storeName(s)}</span>)}
              {interest.keywords.map((k) => <span key={k} className="chip">“{k}”</span>)}
              {interest.only_flash && <span className="chip">⚡ Relâmpago</span>}
              {interest.only_coupons && <span className="chip">🎟️ Cupons</span>}
              {interest.max_price && <span className="chip">até {brl(interest.max_price)}</span>}
              {interest.min_discount && <span className="chip">≥ {interest.min_discount}% off</span>}
              <span className="chip">máx. {interest.max_per_hour}/h</span>
            </div>
          </article>
        ))}
      </div>
      {editing && (
        <Form
          initial={editing.draft}
          id={editing.id}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void reload();
          }}
        />
      )}
    </>
  );
}
