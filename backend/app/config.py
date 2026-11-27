"""Configuração lida do ambiente (.env no Docker Compose)."""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    database_url: str = ""
    secret_key: str = ""

    admin_username: str = "admin"
    admin_password: str = ""
    admin_email: str = ""

    public_url: str = "http://localhost:8080"
    timezone: str = "America/Sao_Paulo"
    session_days: int = 30

    # E-mail (também pode ser configurado pela interface)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_security: str = "starttls"  # starttls | ssl | none

    # WhatsApp: waha | evolution | meta | callmebot | webhook
    whatsapp_provider: str = ""
    waha_url: str = "http://waha:3000"
    waha_api_key: str = ""
    waha_session: str = "default"
    evolution_url: str = ""
    evolution_api_key: str = ""
    evolution_instance: str = ""
    meta_wa_token: str = ""
    meta_wa_phone_id: str = ""
    meta_wa_template: str = ""
    meta_wa_template_lang: str = "pt_BR"
    whatsapp_webhook_url: str = ""

    # Mercado Livre (API oficial, opcional)
    ml_client_id: str = ""
    ml_client_secret: str = ""
    ml_access_token: str = ""

    # X / Twitter (monitoramento de ofertas para produtos cadastrados e perfis)
    x_bearer_token: str = ""
    x_api_key: str = ""
    x_api_secret: str = ""
    x_accounts: str = "pelandobr,promobitoficial,pechinchou,nerdofertas,achadosdotb,ofertasadrena,pcdofafa"
    x_rss_search_url: str = ""

    # Busca Web opcional (Serper.dev / Brave Search — cobre ML, OLX, HardMob e X sem API do ML)
    serper_api_key: str = ""
    brave_api_key: str = ""

    # Leitor de alertas por e-mail via IMAP (buscas salvas OLX, fórum HardMob, Google Alerts, ML)
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"

    # Contato usado no VAPID (Web Push)
    vapid_subject: str = ""

    default_interval_minutes: int = 15
    min_interval_minutes: int = 5
    worker_concurrency: int = 3
    host_min_delay_seconds: float = 2.5
    web_dist: Path = Path(__file__).resolve().parent.parent / "static"

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.data_dir / 'bftracker.db'}"

    @property
    def secret(self) -> str:
        """SECRET_KEY do ambiente ou uma gerada e persistida no volume de dados."""
        if self.secret_key:
            return self.secret_key
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / "secret.key"
        if not path.exists():
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as handle:
                    handle.write(secrets.token_urlsafe(48))
            except FileExistsError:
                pass
        for _ in range(50):
            value = path.read_text().strip()
            if value:
                return value
            import time

            time.sleep(0.1)
        raise RuntimeError(f"{path} está vazio; apague o arquivo e reinicie")


@lru_cache
def get_settings() -> Settings:
    return Settings()
