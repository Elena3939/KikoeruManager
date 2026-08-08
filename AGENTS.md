# AGENTS.md

给后续 AI / 自动化代理的接手说明。这里不写项目百科，只写会影响判断、改动、验证、提交的规则。

## 0. 沟通与提交

- 永远用中文回答。
- 用户要修复就实际看代码、实际改、实际验证，不要给空泛方案。
- 不要猜：先用 `rg` / `git diff` / 文件内容确认。
- 有大块代码或命令时拆小块，避免 Windows 命令长度限制。
- 说明、注释、commit 信息都用中文。
- 提交必须按业务模块拆批；commit 信息写清业务影响，不要写前缀，不要带 tag 号。
- 不要回退用户已有改动；遇到不属于本任务但已经存在的 diff，只能理解并绕开。
- 发布 tag 只能用标准 semver：`v1.2.3`，不要用 `1.2.3` 或 `v1.02`。
- 重启项目只用仓库根目录的 `start-all.bat`；不要手写分散的 uvicorn / Vite 重启命令替代整项目重启。

### 0.1 线上生产连接

- 生产服务器只允许使用项目 SSH 别名 `kikoerumanager-production`，目标主机登录后 `hostname` 必须严格等于 `Elena`；不满足时立即停止，禁止继续查库、看日志或操作容器。
- SSH 配置固定在 `.codex/ssh/config`，连接入口固定为 PowerShell：`& .\.codex\ssh\connect-production.ps1 "hostname"`。不要绕开项目配置手写 IP，也不要连接其它同名/相似服务器。
- 认证默认使用 `C:/Users/Elena/.ssh/kikoerumanager_server_ed25519`，RSA 密钥 `C:/Users/Elena/.ssh/kikoerumanager_server_rsa` 仅作备用；两者都已通过 `BatchMode + publickey` 验证。不要再向用户询问 SSH 密码。
- `.codex/ssh/connect-production.ps1` 只在公钥失败时才使用 `.codex/ssh/production-password.txt` 的本机密码回退；该文件和数据库环境文件均为敏感本地产物，禁止提交、打印或写入 `AGENTS.md`。
- 生产容器名固定为 `elena39-kikoerumanager`，Docker CLI 固定为 `/var/packages/Docker/target/usr/bin/docker`；群晖 sudo 环境不要依赖 `PATH` 里的 `docker`。
- 生产应用端口为 `5555`，宿主 PostgreSQL 映射端口为 `15432`。数据库连接信息只读 `.codex/ssh/production-db.env`，不得把账号密码写入命令输出、日志或提交。
- 线上排查顺序：先验证 `hostname`，再查看容器镜像/运行态/健康状态，然后查 `docker logs` 和 PostgreSQL；未经用户明确要求，不停止、删除、重建容器，不改线上数据。
- 群晖 Docker 导入 JSON 使用 `/docker`、`/ASMR` 等 DSM 虚拟共享路径；Docker CLI inspect 显示的是 `/volume1`、`/volume4`、`/volume5` 真实 bind path。禁止把导入 JSON 的虚拟路径直接拼成 `docker run -v`。

## 1. 项目基线

- 产品名统一为 `KikoeruManager`；技术命名统一小写 `kikoerumanager`。
- 不要把旧名 `Prekikoeru`、`KikoeruTool_Elena`、`kikoeruTool` 混回标题、exe、镜像、文档、环境变量、localStorage key、SSE 事件名。
- GitHub 目标仓库是 `Elena3939/KikoeruManager`。
- GHCR 镜像目标：`ghcr.io/elena3939/kikoerumanager`。
- Docker Hub 镜像目标：`elena39/kikoerumanager`。
- 当前产品是多工作台桌面化工具，不是传统后台管理系统。
- 高频业务：仪表盘、库存主工作台、RJ 字幕工作台、任务中心、操作历史、问题作品、社团补全、下载 / 上传工作台、HTTP 外链下载（含 PikPak / Google Drive / Gofile / OneDrive / Transfer.it）、百度网盘、AI 字幕配对、密码工作台、库存备份、安全网关、通知模板。

## 2. 技术栈与依赖

### 后端

- 后端：`FastAPI` + SQLAlchemy + PostgreSQL 18（`psycopg` 驱动，Alembic baseline）。
- 依赖清单：`backend/requirements.txt`。
- 解压依赖：运行环境必须有官方 `7zz 24.08+`，并保留 `unar` / `lsar`。
- 不要回退到旧 `p7zip-full`。Dockerfile 会显式 purge p7zip，并把官方 `7zz` 链接到 `/usr/local/bin/7zz` 和 `/usr/local/bin/7z`。
- 百度网盘依赖 `BaiduPCS-Go`，Dockerfile 会按架构安装并链接 `/usr/local/bin/BaiduPCS-Go` / `baidupcs-go`；不要把它当成可选工具删掉。
- Redis 是运行态依赖，Python 依赖 `redis>=5.0.0`；只承载短期运行态、事件流和高频缓存，PostgreSQL 仍是最终事实源。
- 新增的伪装 ZIP 探测只用 Python 标准库 `zipfile` / `os`，不用加 requirements。
- 运行态数据库不再保留 SQLite 兼容；`DATABASE_URL` 必须使用 `postgresql+psycopg://...`，存在时覆盖配置文件中的 `database.*` 字段。
- 本地 Windows 通过 `setup.bat` / `scripts/install-postgresql.ps1` 检查、安装、初始化 PostgreSQL，并把随机密码明文写入 `data/config/config.yaml` 方便后续查看和修改。
- `orjson` 是 ActivityLog / JSON 列性能依赖，`nh3` 是邮件 HTML 清洗安全边界，`brotlicffi` 是 DLsite / httpx br 响应解码依赖，`transferit-py` 是 Transfer.it 平台解析依赖；不要因为 import 不集中就移除。
- PostgreSQL 搜索依赖 `pg_trgm` GIN 索引，库存、操作历史、任务中心、已处理归档都有 trigram 索引维护逻辑；不要恢复 SQLite FTS 或另起一套 tokenizer。

### 前端

- 前端：`Vue 3 + Vite + Pinia + Element Plus + Tailwind CSS + Reka UI + VueUse + TanStack Table / Virtual + AG Grid + lucide-vue-next`。
- 包清单以 `frontend/package.json` + `frontend/package-lock.json` 为 Docker 构建基准；根 `Dockerfile` 使用 `npm ci`。
- `frontend/pnpm-lock.yaml` 也要同步维护，避免本地 pnpm 用户装包失败。
- 当前直接依赖必须保留：
  - `@tanstack/vue-table`：库存页文件表格模型。
  - `@tanstack/vue-virtual`：社团作品虚拟滚动视口。
  - `@tiptap/core` / `@tiptap/vue-3` / `@tiptap/starter-kit` / table/link 扩展：邮件 Block Editor 和富文本变量 pill 直接使用。
  - `lucide-vue-next`：全站图标唯一来源。
  - `@lottiefiles/dotlottie-vue` / `lottie-web`：动效。
  - `ag-grid-community` / `ag-grid-vue3`：当前构建和分包配置仍保留，不确认调用链前不要删依赖。
- 主题系统统一走 `frontend/src/composables/useTheme.ts`（light / dark / system 三态，挂 `dark` + `kikoerumanager-dark` 两个 class），暗色样式集中在 `frontend/src/dark-mode.css`；不要再造第二套主题状态机。
- 加载态按钮统一复用 `frontend/src/components/ui/stateful-button.vue`，主题切换按钮统一复用 `frontend/src/components/magicui/AnimatedThemeToggler.vue`；不要每个按钮手写 spinner 或另起主题切换逻辑。
- Vite 项目体积较大，`frontend/package.json` 的 `dev/build/preview` 和根 `Dockerfile` 都使用 `--max-old-space-size=4096`，不要降回 2048。

### Docker / 环境

- 根 `Dockerfile` 是完整前后端单镜像，并内置 PostgreSQL 18 server 与 Redis；`docker/entrypoint.sh` 会在没有 `DATABASE_URL` 时初始化并启动容器内 PostgreSQL，没有 `KIKOERUMANAGER_REDIS_URL` 时启动内置 Redis。
- `backend/Dockerfile` 是后端基础镜像，只安装 PostgreSQL 客户端和 Python 驱动，默认连接外部 PostgreSQL。
- 两个 Dockerfile 都必须保留官方 `7zz 24.08`、`unar`、`lsar`；根 Dockerfile 还要保留 `BaiduPCS-Go` 和 `redis-server`；不要恢复 SQLite FTS5 构建检查。
- Docker 单镜像部署必须持久化挂载 `/app/postgres`，否则更新 / 重建容器后数据库会落在容器层里丢失。
- Docker 单镜像的 Redis AOF / 日志默认在 `/app/data/redis`，`/app/data` 也必须持久化挂载；显式设置 `KIKOERUMANAGER_REDIS_URL` 时使用外部 Redis。
- Docker 里如显式设置 `DATABASE_URL`，则跳过内置 PostgreSQL 并连接外部 PostgreSQL；默认 compose 不设置 `DATABASE_URL`。
- 伪装 ZIP 解压会在 `storage.temp_path` 下创建 `kikoerumanager_embedded_zip_*.zip` 临时视图。Docker 部署时这个 temp 路径要挂到有足够空间的卷，不要放很小的容器层。
- temp 视图成功、失败、取消都必须清理；原始文件路径不能被临时视图覆盖。

## 3. 关键入口

### 后端入口

- API 总入口：`backend/app/api/routes.py`
- 配置模型：`backend/app/config/settings.py`
- 数据库模型：`backend/app/models/database.py`
- 任务引擎：`backend/app/core/task_engine.py`
- 任务中心：`backend/app/core/task_center_service.py`
- 任务中心物化：`backend/app/core/task_center_materialization_service.py`
- Redis 运行态：`backend/app/core/redis_service.py`
- 实时事件：`backend/app/core/realtime_event_service.py`、`backend/app/core/task_center_event_service.py`
- 操作审计：`backend/app/core/activity_log_service.py`、`backend/app/core/activity_log_writer.py`、`backend/app/core/activity_log_aggregator/`
- 操作审计压缩 / rollup：`backend/app/core/activity_log_compactor.py`、`backend/app/core/activity_log_rollup_service.py`、`backend/app/core/activity_log_lite.py`
- 数据库维护：`backend/app/core/database_maintenance_service.py`
- 库存管理：`backend/app/core/library_manager.py`
- 库存索引：`backend/app/core/library_index/`
- 库存社团聚合：`backend/app/core/library_circle_aggregation_service.py`
- 库存文件夹补全：`backend/app/core/library_folder_completion_service.py`
- 解压：`backend/app/core/extract_service.py`
- 压缩包识别：`backend/app/core/file_processor.py`、`backend/app/core/archive_detection.py`
- RJ 字幕：`backend/app/core/rj_subtitle_service.py`、`backend/app/core/linked_subtitle_import_service.py`
- ASMR 下载 / 上传：`backend/app/core/asmr_resource_service.py`
- HTTP 外链下载：`backend/app/core/http_download_service.py`（底层 aria2 RPC，含 PikPak / Google Drive / Gofile / OneDrive / Transfer.it 解析）、`backend/app/core/google_drive_oauth.py`
- 百度网盘：`backend/app/core/baidu_netdisk_service.py`
- AI 字幕配对：`backend/app/core/ai_subtitle_match_service.py`
- 安全网关：`backend/app/core/security_gate_service.py`
- 社团补全：`backend/app/core/circle_completion_service.py`、`backend/app/core/kikoeru_duplicate_service.py`
- DLsite 特典探测：`backend/app/core/dlsite_bonus_probe_service.py`
- 冲突处理：`backend/app/core/conflict_resolution_service.py`
- 通知：`backend/app/core/notification_template_service.py`、`notification_helper.py`、`task_notification_service.py`、`variable_registry.py`、`block_renderers/__init__.py`、`html_sanitizer.py`

### 前端入口

- 主布局：`frontend/src/App.vue`
- 路由：`frontend/src/router/index.js`
- API 封装：`frontend/src/api/index.js`
- 仪表盘：`frontend/src/views/Dashboard.vue`
- 库存页：`frontend/src/views/Library.vue`
- 库存备份：`frontend/src/views/LibraryBackup.vue`
- 任务中心：`frontend/src/views/Tasks.vue`
- 操作历史：`frontend/src/views/ActivityHistory.vue`
- 问题作品：`frontend/src/views/Conflicts.vue`
- 已有文件夹处理：`frontend/src/views/ExistingFolders.vue`
- 社团补全：`frontend/src/views/CircleCompletion.vue`
- ASMR 同步：`frontend/src/views/ASMRSync.vue`
- 百度网盘入口：`frontend/src/views/ASMRSync.vue` 的百度 tab + `frontend/src/components/asmr/BaiduNetdiskPanel.vue`；`/baidu-netdisk` 只做重定向。
- 密码工作台：`frontend/src/views/PasswordVault.vue`
- 字幕导入：`frontend/src/views/SubtitleImport.vue`
- 日志：`frontend/src/views/Logs.vue`
- 安全网关闸页：`frontend/src/views/VerifyGate.vue`、`frontend/src/views/BlockedGate.vue`
- 设置页：`frontend/src/views/Settings.vue`（按面板拆分为 `frontend/src/components/settings/*SettingsPanel.vue`，含 HTTP / AI 字幕 / 百度网盘 / 安全网关 / 通知等）
- 实时事件入口：`frontend/src/composables/useRealtimeEvents.js`；旧 `useTaskCenterStream.js` 只给任务中心兼容，新增实时刷新默认接 `/api/events/stream`。

### 前端基座组件

- 下载任务工作台：`frontend/src/components/download/DownloadTaskWorkbenchDialog.vue`
- 上传任务工作台：`frontend/src/components/upload/UploadTaskWorkbenchDialog.vue`
- 本地 / 服务端上传预览：`frontend/src/components/circle/CircleLocalUploadDialog.vue`、`frontend/src/components/common/ServerUploadPreviewDialog.vue`
- 社团作品虚拟视口：`frontend/src/components/circle/CircleWorksViewport.vue`
- 社团作品卡片 / 行：`frontend/src/components/circle/WorkCard.vue`、`frontend/src/components/circle/WorkListRow.vue`
- 库存移动弹窗：`frontend/src/components/library/LibraryMoveDialog.vue`
- 库存索引徽章：`frontend/src/components/library/LibraryIndexBadge.vue`
- 库存社团聚合 / 内容弹窗：`frontend/src/components/library/FolderContentsDialog.vue`
- 统一筛选下拉：`frontend/src/components/common/AppDropdown.vue`
- 系统弹窗：`frontend/src/components/system/SystemPromptDialog.vue`、`SystemPromptHost.vue`、`frontend/src/composables/useSystemPrompt.js`
- 通知中心：`frontend/src/components/system/NotificationBell.vue`、`frontend/src/composables/useNotifications.js`
- 后台工作台小窗：`frontend/src/components/workbench/BackgroundWorkbenchHost.vue`、`frontend/src/composables/useBackgroundWorkbenchManager.js`
- 主题：`frontend/src/composables/useTheme.ts`、`frontend/src/components/magicui/AnimatedThemeToggler.vue`
- 加载态按钮：`frontend/src/components/ui/stateful-button.vue`（loading / success / error 三态可复用动画）
- Lottie 通用组件：`AppLoadingAnimation.vue`、`AppLottieIcon.vue`、`AppLottieSwitch.vue`、`AppLottieProgressBar.vue`

## 4. 配置与敏感数据

- 用户说“改配置文件”且没有明确说运行态时，默认改仓库模板 `backend/config/config.yaml`。
- 桌面 / 开发默认运行配置是 `data/config/config.yaml`；Docker 是 `/app/config/config.yaml`。
- 只有设置 `CONFIG_PATH` 时才读环境变量指定文件。
- 数据库配置字段在 `database.host/port/database/username/password/sslmode/...`；`/api/config` 返回密码必须脱敏，保存时传回 `********` 或省略都要保留磁盘真实密码。
- Redis 配置字段在 `redis.enabled/required/url/namespace/environment/...`；`/api/config` 返回 URL 必须脱敏，保存脱敏 URL 时必须从运行环境或磁盘回填真实值，不能把 `********` 写回配置。
- 默认 Redis `enabled=true`、`required=true`；只有本地临时跳过时才显式设置 `redis.enabled=false` 和 `redis.required=false`，不要在高压后台任务里静默回退到 PostgreSQL 高频写路径。
- `resource_budget.database_write` 是当前数据库写入资源维度；旧 `sqlite_write` 只能作为读取旧配置的兼容 key，保存后不能再写回旧 key。
- `resource_budget.library_index_write` 是库存索引追赶 / 重建写入资源维度，和普通 `database_write` 分开；索引后台追赶不能把业务写入全部挤死。
- `resource_budget.bonus_probe_database_write` 是 DLsite 特典探测缓存 / 状态回写资源维度，不要并入普通 `database_write` 或删掉。
- 不要提交真实密码、Token、代理、私服地址、群晖账号、本地数据库、缓存、`.env`。
- 默认运行态 / 敏感产物：`.env`、`data/`、`backend/data/`、本地数据库、缓存目录、`.codex-backups/`。
- `/api/config` 返回 SMTP 密码必须脱敏为 `********`；保存时前端传回 `********` 或省略 `password`，后端必须保留真实密码。
- 百度网盘 `cookie`、HTTP 下载 `pikpak_* / gofile_token / google_drive_*`、PikPak 多账号 `password / encoded_token`、Redis URL 密码都要在 `/api/config` 和日志中脱敏；保存脱敏表单时必须从磁盘或当前配置回填真实值，不能把 `********` 写回文件。

## 5. 前端设计规则

- 不要交付默认后台风。
- 样式优先级：`Tailwind CSS` -> 项目已有语义 class -> Lottie 动画增强。
- 图标只用 `lucide-vue-next`。
- 所有按钮必须有交互动效：hover `translateY(-2px) scale(1.02)`，active `scale(0.96)`，图标轻旋转。
- 统一动画曲线：`all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)`。
- 页面默认结构：顶部标题区、工具栏、筛选区、主内容、详情 / 抽屉 / 弹窗。
- 新做任务面板、工作台、预览、批量处理、详情抽屉时，对齐 `DownloadTaskWorkbenchDialog.vue`。
- 系统确认 / 输入 / 提醒统一走 `useSystemPrompt`，不要新增散落的 `ElMessageBox.*`。
- 页头按钮统一走 `.page-head-btn`，不要另起一套。
- loading 遮罩绑定到页面内容区或 Modal 主体区，不要盖住整个页面或 Dialog 顶部按钮。

### 5.1 弹窗聚焦态

- 所有弹窗内的交互元素都不要有聚焦描边 / 聚焦投影 / ring。
- 全局兜底已在 `frontend/src/App.vue` 用 `.el-dialog :is(button, input, textarea, [tabindex], [role="button"], .el-input__wrapper, .el-select__wrapper ...):focus / :focus-visible` 统一清掉 `outline`、`box-shadow`、`--tw-ring-*`。
- 新弹窗里的自定义交互元素（chip、行、卡片、自绘按钮）要么落在上面的选择器族里，要么自己补 `:focus` / `:focus-visible` 去聚焦态，不要留浏览器或 Element Plus / Tailwind 默认蓝框。
- 不要为了“可访问性”单独给弹窗元素加回聚焦描边，本项目统一靠 hover / active 动效表达交互。

### 5.2 遮罩态规则

- 弹窗遮罩统一走 `.el-overlay`，暗色态在 `frontend/src/dark-mode.css` 固定为 `rgba(0, 0, 0, 0.52)`。
- 遮罩默认不加背景模糊（已统一移除 `backdrop-filter`）；只有字幕工作台 `.subtitle-workbench-overlay` 等少数容器保留模糊，新弹窗不要随手加 `backdrop-filter: blur()`。
- 页面 / Modal 内的加载遮罩统一用 `.app-loading-mask`（或库存页 `.library-page-loading-mask`），绑定到内容区或 Modal 主体区，不要盖住整页或 Dialog 顶部按钮，暗色样式已在 `dark-mode.css` 适配。

### 5.3 加载态按钮

- 任何“点击后要等待异步结果”的按钮都复用 `frontend/src/components/ui/stateful-button.vue`，它内置 loading / success / error 三态动画，`@click` 返回 Promise 即可自动驱动。
- 不要每个按钮手写 spinner、`v-if="loading"` 切图标或自管禁用态。
- 需要纯图标态加载（如设置页内联按钮）时可用 `LoaderCircle` + `spin-icon`，但成组的主操作按钮优先 `stateful-button`。

### 5.4 暗黑模式与移动端适配

- 所有新页面 / 新弹窗默认就要做暗黑模式：用 `dark-mode.css` 的 `--km-dark-*` 语义变量，或在 `dark-mode.css` 里补 `html.kikoerumanager-dark ...` 规则，不要只做浅色态再说。
- 主题状态只读 `useTheme`，类挂在 `html.dark` + `html.kikoerumanager-dark`；不要自管 localStorage 或另造暗色开关。
- 所有新页面默认要做移动端适配：复用 `frontend/src/index.css` 已有响应式 helper（`.mobile-stack`、`.mobile-full-dialog`、`.is-mobile-hidden`、`.safe-touch-target`、`.safe-area-*` 等），≤640 普通 ElDialog 自动放大、带 `.mobile-full-dialog` / 已注册的弹窗自动全屏。
- 新弹窗想在小屏全屏，给它加 `custom-class="mobile-full-dialog"`，不要自己写一套断点。

## 6. 当前重点变更红线

### 6.1 伪装 ZIP / 带前缀 ZIP

- 核心文件：`backend/app/core/archive_detection.py`、`extract_service.py`、`file_processor.py`。
- 目标场景：Windows 上 Bandizip 能识别的“MP4/垃圾前缀 + 后面真正 ZIP payload”，Linux / Docker 下 `7zz` 直接看文件头会误判。
- `archive_detection.detect_embedded_zip_offset()` 通过 `zipfile.ZipFile` 读中央目录和 local header 偏移，不做全文件扫描。
- `FileProcessor.is_archive()` 对未知后缀 / 非压缩后缀先跑魔数，再跑 embedded ZIP 探测，命中后进入任务队列。
- `ExtractService.extract()` 发现 embedded ZIP 后：
  - 在 `storage.temp_path` 或系统 temp 下创建 `kikoerumanager_embedded_zip_*.zip`。
  - 从 `PK\x03\x04` 开始复制 payload 给 `7zz`。
  - 不修改 `task.source_path`，归档 / 历史仍指向用户原始文件。
  - 密码匹配使用原始文件路径，避免密码库按伪装文件名失效。
  - 成功、失败、取消、异常都调用 `_cleanup_embedded_zip_view()`。
- 不要把整文件读进内存；复制必须流式分块。
- 不要把 embedded ZIP 逻辑扩到所有正常压缩包；offset `0` 的普通 ZIP 不走临时视图。
- Linux / Docker 下 7zz 报 `File name too long` / `errno=36` / `ENAMETOOLONG` 时，`ExtractService` 会尝试单一超长顶层目录重映射：
  - 只对“所有文件都在同一个超长顶层目录下”的压缩包启用。
  - 顶层目录优先按规范化 RJ 名缩短，仍过长时追加 hash；其它路径组件也要做安全字节裁剪。
  - 单文件通过 `7zz x -so` 流式写入目标 `.part`，完成后原子替换，不能把文件一次性读进内存。
  - 解压校验必须接受 `archive_info.path_remap` 后的路径；失败时仍要清理目标尝试目录。

### 6.2 分卷伪装后缀

- 核心判定走 `_is_disguised_volume_suffix`。
- 含非 ASCII 字符或已知伪装词如 `deleted` / `fake` / `junk` 可判定伪装。
- 绝对不要加 `del` / `rm` 等短前缀，避免误伤 `delta01` 这类合法英文。
- 保持 `_detect_disguised_set_with_clean_target` 对 `_CLEAN_ARCHIVE_EXTENSIONS` 的严格白名单限制。

### 6.3 库存主工作台

- `Library.vue` 是主工作台，不是普通列表页。
- 当前文件列表已切到 `@tanstack/vue-table` 管理 row model，配合自定义 DOM 表格样式。
- 库存页存在普通目录、搜索结果、社团聚合虚拟目录三种浏览语义；`circle:/...` 是展示层路径，操作落地时必须解析回真实 `library_id + path`。
- 库存页新增 / 保留能力：
  - Windows 式框选：原生 Pointer Events + RAF。
  - 表格行拖拽移动：拖动幽灵、可投放 / 阻止状态。
  - 面包屑路径栏：支持折叠、popover、拖拽投放。
  - 批量选择、批量删除、批量移动、API 重命名、当前页 / 当前目录动作作用域。
- 本地移动必须先走 `/api/library/browser/move-preview` 做真实后端预检；不要只靠前端当前层同名判断。
- API 重命名支持批量计划 / 批量行状态，前端要避免重复提交同一批次；后端要保持计划生成和执行分离。
- 同名文件夹是合并语义，不是冲突；只有文件撞名、文件夹/文件类型不一致、目标在源目录内部等情况才进入冲突选择。
- 目录合并后库存索引不能只做 move fast-path：源目录删除、目标目录 replace subtree、未删除源目录 replace subtree 都要按结果补 self_mutation。
- 不要退回 Element Plus 默认表格。
- 改行选择逻辑时要同步键盘、右键菜单、移动弹窗、移动后刷新、搜索定位行状态。
- `LibraryMoveDialog.vue` 负责库存内移动导航；初始路径必须能展开到目标路径。

### 6.4 库存社团聚合视图

- 核心文件：`backend/app/core/library_circle_aggregation_service.py`、`frontend/src/components/library/FolderContentsDialog.vue`、`frontend/src/views/Library.vue`。
- 社团聚合只读 `library_index_entries` 和本地元数据表，不能触发 `os.walk`、远程 FileStation 递归或慢 fallback。
- 聚合结果必须保留真实 `library_id`、`relative_path`、`path`；虚拟路径只用于浏览展示，删除 / 移动 / 重命名 / 内容弹窗要回到真实路径。
- 同一个 RJ 多库 / 多路径收录时是聚合位置列表，不要简单去重到单路径。
- 社团识别范围要收紧在库存索引的真实作品路径上；不要拿顶层分类目录或不含 RJ 的父目录误判社团。

### 6.5 社团补全

- `CircleCompletion.vue` 使用 `CircleWorksViewport.vue` 渲染作品列表。
- `CircleWorksViewport.vue` 依赖 `@tanstack/vue-virtual`，卡片 / 列表模式共用分页和虚拟行。
- 社团补全读路径已拆成 `state`、`summary`、`page`、`work-codes`、`recent` 缓存：L1 进程内 `TTLCache` + L2 Redis JSON + PostgreSQL source，写路径必须调用 `invalidate_completion_view_cache()` 做版本失效。
- 切社团默认只请求 `/works`，响应里的 `summary` 直接供首屏统计；不要重新并发冷读 `/summary` + `/works`。
- `/works` 返回封面优先走 `/api/circle-completion/cover/{RJ}.jpg` / `{RJ}_sam.jpg` 本地缓存；缺失时后端按 DLsite CDN 推导并落 `data/img/`，前端仍保留 `WorkCard` fallback。
- 小屏宽度下使用 plain render，避免移动端虚拟布局高度误差。
- 翻页时保留旧页内容叠加轻量更新态；server paging 下 `CircleWorksViewport` 不要每次强制 `measure()`，只在布局 / 列数 / 行高变化时重测。
- 作品卡片 / 行继续复用 `WorkCard.vue`、`WorkListRow.vue`，保留 CV、关联链、封面错误降级和状态 flash。
- 已满足 tab 有独立工具栏 / 筛选 / 搜索定位逻辑，页头 RJ 搜索要按 owned 状态跳到“已满足作品”或“缺失作品”对应页并高亮，不要固定跳缺失页。
- 批量下载入口优先使用 `asmr_available_rjcode`，不要默认拿 `display_rjcode`。
- DLsite 关联链统一复用 `dlsite_service.get_linked_works()`。
- 本地收录态优先走库存索引 / 社团聚合数据，不要靠慢速全库路径扫描。

### 6.5.1 DLsite 特典探测

- 核心文件：`backend/app/core/dlsite_bonus_probe_service.py`、`docs/dlsite-bonus-probe.md`。
- 特典探测只用 DLsite 官方数据源；作品级结论只有 `has_bonus` / `no_bonus`，对应 `dlsite_bonus_original_probe_states.status`。
- 发售日完成口径是同 maker / 同社团 / 同发售日所有原作 RJ 都已有作品级结论；`500RJ` 只是 product/info 合并请求单位，不是完成依据。
- 查询前先查 `dlsite_bonus_probe_hit_index` 和 `dlsite_bonus_probe_cache`；本地隐藏特典线索命中后要写入当前社团作品，但仍要补完同发售日未结论原作。
- 日期调度固定 6 worker；待处理发售日按最小原作 RJ 升序，worker 拿到一个发售日后必须完整处理完再领下一个。
- 选中作品触发时，前端按发售日传 selected 原作 RJ；后端以 selected RJ 为锚点构造邻近候选，不能被同日其它公开作品超大 RJ 跨度拖成整日全范围。
- 同一发售日并发命中时必须按 RJ 数字区间切稳定 range shard，并通过 active lease 排除正在查询的 RJ，避免重复请求或漏扫相邻区间。
- `403`、`429`、风控页、HTTP 异常、日期页解析异常、批量探测异常都不能写 `no_bonus`。
- 扫描范围超过预算时可以沉淀已命中的隐藏特典，但不能把未覆盖原作标 `no_bonus`；该发售日记 `incomplete` 并在汇总暴露 `incomplete_count`。
- 只有候选 RJ 全部得到稳定 `ok` 或 `missing` 后，才允许给剩余原作写 `no_bonus`。
- 模糊发售日（如 `上旬` / `中旬` / `下旬`）进入特典探测前要用 canonical 原作 product/info 补精确 `YYYY-MM-DD` 并写回 `WorkMetadata.release_date`，同时清理社团补全 metadata / view 缓存。
- Redis dirty buffer 使用 `bonus-probe:cache:stream`，由 `dlsite_bonus_probe_service` 启停 flush worker；关停时要尽量 flush 回 PostgreSQL。

### 6.6 上传 / 下载工作台

- 本地上传任务、服务端上传预览、下载任务面板是一条链，不要只改其中一端。
- `ServerUploadPreviewDialog.vue` 已做预览树虚拟化、类型 chip、横向拖动 chip rail、分组选中统计。
- 上传任务速度：
  - `library_manager.py` 上传回调里做 0.75s 采样和指数平滑。
  - 完成后 `speed_bytes_per_sec` 置 0，保留 `backend_speed_bytes_per_sec` 给历史诊断。
- `task_engine.py` 支持 revive superseded local upload task：
  - 清除 superseded / hidden 标记。
  - 重置 `upload_files`、`uploaded_files`、`upload_runtime`、进度日志。
  - 重新入队时避免重复入队。
- 上传任务行按 `source_dir` 匹配，避免多源上传时进度串行写错文件。
- `DownloadTaskWorkbenchDialog.vue` 和 `UploadTaskWorkbenchDialog.vue` 的字段语义不要乱改：`download_files`、`upload_files`、`uploaded_files`、`progress_log`、`failure_reason`、`final_output_path`、`download_root`。
- 本地复制入库、群晖上传都不能退回整文件 `read()`；必须流式分块并保留进度。
- 后台工作台小窗统一走 `BackgroundWorkbenchHost.vue` / `useBackgroundWorkbenchManager.js`，不要给每个页面另写浮窗状态机。

### 6.7 HTTP 外链下载

- `http_download_service.py` 是底层 aria2 RPC 下载，按平台拆解析：`http` / `gofile` / `transferit` / `onedrive` / `google_drive` / `pikpak`，平台标签走 `HTTP_DOWNLOAD_PLATFORM_LABELS`，不要散落硬编码。
- 下载预览树支持文件级选择；`gofile` / `google_drive` / `transferit` / `pikpak` 要把选择过滤传回后端，百度网盘要保留选中的 `preview_files` / `share_files`。
- 预览树的选择 key 以文件行而不是分享项为粒度；修改结构时要同步缓存版本，避免旧缓存把选择态串错。
- `validate_url` 默认拒绝内网 / 本机 / link-local / metadata 地址，含 DNS rebinding 校验；只有 `allow_private_network` 显式开启才放行。
- 配置在 `HttpDownloaderConfig`（`settings.py`），密码 / token / refresh_token 等敏感字段 `/api/config` 必须脱敏为 `********`，保存时回填磁盘真实值，不能把 `********` 写进配置。
- PikPak 多账号在 `pikpak_accounts` 维护，状态有缓存表 `PikPakStatusCache`；token 失效要能用账号密码自动重登并回写。
- 任务态语义要和任务中心 / 仪表盘对齐：`completed` / `partial_failed`（部分成功）/ 取消态，失败项支持自动重试和手动重试。
- 前端入口：`HttpDownloadSettingsPanel.vue`（设置）、下载工作台与 ASMR 同步页；Google Drive OAuth 走 `google_drive_oauth.py`。
- Transfer.it 支持断流后断点续传，速度统计不能把历史已下载字节当当前瞬时速度。

### 6.8 百度网盘

- 核心文件：`backend/app/core/baidu_netdisk_service.py`、`frontend/src/components/settings/BaiduNetdiskSettingsPanel.vue`、`frontend/src/components/asmr/BaiduNetdiskPanel.vue`。
- 入口挂在 ASMR 同步页的百度 tab，`/baidu-netdisk` 只是重定向到 `/asmr-sync?tab=baidu`。
- Docker / Linux 依赖 `BaiduPCS-Go`；本地 Windows 可走配置里的 `baidupcs_go_path`。不要改成直接浏览器下载。
- 账号绑定支持官方登录窗口、扫码登录、账号密码同步、手动 cookie；这些会互相关闭会话，改状态时要同步关闭旧二维码 / 官方登录 session。
- 百度分享解析要保留分享级和文件级选择、提取码、每文件自定义文件名 / 解压密码；`sanitize_baidu_netdisk_item()` 负责对外剥离 cookie、bdstoken、randsk、share token、提取码等敏感字段。
- 预览缓存的 raw key 不能暴露给前端；任务提交时只传必要的 sanitized 选择数据。

## 7. 业务链路红线

### 7.1 任务中心

- 新任务不能只做到后端能跑，还要补任务中心展示语义、来源页 / 来源动作、历史归属、错误 / 重试 / 等待态。
- 任务上下文字段优先补全：`task_domain`、`task_kind`、`session_id`、`source_page`、`source_action`、`source_label`、`business_key`。
- 状态除了 `pending / processing / completed / failed`，还有 `paused / waiting_manual / waiting_retry`。
- RJ 字幕任务有自己的进度日志、下载明细、人工匹配等待态，不要硬塞回通用粗粒度进度条。
- 新 API 默认走 `/api/task-center/*`；`/api/tasks*` 是兼容层，只给少数历史入口用，新功能不要接回旧任务列表。
- 任务中心实时刷新有两条线：旧 `/api/task-center/stream` 和统一 `/api/events/stream`；新增前端刷新优先用 `useRealtimeEvents.js`，并保留 `kikoerumanager:task-center:changed` 兼容事件。
- Redis 可用时实时事件会双写 Redis Stream：统一事件 `events:stream`、任务中心 `task-center:stream`；SSE 读 Redis 失败只能降级，不要阻断主业务。
- 任务运行态快照在 Redis `task:runtime:{task_id}`，任务中心 / routes 读路径会 overlay 活跃运行态；新增长任务运行态字段时要同步 `redis_service.py` 的 runtime metadata 白名单。
- `TaskEngine` 会双写 `task_center_items` 物化快照，并用指纹和最小写入间隔限流进度更新；不要在每个 progress tick 同步写库。
- DLsite 特典探测任务类型是 `circle_completion_bonus_probe`，进度字段包括 `bonus_probe_meta`、`bonus_probe_summary`、`bonus_probe_result`，任务中心文案不能当普通下载 / 导入任务处理。
- `KIKOERUMANAGER_TASK_CENTER_MATERIALIZED_SUMMARY=1` 会让 summary 读路径优先读物化表；上线前可用 `/api/task-center/materialized/backfill`、`/api/task-center/materialized/list`、`/api/task-center/diagnose` 做双写和 diff。
- 物化表搜索字段 `searchable_text` 依赖 trigram 索引；新增可搜索字段时同步更新物化构造和数据库索引/维护逻辑。

### 7.2 操作历史

- 操作历史是树形聚合，不是平铺流水。
- 改任务流时必须考虑记录是否落库、同一业务是否被拆成噪音日志、子任务是否挂到父记录下。
- `subtitle_import` 只有真正执行导入的 `archive_import / folder_import` 才能挂到“解压入库”树下。
- `pending_execute` 只是预检 / 进入工作台，不进历史树和顶层列表。
- `waiting + task_finished` 文案统一展示为 `等待处理`。
- 手动字幕配对只有真正落盘才写完成日志。
- 社团补全特典探测操作历史使用 `source_action=bonus_probe`，邮件新作触发使用 `new_release_bonus_probe`；lite/detail/children 路径都要保留 `bonus_probe_status`、命中 RJ、date results。
- `/api/activity-logs` 的 row cache 设计前提是 append-only；聚合函数禁止原地修改缓存 dict 的深层内容。
- `activity_log_rollups` 只维护 batch / session / task 三类轻量计数和最新状态，不替代 `activity_log_aggregator` 的深度树形输出。
- 写入操作历史时要让 `ActivityLogWriter` 同步更新 rollup；历史数据用 `/api/activity-logs/rollups/backfill` 回填，用 `/api/activity-logs/rollups/diff` 校验。
- `/api/activity-logs/compact` 会压缩旧 detail 并标 `__compacted=True`，不是删除历史；前端应展示归档态而不是让记录消失。
- ActivityHistory 当前有 lite / detail / children / rollup 多条读路径；改列表性能时先看 `activity_log_lite.py`、`activity_log_aggregator/`、`activity_log_rollup_service.py`，不要直接加全表 JSON 扫描。

### 7.3 问题作品 / 冲突处理

- 顶层动作只暴露 `KEEP_NEW`、`SKIP`、`MERGE`；`KEEP_OLD` 只做兼容别名。
- 解压失败 / 处理失败必须落问题作品，不要只停在任务失败。
- 重复作品、处理中、需要人工判断必须落 `waiting_manual`，不要写成 success。
- `KEEP_NEW` 是后台任务链，不是同步直接改库。
- `_resolve_kikoeru_server_path` 必须走 `LibraryManager.find_rj_in_libraries`，不要回退到多库串行 `list_files + global_search_files`。
- `/api/conflicts` 三阶段耗时日志前缀 `[/api/conflicts]` 要保留。
- resolve 成功必须调用 `mark_task_conflict_resolved_activity_log(task_id, action)`，否则历史会一直卡“等待处理”。

### 7.4 RJ 字幕工作台

- 主入口在库存页，不在设置页。
- 流程分阶段：扫描 RJ 目录 -> 检查已有字幕 -> 搜来源 -> 下载原始字幕 -> 清洗 -> 自动匹配 -> 人工筛选 / 手动配对 -> 写入 `subtitles/`。
- 抓取阶段和最终落盘阶段必须分开。
- 已有字幕目录要留在工作台上下文里，不能简单当失败项。
- `awaiting_manual_match` 前端上算进入“筛选与配对”阶段。
- “重新执行爬取字幕”允许对等待态任务生效，不要按普通 pending 禁用。

### 7.5 删除过滤

- 删除过滤是预审制：发起预审 -> 后台扫描 / 预览 -> 用户审阅 -> 确认后删除。
- 删除成功后直接更新当前树和数量，不要删完强行重跑整轮预审。
- 相关记录必须进入操作审计。
- 目录右键删除过滤、跨库预审、执行删除都要走后端真实库存语义；社团聚合路径必须先解析真实位置。
- 大候选列表前端要保持虚拟化 / 稳定高度，避免预审滚动空白和抖动。

### 7.6 ASMR 同步

- ASMR 同步下载链路仍在使用，不是废代码。
- 改 RJ、任务系统、下载上传链路时，不要误伤 `routes.py`、`task_engine.py`、`asmr_resource_service.py` 里的 ASMR 预览、下载、字幕同步、重命名、分类、移动到 `Finished` 流程。

### 7.7 密码工作台

- 入口：`frontend/src/views/PasswordVault.vue`。
- 后端接口：`routes.py` 的 `/api/passwords/*`。
- 创建密码接口已内置去重合并：
  - 有 `rjcode + filename` 时，同 RJ + 同文件名命中则更新。
  - 通用密码按 `password` 精确匹配合并。
  - 合并命中响应带 `merged: true`。
- 排序下拉必须走 `AppDropdown`。

### 7.8 通知模板 / 邮件块编辑器

- 邮件模板已升级 Block Editor，旧 HTML 模板仍保留。
- 新块类型必须同时补：
  - 前端 `blockTypes.js` 的 `defaultProps / propSchema`。
  - 前端 `blockMiniRenderers.js` 预览。
  - 后端 `block_renderers/__init__.py` 真渲染。
- 变量统一走 `variable_registry.py`，不要散落 `payload[xxx]` 直读。
- 富文本变量 pill 必须保留 `data-var`。
- HTML 清洗统一走 `html_sanitizer.py` 的 `sanitize_html()`。
- 预览接口要 debounce + abort 上一次请求 + requestId 校验。
- `task_metadata` 不能整段塞进邮件 payload，必须走白名单。

### 7.9 安全网关

- 后端入口：`backend/app/core/security_gate_service.py`、`routes.py` 的 `security_gate_middleware` 和 `/api/security-gate/*`。
- 前端入口：`frontend/src/views/VerifyGate.vue`、`BlockedGate.vue`、`SecurityGateSettingsPanel.vue`，路由守卫在 `frontend/src/router/index.js`。
- 门禁页面自身、静态资源、健康检查、SSE 连接要按 middleware 允许/验证规则处理；不要让未认证用户绕过 API，也不要把 `/verify` / `/blocked` 卡死在重定向循环。
- 黑名单访问、失败次数、解除黑名单和邮件提醒都有日志/节流表；改验证逻辑要同步 `SecurityGateAuthLog`、`SecurityGateBlacklist`、`SecurityGateEmailThrottle`。
- TOTP 绑定二维码只在确认新验证码后替换旧绑定；不要生成二维码就立即让旧验证器失效。

## 8. 群晖 / 库存索引

- 群晖通信相关错误统一抛 `SynologyError`，不要裸抛 `RuntimeError`。
- 远程搜索优先走群晖原生接口，不要偷偷退回本地递归。
- 根目录 `/` 搜索按 share 拆分汇总。
- RJ 字幕远程扫描递归时跳过 `subtitles`。
- 判断远程路径是否在库存范围内时，复用 `root / browse_root` 校验。
- 常见群晖错误码：`119`、`121`、`401`、`408`。

### 库存搜索索引

- 入口：`backend/app/core/library_index/`。
- DB 表：`library_index_entries`、`library_index_status`。
- `LibraryManager.find_rj_in_libraries`、`list_files` 搜索、`get_library_size`、社团聚合视图已自动接索引；业务层直接调 `LibraryManager` 或聚合服务，不要自己扫库。
- 写操作必须补 self_mutation：删除、重命名、批量删除、移动、解压落地、字幕落盘。
- 新部署 / 新加库存通常由用户手动触发重建；启动时只能为“远程库无可用快照且明确需要初始化”的场景触发补建，不要每次启动无脑扫远程库。
- `has_usable_snapshot` 为真时，`syncing` 期间读路径应继续用旧快照；无快照时才走受控初始化 / 降级链路。
- syncing 时 `total_entries` 是已扫描数；ready 后才是总数。
- 远程 Synology 扫描用 `SYNO.FileStation.Search`，降级遍历必须限流，不能把 `walk()` 当主路径。
- 前端 `LibraryIndexBadge.vue` 轮询 1.2s；后端每 0.5s 状态上报，别单边改频率。

### 数据库维护 / 全文搜索

- 设置页维护入口：`MaintenanceSettingsPanel.vue` + `DatabaseShrinkCard.vue`；全文搜索入口：`FtsSettingsPanel.vue`。
- `/api/database/maintenance/shrink` 的实际流程是压缩旧操作记录 detail -> `VACUUM ANALYZE` -> 重建 pg_trgm 索引；它不会删除操作历史。
- 维护状态会广播 `maintenance.database_shrink.changed` 到 `/api/events/stream`；前端有 30s fallback poll，不要另起短轮询打爆后端。
- pg_trgm 重建覆盖操作历史、库存索引、任务中心物化表、已处理归档；新增 trigram 索引要同步 `database_maintenance_service.py` 的 `_TRIGRAM_INDEXES` 和 `models/database.py` 的 index specs。
- 性能诊断读取 `pg_stat_statements` 时要容忍扩展不可查；前端只能显示降级提示，不要把诊断失败当维护失败。

## 9. 桌面与发布

- 桌面入口：`desktop_app.py`。
- 当前稳定方案是 `pystray` 原生托盘菜单；没明确要求不要改成自绘菜单。
- exe 名统一 `KikoeruManager.exe`。
- 图标必须来自仓库资源，不要依赖外部绝对路径。
- 发布前先 `git status`，确认没有 `.env`、本地数据库、用户配置、缓存目录。
- tag 用 annotated tag，semver 格式。

## 10. 最低验证

- 改前端：至少在 `frontend` 跑 `npm run build`。
- 改前端依赖：再跑 `npm ls <新增包> --depth=0`，并确认 `package.json`、`package-lock.json`、`pnpm-lock.yaml` 都同步。
- 改后端核心：至少跑 `py_compile` 覆盖相关文件。
- 改解压 / 文件识别：跑 `backend/tests/test_extract_service.py` 中对应用例；涉及真实用户样本时，用样本实际验证。
- 改库存索引 / `library_manager.py` 写操作 / `find_rj_in_libraries`：跑 `tests/test_library_index_*.py tests/test_library_manager_index_integration.py -q`。
- 改库存社团聚合：跑 `backend/tests/test_library_circle_aggregation*.py`，涉及前端浏览再跑 `npm run build`。
- 改社团补全读模型 / 分页 / 封面缓存：跑 `backend/tests/test_circle_completion_paged_view.py backend/tests/test_circle_completion_bonus_grouping.py -q`，前端改动再跑 `npm run build`。
- 改 DLsite 特典探测：跑 `backend/tests/test_dlsite_bonus_probe_service.py backend/tests/test_circle_completion_paged_view.py -q`，涉及操作历史 / 通知再补 `backend/tests/test_activity_log_*.py backend/tests/test_task_notification_service.py -q`。
- 改任务中心 / 实时事件：跑 `backend/tests/test_task_center_service.py backend/tests/test_routes_maintenance_config.py -q`，前端改动再跑 `npm run build`。
- 改 Redis 配置 / 运行态 / dirty buffer：跑 `backend/tests/test_redis_config.py backend/tests/test_routes_maintenance_config.py backend/tests/test_database_compat_migrations.py -q`，并用 `scripts/check-redis.ps1` 做本机连通性冒烟。
- 改操作历史 / rollup / compact：跑 `backend/tests/test_activity_log_*.py backend/tests/test_routes_maintenance_config.py -q`。
- 改 HTTP / 百度网盘下载：跑 `backend/tests/test_http_download_service.py backend/tests/test_baidu_netdisk*.py backend/tests/test_task_notification_service.py -q`，前端面板改动再跑 `npm run build`。
- 改通知模板：后端 `py_compile` + 前端 `npm run build`。
- 改安全网关：跑相关 `routes.py` / `security_gate_service.py` `py_compile`，并手动验证 `/verify`、`/blocked`、正常业务页跳转。
- 改数据库维护 / FTS：跑 `backend/tests/test_routes_maintenance_config.py backend/tests/test_activity_log_rollup_service.py -q`，前端设置页改动再跑 `npm run build`。
- 改发布流程：检查 `.github/workflows/ghcr.yml` 和 semver tag。

## 11. 常用排查路径

- “改配置文件”：默认看 `backend/config/config.yaml`。
- “Docker 里解压识别不了”：先看 `Dockerfile` / `backend/Dockerfile` 是否有官方 `7zz`、`unar`、`lsar`，再看 `archive_detection.py`、`file_processor.py`、`extract_service.py`。
- “伪装 ZIP / mp4 改 zip 仍识别不了”：确认 `detect_embedded_zip_offset()` 是否能返回 offset，确认 temp 路径可写且空间足够。
- “库存页交互不对”：先看 `Library.vue`、`LibraryMoveDialog.vue`、`frontend/src/api/index.js`。
- “库存社团聚合 / circle:/ 路径不对”：先看 `library_circle_aggregation_service.py`、`FolderContentsDialog.vue`、`Library.vue`，确认虚拟路径是否解析回真实库路径。
- “社团列表卡顿 / 空白”：先看 `CircleWorksViewport.vue` 和 `@tanstack/vue-virtual` 是否安装。
- “社团补全切页 / 已满足 / 封面慢”：先看 `circle_completion_service.py` 的 state/page/work-codes 缓存、`circle_image_cache_service.py`、`CircleCompletion.vue`、`CircleWorksViewport.vue`。
- “DLsite 特典探测漏命中 / no_bonus 异常”：先看 `dlsite_bonus_probe_service.py`、`docs/dlsite-bonus-probe.md`、`dlsite_bonus_probe_cache`、`dlsite_bonus_probe_hit_index`、`dlsite_bonus_original_probe_states`。
- “Redis 不可用 / 任务运行态丢失 / SSE 延迟”：先跑 `scripts/check-redis.ps1`，再看 `redis_service.py`、`routes.py` 的 startup / SSE 读流、`docker/entrypoint.sh` 是否启动内置 Redis。
- “上传预览 / 上传进度不对”：先看 `ServerUploadPreviewDialog.vue`、`UploadTaskWorkbenchDialog.vue`、`library_manager.py`、`task_engine.py`。
- “任务中心不刷新 / 状态串了”：先看 `task_engine.py` 的 event hook / 物化快照、`task_center_service.py`、`task_center_materialization_service.py`、`useRealtimeEvents.js`。
- “操作历史 / 历史记录不对”：先看 `activity_log_service.py`、`activity_log_writer.py`、`activity_log_aggregator/`、`activity_log_rollup_service.py`、`ActivityHistory.vue`。
- “数据库变大 / 搜索慢”：先看 `database_maintenance_service.py`、`DatabaseShrinkCard.vue`、`FtsSettingsPanel.vue`、`models/database.py` 的 pg_trgm index specs。
- “通知邮件 / 模板 / 变量不对”：先看 `notification_template_service.py`、`block_renderers/__init__.py`、`variable_registry.py`、`notification_helper.py`。
- “HTTP 外链 / PikPak / Google Drive / Gofile 下载不对”：先看 `http_download_service.py`、`google_drive_oauth.py`、`HttpDownloadSettingsPanel.vue`，确认 aria2 可用、代理和 token 有效。
- “百度网盘下载 / 登录态不对”：先看 `baidu_netdisk_service.py`、`BaiduNetdiskSettingsPanel.vue`、`BaiduNetdiskPanel.vue`，确认 `BaiduPCS-Go` 路径、cookie 脱敏回填和二维码 / 官方登录 session。
- “安全网关误跳转 / 黑名单不对”：先看 `security_gate_service.py`、`routes.py` middleware、`router/index.js`、`VerifyGate.vue`、`BlockedGate.vue`。
- “暗黑模式样式没生效 / 闪白”：先看 `useTheme.ts` 是否挂上 `html.dark` + `html.kikoerumanager-dark`，再看 `dark-mode.css` 是否补了对应选择器。
- “弹窗有蓝色聚焦框 / 移动端弹窗没全屏”：先看 `App.vue` 的弹窗去聚焦兜底和 `index.css` 的响应式 helper / `.mobile-full-dialog`。
- “按钮加载态闪烁 / 不复用”：统一换 `frontend/src/components/ui/stateful-button.vue`。
