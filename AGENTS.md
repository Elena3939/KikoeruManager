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

## 1. 项目基线

- 产品名统一为 `KikoeruManager`；技术命名统一小写 `kikoerumanager`。
- 不要把旧名 `Prekikoeru`、`KikoeruTool_Elena`、`kikoeruTool` 混回标题、exe、镜像、文档、环境变量、localStorage key、SSE 事件名。
- GitHub 目标仓库是 `Elena3939/KikoeruManager`。
- GHCR 镜像目标：`ghcr.io/elena3939/kikoerumanager`。
- Docker Hub 镜像目标：`elena39/kikoerumanager`。
- 当前产品是多工作台桌面化工具，不是传统后台管理系统。
- 高频业务：库存主工作台、RJ 字幕工作台、任务中心、操作历史、问题作品、社团补全、下载 / 上传工作台、通知模板。

## 2. 技术栈与依赖

### 后端

- 后端：`FastAPI` + SQLAlchemy + SQLite。
- 依赖清单：`backend/requirements.txt`。
- 解压依赖：运行环境必须有官方 `7zz 24.08+`，并保留 `unar` / `lsar`。
- 不要回退到旧 `p7zip-full`。Dockerfile 会显式 purge p7zip，并把官方 `7zz` 链接到 `/usr/local/bin/7zz` 和 `/usr/local/bin/7z`。
- 新增的伪装 ZIP 探测只用 Python 标准库 `zipfile` / `os`，不用加 requirements。

### 前端

- 前端：`Vue 3 + Tailwind CSS + Radix Vue / Reka UI + Headless UI + VueUse + TanStack Table / AG Grid + lucide-vue-next`。
- 包清单以 `frontend/package.json` + `frontend/package-lock.json` 为 Docker 构建基准；根 `Dockerfile` 使用 `npm ci`。
- `frontend/pnpm-lock.yaml` 也要同步维护，避免本地 pnpm 用户装包失败。
- 当前直接依赖必须保留：
  - `@tanstack/vue-table`：库存页文件表格模型。
  - `@tanstack/vue-virtual`：社团作品虚拟滚动视口。
  - `@tiptap/core`：邮件 Block Editor 自定义扩展直接 import。
  - `lucide-vue-next`：全站图标唯一来源。
  - `@lottiefiles/dotlottie-vue` / `lottie-web`：动效。
- Vite 项目体积较大，`frontend/package.json` 的 `dev/build/preview` 和根 `Dockerfile` 都使用 `--max-old-space-size=4096`，不要降回 2048。

### Docker / 环境

- 根 `Dockerfile` 是完整前后端镜像；`backend/Dockerfile` 是后端镜像。
- 两个 Dockerfile 都必须保留官方 `7zz 24.08`、`unar`、`lsar`、SQLite FTS5 检查。
- 伪装 ZIP 解压会在 `storage.temp_path` 下创建 `kikoerumanager_embedded_zip_*.zip` 临时视图。Docker 部署时这个 temp 路径要挂到有足够空间的卷，不要放很小的容器层。
- temp 视图成功、失败、取消都必须清理；原始文件路径不能被临时视图覆盖。

## 3. 关键入口

### 后端入口

- API 总入口：`backend/app/api/routes.py`
- 配置模型：`backend/app/config/settings.py`
- 数据库模型：`backend/app/models/database.py`
- 任务引擎：`backend/app/core/task_engine.py`
- 任务中心：`backend/app/core/task_center_service.py`
- 操作审计：`backend/app/core/activity_log_service.py`、`backend/app/core/activity_log_writer.py`、`backend/app/core/activity_log_aggregator/`
- 库存管理：`backend/app/core/library_manager.py`
- 库存索引：`backend/app/core/library_index/`
- 解压：`backend/app/core/extract_service.py`
- 压缩包识别：`backend/app/core/file_processor.py`、`backend/app/core/archive_detection.py`
- RJ 字幕：`backend/app/core/rj_subtitle_service.py`、`backend/app/core/linked_subtitle_import_service.py`
- ASMR 下载 / 上传：`backend/app/core/asmr_resource_service.py`
- 社团补全：`backend/app/core/circle_completion_service.py`、`backend/app/core/kikoeru_duplicate_service.py`
- 冲突处理：`backend/app/core/conflict_resolution_service.py`
- 通知：`backend/app/core/notification_template_service.py`、`notification_helper.py`、`task_notification_service.py`、`variable_registry.py`、`block_renderers/__init__.py`、`html_sanitizer.py`

### 前端入口

- 主布局：`frontend/src/App.vue`
- 路由：`frontend/src/router/index.js`
- API 封装：`frontend/src/api/index.js`
- 库存页：`frontend/src/views/Library.vue`
- 任务中心：`frontend/src/views/Tasks.vue`
- 操作历史：`frontend/src/views/ActivityHistory.vue`
- 问题作品：`frontend/src/views/Conflicts.vue`
- 社团补全：`frontend/src/views/CircleCompletion.vue`
- ASMR 同步：`frontend/src/views/ASMRSync.vue`
- 设置页：`frontend/src/views/Settings.vue`

### 前端基座组件

- 下载任务工作台：`frontend/src/components/download/DownloadTaskWorkbenchDialog.vue`
- 上传任务工作台：`frontend/src/components/upload/UploadTaskWorkbenchDialog.vue`
- 本地 / 服务端上传预览：`frontend/src/components/circle/CircleLocalUploadDialog.vue`、`frontend/src/components/common/ServerUploadPreviewDialog.vue`
- 社团作品虚拟视口：`frontend/src/components/circle/CircleWorksViewport.vue`
- 社团作品卡片 / 行：`frontend/src/components/circle/WorkCard.vue`、`frontend/src/components/circle/WorkListRow.vue`
- 库存移动弹窗：`frontend/src/components/library/LibraryMoveDialog.vue`
- 库存索引徽章：`frontend/src/components/library/LibraryIndexBadge.vue`
- 统一筛选下拉：`frontend/src/components/common/AppDropdown.vue`
- 系统弹窗：`frontend/src/components/system/SystemPromptDialog.vue`、`SystemPromptHost.vue`、`frontend/src/composables/useSystemPrompt.js`
- 通知中心：`frontend/src/components/system/NotificationBell.vue`、`frontend/src/composables/useNotifications.js`
- Lottie 通用组件：`AppLoadingAnimation.vue`、`AppLottieIcon.vue`、`AppLottieSwitch.vue`、`AppLottieProgressBar.vue`

## 4. 配置与敏感数据

- 用户说“改配置文件”且没有明确说运行态时，默认改仓库模板 `backend/config/config.yaml`。
- 桌面 / 开发默认运行配置是 `data/config/config.yaml`；Docker 是 `/app/config/config.yaml`。
- 只有设置 `CONFIG_PATH` 时才读环境变量指定文件。
- 不要提交真实密码、Token、代理、私服地址、群晖账号、本地数据库、缓存、`.env`。
- 默认运行态 / 敏感产物：`.env`、`data/`、`backend/data/`、本地数据库、缓存目录、`.codex-backups/`。
- `/api/config` 返回 SMTP 密码必须脱敏为 `********`；保存时前端传回 `********` 或省略 `password`，后端必须保留真实密码。

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

### 6.2 分卷伪装后缀

- 核心判定走 `_is_disguised_volume_suffix`。
- 含非 ASCII 字符或已知伪装词如 `deleted` / `fake` / `junk` 可判定伪装。
- 绝对不要加 `del` / `rm` 等短前缀，避免误伤 `delta01` 这类合法英文。
- 保持 `_detect_disguised_set_with_clean_target` 对 `_CLEAN_ARCHIVE_EXTENSIONS` 的严格白名单限制。

### 6.3 库存主工作台

- `Library.vue` 是主工作台，不是普通列表页。
- 当前文件列表已切到 `@tanstack/vue-table` 管理 row model，配合自定义 DOM 表格样式。
- 库存页新增 / 保留能力：
  - Windows 式框选：原生 Pointer Events + RAF。
  - 表格行拖拽移动：拖动幽灵、可投放 / 阻止状态。
  - 面包屑路径栏：支持折叠、popover、拖拽投放。
  - 批量选择、批量删除、批量移动、API 重命名、当前页 / 当前目录动作作用域。
- 不要退回 Element Plus 默认表格。
- 改行选择逻辑时要同步键盘、右键菜单、移动弹窗、移动后刷新、搜索定位行状态。
- `LibraryMoveDialog.vue` 负责库存内移动导航；初始路径必须能展开到目标路径。

### 6.4 社团补全

- `CircleCompletion.vue` 使用 `CircleWorksViewport.vue` 渲染作品列表。
- `CircleWorksViewport.vue` 依赖 `@tanstack/vue-virtual`，卡片 / 列表模式共用分页和虚拟行。
- 小屏宽度下使用 plain render，避免移动端虚拟布局高度误差。
- 作品卡片 / 行继续复用 `WorkCard.vue`、`WorkListRow.vue`，保留 CV、关联链、封面错误降级和状态 flash。
- 批量下载入口优先使用 `asmr_available_rjcode`，不要默认拿 `display_rjcode`。
- DLsite 关联链统一复用 `dlsite_service.get_linked_works()`。

### 6.5 上传 / 下载工作台

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

## 7. 业务链路红线

### 7.1 任务中心

- 新任务不能只做到后端能跑，还要补任务中心展示语义、来源页 / 来源动作、历史归属、错误 / 重试 / 等待态。
- 任务上下文字段优先补全：`task_domain`、`task_kind`、`session_id`、`source_page`、`source_action`、`source_label`、`business_key`。
- 状态除了 `pending / processing / completed / failed`，还有 `paused / waiting_manual / waiting_retry`。
- RJ 字幕任务有自己的进度日志、下载明细、人工匹配等待态，不要硬塞回通用粗粒度进度条。

### 7.2 操作历史

- 操作历史是树形聚合，不是平铺流水。
- 改任务流时必须考虑记录是否落库、同一业务是否被拆成噪音日志、子任务是否挂到父记录下。
- `subtitle_import` 只有真正执行导入的 `archive_import / folder_import` 才能挂到“解压入库”树下。
- `pending_execute` 只是预检 / 进入工作台，不进历史树和顶层列表。
- `waiting + task_finished` 文案统一展示为 `等待处理`。
- 手动字幕配对只有真正落盘才写完成日志。
- `/api/activity-logs` 的 row cache 设计前提是 append-only；聚合函数禁止原地修改缓存 dict 的深层内容。

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
- `LibraryManager.find_rj_in_libraries`、`list_files` 搜索、`get_library_size` 已自动接索引；业务层直接调 `LibraryManager`。
- 写操作必须补 self_mutation：删除、重命名、批量删除、移动、解压落地、字幕落盘。
- 新部署 / 新加库存必须用户手动触发重建，不要启动时自动扫远程库。
- syncing 时 `total_entries` 是已扫描数；ready 后才是总数。
- 前端 `LibraryIndexBadge.vue` 轮询 1.2s；后端每 0.5s 状态上报，别单边改频率。

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
- 改通知模板：后端 `py_compile` + 前端 `npm run build`。
- 改发布流程：检查 `.github/workflows/ghcr.yml` 和 semver tag。

## 11. 常用排查路径

- “改配置文件”：默认看 `backend/config/config.yaml`。
- “Docker 里解压识别不了”：先看 `Dockerfile` / `backend/Dockerfile` 是否有官方 `7zz`、`unar`、`lsar`，再看 `archive_detection.py`、`file_processor.py`、`extract_service.py`。
- “伪装 ZIP / mp4 改 zip 仍识别不了”：确认 `detect_embedded_zip_offset()` 是否能返回 offset，确认 temp 路径可写且空间足够。
- “库存页交互不对”：先看 `Library.vue`、`LibraryMoveDialog.vue`、`frontend/src/api/index.js`。
- “社团列表卡顿 / 空白”：先看 `CircleWorksViewport.vue` 和 `@tanstack/vue-virtual` 是否安装。
- “上传预览 / 上传进度不对”：先看 `ServerUploadPreviewDialog.vue`、`UploadTaskWorkbenchDialog.vue`、`library_manager.py`、`task_engine.py`。
- “任务中心 / 历史记录不对”：先看 `task_center_service.py`、`activity_log_service.py`、`Tasks.vue`、`ActivityHistory.vue`。
- “通知邮件 / 模板 / 变量不对”：先看 `notification_template_service.py`、`block_renderers/__init__.py`、`variable_registry.py`、`notification_helper.py`。
