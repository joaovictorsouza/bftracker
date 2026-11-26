const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

export const brl = (value: number | null | undefined) =>
  value == null ? "—" : money.format(value);

export function ago(value: string | null | undefined): string {
  if (!value) return "nunca";
  const seconds = (Date.now() - new Date(value).getTime()) / 1000;
  if (seconds < 0) return "agora";
  if (seconds < 60) return "agora há pouco";
  if (seconds < 3600) return `há ${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `há ${Math.floor(seconds / 3600)} h`;
  const days = Math.floor(seconds / 86400);
  return days === 1 ? "ontem" : `há ${days} dias`;
}

export const shortDate = (value: string) => {
  const [, month, day] = value.slice(0, 10).split("-");
  return `${day}/${month}`;
};

/** Só deixa abrir endereços http(s): os links vêm de sites de terceiros. */
export const safeUrl = (url: string) => (/^https?:\/\//i.test(url) ? url : "#");

export const parseNumber = (value: string): number | null => {
  const clean = value.trim().replace(/[^\d.,]/g, "");
  if (!clean) return null;
  const normalized = clean.includes(",")
    ? clean.replace(/\./g, "").replace(",", ".")
    : /^\d{1,3}(\.\d{3})+$/.test(clean)
      ? clean.replace(/\./g, "")
      : clean;
  const number = Number(normalized);
  return Number.isFinite(number) && number > 0 ? number : null;
};
