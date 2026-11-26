"""Extrai preço, cupom, loja, categoria e urgência de textos livres de ofertas."""

from __future__ import annotations

import re

from .text import PRICE_RE, normalize, parse_brl

CATEGORIES: dict[str, str] = {
    "celulares": "Celulares",
    "games": "Games",
    "informatica": "Notebooks e informática",
    "hardware": "Hardware e PC gamer",
    "tvs": "TVs e vídeo",
    "audio": "Fones e áudio",
    "wearables": "Relógios e wearables",
    "casa-inteligente": "Casa inteligente",
    "tablets": "Tablets e e-readers",
    "eletrodomesticos": "Eletrodomésticos",
    "casa": "Casa e móveis",
    "ferramentas": "Ferramentas e automotivo",
    "moda": "Moda e calçados",
    "beleza": "Beleza e saúde",
    "mercado": "Mercado",
    "livros": "Livros",
    "esporte": "Esporte e lazer",
    "infantil": "Infantil e brinquedos",
    "cupons": "Cupons",
    "outros": "Outros",
}

# ordem importa: a primeira categoria com palavra encontrada vence
_KEYWORDS: list[tuple[str, str]] = [
    ("games", r"ps[345]|playstation|xbox|nintendo|switch 2|dualsense|gamepad|joystick|"
              r"jogo|jogos|steam deck|rog ally|game pass|ps plus|gta"),
    ("wearables", r"smartwatch|smartband|galaxy watch|apple watch|relogio|mi band|watch fit"),
    ("audio", r"fone|fones|headphone|headset|earbuds|airpods|galaxy buds|soundbar|"
              r"caixa de som|jbl|speaker|home theater"),
    ("tablets", r"tablet|ipad|kindle|galaxy tab|e reader"),
    ("celulares", r"smartphone|celular|iphone|galaxy [samz]\d+|galaxy z|moto [ge]\d*|"
                  r"motorola edge|redmi|poco [xfmc]\d|xiaomi \d+|realme|razr"),
    ("hardware", r"placa de video|geforce|radeon|rtx ?\d{4}|rx ?\d{4}|ryzen|core i\d|"
                 r"processador|placa mae|memoria ram|ddr[45]|ssd|nvme|hd externo|"
                 r"water ?cooler|gabinete|fonte \d{3}w|pc gamer"),
    ("informatica", r"notebook|laptop|macbook|chromebook|computador|all in one|monitor|"
                    r"teclado|mouse|webcam|roteador|mesh|impressora|pen ?drive|"
                    r"cadeira gamer|windows"),
    ("tvs", r"tv|televisao|televisor|smart tv|projetor|fire tv|chromecast|google tv|roku"),
    ("casa-inteligente", r"echo|alexa|google nest|lampada inteligente|camera de seguranca|"
                         r"fechadura digital|robo aspirador|tomada inteligente"),
    ("eletrodomesticos", r"geladeira|refrigerador|fogao|cooktop|forno|micro ?ondas|lavadora|"
                         r"maquina de lavar|lava loucas|ar condicionado|ventilador|airfryer|"
                         r"fritadeira|cafeteira|liquidificador|batedeira|aspirador|purificador|"
                         r"panela eletrica|ferro de passar|climatizador|freezer"),
    ("ferramentas", r"furadeira|parafusadeira|ferramenta|compressor|lavadora de alta|pneu|"
                    r"automotivo|moto peca|trena|serra"),
    ("casa", r"sofa|colchao|cadeira|mesa|guarda roupa|panela|jogo de cama|toalha|"
             r"movel|estante|frigideira|faqueiro|garrafa|copo"),
    ("moda", r"tenis|camiseta|camisa|calca|jaqueta|bone|oculos|mochila|bolsa|sandalia|"
             r"chinelo|meia|cueca|vestido|nike|adidas|puma"),
    ("beleza", r"perfume|shampoo|creme|maquiagem|barbeador|aparador|secador|chapinha|"
               r"protetor solar|desodorante|whey|creatina|vitamina|suplemento"),
    ("infantil", r"brinquedo|lego|boneca|boneco|fralda|carrinho de bebe|infantil|bebe"),
    ("livros", r"livro|livros|box de livros|hq|manga"),
    ("esporte", r"bicicleta|bike|patinete|esteira|halter|academia|barraca|camping|bola"),
    ("mercado", r"cerveja|cafe|chocolate|leite|azeite|sabao|detergente|amaciante|racao|"
                r"vinho|papel higienico|arroz|biscoito"),
]
_CATEGORY_RE = [(cat, re.compile(rf"\b(?:{pattern})\b")) for cat, pattern in _KEYWORDS]

_FLASH_RE = re.compile(
    r"\b(relampago|corre+|corram|so hoje|somente hoje|por tempo limitado|poucas unidades|"
    r"ultimas unidades|acaba (?:hoje|rapido)|vai acabar|voando|imperdivel agora|"
    r"menor preco (?:historico|ja visto)|oferta do dia|\d{1,2}h apenas)\b"
)
_BUG_RE = re.compile(r"\b(bug|erro de preco|preco bugado|bugou|bugado)\b")
_BF_RE = re.compile(r"\b(black ?friday|black ?week|esquenta black|cyber ?monday|"
                    r"black november|semana black|\bblack\b d[aeo])\b")
_COUPON_WORD_RE = re.compile(r"\b(cupom|cupons|codigo promocional|voucher)\b")
_DEAL_HINT_RE = re.compile(
    r"\b(oferta|ofertas|promocao|promocoes|desconto|cupom|cupons|mais barato|menor preco|"
    r"black|por menos|abaixo de|sai por|cai para|despenca|derruba|\d{1,2}% off|em queda|"
    r"preco baixo|relampago)\b"
)
_CODE_STOP = {
    "DESCONTO", "CUPOM", "CUPONS", "OFERTA", "OFERTAS", "PROMO", "PARA", "NO", "NA", "DE",
    "DO", "DA", "COM", "APP", "SITE", "LINK", "AQUI", "AMAZON", "MAGALU", "SHOPEE", "KABUM",
    "MERCADO", "LIVRE", "OFF", "PIX", "FRETE", "GRATIS", "GRÁTIS", "PRIME", "VISTA",
    "CLIQUE", "RESGATE", "ATIVE", "APLIQUE", "USE", "LOJA", "ALIEXPRESS", "BLACK", "FRIDAY",
    "EXCLUSIVO", "ABAIXO", "ACIMA", "VÁLIDO", "VALIDO", "COMPRAS", "REAIS", "PRODUTO",
    "MERCADOLIVRE", "CARREFOUR", "AMERICANAS", "CASAS", "BAHIA", "NOVO", "DISPONÍVEL",
}
_COUPON_CODE_RE = re.compile(
    r"(?:cupom|c[óo]digo|voucher)(?:\s+(?:de\s+desconto|promocional|no\s+\w+|exclusivo))?"
    r"\s*(?:é|use|usar|aplique|:|=|👉|➡️|-)?\s*[:\-–]?\s*[\"'“]?"
    r"([A-Za-z0-9][A-Za-z0-9_\-]{3,24})",
    re.IGNORECASE,
)
_USE_CODE_RE = re.compile(
    r"(?:use|aplique|utilize|digite|resgate)\s+(?:o\s+)?(?:cupom\s+|c[óo]digo\s+)?[\"'“]?"
    r"([A-Z0-9]{4,24})\b"
)


def category_of(text: str) -> str:
    value = normalize(text)
    for category, pattern in _CATEGORY_RE:
        if pattern.search(value):
            return category
    return "outros"


def find_coupon(text: str) -> str:
    for pattern in (_COUPON_CODE_RE, _USE_CODE_RE):
        for match in pattern.finditer(text):
            code = match.group(1).strip("-_")
            if code.upper() in _CODE_STOP or code.isdigit() or code.lower().startswith("http"):
                continue
            # códigos reais são em maiúsculas ou misturam letras e números
            mixed = any(c.isdigit() for c in code) and any(c.isalpha() for c in code)
            if code.isupper() or mixed:
                return code
    return ""


def find_prices(text: str) -> tuple[float | None, float | None]:
    """(preço atual, preço antigo). Ignora parcelas e valores de desconto."""
    current: list[tuple[int, float]] = []
    old: float | None = None
    for match in PRICE_RE.finditer(text):
        value = parse_brl(match.group(1))
        if not value:
            continue
        before = text[max(0, match.start() - 28): match.start()].lower()
        after = text[match.end(): match.end() + 22].lower()
        if re.search(r"\d{1,2}\s*x\s*(de\s*)?$", before):
            continue  # parcela
        if re.search(r"^\s*(off|de desconto|de cashback|em cashback|de volta|a menos|mil)", after):
            continue
        if re.search(r"(desconto de|economi\w+|cashback de|acima de|a partir de compras de|"
                     r"compras de|m[íi]nim\w+ de?|limitado a|at[ée] )\s*$", before):
            continue
        if re.search(r"(\bera\b|\bde\b|antes:?|normal:?|de:)\s*$", before) and re.search(
            r"^.{0,20}?(por|\||→|➡|agora)", after, re.S
        ):
            old = value
            continue
        weight = 0
        if re.search(r"(por|apenas|s[óo]|pre[çc]o|agora|sai por|💰|🔥|💵|✅)\W{0,6}$", before):
            weight = -2
        if re.search(r"^\W{0,4}(no pix|[àa] vista|em 1x)", after):
            weight = -3
        current.append((weight, value))
    if not current:
        return None, old
    best_weight = min(w for w, _ in current)
    price = min(v for w, v in current if w == best_weight)
    if old is not None and old <= price:
        old = None
    return price, old


def classify(title: str, description: str = "") -> dict:
    full = f"{title}\n{description}"
    value = normalize(full)
    price, old = find_prices(title)
    if price is None:
        price, old = find_prices(full)
    coupon = find_coupon(full)
    return {
        "price": price,
        "old_price": old,
        "coupon": coupon,
        "category": category_of(title) if category_of(title) != "outros"
        else category_of(description[:200]),
        "is_flash": bool(_FLASH_RE.search(value)),
        "is_bug": bool(_BUG_RE.search(value)),
        "is_blackfriday": bool(_BF_RE.search(value)),
        "is_coupon": bool(coupon) or bool(_COUPON_WORD_RE.search(normalize(title))),
    }


def looks_like_deal(title: str, categories: list[str] | None = None) -> bool:
    """Separa ofertas de notícias comuns nos feeds de sites de tecnologia."""
    value = normalize(title)
    price, _ = find_prices(title)
    cats = normalize(" ".join(categories or []))
    if re.search(r"\b(ofertas?|promoc\w+|achados|descontos?)\b", cats):
        return True
    if re.search(r"\b(golpes?|vazamento|processad\w|multa|carros?|picape|suv|sedan|"
                 r"como |qual |quais |melhor \w+ para comprar|vale a pena|vale a pena pagar|"
                 r"quanto vale)", value):
        return False
    if price is not None and _DEAL_HINT_RE.search(value):
        return True
    strong = re.search(
        r"\b(oferta|cupom|\d{1,2}% off|menor preco|despenca|derruba preco|em promocao|"
        r"por menos|promocao relampago|mais barato)\b", value
    )
    percent = re.search(r"\d{1,2}\s?%", title) and _DEAL_HINT_RE.search(value)
    return bool(strong or percent)


def score_deal(info: dict, store_score: int, discount: float | None) -> int:
    score = 30
    score += 25 if info.get("is_flash") else 0
    score += 30 if info.get("is_bug") else 0
    score += 10 if info.get("coupon") else 0
    score += 5 if info.get("is_blackfriday") else 0
    if discount:
        score += min(int(discount // 2), 30)
    score += (store_score - 60) // 5
    return max(0, min(score, 100))
