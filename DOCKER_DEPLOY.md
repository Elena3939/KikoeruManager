# Prekikoeru Docker 部署说明

本仓库已提供：

- [Dockerfile](D:/Clash%20Verge/KikoeruTool_Elena/Dockerfile)
- [docker-compose.yml](D:/Clash%20Verge/KikoeruTool_Elena/docker-compose.yml)

当前镜像构建方式为：

1. 先在 Node 18 环境中构建前端
2. 再在 Python 3.11 环境中安装后端并拷贝静态文件
3. 运行入口为 `python -m app.main`

## 目录映射建议

推荐至少映射以下目录：

- `./config:/app/config`
- `./data:/app/data`
- `/path/to/input:/input`
- `/path/to/temp:/temp`
- `/path/to/library:/library`

按需增加：

- `/path/to/existing:/existing`
- `/path/to/processed:/processed`

如果需要字幕同步，也建议为字幕目录提供稳定映射，并在应用设置中填写对应路径。

## Docker Compose 示例

```yaml
version: "3.8"

services:
  prekikoeru:
    build:
      context: .
      dockerfile: Dockerfile
    image: prekikoeru:latest
    container_name: prekikoeru
    ports:
      - "8000:8000"
    environment:
      - CONFIG_PATH=/app/config/config.yaml
      - DATA_PATH=/app/data
      - TZ=Asia/Shanghai
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - /path/to/input:/input
      - /path/to/temp:/temp
      - /path/to/library:/library
      - /path/to/existing:/existing
      - /path/to/processed:/processed
    user: "0:0"
    privileged: true
    restart: unless-stopped
```

启动：

```bash
docker compose up -d --build
```

查看日志：

```bash
docker compose logs -f
```

## 访问地址

- 应用：`http://localhost:8000`
- API 文档：`http://localhost:8000/docs`

Docker 模式下前端静态文件由 FastAPI 直接托管，不需要单独启动 Vite。

## 首次启动后要做什么

1. 打开设置页面
2. 确认应用内路径与容器映射路径一致
3. 配置 `seven_zip_path`
4. 配置重命名、过滤、分类规则
5. 小批量测试后再开启监视器

## 关于配置文件

Docker 环境下后端通过环境变量固定读取：

```text
/app/config/config.yaml
```

首次运行如文件不存在，会在该位置生成默认配置。

仓库中的 [backend/config/config.yaml](backend/config/config.yaml) 可作为模板参考，但 Docker 实际运行以挂载目录中的配置为准。

## 健康检查

仓库中的 Compose 和 Dockerfile 都已经内置健康检查，请求地址为：

```text
http://localhost:8000/api/health
```

## 常见问题

### 页面打不开

- 确认容器已启动
- 确认 8000 端口已映射
- 执行 `docker compose logs -f`

### 配置没生效

- 检查容器内读取的是否是 `/app/config/config.yaml`
- 不要只修改仓库里的 `backend/config/config.yaml`

### 文件权限异常

当前 Compose 示例使用 `privileged: true` 与 `user: "0:0"`。如果你要收紧权限，需要自行验证容器对映射目录的读写能力。

### 7-Zip 问题

镜像已安装 `p7zip-full`。通常只需在配置中使用默认值 `7z`。

## 适合 Docker 的场景

- 作为家庭服务器上的统一整理服务
- 用映射目录统一处理下载目录、库存目录和归档目录
- 不需要本地开发热更新界面
