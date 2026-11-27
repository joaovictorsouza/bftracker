#!/bin/sh
# Gera variáveis prontas com senhas fortes para colar na aba "Environment" do Dokploy
# (e também salva em .env local com permissão 600, ignorado pelo Git).
# Uso: ./scripts/setup.sh [dominio] [email]
set -eu
cd "$(dirname "$0")/.."

random() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "$1"; }
domain="${1:-ofertas.seudominio.com}"
email="${2:-}"
pg_password="$(random 32)"
admin_password="$(random 16)"
secret_key="$(random 48)"
waha_key="$(random 32)"
public_url="https://${domain#https://}"
public_url="${public_url%/}"

if [ ! -f .env ]; then
  umask 077
  cp .env.example .env
  chmod 600 .env
  set_var() {
    sed "s|^$1=.*|$1=$2|" .env >.env.tmp && cat .env.tmp >.env && rm .env.tmp
  }
  set_var POSTGRES_PASSWORD "$pg_password"
  set_var ADMIN_PASSWORD "$admin_password"
  set_var SECRET_KEY "$secret_key"
  set_var WAHA_API_KEY "$waha_key"
  set_var ADMIN_EMAIL "$email"
  set_var PUBLIC_URL "$public_url"
fi

cat <<EOF

=== Cole na aba "Environment" do serviço Compose no Dokploy ===

POSTGRES_PASSWORD=$pg_password
ADMIN_USERNAME=admin
ADMIN_PASSWORD=$admin_password
ADMIN_EMAIL=$email
SECRET_KEY=$secret_key
PUBLIC_URL=$public_url
TIMEZONE=America/Sao_Paulo
WAHA_API_KEY=$waha_key

===============================================================
Na aba "Domains" do Dokploy:
  Service Name:   app
  Container Port: 8000
  Host:           ${public_url#https://}
  HTTPS:          Ativado (Let's Encrypt)
EOF
