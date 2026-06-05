FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（官方 7-Zip 24.08、BaiduPCS-Go、unar）
# 与根 Dockerfile 保持一致：支持多架构、排除旧 p7zip、构建期验证版本。
ARG TARGETARCH
ARG KIKOERUMANAGER_VERSION=dev
ARG BAIDUPCS_GO_VERSION=4.0.1
RUN sed -i 's/Components: main/Components: main contrib non-free non-free-firmware/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        wget \
        xz-utils \
        aria2 \
        unar \
    && apt-get purge -y --auto-remove p7zip-full p7zip p7zip-rar 2>/dev/null || true \
    && case "${TARGETARCH:-amd64}" in \
        amd64|x86_64) SEVENZIP_PKG=7z2408-linux-x64.tar.xz ;; \
        arm64|aarch64) SEVENZIP_PKG=7z2408-linux-arm64.tar.xz ;; \
        arm|armv7l) SEVENZIP_PKG=7z2408-linux-arm.tar.xz ;; \
        *) echo "Unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
       esac \
    && wget --retry-connrefused --waitretry=5 --tries=3 -O /tmp/7z.tar.xz \
        "https://github.com/ip7z/7zip/releases/download/24.08/${SEVENZIP_PKG}" \
    && mkdir -p /opt/7zip \
    && tar -xJf /tmp/7z.tar.xz -C /opt/7zip \
    && ln -sf /opt/7zip/7zz /usr/local/bin/7zz \
    && ln -sf /opt/7zip/7zz /usr/local/bin/7z \
    && case "${TARGETARCH:-amd64}" in \
        amd64|x86_64) BAIDUPCS_GO_PKG=BaiduPCS-Go-v${BAIDUPCS_GO_VERSION}-linux-amd64.zip ;; \
        arm64|aarch64) BAIDUPCS_GO_PKG=BaiduPCS-Go-v${BAIDUPCS_GO_VERSION}-linux-arm64.zip ;; \
        arm|armv7l) BAIDUPCS_GO_PKG=BaiduPCS-Go-v${BAIDUPCS_GO_VERSION}-linux-arm.zip ;; \
        *) echo "Unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
       esac \
    && wget --retry-connrefused --waitretry=5 --tries=3 -O /tmp/baidupcs-go.zip \
        "https://github.com/qjfoidnh/BaiduPCS-Go/releases/download/v${BAIDUPCS_GO_VERSION}/${BAIDUPCS_GO_PKG}" \
    && mkdir -p /tmp/baidupcs-go \
    && python -c "import zipfile; zipfile.ZipFile('/tmp/baidupcs-go.zip').extractall('/tmp/baidupcs-go')" \
    && find /tmp/baidupcs-go -type f -name BaiduPCS-Go -exec install -m 0755 {} /usr/local/bin/BaiduPCS-Go \; -quit \
    && test -x /usr/local/bin/BaiduPCS-Go \
    && ln -sf /usr/local/bin/BaiduPCS-Go /usr/local/bin/baidupcs-go \
    && rm -f /tmp/7z.tar.xz /tmp/baidupcs-go.zip /usr/bin/7z /usr/bin/7za /usr/bin/7zr \
    && rm -rf /tmp/baidupcs-go \
    && rm -rf /var/lib/apt/lists/* \
    && /usr/local/bin/7zz --help | head -3 \
    && /usr/local/bin/7zz --help | grep -q "24.08" \
    && mkdir -p /tmp/baidupcs-go-config \
    && BAIDUPCS_GO_CONFIG_DIR=/tmp/baidupcs-go-config /usr/local/bin/BaiduPCS-Go -v | head -5 \
    && aria2c --version | head -1 \
    && which unar && unar --version 2>&1 | head -1 \
    && which lsar && echo "===== unar + lsar installed OK ====="

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt
RUN python - <<'PY'
import sqlite3

conn = sqlite3.connect(":memory:")
opts = {row[0] for row in conn.execute("PRAGMA compile_options")}
print("SQLite version:", sqlite3.sqlite_version)
print("SQLite FTS options:", sorted(opt for opt in opts if "FTS" in opt or "TOKEN" in opt))
if "ENABLE_FTS5" not in opts:
    raise SystemExit("当前 Python SQLite 未启用 ENABLE_FTS5")
conn.execute("CREATE VIRTUAL TABLE fts5_probe USING fts5(x)")
conn.execute("CREATE VIRTUAL TABLE trigram_probe USING fts5(x, tokenize='trigram')")
print("SQLite FTS5 + trigram 检查通过")
PY

# 复制应用代码
COPY app/ ./app/

# 创建数据目录
RUN mkdir -p /app/data /app/config

# 环境变量
ENV CONFIG_PATH=/app/config/config.yaml
ENV DATA_PATH=/app/data
ENV PYTHONPATH=/app
ENV KIKOERUMANAGER_VERSION=${KIKOERUMANAGER_VERSION}

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["python", "-m", "app.main"]
