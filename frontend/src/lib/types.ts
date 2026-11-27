export interface Trust {
  level: "alta" | "boa" | "atencao" | "desconhecida";
  score: number;
  note: string;
  reputation_url: string;
}

export interface Offer {
  id: number;
  source: string;
  store: string;
  store_key: string;
  seller: string;
  marketplace: boolean;
  title: string;
  url: string;
  image: string;
  price: number;
  card_price: number | null;
  original_price: number | null;
  installments: number | null;
  installment_value: number | null;
  interest_free: boolean | null;
  pix: boolean;
  free_shipping: boolean | null;
  coupon: string;
  condition: "new" | "used" | "refurbished";
  location: string;
  variant_key: string;
  variant_label: string;
  suspicious: boolean;
  hidden: boolean;
  previous_price: number | null;
  lowest_price: number;
  first_seen_at: string;
  trust: Trust;
}

export interface Verdict {
  level: "none" | "learning" | "record" | "great" | "good" | "fair" | "expensive" | "fake";
  label: string;
  lowest?: number;
  median?: number;
  change?: number;
  days?: number;
}

export interface WatchData {
  name: string;
  kind: "product" | "url";
  query: string;
  url: string;
  include_terms: string[];
  exclude_terms: string[];
  min_price: number | null;
  max_price: number | null;
  target_price: number | null;
  drop_percent: number;
  sources: string[];
  include_used: boolean;
  used_state: string;
  used_region: string;
  used_max_price: number | null;
  interval_minutes: number;
  active: boolean;
}

export interface SourceReport {
  state: "ok" | "blocked" | "error" | "unconfigured" | "unknown";
  name: string;
  items?: number;
  message?: string;
}

export interface Watch extends WatchData {
  id: number;
  last_checked_at: string | null;
  next_run_at: string | null;
  report: { sources?: Record<string, SourceReport> };
  offers: number;
  stores: number;
  variants: number;
  best: Offer | null;
  cheapest_used: Offer | null;
  verdict: Verdict;
  spark: number[];
  image: string;
}

export interface Recommendation {
  best: Offer;
  cheapest: Offer | null;
  installment: Offer | null;
}

export interface Variant {
  key: string;
  label: string;
  offers: number;
  stores: number;
  new: Recommendation | null;
  used: Recommendation | null;
  image: string;
  verdict: Verdict;
  history: { day: string; price: number; store: string; imported: boolean }[];
}

export interface WatchDetail extends Watch {
  recommendation: Recommendation | null;
  variant_list: Variant[];
  offer_list: Offer[];
  hidden_list: Offer[];
}

export interface Deal {
  id: number;
  source_name: string;
  title: string;
  url: string;
  link: string;
  image: string;
  store: string;
  store_key: string;
  price: number | null;
  old_price: number | null;
  discount_percent: number | null;
  coupon: string;
  category: string;
  is_flash: boolean;
  is_coupon: boolean;
  is_blackfriday: boolean;
  is_bug: boolean;
  published_at: string;
  trust: Trust | null;
  also: string[];
}

export interface Coupon {
  id: number;
  store: string;
  store_key: string;
  code: string;
  title: string;
  discount: string;
  conditions: string;
  url: string;
  source: string;
  is_flash: boolean;
  expires_at: string | null;
  first_seen_at: string;
}

export interface Prefs {
  channels: Record<string, boolean>;
  min_priority: Record<string, number>;
  quiet_start: string;
  quiet_end: string;
  quiet_allow_urgent: boolean;
}

export interface User {
  id: number;
  username: string;
  is_admin: boolean;
  email: string;
  whatsapp: string;
  callmebot_key: string;
  prefs: Prefs;
}

export interface StoreInfo {
  key: string;
  name: string;
  trust: Trust["level"];
  score: number;
  marketplace: boolean;
  note: string;
  reputation_url: string;
}

export interface Meta {
  categories: { key: string; name: string }[];
  stores: StoreInfo[];
  stores_checked_at: string;
  states: string[];
}

export interface Interest {
  id: number;
  name: string;
  categories: string[];
  keywords: string[];
  exclude_terms: string[];
  stores: string[];
  max_price: number | null;
  min_discount: number | null;
  only_flash: boolean;
  only_coupons: boolean;
  max_per_hour: number;
  active: boolean;
}

export interface Notice {
  id: number;
  kind: string;
  priority: number;
  title: string;
  body: string;
  url: string;
  path: string;
  image: string;
  created_at: string;
  read: boolean;
  deliveries?: { channel: string; status: string; error: string }[];
}

export interface Dashboard {
  stats: {
    watches: number;
    offers: number;
    deals_24h: number;
    coupons: number;
    alerts_24h: number;
  };
  drops: {
    watch_id: number;
    watch: string;
    title: string;
    store: string;
    price: number;
    previous: number;
    url: string;
    image: string;
    at: string;
  }[];
  hot: Deal[];
  worker_online: boolean;
  x_live_url?: string;
}

export interface ApiTokenInfo {
  id: number;
  name: string;
  prefix: string;
  token?: string;
  last_used_at: string | null;
  created_at: string;
}

export interface SourceRow {
  key: string;
  name: string;
  kind: "store" | "feed";
  covers: string;
  interval_seconds: number;
  enabled: boolean;
  state: SourceReport["state"];
  message: string;
  last_ok_at: string | null;
  last_run_at: string | null;
  blocked_until: string | null;
  last_items: number;
}
