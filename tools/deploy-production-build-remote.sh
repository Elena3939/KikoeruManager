#!/bin/sh
set -eu

ARCHIVE_PATH=${1:?missing archive path}
RELEASE_ID=${2:?missing release id}
SOURCE_REVISION=${3:?missing source revision}
FORCE=${4:-0}
DRY_RUN=${5:-0}

DOCKER=/var/packages/Docker/target/usr/bin/docker
CONTAINER=elena39-kikoerumanager
KEEP_RELEASES=3
SWITCHED=0
BACKUP_CONTAINER=
RELEASE_DIR=

log() {
  printf '[生产发布] %s\n' "$*"
}

fail() {
  printf '[生产发布] 错误: %s\n' "$*" >&2
  exit 1
}

cleanup_upload() {
  rm -f "$ARCHIVE_PATH"
}

rollback() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$SWITCHED" -eq 1 ] && [ -n "$BACKUP_CONTAINER" ]; then
    log "新容器启动失败，开始回滚到 $BACKUP_CONTAINER"
    "$DOCKER" rm -f "$CONTAINER" >/dev/null 2>&1 || true
    "$DOCKER" rename "$BACKUP_CONTAINER" "$CONTAINER" >/dev/null 2>&1 || true
    "$DOCKER" start "$CONTAINER" >/dev/null 2>&1 || true
  fi
  cleanup_upload
  exit "$status"
}

trap rollback EXIT INT TERM

[ "$(hostname)" = 'Elena' ] || fail "生产主机校验失败: $(hostname)"
[ -f "$ARCHIVE_PATH" ] || fail "源码快照不存在: $ARCHIVE_PATH"
case "$RELEASE_ID" in
  *[!0-9A-Za-z-]*|'') fail "非法发布版本号: $RELEASE_ID" ;;
esac
case "$SOURCE_REVISION" in
  *[!0-9a-f]*|'') fail "非法源码 revision" ;;
esac

"$DOCKER" inspect "$CONTAINER" >/dev/null 2>&1 || fail "生产容器不存在: $CONTAINER"
DATA_SOURCE=$("$DOCKER" inspect --format '{{range .Mounts}}{{if eq .Destination "/app/data"}}{{.Source}}{{end}}{{end}}' "$CONTAINER")
[ -n "$DATA_SOURCE" ] || fail '无法定位生产容器的 /app/data 宿主机挂载'

DEPLOY_ROOT="$DATA_SOURCE/.deploy"
RELEASES_ROOT="$DEPLOY_ROOT/releases"
RELEASE_DIR="$RELEASES_ROOT/$RELEASE_ID"
CONTEXT_DIR="$RELEASE_DIR/context"
MANIFEST_FILE="$RELEASE_DIR/manifest.txt"
IMAGE="elena39/kikoerumanager:hotfix-$RELEASE_ID"

if [ -e "$RELEASE_DIR" ]; then
  fail "发布版本已存在: $RELEASE_ID"
fi

mkdir -p "$CONTEXT_DIR"
tar -xzf "$ARCHIVE_PATH" -C "$CONTEXT_DIR"
for required in Dockerfile .dockerignore backend/requirements.txt frontend/package-lock.json; do
  [ -f "$CONTEXT_DIR/$required" ] || fail "源码快照缺少构建必需文件: $required"
done

cat > "$MANIFEST_FILE" <<EOF
release_id=$RELEASE_ID
source_revision=$SOURCE_REVISION
created_at=$(date '+%Y-%m-%dT%H:%M:%S%z')
image=$IMAGE
EOF

if [ "$DRY_RUN" = '1' ]; then
  log "演练完成，源码快照已验证: $RELEASE_ID"
  rm -rf "$RELEASE_DIR"
  trap - EXIT INT TERM
  cleanup_upload
  exit 0
fi

active_processing_count() {
  "$DOCKER" exec "$CONTAINER" sh -lc '
    export PGPASSWORD="$POSTGRES_PASSWORD"
    psql -h 127.0.0.1 -p 5432 -U kikoerumanager -d kikoerumanager -Atc \
      "SELECT count(*) FROM task_center_items WHERE status = '\''processing'\'';"
  ' 2>/dev/null | tr -d '[:space:]'
}

require_idle_or_force() {
  count=$(active_processing_count || true)
  case "$count" in
    ''|*[!0-9]*)
      [ "$FORCE" = '1' ] || fail '无法确认生产 processing 任务数量；如已人工确认可中断，再使用 -Force 发布'
      log '无法确认 processing 任务数量，按 -Force 继续'
      ;;
    0) ;;
    *)
      [ "$FORCE" = '1' ] || fail "检测到 $count 个 processing 任务，拒绝在任务运行时切换容器"
      log "检测到 $count 个 processing 任务，按 -Force 继续"
      ;;
  esac
}

build_image() {
  attempt=1
  while [ "$attempt" -le 3 ]; do
    if "$DOCKER" build \
      --tag "$IMAGE" \
      --build-arg "KIKOERUMANAGER_VERSION=hotfix-$RELEASE_ID" \
      "$CONTEXT_DIR"; then
      return 0
    fi
    if [ "$attempt" -eq 3 ]; then
      return 1
    fi
    delay=$((attempt * 20))
    log "镜像构建第 $attempt 次失败，$delay 秒后重试"
    sleep "$delay"
    attempt=$((attempt + 1))
  done
}

clone_container() {
  source_container=$1
  target_container=$2
  target_image=$3

  "$DOCKER" run --rm -i \
    -v /var/run/docker.sock:/var/run/docker.sock \
    --entrypoint python "$target_image" - "$source_container" "$target_container" "$target_image" <<'PY'
import json
import socket
import sys
from urllib.parse import quote

source_name, target_name, target_image = sys.argv[1:4]

def request(method, path, payload=None):
    body = b"" if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = [
        f"{method} {path} HTTP/1.1",
        "Host: docker",
        "Connection: close",
    ]
    if body:
        headers.extend(("Content-Type: application/json", f"Content-Length: {len(body)}"))
    raw_request = ("\r\n".join(headers) + "\r\n\r\n").encode("ascii") + body
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect("/var/run/docker.sock")
    client.sendall(raw_request)
    chunks = []
    while True:
        chunk = client.recv(65536)
        if not chunk:
            break
        chunks.append(chunk)
    client.close()
    response = b"".join(chunks)
    header, _, response_body = response.partition(b"\r\n\r\n")
    status_line = header.split(b"\r\n", 1)[0].decode("ascii", "replace")
    try:
        status = int(status_line.split()[1])
    except (IndexError, ValueError) as exc:
        raise RuntimeError(f"Docker API response invalid: {status_line}") from exc
    if status < 200 or status >= 300:
        detail = response_body.decode("utf-8", "replace")
        raise RuntimeError(f"Docker API {method} {path} failed: {status} {detail}")
    return response_body

source = json.loads(request("GET", f"/v1.41/containers/{quote(source_name, safe='')}/json"))
config = dict(source["Config"])
config["Image"] = target_image

allowed_endpoint_keys = {"IPAMConfig", "Links", "Aliases", "DriverOpts", "GwPriority"}
endpoints = {}
for name, endpoint in (source.get("NetworkSettings", {}).get("Networks", {}) or {}).items():
    endpoints[name] = {key: endpoint[key] for key in allowed_endpoint_keys if key in endpoint}

config["HostConfig"] = source["HostConfig"]
config["NetworkingConfig"] = {"EndpointsConfig": endpoints}
request(
    "POST",
    f"/v1.41/containers/create?name={quote(target_name, safe='')}",
    config,
)
PY
}

wait_for_health() {
  attempt=1
  while [ "$attempt" -le 36 ]; do
    health=$("$DOCKER" inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER" 2>/dev/null || true)
    if [ "$health" = 'healthy' ] && curl --max-time 5 -fsS http://127.0.0.1:5555/api/health >/dev/null; then
      return 0
    fi
    sleep 5
    attempt=$((attempt + 1))
  done
  return 1
}

cleanup_old_releases() {
  kept=0
  for path in $(ls -1 "$RELEASES_ROOT" 2>/dev/null | sort -r); do
    kept=$((kept + 1))
    if [ "$kept" -le "$KEEP_RELEASES" ]; then
      continue
    fi
    old_image=$(sed -n 's/^image=//p' "$RELEASES_ROOT/$path/manifest.txt" 2>/dev/null | head -n 1)
    [ -z "$old_image" ] || "$DOCKER" image rm "$old_image" >/dev/null 2>&1 || true
    rm -rf "$RELEASES_ROOT/$path"
    log "已清理过期源码版本: $path"
  done

  kept=0
  for name in $("$DOCKER" ps -a --format '{{.Names}}' | grep "^${CONTAINER}-rollback-" | sort -r || true); do
    kept=$((kept + 1))
    if [ "$kept" -le "$KEEP_RELEASES" ]; then
      continue
    fi
    "$DOCKER" rm -f "$name" >/dev/null 2>&1 || true
  done
}

require_idle_or_force
log "开始在生产服务器构建镜像: $IMAGE"
build_image || fail '生产镜像构建连续三次失败'

"$DOCKER" image inspect "$IMAGE" >/dev/null
PRECHECK_CONTAINER="${CONTAINER}-precheck-$RELEASE_ID"
clone_container "$CONTAINER" "$PRECHECK_CONTAINER" "$IMAGE"
"$DOCKER" rm "$PRECHECK_CONTAINER" >/dev/null
log '候选镜像已通过容器配置预检'

require_idle_or_force
BACKUP_CONTAINER="${CONTAINER}-rollback-$RELEASE_ID"
log '停止当前生产容器'
"$DOCKER" stop --time 45 "$CONTAINER"
"$DOCKER" rename "$CONTAINER" "$BACKUP_CONTAINER"
SWITCHED=1

log '使用新镜像创建生产容器'
clone_container "$BACKUP_CONTAINER" "$CONTAINER" "$IMAGE"
"$DOCKER" start "$CONTAINER"

if ! wait_for_health; then
  fail '新容器在 180 秒内未恢复健康状态'
fi

printf 'deployed_image_id=%s\n' "$("$DOCKER" image inspect --format '{{.Id}}' "$IMAGE")" >> "$MANIFEST_FILE"
printf 'deployed_at=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" >> "$MANIFEST_FILE"
cleanup_old_releases

log "发布成功: $RELEASE_ID"
trap - EXIT INT TERM
cleanup_upload
exit 0
