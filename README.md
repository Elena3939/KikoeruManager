# Prekikoeru

Prekikoeru 是一个面向 DLsite 音声作品整理场景的桌面/Web 混合工具，核心目标是把压缩包、已有文件夹、字幕目录和库存目录串成一条可配置的整理流水线。

项目当前包含：

- FastAPI 后端
- Vue 3 + Element Plus 前端
- Windows 桌面打包入口与系统托盘
- Docker 部署方案
- 已有文件夹处理、增强查重、ASMR 同步下载、库存打包等专项能力

> 使用前请先阅读 [免责声明](DISCLAIMER.md)。项目适用于成年人对本地文件进行整理、归档与检索。

## 主要功能

- 自动扫描输入目录并创建处理任务
- 解压压缩包、支持 7-Zip、嵌套压缩包和密码列表
- 抓取作品元数据并按模板重命名
- 过滤不需要的文件或目录
- 按社团、系列、RJ 号范围等规则分类入库
- 检测直接重复、关联作品冲突、翻译版本冲突
- 处理“已有文件夹”而不重新解压
- 从字幕目录扫描 RJ 号，执行 ASMR 同步下载
- 管理密码库、已处理压缩包清理、库存打包
- 提供 Kikoeru 服务器查重与路径映射能力

## 页面模块

当前前端页面与仓库代码一致，包含：

- 概览
- 任务队列
- 问题作品
- 库存管理
- 密码库
- 已有文件夹
- 同步下载
- 库存打包
- 设置
- 日志

## 快速开始

### Windows 普通使用

1. 先执行 [setup.bat](D:/Clash%20Verge/KikoeruTool_Elena/setup.bat) 安装依赖。
2. 执行 [start-all.bat](D:/Clash%20Verge/KikoeruTool_Elena/start-all.bat) 启动前后端。
3. 浏览器访问 `http://localhost:5173`。
4. 后端 API 文档位于 `http://localhost:8000/docs`。

如果你要打包桌面版，可参考 [docs/BUILD.md](docs/BUILD.md)。

### 本地开发

1. 安装 Python 3.11+ 与 Node.js 18+。
2. 后端依赖位于 [backend/requirements.txt](backend/requirements.txt)。
3. 前端依赖位于 [frontend/package.json](frontend/package.json)。
4. 可直接使用 [start-dev.bat](D:/Clash%20Verge/KikoeruTool_Elena/start-dev.bat)、[start-dev.ps1](D:/Clash%20Verge/KikoeruTool_Elena/start-dev.ps1) 或 [start-dev.sh](D:/Clash%20Verge/KikoeruTool_Elena/start-dev.sh)。

### Docker 部署

仓库已提供 [Dockerfile](D:/Clash%20Verge/KikoeruTool_Elena/Dockerfile) 与 [docker-compose.yml](D:/Clash%20Verge/KikoeruTool_Elena/docker-compose.yml)。详细说明见 [DOCKER_DEPLOY.md](DOCKER_DEPLOY.md)。

## 配置说明

项目的配置模型定义在 [backend/app/config/settings.py](backend/app/config/settings.py)。

常用配置包括：

- 存储路径：输入目录、临时目录、库存目录、已处理压缩包目录、已有文件夹目录、字幕目录
- 解压配置：7-Zip 路径、密码列表、嵌套解压深度
- 元数据配置：超时、代理、封面处理
- 重命名配置：模板、CV 拼接、标签数量、扁平化子目录
- 分类配置：按社团、系列、RJ 号范围分类
- 自动流程配置：普通任务、已有文件夹、ASMR 同步的步骤开关
- Kikoeru 服务器查重配置
- 密码库清理、已处理压缩包清理、库存打包配置

仓库内现有示例配置文件在 [backend/config/config.yaml](backend/config/config.yaml)。

注意：

- 开发模式下，如果没有设置 `CONFIG_PATH`，后端会按默认逻辑寻找或创建运行时配置文件。
- Docker 部署时通过环境变量将配置固定到 `/app/config/config.yaml`。
- 桌面打包版会在 `exe` 同级的 `data/config/config.yaml` 中生成可编辑配置。

## 文档索引

- [QUICK_START.md](QUICK_START.md)：最短上手路径
- [START_GUIDE.md](START_GUIDE.md)：Windows 首次安装与启动说明
- [docs/INTRODUCTION.md](docs/INTRODUCTION.md)：产品介绍与模块说明
- [docs/LOCAL_DEV.md](docs/LOCAL_DEV.md)：本地开发说明
- [docs/BUILD.md](docs/BUILD.md)：Windows 打包说明
- [docs/TESTING.md](docs/TESTING.md)：测试说明
- [docs/7ZIP_CONFIG.md](docs/7ZIP_CONFIG.md)：7-Zip 配置说明
- [DOCKER_DEPLOY.md](DOCKER_DEPLOY.md)：Docker 部署说明
- [CONFIG_HOT_RELOAD_README.md](CONFIG_HOT_RELOAD_README.md)：配置重载说明
- [EXISTING_FOLDERS_DUPLICATE_CHECK.md](EXISTING_FOLDERS_DUPLICATE_CHECK.md)：已有文件夹查重说明
- [DUPLICATE_CHECK_IMPROVEMENT.md](DUPLICATE_CHECK_IMPROVEMENT.md)：增强查重说明
- [TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md)：技术架构说明

## 项目结构

```text
Prekikoeru/
├── backend/                 后端服务、配置模型、核心处理逻辑
├── frontend/                前端界面与页面模块
├── docs/                    补充文档
├── desktop_app.py           Windows 桌面版入口
├── build-release.bat        Windows 单文件打包脚本
├── package.bat              旧版打包脚本
├── start-all.bat            一键启动前后端
├── start-dev.*              开发环境启动脚本
└── docker-compose.yml       Docker Compose 示例
```

## 维护建议

- 不要把真实账号、Token、代理和密码直接提交到仓库配置文件中。
- 变更配置模型时，同步更新 [backend/app/config/settings.py](backend/app/config/settings.py) 和相关文档。
- 调整页面模块时，同步更新本文档与 [docs/INTRODUCTION.md](docs/INTRODUCTION.md)。
