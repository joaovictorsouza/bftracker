#!/bin/sh
# Gera o .env com senhas aleatórias. Uso: ./scripts/setup.sh [dominio] [email]
set -eu
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  echo "Já existe um .env; nada foi alterado."
  exit 0
fi

random() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "$1"; }
domain="${1:-}"
email="${2:-}"
admin_password="$(random 16)"

set_var() {
  # os valores gerados não contêm "|" nem "&"
  sed "s|^$1=.*|$1=$2|" .env >.env.tmp && cat .env.tmp >.env && rm .env.tmp
}

umask 077
cp .env.example .env
chmod 600 .env
set_var POSTGRES_PASSWORD "$(random 32)"
set_var ADMIN_PASSWORD "$admin_password"
set_var SECRET_KEY "$(random 48)"
set_var WAHA_API_KEY "$(random 32)"
set_var ADMIN_EMAIL "$email"
if [ -n "$domain" ]; then
  set_var SITE_ADDRESS "$domain"
  set_var PUBLIC_URL "https://$domain"
fi

echo
echo "Arquivo .env criado."
echo "  Usuário: admin"
echo "  Senha:   $admin_password   (guarde e troque no primeiro acesso)"
echo
echo "Agora rode:  docker compose up -d --build"
