const $ = (id) => document.getElementById(id);

function setStatus(el, msg, ok = true) {
  el.textContent = msg;
  el.className = `status ${ok ? "ok" : "err"}`;
}

function renderWatches(data, serverUrl) {
  $("openApp").href = serverUrl || "#";
  $("watchesBox").style.display = "block";
  $("xAll").href = data.x_all_url;
  $("hardmobBtn").href = data.hardmob_url;
  const list = $("watchList");
  list.replaceChildren();
  (data.watches || []).slice(0, 12).forEach((w) => {
    const div = document.createElement("div");
    div.className = "watch";
    const title = document.createElement("div");
    title.className = "watch-title";
    title.textContent = w.name;
    const chips = document.createElement("div");
    chips.className = "chips";
    const links = [
      ["ML", w.links.ml_new],
      ...(w.include_used ? [["ML Usados", w.links.ml_used], ["OLX", w.links.olx]] : []),
      ["X ao vivo", w.links.x_live],
    ];
    links.forEach(([label, href]) => {
      const a = document.createElement("a");
      a.className = "chip";
      a.href = href;
      a.target = "_blank";
      a.rel = "noreferrer";
      a.textContent = label;
      chips.appendChild(a);
    });
    div.appendChild(title);
    div.appendChild(chips);
    list.appendChild(div);
  });
}

function refreshPing(serverUrl) {
  chrome.runtime.sendMessage({ type: "bft:ping" }, (res) => {
    if (!res || !res.ok) {
      $("configDetails").open = true;
      setStatus($("connStatus"), res?.error || "Não conectado", false);
      return;
    }
    setStatus(
      $("connStatus"),
      `Conectado como ${res.data.username} (${res.data.watches_count} monitorados)`,
      true,
    );
    renderWatches(res.data, serverUrl);
  });
}

chrome.runtime.sendMessage({ type: "bft:config" }, (cfg) => {
  if (!cfg) return;
  $("serverUrl").value = cfg.serverUrl || "";
  $("apiToken").value = cfg.apiToken || "";
  $("autoCapture").checked = cfg.autoCapture !== false;
  if (!cfg.apiToken) {
    $("configDetails").open = true;
  } else {
    refreshPing(cfg.serverUrl);
  }
});

$("autoCapture").addEventListener("change", async (e) => {
  await chrome.storage.local.set({ autoCapture: e.target.checked });
});

$("saveBtn").addEventListener("click", async () => {
  const serverUrl = $("serverUrl").value.trim().replace(/\/+$/, "");
  const apiToken = $("apiToken").value.trim();
  await chrome.storage.local.set({ serverUrl, apiToken });
  refreshPing(serverUrl);
});

$("captureNow").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) return;
  setStatus($("captureResult"), "Lendo página…", true);
  chrome.tabs.sendMessage(tab.id, { type: "bft:capture-now" }, (res) => {
    if (chrome.runtime.lastError || !res) {
      setStatus(
        $("captureResult"),
        "Abra uma página do Mercado Livre, OLX, hardMOB, X ou recarregue a aba.",
        false,
      );
      return;
    }
    if (!res.ok) {
      setStatus($("captureResult"), res.error || "Falha ao enviar", false);
      return;
    }
    const d = res.data || {};
    setStatus(
      $("captureResult"),
      `Enviados: ${res.foundItems || 0} anúncios (${d.matched || 0} nos monitorados) e ${res.foundDeals || 0} ofertas (${d.deals_new || 0} novas no radar).`,
      true,
    );
  });
});
