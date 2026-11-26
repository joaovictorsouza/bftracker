from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Datas sempre em UTC com fuso, inclusive no SQLite."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    email: Mapped[str] = mapped_column(String(255), default="")
    whatsapp: Mapped[str] = mapped_column(String(32), default="")
    callmebot_key: Mapped[str] = mapped_column(String(64), default="")
    prefs: Mapped[dict] = mapped_column(JSON, default=dict)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Watch(Base):
    __tablename__ = "watches"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16), default="product")  # product | url
    query: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    include_terms: Mapped[list] = mapped_column(JSON, default=list)
    exclude_terms: Mapped[list] = mapped_column(JSON, default=list)
    min_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    drop_percent: Mapped[float] = mapped_column(Float, default=3.0)
    sources: Mapped[list] = mapped_column(JSON, default=list)  # vazio = todas
    include_used: Mapped[bool] = mapped_column(Boolean, default=True)
    used_state: Mapped[str] = mapped_column(String(2), default="")
    used_region: Mapped[str] = mapped_column(String(80), default="")
    used_max_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=15)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    baseline_done: Mapped[bool] = mapped_column(Boolean, default=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    last_report: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    user: Mapped[User] = relationship()


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (UniqueConstraint("watch_id", "source", "external_id", name="uq_offer"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(40))
    external_id: Mapped[str] = mapped_column(String(200))
    store: Mapped[str] = mapped_column(String(80))
    store_key: Mapped[str] = mapped_column(String(60), default="")
    seller: Mapped[str] = mapped_column(String(120), default="")
    marketplace: Mapped[bool] = mapped_column(Boolean, default=False)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    image: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[float] = mapped_column(Float)  # melhor preço à vista
    card_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # total parcelado
    original_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    installments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    installment_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    interest_free: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    pix: Mapped[bool] = mapped_column(Boolean, default=False)
    free_shipping: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    coupon: Mapped[str] = mapped_column(String(200), default="")
    condition: Mapped[str] = mapped_column(String(12), default="new")  # new | used | refurbished
    location: Mapped[str] = mapped_column(String(160), default="")
    variant_key: Mapped[str] = mapped_column(String(120), default="padrao", index=True)
    variant_label: Mapped[str] = mapped_column(String(160), default="Padrão")
    suspicious: Mapped[bool] = mapped_column(Boolean, default=False)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    previous_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    lowest_price: Mapped[float] = mapped_column(Float)
    missed_runs: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class PricePoint(Base):
    __tablename__ = "price_points"
    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), index=True)
    price: Mapped[float] = mapped_column(Float)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class DailyBest(Base):
    """Melhor preço por dia e variante (inclui histórico importado de comparadores)."""

    __tablename__ = "daily_best"
    __table_args__ = (
        UniqueConstraint("watch_id", "variant_key", "condition", "day", name="uq_daily"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"), index=True)
    variant_key: Mapped[str] = mapped_column(String(120))
    condition: Mapped[str] = mapped_column(String(12), default="new")
    day: Mapped[date] = mapped_column(Date)
    price: Mapped[float] = mapped_column(Float)
    store: Mapped[str] = mapped_column(String(80), default="")
    imported: Mapped[bool] = mapped_column(Boolean, default=False)


class Deal(Base):
    """Oferta publicada por sites, fóruns e canais especializados."""

    __tablename__ = "deals"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_deal"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(60), index=True)
    source_name: Mapped[str] = mapped_column(String(80), default="")
    external_id: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text)
    link: Mapped[str] = mapped_column(Text, default="")  # link direto para a loja, se houver
    image: Mapped[str] = mapped_column(Text, default="")
    store: Mapped[str] = mapped_column(String(80), default="")
    store_key: Mapped[str] = mapped_column(String(60), default="", index=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    old_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    discount_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    coupon: Mapped[str] = mapped_column(String(120), default="")
    category: Mapped[str] = mapped_column(String(40), default="outros", index=True)
    is_flash: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_coupon: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_blackfriday: Mapped[bool] = mapped_column(Boolean, default=False)
    is_bug: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[int] = mapped_column(Integer, default=0)
    fingerprint: Mapped[str] = mapped_column(String(80), default="", index=True)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class Coupon(Base):
    __tablename__ = "coupons"
    __table_args__ = (UniqueConstraint("store_key", "code", "title_key", name="uq_coupon"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    store: Mapped[str] = mapped_column(String(80))
    store_key: Mapped[str] = mapped_column(String(60), index=True)
    code: Mapped[str] = mapped_column(String(60), default="")
    title: Mapped[str] = mapped_column(Text)
    title_key: Mapped[str] = mapped_column(String(80), default="")
    discount: Mapped[str] = mapped_column(String(60), default="")
    conditions: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(60))
    is_flash: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Interest(Base):
    """Alerta sobre o radar: categorias, palavras-chave, lojas, cupons e relâmpagos."""

    __tablename__ = "interests"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    categories: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    exclude_terms: Mapped[list] = mapped_column(JSON, default=list)
    stores: Mapped[list] = mapped_column(JSON, default=list)
    max_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_discount: Mapped[float | None] = mapped_column(Float, nullable=True)
    only_flash: Mapped[bool] = mapped_column(Boolean, default=False)
    only_coupons: Mapped[bool] = mapped_column(Boolean, default=False)
    max_per_hour: Mapped[int] = mapped_column(Integer, default=10)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    user: Mapped[User] = relationship()


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_notification"),
        Index("ix_notification_user_created", "user_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    priority: Mapped[int] = mapped_column(Integer, default=2)  # 1 baixa, 2 normal, 3 urgente
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, default="")  # destino externo (loja)
    path: Mapped[str] = mapped_column(String(200), default="/")  # destino no app
    image: Mapped[str] = mapped_column(Text, default="")
    watch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    deliveries: Mapped[list[Delivery]] = relationship(
        back_populates="notification", cascade="all, delete-orphan"
    )


class Delivery(Base):
    __tablename__ = "deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    notification_id: Mapped[int] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(16))  # push | email | whatsapp
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    notification: Mapped[Notification] = relationship(back_populates="deliveries")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SourceStatus(Base):
    __tablename__ = "source_status"
    source: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    kind: Mapped[str] = mapped_column(String(16), default="store")  # store | feed
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    state: Mapped[str] = mapped_column(String(16), default="unknown")  # ok|blocked|error|unknown
    last_ok_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    blocked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    last_items: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    baseline_done: Mapped[bool] = mapped_column(Boolean, default=False)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    secret: Mapped[bool] = mapped_column(Boolean, default=False)


class RunRequest(Base):
    """Pedido de execução imediata feito pela interface e atendido pelo worker."""

    __tablename__ = "run_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # watch | source
    target: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Heartbeat(Base):
    __tablename__ = "heartbeats"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
