# AGENTS.md

给后续 AI / 自动化代理的接手说明。只写现在还活着、改动频率高、最容易踩坑的东西。

## 1. 项目现状

- 项目统一名称：`Prekikoeru`
- 主要技术栈：
  - 后端：FastAPI
  - 前端：Vue 3 + Vite + Element Plus
  - 桌面版：`pystray` + PyInstaller
- 当前主干工作不只是“解压整理”，已经扩展成 4 个高频区：
  - 库存浏览 / 搜索 / 文件管理
  - RJ 字幕工作台
  - 任务中心
  - 操作审计 / 历史记录
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

## 9. 现在建议优先级

1. 稳定 RJ 工作台“原始抓取 -> 人工筛选 -> 自动预匹配 -> 手动配对 -> 最终写入”整条链
2. 继续清理任务中心、操作日志、字幕工作台之间的状态串台
3. 继续统一库存页工具栏、批量条、右侧操作区的交互一致性
4. 继续补群晖 DSM 兼容细节，尤其是远程 `subtitles` 目录处理
5. 清理旧文案、乱码注释、历史品牌残留
