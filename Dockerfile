# 多阶段构建 Dockerfile
# 阶段1：构建前端
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# 复制前端依赖
COPY frontend/package*.json ./
# 增大 Node.js 堆内存上限，避免大型 Vite 项目 OOM
RUN NODE_OPTIONS="--max-old-space-size=2048" npm ci

# 复制前端源码并构建
COPY frontend/ ./
RUN NODE_OPTIONS="--max-old-space-size=2048" npm run build

# 阶段2：后端运行环境
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（官方 7-Zip 24.08、unar 和 opencc）
# - 用 TARGETARCH（buildx 自动注入）选择 x64 / arm64 包，兼容 amd64 群晖和 ARM64 群晖。
# - 显式 uninstall p7zip-full，避免 /usr/bin/7z 覆盖 /usr/local/bin/7zz 的 PATH 优先级。
# - 构建末尾打印 `7zz -version`，构建失败或版本错位时立刻暴露，不会悄悄回退到旧 p7zip。
ARG TARGETARCH
RUN sed -i 's/Components: main/Components: main contrib non-free non-free-firmware/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        wget \
        xz-utils \
        unar \
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
    && rm -f /tmp/7z.tar.xz /usr/bin/7z /usr/bin/7za /usr/bin/7zr \
    && rm -rf /var/lib/apt/lists/* \
    && echo "===== 7-Zip version check =====" \
    && /usr/local/bin/7zz --help | head -3 \
    && /usr/local/bin/7zz --help | grep -q "24.08" \
    && echo "===== 7-Zip 24.08 installed OK =====" \
    && which unar && unar --version 2>&1 | head -1 \
    && which lsar && echo "===== unar + lsar installed OK ====="

# 复制后端依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码
COPY backend/app/ ./app/

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
# 应用端口，可通过 docker run -e PORT=xxxx 覆盖
ENV PORT=5555

# 暴露端口（与 PORT 默认值一致）
EXPOSE 5555

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:' + os.environ.get('PORT','5555') + '/api/health')" || exit 1

# 启动命令
CMD ["python", "-m", "app.main"]
