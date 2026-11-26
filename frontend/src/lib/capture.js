/*
 * Código do favorito "Enviar ao BFTracker". Roda na página que VOCÊ abriu (OLX, Mercado
 * Livre ou qualquer loja), lê os anúncios visíveis e abre o BFTracker para confirmar.
 * Precisa ser autossuficiente: é convertido em texto e executado fora do aplicativo.
 */
export function capture(base) {
  const text = (node) => (node ? node.textContent.replace(/\s+/g, " ").trim() : "");
  const money = (value) => {
    const match = String(value).match(/\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?/);
    return match ? Number(match[0].replace(/\./g, "").replace(",", ".")) : 0;
  };
  const https = (url) => {
    try {
      const parsed = new URL(url, location.href);
      return parsed.protocol === "https:" ? parsed.href : "";
    } catch (_) {
      return "";
    }
  };
  const picture = (card) => {
    const img = card.querySelector("picture img, img");
    if (!img) return "";
    return https(img.getAttribute("data-src") || img.currentSrc || img.getAttribute("src") || "");
  };
  const found = new Map();
  const add = (item) => {
    if (item.title && item.url && item.price > 0 && !found.has(item.url)) {
      found.set(item.url, {
        title: item.title.replace(/<[^>]{0,20}>/g, " ").trim().slice(0, 300),
        url: item.url.slice(0, 2000),
        price: item.price,
        condition: item.condition || "",
        location: (item.location || "").slice(0, 160),
        image: (item.image || "").slice(0, 2000),
      });
    }
  };
  const host = location.hostname;

  if (/(^|\.)olx\.com\.br$/.test(host)) {
    document.querySelectorAll("section.olx-adcard, [data-testid='ad-card']").forEach((card) => {
      const link = card.querySelector("a[data-testid='adcard-link'], a[href*='olx.com.br']");
      const price = card.querySelector("h3.olx-adcard__price, [class*='price']");
      if (!link || !price) return;
      add({
        title: link.getAttribute("title") || text(link),
        url: https(link.href),
        price: money(text(price)),
        condition: "used",
        location: text(
          card.querySelector("p.olx-adcard__location") ||
            card.querySelector("[data-testid*='location']"),
        ),
        image: picture(card),
      });
    });
  }

  if (/(^|\.)mercadoli[vb]re\.com(\.br)?$/.test(host)) {
    const usedPage = /CONDITION_2230581/.test(location.href);
    document.querySelectorAll("li.ui-search-layout__item, .poly-card").forEach((card) => {
      const link = card.querySelector("a.poly-component__title, a[href*='MLB']");
      if (!link) return;
      // primeiro valor que não esteja riscado nem seja parcela
      const amount = [...card.querySelectorAll(".andes-money-amount")].find(
        (node) =>
          !node.closest("s, .andes-money-amount--previous, .poly-price__installments") &&
          !node.classList.contains("andes-money-amount--previous"),
      );
      if (!amount) return;
      const whole = text(amount.querySelector(".andes-money-amount__fraction"));
      const cents = text(amount.querySelector(".andes-money-amount__cents"));
      const heading = card.querySelector(".poly-component__title, h2, h3");
      add({
        title: text(heading) || text(link),
        url: https(link.href),
        price: money(cents ? `${whole},${cents}` : whole),
        condition: usedPage || /\bUsado\b/.test(text(card)) ? "used" : "",
        location: text(card.querySelector(".poly-component__location")),
        image: picture(card),
      });
    });
  }

  // página de um único produto, em qualquer loja (dados estruturados)
  if (found.size === 0) {
    const nodes = [];
    document.querySelectorAll('script[type="application/ld+json"]').forEach((script) => {
      try {
        const stack = [JSON.parse(script.textContent)];
        while (stack.length) {
          const node = stack.pop();
          if (Array.isArray(node)) stack.push(...node);
          else if (node && typeof node === "object") {
            if (node["@graph"]) stack.push(node["@graph"]);
            nodes.push(node);
          }
        }
      } catch (_) {
        /* bloco inválido */
      }
    });
    const product = nodes.find((n) => String(n["@type"]).includes("Product") && n.offers);
    const meta = (name) =>
      document.querySelector(`meta[property="${name}"], meta[itemprop="${name}"]`)?.content || "";
    const offer = product ? [].concat(product.offers)[0] : null;
    const price =
      Number(offer?.price ?? offer?.lowPrice) || money(meta("product:price:amount") || "");
    add({
      title: product?.name || meta("og:title"),
      url: https(location.href),
      price,
      condition: /used/i.test(offer?.itemCondition || "") ? "used" : "",
      image: https([].concat(product?.image || meta("og:image"))[0] || ""),
    });
  }

  const items = [...found.values()].slice(0, 100);
  if (!items.length) {
    alert("BFTracker: não encontrei anúncios com preço nesta página.");
    return items;
  }
  const bytes = new TextEncoder().encode(JSON.stringify({ items }));
  let binary = "";
  bytes.forEach((b) => (binary += String.fromCharCode(b)));
  // o conteúdo vai no fragmento (#), que o navegador não envia ao servidor
  const target = `${base}/importar#d=${encodeURIComponent(btoa(binary))}`;
  if (!window.open(target, "_blank")) location.href = target;
  return items;
}
