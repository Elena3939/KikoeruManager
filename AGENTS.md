# AGENTS.md

给后续 AI / 自动化代理的接手说明。目标是少踩坑、少回退、少串状态；这里不写项目百科，只保留仍然会影响改动判断的规则。

## 1. 项目基线

- 项目名统一用 `KikoeruManager`（PascalCase 显示 / 标题 / exe 名 / 品牌）；技术场景（npm package name、Docker image、container name、SMTP 默认发件人 `from_name`、环境变量前缀的小写形式、localStorage key 命名空间、SSE 自定义事件名前缀、临时文件 magic prefix）统一用 `kikoerumanager`（全小写）。
- 不要把 `Prekikoeru` / `KikoeruTool_Elena` / `kikoeruTool` 这类旧名混回新文案、新标题、新打包产物。环境变量前缀统一为 `KIKOERUMANAGER_*`，自定义事件名 / localStorage key 用 `kikoerumanager.xxx` 或 `kikoerumanager:xxx`。
- GitHub 仓库目标名称是 `Elena3939/KikoeruManager`（仓库需用户在 GitHub 网页端 Settings → General 改名），GHCR image 跟随仓库名自动是 `ghcr.io/elena3939/kikoerumanager`，Docker Hub image 是 `elena39/kikoerumanager`。所有 README / 文档里都已按这个目标名称写，**不要**回退成旧的 `KikoeruTool_Elena` / `kikoerutool_elena`。
- 如果发现 GHCR build 失败 / `git push` 报 404，先确认用户是否已经在 GitHub 上完成仓库改名 + 是否已在本地 `git remote set-url origin https://github.com/Elena3939/KikoeruManager.git`。GitHub 改名后旧 URL 会自动 redirect，git remote 不必须立刻改但建议改。
- 技术栈：后端 `FastAPI`；前端 `Vue 3 + Vite + Element Plus + Tailwind CSS + lucide-vue-next`；桌面端 `pystray + PyInstaller`。
- 当前产品形态是多工作台桌面化产品，不是传统后台管理系统。
- 高频业务区：库存主工作台、RJ 字幕工作台、任务中心、操作历史、社团补全、下载 / 上传工作台。
- 发布 tag 只能用标准 semver：正确 `v1.2.3`，错误 `v1.02`、`1.2.3`。

## 2. 关键入口

### 后端

- API 总入口：`backend/app/api/routes.py`
- 配置模型：`backend/app/config/settings.py`
- 数据库模型：`backend/app/models/database.py`
- 任务引擎：`backend/app/core/task_engine.py`
- 任务中心：`backend/app/core/task_center_service.py`
- 操作审计：`backend/app/core/activity_log_service.py`、`backend/app/core/activity_log_writer.py`、`backend/app/core/activity_log_aggregator/`
- 库存管理：`backend/app/core/library_manager.py`
- RJ 字幕：`backend/app/core/rj_subtitle_service.py`、`backend/app/core/linked_subtitle_import_service.py`
- 社团补全：`backend/app/core/circle_completion_service.py`、`backend/app/core/kikoeru_duplicate_service.py`
- ASMR 下载 / 上传：`backend/app/core/asmr_resource_service.py`
- 冲突处理：`backend/app/core/conflict_resolution_service.py`
- 通知模板：`backend/app/core/notification_template_service.py`、`backend/app/core/notification_helper.py`、`backend/app/core/task_notification_service.py`、`backend/app/core/variable_registry.py`、`backend/app/core/block_renderers/__init__.py`、`backend/app/core/html_sanitizer.py`
- 邮件监听 / IMAP：`backend/app/core/email_watcher_service.py`（如有）以及 `routes.py` 内 `/api/notifications/*`、`/api/email-watcher/*` 接口
- 群晖错误体系：`backend/app/core/synology_*.py` 中的 `SynologyError`，群晖通信相关运行时错误统一走它，不再裸抛 `RuntimeError`
- 库存搜索索引：`backend/app/core/library_index/`（`service.py` 调度 / `local_scanner.py` / `remote_scanner.py` / `snapshot_store.py` SQLite 持久化 / `types.py` 数据类）、DB 表 `library_index_entries` + `library_index_status`（在 `models/database.py`）、API 聚合在 `routes.py` 的 `/api/library/index/*`

### 前端

- 主布局：`frontend/src/App.vue`
- 路由：`frontend/src/router/index.js`
- API 封装：`frontend/src/api/index.js`
- 库存页：`frontend/src/views/Library.vue`
- Dashboard：`frontend/src/views/Dashboard.vue`
- 任务中心：`frontend/src/views/Tasks.vue`
- 操作历史：`frontend/src/views/ActivityHistory.vue`
- 问题作品：`frontend/src/views/Conflicts.vue`
- 社团补全：`frontend/src/views/CircleCompletion.vue`
- ASMR 同步：`frontend/src/views/ASMRSync.vue`
- 设置页：`frontend/src/views/Settings.vue`

### 前端基座组件

- 下载任务工作台：`frontend/src/components/download/DownloadTaskWorkbenchDialog.vue`
- 上传任务工作台：`frontend/src/components/upload/UploadTaskWorkbenchDialog.vue`
- 社团下载预览：`frontend/src/components/circle/CircleDownloadPreviewDialog.vue`
- 社团作品卡片 / 行：`frontend/src/components/circle/WorkCard.vue`、`frontend/src/components/circle/WorkListRow.vue`
- 本地 / 服务端上传预览：`frontend/src/components/circle/CircleLocalUploadDialog.vue`、`frontend/src/components/common/ServerUploadPreviewDialog.vue`
- 操作历史详情：`frontend/src/components/activity/ActivityLogDetailDialog.vue`
- 通知模板编辑器：`frontend/src/components/settings/NotificationTemplatesPanel.vue`、`NotificationTemplateEditor.vue`、`frontend/src/components/settings/block-editor/`（`TemplateBlockCanvas.vue`、`TemplateBlockInspector.vue`、`TemplateBlockLibrary.vue`、`TemplateBlockPreview.vue`、`RichTextEditor.vue`、`SlashMenu.vue`、`blockTypes.js`、`blockMiniRenderers.js`、`defaultEmailTemplate.js`、`presetTemplates.js`、`emailImageExtension.js`、`preserveEmailAttributes.js`）
- 通知铃铛 / 通知中心：`frontend/src/components/system/NotificationBell.vue`、`frontend/src/composables/useNotifications.js`
- 系统弹窗：`frontend/src/components/system/SystemPromptDialog.vue`、`frontend/src/components/system/SystemPromptHost.vue`、`frontend/src/composables/useSystemPrompt.js`
- Lottie 通用组件：`frontend/src/components/common/AppLoadingAnimation.vue`、`AppLottieIcon.vue`、`AppLottieSwitch.vue`、`AppLottieProgressBar.vue`
- 统一空态：`frontend/src/components/common/AppEmptyState.vue`
- 库存索引徽章：`frontend/src/components/library/LibraryIndexBadge.vue`（chip + 圆环 SVG spinner + 实时已扫描数字 + 重建按钮，库存页头部右侧）
- **统一筛选下拉**：`frontend/src/components/common/AppDropdown.vue`，所有页面的单选筛选 / 排序 / 范围选择器都走这个，不要再新增 `el-select`（只在多选 + collapse-tags 场景才允许保留 `el-select`）。

### 桌面 / 发布

- 托盘入口：`desktop_app.py`
- 启动：`backend/run.py`、`backend/start.bat`、`frontend/start.bat`、`start-all.bat`、`start-dev.bat`、`start-dev.ps1`
- 打包：`build-release.bat`、`package.bat`、`backend/build.py`
- CI：`.github/workflows/ghcr.yml`

## 3. 硬规则

### 代码与沟通

- 说明、注释、commit 信息都用中文。
- 修改代码时遵守 `karpathy-writing-style` 的清晰、直接、少废话原则；本项目文档仍以中文工程说明为准。
- 必须使用 `script setup`。展示组件和业务逻辑要拆开，不要继续堆超大 `.vue`。

### 配置与敏感数据

- 用户说“改配置文件”且没有明确说运行态时，默认改仓库模板 `backend/config/config.yaml`，不要直接碰本地真实运行配置。
- 本地桌面 / 开发运行默认读取项目根目录 `data/config/config.yaml`；代码入口是 `backend/app/config/settings.py` 的 `_resolve_config_path()`。只有设置了 `CONFIG_PATH` 时才会改读环境变量指向的文件。
- `get_config_file_path()` 返回的是运行配置路径，当前默认 `./data/config/config.yaml`；排查“设置页保存后配置不对”先看 `/api/config/state`、后端日志里的 `[CONFIG] 尝试加载配置文件` 和 `data/config/config.yaml`。
- `backend/config/config.yaml` 是模板 / 仓库默认配置，不是当前桌面运行态实际读取文件。不要用它判断用户本机设置是否生效。
- 常见真实配置位置：桌面版 / 开发默认 `data/config/config.yaml`，Docker `/app/config/config.yaml`。
- 不要提交真实密码、Token、代理、私服地址、群晖账号信息。
- 默认视为运行态 / 敏感产物：`.env`、`backend/data/`、本地数据库、缓存目录、`.codex-backups/`、`data/`。

### 设置页 / 通知配置

- SMTP 发件配置在 `notification_email` 下，模型在 `backend/app/config/settings.py` 的 `NotificationEmailConfig`，接口聚合在 `backend/app/api/routes.py` 的 `/api/config` 和 `/api/notifications/test-email`。
- `/api/config` 返回 SMTP 密码时必须脱敏为 `********`；保存 `/api/config` 时如果前端传回 `********` 或省略 `password`，后端必须保留运行配置里的真实密码，不能把占位符写回 `data/config/config.yaml`。
- 前端设置草稿在 `frontend/src/composables/useSettingsDraft.js`；保存前应避免把未改动的脱敏密码作为真实配置提交。
- QQ 邮箱 SMTP 常用组合是 `smtp.qq.com` + `465` + `smtp_ssl: true` + `smtp_starttls: false`。`587` 才通常配 STARTTLS；端口和加密方式错配只应导致测试邮件失败，不应拖垮设置页。
- 通知铃铛入口是 `frontend/src/components/system/NotificationBell.vue`，SSE 单例在 `frontend/src/composables/useNotifications.js`。这里的启动 / 停止函数名必须和 composable 导出一致；未捕获的 mounted 报错会连锁打断设置页组件更新。
- IMAP 邮件监听配置在设置页“邮件监听”区块，后端入口聚合在 `routes.py` 的 `/api/email-watcher/*`（启动 / 停止 / 立即检查 / 诊断）。`subject_filter` 默认空字符串，**不要**塞默认关键词，否则 DLsite 邮件会被静默过滤掉。

### 桌面端

- 当前稳定方案是 `pystray` 原生托盘菜单。没明确要求，不要改成自绘菜单 / Win32 假菜单。
- 桌面包名统一为 `KikoeruManager.exe`。
- 图标必须来自仓库资源，不能依赖外部绝对路径。

## 4. 前端设计规则

- 不要交付 Element Plus 默认后台风。
- 样式优先级：`Tailwind CSS` -> 项目已有语义 class -> `Element Plus` 容器 / 基础交互能力 -> Lottie 动画增强。
- 图标只允许用 `lucide-vue-next`。不要混用多套图标库。
- 所有按钮、都要有交互动效：hover `translateY(-2px) scale(1.02)`，active `scale(0.96)`，图标轻旋转。
- 统一动画曲线：`all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)`。
- 按钮优先自定义渐变 / 弱边框 / 小阴影，不要直接交付默认按钮样式。
- 主操作按钮（保留新版 / 重试 / 合并 / 主表单 submit）默认走“180deg 三段渐变 + inset 1px 顶部高光 + 双层 glow shadow”，hover `translateY(-2px)` + 阴影展开，active `translateY(0) scale(0.97)`；参考 `Conflicts.vue` 的 `.conflicts-action-btn.is-primary/is-emerald/is-amber`。
- 次操作按钮（跳过 / 取消 / 关闭）走“白底 ghost”（白底 + 灰文字 + 极淡边），避免和主操作争夺视觉权重。参考 `.conflicts-action-btn.is-slate`。
- 状态 chip / 类型标签（库存 success/warning/danger/info、索引 ready/syncing/error 等）也按“180deg 双段渐变 + inset 1px 顶部高光 + 同色微 glow + hover translateY(-1px) scale(1.04)”出货，不要再用纯色 0.8 透明度的塑料感。
- 页面默认结构：顶部标题区、工具栏、筛选区、卡片主内容、展开详情区。
- 禁止用 Element Plus 默认表格当核心页面布局。
- 新做任务面板、工作台、预览、批量处理、详情抽屉时，默认对齐 `DownloadTaskWorkbenchDialog.vue`。
- 系统确认 / 输入 / 提醒统一走 `useSystemPrompt`，不要新增散落的 `ElMessageBox.*`。
- 页头按钮（刷新 / 重建 / 归档 等）统一走 `.page-head-btn` 规范（定义在 `frontend/src/index.css`）：黑 primary 三段渐变、inset 高光、按下 `scale(0.94)` + `inset shadow` + 短暂白色 flash 高光。**不要**再给页头另写一套自制按钮样式，尤其不要用 Element Plus 默认按钮。
- loading / busy 切换时，图标用 220ms 淡入淡出 swap（参考 `ActivityHistory.vue` 的 `.page-head-btn-icon-swap`），**不要**加载中隐藏整个按钮（会触发被点击→按钮消失→按下态丢失的"闪烁"Bug）。
- `v-app-loading` 遮罩**必须**绑定到「页面内容区」或「Modal 主体区」，而不是整页 / 整 Dialog。典型错误：绑到顶级 section 会盖住头部的「刷新 / 关闭」按钮，用户看到的是"转圈时按钮点不了还在闪"。页头按钮自带按钮级 spinner（`Loader2 animate-spin`），遮罩只负责主内容区。

## 5. 业务链路红线

### 通知模板 / 邮件块编辑器

- 邮件模板已升级为 Block Editor，参考设计文档 `docs/notification-template-builder.md`。模板表多了 `blocks` JSON 列和 `editor_mode` 字段：`html` 走旧逻辑，`blocks` 走新积木渲染，**不要**把两条链路混着改。
- 后端渲染入口在 `backend/app/core/block_renderers/__init__.py`：`render_blocks(blocks, payload) -> sanitize_html -> wrap_email_envelope`。新增块类型必须同时补：前端 `blockTypes.js` 的 `defaultProps / propSchema`、`blockMiniRenderers.js` 的预览、后端 `block_renderers` 里的 `render_xxx`。三者缺一就会出现“画布有但邮件渲染丢失”或“预览和真实邮件不一致”。
- 变量系统统一走 `backend/app/core/variable_registry.py`：中文 key 是权威（`任务标题`、`摘要`、`总文件数`、`业务数据块` 等），英文 key 走 `VARIABLE_ALIASES` 兼容旧模板。**不要**新增散落的 `payload[xxx]` 直读，加变量必须先在 `VARIABLE_REGISTRY` 注册。
- 富文本块的“变量 pill”是 `<span data-var="任务标题">...</span>`，渲染时由 `_VAR_PILL_RE` 还原为 `{任务标题}` 再交给 `substitute_variables`。改 RichTextEditor 时不要破坏 `data-var` 属性，否则邮件里变量会变成纯文字。
- HTML 清洗统一走 `backend/app/core/html_sanitizer.py` 的 `sanitize_html()`（底层优先 `nh3`）。邮件块只输出 email-safe 的 table + inline style，**禁止** `script / iframe / 外部 CSS / JS 交互`。
- 任务发邮件时业务 payload 由 `backend/app/core/notification_helper.py` 构造：`build_notification_extra_for_task` / `build_import_notification_extra` 等，结果通过 `set_notification_extra(task, ...)` 塞进 `task_metadata.notification_extra`，再由 `task_notification_service` 合并进 outbox payload。新任务想在邮件里出业务块（文件树 / 统计 / 日志 / diff），改这里，不要直接改模板渲染。
- 预览接口 `/api/notifications/templates/preview-blocks` 必须 `debounce 300ms + abort 上一个请求 + requestId 校验`，否则乱序响应会让画布闪烁。
- 邮件 `task_metadata` 不能整段塞进 payload，要走 `safe_metadata` 白名单，避免泄漏路径 / Token。
- 旧 HTML 模板继续保留，提供“转换为 blocks”入口；不要直接删 `editor_mode == 'html'` 分支。


### 库存页

- `Library.vue` 是主工作台，不是普通列表页。
- 已集成多库存、本地 + 群晖、搜索定位、文件管理、批量操作、删除过滤预审、RJ 字幕入口、库存索引徽章。
- 改样式前先读现有 class；不要退回默认 Element 风。
- 头部右侧的 `LibraryIndexBadge.vue` 是当前库存搜索索引的状态入口：syncing 时切换 SVG 圆环 spinner，每 1.2s 轮询；后端每 0.5s 上报一次。**不要**关轮询 / 随意改 polling 频率，会破坏“近似实时”体感。
- `lib-chip-success/warning/danger/info` 已升级为渐变 + inset 高光 + glow + hover lift；新增状态标签优先复用这套 class，不要再发明纯色塑料 chip。

### RJ 字幕工作台

- 主入口在库存页，不在设置页。
- 入口包括：当前页抓字幕、当前目录抓字幕、行内识别抓字幕、选中后批量抓字幕、字幕任务面板。
- 流程必须分阶段：扫描 RJ 目录 -> 检查已有字幕 -> 搜来源 -> 下载原始字幕 -> 清洗 -> 自动匹配 -> 人工筛选 / 手动配对 -> 写入 `subtitles/`。
- 不自动扫全盘，不自动抢焦点，不要求用户手填大量路径。
- 抓取阶段和最终落盘阶段必须分开。
- 已有字幕目录要保留在工作台上下文里，不能简单当失败项。
- `awaiting_manual_match` 在前端交互上算进入“筛选与配对”阶段，即使底层状态常还是 `pending`。
- 这类任务允许“重新执行爬取字幕”，不要按普通 `pending` 禁用。
- 扫描区显示“已入任务 N”时，任务总栏和任务队列必须合并显示已绑定 `task_id` 但轮询尚未返回的任务。

### 任务中心

- 新任务不能只做到后端能跑，还要补齐任务中心展示语义、来源页 / 来源动作、历史记录归属、错误 / 重试 / 等待态。
- 任务上下文字段优先补全：`task_domain`、`task_kind`、`session_id`、`source_page`、`source_action`、`source_label`、`business_key`。
- 任务状态除了 `pending / processing / completed / failed`，还有 `paused / waiting_manual / waiting_retry`。
- RJ 字幕任务有自己的进度日志、下载明细、人工匹配等待态，不要硬塞回通用粗粒度进度条。

### 操作历史

- 历史记录已经是树形聚合，不是平铺流水。
- 改任务流时必须考虑操作记录是否落库、同一业务是否被拆成噪音日志、子任务是否应该挂到父记录下。
- `subtitle_import` 只有真正执行导入的 `archive_import / folder_import` 才能挂到“解压入库”树下。
- `pending_execute` 只是预检 / 进入工作台，不进历史树和顶层列表。
- 历史页残留的 `waiting + task_finished` 文案统一展示为 `等待处理`。
- 手动字幕配对完成后：真正落盘才补写 `subtitle_import` 完成日志；只配对不落盘时不能伪造“字幕补配完成”。

### 删除过滤

- 删除过滤是预审制：发起预审 -> 后台扫描 / 预览 -> 用户审阅 -> 确认后删除。
- 删除成功后直接更新当前树和数量，不要删完再强行重跑整轮预审。
- 相关记录必须进入操作审计。

### 问题作品 / 冲突处理

- 新 UI 顶层动作只暴露 `KEEP_NEW`、`SKIP`、`MERGE`。`KEEP_OLD` 只能做兼容别名。
- 解压失败 / 处理失败要落问题作品列表，不要只停在任务失败。
- 重复作品、正在处理中、需要人工判断必须落 `waiting_manual`，不要写成 `completed / success`。
- `KEEP_NEW` 是后台任务链，不是同步直接改库。
- 冲突项允许 `PROCESSING`；列表页会对已结束但仍卡住的关联任务做回退和恢复元数据，别删这段逻辑。
- `classifier._check_existing()` 必须排除运行态目录：`待处理`、`_conflicts`、`temp`、`tmp`。
- 失败项重试链路要看 `cleanup_retry_output_artifacts()`，避免留下上次重试产物。
- `_resolve_kikoeru_server_path` 已统一走 `LibraryManager.find_rj_in_libraries`（接索引快速路径） + `asyncio.wait_for(timeout=20.0)` 兑底慢盘。**不要**回退到原来的 `list_files + global_search_files` 多库并行循环（N 条 conflict 串行会打死接口）。
- `/api/conflicts` 列表分三阶段：`db_query` → `phase1_serial`（SQLAlchemy 串行 status 恢复 + actions 计算）→ `phase2_parallel_context`（信号量 8 限流的 `describe_conflict_async`）。三阶段都打 INFO 耗时日志（前缀 `[/api/conflicts]`），慢盘排查先看日志再动代码。
- 详情区主操作按钮（保留新版 / 重试 / 合并）已落“主按钮设计语言”（三段渐变 + inset 高光 + 双层 glow），跳过用 ghost 拉低视觉权重。改样式前先看 `.conflicts-action-btn` 现有 class。
- 问题作品 resolve 后必须联动操作记录：`/api/conflicts/{id}/resolve` 成功时调用 `mark_task_conflict_resolved_activity_log(task_id, action)`，把原任务那条 `task_finished/waiting` 行回写成 `已跳过 / 已保留新版 / 已合并`。否则操作记录会一直停在"等待处理"——用户觉得"拍完板了记录还在卡"。改 `KEEP_NEW / SKIP / MERGE` 任一分支都要确认这条联动还在。

### ASMR 同步

- ASMR 同步下载链路仍在使用，不是废代码。
- 改 RJ、任务系统、下载上传链路时，不要误伤 `routes.py`、`task_engine.py`、`asmr_resource_service.py` 里的 ASMR 预览、下载、字幕同步、重命名、分类、移动到 `Finished` 流程。

### 社团补全

- 社团补全是独立工作台，入口 `CircleCompletion.vue`。
- 服务器拥有判定是两段式：先按社团关键词走 Kikoeru 搜索分页，再对 canonical RJ 走 `check_duplicate_with_linkages`。
- Kikoeru 没有稳定社团搜索 API 时，走站内真实搜索数据源分页，不要猜接口。
- 下载落盘：先下临时目录，作品目录走 API 命名，最终进入 `目标库存 / 可选前缀目录 / 社团名 / API 命名后的作品目录`。
- 预览弹窗里的“库存内前缀目录”是下拉缓存，不是自由输入；空值表示直接按社团名入库。
- 同类作品卡优先复用 `WorkCard.vue` / `WorkListRow.vue`。保留 `WorkCard.vue` 的 CV 列表和 `.work-cv` 样式。
- 下载工作台摘要进度条用 `AppLottieProgressBar`，不要退回普通纯色条。
- 每个下载任务卡的 Lottie 图标按任务状态独立控制，不要合并成单一 ref。
- 社团补全索引任务支持取消；新增长循环时补 `cancel_callback`。
- 批量下载入口优先用 `asmr_available_rjcode`，不要默认拿 `display_rjcode`。
- DLsite 关联链统一复用 `dlsite_service.get_linked_works()`，不能只信 `language_editions`。

### 密码工作台

- 入口：`frontend/src/views/PasswordVault.vue`；后端聚合在 `routes.py` 的 `/api/passwords/*`。
- **创建密码接口已内置去重合并**：
  - 同时有 `rjcode + filename` 时，命中现有同 RJ + 同文件名条目则更新密码 / 备注 / 刷新 `updated_at`。
  - **没有 RJ 和文件名（通用密码）**时，按 `password` 字段精确匹配合并；仅原备注为空、新输入带备注才补写备注。不改任何字段时连 `updated_at` 都不刷新，避免排序跳动。
  - 合并命中时响应会带 `merged: true`，前端据此显示"已合并到现有密码"，而不是"已新建"。改 `create_password` 分支时不要抹掉这段 dedup 逻辑。
- 排序字段由下拉控制（`passwordSortBy`：`created_at / updated_at / rjcode / filename / use_count`），必须走统一 `AppDropdown`，不要再用 `el-select`。

### 下载 / 上传与大文件

- 群晖上传核心在 `library_manager.py`，ASMR 增强下载上传在 `asmr_resource_service.py`。
- 禁止把整文件 `read()` 进内存再拼 multipart；必须保持分块流式上传。
- 本地复制入库也要分块，不要退回无进度的 `shutil.copy2`。
- 批量取消接口 `/api/tasks/batch-cancel-cleanup` 会取消任务并清理 `download_root`；改取消逻辑时同步考虑文件清理和历史语义。
- Synology 客户端按配置签名缓存，配置变化会自动重建客户端；改群晖配置后不需要重启服务。
- `local_download_ready` 只认数据库明确标志。只有任务 `completed` 才写 `True`，失败 / 异常都写 `False`。
- 工作台依赖字段：`download_files`、`upload_files`、`uploaded_files`、`progress_log`、`failure_reason`、`final_output_path`、`download_root`。
- `LibraryManager.upload_directory_to_remote_library` 已同时支持「单文件」和「目录」上传：单文件时直接落到 `target_root_path/<basename>`，不再套一层同名子目录。改上传链路时注意保留 `isfile(source_dir)` 分支，否则单文件会被当成"空目录"失败。

### 群晖 / 远程库存

- 远程搜索优先走群晖原生接口，不要偷偷退回本地递归。
- 根目录 `/` 搜索时按 share 拆分再汇总。
- RJ 字幕远程扫描递归时跳过 `subtitles`。
- 远程 `list / stat / create` 行为可能不完全一致，改 `relative_path`、`real_path`、标准化路径时要谨慎。
- 判断远程路径是否在库存范围内时，复用现有 `root / browse_root` 校验。
- 常见群晖错误码：`119`、`121`、`401`、`408`。
- 群晖通信相关错误统一抛 `SynologyError`，**不要**裸抛 `RuntimeError`。库存接口对 `SynologyError` 走 `WARNING` 不打堆栈；OTP 过期由前端库存页横幅引导用户重新登录，别在后端日志里刷红。

### 库存搜索索引（LibraryIndexService）

- 2026-05 新加的常驻基础设施。**所有 RJ 跨库搜索 / 库存大小统计 / 问题作品路径拾回**优先走索引快速路径，索引就绪（`status='ready'`）时 ms 级；未 ready 时 fallback 原 SYNO.Search / `os.walk` 路径，**不要**直接调底层 fallback API。
- 入口在 `backend/app/core/library_index/`：`service.py`（重建调度 + self_mutation 通知）、`local_scanner.py`（`os.scandir` 后序遍历）、`remote_scanner.py`（SYNO.FileStation.Search 分页）、`snapshot_store.py`（SQLite 持久化）、`types.py`（`IndexEntry` / `IndexStatus` 数据类）。
- DB 表：`library_index_entries`（索引条目）、`library_index_status`（状态机 + 总数 + 上次扫描时间 + 错误）。**不要**往这两张表里塞业务字段。
- `LibraryManager` 的 `find_rj_in_libraries`、`list_files`（搜索）、`get_library_size` 都已自动接入：ready 走 `LibraryIndexService.search_*`，未 ready 走原 fallback。`conflict_resolution_service` 等业务**直接调 `LibraryManager`**，不要绕开它去拼 `LibraryIndexService`。
- self_mutation：`LibraryManager` 的写操作（删除 / 重命名 / 批量删除 / 移动 / 解压落地 / 字幕落盘）必须**操作完立即**调用 `handle_self_mutation_upsert / delete / batch`，让索引和真实磁盘保持一致；watcher 只兑底外部变更。新增写操作必须补 self_mutation 通知，否则用户重启服务前索引会过期。
- 重建语义：`status='syncing'` 期间 `total_entries` 表示**已扫描数**（实时增长），`status='ready'` 后表示**总条数**。前端徽章按 status 区分文案，**不要**反过来用 `total_entries=0` 判断空库。
- 重建进度上报：本地 / 远程都是 `chunk_size=500` 分块写盘 + 每 0.5s `upsert_status(status='syncing', total_entries=written)`。前端 `LibraryIndexBadge.vue` 轮询 1.2s 配套，**不要**单方面改频率。
- 同库存并发由 `_get_lock(library_id)` 保护：本地阻塞等待，远程立即返回当前状态（避免远程扫描互相挤占）。
- 新部署 / 新加库存：用户必须**手动触发一次重建**才能享受 ms 级查询，**不要**在启动时自动重建（远程库可能 30 分钟）。重建期间业务可正常工作，`LibraryManager` 同时支持 ready 路径和 fallback 路径。
- API：`POST /api/library/index/rebuild?library_id=xxx`（本地走 thread，远程走 async task）、`GET /api/library/index/status?library_id=xxx`、`GET /api/library/index/search?library_id=xxx&q=xxx`。
- 所有索引相关日志都加了 `[索引]` 前缀，慢盘排查直接 `grep [索引]`。
- 测试：`backend/tests/test_library_index_*.py` 共 6 个文件 54 个 case，改这套基础设施前先跑一遍。

## 6. 常见需求先看哪里

- “改配置文件”：默认看 `backend/config/config.yaml`。
- “RJ 字幕有问题”：先看 `Library.vue`、`frontend/src/api/index.js`、`routes.py`、`task_engine.py`、`rj_subtitle_service.py`、`linked_subtitle_import_service.py`、`library_manager.py`。
- “任务中心 / 历史记录不对”：先看 `task_center_service.py`、`activity_log_service.py`、`routes.py`、`Dashboard.vue`、`ActivityHistory.vue`、`Tasks.vue`、`Library.vue`。
- “社团补全任务 / 历史不完整”：先看 `ActivityHistory.vue` 社团索引概览、`routes.py` 的 `circle_completion` 聚合、`Tasks.vue` 的 `dlsite_failure_reason`、`activity_log_service.py` 的类型映射。
- “下载 / 上传工作台不对”：先看 `asmr_resource_service.py`、`library_manager.py`、`routes.py`、下载 / 上传工作台组件、上传预览组件、`ActivityHistory.vue`。
- “通知邮件 / 模板 / 变量 / 业务块不对”：先看 `notification_template_service.py`、`block_renderers/__init__.py`、`variable_registry.py`、`notification_helper.py`、`task_notification_service.py`，前端看 `NotificationTemplateEditor.vue`、`block-editor/RichTextEditor.vue`、`blockTypes.js`、`blockMiniRenderers.js`。
- “通知铃铛 / 通知中心 / 邮件监听不对”：先看 `NotificationBell.vue`、`useNotifications.js`、`routes.py` 的 `/api/notifications/*` 与 `/api/email-watcher/*`。
- “推送仓库”：先跑 `git status`，确认没有 `.env`、本地数据库、用户配置、缓存目录，tag 符合 semver。
- “Actions 失败”：先看 tag 是否 `vX.Y.Z`，再看 `.github/workflows/ghcr.yml` 的触发和 semver 解析。

## 7. 一次性脚本

- 历史重复社团索引清理：`backend/scripts/merge_duplicate_circle_catalogs.py`
  - 预览：`py -3 backend/scripts/merge_duplicate_circle_catalogs.py`
  - 写入：`py -3 backend/scripts/merge_duplicate_circle_catalogs.py --apply`
  - 如果 `circle_works` 加字段，要同步维护 merge 逻辑。
- 操作历史脏数据清理：`backend/scripts/cleanup_dirty_activity_logs.py`
  - 默认预览，真正写入加 `--apply`。
  - 用于删除旧 `subtitle_import / pending_execute` 噪音、修正重复作品 success、清理运行态目录误判。

## 8. 最低验证

- 改前端：至少在 `frontend` 执行 `npm run build`。
- 改后端核心：至少执行 `py -3 -m py_compile backend/app/api/routes.py backend/app/core/task_engine.py backend/app/core/rj_subtitle_service.py backend/app/core/task_center_service.py backend/app/core/activity_log_service.py`。
- 改库存搜索索引 / `library_manager.py` 写操作 / `find_rj_in_libraries`：在 `backend` 下跑 `venv\Scripts\python.exe -m pytest tests/test_library_index_*.py tests/test_library_manager_index_integration.py -q`，54 个 case 必须全过。
- 改通知模板 / 邮件渲染：补 `py -3 -m py_compile backend/app/core/notification_template_service.py backend/app/core/notification_helper.py backend/app/core/task_notification_service.py backend/app/core/variable_registry.py backend/app/core/block_renderers/__init__.py backend/app/core/html_sanitizer.py`，前端 `npm run build`。
- 改社团补全后端：补跑 `py -3 -m py_compile backend/app/core/circle_completion_service.py backend/app/core/asmr_resource_service.py backend/app/models/database.py`，前端仍跑 `npm run build`。
- 改下载 / 上传链路：前端跑 `npm run build`；如改后端，补对应 `py_compile`。
- 改桌面版：检查托盘图标、菜单、打开 Web、退出、打包。
- 改发布流程：检查 `.github/workflows/ghcr.yml` 和 semver tag。

## 9. 操作历史性能栈

`/api/activity-logs` 已做 Phase 4D 优化，首屏热命中约 `~11ms`。动这片代码前先理解下面这些约束。

- JSON 列由 `orjson` 反序列化，依赖写在 `backend/requirements.txt`。
- `activity_log_writer.py` 里有 append-only 行级 dict LRU 缓存，默认上限 10000 行。
- `routes.py` 的 `list_activity_logs` 先查 ID，再走缓存命中，miss 批取 ORM，最后调用 `merge_activity_rows_from_dicts(rows_dict)`。
- `merge_activity_rows_from_dicts` 的入参永远当不可变。行级缓存存的就是这些 dict，算法里禁止原地改深层 `detail` / `child_rows`。
- 防御测试：`backend/tests/test_activity_log_aggregator.py` 里的 `test_from_dicts_does_not_mutate_input`。
- `row_cache` 的设计前提是 `activity_logs` 只有 INSERT，没有 UPDATE / DELETE。以后如果支持编辑审计行或软删除，必须同步 invalidate 缓存。
- 新增后端运行时依赖，尤其二进制扩展，必须同步：`requirements.txt`、五个启动自检脚本、`backend/build.py`、`build-release.bat`。
- profile 脚本保留在 `.codex-backups/`，改 list 接口 / merge 算法 / writer 缓存后，至少跑 `_profile_cached_endpoint.py` 看热命中是否仍在 `~10ms` 量级。

## 9.5 库存搜索索引性能栈

`LibraryIndexService` 是 2026-05 新基础设施，所有 RJ 跨库搜索、库存大小统计、问题作品路径拾回都依赖它。动这片代码前理解约束。

- 索引数据由 SQLite 持久化（`library_index_entries` + `library_index_status`），不依赖内存。重启服务索引仍在。
- 索引就绪（`status='ready'`）时 RJ 搜索是 ms 级；未 ready 时 fallback 原 SYNO.Search / `os.walk`，慢但功能等价，业务无感。
- self_mutation 是为了“业务自身改了文件后索引立刻同步”，避免 watcher 延迟。新加的删除 / 重命名 / 移动 / 解压 / 字幕落盘代码都必须挂上 self_mutation 通知。
- 单条 search 是 ms 级，但**前端不要无脑高频调用**：`/api/conflicts` 这种 N 条 conflict × N 次跨库 search 的场景必须配信号量限流（已用 `Semaphore(8)`） + 总超时（已用 `asyncio.wait_for(timeout=20)`），否则远端 NAS 占线时单条会拖死整个请求。
- 重建本地库 `chunk_size=500` 分块写盘 + 每 0.5s `upsert_status` 一次；远程也是这个节奏。前端轮询 1.2s，合起来是“近似实时”。不要把重建改成全量扫完再一次写盘。
- 跨库查询 `LibraryManager.find_rj_in_libraries` 内部并行调用 `LibraryIndexService.search_rj_per_library`，仅对 ready 的库走索引、未 ready 的库走原 fallback。**不要**为了走索引背面强迫重建。
- 阅后端日志：所有 `LibraryIndexService` 所发日志都以 `[索引]` 开头。前端可以调 `/api/library/index/status` 验证状态。

## 10. 当前优先级

1. 稳定 RJ 工作台“原始抓取 -> 人工筛选 -> 自动预匹配 -> 手动配对 -> 最终写入”整条链。
2. 清理任务中心、操作日志、字幕工作台之间的状态串台。
3. 统一库存页工具栏、批量条、右侧操作区的交互一致性。
4. 稳定下载 / 上传工作台与群晖大文件链路。
5. 继续补群晖 DSM 兼容细节，尤其远程 `subtitles` 目录处理。
6. 清理旧文案、乱码注释、历史品牌残留。

## 11. 最近改动同步（2026-05）

### 性能：DB 连接池 + 社团补全 / DLsite 调用栈（v1.5.35）

整批围绕"任务执行期一直占着 db connection + 重复 HTTP"的卡顿问题，按"短事务 + 跨 IO 切段 + 函数级 cache"模板重构。

- **`backend/scripts/find_long_db_sessions.py`**：辅助脚本，扫描所有 `db = SessionLocal()` / `next(get_db())` 块里跨 `await IO` 的长事务点，作为这一批重构的 grep 入口。后续要加新 service / route 时，先用它扫一遍，避免又写出"DB 拿着不放跑外网"的形态。
- **`circle_completion_service.py`**：新增 `CircleCompletionSnapshot` dataclass，把任务执行期所有外部数据（asmr work_info / tracks、canonical 链路、Kikoeru 状态）一次性集中获取（Phase 1）；Phase 2 纯本地查询，不再触网。新增 `chain_rjs_by_canonical` 链路去重，把 Kikoeru 查询次数从全 RJ 数（典型 39）降到独立链路数（典型 13）；中文翻译版可见性探测改信任 DLsite 的 `language_editions`，不再走 `_is_public_work_available` HTML probe（一次任务能省 698 次抓取里的 580 次 miss）。
- **`dlsite_service.py`**：
  - `_linked_works_inflight` 函数级 inflight + cache：之前一次社团补全任务里同一 RJ 会被 `prepare_candidate` / `resolve_canonical_rj` / Kikoeru `check_duplicate_with_linkages` 三处分别触发完整递归（一次任务跑了 2819 次 `get_linked_works`），现在同一 RJ 在同一任务内只完整递归一次。
  - `_fetch_page_html_with_url`：把 HTML 字节按 URL 集中缓存，`_resolve_translation_page_fallback` 和 `_fetch_product_page_metadata` 不再各抓一次同一 URL（双抓 BUG）。
  - `_detect_brotli_support()` 启动期主动探测 `brotli`/`brotlicffi`，未装时把 `Accept-Encoding` 自动降到 `gzip, deflate`。**否则** DLsite 返回 `Content-Encoding=br` 时 httpx 不解压、`response.text` 直接是乱码二进制，社团 profile 解析为 0、关键字搜索 / 全站推荐位 RJ 汇染整批挂掉。`requirements.txt` 把 `brotli>=1.1.0` 换成 `brotlicffi>=1.1.0`（cffi 实现，对 Python 3.13/3.14 兼容性好得多）。
- **`linked_subtitle_import_service.py`**：把跨整循环 + 多 await 的长事务重构成 Phase A 短读 + `expunge_all` / Phase B 无 session 跑 IO 算决策 / Phase C 短写落库的三段式。前端轮询字幕补配工作台高频调用时不会再压垮 connection pool。
- **`conflict_resolution_service.py`、`duplicate_service.py`、`kikoeru_duplicate_service.py`、`email_watcher_service.py`、`processed_archive_cleanup.py`**：同样的"短事务 + 跨 IO 切段"模板，分别覆盖问题作品扫描、查重、Kikoeru 查重、IMAP 邮件监听、归档清理几条主链路。
- **`routes.py /api/conflicts`**：phase1 拿到 conflicts 列表后立即 `expunge_all` + `db.close()`，phase2 跑远程 stat / IO 全程不带 db。phase1 抛异常时 phase2 仍兜底 close 一次。

### Bug 修复：7zz 解析 Windows CRLF 残留

- `extract_service.py::_parse_7z_list_output` 之前 `output.strip().split('\n')`，Windows 上 7zz 走 CRLF 输出，每行末尾的 `\r` 被 regex 的 `(.+)$` 吃进 `name` 字段（`'test.txt\r'`），下游所有按 `'.txt'` / `'.zip'` 比对全部失效，影响 `_get_archive_info` 等所有下游清单校验。改成 `splitlines()` + `name.rstrip('\r')`。

### 测试基础设施 + 历史失败一次性清账

- `backend/tests/conftest.py` 新增 `pytest_configure`：把 pytest `tmp_path` basetemp 重定向到工程内 `backend/.pytest-tmp/`，绕开 Windows `%TEMP%/pytest-of-<user>/` 经常被杀软 / OneDrive 锁定导致的 `PermissionError [WinError 5]`，每次启动还会清理上一轮残留。`.gitignore` 同步加 `backend/.pytest-tmp/` + `.pytest_cache/`。
- 一次性修了 14 个历史失败 / 错误：
  - `test_extract_service.py` 5 个：CRLF 期望对齐、`_find_garbled_filename_sample` 改返回 `_safe_diagnostic_name` 后的字符串、`unzip` 命令换成 `zipfile.extractall`、`Mock(spec=Task)` 漏指实例属性改用真实 Task、`_wait_file_stable` 对 < 1024 字节小 zip 死等 30 分钟（patch 跳过）。
  - `test_library_index_self_mutation.py` 7 个：全是 `tmp_path` 创建失败，被上面的 conftest 修一次性救活。
  - `test_library_browser_api.py`：原 `_LegacyStorage` ad-hoc 类没有 `model_dump`、`monkeypatch _config_file_path` 路径根本不被生产代码调用、嵌套目录层级错让浅层列表查不到目标作品。改用真实 `StorageConfig` + 扁平目录。
  - `test_api.py::test_get_task_by_id`：`task_engine` 是进程级单例，跨测试共享，`FileProcessor.process_file` 会拒绝 source_path 已在 pending/processing 的重复任务（返回 None → route 抛 400）。每个 test 用唯一 source_path。
- 新增 3 个测试文件：`test_circle_completion_announce_search.py`、`test_circle_completion_release_date.py`、`test_circle_completion_snapshot.py`，覆盖社团补全的 announce 搜索、发售日解析、snapshot 新数据流。
- 全量验证：`venv\Scripts\python.exe -m pytest tests/` → **204 passed, 0 failed**。

### 社团补全 / 缺失作品

- 缺失作品"发售时间"排序在 `frontend/src/views/CircleCompletion.vue` 增强了日期解析：
  - 支持从带附加文本的日期里提取 `YYYY-MM-DD`（如带括号、曜日、说明文案）。
  - 支持宽松 `YYYY-MM` 解析，避免解析失败被当作 `0` 导致倒序沉底。

### 版本号 / 发布

- 侧边栏版本号来源是 `frontend/src/App.vue` 的 `appVersion` 常量；发版改版本时要同步这里。
- 已发生一次误把 `frontend/src/assets/temp/` 临时图提交进仓库的情况；后续提交前必须重点检查临时目录与二进制资源是否误入变更集。
- 版本发布已使用 semver tag：`v1.0.10`；如果代码有补提，记得同步更新 tag 与展示版本，避免"标签版本"和"UI 版本"不一致。

### 字幕去重逻辑（`rj_subtitle_service.py`）

- 去重策略改为：**先按文件名分组，再在同名组内比对内容指纹**，避免不同音轨对应的同内容字幕被误合并。
- 修改前的逻辑会跨名称直接用内容指纹去重，导致同名不同轨的字幕丢失；修改后每组独立走 `_build_subtitle_content_fingerprint`，不同名称不再跨组合并。

### Kikoeru 查重服务（`kikoeru_duplicate_service.py`）

- `_fetch_track_subtitle_state` 返回值由 2 元组改为 3 元组：`(subtitle_count, total_track_count, source)`，新增 `total_track_count` 用于判断服务器是否为空壳作品。
- `KikoeruDuplicateResult` 新增 `total_track_count: int` 字段（`-1`=未知，`0`=空壳，`>0`=有文件），调用方改动要同步更新解包。

### 解压服务（`extract_service.py`）

- 新增 `_collapse_wrapper_dir`：解压后若输出目录只有一层同名包装目录，自动折叠进父目录，避免多余嵌套。
- 新增 `_try_extract_nested_direct`：直接解压至目标目录的内层尝试，减少无效临时目录。

### 字幕导入服务（`linked_subtitle_import_service.py`）

- 新增 `_quick_count_local_candidate_files`：快速统计候选字幕数量，避免全量扫描。
- `summarize_cached` / `_noop_kikoeru` 内部辅助函数化，减少重复调用开销。

### 任务引擎（`task_engine.py`）

- 新增对"小型压缩包是字幕候选"的判定分支：`< 10MB` 且开启字幕匹配预检时，根据 Kikoeru 状态决定走字幕配对路由还是转问题作品等待人工。
- 新增 `_queue_nested_subtitle_archives`：解压后如发现内嵌字幕压缩包，自动入子任务队列处理。
- 启动时清理上次服务重启前残留的"正在处理中"临时冲突记录。

### 通知构造层（`notification_helper.py`、`variable_registry.py`）

- 新增 `build_problem_work_notification_extra`：问题作品任务（`waiting_manual` / 冲突类）专用 payload 构造函数，支持 RJ 作品卡片块（`rj_work_cards`）。
- 新增 `_dedupe_redundant_tree_dirs`：清洗文件树中与 RJ 前缀冗余的单级包装目录。
- `variable_registry.py` 新增 `rj_work_cards` 变量示例（包含 `success`、`duplicate`、`waiting_manual` 三种卡片状态的预览样本）。

### 邮件块渲染（`block_renderers/__init__.py`、`blockTypes.js`、`blockMiniRenderers.js`）

- SVG 图标渲染补全了 `fill:none; stroke` 等属性，修复部分客户端图标不可见的问题。
- 文件树渲染逻辑改进：
  - 新增 `_coerce_tree`：将平铺路径列表自动转换为嵌套目录树，兼容没有预构建树的旧 payload。
  - `file_tree` 优先级调高：`download_files / upload_files / filtered_files / extracted_files` 中任意一项有值且 `file_tree` 存在时，统一切换到 `file_tree` 渲染。
  - 目录行改用 `<details>/<summary>` 折叠，解决 `margin-left` 与 `padding-left` 叠加导致深层文件缩进过大的问题。
  - 继承 `is_muted` 状态：父目录被过滤时子节点自动置灰，不再需要每个子节点单独标记。

### 任务中心 / 操作历史（`Tasks.vue`、`ActivityHistory.vue`）

- 文件树新增 `dedupeTreeDirs`：折叠与 RJ 前缀同名或内容相同的单层包装目录，前端展示层与后端 `_dedupe_redundant_tree_dirs` 对齐。
- `Tasks.vue` 修复 `upload_files` / `uploaded_files` 判断逻辑：从"先后判断"改为"合并判断"，避免其中一个为空时另一个被跳过。
- `ActivityHistory.vue` 文件树标题改为始终显示实际条目数，不再因过滤数量为 0 而显示不同格式的括号文本。

### 数据库模型（`database.py`）

- `ProcessedArchive.to_dict()` 中 `processed_at` 现在正确附加本地时区偏移（`+08:00` 格式），避免前端把无时区 ISO 字符串当 UTC 解析导致时间显示提前 8 小时。

### 字幕检查工作台（`SubtitleInspectorWorkbench.vue`、`SubtitleTaskStage.vue`、`SubtitleWorkbenchStage.vue`）

- 顺序配对模式 UI 升级：音频选中序号徽章改为蓝色圆形胶囊（`bg-blue-600`），字幕序号改为紫色（`bg-violet-600`），视觉区分更清晰.
- 左侧音频行 hover 改为蓝色系，字幕行 hover 改为紫色系，已进入序列的行用渐变高亮+阴影区分.
- 顺序配对提示文案更新，明确说明"左侧蓝色序号=音频顺序，右侧紫色序号=字幕顺序".
- 中间三栏改用 `overflow-x-auto` + `min-w-[980px]` 包裹，解决小屏幕下三列被压缩至不可用的问题.
- 操作按钮改用可选链调用（`view.xxx?.()`），避免 `ctx` 为空时 mounted 报错连锁打断父组件更新.
- `view` computed 补全了完整的空值默认对象，防止 `props.ctx` 为 `null` 时模板访问属性报错.

### 库存搜索索引（新基础设施 `LibraryIndexService`）

- 新增模块 `backend/app/core/library_index/`（`service` / `local_scanner` / `remote_scanner` / `snapshot_store` / `types`）+ DB 表 `library_index_entries` / `library_index_status`，所有 RJ 跨库搜索 / 库存大小统计 / 问题作品路径拾回都走它.
- `LibraryManager.find_rj_in_libraries` / `list_files` 搜索分支 / `get_library_size` 已接入：ready 时 ms 级走索引，未 ready 走原 SYNO.Search / `os.walk` fallback，业务无感.
- `LibraryManager` 的本地与远程写操作（删除 / 重命名 / 批量删除 / 移动 / 解压落地 / 字幕落盘）全部挂 `handle_self_mutation_*`，索引随业务实时同步，不依赖 watcher 兜底.
- 重建支持每 0.5s 进度上报：`chunk_size=500` 分块写盘 + `upsert_status(status='syncing', total_entries=written)`，syncing 期间 `total_entries` 表示**已扫描数**，ready 后表示**总条数**.
- 同库存并发由 `_get_lock(library_id)` 保护：本地阻塞等待，远程立即返回当前状态避免互相挤占.
- 接口 `POST /api/library/index/rebuild` / `GET /api/library/index/status` / `GET /api/library/index/search`，全部聚合在 `routes.py`，所有日志加 `[索引]` 前缀.
- 测试覆盖 `backend/tests/test_library_index_*.py` + `test_library_manager_index_integration.py` 共 54 个 case.

### 库存索引徽章（`LibraryIndexBadge.vue`）

- 库存页头部右侧新组件，展示当前库存索引状态：idle / syncing / ready / error 四态.
- syncing 时把 `IconDatabase` 切换为双层 SVG 圆环 spinner（背景轨道 + 旋转弧 dasharray 动画），同步显示已扫描数（千分位 + `tabular-nums` 防跳）.
- 轮询 1.2s 配后端 0.5s 上报，成“近似实时”体感.
- chip 升级渐变底 + inset 1px 顶部高光 + syncing 呼吸式扩散环.
- 重建按钮内置确认弹窗（`useSystemConfirm`），远程库给“可能数分钟到数十分钟”的预期.

### 问题作品列表性能与视觉

- `_resolve_kikoeru_server_path` 改走 `LibraryManager.find_rj_in_libraries`（享受索引快速路径），加 `asyncio.wait_for(timeout=20.0)` 兑底慢盘.
- `/api/conflicts` 加三阶段 INFO 日志（前缀 `[/api/conflicts]`）：`db_query` / `phase1_serial` / `phase2_parallel_context` / `完成 total`，慢盘排查直接看日志.
- 详情区主操作按钮（保留新版 / 重试 / 合并 / 跳过）重设计：主按钮三段渐变（180deg 三色） + inset 顶部高光 + 双层 glow shadow + hover translateY(-2px) + 图标独立动效（重试图标逆旋 180°、合并图标轻跳、保留图标 scale + 微旋）；跳过改白底 ghost 拉低视觉权重.
- 批量按钮（批量重试 / 批量跳过）同步对齐新设计语言，紧凑款 30px 高.

### 库存页标签视觉升级

- `lib-chip-success / warning / danger / info` 从纯色 0.8 透明改为 180deg 双段渐变 + inset 1px 顶部高光 + 同色微 glow + hover `translateY(-1px) scale(1.04)`，告别“塑料感”.

### 统一筛选下拉 `AppDropdown` 全系统落地

- 引入 `frontend/src/components/common/AppDropdown.vue` 作为单选筛选 / 排序 / 范围选择的项目统一下拉。风格 = trigger 按钮 + 弹出菜单 + icon + label + badge，跟页头按钮、主按钮设计语言一致.
- 已替换 8/9 处 `<el-select>`（整站仅 `Logs.vue` 的 `selectedModules` 多选 + collapse-tags 保留 `el-select`）：
  - `views/ActivityHistory.vue`：时间范围 `statsDays` + 分类 + 状态 三处.
  - `views/Logs.vue`：日志条数 `logLimit`.
  - `views/PasswordVault.vue`：密码排序 `passwordSortBy`.
  - `views/CircleCompletion.vue`：社团排序 `circleSortKey`.
  - `components/settings/RulesSettingsPanel.vue`：过滤规则作用域 / 分类规则类型（v-for 内各一处）.
  - `components/subtitle-import/SubtitleImportWorkbench.vue`、`components/library/subtitle-workbench/SubtitleConfigRail.vue`：字幕过滤作用范围.
- 新增单选筛选一律走 `AppDropdown`；只有 `multiple + collapse-tags + tag 渲染` 这种 AppDropdown 没覆盖的复杂场景，才允许继续用 `el-select`.

### 全局按钮反闪烁 + `page-head-btn` 规范传播

- 页头「刷新 / 重建 / 归档 / 返回」按钮统一落 `.page-head-btn` 规范（class 在 `frontend/src/index.css`）：黑 primary 三段渐变 + inset 高光 + 按下 `scale(0.94)` + `inset shadow` + 短暂白色 flash 高光 + hover `translateY(-2px)`.
- loading 态不再隐藏整个按钮，而是用 220ms 淡入淡出 swap `RefreshCcw ↔ Loader2 animate-spin`（`.page-head-btn-icon-swap`），文字同步切换（`刷新` ↔ `刷新中…`），彻底消灭"按下→按钮消失→按下态丢失"闪烁 Bug.
- 已传播到 `ActivityHistory.vue`、`ASMRSync.vue`、`SubtitleImport.vue`、`LibraryBackup.vue`、`ExistingFolders.vue`、`Conflicts.vue`、`Library.vue`、`CircleCompletion.vue`、`PasswordVault.vue`；未来新页面必须对齐这套 class，不要再手搓自制页头按钮.

### `v-app-loading` 遮罩不再盖头部 / 关闭按钮

- 修正了原先把 `v-app-loading` 绑到页面 / Dialog 顶层 section 导致遮罩盖住「刷新 / 关闭 / 归档」按钮、用户点不了又看到按钮闪烁的 Bug.
- 规则：`v-app-loading` **只绑到"主内容区"**（例如 `timeline-shell`、`dialog-body`），头部和工具栏始终可见可点；头部按钮自带按钮级 `Loader2` spinner，遮罩只负责主体.
- 已修复页面：`ActivityHistory.vue`、`Library.vue`、`FolderContentsDialog.vue`、`FilterDeleteDialog.vue`、`SubtitleImportWorkbench.vue`.

### 操作记录页重构（`ActivityHistory.vue` + `useActivityDetailModels.js`）

- 筛选栏：时间范围 / 分类 / 状态 全部换成 `AppDropdown`；下拉选择即触发查询；筛选命中条件时显示重置按钮，没筛选时不显示（减少视觉噪音）.
- 页头「刷新」按钮走 `.page-head-btn` + 图标 swap，loading 态按钮永远可见，不再闪烁.
- 加载遮罩只绑在 `timeline-shell` 上，不影响头部按钮点击.
- `activity_log_lite.py` 的 `build_lite_item` 针对单条 `pipeline_rename` 补 `compact_detail`（`old_name / new_name / error / reason`）；前端 `useActivityDetailModels.js` 读取这段字段渲染「原 / 新」对比块。批量重命名（`batch_api_rename / batch_manual_rename`）不挂这个字段，保留 summary 走批量路径.

### 问题作品联动操作记录（后端 + 前端）

- 新增 `backend/app/core/activity_log_service.py::mark_task_conflict_resolved_activity_log`：问题作品 `/api/conflicts/{id}/resolve` 成功后，把原任务那条 `task_finished/waiting` 行回写成 `已跳过 / 已保留新版 / 已合并`，同时更新 `status`（SKIP→cancelled / KEEP_NEW / MERGE→success），让操作记录页不再停留在"等待处理".
- `routes.py` 的 `resolve_conflict` 在成功分支里统一调用这个 writer；改 `KEEP_NEW / SKIP / MERGE` 任一分支时都要确认联动还在.

### 密码工作台去重合并（`routes.py::create_password`）

- 同 `rjcode + filename` 已有条目 → 更新密码 / 备注 / 刷新 `updated_at`.
- 通用密码（无 RJ 无 filename）按 `password` 精确匹配合并；仅当原备注为空且新输入带备注时补写备注，**不**刷 `updated_at`，避免"每次保存相同通用密码都把条目顶到排序最前面".
- 响应体新增 `merged: bool` 字段，前端据此显示"已合并到现有密码"而不是"已新建".

### 单文件上传支持（`library_manager.py::upload_directory_to_remote_library`）

- 原本只支持目录上传，传入单文件时把 `basename` 当目录塞，结果远程生成"空目录 / 文件跑到同名子目录里".
- 现改为先判断 `os.path.isfile(source_dir)`：单文件时构造一条 `file_row` 走同套并发通道，`final_remote_path = target_root_path/<filename>`，不再多套一层目录；成功后按需 `os.unlink(source_dir)`.
- 目录场景逻辑完全不变（`os.walk` + 并发）。

## 21. 移动端适配（进行中 / 接手说明）

整个移动端适配按 Phase 推进，**桌面端零改动**是最高优先级硬约束（所有规则必须包在 `@media (max-width: X)` 或新增类名内，不能改桌面端原始 CSS）。

### 21.1 当前进度（2026-05）

**已完成**：

- **Phase 0 奠基**：`@/frontend/src/index.css` 加 `Mobile Adaptation Foundation` 大区块（断点别名、`mobile-full-dialog` / `subtitle-workbench-dialog` / `custom-preview-modal` / `filter-delete-dialog` 等 `.el-dialog` 类 `≤640` 自动全屏 100vw/100dvh）、`useViewport.js` composable（`isMobile/isTablet/isDesktop` 响应式状态）、hover 保护（`@media (hover: hover)` 包裹所有 hover 样式）。
- **Phase 1 骨架**：`App.vue` 移动端汉堡抽屉侧栏（≤1024 收 sidebar 进抽屉、汉堡按钮、点遮罩关闭）、Dashboard 移动端 stream 模式（解锁 height 100%、padding 8/10/16）、Tasks 任务队列移动端布局（`TasksFilters` 工具栏 wrap、`DashboardActiveTasks` 卡片紧凑）。
- **Phase 2.1 轻量页 + 全局基座**：
  - `AppPageHeader.vue` 全局 ≤640 stack（左右两区垂直堆叠、icon 36×36、title 18px）
  - `index.css` 在 `@media (max-width: 640px)` 加 slot 区通用规则（`.app-page-head-right > button` 50% 等宽、`.icon-only` button 自然方形、`.hero-search-wrap / .page-head-search-wrap / .page-head-search / input[type="text"]` 独占整行）— 这条规则必须放全局而非 AppPageHeader scoped，因为 slot 内子元素带的是父组件 data-v 不是 AppPageHeader 的
  - `Settings.vue` ≤640 padding + `SettingsWorkbench.vue` ≤1024 双栏 → 横向滚动 chip nav（search/footer 隐藏）
  - `PasswordVault.vue` ≤640 搜索框全宽覆盖
  - `ExistingFolders.vue` ≤640 padding + sidebar actions 2 列
- **Phase 2.2 Conflicts**：`Conflicts.vue` ≤1024 双栏（list 360px + detail）→ flex-col stack、内部 `.conflicts-list-scroll / .conflicts-detail-body` overflow 松绑、批量动作按钮 wrap + 50% 等宽、≤640 padding 收紧。
- **Phase 2.3 ActivityHistory**：`ActivityHistory.vue` ≤640 padding/metric/event-row/filter-bar 紧凑、`ActivityLogDetailDialog.vue` ≤640 全屏覆盖（关键：自身 `.activity-detail-dialog :deep(.el-dialog)` 优先级 > 全局 `.custom-preview-modal.el-dialog`，所以必须在组件 scoped 内补 ≤640 全屏 + 解锁 `.activity-window` 的 `min-height: 800px / max-width: 1840px` 默认值 + 内部 grid `min-width: 0` + `word-break: break-all` 防长 trace-id 撑爆）。
- **Phase 2.4 SubtitleImport**：`SubtitleImport.vue` view 页 ≤1024 双栏 stack（`.subtitle-main / .subtitle-list-pane / .subtitle-detail-pane` 转 flex-col、内部 `.subtitle-list-scroll / .subtitle-detail-body` 滚动区松绑、Tab segmented 占满整行 + 按钮平均分）、≤640 padding 收紧 + meta-grid 改单列 + 提交按钮全宽 + 字幕文件树 max-height 200px；`SubtitleImportWorkbench.vue` 仅顺带修复 ≤640 解锁 `.subtitle-workbench-shell` 的 `min-height: 78vh / max-height: 92vh` 和 `:global(.subtitle-import-workbench-dialog .el-dialog__body)` 的 `max-height: calc(100vh - 18px)`，让 shell 撑满全屏 dialog（dialog 由全局 `.subtitle-workbench-dialog` 规则统一改成 100vw/100dvh）。**内部 `SubtitleWorkbenchStage` 三栏（任务栏 / 配对区 / 上下文抽屉）的分步抽屉化未做**，留给 Phase 4。
- **Phase 2.5 Library**：`Library.vue`（17K 行，全项目最重；**主表格其实是 `el-table` 不是 ag-grid**，AGENTS.md 之前的描述已修正）。新增 `frontend/src/components/library/LibraryMobileCard.vue`（图标 + 文件名 + RJ chip + 大小·时间 + 来源库 chip + 右上角 ⋮ 按钮，9 类文件 icon 颜色与桌面 `.file-icon.icon-*` 同源，状态 class `.is-located / .is-context-active / .is-operating` 与 `library-row-*` 视觉对齐）。`Library.vue` 在 `el-table` 上加 `v-if="!isMobileViewport"`，紧跟一个 `v-else` `.lib-mobile-list` 渲染 `LibraryMobileCard` v-for；新增 3 个 handler `onMobileCardClick / onMobileCardContextMenu / onMobileCardMenuClick`，复用桌面端 `handleLibraryRowClick / handleLibraryRowContextMenu / openLibraryRowContextMenuAtPosition`，搜索结果直接走 `locateLibrarySearchResult`。**移动端不实现多选**（el-table 的 selection-change 同步过来代价大；多选保留桌面端），sort 只在桌面端通过 el-table 头部触发。≤1024 `.lib-card-header` 工具栏 stack。≤640 进一步紧凑（**第二轮**优化）：`.lib-info-strip` **整块 `display:none`**（库名 / 健康 / 索引徽章已经在 `AppPageHeader` chip 区展示，重复保留只是一屏空间浪费）；`.lib-toolbar` 改 **2 列 grid** —— `:deep(.app-dd-root)`（库下拉）和 `:deep(.lib-search-box)`（LibrarySearchBox 根 class）各 `grid-column: 1 / -1` 独占整行，剩下的 button 按 grid 流自动 2 列分布；`.path-toolbar` 同 2 列 grid，`.path-toolbar-left` / `.path-toolbar-right` 各占整行（`right` 内再嵌 2 列 grid 给批量按钮，scope-toggle 独占整行）；`.batch-actions` 同 2 列 grid 平分批量按钮；`.pagination-wrap` 隐藏 `el-pagination__sizes/__jump` 只留 prev/pager/next + 总数。**`tableRef.value` 全文件都用了 `?.` 可选链，移动端 el-table 不渲染时不会报错**。**关键技术点**：搜索框命中要用 `:deep(.lib-search-box)`，不是 `.lib-search`/`.lib-search-wrap`（那是 LibrarySearchBox 内部的子 class）。

- **Phase 3 高复杂度页（已完成 ASMRSync + CircleCompletion）**：
  - **Phase 3a `ASMRSync.vue`**（88KB / 2288 行）：引入 `useViewport`，给 preview `el-dialog` 加 `class="mobile-full-dialog"`（全局 ≤640 自动 100vw/100dvh），enhanced session `el-drawer` 用 `:size="isMobileViewport ? '100%' : '55%'"` 动态切换。模板内两处 `grid-cols-3` / `grid-cols-2` 改成 `grid-cols-1 sm:grid-cols-*` 默认单列。≤640 末尾追加大块 CSS：`.asmr-page` padding 8/10/14、`.asmr-info-strip` 进一步紧凑（≤720 已有 2 列规则，这里仅 padding/font 压缩）、`.asmr-card-head/body` padding 紧凑、`.asmr-batch-toolbar` stack（actions 3 列 grid，第 3 个"下载选中"独占整行）、`.asmr-task-head` stack + actions 50% 等宽、`.asmr-list-row` stack + actions 2 列 grid、`.enhanced-plan-card` 解锁 max-width 让 grid 撑满、`.asmr-table-wrap` max-height 320 + 内部允许横滑。
  - **Phase 3b `CircleCompletion.vue`**（215KB / 6005 行，全项目第二重）：≤1100 已有的双栏 stack 保留。≤640 末尾追加大块 CSS。**关键修复一："内容看不到 + 划不动"**：桌面端 `.circle-page` 是 `height: 100% + overflow-y: auto` 固定高度滚动容器，内部 `.circle-shell / .circle-main / .works-card / .circle-tabs-wrapper / .circle-tabs / .work-grid / .work-list` 全都 `flex: 1 + min-height: 0`，由 work-grid 自己滚作品。移动端这套嵌套 flex 让每个区只分到屏幕的一小部分高度，work-grid 几乎看不见且嵌套滚动让外层手势"划不动"。**与 Conflicts / SubtitleImport 一致的修复**：≤640 把 `.circle-page` `height: auto + overflow: visible`，内部所有 `flex: 1` 容器一律改成 `flex: 0 0 auto + overflow: visible + min-height: 0 + max-height: none`，让 work-grid 自然撑开、整页跟着外层 `.content-shell` 一起滚。`.circle-tabs :deep(.el-tabs__content) / :deep(.el-tab-pane)` 也松绑 overflow。**关键修复二**：`.circle-tabs-wrapper .toolbar-right-actions` 桌面是 `position: absolute` 在移动端会盖住 tabs 标签，强制 `position: static + flex-wrap + padding-bottom: 6px`。其他视觉紧凑：`.circle-page-header / .index-progress-card` margin/padding 紧凑、`.circle-shell` padding 6px、`.sidebar-card` padding 12 + `.circle-list` `max-height: 320px` 限高（避免移动端整屏只有侧栏可视）、`.toolbar-card` padding 紧凑、`.filter-toggles / .view-toggle-group` wrap、Tailwind utility `.works-card > div.flex.items-center.justify-between` 改 stack + 内部 actions 3 列 grid（primary "下载选中项"独占整行）、`.work-grid` minmax 由 152 改 140 ≤640 稳定 2 列 (414px / 140 ≈ 2.8)、`.works-pager` 居中 + 隐藏 `el-pagination__sizes/__jump`、`.compare-head` 隐藏 + `.compare-row` 改 1 列 stack。两个 dialog `:deep(.circle-preview-dialog .el-dialog)` 与 `:deep(.circle-reimport-dialog .el-dialog)` ≤640 强制 100vw/100dvh 全屏（沿用已有 :deep 选择器路径），body height 设为 `calc(100dvh - footer)` 避免内容溢出。

**待办**：

- **Phase 4 工作台 Dialog**：`DownloadTaskWorkbenchDialog.vue` / `UploadTaskWorkbenchDialog.vue` / `SubtitleImportWorkbench.vue` 内部 `SubtitleWorkbenchStage` 三栏（任务栏 / 配对区 / 上下文抽屉）这些重型 dialog 在移动端要做"分步抽屉"模式（顶部 step indicator + 一次只显示一段表单），dialog 内的 ag-grid（如 `DownloadTaskWorkbenchDialog` 的下载任务表）也要卡片化。
- **Phase 5 收尾**：触摸交互（hit area ≥ 44px）、三档分辨率（414×896 / 768×1024 / 1440×900）实际验证、其他遗漏页面（如 `Logs.vue` / `LibraryBackup.vue` 内部细节）补漏；Library 移动端**多选 / sort** 进入选择模式（长按进入多选）若需要可在 Phase 5 补做。

### 21.2 必读硬约束（任何 Phase 都不能违反）

1. **桌面端零改动**：所有新规则只能加在 `@media (max-width: X)` 媒体查询内，或者新增独立 class（不修改现有 class 的桌面态属性）。改完后桌面端 (>1024px) 必须像没改一样。
2. **断点统一**：
   - `≤640` 手机
   - `≤1024` 平板 + 窄桌面
   - `1280` Conflicts 等部分页面用作"大平板/窄桌面切回桌面态"的边界
   - **不要新增其他随意断点**（如 720 / 980 已有的保留，新增请走 640 / 1024）
3. **`AppPageHeader` slot 规则不要重复实现**：已经在 `index.css` 全局区块定义好。新页面顶栏多按钮场景**只需在 icon-only 按钮上加 `class="icon-only"` 或 `data-icon-only` 属性**，其他文字按钮会自动 50% 等宽，搜索框 wrap 自动独占整行。
4. **Dialog 全屏规则**：
   - 简单 dialog 直接在 `<el-dialog class="mobile-full-dialog">` 加这个 class，全局规则会自动 ≤640 全屏
   - 已有自定义 dialog class（如 `.custom-preview-modal` / `.activity-detail-dialog`）走全局规则即可
   - **如果 dialog 自己用 `:deep(.el-dialog)` 写了 width/height，必须在自己 scoped 内补一份 ≤640 覆盖**（否则会被自己的高优先级规则吃掉，参考 `ActivityLogDetailDialog.vue`）
5. **Vue scoped style 不能穿透 slot**：slot 内的元素带父组件 data-v，AppPageHeader scoped 内的选择器选不到。这种规则要么用 `:deep()`，要么直接放全局 `index.css`。
6. **`v-app-loading` 只绑主内容区**：头部按钮永远可见，遮罩别盖住关闭/刷新按钮。这是 20 节就有的旧规则，移动端别破坏。
7. **`min-height` 是隐形地雷**：很多桌面端 dialog/section 写了 `min-height: 800px` 之类硬性值，移动端必须显式覆盖成 `min-height: 0`，否则会撑爆容器。Activity 详情 dialog 就栽过这个坑。
8. **`min-width: 0` 是 grid/flex 子项防溢出的标配**：长 trace-id / RJ 路径 / 邮箱地址等会撑爆 grid 列。配合 `word-break: break-all` 或 `overflow-wrap: anywhere` 使用。

### 21.3 关键文件锚点

- 全局基座：`@/frontend/src/index.css`（`Mobile Adaptation Foundation` 区块、`AppPageHeader slot 区移动端通用布局` 区块、Safe Area 适配）
- 视口 composable：`@/frontend/src/composables/useViewport.js`
- 全局头部：`@/frontend/src/components/common/AppPageHeader.vue`
- 主布局：`@/frontend/src/App.vue`（汉堡抽屉 + sidebar 抽屉态）
- 已适配的复杂页：`Conflicts.vue` / `ActivityHistory.vue` / `Settings.vue` + `SettingsWorkbench.vue` 是参考样板

### 21.4 继续推进时的建议节奏

1. 先在浏览器开发者工具切 414×896 / 768×1024 / 1440×900 三档实拍一遍**已完成 Phase**，回归确认桌面端没被改坏
2. 再按 2.4 → 2.5 → 3 → 4 → 5 顺序推进，每个 Phase 做完都让用户实拍一遍才进下一批
3. Library / Phase 4 工作台 Dialog 是最难的，预留半天到一天时间；其余页面参考已完成的 Conflicts / Activity 套路改 stack + padding 即可，单页通常 30 分钟内
4. **不要试图一次性改完所有页面**，AI 会丢上下文。一次只推一个 Phase，让用户验证再继续
