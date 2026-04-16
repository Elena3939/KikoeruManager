# AGENTS.md

给后续 AI / 自动化代理的接手说明。只写现在还活着、改动频率高、最容易踩坑的东西。

## 1. 项目现状

- 项目统一名称：`Prekikoeru`

- 项目定位：
  - 不再是单一工具，而是多工作台组合的桌面化产品
  - 前端体验目标为“产品级 UI”，而非传统后台管理系统

- 主要技术栈：
  - 后端：FastAPI
  - 前端：Vue 3 + Vite + Element Plus + Tailwind CSS + lucide-vue-next
  - 动画:auto-animate,Transition + Tailwind
  - 桌面版：`pystray` + PyInstaller

- 前端设计原则（全局约束）：
  - 技术实现：Vue
  - 设计语言：对齐 React 产品风格（shadcn / Vercel）
  - 默认不接受 Element Plus 原生后台风格作为最终 UI
  - 所有页面需符合统一工作台视觉体系
  - 动画效果优先用Transition + Tailwind或者auto-animate

- 当前主干工作不只是“解压整理”，已经扩展成 4 个高频区：
  - 库存浏览 / 搜索 / 文件管理（主操作中台）
  - RJ 字幕工作台（完整处理流程）
  - 任务中心（核心状态链路）
  - 操作审计 / 历史记录（行为追踪系统）

- 发布标签仍然只能用标准 semver：
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
- 冲突处理：`backend/app/core/conflict_resolution_service.py`

### 前端核心

- 主布局：`frontend/src/App.vue`
- 路由：`frontend/src/router/index.js`
- API 封装：`frontend/src/api/index.js`
- 库存页：`frontend/src/views/Library.vue`
- 仪表盘：`frontend/src/views/Dashboard.vue`
- 操作历史：`frontend/src/views/ActivityHistory.vue`
- 问题作品：`frontend/src/views/Conflicts.vue`
- 设置页：`frontend/src/views/Settings.vue`

### 桌面 / 发布

- 托盘入口：`desktop_app.py`
- 打包脚本：`build-release.bat`、`package.bat`、`backend/build.py`
- CI：`.github/workflows/ghcr.yml`

## 3. 硬规则

### 品牌统一

- 新改动统一使用 `Prekikoeru`
- 不要把旧名混回去：
  - `KikoeruTool_Elena`
  - 其他历史名
- 以下位置改品牌时必须一起看：
  - 页面标题
  - favicon
  - 托盘标题
  - exe 名称
  - FastAPI title / health 文案
  - 发布说明 / README / bat 脚本输出文案

### 配置安全

- 仓库模板配置优先看：`backend/config/config.yaml`
- 本地真实运行配置常见位置：
  - 桌面版：`data/config/config.yaml`
  - Docker：`/app/config/config.yaml`
- 用户说“改配置文件”时，默认改仓库模板，不要直接碰用户私有运行配置
- 不要提交真实密码、Token、代理地址、私服地址、群晖账号信息
- `.env`、`backend/data/`、本地数据库、缓存目录先默认视为敏感或运行态产物

### 桌面端

- 当前稳定方案还是 `pystray` 原生托盘菜单
- 没明确要求时，不要重写成自绘菜单 / Win32 假菜单
- 桌面包名统一为 `Prekikoeru.exe`
- 图标必须来自仓库资源，不能依赖外部绝对路径

## 4. 当前真实高频功能

### 4.1 库存页已经是主工作台

- 入口：`frontend/src/views/Library.vue`
- 这里已经不只是“列表页”，而是整个高频操作中台
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
- 库存页 UI 已做过一轮定制，别随手退回默认 Element 样式
- 顶部工具栏、批量条、右侧操作按钮已经有自己的节奏和颜色语义，改样式先通读现有 class

### 4.2 RJ 字幕工作台已经是“完整流程”，不是单按钮

- 主入口都在库存页，不在设置页
- 当前实际入口：
  - `当前页抓字幕` / `当前目录抓字幕`
  - 行内 `识别抓字幕`
  - 选中后 `批量抓字幕`
  - `字幕任务面板`
- 这套功能已经不是单纯下载字幕，而是完整工作台：
  1. 扫描 RJ 目录
  2. 检查已有字幕
  3. 搜字幕来源
  4. 下载原始字幕
  5. 去广告 / 繁转简 / 内容去重
  6. 自动匹配音频
  7. 进入人工筛选与手动配对
  8. 最终写入 `subtitles/`
- 当前核心原则：
  - 不自动扫全盘
  - 不自动抢焦点
  - 不要求用户手填一堆路径
  - 先抓原始字幕，再筛选和配对，再写入
  - “抓取阶段”和“最终落盘阶段”必须分开
- 已有字幕目录不是简单失败项：
  - 会保留在工作台上下文里，方便继续检查和人工补配
- RJ 工作台现在已经覆盖：
  - 本地目录
  - 群晖远程目录
  - 远程 `subtitles` 写回
  - Kikoeru 已有字幕检查
  - metadata 匹配开关
  - 命名策略
  - 字幕过滤规则

### 4.3 任务系统不是附属品，已经是主链路

- 核心：`backend/app/core/task_engine.py`
- 现有任务类型至少包括：
  - `AUTO_PROCESS`
  - `PROCESS_EXISTING_FOLDER`
  - `ASMR_SYNC_DOWNLOAD`
  - `RJ_SUBTITLE_FETCH`
- 任务状态除了普通 `pending/processing/completed/failed`，还有：
  - `paused`
  - `waiting_manual`
  - `waiting_retry`
- 现在任务对象已经带统一业务上下文：
  - `task_domain`
  - `task_kind`
  - `session_id`
  - `source_page`
  - `source_action`
  - `source_label`
  - `business_key`
- 这意味着：
  - 新任务不要只顾后端能跑，要补齐任务中心展示语义
  - 前端新入口创建任务时，要想清楚来源页和来源动作
- RJ 字幕任务有自己的进度日志、下载明细、人工匹配等待态，不要把它硬塞回通用粗粒度进度条模型

### 4.4 操作审计 / 历史记录已经成体系

- 核心：`backend/app/core/activity_log_service.py`
- 前端入口：`frontend/src/views/ActivityHistory.vue`
- `routes.py` 已经对日志做了树形聚合，不再是平铺流水：
  - 字幕抓取 + 重跑
  - 字幕配对
  - 批量任务
  - 删除过滤预审 / 重试
  - 字幕导入
  - API 重命名 / 批量重命名
- 所以以后改任务流时，不只是“功能能跑”就完了，还要考虑：
  - 操作记录有没有落
  - 同一业务会不会被拆成一堆不可读日志
  - 子任务是否应该挂到父记录下
- 最近这轮针对“解压入库 / 字幕补配”又加了几条硬口径：
  - `subtitle_import` 只有真正执行导入的 `archive_import / folder_import` 才允许挂到“解压入库”树下
  - `pending_execute` 只是预检 / 进入工作台，不算真实执行，不能出现在历史树和顶层列表里
  - 同一批量解压下的子节点会按 `relation / task_id / source_path / rjcode / action` 去重，防止一个 RJ 被重复挂 3-4 次
  - 历史页里残留的 `waiting + task_finished` 文案统一展示成 `等待处理`，不要再回退成 `等待 · task_finished`
- 手动字幕配对完成后，如果 `manual_complete` 实际触发了最终导入，路由层还要补写一条真正的 `subtitle_import` 完成日志；只做了配对、不落盘，不应该伪造“字幕补配完成”

### 4.5 删除过滤已经是“预审制”

- 正确体验不是点完直接删
- 正确链路：
  1. 发起删除过滤预审
  2. 后台任务跑扫描 / 预览
  3. 用户审阅结果
  4. 确认后才真正删除
- 删除成功后应该直接更新当前树和数量
- 不要删完再强行重新跑一整轮预审
- 相关记录会进操作审计，别绕开

### 4.6 问题作品 / 冲突处理仍然重要

- 顶层动作继续收敛为：
  - `KEEP_NEW`
  - `SKIP`
  - `MERGE`
- `KEEP_OLD` 只能当兼容别名，别继续往新 UI 暴露
- 解压失败 / 处理失败现在会落到问题作品列表，不要只停留在任务失败
- 任务引擎里已经有把失败任务补记为问题作品的逻辑：
  - `EXTRACT_FAILED`
  - `PROCESS_FAILED`
- 失败项重试成功后，要注意同步清理 / 标记恢复，不要留下脏状态
- 最近对重复作品状态口径做了收紧：
  - `重复作品 / 正在处理中 / 需要人工判断` 这类任务状态应落 `waiting_manual`
  - 不要再把重复冲突写成 `completed/success`，否则历史记录会被误读成“正常入库完成”
- `classifier._check_existing()` 现在必须排除运行态目录：
  - `待处理`
  - `_conflicts`
  - `temp`
  - `tmp`
  这些路径只代表临时态 / 问题态，不能拿来判定“服务器已经存在”或“库存重复”
- 如果 `LibrarySnapshot` 里命中这些临时路径，当前实现会顺手清掉脏快照；以后改查重时别把这个清洗逻辑删回去

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
- 改 RJ 或任务系统时，别误伤这条链

### 4.8 社团补全现在是独立工作台

- 前端入口：`frontend/src/views/CircleCompletion.vue`
- 后端核心：`backend/app/core/circle_completion_service.py`
- Kikoeru 相关：`backend/app/core/kikoeru_duplicate_service.py`
- 这条链路现在不是简单列表页，已经包含：
  - 社团索引建立 / 刷新
  - Kikoeru 服务器已拥有判定
  - DLsite 关联链聚合
  - asmr.one 资源预览
  - 批量增强下载
  - 下载完成后按社团名入库
- 当前服务器拥有判定是两段式：
  1. 先按社团关键词走 Kikoeru 搜索分页
  2. 再对聚合后的 canonical RJ 走 `check_duplicate_with_linkages`
- Kikoeru 没有稳定社团搜索 API 时，当前实现直接走站内真实搜索数据源分页，不要再退回拍脑袋猜接口
- 社团补全下载的当前落盘原则：
  - 先下到临时目录
  - 作品目录走 API 命名
  - 最终按 `目标库存 / 可选前缀目录 / 社团名 / API命名后的作品目录` 入库
- 预览弹窗里的“库存内前缀目录”现在是下拉缓存，不是自由输入；空值语义是“直接按社团名入库”
- 下载工作台有自己的一套状态缓存和后台悬浮卡：
  - 前端本地缓存 key 在 `CircleCompletion.vue`
  - 不要随手删掉恢复逻辑，否则刷新页面后用户看不到还在跑的批量下载
- 社团补全索引任务支持取消：
  - 前端按钮在 `CircleCompletion.vue`
  - 后端取消检查在 `circle_completion_service.py`
  - 新增长循环时记得补 `cancel_callback`
- 社团补全相关操作日志已经单独收敛：
  - 不要再写 `view_built` 这种纯视图噪音日志
  - 主记录应聚焦“创建索引检索成功 / 创建下载任务 / 下载完成”
  - 同一 RJ 的下载文件不要平铺成一堆顶层记录，应挂到父记录或任务详情里
- 最近这轮改动后，社团索引还额外依赖这些实现细节：
  - 建索引时优先按 `circle_name_normalized` 复用已有 `circle_catalogs.circle_id`，不要因为同名社团重复生成新 catalog
  - 如果种子作品没有 `maker_id`，会回退补查多个 seed 作品 metadata 来反推 `maker_id`
  - DLsite 抓取失败原因现在会写进任务详情和操作日志 detail，排障先看 `dlsite_failure_reason`
  - `circle_works` 现在新增并依赖：
    - `asmr_available_rjcode`
    - `kikoeru_found_rjcodes`
    - `kikoeru_subtitle_rjcodes`
  - 前端“来源对比”标签页和操作历史里的“社团源对比”卡片都吃这些字段，改接口时要保持兼容
- DLsite 关联链现在不能只信 `language_editions`：
  - 要递归翻译本 / 子作品 / parent-child 关系，像 `RJ01021152 -> RJ01092544` 这种同语言不同译者也必须进 canonical 链
  - 系统内和 DL 关联作品相关的地方要统一复用 `dlsite_service.get_linked_works()`，不要各写一套
- Kikoeru 命中口径已经改掉：
  - 只要同原作任一关联 RJ 命中，就算 `服务器已有`
  - 前端主卡片和刷新结果优先显示真实命中的 `matched_rjcode`
  - 不要再要求“当前优先 RJ 精确命中”才算服务器拥有
- `circle_completion_service` 刷新结果返回模型已经偏业务语义，不再给前端直接喂“服务器命中变体 / 字幕状态变体”这种调试字段
  - 当前前端依赖：
    - `server_match_rjcodes`
    - `server_match_primary_rjcode`
    - `subtitle_present`
    - `change_flags`
- `ActivityHistory.vue` 的社团刷新抽屉现在固定按“有更新优先”排序，且有：
  - `全部 / 仅有更新 / 仅无变化`
  - 每页 10 条
  - 有更新卡片右上角 `NEW`
  如果后端改返回结构，别忘了把这些筛选和排序一起维护
- 索引结果现在不只是计数：
  - 后端会给每个作品算 `preferred_variant`
  - 同时产出 `source_compare.kikoeru / dlsite / asmr_one`
  - Kikoeru、DLsite、asmr.one 三列对比要能区分原作、简体、繁体、字幕提示等标签
- 批量下载入口现在优先走 `asmr_available_rjcode`
  - 不要再默认拿 `display_rjcode` 直接生成下载计划
  - 社团补全内部生成增强下载计划时会关闭通用 ASMR 预览日志，避免操作历史里刷出无意义顶层记录
- 最近索引列表现在会按 `circle_name_normalized / circle_id` 去重
  - 如果看到同名社团重复，多半是旧缓存脏数据，需要先处理数据库而不是改前端

### 4.9 大文件上传现在必须走流式

- 群晖上传核心在 `backend/app/core/library_manager.py`
- ASMR 增强下载上传链路在 `backend/app/core/asmr_resource_service.py`
- 当前已经修过一次“大 wav 上传把内存打爆”：
  - 不能再把整文件 `read()` 到内存再拼 multipart
  - 必须保持分块流式上传
  - 本地复制入库同样要走分块，不要退回 `shutil.copy2` 这种无进度粗放写法
- 下载工作台现在依赖这些运行态字段：
  - `download_files`
  - `upload_files`
  - `uploaded_files`
  - `progress_log`
  - `failure_reason`
  - `final_output_path`
- 如果改了下载 / 上传链路，记得同步检查：
  - `/api/asmr-sync/status`
  - `frontend/src/views/CircleCompletion.vue`
  - `frontend/src/views/ActivityHistory.vue`

### 4.9.1 下载工作台弹窗现在是前端弹窗基准样式

- 基准实现：`frontend/src/components/download/DownloadTaskWorkbenchDialog.vue`
- 以后新做弹窗，尤其是“任务面板 / 工作台 / 预览 / 批量处理 / 详情抽屉式信息弹窗”，默认先对齐这套布局语言，不要每个弹窗都重新发明一套
- 这不是只抄颜色，而是整套信息分层一起复用：
  - 顶部标题区 + 浅灰 header / body 分层
  - 首屏工具栏：左侧摘要统计，右侧动作按钮
  - 筛选区：胶囊筛选按钮成行排列
  - 主内容区：卡片列表，不要退回裸表格思路
  - 卡片展开后再放细节、文件流水线、日志，不要一上来把所有信息摊平
- 视觉规则默认按这套走：
  - 外层弹窗圆角、浅灰背景、弱边框、无厚重阴影
  - 内容卡片白底，状态只做轻量边框/底色提示，不要大面积高饱和铺色
  - 按钮、筛选、状态统一使用圆角胶囊风格
  - 字体继续沿用当前这套 `SF Pro Rounded` / `SF Pro Text` / `PingFang SC` / `Microsoft YaHei` 回退链
  - 间距、字号、标签密度保持“紧凑但不拥挤”，不要做成后台默认大表单风
- 信息结构规则：
  - 先给总览统计，再给筛选，再给任务卡片，再给展开详情
  - 状态展示优先用状态 pill、meta pill、进度条、短日志，不要堆长段说明文案
  - 失败、等待、处理中、完成要靠统一语义色和状态标签区分，别每个弹窗自造一套文案和颜色
- 实现规则：
  - 优先延续现有 class 命名节奏：`toolbar / summary / actions / filter-pill / task-card / meta-pill / detail-grid / log-list`
  - 能复用现有样式语义就复用，不要为了“看起来不一样”改成另一套视觉体系
  - 如果业务特殊必须偏离这套基准，要有明确理由；默认不是设计自由发挥题

### 4.9.2 前端弹窗 / 预览页默认组件包口径

- 当前这套预览下载工作台，实际依赖口径是：
  - 框架：`Vue 3`
  - 基础 UI 组件：`Element Plus`
  - 图标：`lucide-vue-next`
  - 页面布局与视觉表达：`Tailwind CSS v4`
  - 数据请求：`axios`
  - 时间处理：`dayjs`
- 默认理解：
  - 弹窗容器、进度条、空态这类基础能力优先用 `Element Plus`
  - 图标优先用 `lucide-vue-next`，不要一会儿 `Element Plus Icons` 一会儿别的图标库混着来
  - 布局、间距、圆角、玻璃感、响应式节奏优先沿用 `Tailwind` 实用类和项目现有语义 class
  - 业务卡片样式、状态 pill、工具栏、筛选条这些“视觉层”优先复用项目现有手写样式，不要再额外引入新的弹窗库、卡片库、样式框架
- 其他页面也按这个原则处理：
  - 不要给某个页面单独引入新的 UI 组件包，只为做一个弹窗、tab、卡片或按钮
  - 不要混用多套图标体系，避免页面气质和线条粗细打架
  - 不要把 `Element Plus` 默认风格直接铺满页面；容器能力可以用，视觉表达继续走项目自己的工作台风格
  - 如果真的要新增第三方包，先确认现有 `Element Plus + Tailwind + lucide-vue-next` 组合做不到，再决定

### 4.9.3 前端设计必须遵循 React 产品风格（强制规范）

- 所有新增或重构的前端页面、弹窗、工作台、详情页，必须遵循以下原则：
  - 技术实现：必须使用 `Vue 3`
  - 设计语言：必须对齐 React 社区主流产品风格（shadcn / Radix / Vercel 风格）
- 本项目明确不接受“默认后台管理系统风格 UI”
- 任何新页面如果仍然呈现明显 Element Plus 默认风格，视为不合格实现

---

### 4.9.4 视觉与交互强制规范

- 必须遵循以下视觉原则：
  - 克制、留白明确、层级清晰
  - 禁止大面积高饱和色块堆叠
  - 禁止“后台表单式 UI”作为主视觉
  - 所有界面需具备产品级视觉，而不是工具页拼接感
- 页面视觉目标：
  - 用户第一眼感知应接近现代 React 产品界面，而不是传统管理后台

---

### 4.9.5 组件结构强制规范

- 页面必须拆分为清晰的结构层级：
  - 顶部标题区（标题 + 简述）
  - 工具栏（摘要 + 主操作）
  - 筛选区（pill / tabs / segmented）
  - 内容区（卡片为主，不使用裸表格作为主结构）
  - 详情区（展开后展示）
- 禁止：
  - 把所有逻辑和 UI 写在单一 `.vue` 文件中
  - 不拆组件直接堆模板
- 必须：
  - 使用 `script setup`
  - 合理使用 `props / emits / composables`
  - 展示组件与业务逻辑解耦

---

### 4.9.6 样式与技术栈强制规范

- 样式优先级必须为：
  1. `Tailwind CSS`（布局 / 间距 / 圆角 / 响应式）
  2. 项目已有语义 class（卡片 / 状态 / 工具栏）
  3. `Element Plus`（仅用于容器与基础交互能力）
- 禁止：
  - 直接使用 Element Plus 默认样式作为最终 UI
  - 引入额外 UI 框架（除非现有方案无法实现）
- 图标规范：
  - 只允许使用 `lucide-vue-next`
  - 禁止混用多套图标库

---

### 4.9.7 代码与视觉一致性规范

- 同一类组件（卡片 / 状态标签 / 按钮 / 筛选条）必须保持统一风格
- 禁止：
  - 每个页面定义不同风格组件
  - 同类元素视觉不一致
- 所有状态展示必须统一语义：
  - 使用 pill / icon / 颜色，而不是文本堆叠

---

### 4.9.8 禁止事项（强约束）

以下行为一律禁止：

- 使用 Element Plus 默认表格作为核心页面布局
- 使用默认按钮样式直接交付 UI
- 在同一页面混用多种设计语言（后台风 + 产品风）
- 图标库混用（如 Element Icons + Lucide 混用）
- 未经设计统一直接新增 UI 风格

---

### 4.9.9 验收标准（必须满足）

前端改动必须满足以下条件才视为合格：

- 技术上：符合 Vue 3 规范
- 视觉上：接近 React 产品级 UI（Vercel / shadcn 风格）
- 结构上：组件拆分合理，信息层级清晰
- 一致性：与现有工作台 UI 风格统一

---

### 4.9.10 违例处理原则

- 不符合以上规范的 UI 改动：
  - 必须重构，不允许“先合并后优化”
- 视觉风格不统一：
  - 优先统一，而不是保留历史实现
- 对规范有疑问时：
  - 默认向现有工作台（DownloadTaskWorkbenchDialog.vue）对齐




### 4.10 历史重复社团索引现在有一次性清理脚本

- 脚本：`backend/scripts/merge_duplicate_circle_catalogs.py`
- 用途：
  - 按 `circle_name_normalized` 找出重复 `circle_catalogs`
  - 预览重复组
  - 备份 `backend/data/cache.db`
  - 合并 `circle_works`
  - 删除重复 catalog
- 默认是预览模式：
  - `py -3 backend/scripts/merge_duplicate_circle_catalogs.py`
- 真正写入要显式加：
  - `py -3 backend/scripts/merge_duplicate_circle_catalogs.py --apply`
- 这脚本只适合清理历史脏数据，不是日常索引流程的一部分
- 合并逻辑当前会保留：
  - 最新时间
  - 更完整的标题 / maker 信息
  - 合并后的 `source_mask`
  - 合并后的 `linked_rjcodes`
- 如果后续继续给 `circle_works` 加字段，要同步检查这个脚本的 merge 逻辑，不然清理历史数据会丢信息

### 4.11 操作历史脏数据现在还有单独清理脚本

- 脚本：`backend/scripts/cleanup_dirty_activity_logs.py`
- 作用：
  - 删除旧的 `subtitle_import / pending_execute` 噪音记录
  - 把旧的“重复作品但状态写成 success”的日志修正为等待人工处理口径
  - 清理由 `待处理 / _conflicts / temp / tmp` 路径误判出来的问题作品脏数据
- 默认先预览，真正写入要加 `--apply`
- 这是历史数据修复脚本，不是常规运行流程；以后如果继续扩展活动日志状态，记得同步维护这个脚本的筛选条件

## 5. 群晖 / 远程库存注意点

- 远程搜索必须优先走群晖原生接口，不要偷偷退回本地递归逻辑
- 根目录 `/` 搜索时，要按 share 拆分再汇总
- RJ 字幕远程扫描和写回已经单独处理过：
  - 递归时跳过 `subtitles`
  - 远程 `list/stat/create` 行为可能不完全一致
  - `relative_path`、`real_path`、标准化路径要格外小心
- 判断远程路径是否在库存范围内时，要复用现有 root/browse_root 校验
- 常见群晖错误码仍需优先关注：
  - `119`
  - `121`
  - `401`
  - `408`

## 6. 用户需求的默认理解

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
  6. `frontend/src/views/Library.vue`
- 如果是“社团补全任务看不懂 / 历史记录不完整”：
  1. 看 `ActivityHistory.vue` 里的社团索引概览卡片有没有数据
  2. 看 `routes.py` 是否把 `circle_completion` 的 `task_finished / task_finished_incomplete` 合并到索引父记录下
  3. 看 `Tasks.vue` 是否展示了 `dlsite_failure_reason`
  4. 看 `activity_log_service.py` 是否把 `CIRCLE_COMPLETION_INDEX / CIRCLE_COMPLETION_DOWNLOAD_BATCH` 正确映射到 `circle_completion`

### 用户说“推送仓库”

- 先检查：
  - `git status`
  - 是否混入 `.env`、本地数据库、用户配置
  - tag 是否符合 semver

### 用户说“为什么 Actions 失败”

- 先看 tag 是否为 `vX.Y.Z`
- 再看 `.github/workflows/ghcr.yml` 的触发与 semver 解析

## 7. 改动时的实现偏好

- 优先复用现有服务和任务模型，不要在路由里堆业务
- 库存树、远程路径标准化、RJ 扫描逻辑都已经有现成实现，别重复造轮子
- 新增任务或扩展任务时，顺手把：
  - 任务中心上下文
  - 操作日志
  - 前端状态展示
  - 错误态和重试态
  一起补齐
- 前端如果只是补按钮，不够；要确认对应 loading、空态、禁用态、完成态都闭环
- 不要把“能跑”当“可维护”，这个项目现在明显已经进入状态同步复杂期

## 8. 最低验证要求

### 改前端后

- 至少执行：`npm run build`
- 重点看：
  - 页面标题 / favicon
  - 库存页是否正常渲染
  - 搜索 / 定位是否还能用
  - RJ 字幕弹窗能否打开
  - 字幕任务面板状态是否还正常
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
- 如果改了社团补全，再补：
  - `py -3 -m py_compile backend/app/core/circle_completion_service.py backend/app/core/asmr_resource_service.py backend/app/models/database.py`
  - 有历史缓存时，确认 `init_db()` 的 `circle_works` 增量字段迁移能跑
  - 如果动了去重逻辑，先用 `backend/scripts/merge_duplicate_circle_catalogs.py` 预览再决定是否执行 `--apply`

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

### 改社团补全前端后

- 至少执行：`npm run build`
- 重点看：
  - 最近索引列表是否按社团去重
  - 缺失作品卡片点击整卡选择是否正常
  - “来源对比”标签页分页是否正常
  - 预览下载是否仍然拿到正确的 `resolved_rjcode`
  - `ActivityHistory.vue` 里的社团索引概览抽屉是否正常渲染
  - 历史详情抽屉拖拽宽度后没有事件泄漏

## 9. 现在建议优先级

1. 稳定 RJ 工作台“原始抓取 -> 人工筛选 -> 自动预匹配 -> 手动配对 -> 最终写入”整条链
2. 继续清理任务中心、操作日志、字幕工作台之间的状态串台
3. 继续统一库存页工具栏、批量条、右侧操作区的交互一致性
4. 继续补群晖 DSM 兼容细节，尤其是远程 `subtitles` 目录处理
5. 清理旧文案、乱码注释、历史品牌残留
