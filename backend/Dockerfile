FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（官方 7-Zip 24.08、unar）
# 与根 Dockerfile 保持一致：支持多架构、排除旧 p7zip、构建期验证版本。
ARG TARGETARCH
RUN sed -i 's/Components: main/Components: main contrib non-free non-free-firmware/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        wget \
        xz-utils \
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
    && rm -f /tmp/7z.tar.xz /usr/bin/7z /usr/bin/7za /usr/bin/7zr \
    && rm -rf /var/lib/apt/lists/* \
    && /usr/local/bin/7zz --help | head -3 \
    && /usr/local/bin/7zz --help | grep -q "24.08" \
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

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["python", "-m", "app.main"]
