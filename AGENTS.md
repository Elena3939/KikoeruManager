# AGENTS.md

给后续 AI / 自动化代理的接手说明。目标是少踩坑、少回退、少串状态；这里不写项目百科，只保留仍然会影响改动判断的规则。

## 1. 项目基线

- 项目名统一用 `Prekikoeru`。不要把 `KikoeruTool_Elena` 或其他旧名混回新文案、新标题、新打包产物。
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
- 桌面包名统一为 `Prekikoeru.exe`。
- 图标必须来自仓库资源，不能依赖外部绝对路径。

## 4. 前端设计规则

- 不要交付 Element Plus 默认后台风。
- 样式优先级：`Tailwind CSS` -> 项目已有语义 class -> `Element Plus` 容器 / 基础交互能力 -> Lottie 动画增强。
- 图标只允许用 `lucide-vue-next`。不要混用多套图标库。
- 所有按钮、都要有交互动效：hover `translateY(-2px) scale(1.02)`，active `scale(0.96)`，图标轻旋转。
- 统一动画曲线：`all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)`。
- 按钮优先自定义渐变 / 弱边框 / 小阴影，不要直接交付默认按钮样式。
- 页面默认结构：顶部标题区、工具栏、筛选区、卡片主内容、展开详情区。
- 禁止用 Element Plus 默认表格当核心页面布局。
- 新做任务面板、工作台、预览、批量处理、详情抽屉时，默认对齐 `DownloadTaskWorkbenchDialog.vue`。
- 系统确认 / 输入 / 提醒统一走 `useSystemPrompt`，不要新增散落的 `ElMessageBox.*`。

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
- 已集成多库存、本地 + 群晖、搜索定位、文件管理、批量操作、删除过滤预审、RJ 字幕入口。
- 改样式前先读现有 class；不要退回默认 Element 风。

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

### 下载 / 上传与大文件

- 群晖上传核心在 `library_manager.py`，ASMR 增强下载上传在 `asmr_resource_service.py`。
- 禁止把整文件 `read()` 进内存再拼 multipart；必须保持分块流式上传。
- 本地复制入库也要分块，不要退回无进度的 `shutil.copy2`。
- 批量取消接口 `/api/tasks/batch-cancel-cleanup` 会取消任务并清理 `download_root`；改取消逻辑时同步考虑文件清理和历史语义。
- Synology 客户端按配置签名缓存，配置变化会自动重建客户端；改群晖配置后不需要重启服务。
- `local_download_ready` 只认数据库明确标志。只有任务 `completed` 才写 `True`，失败 / 异常都写 `False`。
- 工作台依赖字段：`download_files`、`upload_files`、`uploaded_files`、`progress_log`、`failure_reason`、`final_output_path`、`download_root`。

### 群晖 / 远程库存

- 远程搜索优先走群晖原生接口，不要偷偷退回本地递归。
- 根目录 `/` 搜索时按 share 拆分再汇总。
- RJ 字幕远程扫描递归时跳过 `subtitles`。
- 远程 `list / stat / create` 行为可能不完全一致，改 `relative_path`、`real_path`、标准化路径时要谨慎。
- 判断远程路径是否在库存范围内时，复用现有 `root / browse_root` 校验。
- 常见群晖错误码：`119`、`121`、`401`、`408`。
- 群晖通信相关错误统一抛 `SynologyError`，**不要**裸抛 `RuntimeError`。库存接口对 `SynologyError` 走 `WARNING` 不打堆栈；OTP 过期由前端库存页横幅引导用户重新登录，别在后端日志里刷红。

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

## 10. 当前优先级

1. 稳定 RJ 工作台“原始抓取 -> 人工筛选 -> 自动预匹配 -> 手动配对 -> 最终写入”整条链。
2. 清理任务中心、操作日志、字幕工作台之间的状态串台。
3. 统一库存页工具栏、批量条、右侧操作区的交互一致性。
4. 稳定下载 / 上传工作台与群晖大文件链路。
5. 继续补群晖 DSM 兼容细节，尤其远程 `subtitles` 目录处理。
6. 清理旧文案、乱码注释、历史品牌残留。

## 11. 最近改动同步（2026-05）

- 缺失作品“发售时间”排序在 `frontend/src/views/CircleCompletion.vue` 增强了日期解析：
  - 支持从带附加文本的日期里提取 `YYYY-MM-DD`（如带括号、曜日、说明文案）。
  - 支持宽松 `YYYY-MM` 解析，避免解析失败被当作 `0` 导致倒序沉底。
- 侧边栏版本号来源是 `frontend/src/App.vue` 的 `appVersion` 常量；发版改版本时要同步这里。
- 已发生一次误把 `frontend/src/assets/temp/` 临时图提交进仓库的情况；后续提交前必须重点检查临时目录与二进制资源是否误入变更集。
- 版本发布已使用 semver tag：`v1.0.10`；如果代码有补提，记得同步更新 tag 与展示版本，避免“标签版本”和“UI 版本”不一致。
