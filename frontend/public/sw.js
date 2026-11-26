/* Service worker do BFTracker: notificações push e abertura offline da interface. */
const CACHE = "bftracker-v1";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(["/", "/icon.svg", "/icon-192.png"])));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  // dados nunca vêm do cache
  if (request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/")) return;
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          const key = request.mode === "navigate" ? "/" : request;
          caches.open(CACHE).then((c) => c.put(key, copy));
        }
        return response;
      })
      .catch(async () => {
        const cached = await caches.match(request.mode === "navigate" ? "/" : request);
        return cached ?? Response.error();
      }),
  );
});

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data.json();
  } catch (_) {
    data = { title: "BFTracker", body: event.data ? event.data.text() : "" };
  }
  const actions = data.url ? [{ action: "store", title: "Ver oferta" }] : [];
  event.waitUntil(
    self.registration.showNotification(data.title || "BFTracker", {
      body: data.body || "",
      icon: "/icon-192.png",
      badge: "/badge.png",
      image: data.image || undefined,
      tag: data.id ? `bft-${data.id}` : undefined,
      requireInteraction: data.priority >= 3,
      vibrate: data.priority >= 3 ? [120, 60, 120] : [80],
      data: { url: data.url || "", path: data.path || "/" },
      actions,
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const { url, path } = event.notification.data || {};
  const external = event.action === "store" && url && url.startsWith("http");
  event.waitUntil(
    (async () => {
      if (external) return self.clients.openWindow(url);
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      const open = windows[0];
      if (open) {
        await open.focus();
        open.postMessage({ type: "navigate", path: path || "/" });
        return;
      }
      return self.clients.openWindow(path || "/");
    })(),
  );
});
