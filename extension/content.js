/*
 * Content script do BFTracker Companion.
 * Lê apenas os cartões de anúncios e ofertas visíveis nas páginas abertas pelo usuário
 * (Mercado Livre, OLX, hardMOB, X/Twitter, Enjoei) e envia ao background worker.
 * Nunca interage com logins, formulários ou verificações de segurança.
 */
(() => {
  const seenKeys = new Set();
  let timer = null;

  const text = (node) => (node ? node.textContent.replace(/\s+/g, " ").trim() : "");
  const money = (value) => {
    const match = String(value || "").match(/\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?/);
    return match ? Number(match[0].replace(/\./g, "").replace(",", ".")) : 0;
  };
  const moneyInText = (value) => {
    const match = String(value || "").match(
      /R\$\s*(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)/i,
    );
    return match ? money(match[1]) : 0;
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
  const findCoupon = (raw) => {
    const m =
      String(raw || "").match(
        /(?:cupom|c[óo]digo|voucher|use|aplique)\s*[:\-–=]?\s*["'“]?([A-Z0-9][A-Z0-9_-]{3,23})\b/i,
      ) || [];
    const code = (m[1] || "").toUpperCase();
    const stop = new Set([
      "CUPOM", "DESCONTO", "OFERTA", "MERCADO", "LIVRE", "AMAZON", "MAGALU", "KABUM",
      "SHOPEE", "GRATIS", "FRETE", "BLACK", "FRIDAY", "AQUI", "LINK", "PARA",
    ]);
    if (!code || stop.has(code) || /^\d+$/.test(code)) return "";
    return code;
  };

  function extractFromPage(onlyUnsent) {
    const items = [];
    const deals = [];
    const localItems = new Set();
    const localDeals = new Set();

    const addItem = (item) => {
      if (!item.title || !item.url || !(item.price > 0) || localItems.has(item.url)) return;
      if (onlyUnsent && seenKeys.has(`i:${item.url}:${item.price}`)) return;
      localItems.add(item.url);
      seenKeys.add(`i:${item.url}:${item.price}`);
      items.push({
        title: item.title.replace(/<[^>]{0,20}>/g, " ").trim().slice(0, 300),
        url: item.url.slice(0, 2000),
        price: item.price,
        original_price: item.original_price > item.price ? item.original_price : null,
        installments: item.installments || null,
        installment_value: item.installment_value || null,
        interest_free: item.interest_free ?? null,
        free_shipping: item.free_shipping ?? null,
        coupon: (item.coupon || "").slice(0, 200),
        seller: (item.seller || "").slice(0, 120),
        condition: item.condition || "",
        location: (item.location || "").slice(0, 160),
        image: (item.image || "").slice(0, 2000),
      });
    };

    const addDeal = (deal) => {
      const key = deal.external_id || deal.url;
      if (!deal.title || !deal.url || localDeals.has(key)) return;
      if (onlyUnsent && seenKeys.has(`d:${key}`)) return;
      localDeals.add(key);
      seenKeys.add(`d:${key}`);
      deals.push({
        source: deal.source || "navegador",
        source_name: (deal.source_name || "Navegador").slice(0, 80),
        external_id: (deal.external_id || "").slice(0, 240),
        title: deal.title.replace(/<[^>]{0,20}>/g, " ").trim().slice(0, 350),
        url: deal.url.slice(0, 2000),
        link: (deal.link || "").slice(0, 2000),
        description: (deal.description || "").slice(0, 1500),
        image: (deal.image || "").slice(0, 2000),
        store: (deal.store || "").slice(0, 80),
        price: deal.price > 0 ? deal.price : null,
        old_price: deal.old_price > (deal.price || 0) ? deal.old_price : null,
        coupon: (deal.coupon || "").slice(0, 120),
        is_coupon: Boolean(deal.is_coupon),
        is_flash: Boolean(deal.is_flash),
      });
    };

    const host = location.hostname;

    if (/(^|\.)olx\.com\.br$/.test(host)) {
      document.querySelectorAll("section.olx-adcard, [data-testid='ad-card']").forEach((card) => {
        const link = card.querySelector("a[data-testid='adcard-link'], a[href*='olx.com.br']");
        const priceNode = card.querySelector("h3.olx-adcard__price, [class*='price']");
        if (!link || !priceNode) return;
        const instText = text(card.querySelector("[data-testid='adcard-price-info']"));
        const inst = instText.match(/(\d{1,2})x\s*de\s*R\$\s*([\d.,]+)/i);
        const badges = text(card.querySelector(".olx-adcard__badges"));
        addItem({
          title: link.getAttribute("title") || text(link),
          url: https(link.href),
          price: money(text(priceNode)),
          installments: inst ? Number(inst[1]) : null,
          installment_value: inst ? money(inst[2]) : null,
          free_shipping: /frete gr[áa]tis/i.test(badges) ? true : null,
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
      const usedPage = /CONDITION_2230581|_Usado/i.test(location.href);
      document
        .querySelectorAll(
          "li.ui-search-layout__item, .poly-card, .ui-search-result, .promotion-item, .andes-card",
        )
        .forEach((card) => {
          const link = card.querySelector(
            "a.poly-component__title, a.ui-search-link, a.promotion-item__link-container, a[href*='MLB'], a[href*='/p/MLB']",
          );
          if (!link) return;
          const amounts = [...card.querySelectorAll(".andes-money-amount")];
          const mainAmount = amounts.find(
            (node) =>
              !node.closest(
                "s, del, .andes-money-amount--previous, .poly-price__installments, .ui-search-installments, .poly-component__coupons",
              ) && !node.classList.contains("andes-money-amount--previous"),
          );
          if (!mainAmount) return;
          const readAmount = (node) => {
            if (!node) return 0;
            const whole = text(node.querySelector(".andes-money-amount__fraction"));
            const cents = text(node.querySelector(".andes-money-amount__cents"));
            return whole ? money(cents ? `${whole},${cents}` : whole) : money(text(node));
          };
          const prevNode = card.querySelector("s .andes-money-amount, .andes-money-amount--previous");
          const instText = text(
            card.querySelector(".poly-price__installments, .ui-search-installments"),
          );
          const instMatch = instText.match(/(\d{1,2})x\s*(?:de\s*)?R?\$?\s*([\d.,]+)/i);
          const shipText = text(
            card.querySelector(".poly-component__shipping, .ui-search-item__shipping"),
          );
          const couponText = text(
            card.querySelector(
              ".poly-component__coupons, [class*='coupon'], .ui-search-item__highlight-label",
            ),
          );
          const sellerText = text(card.querySelector(".poly-component__seller")).replace(
            /^Por\s+/i,
            "",
          );
          const heading = card.querySelector(
            ".poly-component__title, .ui-search-item__title, .promotion-item__title, h2, h3",
          );
          const cardText = text(card);
          const cond =
            usedPage || /\bUsado\b/i.test(cardText)
              ? "used"
              : /\bRecondicionado\b/i.test(cardText)
                ? "refurbished"
                : "";
          addItem({
            title: text(heading) || text(link),
            url: https(link.href),
            price: readAmount(mainAmount),
            original_price: readAmount(prevNode),
            installments: instMatch ? Number(instMatch[1]) : null,
            installment_value: instMatch ? money(instMatch[2]) : null,
            interest_free: instMatch ? /sem juros/i.test(instText) : null,
            free_shipping: /frete gr[áa]tis|full/i.test(shipText) ? true : null,
            coupon: couponText,
            seller: sellerText,
            condition: cond,
            location: text(card.querySelector(".poly-component__location")),
            image: picture(card),
          });
        });

      const pdpTitle = text(document.querySelector("h1.ui-pdp-title"));
      const pdpPrice = document.querySelector(
        "#price .ui-pdp-price__second-line .andes-money-amount, .ui-pdp-price__second-line .andes-money-amount",
      );
      if (!items.length && pdpTitle && pdpPrice) {
        const whole = text(pdpPrice.querySelector(".andes-money-amount__fraction"));
        const cents = text(pdpPrice.querySelector(".andes-money-amount__cents"));
        const sub = text(document.querySelector(".ui-pdp-subtitle"));
        addItem({
          title: pdpTitle,
          url: https(location.href),
          price: money(cents ? `${whole},${cents}` : whole),
          condition: /usado/i.test(sub) ? "used" : /recondicionado/i.test(sub) ? "refurbished" : "new",
          image: picture(document.querySelector(".ui-pdp-gallery") || document.body),
        });
      }

      if (/\/cupons/i.test(location.pathname)) {
        document.querySelectorAll(".andes-card, [class*='coupon-card']").forEach((card, idx) => {
          const cardText = text(card);
          if (!/(%|\bR\$)\s*.*OFF/i.test(cardText)) return;
          const title =
            text(card.querySelector("h2, h3, [class*='title']")) || cardText.slice(0, 140);
          addDeal({
            source: "mercadolivre_cupons",
            source_name: "Mercado Livre · Cupons",
            external_id: `mlcoupon-${idx}-${title.slice(0, 40)}`,
            title: `Cupom Mercado Livre: ${title}`,
            url: https(location.href),
            description: cardText,
            store: "Mercado Livre",
            coupon: findCoupon(cardText),
            is_coupon: true,
          });
        });
      }
    }

    if (/(^|\.)hardmob\.com\.br$/.test(host)) {
      document.querySelectorAll("li.threadbit").forEach((row) => {
        if (row.className.includes("sticky") || row.querySelector(".sticky")) return;
        const link = row.querySelector("a.title");
        if (!link) return;
        const title = text(link);
        const rawHref = (link.getAttribute("href") || "").replace(/\?s=[^&]+/, "");
        const threadUrl = https(rawHref);
        const tid = (threadUrl.match(/threads\/(\d+)/) || [])[1] || "";
        if (!tid || !/R\$|cupom|%|gr[áa]tis|oferta|promo/i.test(title)) return;
        const info = row.querySelector("div.threadinfo");
        const preview = (info && info.getAttribute("title")) || "";
        const extMatch = preview.match(/https?:\/\/(?!(?:www\.)?hardmob\.com\.br)\S+/i);
        addDeal({
          source: "hardmob",
          source_name: "hardMOB Promoções",
          external_id: tid,
          title,
          url: threadUrl,
          link: extMatch ? https(extMatch[0]) : "",
          description: preview,
          price: moneyInText(title) || moneyInText(preview),
          coupon: findCoupon(`${title}\n${preview}`),
        });
      });

      if (!deals.length && /\/threads\//.test(location.pathname)) {
        const h1 = text(document.querySelector("h1, .threadtitle"));
        const post = document.querySelector("blockquote.postcontent, .postbody .content");
        const postText = text(post);
        if (h1 && post) {
          const extLink = [...post.querySelectorAll("a[href^='https://']")].find(
            (a) => !/hardmob\.com\.br/i.test(a.href),
          );
          addDeal({
            source: "hardmob",
            source_name: "hardMOB Promoções",
            external_id: (location.pathname.match(/threads\/(\d+)/) || [])[1] || "",
            title: h1,
            url: https(location.href),
            link: extLink ? https(extLink.href) : "",
            description: postText,
            price: moneyInText(h1) || moneyInText(postText),
            coupon: findCoupon(`${h1}\n${postText}`),
          });
        }
      }
    }

    if (/(^|\.)(x|twitter)\.com$/.test(host)) {
      document.querySelectorAll('article[data-testid="tweet"]').forEach((tweet) => {
        const timeNode = tweet.querySelector("a[href*='/status/'] time");
        const statusAnchor = timeNode ? timeNode.closest("a[href*='/status/']") : null;
        if (!statusAnchor) return;
        const tweetUrl = https(statusAnchor.href);
        const match = tweetUrl.match(/\/([^/]+)\/status\/(\d+)/);
        if (!match) return;
        const [, handle, tid] = match;
        const bodyNode = tweet.querySelector('[data-testid="tweetText"]');
        const body = text(bodyNode) || text(tweet);
        if (!/R\$|\bcupom\b|\boferta\b|\bpromo|\bdesconto\b|\bbug\b|\d{1,2}%\s*off/i.test(body)) {
          return;
        }
        const extAnchor = [...tweet.querySelectorAll("a[href^='https://']")].find(
          (a) => !/(^|\.)(x|twitter)\.com$/i.test(new URL(a.href).hostname),
        );
        const photo = tweet.querySelector('[data-testid="tweetPhoto"] img[src^="https://"]');
        const firstLine = body.replace(/https?:\/\/\S+/g, "").trim().slice(0, 220);
        addDeal({
          source: "x_twitter",
          source_name: `X · @${handle}`,
          external_id: tid,
          title: firstLine || body.slice(0, 200),
          url: tweetUrl,
          link: extAnchor ? https(extAnchor.href) : "",
          description: body,
          image: photo ? https(photo.src) : "",
          price: moneyInText(body),
          coupon: findCoupon(body),
        });
      });
    }

    if (/(^|\.)enjoei\.com\.br$/.test(host)) {
      document.querySelectorAll("a[href*='/p/']").forEach((link) => {
        const card = link.closest("[data-test*='card'], li, article, div") || link;
        const p = moneyInText(text(card));
        const title =
          link.getAttribute("title") || text(card.querySelector("h2, h3, span")) || text(link);
        if (p > 0 && title) {
          addItem({ title, url: https(link.href), price: p, condition: "used", image: picture(card) });
        }
      });
    }

    return { items, deals };
  }

  function scheduleAutoScan() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      chrome.runtime.sendMessage({ type: "bft:config" }, (cfg) => {
        if (chrome.runtime.lastError || !cfg || !cfg.autoCapture || !cfg.apiToken) return;
        const { items, deals } = extractFromPage(true);
        if (items.length || deals.length) {
          chrome.runtime.sendMessage({ type: "bft:ingest", items, deals });
        }
      });
    }, 1200);
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type === "bft:capture-now") {
      const { items, deals } = extractFromPage(false);
      chrome.runtime.sendMessage({ type: "bft:ingest", items, deals }, (res) => {
        sendResponse({ ...res, foundItems: items.length, foundDeals: deals.length });
      });
      return true;
    }
    return false;
  });

  scheduleAutoScan();
  window.addEventListener("scroll", scheduleAutoScan, { passive: true });
})();
