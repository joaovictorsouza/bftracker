from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator


def _clean_terms(values: list[str]) -> list[str]:
    cleaned = [" ".join(v.split())[:60] for v in values if v and v.strip()]
    return list(dict.fromkeys(cleaned))[:30]


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class PasswordIn(BaseModel):
    current: str = Field(min_length=1, max_length=200)
    new: str = Field(min_length=8, max_length=200)


class Prefs(BaseModel):
    channels: dict[str, bool] = Field(default_factory=dict)
    min_priority: dict[str, int] = Field(default_factory=dict)
    quiet_start: str = ""
    quiet_end: str = ""
    quiet_allow_urgent: bool = True

    @field_validator("quiet_start", "quiet_end")
    @classmethod
    def hhmm(cls, value: str) -> str:
        if value and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("Use o formato HH:MM")
        return value


class ProfileIn(BaseModel):
    email: str = Field(default="", max_length=255)
    whatsapp: str = Field(default="", max_length=32)
    callmebot_key: str = Field(default="", max_length=64)
    prefs: Prefs

    @field_validator("email")
    @classmethod
    def email_format(cls, value: str) -> str:
        value = value.strip()
        if value and not re.fullmatch(r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+", value):
            raise ValueError("E-mail inválido")
        return value

    @field_validator("whatsapp")
    @classmethod
    def phone(cls, value: str) -> str:
        value = value.strip()
        digits = re.sub(r"\D", "", value)
        if value and not 10 <= len(digits) <= 15:
            raise ValueError("Informe o número com DDD (ex.: +55 11 91234-5678)")
        return value


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[\w.@-]+$")
    password: str = Field(min_length=8, max_length=200)
    is_admin: bool = False


class WatchIn(BaseModel):
    name: str = Field(default="", max_length=120)
    kind: str = Field(default="product", pattern="^(product|url)$")
    query: str = Field(default="", max_length=200)
    url: str = Field(default="", max_length=2000)
    include_terms: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    target_price: float | None = Field(default=None, ge=0)
    drop_percent: float = Field(default=3.0, ge=0.5, le=90)
    sources: list[str] = Field(default_factory=list)
    include_used: bool = True
    used_state: str = Field(default="", max_length=2)
    used_region: str = Field(default="", max_length=80)
    used_max_price: float | None = Field(default=None, ge=0)
    interval_minutes: int = Field(default=15, ge=5, le=1440)
    active: bool = True

    @field_validator("include_terms", "exclude_terms")
    @classmethod
    def terms(cls, values):
        return _clean_terms(values)

    @model_validator(mode="after")
    def coherent(self):
        self.query = " ".join(self.query.split())
        self.url = self.url.strip()
        if self.kind == "url":
            if not re.match(r"https?://\S+$", self.url):
                raise ValueError("Informe o endereço (URL) do produto")
        elif len(self.query) < 2:
            raise ValueError("Informe o que deseja monitorar")
        self.name = " ".join(self.name.split()) or (self.query or "Produto por link")[:120]
        self.used_state = self.used_state.lower()
        self.min_price = self.min_price or None
        self.max_price = self.max_price or None
        self.target_price = self.target_price or None
        self.used_max_price = self.used_max_price or None
        if self.min_price and self.max_price and self.min_price > self.max_price:
            raise ValueError("O preço mínimo é maior que o máximo")
        return self


class InterestIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    categories: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    stores: list[str] = Field(default_factory=list)
    max_price: float | None = Field(default=None, ge=0)
    min_discount: float | None = Field(default=None, ge=0, le=99)
    only_flash: bool = False
    only_coupons: bool = False
    max_per_hour: int = Field(default=10, ge=1, le=60)
    active: bool = True

    @field_validator("keywords", "exclude_terms")
    @classmethod
    def terms(cls, values):
        return _clean_terms(values)

    @model_validator(mode="after")
    def needs_filter(self):
        self.max_price = self.max_price or None
        self.min_discount = self.min_discount or None
        if not any((self.categories, self.keywords, self.stores, self.max_price,
                    self.min_discount, self.only_flash, self.only_coupons)):
            raise ValueError("Escolha ao menos um filtro para o alerta")
        return self


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=10, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class PushIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000, pattern=r"^https://")
    keys: PushKeys


class EndpointIn(BaseModel):
    endpoint: str = Field(max_length=1000)


class TestChannelIn(BaseModel):
    channel: str = Field(pattern="^(push|email|whatsapp)$")


class SettingsIn(BaseModel):
    values: dict[str, str | None]


class ToggleIn(BaseModel):
    enabled: bool


class CustomSourceIn(BaseModel):
    kind: str = Field(pattern="^(telegram|rss|vtex)$")
    name: str = Field(default="", max_length=60)
    value: str = Field(min_length=3, max_length=500)  # canal ou URL
