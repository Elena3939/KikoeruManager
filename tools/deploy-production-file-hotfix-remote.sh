#!/bin/sh
set -eu

SOURCE_FILE=${1:?missing source file}
CONTAINER_PATH=${2:?missing container path}
RELEASE_ID=${3:?missing release id}
EXPECTED_HASH=${4:?missing source hash}

DOCKER=/var/packages/Docker/target/usr/bin/docker
CONTAINER=elena39-kikoerumanager
BACKUP_DIR=
BACKUP_FILE=
APPLIED=0

log() {
  printf '[文件热补丁] %s\n' "$*"
}

fail() {
  printf '[文件热补丁] 错误: %s\n' "$*" >&2
  exit 1
}

rollback() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$APPLIED" -eq 1 ] && [ -n "$BACKUP_FILE" ]; then
    log '健康检查失败，恢复原始文件'
    "$DOCKER" cp "$BACKUP_FILE" "$CONTAINER:$CONTAINER_PATH" >/dev/null 2>&1 || true
    "$DOCKER" restart --time 45 "$CONTAINER" >/dev/null 2>&1 || true
  fi
  rm -f "$SOURCE_FILE"
  exit "$status"
}

trap rollback EXIT INT TERM

[ "$(hostname)" = 'Elena' ] || fail "生产主机校验失败: $(hostname)"
[ -f "$SOURCE_FILE" ] || fail "上传的源码不存在: $SOURCE_FILE"
[ -n "$CONTAINER_PATH" ] || fail '目标路径为空'
case "$CONTAINER_PATH" in
  /app/app/*.py) ;;
  *) fail "拒绝写入目标路径: $CONTAINER_PATH" ;;
esac

"$DOCKER" inspect "$CONTAINER" >/dev/null 2>&1 || fail "生产容器不存在: $CONTAINER"
DATA_SOURCE=$("$DOCKER" inspect --format '{{range .Mounts}}{{if eq .Destination "/app/data"}}{{.Source}}{{end}}{{end}}' "$CONTAINER")
[ -n "$DATA_SOURCE" ] || fail '无法定位 /app/data 宿主机挂载'

ACTUAL_HASH=$(sha256sum "$SOURCE_FILE" | awk '{print $1}')
[ "$ACTUAL_HASH" = "$EXPECTED_HASH" ] || fail '上传文件 SHA-256 不匹配'

PROCESSING=$("$DOCKER" exec "$CONTAINER" sh -lc 'export PGPASSWORD="$POSTGRES_PASSWORD"; psql -h 127.0.0.1 -p 5432 -U kikoerumanager -d kikoerumanager -Atc "SELECT count(*) FROM task_center_items WHERE status = chr(112)||chr(114)||chr(111)||chr(99)||chr(101)||chr(115)||chr(115)||chr(105)||chr(110)||chr(103);"' | tr -d '[:space:]')
case "$PROCESSING" in
  0) ;;
  ''|*[!0-9]*) fail '无法确认 processing 任务数量' ;;
  *) fail "检测到 $PROCESSING 个 processing 任务，拒绝热补丁" ;;
esac

BACKUP_DIR="$DATA_SOURCE/.deploy/file-hotfix-backups/$RELEASE_ID"
BACKUP_FILE="$BACKUP_DIR/original.py"
mkdir -p "$BACKUP_DIR"
"$DOCKER" cp "$CONTAINER:$CONTAINER_PATH" "$BACKUP_FILE"
printf 'release_id=%s\nsource_sha256=%s\nprevious_image=%s\n' \
  "$RELEASE_ID" \
  "$EXPECTED_HASH" \
  "$("$DOCKER" inspect --format '{{.Config.Image}}' "$CONTAINER")" \
  > "$BACKUP_DIR/manifest.txt"

log "覆盖 $CONTAINER_PATH"
"$DOCKER" cp "$SOURCE_FILE" "$CONTAINER:$CONTAINER_PATH"
APPLIED=1

CONTAINER_HASH=$("$DOCKER" exec "$CONTAINER" sha256sum "$CONTAINER_PATH" | awk '{print $1}')
[ "$CONTAINER_HASH" = "$EXPECTED_HASH" ] || fail '容器内文件 SHA-256 不匹配'

log '重启生产容器'
"$DOCKER" restart --time 45 "$CONTAINER" >/dev/null

attempt=1
while [ "$attempt" -le 36 ]; do
  health=$("$DOCKER" inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER")
  if [ "$health" = 'healthy' ] && curl --max-time 5 -fsS http://127.0.0.1:5555/api/health >/dev/null; then
    break
  fi
  [ "$attempt" -lt 36 ] || fail '新代码启动后 180 秒内未恢复健康'
  sleep 5
  attempt=$((attempt + 1))
done

kept=0
for name in $(ls -1 "$DATA_SOURCE/.deploy/file-hotfix-backups" 2>/dev/null | sort -r); do
  kept=$((kept + 1))
  [ "$kept" -le 3 ] || rm -rf "$DATA_SOURCE/.deploy/file-hotfix-backups/$name"
done

log "发布成功: $RELEASE_ID"
trap - EXIT INT TERM
rm -f "$SOURCE_FILE"
exit 0
