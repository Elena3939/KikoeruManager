# KikoeruManager

一个本地 / 远程通用的 DLsite 同人音声压缩包智能管理工具，覆盖「自动解压 → 元数据获取 → 智能分类 → 库存入库 → 字幕匹配 → 重复处理 → 任务追踪」整条链路，支持本地多盘、群晖远程库存与桌面托盘运行。

[![GHCR](https://img.shields.io/badge/ghcr.io-kikoerumanager-2496ED?logo=docker)](https://github.com/Elena3939/KikoeruManager/pkgs/container/kikoerumanager)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> **重要提示**：使用本软件即表示已阅读并同意 [免责声明与使用条款](DISCLAIMER.md)。本软件仅限 18 周岁及以上成年人使用。

### 功能介绍

- **智能解压**：自动识别压缩格式 / 修复错误后缀名 / 密码字典爆破 / 分卷合并 / 嵌套压缩包递归处理 / 单层包装目录折叠
- **DLsite 元数据**：自动抓取 RJ 作品信息、社团、CV、标签、封面，支持关联作品（多语言版本）链路
- **智能分类**：按社团 / 系列 / RJ 段规则自动分类入库，支持多个本地库存与多个群晖远程库存并存
- **群晖远程库存**：基于 SYNO.FileStation REST API，支持远程列表 / 上传 / 搜索 / 重命名 / 移动，OTP 自动续期；上传支持目录与单文件分块流式
- **库存搜索索引**：常驻 SQLite 索引（`library_index_entries` + `library_index_status`），跨库 RJ 搜索 / 库存大小统计 / 问题作品路径拾回 ms 级响应；支持本地 + 远程两种扫描器，0.5s 实时上报已扫描数
- **问题作品工作台**：解压失败 / 重复作品 / 待人工的统一在 GUI 拍板（保留新版 / 跳过 / 合并），不再卡在任务失败队列
- **RJ 字幕工作台**：扫描 → 抓取 → 清洗 → 自动匹配 → 人工筛选 → 落盘 全流程；支持顺序配对、内容指纹去重、远程字幕目录直接写入
- **ASMR 同步下载**：扫描字幕目录 → 缺失作品列表 → 批量下载 → 重命名 → 自动入库
- **社团补全工作台**：按社团关键词索引服务器持有作品，列出缺失项，预览后批量下载补全；支持 IMAP 邮件监听新发售
- **任务中心**：所有耗时操作（下载 / 上传 / 解压 / 字幕 / 重命名 / 同步）都是后台任务，可暂停 / 取消 / 重试 / 批量处理，含 `paused / waiting_manual / waiting_retry` 等状态
- **操作历史**：树形聚合（不是平铺流水），按业务键合并子任务、保留人工干预轨迹，支持类型 / 状态 / 时间多维筛选
- **通知系统**：内建 SSE 通知中心 + 铃铛、SMTP 邮件发送、IMAP 邮件监听；邮件模板提供 Block Editor 拖拽编辑器（积木式），支持文件树 / RJ 卡片 / 统计 / 日志 / diff 等业务块
- **密码工作台**：DLsite 压缩包密码本地存储与去重合并，自动尝试历史密码
- **桌面托盘**：基于 `pystray`，开机自启 / 后台运行 / 一键打开 Web；Windows 一键打包 exe

### 源码安装部署

本项目分为后端（`FastAPI`）和前端（`Vue 3 + Vite`）两部分。

```bash
# 1. 克隆仓库
git clone https://github.com/Elena3939/KikoeruManager.git
cd KikoeruManager

# 2. 后端
cd backend
python -m venv venv
venv\Scripts\activate           # Windows
# source venv/bin/activate      # Linux / macOS
pip install -r requirements.txt
python -m app.main

# 3. 前端（新终端）
cd frontend
npm install
npm run dev
```

或在 Windows 直接：

```bat
.\start-dev.bat                 # 一键拉起前端 + 后端
```

启动后访问 <http://localhost:8000>，前端 dev server 默认在 <http://localhost:5173>。

### Windows 桌面版

打包好的 exe 见 [Releases](https://github.com/Elena3939/KikoeruManager/releases)，下载解压后双击 `KikoeruManager.exe` 即可，自带托盘 + 自动打开 Web。

也可在本地从源码打包：

```bat
.\build-release.bat             # 构建前端 + PyInstaller 打包后端 + 生成发行 zip
```

### Docker 部署

```bash
# 拉取镜像（Dockerhub）
docker pull elena39/kikoerumanager:latest
```
```bash
# 拉取镜像（GHCR）
docker pull ghcr.io/elena3939/kikoerumanager:latest
```

或用 `docker-compose.yml`：

```yaml
services:
  kikoerumanager:
    image: ghcr.io/elena3939/kikoerumanager:latest
    container_name: kikoerumanager
    ports:
      - "5555:5555"
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Asia/Shanghai
    volumes:
      - ./config:/app/config              # 配置目录（config.yaml）
      - ./data:/app/data                  # 数据库 / 日志 / 缓存
      - /your/path/input:/input           # 待处理压缩包
      - /your/path/library:/library       # 音声库存
      - /your/path/temp:/temp             # 临时解压目录
      - /your/path/processed:/processed   # 已处理压缩包归档
      - /your/path/subtitles:/Subtitles   # ASMR 同步字幕目录
    restart: unless-stopped
```

启动后访问 <http://localhost:5555>。

### 技术栈

后端：

- `FastAPI`（Web 框架）
- `SQLAlchemy` + `SQLite`（持久化，单文件部署友好）
- `Pydantic`（配置 / Schema 校验）
- `httpx` + `cheerio`-like 解析（DLsite 爬虫）
- `Synology DSM REST API`（远程群晖通信）
- `pystray` + `Pillow`（桌面托盘）
- `PyInstaller`（Windows 打包）
- `imapclient` + `aiosmtplib`（邮件监听 / 发送）
- `nh3`（HTML 清洗）
- `orjson`（快速 JSON 反序列化）

前端：

- `Vue 3` + `Vite` + `Pinia`
- `Element Plus` + `Tailwind CSS`
- `lucide-vue-next`（图标，全站统一）
- `@lottiefiles/dotlottie-vue`（动效）
- `Tiptap`（富文本 / 邮件 Block Editor）

### 项目目录结构

```
├── backend/                         # FastAPI 后端
│   ├── app/
│   │   ├── api/                     # REST 路由总入口（routes.py）
│   │   ├── core/                    # 业务核心服务
│   │   │   ├── library_index/       # 库存搜索索引基础设施（SQLite + 双扫描器）
│   │   │   ├── activity_log_*       # 操作历史树形聚合 + lite 路径
│   │   │   ├── activity_log_aggregator/  # 历史聚合算法
│   │   │   ├── block_renderers/     # 邮件 Block Editor 服务端渲染
│   │   │   ├── library_manager.py   # 本地 + 群晖库存统一管理
│   │   │   ├── task_engine.py       # 任务调度引擎
│   │   │   ├── task_center_service.py
│   │   │   ├── conflict_resolution_service.py
│   │   │   ├── rj_subtitle_service.py
│   │   │   ├── linked_subtitle_import_service.py
│   │   │   ├── circle_completion_service.py
│   │   │   ├── kikoeru_duplicate_service.py
│   │   │   ├── asmr_resource_service.py
│   │   │   ├── notification_template_service.py
│   │   │   ├── notification_helper.py
│   │   │   ├── variable_registry.py
│   │   │   ├── email_watcher_service.py
│   │   │   └── synology_*.py        # 群晖通信 + SynologyError 体系
│   │   ├── models/                  # SQLAlchemy 模型
│   │   └── config/                  # Pydantic 配置
│   ├── tests/                       # 单元 + 集成测试（含库存索引 54 个 case）
│   ├── scripts/                     # 一次性运维脚本
│   ├── requirements.txt
│   └── build.py                     # PyInstaller 打包入口
├── frontend/                        # Vue3 + Vite 前端
│   ├── src/
│   │   ├── views/                   # 页面（Library / Tasks / ActivityHistory / Conflicts / CircleCompletion / Settings 等）
│   │   ├── components/              # 共享组件
│   │   │   ├── library/             # 库存工作台子组件
│   │   │   ├── download/            # 下载任务工作台
│   │   │   ├── upload/              # 上传任务工作台
│   │   │   ├── activity/            # 操作历史详情
│   │   │   ├── circle/              # 社团补全相关
│   │   │   ├── settings/            # 设置面板（含 block-editor 邮件模板）
│   │   │   ├── subtitle-import/     # 字幕导入工作台
│   │   │   ├── system/              # 系统弹窗 / 通知铃铛
│   │   │   └── common/              # AppDropdown / AppLottieIcon / AppEmptyState 等
│   │   ├── composables/             # 复用逻辑（useNotifications / useSystemPrompt 等）
│   │   ├── api/                     # API 封装
│   │   └── router/
│   ├── package.json
│   └── vite.config.js
├── docs/                            # 文档
│   ├── INTRODUCTION.md
│   ├── BUILD.md
│   └── notification-template-builder.md
├── desktop_app.py                   # 桌面托盘入口（pystray）
├── docker-compose.yml               # Docker Compose 模板
├── unraid-template.xml              # Unraid 模板
├── start-all.bat / start-dev.bat    # Windows 一键启动
├── build-release.bat                # Windows 一键打包发行
├── .github/workflows/ghcr.yml       # CI：GHCR + Docker Hub 自动构建
├── DISCLAIMER.md                    # 免责声明
└── README.md
```

### TODO

- [x] 多本地库存 + 多远程群晖库存
- [x] 库存搜索索引（SQLite + 双扫描器 + self_mutation）
- [x] 问题作品 GUI 拍板（保留新版 / 跳过 / 合并）
- [x] RJ 字幕工作台（扫描 / 抓取 / 配对 / 落盘 全流程）
- [x] ASMR 同步下载
- [x] 社团补全工作台 + IMAP 邮件监听新发售
- [x] 任务中心（暂停 / 取消 / 重试 / 批量）
- [x] 操作历史树形聚合
- [x] 邮件 Block Editor + 拖拽变量 pill + 业务数据块
- [x] 桌面托盘 + Windows 打包 + Docker 镜像
- [ ] 用户认证 / 多用户支持
- [ ] 第三方音声资源站对接（FANZA / 其他同人站）
- [ ] 内嵌音声播放器（封面 + 章节 + 字幕同步）
- [ ] 收藏 / 标星 / 评分 / 评论
- [ ] 字幕自动翻译 + OCR 字幕识别
- [ ] 邮件监听规则编辑器 + 自定义触发条件

### 文档

- [免责声明与使用条款](DISCLAIMER.md) — **使用即默认同意**
- [软件介绍](docs/INTRODUCTION.md)
- [构建指南](docs/BUILD.md)
- [Docker 部署](DOCKER_DEPLOY.md)
- [快速上手](START_GUIDE.md)
- [给后续 AI / 自动化代理的接手说明](AGENTS.md)
- API 文档：服务启动后访问 <http://localhost:8000/docs>

### 感谢

本项目在参考借鉴、致敬以下开源项目：

- [Sakyoriii/prekikoeru](https://github.com/Sakyoriii/prekikoeru) — DLsite 资源自动解压整理工具
- [yodhcn/dlsite-doujin-renamer](https://github.com/yodhcn/dlsite-doujin-renamer) — DLsite 同人作品重命名工具
- [Number178/kikoeru-express](https://github.com/Number178/kikoeru-express) — 同人音声专用流媒体服务器
- [canforgive/KikoeruTool](https://github.com/canforgive/KikoeruTool) — DLsite 音声作品智能整理工具（基于原型开发）

### 声明

本项目作为开源软件，本身不包含任何版权内容或其它违反法律的内容。项目中的程序是为了个人用户管理自己所有的合法数据资料而设计的。

程序作者并不能防止内容提供商（如各类网站）或其它用户使用本程序提供侵权或其它非法内容。程序作者与使用本程序的各类内容提供商并无联系，不为其提供技术支持，也不为其不当使用承担法律责任。

详细使用条款见 [DISCLAIMER.md](DISCLAIMER.md)。**本软件仅限 18 周岁及以上成年人使用。**

### 许可协议

[MIT License](LICENSE)
