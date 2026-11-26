import {
  Bug,
  Copy,
  ExternalLink,
  EyeOff,
  Eye,
  MapPin,
  Tag,
  Ticket,
  Truck,
  Zap,
} from "lucide-react";
import { ago, brl, safeUrl } from "../lib/format";
import type { Deal, Offer } from "../lib/types";
import { ProductImage, TrustBadge, useToast } from "./ui";

export function installmentText(offer: Offer): string {
  if (!offer.installments || !offer.installment_value || offer.installments < 2) return "";
  const interest = offer.interest_free ? " sem juros" : offer.interest_free === false ? " com juros" : "";
  return `${offer.installments}x de ${brl(offer.installment_value)}${interest}`;
}

export function CouponCode({ code }: { code: string }) {
  const toast = useToast();
  return (
    <button
      type="button"
      className="inline-flex max-w-full cursor-pointer items-center gap-1.5 rounded-lg border border-dashed border-accent px-2 py-1 font-mono text-xs font-bold text-accent"
      title="Copiar cupom"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(code);
          toast({ kind: "ok", text: `Cupom ${code} copiado` });
        } catch {
          toast({ kind: "error", text: "Não foi possível copiar" });
        }
      }}
    >
      <span className="truncate">{code}</span>
      <Copy className="size-3.5 shrink-0" />
    </button>
  );
}

const CONDITION = { new: "", used: "Usado", refurbished: "Recondicionado" };

export function OfferRow({ offer, onHide }: { offer: Offer; onHide?: (offer: Offer) => void }) {
  const installments = installmentText(offer);
  const drop =
    offer.previous_price && offer.previous_price > offer.price
      ? Math.round((1 - offer.price / offer.previous_price) * 100)
      : 0;
  return (
    <article className={`card flex gap-3 p-3 sm:items-center ${offer.hidden ? "opacity-50" : ""}`}>
      <ProductImage src={offer.image} className="size-16 sm:size-20" />
      <div className="min-w-0 flex-1">
        <h3 className="line-clamp-2 text-sm font-medium">{offer.title}</h3>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          <strong className="text-text">{offer.store}</strong>
          <TrustBadge trust={offer.trust} />
          {offer.seller && offer.seller !== offer.store && <span>por {offer.seller}</span>}
          {CONDITION[offer.condition] && <span className="chip">{CONDITION[offer.condition]}</span>}
          {offer.location && (
            <span className="inline-flex items-center gap-1">
              <MapPin className="size-3" />
              {offer.location}
            </span>
          )}
          {offer.free_shipping && (
            <span className="inline-flex items-center gap-1 text-good">
              <Truck className="size-3" /> Frete grátis
            </span>
          )}
        </div>
        {offer.suspicious && (
          <p className="mt-1 text-xs font-medium text-warn">
            ⚠️ Muito abaixo do normal: pode ser golpe, peça ou acessório.
          </p>
        )}
        {offer.coupon && <p className="mt-1 text-xs text-accent">🎟️ {offer.coupon}</p>}
        <div className="mt-2 flex flex-wrap items-end justify-between gap-2">
          <div>
            <span className="text-lg font-bold">{brl(offer.price)}</span>
            {offer.pix && <span className="ml-1 text-xs text-muted">no Pix</span>}
            {drop > 0 && <span className="ml-2 text-xs font-bold text-good">↓ {drop}%</span>}
            {installments && <p className="text-xs text-muted">ou {installments}</p>}
          </div>
          <div className="flex gap-2">
            {onHide && (
              <button
                type="button"
                className="btn-ghost !min-h-9 !px-2.5"
                onClick={() => onHide(offer)}
                title={offer.hidden ? "Voltar a considerar" : "Não é o que procuro (ocultar)"}
                aria-label={offer.hidden ? "Mostrar oferta" : "Ocultar oferta"}
              >
                {offer.hidden ? <Eye className="size-4" /> : <EyeOff className="size-4" />}
              </button>
            )}
            <a className="btn-primary !min-h-9" href={safeUrl(offer.url)} target="_blank" rel="noreferrer">
              Ver <ExternalLink className="size-3.5" />
            </a>
          </div>
        </div>
      </div>
    </article>
  );
}

export function DealCard({ deal }: { deal: Deal }) {
  return (
    <article className="card rise flex flex-col overflow-hidden">
      <div className="flex gap-3 p-4">
        <ProductImage src={deal.image} className="size-20" />
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap gap-1">
            {deal.is_bug && (
              <span className="chip !border-transparent !bg-rose-500/15 !text-bad">
                <Bug className="size-3" /> Bug?
              </span>
            )}
            {deal.is_flash && (
              <span className="chip !border-transparent !bg-amber-500/15 !text-warn">
                <Zap className="size-3" /> Relâmpago
              </span>
            )}
            {deal.is_coupon && (
              <span className="chip !text-accent">
                <Ticket className="size-3" /> Cupom
              </span>
            )}
            {deal.is_blackfriday && (
              <span className="chip">
                <Tag className="size-3" /> Black Friday
              </span>
            )}
          </div>
          <h3 className="line-clamp-3 text-sm font-medium">{deal.title}</h3>
        </div>
      </div>
      <div className="mt-auto space-y-2 px-4 pb-4">
        <div className="flex flex-wrap items-baseline gap-2">
          {deal.price != null && <span className="text-xl font-bold">{brl(deal.price)}</span>}
          {deal.old_price != null && (
            <span className="text-sm text-muted line-through">{brl(deal.old_price)}</span>
          )}
          {deal.discount_percent != null && (
            <span className="text-sm font-bold text-good">-{Math.round(deal.discount_percent)}%</span>
          )}
        </div>
        {deal.coupon && <CouponCode code={deal.coupon} />}
        <div className="flex items-end justify-between gap-2">
          <div className="min-w-0 text-xs text-muted">
            <div className="flex flex-wrap items-center gap-x-2">
              {deal.store && <strong className="text-text">{deal.store}</strong>}
              {deal.trust && <TrustBadge trust={deal.trust} />}
            </div>
            <a
              href={safeUrl(deal.url)}
              target="_blank"
              rel="noreferrer"
              className="block truncate hover:text-accent"
              title={deal.also.length ? `Também em: ${deal.also.join(", ")}` : undefined}
            >
              {deal.source_name}
              {deal.also.length > 0 && ` +${deal.also.length}`} · {ago(deal.published_at)}
            </a>
          </div>
          <a className="btn-primary !min-h-9 shrink-0" href={safeUrl(deal.link || deal.url)} target="_blank" rel="noreferrer">
            Abrir <ExternalLink className="size-3.5" />
          </a>
        </div>
      </div>
    </article>
  );
}
