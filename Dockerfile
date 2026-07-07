ARG KIKOERUMANAGER_VERSION=dev

# 多阶段构建 Dockerfile
# 阶段1：构建前端
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
ARG KIKOERUMANAGER_VERSION=dev
ENV KIKOERUMANAGER_VERSION=${KIKOERUMANAGER_VERSION}

# 复制前端依赖清单；TanStack Table 等前端交互依赖由 lock 文件锁定并通过 npm ci 安装
COPY frontend/package*.json ./
# 增大 Node.js 堆内存上限，避免大型 Vite 项目 OOM
RUN NODE_OPTIONS="--max-old-space-size=4096" npm ci

# 复制前端源码并构建
COPY frontend/ ./
RUN NODE_OPTIONS="--max-old-space-size=4096" npm run build

# 阶段2：后端运行环境
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（官方 7-Zip 24.08、7-Zip ZS 兼容后端、BaiduPCS-Go、unar、opencc 和内置 Redis）
# - 用 TARGETARCH（buildx 自动注入）选择 x64 / arm64 包，兼容 amd64 群晖和 ARM64 群晖。
# - 显式 uninstall p7zip-full，避免 /usr/bin/7z 覆盖 /usr/local/bin/7zz 的 PATH 优先级。
# - 构建末尾打印 `7zz -version`，构建失败或版本错位时立刻暴露，不会悄悄回退到旧 p7zip。
ARG TARGETARCH
ARG KIKOERUMANAGER_VERSION=dev
ARG BAIDUPCS_GO_VERSION=4.0.1
ARG SEVENZIP_ZSTD_VERSION=v26.01-v1.5.7-R1
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        wget \
        bash \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*
RUN sed -i 's/Components: main/Components: main contrib non-free non-free-firmware/g' /etc/apt/sources.list.d/debian.sources && \
    install -d /usr/share/postgresql-common/pgdg && \
    wget --retry-connrefused --waitretry=5 --tries=3 -O /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc && \
    . /etc/os-release && \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list && \
    apt-get update && apt-get install -y --no-install-recommends \
        aria2 \
        unar \
        libpq5 \
        postgresql-18 \
        postgresql-client-18 \
        redis-server \
        libopencc-dev \
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
        amd64|x86_64) SEVENZIP_ZSTD_PKG=linux-gcc-x64.zip ;; \
        arm64|aarch64) SEVENZIP_ZSTD_PKG=linux-gcc-arm64.zip ;; \
        arm|armv7l) SEVENZIP_ZSTD_PKG= ;; \
        *) echo "Unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
       esac \
    && if [ -n "${SEVENZIP_ZSTD_PKG}" ]; then \
        wget --retry-connrefused --waitretry=5 --tries=3 -O /tmp/7z-zstd.zip \
            "https://github.com/mcmilk/7-Zip-zstd/releases/download/${SEVENZIP_ZSTD_VERSION}/${SEVENZIP_ZSTD_PKG}" \
        && mkdir -p /opt/7zip-zstd \
        && python -c "import zipfile; zipfile.ZipFile('/tmp/7z-zstd.zip').extractall('/opt/7zip-zstd')" \
        && chmod 0755 /opt/7zip-zstd/7z /opt/7zip-zstd/7za /opt/7zip-zstd/7zr /opt/7zip-zstd/7zz \
        && ln -sf /opt/7zip-zstd/7zz /usr/local/bin/7zzs; \
       else \
        echo "===== 7-Zip ZS has no linux armv7 build; skipping optional zstd backend ====="; \
       fi \
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
    && rm -f /tmp/7z.tar.xz /tmp/7z-zstd.zip /tmp/baidupcs-go.zip /usr/bin/7z /usr/bin/7za /usr/bin/7zr \
    && rm -rf /tmp/baidupcs-go \
    && rm -rf /var/lib/apt/lists/* \
    && echo "===== 7-Zip version check =====" \
    && /usr/local/bin/7zz --help | head -3 \
    && /usr/local/bin/7zz --help | grep -q "24.08" \
    && echo "===== 7-Zip 24.08 installed OK =====" \
    && if [ -x /usr/local/bin/7zzs ]; then \
        echo "===== 7-Zip ZS version check =====" \
        && /usr/local/bin/7zzs i | head -3 \
        && /usr/local/bin/7zzs i | grep -q "ZSTD" \
        && echo "===== 7-Zip ZS zstd backend installed OK ====="; \
       fi \
    && echo "===== BaiduPCS-Go version check =====" \
    && mkdir -p /tmp/baidupcs-go-config \
    && BAIDUPCS_GO_CONFIG_DIR=/tmp/baidupcs-go-config /usr/local/bin/BaiduPCS-Go -v | head -5 \
    && echo "===== BaiduPCS-Go installed OK =====" \
    && aria2c --version | head -1 \
    && which unar && unar --version 2>&1 | head -1 \
    && which lsar && echo "===== unar + lsar installed OK ====="

# 复制后端依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python - <<'PY'
import psycopg

print("psycopg version:", psycopg.__version__)
print("PostgreSQL Python driver check OK")
PY
RUN psql --version
RUN redis-server --version

# 复制后端代码与 PostgreSQL schema baseline
COPY backend/app/ ./app/
COPY backend/alembic/ ./backend/alembic/
COPY alembic.ini ./alembic.ini
COPY docker/entrypoint.sh /usr/local/bin/kikoerumanager-entrypoint
RUN chmod +x /usr/local/bin/kikoerumanager-entrypoint

# 从前端构建阶段复制静态文件
COPY --from=frontend-builder /app/frontend/dist /app/static

# 验证静态文件是否正确复制
RUN ls -la /app/static/ && \
    if [ -f /app/static/index.html ]; then \
        echo "✓ Static files copied successfully"; \
    else \
        echo "✗ Static files not found!"; \
        exit 1; \
    fi

# 创建必要的目录
RUN mkdir -p /app/data /app/config /input /temp /library /existing /processed

# 环境变量
ENV CONFIG_PATH=/app/config/config.yaml
ENV DATA_PATH=/app/data
ENV PYTHONPATH=/app
ENV STATIC_FILES_PATH=/app/static
ENV KIKOERUMANAGER_VERSION=${KIKOERUMANAGER_VERSION}
ENV PGDATA=/app/postgres/data
# 应用端口，可通过 docker run -e PORT=xxxx 覆盖
ENV PORT=5555

# 暴露端口（与 PORT 默认值一致）
EXPOSE 5555

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:' + os.environ.get('PORT','5555') + '/api/health')" || exit 1

# 启动命令
ENTRYPOINT ["kikoerumanager-entrypoint"]
CMD ["python", "-m", "app.main"]
