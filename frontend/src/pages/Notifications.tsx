import { Bell, ExternalLink, Mail, MessageCircle, Smartphone } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Empty, ErrorBox, Loading, PageHeader, ProductImage } from "../components/ui";
import { api } from "../lib/api";
import { ago, safeUrl } from "../lib/format";
import { useData } from "../lib/hooks";
import type { Notice } from "../lib/types";

const CHANNEL = { push: Smartphone, email: Mail, whatsapp: MessageCircle };
const STATUS: Record<string, [string, string]> = {
  sent: ["text-good", "enviado"],
  pending: ["text-warn", "na fila"],
  failed: ["text-bad", "falhou"],
};

export function Notifications() {
  const [limit, setLimit] = useState(40);
  const { data, error, loading } = useData<{ items: Notice[]; unread: number }>(
    `/notifications?limit=${limit}`,
    (u) => u.notifications.length > 0,
  );

  // marca como lidas depois de mostrar
  useEffect(() => {
    if (data?.unread) void api.post("/notifications/read").catch(() => {});
  }, [data]);

  return (
    <>
      <PageHeader title="Avisos" subtitle="Tudo o que o BFTracker encontrou para você" />
      <ErrorBox message={error} />
      {loading && !data && <Loading />}
      {data?.items.length === 0 && (
        <Empty icon={<Bell />} title="Nenhum aviso ainda">
          Quando um preço cair ou surgir um cupom, aparece aqui.
        </Empty>
      )}
      <ul className="space-y-2">
        {data?.items.map((n) => (
          <li key={n.id} className={`card flex gap-3 p-3 ${n.read ? "" : "border-accent/70"}`}>
            <ProductImage src={n.image} className="size-14" />
            <div className="min-w-0 flex-1">
              <Link to={n.path} className="text-sm font-semibold hover:text-accent">
                {n.title}
              </Link>
              <p className="mt-0.5 line-clamp-6 text-xs whitespace-pre-line text-muted">{n.body}</p>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted">
                <span>{ago(n.created_at)}</span>
                {n.priority >= 3 && <span className="font-bold text-warn">Urgente</span>}
                {n.deliveries?.map((d) => {
                  const Icon = CHANNEL[d.channel as keyof typeof CHANNEL] ?? Bell;
                  const [color, label] = STATUS[d.status] ?? ["", d.status];
                  return (
                    <span key={d.channel} className={`inline-flex items-center gap-1 ${color}`} title={d.error}>
                      <Icon className="size-3.5" /> {label}
                    </span>
                  );
                })}
                {n.url && (
                  <a href={safeUrl(n.url)} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-1 font-semibold text-accent">
                    Ver oferta <ExternalLink className="size-3.5" />
                  </a>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
      {data && data.items.length === limit && limit < 100 && (
        <button className="btn-ghost mt-4 w-full" onClick={() => setLimit(100)}>
          Mostrar mais
        </button>
      )}
    </>
  );
}
