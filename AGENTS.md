# AGENTS.md

给后续 AI / 自动化代理的快速接手说明。只保留高频且容易踩坑的结论。

## 1. 项目定位

- 项目统一名称：`Prekikoeru`
- 技术栈：
  - 后端：FastAPI
  - 前端：Vue 3 + Vite
  - 桌面版：`pystray` 托盘 + PyInstaller
- 主分支：`master`
- 发布标签只能用标准 semver：
  - 正确：`v1.0.1`
  - 错误：`v1.01`

## 2. 关键入口

### 后端

- API 路由：[backend/app/api/routes.py](backend/app/api/routes.py)
- 配置模型：[backend/app/config/settings.py](backend/app/config/settings.py)
- 任务引擎：[backend/app/core/task_engine.py](backend/app/core/task_engine.py)
- 库存管理：[backend/app/core/library_manager.py](backend/app/core/library_manager.py)
- RJ 字幕服务：[backend/app/core/rj_subtitle_service.py](backend/app/core/rj_subtitle_service.py)
- 冲突处理服务：[backend/app/core/conflict_resolution_service.py](backend/app/core/conflict_resolution_service.py)

### 前端

- 主布局：[frontend/src/App.vue](frontend/src/App.vue)
- 路由：[frontend/src/router/index.js](frontend/src/router/index.js)
- API 封装：[frontend/src/api/index.js](frontend/src/api/index.js)
- 库存页：[frontend/src/views/Library.vue](frontend/src/views/Library.vue)
- 问题作品页：[frontend/src/views/Conflicts.vue](frontend/src/views/Conflicts.vue)
- 设置页：[frontend/src/views/Settings.vue](frontend/src/views/Settings.vue)

### 桌面 / 发布

- 托盘入口：[desktop_app.py](desktop_app.py)
- 打包脚本：[build-release.bat](build-release.bat) / [package.bat](package.bat) / [backend/build.py](backend/build.py)
- CI：[.github/workflows/ghcr.yml](.github/workflows/ghcr.yml)

## 3. 硬规则

### 品牌一致性

- 所有新改动统一使用 `Prekikoeru`
- 不要混回旧名：
  - `KikoeruTool_Elena`
  - 其他旧品牌名
- 以下位置必须同步：
  - 页面标题
  - favicon
  - 托盘名称
  - exe 名称
  - API 标题
  - 发布说明

### 配置安全

- 仓库默认模板：`backend/config/config.yaml`
- 本地运行常见配置：
  - 桌面版：`data/config/config.yaml`
  - Docker：`/app/config/config.yaml`
- 不要覆盖用户真实运行配置
- 不要提交真实密码、Token、代理或私有地址
- 用户说“改配置文件”时，默认理解为改仓库模板，不是改本地敏感配置

### 桌面托盘

- 当前稳定方案是 `pystray` 原生托盘菜单
- 没有明确要求时，不要重写成 Win32 菜单或自定义假菜单
- 当前桌面包名统一为 `Prekikoeru.exe`
- 图标必须使用仓库内资源，不能依赖外部绝对路径

## 4. 当前高频功能

### RJ 字幕工作台

- 入口在库存页，不在设置页
- 主入口：
  - `当前目录抓字幕`
  - `批量抓字幕`
  - 行内 `识别抓字幕`
  - `字幕任务面板`
- 核心原则：
  - 不自动扫盘
  - 不自动强制抢焦点
  - 不要求用户手填路径
  - 先抓原始字幕，再人工筛选和匹配
- 正确流程：
  1. 抓取原始字幕
  2. 用户查看原始结果并手动删除不需要项
  3. 自动预匹配
  4. 手动配对
  5. 最终按命名策略写入
- 不要把“抓取”和“最终命名”混在同一阶段

### 库存页

- 库存页是高频改动区，改前先看结构
- 已有能力：
  - 多库存浏览
  - 本地 / 群晖库存
  - 行内打开 / 重命名 / 删除
  - 文件管理弹窗
  - RJ 字幕工作台
- 目录树能力优先复用现有实现，不要重新造树
- 顶部工具栏按钮要求同宽、同高、同节奏
- 库存页右侧操作按钮已是定制视觉，不要退回默认 `type/plain`

### 删除过滤预审

- 当前已是后台任务 + 进度轮询模式
- 正确体验：
  - 先预审
  - 用户审阅
  - 再确认删除
- 删除成功后应直接更新当前树和计数，不应重新启动一遍预审

### 问题作品 / 冲突处理

- 顶层动作收敛为：
  - `KEEP_NEW`
  - `SKIP`
  - `MERGE`
- `KEEP_OLD` 只允许作为兼容别名存在，不要继续在新 UI 暴露
- `KEEP_NEW` 必须经过删除预审 / 删除确认
- `MERGE` 应进入文件级工作台，不是简单并存
- 解压失败应落到问题列表：
  - 类型：`EXTRACT_FAILED`
  - 默认只允许 `SKIP`

## 5. 群晖 / 远程库注意点

- 远程搜索必须走群晖原生搜索接口，不要退回本地递归扫盘
- 根目录 `/` 搜索时，要按 share 拆分再汇总
- 群晖常见问题码仍要重点留意：
  - `119`
  - `121`
  - `401`
  - `408`
- 远程目录存在 `subtitles` 时，`list / stat / create` 表现可能不一致，DSM 兼容性要谨慎

## 6. 用户常见需求的默认处理

### 用户说“改配置文件”

- 默认改仓库模板
- 不要动本地真实敏感配置

### 用户说“推送仓库”

- 先检查：
  - `git status`
  - 是否混入敏感配置
  - tag 是否符合 semver

### 用户说“为什么 Actions 失败”

- 先看 tag 是否是 `vX.Y.Z`
- 再看 `.github/workflows/ghcr.yml` 的 semver 解析

### 用户说“RJ 字幕功能有问题”

- 优先检查：
  1. `frontend/src/views/Library.vue`
  2. `frontend/src/api/index.js`
  3. `backend/app/api/routes.py`
  4. `backend/app/core/task_engine.py`
  5. `backend/app/core/rj_subtitle_service.py`
  6. `backend/app/core/library_manager.py`

## 7. 最低验证要求

### 改前端后

- 至少执行：`npm run build`
- 重点检查：
  - 页面标题
  - favicon
  - 库存页渲染
  - RJ 弹窗能打开

### 改后端后

- 至少执行：
  - `py -3 -m py_compile backend/app/api/routes.py backend/app/core/task_engine.py backend/app/core/rj_subtitle_service.py`
- 重点检查：
  - 配置加载
  - RJ 接口还能创建任务
  - 库存接口未被误伤

### 改桌面版后

- 至少检查：
  - 托盘图标显示
  - 右键菜单正常
  - 能打开 Web
  - 能退出程序
  - 打包仍可用

### 改发布流程后

- 至少检查：
  - `.github/workflows/ghcr.yml`
  - tag 仍符合 semver

## 8. 当前建议优先级

1. 稳定 RJ 工作台“原始抓取 -> 人工筛选 -> 自动预匹配 -> 手动配对 -> 一键应用”
2. 清理 RJ 状态、字幕树、任务焦点之间的串台
3. 继续统一库存页按钮和工具栏视觉
4. 继续处理群晖 DSM 兼容问题
5. 清理乱码注释和旧文案
