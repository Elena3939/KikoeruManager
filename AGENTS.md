# AGENTS.md

给后续 AI / 自动化代理的接手说明。这里只保留现在还活着、改动频率高、最容易踩坑的内容。目标不是“介绍项目”，而是让接手的人少踩坑、少回退、少串状态。

## 1. 项目定位

- 项目统一名称：`Prekikoeru`
- 这已经不是单一小工具，而是多工作台组合的桌面化产品
- 前端目标是产品级工作台体验，不是传统后台管理系统

### 主要技术栈

- 后端：`FastAPI`
- 前端：`Vue 3 + Vite + Element Plus + Tailwind CSS + lucide-vue-next`
- 动画：`Transition + Tailwind`、`auto-animate`
- 桌面版：`pystray + PyInstaller`

### 当前高频业务区

- 库存浏览 / 搜索 / 文件管理：主操作中台
- RJ 字幕工作台：完整抓取、筛选、配对、写入链路
- 任务中心：核心状态链路
- 操作审计 / 历史记录：行为追踪系统
- 社团补全工作台：索引、对比、下载、入库
- 下载 / 上传工作台：批量任务详情、流水线、状态恢复

### 发布规则

- tag 只能用标准 semver
- 正确：`v1.2.3`
- 错误：`v1.02`、`1.2.3`

## 2. 关键入口

### 后端核心

- API 总入口：`backend/app/api/routes.py`
- 配置模型：`backend/app/config/settings.py`
- 任务引擎：`backend/app/core/task_engine.py`
- 任务中心服务：`backend/app/core/task_center_service.py`
- 操作审计服务：`backend/app/core/activity_log_service.py`
- 库存管理：`backend/app/core/library_manager.py`
- RJ 字幕服务：`backend/app/core/rj_subtitle_service.py`
- 关联字幕补配：`backend/app/core/linked_subtitle_import_service.py`
- 社团补全：`backend/app/core/circle_completion_service.py`
- Kikoeru 去重 / 命中：`backend/app/core/kikoeru_duplicate_service.py`
- ASMR 下载 / 上传链路：`backend/app/core/asmr_resource_service.py`
- 冲突处理：`backend/app/core/conflict_resolution_service.py`

### 前端核心

- 主布局：`frontend/src/App.vue`
- 路由：`frontend/src/router/index.js`
- API 封装：`frontend/src/api/index.js`
- 库存页：`frontend/src/views/Library.vue`
- 仪表盘：`frontend/src/views/Dashboard.vue`
- 操作历史：`frontend/src/views/ActivityHistory.vue`
- 任务中心：`frontend/src/views/Tasks.vue`
- 问题作品：`frontend/src/views/Conflicts.vue`
- 社团补全：`frontend/src/views/CircleCompletion.vue`
- ASMR 同步：`frontend/src/views/ASMRSync.vue`
- 设置页：`frontend/src/views/Settings.vue`

### 前端工作台 / 弹窗基准

- 下载任务工作台：`frontend/src/components/download/DownloadTaskWorkbenchDialog.vue`
- 上传任务工作台：`frontend/src/components/upload/UploadTaskWorkbenchDialog.vue`
- 社团下载预览：`frontend/src/components/circle/CircleDownloadPreviewDialog.vue`
- 本地上传预览：`frontend/src/components/circle/CircleLocalUploadDialog.vue`
- 服务端上传预览：`frontend/src/components/common/ServerUploadPreviewDialog.vue`
- 操作历史详情：`frontend/src/components/activity/ActivityLogDetailDialog.vue`

### 新拆分入口

- 设置工作台宿主：`frontend/src/components/settings/SettingsWorkbench.vue`
- 设置分区面板：
  - `frontend/src/components/settings/LibraryInventoryPanel.vue`
  - `frontend/src/components/settings/StorageSettingsPanel.vue`
  - `frontend/src/components/settings/SynologyProfileCenter.vue`
- 字幕导入工作台状态拆分：
  - `frontend/src/composables/useSubtitleImportArchive.js`
  - `frontend/src/composables/useSubtitleImportFolder.js`
  - `frontend/src/composables/useSubtitleImportWorkbench.js`
- Lottie 通用组件：
  - `frontend/src/components/common/AppLoadingAnimation.vue`
  - `frontend/src/components/common/AppLottieIcon.vue`
  - `frontend/src/components/common/AppLottieSwitch.vue`

### 桌面 / 发布

- 托盘入口：`desktop_app.py`
- 后端启动：`backend/run.py`、`backend/start.bat`
- 前端启动：`frontend/start.bat`
- 一键启动：`start-all.bat`、`start-dev.bat`、`start-dev.ps1`
- 打包脚本：`build-release.bat`、`package.bat`、`backend/build.py`
- CI：`.github/workflows/ghcr.yml`

## 3. 硬规则

### 3.1 品牌统一

- 新改动统一使用 `Prekikoeru`
- 不要把旧名混回去：
  - `KikoeruTool_Elena`
  - 其他历史名
- 改品牌时必须一起看：
  - 页面标题
  - favicon
  - 托盘标题
  - exe 名称
  - FastAPI title / health 文案
  - README / 发布说明 / bat 输出文案

### 3.2 配置与敏感数据

- 仓库模板配置优先看：`backend/config/config.yaml`
- 本地真实运行配置常见位置：
  - 桌面版：`data/config/config.yaml`
  - Docker：`/app/config/config.yaml`
- 用户说“改配置文件”时，默认改仓库模板，不要直接碰用户私有运行配置
- 不要提交真实密码、Token、代理、私服地址、群晖账号信息
- 默认把这些当敏感或运行态产物：
  - `.env`
  - `backend/data/`
  - 本地数据库
  - 缓存目录
  - `.codex-backups/`

### 3.3 桌面端

- 当前稳定方案还是 `pystray` 原生托盘菜单
- 没明确要求时，不要重写成自绘菜单 / Win32 假菜单
- 桌面包名统一为 `Prekikoeru.exe`
- 图标必须来自仓库资源，不能依赖外部绝对路径

### 3.4 前端设计硬约束

- 技术实现必须使用 `Vue 3`
- 设计语言必须对齐 React 产品风格：`shadcn / Radix / Vercel`
- 明确不接受 Element Plus 默认后台风作为最终 UI
- 所有页面、弹窗、工作台都必须落在统一工作台视觉体系内

### 3.5 前端实现硬约束

- 样式优先级：
  1. `Tailwind CSS`
  2. 项目已有语义 class
  3. `Element Plus` 仅用于容器和基础交互能力
- 图标只允许使用 `lucide-vue-next`
- 禁止事项：
  - 用 Element Plus 默认表格当核心页面布局
  - 用默认按钮样式直接交付
  - 同一页面混用多种设计语言
  - 混用多套图标库
  - 为单页临时引入新 UI 框架

### 3.6 页面结构硬约束

- 页面默认拆成这些层级：
  - 顶部标题区：标题 + 简述
  - 工具栏：摘要 + 主操作
  - 筛选区：pill / tabs / segmented
  - 内容区：卡片为主，不用裸表格当主结构
  - 详情区：展开后展示
- 必须使用 `script setup`
- 展示组件与业务逻辑要解耦
- 不要把所有逻辑和 UI 堆进一个超大 `.vue`

### 3.7 弹窗 / 工作台视觉基准

- 基准实现：`frontend/src/components/download/DownloadTaskWorkbenchDialog.vue`
- 新做“任务面板 / 工作台 / 预览 / 批量处理 / 详情抽屉”时默认对齐这套语言
- 系统内提醒 / 确认 / 输入弹窗统一走：
  - 组件：`frontend/src/components/system/SystemPromptDialog.vue`
  - 宿主：`frontend/src/components/system/SystemPromptHost.vue`
  - 服务：`frontend/src/composables/useSystemPrompt.js`
- 成功 / 错误状态图标统一走：
  - `frontend/src/components/system/SuccessMessageIcon.vue`
  - `frontend/src/components/system/ErrorMessageIcon.vue`
- 禁止新增散落的 `ElMessageBox.*` 调用；默认只允许通过统一服务层调用
- 视觉口径固定：
  - 轻玻璃质感
  - 弱描边
  - 白底内容卡
  - 胶囊 badge / meta
  - 柔和动效
- 业务提醒优先复用这些能力，不要在页面里自己拼 HTML 弹窗：
  - `tone`
  - `badge`
  - `currentLabel/currentValue`
  - `details`
  - `prompt`
- 如果必须保留 Element 原生弹窗，必须先有明确技术理由，不然视为不符合前端约束
- 默认结构：
  - 顶部标题区
  - 首屏工具栏：左摘要、右动作
  - 胶囊筛选区
  - 卡片列表主内容
  - 卡片展开后的细节 / 文件流水线 / 日志
- 默认视觉：
  - 圆角
  - 浅灰背景分层
  - 弱边框
  - 白底内容卡
  - 轻量状态底色 / 边框提示
  - 胶囊按钮 / 状态 pill / meta pill
- 优先延续现有 class 语义：
  - `toolbar`
  - `summary`
  - `actions`
  - `filter-pill`
  - `task-card`
  - `meta-pill`
  - `detail-grid`
  - `log-list`

## 4. 当前真实业务链路

### 4.1 库存页是主工作台，不是普通列表页

- 入口：`frontend/src/views/Library.vue`
- 当前已集成：
  - 多库存切换
  - 本地库存 + 群晖远程库存
  - 当前页 / 当前目录作用域切换
  - 文件名 / RJ 号搜索
  - 结果定位回原目录
  - 行内打开 / 直接打开 / 重命名 / API 重命名 / 删除
  - 文件管理弹窗
  - 批量操作
  - 删除过滤预审
  - RJ 字幕工作台入口
- 库存页 UI 已经定制过，别退回默认 Element 风格
- 顶部工具栏、批量条、右侧操作按钮都已经有固定节奏和颜色语义，改样式前先读现有 class

### 4.2 RJ 字幕工作台是完整流程，不是单按钮

- 主入口在库存页，不在设置页
- 当前实际入口：
  - `当前页抓字幕`
  - `当前目录抓字幕`
  - 行内 `识别抓字幕`
  - 选中后 `批量抓字幕`
  - `字幕任务面板`
- 完整流程：
  1. 扫描 RJ 目录
  2. 检查已有字幕
  3. 搜字幕来源
  4. 下载原始字幕
  5. 去广告 / 繁转简 / 内容去重
  6. 自动匹配音频
  7. 人工筛选与手动配对
  8. 最终写入 `subtitles/`
- 核心原则：
  - 不自动扫全盘
  - 不自动抢焦点
  - 不要求用户手填大量路径
  - 先抓原始字幕，再筛选 / 配对，再写入
  - 抓取阶段和最终落盘阶段必须分开
- 已有字幕目录不是简单失败项，要保留在工作台上下文里供继续处理
- 当前已覆盖：
  - 本地目录
  - 群晖远程目录
  - 远程 `subtitles` 写回
  - Kikoeru 已有字幕检查
  - metadata 匹配开关
  - 命名策略
  - 字幕过滤规则

### 4.3 任务系统已经是主链路

- 核心：`backend/app/core/task_engine.py`
- 当前任务类型至少包括：
  - `AUTO_PROCESS`
  - `PROCESS_EXISTING_FOLDER`
  - `ASMR_SYNC_DOWNLOAD`
  - `RJ_SUBTITLE_FETCH`
  - 社团补全相关批量任务
  - 下载 / 上传工作台相关任务
- 任务状态除了普通 `pending / processing / completed / failed`，还有：
  - `paused`
  - `waiting_manual`
  - `waiting_retry`
- 任务对象统一业务上下文：
  - `task_domain`
  - `task_kind`
  - `session_id`
  - `source_page`
  - `source_action`
  - `source_label`
  - `business_key`
- 新任务不要只顾后端能跑，还要补齐：
  - 任务中心展示语义
  - 来源页 / 来源动作
  - 历史记录归属
  - 错误态 / 重试态 / 等待态
- RJ 字幕任务有自己的进度日志、下载明细、人工匹配等待态，不要硬塞回通用粗粒度进度条

### 4.4 操作审计 / 历史记录已经成体系

- 核心：`backend/app/core/activity_log_service.py`
- 前端入口：`frontend/src/views/ActivityHistory.vue`
- `routes.py` 已经做树形聚合，不是平铺流水
- 当前已收敛的记录类型包括：
  - 字幕抓取 + 重跑
  - 字幕配对
  - 批量任务
  - 删除过滤预审 / 重试
  - 字幕导入
  - API 重命名 / 批量重命名
  - 社团补全索引 / 下载
  - 下载 / 上传工作台任务详情
- 改任务流时除了“能跑”，还要考虑：
  - 操作记录有没有落
  - 同一业务会不会被拆成不可读碎日志
  - 子任务是不是应该挂到父记录下

#### 当前硬口径

- `subtitle_import` 只有真正执行导入的 `archive_import / folder_import` 才能挂到“解压入库”树下
- `pending_execute` 只是预检 / 进入工作台，不算真实执行，不能进历史树和顶层列表
- 同一批量解压下的子节点按这些维度去重：
  - `relation`
  - `task_id`
  - `source_path`
  - `rjcode`
  - `action`
- 历史页残留的 `waiting + task_finished` 文案统一展示成 `等待处理`
- 手动字幕配对完成后：
  - 如果 `manual_complete` 真正触发最终导入，路由层要补写真实 `subtitle_import` 完成日志
  - 只做配对、不落盘时，不能伪造“字幕补配完成”

### 4.5 删除过滤已经是预审制

- 正确链路：
  1. 发起删除过滤预审
  2. 后台任务跑扫描 / 预览
  3. 用户审阅结果
  4. 确认后才真正删除
- 删除成功后应该直接更新当前树和数量
- 不要删完再强行重新跑一整轮预审
- 相关记录必须进入操作审计

### 4.6 问题作品 / 冲突处理仍然重要

- 顶层动作收敛为：
  - `KEEP_NEW`
  - `SKIP`
  - `MERGE`
- `KEEP_OLD` 只能做兼容别名，不要继续暴露到新 UI
- 解压失败 / 处理失败会落到问题作品列表，不要只停留在任务失败
- 任务引擎已有补记逻辑：
  - `EXTRACT_FAILED`
  - `PROCESS_FAILED`
- 失败项重试成功后，要同步清理 / 标记恢复，别留下脏状态
- 重复作品 / 正在处理中 / 需要人工判断这类状态，必须落 `waiting_manual`
- 不要把重复冲突写成 `completed / success`

#### 查重额外注意

- `classifier._check_existing()` 必须排除这些运行态目录：
  - `待处理`
  - `_conflicts`
  - `temp`
  - `tmp`
- 这些路径只代表临时态 / 问题态，不能用于判定“服务器已存在”或“库存重复”
- `LibrarySnapshot` 命中这些路径时，现实现会顺手清理脏快照，别把这段清洗逻辑删回去

### 4.7 ASMR 同步下载链路还在

- 相关 API 还在 `routes.py`
- 相关任务还在 `task_engine.py`
- 这条链路不是废代码，仍包含：
  - 预览版本
  - 下载文件
  - 字幕同步
  - 重命名
  - 分类
  - 移动字幕源目录到 `Finished`
- 改 RJ 或任务系统时不要误伤

### 4.8 社团补全是独立工作台

- 前端入口：`frontend/src/views/CircleCompletion.vue`
- 后端核心：`backend/app/core/circle_completion_service.py`
- Kikoeru 相关：`backend/app/core/kikoeru_duplicate_service.py`
- 当前链路包含：
  - 社团索引建立 / 刷新
  - Kikoeru 服务器已拥有判定
  - DLsite 关联链聚合
  - asmr.one 资源预览
  - 批量增强下载
  - 下载完成后按社团名入库

#### 当前实现口径

- 服务器拥有判定是两段式：
  1. 按社团关键词走 Kikoeru 搜索分页
  2. 再对 canonical RJ 走 `check_duplicate_with_linkages`
- Kikoeru 没有稳定社团搜索 API 时，直接走站内真实搜索数据源分页，不要拍脑袋猜接口
- 下载落盘原则：
  - 先下到临时目录
  - 作品目录走 API 命名
  - 最终按 `目标库存 / 可选前缀目录 / 社团名 / API 命名后的作品目录` 入库
- 预览弹窗里的“库存内前缀目录”是下拉缓存，不是自由输入
- 空值语义是“直接按社团名入库”
- 下载工作台有自己的状态缓存和后台悬浮卡，不要删恢复逻辑
- 下载工作台摘要进度条当前是：
  -  `frontend/src/assets/anime/progress bar.lottie`
  - 下载 / 上传图标优先复用 `frontend/src/assets/anime/download-icon-clean.json`、`frontend/src/assets/anime/Uploading to cloud.lottie`
- 如果后续有人改下载工作台进度表现，不要把它退回普通纯色条，也不要让 `.lottie` 独自承担进度宽度计算
- 社团补全索引任务支持取消；新增长循环时记得补 `cancel_callback`

#### 当前依赖细节

- 建索引时优先按 `circle_name_normalized` 复用已有 `circle_catalogs.circle_id`
- 如果种子作品没有 `maker_id`，会回退补查多个 seed metadata 反推
- DLsite 抓取失败原因会写进任务详情和操作日志 detail，排障先看 `dlsite_failure_reason`
- `circle_works` 当前依赖这些字段：
  - `asmr_available_rjcode`
  - `kikoeru_found_rjcodes`
  - `kikoeru_subtitle_rjcodes`
- 前端“来源对比”和历史里的“社团源对比”卡片都吃这些字段，改接口要保持兼容
- DLsite 关联链不能只信 `language_editions`，要递归翻译本 / 子作品 / parent-child
- 系统内涉及 DL 关联作品的地方统一复用 `dlsite_service.get_linked_works()`
- Kikoeru 命中口径：
  - 任一关联 RJ 命中就算 `服务器已有`
  - 前端优先显示真实命中的 `matched_rjcode`
- `circle_completion_service` 刷新结果当前前端依赖：
  - `server_match_rjcodes`
  - `server_match_primary_rjcode`
  - `subtitle_present`
  - `change_flags`
- 索引结果现在不只是计数，后端还会给：
  - `preferred_variant`
  - `source_compare.kikoeru`
  - `source_compare.dlsite`
  - `source_compare.asmr_one`
- 批量下载入口优先走 `asmr_available_rjcode`，不要默认拿 `display_rjcode`
- 社团补全内部生成增强下载计划时会关闭通用 ASMR 预览日志，避免刷无意义顶层历史
- 最近索引列表按 `circle_name_normalized / circle_id` 去重；同名重复通常先查数据库脏数据

### 4.9 下载 / 上传链路与大文件处理

- 群晖上传核心：`backend/app/core/library_manager.py`
- ASMR 增强下载上传链路：`backend/app/core/asmr_resource_service.py`
- 不能再把整文件 `read()` 进内存再拼 multipart
- 必须保持分块流式上传
- 本地复制入库同样走分块，不要退回 `shutil.copy2` 这种无进度粗放写法

#### 当前工作台依赖的运行态字段

- `download_files`
- `upload_files`
- `uploaded_files`
- `progress_log`
- `failure_reason`
- `final_output_path`

#### 改下载 / 上传链路时同步检查

- `/api/asmr-sync/status`
- `frontend/src/views/CircleCompletion.vue`
- `frontend/src/views/ActivityHistory.vue`
- `frontend/src/components/download/DownloadTaskWorkbenchDialog.vue`
- `frontend/src/components/upload/UploadTaskWorkbenchDialog.vue`
- `frontend/src/components/common/ServerUploadPreviewDialog.vue`
- `frontend/src/components/circle/CircleLocalUploadDialog.vue`

## 5. 群晖 / 远程库存注意点

- 远程搜索必须优先走群晖原生接口，不要偷偷退回本地递归
- 根目录 `/` 搜索时，要按 share 拆分再汇总
- RJ 字幕远程扫描和写回已经单独处理过：
  - 递归时跳过 `subtitles`
  - 远程 `list / stat / create` 行为可能不完全一致
  - `relative_path`、`real_path`、标准化路径要格外小心
- 判断远程路径是否在库存范围内时，复用现有 `root / browse_root` 校验
- 常见群晖错误码优先关注：
  - `119`
  - `121`
  - `401`
  - `408`

## 6. 用户需求默认理解

### 用户说“改配置文件”

- 默认改仓库模板，不改本地真实敏感配置

### 用户说“RJ 字幕有问题”

- 优先检查：
  1. `frontend/src/views/Library.vue`
  2. `frontend/src/api/index.js`
  3. `backend/app/api/routes.py`
  4. `backend/app/core/task_engine.py`
  5. `backend/app/core/rj_subtitle_service.py`
  6. `backend/app/core/linked_subtitle_import_service.py`
  7. `backend/app/core/library_manager.py`

### 用户说“任务中心 / 历史记录不对”

- 优先检查：
  1. `backend/app/core/task_center_service.py`
  2. `backend/app/core/activity_log_service.py`
  3. `backend/app/api/routes.py`
  4. `frontend/src/views/Dashboard.vue`
  5. `frontend/src/views/ActivityHistory.vue`
  6. `frontend/src/views/Tasks.vue`
  7. `frontend/src/views/Library.vue`

### 用户说“社团补全任务看不懂 / 历史记录不完整”

- 先看：
  1. `ActivityHistory.vue` 里的社团索引概览卡片有没有数据
  2. `routes.py` 是否把 `circle_completion` 的 `task_finished / task_finished_incomplete` 合并到索引父记录
  3. `Tasks.vue` 是否展示了 `dlsite_failure_reason`
  4. `activity_log_service.py` 是否把 `CIRCLE_COMPLETION_INDEX / CIRCLE_COMPLETION_DOWNLOAD_BATCH` 正确映射到 `circle_completion`

### 用户说“下载 / 上传工作台不对”

- 优先检查：
  1. `backend/app/core/asmr_resource_service.py`
  2. `backend/app/core/library_manager.py`
  3. `backend/app/api/routes.py`
  4. `frontend/src/components/download/DownloadTaskWorkbenchDialog.vue`
  5. `frontend/src/components/upload/UploadTaskWorkbenchDialog.vue`
  6. `frontend/src/components/common/ServerUploadPreviewDialog.vue`
  7. `frontend/src/components/circle/CircleLocalUploadDialog.vue`
  8. `frontend/src/views/ActivityHistory.vue`
  9. `frontend/src/components/download/DownloadTaskWorkbenchDialog.vue` 的摘进度条是不是这个动画 `progress bar.lottie`

### 用户说“推送仓库”

- 先检查：
  - `git status`
  - 有没有混入 `.env`、本地数据库、用户配置、缓存目录
  - tag 是否符合 semver

### 用户说“为什么 Actions 失败”

- 先看 tag 是否为 `vX.Y.Z`
- 再看 `.github/workflows/ghcr.yml` 的触发与 semver 解析

## 7. 实现偏好

- 优先复用现有服务和任务模型，不要在路由里堆业务
- 库存树、远程路径标准化、RJ 扫描逻辑都有现成实现，别重复造轮子
- 新增或扩展任务时，顺手把这些一起补齐：
  - 任务中心上下文
  - 操作日志
  - 前端状态展示
  - 错误态 / 重试态 / 等待态
- 前端不是补个按钮就完事，要确认：
  - loading
  - 空态
  - 禁用态
  - 完成态
  - 错误态
  - 重试态
  - 人机交互
  都闭环
- 不要把“能跑”当“可维护”，这个项目已经进入多工作台状态同步复杂期

## 8. 一次性脚本 / 脏数据修复

### 历史重复社团索引清理

- 脚本：`backend/scripts/merge_duplicate_circle_catalogs.py`
- 默认预览：
  - `py -3 backend/scripts/merge_duplicate_circle_catalogs.py`
- 真正写入：
  - `py -3 backend/scripts/merge_duplicate_circle_catalogs.py --apply`
- 作用：
  - 按 `circle_name_normalized` 找重复 `circle_catalogs`
  - 备份 `backend/data/cache.db`
  - 合并 `circle_works`
  - 删除重复 catalog
- 如果 `circle_works` 再加字段，记得同步维护 merge 逻辑

### 操作历史脏数据清理

- 脚本：`backend/scripts/cleanup_dirty_activity_logs.py`
- 默认预览，真正写入要加 `--apply`
- 作用：
  - 删除旧的 `subtitle_import / pending_execute` 噪音记录
  - 把旧的“重复作品但状态写成 success”修正为等待人工处理口径
  - 清理由 `待处理 / _conflicts / temp / tmp` 误判出的脏数据
- 这是历史修复脚本，不是日常流程

## 9. 最低验证要求

### 改前端后

- 至少执行：`npm run build`
- 重点看：
  - 页面标题 / favicon
  - 库存页是否正常渲染
  - 搜索 / 定位是否还能用
  - RJ 字幕弹窗能否打开
  - 字幕任务面板状态是否正常
  - Dashboard / ActivityHistory 是否没炸

### 改后端后

- 至少执行：
  - `py -3 -m py_compile backend/app/api/routes.py backend/app/core/task_engine.py backend/app/core/rj_subtitle_service.py backend/app/core/task_center_service.py backend/app/core/activity_log_service.py`
- 重点看：
  - 配置加载
  - 库存接口没被误伤
  - RJ 接口还能创建任务
  - 任务状态查询还能返回
  - 操作日志列表还能正常聚合返回

### 改社团补全后

- 后端再补：
  - `py -3 -m py_compile backend/app/core/circle_completion_service.py backend/app/core/asmr_resource_service.py backend/app/models/database.py`
- 前端至少执行：`npm run build`
- 重点看：
  - 最近索引列表是否按社团去重
  - 缺失作品卡片点击整卡选择是否正常
  - “来源对比”标签页分页是否正常
  - 预览下载是否仍能拿到正确 `resolved_rjcode`
  - `ActivityHistory.vue` 的社团索引概览抽屉是否正常渲染
  - 历史详情抽屉拖拽宽度后没有事件泄漏

### 改下载 / 上传链路后

- 至少执行：`npm run build`
- 如果改了后端，再补对应 `py_compile`
- 重点看：
  - 大文件上传不会爆内存
  - 进度条 / 进度日志正常更新
  - 刷新页面后工作台状态可恢复
  - 历史记录能看到任务详情但不会刷一堆噪音顶层日志

### 改桌面版后

- 至少检查：
  - 托盘图标显示
  - 菜单正常
  - 能打开 Web
  - 能退出
  - 打包仍可用

### 改发布流程后

- 至少检查：
  - `.github/workflows/ghcr.yml`
  - 版本 tag 仍符合 semver

## 10. 当前建议优先级

1. 稳定 RJ 工作台“原始抓取 -> 人工筛选 -> 自动预匹配 -> 手动配对 -> 最终写入”整条链
2. 继续清理任务中心、操作日志、字幕工作台之间的状态串台
3. 继续统一库存页工具栏、批量条、右侧操作区的交互一致性
4. 稳定下载 / 上传工作台与群晖大文件链路
5. 继续补群晖 DSM 兼容细节，尤其是远程 `subtitles` 目录处理
6. 清理旧文案、乱码注释、历史品牌残留
