import { api } from "./api";

export const pushSupported = () =>
  "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

export const isIos = () => /iPad|iPhone|iPod/.test(navigator.userAgent);
export const isStandalone = () => window.matchMedia("(display-mode: standalone)").matches;

function decodeKey(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null;
  const registration = await navigator.serviceWorker.getRegistration();
  return (await registration?.pushManager.getSubscription()) ?? null;
}

export async function enablePush(): Promise<void> {
  if (!window.isSecureContext) {
    throw new Error("Push exige HTTPS. Configure um domínio (veja o README).");
  }
  if (!pushSupported()) {
    throw new Error(
      isIos()
        ? "No iPhone, adicione o BFTracker à Tela de Início e abra por lá para ativar o push."
        : "Este navegador não suporta notificações push.",
    );
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error("Permissão negada. Libere as notificações nas configurações do navegador.");
  }
  await navigator.serviceWorker.register("/sw.js");
  const registration = await navigator.serviceWorker.ready;
  const { key } = await api.get<{ key: string }>("/push/key");
  let subscription = await registration.pushManager.getSubscription();
  const applicationServerKey = decodeKey(key);
  if (subscription) {
    const old = new Uint8Array(subscription.options.applicationServerKey ?? new ArrayBuffer(0));
    if (old.join() !== applicationServerKey.join()) {
      await subscription.unsubscribe();
      subscription = null;
    }
  }
  subscription ??= await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey,
  });
  await api.post("/push/subscribe", subscription.toJSON());
}

export async function disablePush(): Promise<void> {
  const subscription = await currentSubscription();
  if (!subscription) return;
  await api.post("/push/unsubscribe", { endpoint: subscription.endpoint });
  await subscription.unsubscribe();
}
