"""Monta a lista de fontes ativas a partir da configuração atual."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.appsettings import get_json
from .amazon import Amazon
from .base import FeedSource, StoreSource
from .comparators import Buscape, Zoom
from .feeds import (
    PROMOBIT_PAGES,
    RSS_FEEDS,
    TELEGRAM_CHANNELS,
    Promobit,
    RssFeed,
    TelegramChannel,
)
from .gatry import GatryFeed, GatrySearch
from .imap_alerts import ImapAlertsFeed
from .kabum import Kabum
from .mercadolivre import MercadoLivre
from .olx import Olx
from .pelando import (
    PELANDO_COUPON_STORES,
    PELANDO_DEAL_PAGES,
    PelandoCoupons,
    PelandoDeals,
)
from .vtex import DEFAULT_VTEX, Vtex
from .websearch import WebSearchStore
from .x_twitter import XTwitterAccountsFeed, XTwitterWatchesFeed


def store_sources(db: Session) -> list[StoreSource]:
    sources: list[StoreSource] = [
        Zoom(),
        Buscape(),
        GatrySearch(),
        Amazon(),
        Kabum(),
        WebSearchStore(),
        MercadoLivre(),
        Olx(),
    ]
    sources += [Vtex(key, name, url, cond) for key, (name, url, cond) in DEFAULT_VTEX.items()]
    for custom in get_json(db, "custom_vtex", []):
        sources.append(
            Vtex(custom["key"], custom["name"], custom["url"], guard=True)
        )
    return sources


def feed_sources(db: Session) -> list[FeedSource]:
    sources: list[FeedSource] = [Promobit(*page) for page in PROMOBIT_PAGES]
    sources += [PelandoDeals(*page) for page in PELANDO_DEAL_PAGES]
    sources += [PelandoCoupons(*store) for store in PELANDO_COUPON_STORES]
    sources.append(GatryFeed())
    sources.append(XTwitterWatchesFeed())
    sources.append(XTwitterAccountsFeed())
    sources.append(ImapAlertsFeed())
    sources += [TelegramChannel(c, n) for c, n in TELEGRAM_CHANNELS.items()]
    sources += [RssFeed(k, n, u) for k, (n, u) in RSS_FEEDS.items()]
    for channel in get_json(db, "custom_telegram", []):
        sources.append(TelegramChannel(channel["channel"], channel.get("name", "")))
    for feed in get_json(db, "custom_rss", []):
        sources.append(RssFeed(feed["key"], feed["name"], feed["url"], guard=True))
    return sources
