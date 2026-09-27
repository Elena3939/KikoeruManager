#!/bin/sh
set -eu
ARCHIVE="$1"
RELEASE_ID="$2"
DOCKER=/var/packages/Docker/target/usr/bin/docker
CONTAINER=elena39-kikoerumanager
[ "$(hostname)" = "Elena" ] || { echo '生产主机校验失败' >&2; exit 1; }
DATA_SOURCE=$("$DOCKER" inspect --format '{{range .Mounts}}{{if eq .Destination "/app/data"}}{{.Source}}{{end}}{{end}}' "$CONTAINER")
[ -n "$DATA_SOURCE" ] || { echo '无法定位 /app/data 挂载' >&2; exit 1; }
PROCESSING=$("$DOCKER" exec "$CONTAINER" sh -lc 'export PGPASSWORD="$POSTGRES_PASSWORD"; psql -h 127.0.0.1 -p 5432 -U kikoerumanager -d kikoerumanager -Atc "SELECT count(*) FROM task_center_items WHERE status = chr(112)||chr(114)||chr(111)||chr(99)||chr(101)||chr(115)||chr(115)||chr(105)||chr(110)||chr(103);"' | tr -d '[:space:]')
[ "$PROCESSING" = 0 ] || { echo "检测到 processing 任务: $PROCESSING" >&2; exit 1; }
BACKUP_DIR="$DATA_SOURCE/.deploy/frontend-static-backups/$RELEASE_ID"
mkdir -p "$BACKUP_DIR"
"$DOCKER" exec "$CONTAINER" sh -lc 'tar -czf - -C /app/static .' > "$BACKUP_DIR/original-static.tar.gz"
printf 'release_id=%s\nimage=%s\n' "$RELEASE_ID" "$("$DOCKER" inspect --format '{{.Config.Image}}' "$CONTAINER")" > "$BACKUP_DIR/manifest.txt"
"$DOCKER" exec -i "$CONTAINER" sh -lc 'rm -rf /app/static.__deploy_new && mkdir -p /app/static.__deploy_new && tar -xzf - -C /app/static.__deploy_new' < "$ARCHIVE"
"$DOCKER" exec "$CONTAINER" sh -lc 'rm -rf /app/static.__deploy_old && mv /app/static /app/static.__deploy_old && mv /app/static.__deploy_new /app/static && rm -rf /app/static.__deploy_old'
"$DOCKER" restart --time 45 "$CONTAINER" >/dev/null
attempt=1
while [ "$attempt" -le 36 ]; do
  health=$("$DOCKER" inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER")
  if [ "$health" = healthy ] && curl --max-time 5 -fsS http://127.0.0.1:5555/api/health >/dev/null; then break; fi
  [ "$attempt" -lt 36 ] || { echo '前端发布后容器未恢复健康' >&2; exit 1; }
  sleep 5
  attempt=$((attempt + 1))
done
rm -f "$ARCHIVE"
echo "[前端静态产物] 发布成功: $RELEASE_ID"
