import pytest

from app.core import dealtext, matching, stores
from app.core.text import brl, normalize, parse_brl


@pytest.mark.parametrize(
    "raw,expected",
    [("R$ 3.800", 3800), ("1.234,56", 1234.56), ("4699.9", 4699.9), (5199, 5199), ("", None),
     ("R$ 0,00", None), ("R$ 12,5", 12.5)],
)
def test_parse_brl(raw, expected):
    assert parse_brl(raw) == expected


def test_format_and_normalize():
    assert brl(1234.5) == "R$ 1.234,50"
    assert normalize("PlayStation®5 Slim 1 TB") .startswith("ps5")
    assert "1tb" in normalize("SSD 1 TB")


CRITERIA = matching.Criteria("PS5")


@pytest.mark.parametrize(
    "title",
    [
        "Console Sony PlayStation 5 Slim 1TB",
        "PlayStation 5 Pro",
        "PS5 Slim Digital com 2 controles",
        "Console PlayStation 5 + 2 Jogos Digitais",
        "Playstation5 825GB branco",
        "Sony CFI-2016 PlayStation 5 Standard Edition",
        "Stea PlayStation®5 console (slim)",
        "Bundle GTA VI + PlayStation 5 Slim Disk",
        "Usado: PlayStation 5 825GB",
    ],
)
def test_accepts_console(title):
    assert matching.matches(title, CRITERIA)


@pytest.mark.parametrize(
    "title",
    [
        "Controle DualSense para PS5",
        "Jogo Marvel's Spider-Man 2 PS5",
        "Marvel's Spider-Man 2 - PS5",
        "Capa protetora PS5 Slim",
        "Playstation Portal Para Console PS5",
        "Base de carregamento compatível com PS5",
        "Headset Pulse 3D PS5",
        "PS5 com defeito, para retirada de peças",
        "Procuro PS5 usado",
        "Console PlayStation 4 Slim",
        "Somente a caixa do PS5",
        "Minecraft PS5 Midia Fisica - Playstation",
        "Silent Hill F Day One Edition PS5 Midia Fisica",
        "EA Sports FC 27 PlayStation 5 Standard",
        "Mão Alienígena Suporte Controle Vídeo Game PS4 PS5 Xbox",
        "Estação Carregamento Controle Ps5 Dual Carregador Usb Dock",
    ],
)
def test_rejects_accessories_and_other_products(title):
    assert not matching.matches(title, CRITERIA)


def test_searching_for_an_accessory_still_works():
    criteria = matching.Criteria("controle dualsense")
    assert matching.matches("Controle Sem Fio DualSense PS5", criteria)


def test_include_exclude_and_price_range():
    criteria = matching.Criteria("iphone 17", include_terms=["256gb"], exclude_terms=["pro"],
                                 min_price=4000, max_price=7000)
    assert matching.matches("Apple iPhone 17 256 GB Preto", criteria, 5600)
    assert not matching.matches("Apple iPhone 17 Pro 256GB", criteria, 6000)
    assert not matching.matches("Apple iPhone 17 512GB", criteria, 6000)
    assert not matching.matches("Apple iPhone 17 256GB", criteria, 9000)
    assert not matching.matches("Apple iPhone 16 256GB", criteria, 5000)


def test_variants_distinguish_models():
    def key(title):
        return matching.variant_of(title, "ps5")[0]

    assert key("PlayStation 5 Pro 2TB") != key("PlayStation 5 Slim 1TB")
    assert key("PS5 Slim Digital 825GB") != key("PS5 Slim 825GB com leitor de discos")
    assert key("PS5 825 GB branco") == key("Console PlayStation 5, SSD 825GB, preto")
    assert "digital" in key("PS5 Edição Digital")
    assert matching.variant_of("iPhone 17 256GB 8GB RAM", "iphone 17")[1] == "256GB"
    assert "16GB RAM" in matching.variant_of("Notebook X 16GB RAM SSD 512GB", "notebook")[1]


def test_condition_detection():
    assert matching.detect_condition("iPhone 13 Seminovo") == "used"
    assert matching.detect_condition("iPhone 13 Recondicionado") == "refurbished"
    assert matching.detect_condition("iPhone 13 lacrado") == "new"


def test_comparator_variant_text():
    criteria = matching.Criteria("ps5")
    assert matching.best_variant_title("Produto genérico", "PS5 Pro 2TB", criteria) == "PS5 Pro 2TB"
    described = matching.best_variant_title("PS5 Digital", "PlayStation 5 825GB", criteria)
    assert "825gb" in described


def test_deal_prices_ignore_installments_and_discount_values():
    price, old = dealtext.find_prices(
        "Smart TV de R$ 3.000 por R$ 2.199,90 no Pix ou 10x de R$ 244,00"
    )
    assert (price, old) == (2199.90, 3000)
    assert dealtext.find_prices("Cupom R$ 30 OFF em compras acima de R$ 100")[0] is None


@pytest.mark.parametrize(
    "text,code",
    [
        ("Use o cupom TECH20 no carrinho", "TECH20"),
        ("Cupom: LIVREOFF", "LIVREOFF"),
        ("🎟️ CUPOM: MEGABR03", "MEGABR03"),
        ("aplique o cupom da loja para economizar", ""),
        ("Cupom de desconto Amazon", ""),
    ],
)
def test_find_coupon(text, code):
    assert dealtext.find_coupon(text) == code


def test_classify_flash_bug_blackfriday():
    info = dealtext.classify("CORRE! Bug no iPhone 17 por R$ 999 na Black Friday")
    assert info["is_flash"] and info["is_bug"] and info["is_blackfriday"]
    assert info["category"] == "celulares"
    assert dealtext.classify("Geladeira Frost Free 400L")["category"] == "eletrodomesticos"


def test_news_filter():
    assert dealtext.looks_like_deal("Magalu derruba preço do volante G29 com 35% OFF no PIX")
    assert dealtext.looks_like_deal("Galaxy Tab sai por menos de R$ 5.000")
    assert not dealtext.looks_like_deal("Black Friday: Amazon é a marca mais usada em golpes")
    assert not dealtext.looks_like_deal("Chevrolet derrete preços da S10 e picape fica barata")
    assert not dealtext.looks_like_deal("WhatsApp agora permite agendar mensagens")


def test_stores():
    assert stores.identify("Magalu")[0] == "magalu"
    assert stores.identify("KaBuM!")[0] == "kabum"
    assert stores.find_by_url("https://www.amazon.com.br/dp/X").key == "amazon"
    assert stores.find_by_url("https://amazon.com.br.golpe.example/x") is None
    assert stores.find_in_text("Oferta no Mercado Livre hoje").key == "mercadolivre"
    assert stores.trust_of("casasbahia")["level"] == "atencao"
    assert stores.trust_of("loja-qualquer")["level"] == "desconhecida"
