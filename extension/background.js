/*
 * Service Worker da extensão BFTracker Companion.
 * Envia ofertas/anúncios capturados nas abas abertas pelo usuário direto para o seu BFTracker
 * usando uma chave pessoal revogável (Bearer bft_...), sem nunca exportar cookies ou senhas.
 */

async function loadConfig() {
  const stored = await chrome.storage.local.get(["serverUrl", "apiToken", "autoCapture"]);
  let serverUrl = (stored.serverUrl || "").trim().replace(/\/+$/, "");
  if (!serverUrl) {
    try {
      const resp = await fetch(chrome.runtime.getURL("default-config.json"));
      if (resp.ok) {
        const defaults = await resp.json();
        serverUrl = (defaults.serverUrl || "").trim().replace(/\/+$/, "");
      }
    } catch (_) {
      /* sem default-config */
    }
  }
  return {
    serverUrl,
    apiToken: (stored.apiToken || "").trim(),
    autoCapture: stored.autoCapture !== false,
  };
}

async function apiRequest(method, path, body) {
  const cfg = await loadConfig();
  if (!cfg.serverUrl || !cfg.apiToken) {
    throw new Error("Configure o endereço e a chave do BFTracker na extensão.");
  }
  const response = await fetch(`${cfg.serverUrl}/api${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${cfg.apiToken}`,
      "X-Requested-With": "bftracker",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error((data && data.detail) || `HTTP ${response.status}`);
  }
  return data;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type === "bft:config") {
    loadConfig().then(sendResponse);
    return true;
  }

  if (msg?.type === "bft:ping") {
    apiRequest("GET", "/ext/ping")
      .then((res) => sendResponse({ ok: true, data: res }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (msg?.type === "bft:ingest") {
    const items = Array.isArray(msg.items) ? msg.items.slice(0, 100) : [];
    const deals = Array.isArray(msg.deals) ? msg.deals.slice(0, 100) : [];
    if (!items.length && !deals.length) {
      sendResponse({ ok: true, data: { received: 0, matched: 0, deals_new: 0 } });
      return false;
    }
    apiRequest("POST", "/import", { items, deals })
      .then((res) => {
        const total = (res.matched || 0) + (res.deals_new || 0);
        const tabId = sender?.tab?.id || msg.tabId;
        if (tabId) {
          const text = total > 0 ? `+${total}` : `${items.length + deals.length}`;
          chrome.action.setBadgeText({ tabId, text: text.slice(0, 4) });
          chrome.action.setBadgeBackgroundColor({
            tabId,
            color: total > 0 ? "#10b981" : "#7c3aed",
          });
        }
        sendResponse({ ok: true, data: res });
      })
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }
  return false;
});
