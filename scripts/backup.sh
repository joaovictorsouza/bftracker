#!/bin/sh
# Cópia do banco em ./backups
set -eu
cd "$(dirname "$0")/.."
umask 077
mkdir -p backups
stamp="$(date +%Y%m%d-%H%M%S)"
docker compose exec -T db pg_dump -U bftracker --clean --if-exists bftracker | gzip >"backups/db-$stamp.sql.gz"
[ -f .env ] && cp .env "backups/env-$stamp"
echo "Backup salvo em backups/ (contém segredos: guarde em local seguro)"
