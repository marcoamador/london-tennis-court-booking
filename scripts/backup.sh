#!/usr/bin/env sh
# Consistent SQLite backup from the running container into ./backups (keeps 14 days).
# Cron example (server): 30 3 * * * cd /opt/courtwatch && ./scripts/backup.sh >> backups/backup.log 2>&1
set -eu
cd "$(dirname "$0")/.."
mkdir -p backups
stamp=$(date +%Y%m%d-%H%M%S)
docker compose exec -T app python -c "
import sqlite3
src = sqlite3.connect('/data/courtwatch.db')
dst = sqlite3.connect('/data/backup.db')
src.backup(dst)
dst.close()
"
docker compose cp app:/data/backup.db "backups/courtwatch-$stamp.db"
docker compose exec -T app rm -f /data/backup.db
find backups -name 'courtwatch-*.db' -mtime +14 -delete
echo "Backup written: backups/courtwatch-$stamp.db"
