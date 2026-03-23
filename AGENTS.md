# AGENTS.md

本文档面向后续执行任务的 AI / 自动化代理。
目标不是介绍项目，而是帮助代理快速进入正确上下文，避免重复踩坑。

## 1. 项目现状

- 项目统一名称：`Prekikoeru`
- 主分支：`master`
- 当前发布标签规范：必须使用标准 semver，例如 `v1.0.1`
- 禁止再使用非标准标签，例如 `v1.01`
- 当前仓库包含：
  - FastAPI 后端
  - Vue 3 + Vite 前端
  - Windows 桌面托盘入口
  - PyInstaller 打包脚本
  - GHCR GitHub Actions

## 2. 核心目录与入口

### 后端

- API 入口：
  - `backend/app/api/routes.py`
- 配置模型：
  - `backend/app/config/settings.py`
- 任务引擎：
  - `backend/app/core/task_engine.py`
- 库存管理：
  - `backend/app/core/library_manager.py`
- RJ 字幕抓取服务：
  - `backend/app/core/rj_subtitle_service.py`

### 前端

- 主布局与侧边栏：
  - `frontend/src/App.vue`
- 路由：
  - `frontend/src/router/index.js`
- API 封装：
  - `frontend/src/api/index.js`
- 库存页：
  - `frontend/src/views/Library.vue`
- 设置页：
  - `frontend/src/views/Settings.vue`
- 浏览器标题 / favicon：
  - `frontend/index.html`
  - `frontend/public/favicon.ico`

### 桌面版

- 桌面入口：
  - `desktop_app.py`
- 打包脚本：
  - `build-release.bat`
  - `package.bat`
  - `backend/build.py`

### CI / 发布

- GitHub Actions：
  - `.github/workflows/ghcr.yml`

## 3. 当前稳定结论

### 品牌命名

- 所有新改动统一使用 `Prekikoeru`
- 不要再恢复或混入：
  - `KikoeruTool_Elena`
  - 其他旧命名

涉及以下位置时必须保持一致：

- 前端页面标题
- favicon
- 桌面托盘名称
- exe 名称
- API 标题
- 发布说明

### 桌面托盘

- 当前稳定实现以 `pystray` 原生托盘菜单为准
- 不要轻易改回手写 Win32 菜单或自定义假菜单
- 已验证可用能力：
  - 托盘图标显示正常
  - 系统原生右键菜单正常
  - 菜单可打开 Web 界面
  - 菜单可退出程序
  - 启动时多余通知弹窗已移除

### 打包

- 图标必须使用项目内资源
- 不要再依赖外部绝对路径 ico
- 当前桌面包名统一为 `Prekikoeru.exe`

### 发布

- `master` 推送可以触发 workflow
- tag 必须是 `vX.Y.Z`
- GHCR workflow 依赖 semver 解析
- 如果 Actions 因 tag 失败，先检查 tag 格式，不要先怀疑代码

## 4. 配置文件规则

### 默认配置文件

- 仓库默认配置文件：
  - `backend/config/config.yaml`
- 它应当是“可提交的默认模板”
- 可以有默认值，但不能包含用户真实敏感信息

### 本地运行配置

常见运行时配置路径：

- 桌面版：
  - `data/config/config.yaml`
- Docker：
  - `/app/config/config.yaml`

### 安全约束

- 不要覆盖用户本地正在使用的真实 `config.yaml`
- 不要把本地真实密码、Token、代理地址、私有服务地址重新提交进 Git
- 如果用户要求“改 Git 上的配置”，优先理解为：
  - 修改仓库默认模板
  - 不要动用户本地真实运行配置

## 5. RJ 字幕抓取功能现状

这是当前项目最近新增且需要重点理解的功能。

### 功能定位

- 这是“音频已在本地库存中，去抓字幕”的反向流程
- 不是 `ASMR 同步下载` 的重复页面
- 设计上已改为直接集成在库存页使用

### 当前入口

- 主入口在：
  - `frontend/src/views/Library.vue`
- 已集成到库存页的这些操作：
  - `当前目录抓字幕`
  - `字幕任务面板`
  - 行内 `识别抓字幕`
  - 批量 `批量抓字幕`

### 当前交互原则

- 不自动扫盘
- 不自动后台轮询闪烁
- 不要求手动输入路径
- 由库存页直接选目录或父目录触发

### 当前弹窗结构

`RJ 字幕抓取` 弹窗已经改成“工作台”结构：

- 左侧：
  - 执行选项
  - 待处理目录列表
- 右侧：
  - 最近字幕任务
  - 字幕文件树检查

### 当前可调选项

这些选项已经放回库存弹窗内，而不是设置页：

- `覆盖已有字幕`
- `只扫一级`
- `启用 metadata 匹配`
- `来源搜索` 展示开关
- `写入结果` 展示开关
- `下载进度` 展示开关
- `问题项` 展示开关

这些值当前保存在前端本地 `localStorage`，不再依赖设置页默认值。

### 当前后端能力

RJ 字幕流程已接通：

- 扫描接口：
  - `POST /api/rj-subtitle/scan`
- 创建任务接口：
  - `POST /api/rj-subtitle/start`
- 状态接口：
  - `GET /api/rj-subtitle/status`

任务类型：

- `TaskType.RJ_SUBTITLE_FETCH`

当前已真正传递到后端执行的参数：

- `overwrite_existing`
- `scan_one_level_only`
- `enable_metadata_match`

### 字幕文件树检查

弹窗内部已经复用库存文件树能力。

当前支持：

- 查看 `subtitles/` 目录树
- 搜索字幕文件
- 重命名字幕文件
- 删除字幕文件
- 删除字幕子目录

当前明确不做：

- 在这个面板里增加复杂编辑器
- 增加与库存主文件树完全一样的全部操作

这里只保留“核对抓取结果并做轻量修正”。

### 与 ASMR 同步下载的关系

- 可参考 `ASMR 同步下载` 的任务信息展示思路
- 但两者方向相反：
  - `ASMR 同步下载`：字幕 -> 下载音频
  - `RJ 字幕抓取`：本地音频 -> 抓字幕
- 不要把两个页面硬合并
- 只复用成熟的任务展示和字幕后处理逻辑

## 6. 库存页现状

库存页是现在变更最频繁的页面之一，动它之前先看清结构。

### 已有能力

- 多库存浏览
- 本地 / 群晖库存支持
- 统计刷新
- 行内打开 / 重命名 / API 重命名 / 删除
- 文件管理弹窗
- RJ 字幕工作台

### 文件管理弹窗

当前库存页已有一套成熟的文件树实现，可复用：

- 展开 / 折叠
- 搜索
- 批量删除
- 图标映射

如果后续还要做“目录树类功能”，优先复用这里，不要重新造一套树。

### 库存与设置联动

之前修过一个坑：

- 设置页改的是 `storage.library_path`
- 库存页读的是 `storage.libraries`

当前已做同步兜底，不要再让默认库存路径和设置页路径脱节。

## 7. UI 约束

### 库存页操作按钮

库存列表右侧那组按钮现在已经不是 Element Plus 默认 plain 风格，而是定制色板。

当前约束：

- 所有按钮使用同一套动效
- 每个动作可有独立颜色
- 不要混回原生默认 `type/plain` 风格
- 按钮组要保持统一的尺寸、圆角和悬浮节奏

当前已单独配色的动作包括：

- 打开
- 直接打开
- 重命名
- API 重命名
- 识别抓字幕
- 文件管理
- 删除

### 顶部工具栏

- 库存页顶部工具按钮现在要求宽度统一
- 不要让按钮靠不同文字长度撑开
- 如果后续改这一排，优先保持：
  - 同高度
  - 同宽度
  - 同间距

## 8. 禁止事项

### 不要乱改桌面托盘方案

- 当前方案已经反复验证过
- 如果用户没明确要求，不要重写托盘实现

### 不要提交本地敏感配置

- 修改 `backend/config/config.yaml` 前先判断：
  - 你改的是仓库模板
  - 还是用户本地真实配置

### 不要使用非标准发布标签

- 只能用 `vX.Y.Z`

### 不要恢复 RJ 字幕设置页

- 这个功能已经明确收回库存弹窗
- 设置页里的重复面板已移除
- 后续不要再把同一组选项拆成两处维护

## 9. 修改后最低验证要求

### 改前端后

至少执行：

- `npm run build`

重点检查：

- 标题是否正确
- favicon 是否正确
- 库存页是否正常渲染
- RJ 字幕弹窗是否能打开

### 改后端后

至少执行：

- `py -3 -m py_compile backend/app/api/routes.py backend/app/core/task_engine.py backend/app/core/rj_subtitle_service.py`

重点检查：

- 配置加载是否报错
- RJ 字幕接口是否还能正常创建任务
- 库存接口是否没被误伤

### 改桌面版后

至少检查：

- 托盘图标是否显示
- 右键菜单是否正常
- 能否打开 Web 界面
- 能否退出程序
- 打包后是否仍正常

### 改发布流程后

至少检查：

- `.github/workflows/ghcr.yml`
- tag 是否仍为 semver

## 10. 常见任务的正确处理方式

### 用户说“改配置文件”

先区分：

- 改仓库默认模板
- 改用户本地运行配置

如果用户没有明确允许，不要替用户覆盖本地真实敏感配置。

### 用户说“推送仓库”

先检查：

- `git status`
- 是否混入本地敏感配置
- tag 是否规范

### 用户说“打包桌面版”

先检查：

- `desktop_app.py`
- 图标资源是否仍在项目内
- 打包脚本是否还在引用外部路径

### 用户说“为什么 Actions 失败”

先检查：

- tag 是否是标准 semver
- `.github/workflows/ghcr.yml` 中 `docker/metadata-action` 的 tag 规则

### 用户说“RJ 字幕功能有问题”

优先检查：

- `frontend/src/views/Library.vue`
- `frontend/src/api/index.js`
- `backend/app/api/routes.py`
- `backend/app/core/task_engine.py`
- `backend/app/core/rj_subtitle_service.py`

先判断问题属于：

- 库存识别
- 扫描参数没传到后端
- 任务状态展示
- 字幕匹配逻辑
- 字幕文件树操作

## 11. 当前值得继续优化的方向

按优先级看，后续最值得做的是：

1. 继续清理仓库中残留的乱码注释和旧文案
2. 为 RJ 字幕工作台补更细的任务筛选和结果回看能力
3. 继续统一库存页按钮和工具栏的视觉系统
4. 把更多敏感配置改成环境变量覆盖模式
5. 补桌面版和库存页的回归检查清单

## 12. 最近变更与交接（2026-03 RJ 字幕工作台）

这一节用于帮助后续代理接住最近一轮高频修改，避免新线程重新踩坑。

### 当前已落地的交互方向

RJ 字幕抓取工作台最近已按下面的方向调整：

- 抓取流程正在朝“先抓原始字幕，再人工筛选与匹配”的模式收敛
- 不应在刚下载字幕时就过早做最终命名
- 任务面板允许查看历史任务，不应该被当前执行中的任务强制切回
- 字幕树检查区不仅用于重命名和删除，还承担后处理修正
- 手动配对工作台已经开始支持更强的人工干预，而不是只依赖自动匹配

### 本轮已经明确做过的改动

涉及文件：

- `frontend/src/views/Library.vue`
- `backend/app/api/routes.py`
- `backend/app/core/task_engine.py`
- `backend/app/core/rj_subtitle_service.py`

最近已做过的关键调整包括：

- RJ 任务状态接口已增加更多工作台所需字段
- 任务切换逻辑已经改过一轮，目标是不让正在执行任务抢走用户当前查看的历史任务
- 检查区和当前焦点任务之间的联动已经改过一轮，避免主卡片、待处理目录、字幕树检查串台
- 手动匹配区已开始支持“顺序点选”模式
- 已增加“配对命名”选项：
  - 跟随音频名
  - 保留字幕名
- 已增加“采用过滤配置”选项，目标是复用现有过滤规则来筛字幕候选
- 已做过一轮“原始字幕先抓取，再等待后处理”的流程改造
- 库存页当前目录工具栏已新增“删除过滤文件”方向的实现，目标是：
  - 先按现有过滤规则扫描当前目录
  - 再以树状预览让用户审阅
  - 用户取消误判项后才真正删除

### 当前用户最新确认的正确工作流

后续代理继续做 RJ 字幕功能时，优先按下面的流程理解：

1. 先从远端抓取原始字幕列表和字幕文件
2. 抓取完成后，让用户先看到“原始抓到了哪些字幕”
3. 用户手动删除不需要的字幕
4. 然后再进入自动预匹配和手动配对阶段
5. 最终命名规则在“后处理匹配阶段”决定，而不是抓取阶段提前决定

也就是说：

- “抓取” 与 “最终命名/最终匹配” 应分阶段
- 抓取阶段应尽量保留原始信息，避免过早处理
- 最终让播放器自动挂字幕时，字幕名和音频名应一致（排除各自后缀）

### 用户最新明确提出且必须记住的需求

#### 1. 任务切换不要被强制抢焦点

用户切到旧任务卡片时：

- 不要因为有任务在运行，就自动切回正在执行的任务
- 主卡片、待处理目录、检查树要跟随同一个任务焦点
- 历史任务查看必须稳定

#### 2. 原始字幕先展示给用户选择

用户明确指出：

- 自动过滤效果目前不够好
- 抓取完后应先让用户看到“全部原始字幕”
- 由用户手动决定保留哪些
- 然后再进入后续匹配

所以不要再把“过滤”和“命名”都强塞在抓取阶段完成。

#### 3. 匹配支持一次性顺序点选

用户需要这样的人工工作流：

- 先在左侧音频列表依次点 1、2、3、4
- 再在右侧字幕列表依次点 1、2、3、4
- 然后一键按顺序配对

如果后续继续完善手动匹配区，优先加强这个能力，而不是再增加复杂自动规则。

#### 4. 命名规则需要可切换

用户已经明确要在工作台中保留配置项：

- 用字幕给音频命名
- 或用音频给字幕命名

但无论哪种模式，都应在“后期匹配时”生效，不应在刚抓取时提前改名。

#### 5. 过滤规则需要复用现有解压过滤配置

用户要求：

- 下载字幕时可以选择启用现有过滤配置
- 利用既有过滤规则筛掉 mp3、反转、无 SE 等不需要的字幕候选
- 但这个过滤过程仍要可理解、可控制，不能黑箱导致用户不知道删了什么

### 当前仍未完全稳定、需要继续排查的点

下面这些属于最近还没完全收住的问题，新线程里优先关注：

#### 群晖远程库相关

- `408`：群晖 FileStation 在列目录或检查 `subtitles` 目录时仍可能报错
- `119`：远程路径失效、目录不存在或权限不足时仍会触发
- `401/101`：上传 multipart 形态、群晖 API 兼容性之前多次出现过，需要继续谨慎处理
- 同一个目录下 `subtitles` 存在但 `list/stat/create` 行为不一致，说明 DSM 兼容性仍有坑

#### RJ 字幕流程相关

- 抓取阶段与后处理阶段的职责边界还需要继续清理
- 某些地方仍可能过早显示“匹配后名字”而不是原始抓取名字
- 原始字幕数量、最终匹配组数、最终写入数要清晰区分展示，避免用户误以为“少文件”
- 过滤规则接入后，需要继续确认是否真的筛掉了用户不想要的字幕
- 目录中明明有 `wav` 对应字幕时，仍有用户看到界面显示 `mp3.vtt`，这个问题必须继续核对：
  - 是真实下载源选错
  - 还是只是前端显示名没切干净

#### 工作台前端体验相关

- 批量删除入口需要明显且稳定，不要只有勾选没有动作按钮
- 写入结果、下载进度、问题项要避免把页面拉得过长
- 检查树的展开/折叠、刷新、批量删除都必须可点且和当前焦点任务一致
- 待处理目录的“音频数 / 现有字幕数”不能在处理后消失或回退成错误值
- “识别抓字幕”打开弹窗时不能卡顿太久，建议先开弹窗再异步刷新内容

### 最近容易误判的点

后续代理遇到下面现象时，要先判断是不是“显示问题”而不是立即认定后端逻辑错了：

- 下载进度里显示的是源站字幕名还是最终目标名
- 当前主卡片显示的 RJ 是目录 RJ 还是来源版本 RJ
- 检查区加载的是当前任务字幕树，还是上一个任务残留状态
- `下载 28`、`匹配组 14`、`写入 14` 这种情况，可能是同轨双格式合并后的结果，不一定是漏抓

### 新线程接手时建议的优先检查文件

如果用户继续反馈“RJ 字幕工作台还有问题”，优先按这个顺序读代码：

1. `frontend/src/views/Library.vue`
2. `frontend/src/api/index.js`
3. `backend/app/api/routes.py`
4. `backend/app/core/task_engine.py`
5. `backend/app/core/rj_subtitle_service.py`
6. `backend/app/core/library_manager.py`

### 新线程里优先继续优化的方向

建议优先顺序：

1. 彻底稳定“原始抓取 -> 人工筛选 -> 自动预匹配 -> 手动配对 -> 一键应用”这条流程
2. 清理 RJ 任务状态和字幕树检查之间的串台/残留状态
3. 明确区分“原始字幕名”“目标字幕名”“最终写入名”的展示
4. 继续处理群晖 DSM 7.1.1 下 FileStation 的兼容问题
5. 优化工作台布局密度，保留信息量但减少纵向撑高
6. 后续把远程库存搜索从“当前页过滤”升级为“接群晖原生搜索接口”的真正远程搜索
6. 后续接群晖原生搜索接口，做真正的远程搜索，不再只依赖当前目录列表后的本地过滤

### 本轮最低验证记录

本轮最近已执行过：

- `py -3 -m py_compile backend/app/api/routes.py backend/app/core/task_engine.py backend/app/core/rj_subtitle_service.py backend/app/config/settings.py`
- `npm run build`

后续如果继续修改上述链路，至少重复这两类验证。

### 2026-03-21 补充交接（字幕树交互 / 字幕过滤 / 原始字幕命名）

最近又补了一轮和 RJ 工作台直接相关的改动：

- 字幕树选择不再只靠 checkbox，已开始支持：
  - 行点击选中
  - `Ctrl+A` 全选
  - `Ctrl/Command + 点击` 多选
  - `Shift + 点击` 区间选择
- 字幕树顶部和底部都保留了批量删除入口，避免选中后还得滚回去找按钮
- “采用过滤配置”已经改成 RJ 工作台自己的“字幕过滤规则”，不再沿用解压过滤的混淆文案
- 字幕过滤规则当前保存在前端本地 `localStorage`，并在创建 RJ 任务时单独传给后端
- 抓取阶段展示名和原始写入名已经开始去除尾部音频后缀：
  - `xxx.mp3.vtt` -> `xxx.vtt`
  - `xxx.wav.vtt` -> `xxx.vtt`
- 下载进度区前端显示也做了同样的后缀清洗，避免用户误以为仍在抓错误格式
- 过程日志区域已经改成铺满宽度，不再只占左半边留下大片空白
- 写入结果区域也改成更紧凑的双列展示，减少纵向撑高

### 这轮之后仍值得继续核对的点

- 当前字幕过滤规则虽然已和解压过滤分离，但仍需继续验证过滤效果是否符合用户预期
- 用户非常在意 `wav` 优先，如果目录里实际存在 `wav` 对应字幕，仍要继续确认不会显示或保留成 `mp3.vtt`
- 群晖 FileStation 的 `408/119/401/101` 兼容问题仍然是后续重点
- RJ 工作台当前信息量依旧很大，后续可以继续压缩任务卡片密度，但不要牺牲信息完整性

### 2026-03-23 补充交接（RJ 工作台流式扫描 / 删除预审 / 文件管理弹窗）

最近又做了一轮高频收口，涉及面比前一轮更广，后续代理接手时请优先按这一节理解当前状态。

#### 本轮涉及的主要文件

- `frontend/src/views/Library.vue`
- `frontend/src/components/library/SubtitleInspectorWorkbench.vue`
- `frontend/src/components/library/FilterDeleteDialog.vue`
- `frontend/src/components/library/FolderContentsDialog.vue`
- `frontend/src/views/Logs.vue`
- `frontend/src/api/index.js`
- `backend/app/api/routes.py`
- `backend/app/core/library_manager.py`
- `backend/app/core/rj_subtitle_service.py`
- `backend/app/core/task_engine.py`
- `backend/app/core/asmr_download_service.py`

#### RJ 字幕工作台这轮已经明确做过的调整

- `当前目录抓字幕 / 批量抓字幕 / 行内识别抓字幕` 已朝“扫描到一个 RJ 就处理一个”的方向改造
- 工作台左侧列表已区分：
  - `可执行与已入任务`
  - `被跳过`
  - `扫描目标`
- `被跳过` 已开始区分至少两类：
  - `已有字幕`
  - `远程无字幕`
- `已有字幕` 的项不应自动入爬取任务，但应允许：
  - 直接进入下方字幕筛选与匹配工作台
  - 对当前单项执行一次“强制重新爬取字幕”
- 当前选中任务头部已增加 `重新执行爬取字幕` 按钮
  - 只能作用于“当前选中的一条任务”
  - 目标是绕过“已有字幕时跳过”
  - 不应批量影响其他任务
- 当前主卡片详情区已压缩为更紧凑布局，并增加可折叠思路，避免日志、写入结果、下载进度把页面无限拉长
- 任务顶部摘要标签已改为可点击筛选，不再只是展示数字
- 历史任务焦点不能再被正在执行的任务强制抢回
- `字幕任务面板` 入口应只负责查看任务，不应偷偷按当前目录再补建待处理项

#### RJ 扫描与创建任务当前正确目标

- 正确行为应该是：
  1. 遍历父目录寻找 RJ 文件夹
  2. 识别到一个 RJ 文件夹后，立即判断是否已有本地字幕
  3. 再判断远端是否存在可用字幕
  4. 只有满足可执行条件时，立即创建一条 RJ 字幕任务
  5. 不应等整批扫描完再统一创建
- 如果本地已有字幕：
  - 默认跳过，不创建任务
  - 但要保留该项供用户进入匹配工作台，或单独强制创建任务
- 如果远端无字幕：
  - 直接跳过
  - 必须在工作台里明确显示“远程无字幕”理由
- 扫描结束后不应再误弹：
  - `当前页面没有 RJ 号`
  - `该目录未扫到 RJ 号文件夹`
  这类提示只有在真正一个命中都没有时才允许出现

#### 这轮新增或强化的 RJ 过滤与日志结论

- RJ 字幕过滤规则已明确与“解压过滤规则”分离，保存在前端本地 `localStorage`
- 创建任务时会把 `use_filter_rules` 和 `subtitle_filter_rules` 一起传给后端
- 后端 `rj_subtitle_service.py` 已补以下能力：
  - 过滤目标兼容 `name / file / filename`
  - 过滤目标兼容 `path / folder / filepath`
  - 过滤目标兼容 `all`
  - 候选匹配时会同时看：
    - `display_name`
    - `source_name`
    - `relative_path`
    - 规整后的显示名
- 已补“下载前候选统计”日志，至少会打印：
  - `初始`
  - `过滤后`
  - `下载去重后`
  - `use_filter_rules`
- 已确认一个常见误区：
  - `[ASMR] 解析后第一个文件 ...` 这类日志只是源站解析日志
  - 不是最终下载候选
- 过滤规则当前仍需继续重点核对：
  - `无效果音 / 効果音なし / 无音效 / SEなし`
  - `mp3 / wav`
  - `反转 / reverse`
  是否都能按用户预期挡掉

#### 删除过滤预审当前状态

- 删除过滤预审已改成后台任务 + 进度轮询模式
- 预审弹窗需要持续显示：
  - 当前状态
  - 命中项数
  - 已扫描项数
  - 已发现项数
  - 待扫目录数
  - 当前路径
- 远程大目录预审目前采取的是：
  - 后台任务
  - 可取消
  - 顺序或受限并发扫描
  - 尽量避免前端单请求超时
- 这轮又补了一个关键修复：
  - `确认删除` 成功后，不能再重新启动一遍预审任务
  - 现在应直接从当前预审树里移除已删项，并更新顶部计数与大小
- 也就是说，删除成功后的正确表现应该是：
  - 列表立刻减少
  - 统计立刻变化
  - 不再出现“像重新创建一遍预审，再显示删除成功”的体验

#### 文件管理弹窗当前状态

- 文件管理弹窗已经从 `Library.vue` 拆出到：
  - `frontend/src/components/library/FolderContentsDialog.vue`
- 当前支持：
  - 展开 / 折叠
  - 搜索
  - 行点选
  - `Ctrl+A`
  - `Ctrl/Command + 点击`
  - `Shift + 点击`
  - 单项删除
  - 批量删除
- 这轮又修了两类确认框统计问题：
  - 文件夹数 / 文件数统计错误
  - 目录大小偶发显示为 `0 B`
- 当前正确口径应是：
  - 单删确认按当前树节点递归统计文件夹数和文件数
  - 批删确认按选中根项的整棵子树汇总统计
  - 如果后端预检返回 `0` 或没带齐统计，前端要回退到当前树节点汇总值
- 一个特别容易漏掉的坑：
  - 批量选择后如果最后只剩 `1` 个根项，删除流程会落到“单删确认”分支
  - 这时必须把这个唯一根项也作为 `previewRow` 传进去
  - 否则确认框大小和计数会再次退化为 `0` 或错误值

#### 系统日志页这轮处理过的点

- 系统侧边栏日志页之前做过一轮虚拟滚动尝试，但用户反馈：
  - 无法正常拖动
  - 页面卡顿
- 后续处理方向已改成“稳定优先”：
  - 恢复可正常滚动
  - 不要让日志页自己抢滚动
  - 只在确实需要时再继续做更稳的性能优化

#### 这轮仍未完全稳定、后续继续排查的重点

- RJ 扫描虽然已经朝“发现一个处理一个”推进，但要继续确认：
  - 是否真的做到边扫描边创建任务
  - 是否还存在“左侧命中已出现，但任务区还是 0”的显示串台
- `已有字幕 -> 跳过` 与 `远程无字幕 -> 跳过` 这两个筛选项必须继续复测
- 远程群晖扫描时：
  - `119` 无效路径
  - `121` 信号灯超时
  - `408` 请求超时
  仍然容易出现，相关日志必须继续保留
- `rj_subtitle_service.py` 里虽然已补过滤目标归一化和候选归一化，但历史乱码日志和老分支仍未完全清干净
- `Library.vue` 虽然拆出了两个大组件，但仍然偏重，后续还能继续拆 composable 或按块分包

#### 新线程继续接手时的优先检查建议

如果用户继续反馈“RJ 字幕工作台还是有问题”，建议优先按这个顺序读：

1. `frontend/src/views/Library.vue`
2. `frontend/src/components/library/SubtitleInspectorWorkbench.vue`
3. `frontend/src/components/library/FilterDeleteDialog.vue`
4. `frontend/src/components/library/FolderContentsDialog.vue`
5. `frontend/src/api/index.js`
6. `backend/app/api/routes.py`
7. `backend/app/core/task_engine.py`
8. `backend/app/core/rj_subtitle_service.py`
9. `backend/app/core/library_manager.py`

#### 本轮补充验证记录

本轮已额外执行过：

- `py -3 -m py_compile backend/app/api/routes.py backend/app/core/task_engine.py backend/app/core/rj_subtitle_service.py`
- `npm run build`

后续如果继续修改上述链路，至少重复这两类验证。

## 13. 问题列表 / 冲突处理重构交接（2026-03-23）

这一节用于给后续线程直接接住“问题列表 / 冲突处理”改造，不需要重新从零分析。
本节不是需求复述，而是按工程落地视角记录：当前实现在哪里、为什么不够、应该怎么拆、哪些能力可以复用、哪些缺口必须补。

### 本轮目标已经明确收敛为以下顶层动作

当前问题列表顶层动作必须收敛为：

- `保留新版`
- `跳过`
- `合并`

后续代理必须记住：

- 顶层不再保留 `保留旧版`
- `保留旧版` 的实际效果与 `跳过` 一致，继续保留只会增加分支复杂度、状态冗余和用户理解成本
- 如果为了兼容旧数据或旧接口短期内还保留 `KEEP_OLD` 字段，也应在服务层尽早映射为 `SKIP`，不要再继续扩散到新 UI、新逻辑、新状态定义里

### 当前相关代码入口

这次重构主要涉及以下文件，后续线程建议优先按这个顺序阅读：

1. `frontend/src/views/Conflicts.vue`
2. `frontend/src/api/index.js`
3. `backend/app/api/routes.py`
4. `backend/app/core/library_manager.py`
5. `backend/app/core/classifier.py`
6. `backend/app/core/duplicate_service.py`
7. `backend/app/core/extract_service.py`
8. `backend/app/core/filter_service.py`
9. `backend/app/models/database.py`

其中当前最关键的现实结论如下：

- `frontend/src/views/Conflicts.vue` 仍是旧式表格页，存在乱码文案、状态简单、动作过薄的问题
- `backend/app/api/routes.py` 中 `/api/conflicts` 与 `/api/conflicts/{id}/resolve` 把大部分冲突处理硬编码在单路由分支里
- 当前 `MERGE` 不是“目录级可控合并”，只是把新版本改名后并存，本质上不满足现需求
- 当前 `KEEP_NEW` 直接删除旧目录，没有接入删除审查，风险很高
- 当前 `SKIP` 直接删除新路径，但缺乏明确的提交前后状态同步设计
- 项目里已经存在可复用的删除预审 / 删除确认能力，集中在 `library_manager.py` 和库存页前端删除交互里，不应重新发明一套
- 项目里已经存在远程群晖递归文件树读取、远程删除、远程批删、远程上传目录能力，可作为冲突处理重构的基础设施

### 当前实现的主要问题

#### 1. 前端问题列表页过薄，无法承载真正的合并工作流

当前 `frontend/src/views/Conflicts.vue` 的问题包括：

- 页面结构过于单一，只适合“查看条目 + 点一个按钮”
- 顶层按钮目前仍有 `KEEP_OLD`
- 行操作直接提交，没有“保留新版删除审查”与“合并预览工作台”的中间层
- 页面有固定轮询逻辑，后续如果引入合并工作台，必须防止轮询打断当前编辑状态
- 当前页内部状态只有 `loading / selected / processingIds` 这类浅状态，不足以表达：
  - 对比加载中
  - 对比结果已就绪
  - 合并决策未提交
  - 提交中
  - 提交失败可恢复
- 当前页已经出现乱码文案，后续最好按 UTF-8 整体重写，不要继续在原文件上做碎片增量补丁

#### 2. 后端 resolve 路由职责过重，且分支行为不安全

当前 `backend/app/api/routes.py` 的 `/api/conflicts/{id}/resolve` 存在这些问题：

- `KEEP_NEW / KEEP_OLD / MERGE / SKIP` 都写在单一路由分支内，职责过于集中
- `KEEP_NEW` 当前会先删 `existing_path`，再解压 / 过滤 / 分类，存在“旧内容删了，新内容没成功”的中间态风险
- `MERGE` 当前不是合并，而是“新版本另存一份”，不符合本次目标
- `KEEP_OLD` 与 `SKIP` 重复
- 删除旧目录和删除新包都没有统一经过删除预审入口
- 远程路径、远程库存、群晖安全替换完全没有在这条链路里被当成一级对象来处理

#### 3. 现有冲突数据模型太薄

当前 `backend/app/models/database.py` 中 `ConflictWork` 主要只有：

- `existing_path`
- `new_path`
- `new_metadata`
- `status`

这意味着目前冲突记录里没有这些信息：

- 目标库存 ID
- 目标是本地还是群晖远程
- 已生成的对比会话 ID
- 合并预览摘要
- 合并选择缓存
- 删除预审结果快照

结论：

- 不建议把所有临时比对数据都塞回数据库
- 建议新增服务层会话对象，数据库仍保存“冲突记录”，比对会话放临时目录 + 内存会话；如果后续有恢复需求，再补持久化

### 已确认可直接复用的现有能力

#### 1. 删除预审 / 删除确认能力

必须优先复用：

- `backend/app/core/library_manager.py`
  - `delete()`
  - `batch_delete()`
  - `_remote_delete_preview()`
  - 远程批删预检与确认链路
- `frontend/src/views/Library.vue`
  - 当前库存页的删除确认消息构建方式
- `frontend/src/components/library/FolderContentsDialog.vue`
  - 当前文件管理弹窗的单删 / 批删预览确认交互

后续线程必须记住：

- `保留新版` 删除旧目录时，必须经过统一删除预审入口
- 不允许出现“问题列表里删除旧目录绕过预审，而库存页删除要预审”的双标行为
- 本地与远程至少要在交互层统一成一套“先预审、再确认、再执行”的节奏

#### 2. 远程文件树与远程上传能力

当前 `library_manager.py` 已有：

- 远程递归文件树读取：`_remote_folder_contents()`
- 远程目录遍历：`_list_remote_directory()`
- 远程删除：`delete()` / `_remote_batch_delete()`
- 远程创建目录：`SynologyFileStationClient.create_folder()`
- 远程上传文件：`SynologyFileStationClient.upload_file()`
- 本地目录整体上传到群晖：`upload_directory_to_library()` / `_upload_directory_to_synology()`

这些能力说明：

- 远程冲突处理不是“完全没有基础设施”
- 但是还缺少专门面向冲突替换 / 合并的事务式编排层
- 后续应新增专门的 `conflict_resolution_service` 或同类服务，不要继续在 `routes.py` 里硬拼

#### 3. 新内容准备能力

当前可以复用：

- `extract_service.py`：解压压缩包到临时目录
- `filter_service.py`：对解压目录执行过滤

这意味着：

- “合并对比左侧 = 新解压且过滤后的内容”是可以直接落地的
- 不需要额外再实现一套简化版解压 / 过滤流程
- 但要注意：冲突页的对比预览不能直接修改真实 `new_path`，必须复制到专用工作目录后再处理

### 强烈建议新增的服务层设计

建议新增：

- `backend/app/core/conflict_resolution_service.py`

这个服务层建议承担以下职责：

#### 1. 对比会话准备

输入：

- `conflict_id`
- `existing_path`
- `new_path`

输出：

- 一个对比会话对象 `session`
- 会话中包含：
  - 新侧临时目录位置
  - 旧侧目标描述（本地 / 远程）
  - 文件对比结果
  - 汇总统计
  - 删除预审结果

建议会话内容至少包含：

- `session_id`
- `conflict_id`
- `workspace_path`
- `new_root`
- `target.kind`：`local | remote | external`
- `target.library_id`
- `target.path`
- `comparison_items`
- `summary`
- `delete_preview`
- `created_at`

#### 2. 保留新版执行

服务层逻辑必须改成：

1. 先准备新内容（必要时解压、过滤）
2. 先完成删除预审结果返回给前端
3. 用户确认后，才进入执行阶段
4. 执行时不能先裸删旧目录再慢慢处理新目录
5. 正确策略应是：
   - 本地：先在临时位置构建最终目录，再做目录替换
   - 远程：先上传临时目录，再做远程切换
6. 旧内容删除 / 备份完成后，才删除新压缩包来源

#### 3. 合并执行

服务层逻辑必须改成：

1. 基于对比结果构建 `MergeDecisionMap`
2. 根据用户选择生成最终提交计划
3. 本地与远程分别走不同落地策略
4. 成功后清理：
   - 新压缩包 / 新目录来源
   - 临时会话目录
   - 不再需要的远程临时目录 / 备份目录

### 合并功能的正确工程模型

#### 1. 顶层“合并”不是一个瞬时动作，而是一条工作流

顶层点“合并”后，不应立即提交。
正确行为应是：

1. 打开合并工作台
2. 后端生成新旧文件对比
3. 用户逐项确认文件去留
4. 前端展示最终结果预览摘要
5. 用户点击“应用合并”
6. 后端按计划落地
7. 成功后该冲突项从问题列表移除

#### 2. 文件对比建议的数据模型

后端建议返回的单文件对比项至少包含：

- `key`
- `name`
- `relative_path`
- `depth`
- `status`
  - `added`
  - `removed`
  - `modified`
  - `unchanged`
- `default_decision`
  - `new`
  - `old`
  - `delete`
- `available_decisions`
- `new_item`
  - `size`
  - `modified_time`
  - `hash`（本地可算，远程可先为空）
- `existing_item`
  - `size`
  - `modified_time`
  - `hash`

判断策略建议：

- 两边都存在且大小不同：直接 `modified`
- 两边都存在、大小相同：
  - 本地可进一步比 `hash`
  - 远程先保守视为 `modified`，不要轻易判 `unchanged`
- 只在新侧存在：`added`
- 只在旧侧存在：`removed`

#### 3. 用户选择建模建议

前端不要给每行绑多个互斥布尔值。
建议统一用：

- `mergeDecisions: Record<relative_path, 'new' | 'old' | 'delete'>`

理由：

- 状态更稳定
- 更适合序列化后提交给后端
- 便于做默认值填充和批量操作
- 便于生成“最终结果预览”

#### 4. 最终结果生成建议

本地：

- 在会话临时目录下生成 `merged_output/`
- 遍历所有 `comparison_items`
- 按决策：
  - `new`：从新侧复制
  - `old`：从旧侧复制
  - `delete`：不复制
- 全部生成完成后，整体替换目标目录

远程：

- 不建议把旧远程目录完整下载到本地再合并
- 正确思路是“保留远程旧文件 + 上传需要的新文件 + 删除用户明确删除的旧文件”
- 即：远程 merge 应该是“按文件事务式提交”，而不是“先拉一份旧目录到本地再整体回传”

### 远程场景必须记住的正确策略

#### 1. 不要从群晖把旧目录整包拉回本地做合并

原因：

- 成本高
- 超时风险高
- 回滚复杂
- 没有现成稳定下载基础设施支撑这条链路

#### 2. `保留新版` 的远程安全替换策略

建议流程：

1. 将新目录上传到目标父目录下的临时目录
   - 例如：`.__prekikoeru_keep_new_xxx`
2. 将旧正式目录改名为备份目录
   - 例如：`.__prekikoeru_backup_xxx`
3. 将临时新目录改名为正式目录名
4. 确认成功后删除备份目录
5. 任一步失败时：
   - 若旧目录已改名但新目录未转正，应立即把备份目录改回正式名
   - 若临时上传目录还在，应尽量删除

必须记住：

- 不要先删旧目录再上传新目录
- 远程切换应以 `rename` 为主，而不是“先 delete 再 upload”

#### 3. `合并` 的远程安全提交策略

建议流程：

1. 对所有选择 `new` 的文件：
   - 先上传到同目录临时文件名
2. 对所有选择 `delete` 或被 `new` 覆盖的旧文件：
   - 先改名为备份名，不要直接删
3. 将新临时文件改名为正式文件名
4. 所有文件都成功后，再删除备份文件
5. 若中途失败：
   - 删除已转正的新文件
   - 将旧备份文件改回正式名
   - 删除未转正的上传临时文件

这条策略的现实意义：

- 不追求理论上的“完整远程事务”
- 追求的是：
  - 能回滚
  - 步骤清晰
  - 基于现有 `upload / rename / delete` 能直接实现
  - 不需要补远程下载与远程复制能力

#### 4. 当前明确存在的远程能力缺口

必须写清楚，避免下个线程误判成“代码里已经有”：

- 当前没有现成的 Synology 远程目录复制封装
- 当前没有冲突处理专用的远程事务管理器
- 当前没有远程合并结果持久化会话
- 当前没有现成的“远程替换目录”服务层，只能复用上传 / rename / delete 自己编排

所以后续不要写成：

- “TODO: 后续补远程上传”

而应该明确写成：

- 基于现有 `upload_file / create_folder / rename / delete` 实现事务式远程提交

### 必须同步修的几个结构性问题

#### 1. `classifier.py` 对远程快照识别不正确

当前 `backend/app/core/classifier.py` 的 `_check_existing()` 主要依赖：

- `os.path.exists(snapshot.folder_path)`

这对远程库存快照是不成立的。
后续代理必须注意：

- 如果 `snapshot.folder_path` 命中某个远程库存根目录，不应该因为 `os.path.exists()` 为假就把它当成失效快照删掉
- 这里需要补一层“路径属于本地库存还是远程库存”的判断
- 否则远程冲突检测会被误伤，进而导致问题列表不完整或误漏

#### 2. `duplicate_service.py` 的推荐项要同步收敛

当前推荐项里仍有：

- `KEEP_OLD`
- `KEEP_BOTH`
- `MERGE_LANG`

这一块至少要分场景处理：

- 问题列表页顶层动作：只保留 `KEEP_NEW / MERGE / SKIP`
- 若某些“已有文件夹处理”逻辑仍需要 `KEEP_BOTH` 之类动作，可以保留在旧链路，但不要再把这些动作带到新的问题列表顶层
- 若保留旧字段兼容历史数据，前端必须做动作映射，不要直接把全部旧 action 暴露给用户

#### 3. `Conflicts.vue` 的渲染与状态管理必须重构

当前潜在问题包括：

- 轮询会打断用户正在看的项目
- `Set` 原地增删的响应式不稳定
- 顶层 `loading` 与行内 `processing` 容易互相覆盖
- 未来如果用 `v-if` 频繁销毁合并工作台，用户做过的文件选择会丢
- 只要仍旧用“行按钮直接提交”的模式，`合并结果预览` 和 `实际提交结果` 很容易脱节

建议：

- 问题列表与合并工作台分层
- 工作台打开时暂停自动刷新问题列表
- 工作台组件不要在切换筛选时销毁
- 每个对比项必须用稳定 key：`relative_path`
- 页面状态至少拆成：
  - `listLoading`
  - `comparisonLoading`
  - `applyLoading`
  - `activeConflictId`
  - `activeSessionId`
  - `mergeDecisions`
  - `compareFilter`
  - `compareSelection`

### 前端交互与视觉风格要求

后续代理必须记住：

- 这次重构不能做成另一套系统风格
- 必须保持与当前项目视觉语言一致
- 优先复用现有 Element Plus 组件与系统内已存在的卡片、标签、对话框、表格节奏
- 不要在问题列表页引入明显风格跳脱的新 UI 体系

建议的视觉与交互方向：

- 问题列表主体仍使用表格 / 卡片结构
- 合并工作台可用 `Drawer` 或大 `Dialog`，但内部组件风格要贴近库存页文件管理弹窗
- 文件对比列表建议用：
  - 左侧过滤与摘要
  - 中间对比表格
  - 右侧结果预览摘要
  但整体仍应是 Element Plus 风格，不要突然做成完全不同的设计语言
- 删除确认文案、危险操作按钮样式、warning 提示节奏应与库存页一致

### 建议新增或重构的前端模块

建议新增：

- `frontend/src/components/conflicts/ConflictMergeWorkbench.vue`
- `frontend/src/components/conflicts/ConflictFileDiffTable.vue`
- `frontend/src/components/conflicts/ConflictResultSummary.vue`
- `frontend/src/components/conflicts/conflictDeletePreview.js` 或同类工具文件

建议重构：

- `frontend/src/views/Conflicts.vue`
- `frontend/src/api/index.js` 中 `conflictApi`

建议 API 扩展为：

- `conflictApi.list()`
- `conflictApi.getComparison(conflictId, { refresh })`
- `conflictApi.resolve(conflictId, payload)`
  - `action`
  - `session_id`
  - `merge_decisions`

### 建议新增或重构的后端模块

建议新增：

- `backend/app/core/conflict_resolution_service.py`

建议这个服务层负责：

- 对比会话准备
- 新内容临时目录生成
- 文件对比结果生成
- 删除预审统一调用
- 本地安全替换
- 远程安全替换
- 远程按文件合并提交
- 会话清理

建议扩展路由：

- `GET /api/conflicts`
  - 增加目标类型 / 是否支持对比 / 目标库存信息
- `GET /api/conflicts/{id}/comparison`
- `POST /api/conflicts/{id}/resolve`
  - 新版 payload 不应只传 `action`
  - 建议允许传：
    - `action`
    - `session_id`
    - `merge_decisions`
    - `confirmed`（如需要二次确认标识）

### 下一线程建议的实施顺序

后续代理如果要真正开始实现，建议按以下顺序，不要乱跳：

1. 先补服务层：`conflict_resolution_service.py`
   - 先把“新侧准备 + 旧侧文件树读取 + 对比结果生成”打通
2. 再补后端 comparison 接口
   - 先让前端可以拿到真实对比数据
3. 再改 `Conflicts.vue`
   - 删除 `KEEP_OLD`
   - 新增“合并工作台”入口
4. 再做 `KEEP_NEW` 的安全替换与删除预审接入
5. 再做 `MERGE` 的本地落地
6. 最后做 `MERGE` 的远程事务式提交
7. 最后再清理历史分支与文案

原因：

- 如果先改 UI，不先补服务层，对比工作台很容易变成假功能
- 如果先做远程合并，不先把本地合并闭环跑通，复杂度会放大
- 如果先删历史分支，不先搭好新服务层，容易把现有功能一起打坏

### 这轮已经明确识别出的未完缺口

后续线程不要忽略这些：

- 当前尚未真正创建 `conflict_resolution_service.py`
- 当前尚未把删除预审接入 `KEEP_NEW`
- 当前尚未把 `MERGE` 改造成真正的文件级合并
- 当前尚未修 `classifier.py` 的远程快照判断
- 当前尚未统一前端删除确认文案构建工具
- 当前 `Conflicts.vue` 仍是旧结构且含乱码
- 当前还没有把问题列表页的轮询与工作台编辑态解耦

### 最低验证要求（后续谁继续改，谁必须重复执行）

如果继续修改冲突处理链路，至少执行：

- `py -3 -m py_compile backend/app/api/routes.py backend/app/core/library_manager.py backend/app/core/classifier.py backend/app/core/duplicate_service.py`
- `npm run build`

重点人工核对：

- 问题列表页能正常渲染
- 不再显示 `保留旧版`
- `保留新版` 会先走删除预审
- `跳过` 删除压缩包失败时不会假装成功
- `合并` 能看到新旧两侧文件对比
- 本地目标目录在失败时不会出现“旧内容已删、新内容未完成”的中间态
- 远程目标目录在失败时不会留下不可理解的半完成状态
- 问题列表在操作成功后才移除项，不要先移除再失败

### 给下一个线程的直接结论

如果用户继续说“问题列表 / 冲突处理要重构”，不要再把重点放在文案和按钮上。
真正应该优先做的是：

1. 新增冲突处理服务层，把 `routes.py` 的硬编码流程拆出去
2. 让 `KEEP_NEW` 接入统一删除预审，并改成安全替换
3. 让 `MERGE` 先有真实文件对比，再有真实合并提交
4. 远程场景按“上传临时件 + rename 切换 + 失败回滚”做，不要走先删旧目录再上传新目录的危险路径
5. 保持现有系统风格，不要把问题列表页做成另一套 UI

### 13.1 按文件拆解的修改清单（问题列表 / 冲突处理重构）

这一节是在上一节基础上进一步细化到“每个文件该改哪些函数和接口”。
后续线程如果准备直接开工，优先按本节执行。

#### A. `frontend/src/views/Conflicts.vue`

这是前端主入口，建议按“重写而不是小补丁”的思路处理。

##### 当前主要问题

- 顶层动作仍包含 `KEEP_OLD`
- 页面只有表格，没有合并工作台区域
- 行操作点击即提交，不支持：
  - 删除预审确认
  - 对比预览
  - 合并决策编辑
- 页面轮询会在用户编辑中打断状态
- 当前文件已有乱码，继续局部改会让后续维护更困难

##### 建议保留的基础结构

- 顶层仍保留“问题列表”页，不要改成其他页面形态
- 仍保留表格作为入口视图
- 可保留批量操作区，但批量动作应只剩：
  - `批量保留新版`
  - `批量跳过`
- 批量 `合并` 不建议第一轮就做，复杂度高，容易做成假功能

##### 建议新增的状态

至少新增：

- `listLoading`
- `listRefreshing`
- `selectedConflicts`
- `processingIds`
- `activeConflictId`
- `comparisonLoading`
- `comparisonError`
- `comparisonVisible`
- `comparisonSession`
- `mergeDecisions`
- `mergeApplyLoading`
- `autoRefreshPaused`

##### 建议新增或重构的方法

建议保留并重构：

- `fetchConflicts()`
  - 增加“如果工作台打开则不覆盖当前 active session”的保护
  - 若列表项已处理成功，再从列表移除
- `handleSelectionChange(selection)`
  - 可保留
- `handleBatchAction(action)`
  - 删除 `KEEP_OLD`
  - 只允许 `KEEP_NEW` / `SKIP`

建议删除旧思路并重写：

- `handleAction(conflict, action)`
  - 不要再直接一把梭提交所有动作
  - 拆成：
    - `openKeepNewConfirm(conflict)`
    - `openMergeWorkbench(conflict)`
    - `confirmSkip(conflict)`

建议新增：

- `openMergeWorkbench(conflict)`
  - 打开工作台
  - 拉取 comparison 数据
  - 初始化 `mergeDecisions`
- `loadConflictComparison(conflictId, { refresh = false } = {})`
- `applyKeepNew(conflict)`
  - 必须先基于 comparison 数据里的 `delete_preview` 弹确认框
- `applySkip(conflict)`
  - 提交前后都更新行状态
- `applyMerge(conflict)`
  - 提交 `session_id + merge_decisions`
- `pauseAutoRefresh()` / `resumeAutoRefresh()`
- `removeResolvedConflict(conflictId)`
  - 只在后端明确成功后调用
- `syncMergeDecisionsFromComparison(comparison)`

##### 渲染层建议

建议结构改成：

- 顶部：标题 + 页面说明 + 批量操作
- 中部：问题列表表格
- 右侧或弹层：合并工作台

建议表格列保留：

- `RJ`
- `冲突类型`
- `现有路径`
- `新内容路径`
- `目标类型`（新增，本地 / 远程 / 外部）
- `检测时间`
- `操作`

建议操作按钮改成：

- `保留新版`
- `合并`
- `跳过`

必须删除：

- 所有 `KEEP_OLD` 按钮和映射文案

#### B. `frontend/src/api/index.js`

##### 当前问题

当前 `conflictApi` 只有：

- `list()`
- `resolve(conflictId, action)`
- `enhancedCheck()`

不够承载本次重构。

##### 建议修改的接口

建议把 `resolve()` 改成支持 payload，而不是只传 action。

建议修改为：

- `list()`
- `getComparison(conflictId, options = {})`
- `resolve(conflictId, payload)`
- `clearSession(conflictId)`（可选，如果后端提供）

##### 具体建议

保留：

- `list()`
- `enhancedCheck()`

新增：

- `getComparison: async (conflictId, options = {}) => { ... }`
  - 调用 `GET /conflicts/{id}/comparison`
  - 支持 `refresh`
- `resolve: async (conflictId, payload) => { ... }`
  - payload 至少支持：
    - `action`
    - `session_id`
    - `merge_decisions`

##### 不要继续保留的旧形式

- `resolve(conflictId, action)` 这种只传单字符串的形式，不足以支持合并提交

#### C. `frontend/src/components/conflicts/ConflictMergeWorkbench.vue`（建议新增）

##### 职责

专门负责“合并”工作流，不要把这套内容继续堆在 `Conflicts.vue` 里。

##### 输入 props 建议

- `visible`
- `conflict`
- `comparison`
- `loading`
- `applyLoading`
- `mergeDecisions`

##### 输出事件建议

- `close`
- `refresh`
- `update:mergeDecisions`
- `apply`

##### 内部应承担的 UI 职责

- 展示摘要：
  - 新文件数
  - 旧文件数
  - 新增 / 删除 / 修改 / 未变化
- 展示筛选器：
  - 全部
  - 冲突项
  - 仅新增
  - 仅旧侧
  - 未变化
- 展示对比表格
- 展示结果预览摘要
- 提供：
  - 恢复默认决策
  - 全部冲突选新
  - 全部冲突选旧
  - 清空删除项

##### 渲染稳定性要求

- 不要使用会导致组件销毁的 `v-if` 频繁切换主工作区
- 优先使用 `v-show` 或外层 `Dialog/Drawer` 的持久化内容
- 所有对比项必须用 `relative_path` 作为 key

#### D. `frontend/src/components/conflicts/ConflictFileDiffTable.vue`（建议新增）

##### 职责

只做“文件对比列表”，不要混进提交逻辑。

##### 建议列

- 文件名
- 相对路径
- 新侧大小
- 旧侧大小
- 新侧时间
- 旧侧时间
- 状态
- 决策

##### 建议支持的交互

- 行内切换决策：`new / old / delete`
- 支持筛选后的稳定渲染
- 路径过长时用 tooltip，不要横向撑爆

##### 注意事项

- 对于 `added` 项：只能选 `new / delete`
- 对于 `removed` 项：只能选 `old / delete`
- 对于 `unchanged` 项：默认 `old`，一般不建议默认 `new`

#### E. `frontend/src/components/conflicts/ConflictResultSummary.vue`（建议新增）

##### 职责

根据 `mergeDecisions` 实时生成最终结果摘要。

##### 建议展示

- 最终保留新文件数
- 最终保留旧文件数
- 最终删除数
- 即将覆盖的冲突文件数
- 结果目录中文件总数（预估）

##### 为什么建议拆出来

- 避免 `Conflicts.vue` 和工作台组件里都写一遍统计逻辑
- 方便保证“预览摘要”和“实际提交 payload”来源一致

#### F. `frontend/src/components/conflicts/conflictDeletePreview.js`（或同类工具文件，建议新增）

##### 职责

统一构建冲突处理里的删除确认文案。

##### 来源建议

优先复用并抽取现有思路：

- `frontend/src/views/Library.vue`
- `frontend/src/components/library/FolderContentsDialog.vue`

##### 建议导出

- `buildConflictDeletePreviewMessage(preview, target)`
- `buildConflictReplaceWarningMessage(preview, target)`

##### 原则

- 不要在问题列表页再复制一套新的确认文案实现
- 保持与库存页删除预审交互一致

#### G. `backend/app/api/routes.py`

这是后端主要路由入口，建议本次不要继续膨胀老的 `resolve` 分支，而是做“路由变薄”。

##### 当前相关入口

- `GET /api/conflicts`
- `POST /api/conflicts/{conflict_id}/resolve`

##### 建议修改 `GET /api/conflicts`

当前返回字段太少。
建议增加：

- `existing_target_kind`
- `existing_library_id`
- `existing_library_name`
- `compare_supported`

这些字段可由新的服务层 `describe_existing_target()` 提前算出。

##### 建议新增接口

- `GET /api/conflicts/{conflict_id}/comparison`
  - 参数：`refresh` 可选
  - 返回：comparison session、summary、comparison_items、delete_preview、merge_preview

##### 建议重构 `POST /api/conflicts/{conflict_id}/resolve`

当前只收：

- `{ action }`

建议改为支持：

- `{ action, session_id, merge_decisions }`

##### 建议逻辑拆分

当前路由内部的 `KEEP_NEW / KEEP_OLD / MERGE / SKIP` 分支应尽量删除。
应改成：

1. 查 conflict
2. 解析 action
3. 调 `conflict_resolution_service.apply_resolution(...)`
4. 成功后更新：
   - `conflict.status`
   - `ProcessedArchive.status`
   - 关联任务状态
5. 返回结果

##### 兼容要求

如果短期内还有旧请求传 `KEEP_OLD`：

- 路由层应立即映射成 `SKIP`
- 不要让新服务层继续维护 `KEEP_OLD` 分支

#### H. `backend/app/core/conflict_resolution_service.py`（建议新增）

这个文件是本次重构的核心。

##### 建议拆成这些公开方法

- `describe_existing_target(existing_path)`
- `get_comparison(conflict, refresh=False)`
- `apply_resolution(conflict, action, session_id=None, merge_decisions=None, allow_refresh=False)`
- `cleanup_session(conflict_id)`

##### 建议内部方法

- `_ensure_session(conflict, refresh=False)`
- `_prepare_session(conflict)`
- `_prepare_new_root(conflict, workspace)`
- `_collect_existing_directory(target)`
- `_collect_local_directory(root_path)`
- `_build_comparison_items(new_items, existing_items, target_kind)`
- `_build_summary(...)`
- `_load_delete_preview(target)`
- `_apply_keep_new(conflict, session)`
- `_apply_skip(conflict)`
- `_build_merge_plan(session, merge_decisions)`
- `_apply_merge(conflict, session, plan)`
- `_replace_local_directory(...)`
- `_replace_remote_directory(...)`
- `_apply_remote_merge(...)`
- `_rollback_remote_merge(...)`
- `_resolve_existing_target(existing_path)`

##### 设计要求

- 服务层必须是“对比 / 应用 / 清理”三段式
- 不要把 DB commit 和 API response 拼接塞进服务层
- 服务层主要负责文件系统和群晖动作编排
- 路由层负责：
  - 查表
  - 调服务
  - 更新 DB
  - 包装响应

#### I. `backend/app/core/library_manager.py`

这个文件目前已经有很多可复用能力，但也需要补几个点。

##### 当前建议直接复用的函数

- `delete()`
- `batch_delete()`
- `_remote_delete_preview()`
- `folder_contents()`
- `_remote_folder_contents()`
- `_upload_directory_to_synology()`
- `_normalize_remote_path()`
- `_remote_path_is_within_root()`

##### 建议新增的函数

建议新增：

- `ensure_remote_directory(client, remote_path)`
  - 递归确保远程目录存在
- `upload_file_to_remote_path(...)`（可选）
  - 给冲突服务层更细粒度调用
- `rename_remote_path(...)`（可选轻封装）
- `delete_remote_path(...)`（可选轻封装）

##### 为什么建议加轻封装

- 当前很多远程动作散落在不同服务里直接调 `SynologyFileStationClient`
- 冲突处理后，远程 rename / delete / ensure dir 会变成高频动作
- 轻封装可统一日志、路径归一化和权限边界校验

##### 需要注意的点

- 现有 `delete()` / `batch_delete()` 逻辑已经分本地和远程，不要再复制一套“冲突删除专用 delete”
- 如果冲突服务层直接调用 `client.rename()`，至少也要复用 `library_manager` 的路径归一化原则

#### J. `backend/app/core/classifier.py`

##### 必修问题

`_check_existing()` 当前对远程快照不正确。

##### 需要重点修改的函数

- `_check_existing(rjcode)`

##### 具体修改建议

当前逻辑：

- 读 `LibrarySnapshot`
- 如果 `os.path.exists(snapshot.folder_path)` 为假，就删快照并认为不存在

应改成：

1. 读取 `snapshot.folder_path`
2. 判断该路径是否命中某个已配置远程库存根目录
3. 如果命中远程库存：
   - 不要用 `os.path.exists()` 直接判死
   - 可保守认为该快照仍有效，或在后续有需要时再补远程 stat 校验
4. 只有本地路径且确实不存在时，才删除过期快照

##### 为什么这是冲突处理重构的前置条件

- 如果远程冲突识别本身不准，后面的“保留新版 / 合并 / 跳过”工作流就建立在错误输入上

#### K. `backend/app/core/duplicate_service.py`

##### 需要重点修改的函数

- `get_resolution_options(...)`

##### 修改目标

收敛问题列表页顶层动作。

##### 具体建议

对于问题列表链路：

- 删除 `KEEP_OLD`
- 不再把 `KEEP_BOTH` 暴露给问题列表顶层
- `MERGE_LANG` 不直接作为问题列表顶层动作
- 收敛成：
  - `KEEP_NEW`
  - `MERGE`
  - `SKIP`

##### 注意

- 如果已有“已有文件夹处理”链路仍依赖 `KEEP_BOTH`，可以暂时保留在旧逻辑里
- 但新问题列表页不能继续直接消费这些旧 action

#### L. `backend/app/models/database.py`

##### 当前问题

`ConflictWork` 模型太薄，不足以表达新的冲突工作流上下文。

##### 第一阶段建议

第一阶段不一定要立刻改数据库字段，优先把对比会话放临时目录 + 内存会话。

##### 如果需要补字段，优先考虑这些

- `last_session_id`
- `target_library_id`
- `target_kind`
- `resolution_payload`（JSON，可选）
- `updated_at`

##### 但必须记住

- 这不是第一阶段的硬前置
- 第一阶段核心是先把服务层、comparison 接口和真实 merge 落地

#### M. `frontend/src/components/library/FolderContentsDialog.vue`

##### 为什么这个文件也要读

因为它已经有一套成熟的删除确认和删除统计逻辑，是问题列表里“保留新版删除审查”最适合参考和抽取的来源之一。

##### 建议复用或抽取的函数思路

- 删除预览消息构造
- 单项删除与批量删除文案节奏
- 删除成功后本地 UI 统计同步方式

##### 注意

- 不建议直接 import 整个组件逻辑
- 建议抽公共工具函数，再让问题列表页复用

#### N. `frontend/src/views/Library.vue`

##### 为什么也要读

这个文件里已有库存页删除预审与删除确认的用户体验节奏。
问题列表页的 `保留新版` 删除旧目录确认，应该尽量保持同一风格。

##### 建议复用的思路

- 删除前预审接口调用顺序
- `ElMessageBox.confirm` 的危险操作样式
- 删除成功后再刷新列表，而不是先乐观移除

#### O. `backend/app/core/extract_service.py`

##### 需要注意的函数

- `extract(task)`

##### 在冲突重构里的作用

- 只负责把新压缩包准备到会话临时目录
- 不要直接让它碰真实旧目录

##### 注意事项

- 冲突对比时应复制压缩包到独立 workspace 后再解压
- 不要直接使用原始 `new_path` 作为工作目录来源，否则容易污染真实文件

#### P. `backend/app/core/filter_service.py`

##### 需要注意的函数

- `filter(path, task)`

##### 在冲突重构里的作用

- 对比工作台左侧应展示“解压后且过滤后的新内容”
- 后续代理不要重新发明一套冲突专用过滤流程

##### 注意事项

- 必须在会话临时目录上执行
- 不要对真实目标目录做过滤

### 13.2 文件修改的优先级顺序

如果下个线程要直接改代码，建议按以下文件顺序动手：

1. `backend/app/core/conflict_resolution_service.py`（新增）
2. `backend/app/api/routes.py`
3. `backend/app/core/classifier.py`
4. `backend/app/core/duplicate_service.py`
5. `frontend/src/api/index.js`
6. `frontend/src/components/conflicts/ConflictMergeWorkbench.vue`（新增）
7. `frontend/src/components/conflicts/ConflictFileDiffTable.vue`（新增）
8. `frontend/src/components/conflicts/ConflictResultSummary.vue`（新增）
9. `frontend/src/views/Conflicts.vue`
10. 必要时抽公共删除预览工具

### 13.3 明确不要怎么改

后续代理不要做成下面这些方向：

- 不要继续在 `routes.py` 里堆更多 `if action == ...` 分支
- 不要把“合并”继续实现成“新版本加后缀另存一份”
- 不要让 `保留新版` 直接删旧目录而绕过预审
- 不要把群晖旧目录完整下载回本地再做合并
- 不要新做一套和库存页风格冲突的 UI
- 不要把 `KEEP_OLD` 以“兼容”为名继续暴露给用户

### 13.4 给下个线程直接复制用的 Checklist

下面这段是给后续线程快速接手用的极简执行清单。
如果新线程一上来就要继续“问题列表 / 冲突处理”重构，优先按这段执行，不要重新从零分析。

#### 一、先读哪些文件

先按这个顺序读：

1. `backend/app/api/routes.py`
2. `backend/app/core/library_manager.py`
3. `backend/app/core/classifier.py`
4. `backend/app/core/duplicate_service.py`
5. `frontend/src/views/Conflicts.vue`
6. `frontend/src/api/index.js`
7. `frontend/src/components/library/FolderContentsDialog.vue`
8. `frontend/src/views/Library.vue`

读的时候重点确认这几个现实结论：

- 顶层动作必须收敛成 `KEEP_NEW / MERGE / SKIP`
- `KEEP_OLD` 必须从新 UI 删除，旧请求只做兼容映射到 `SKIP`
- 当前 `MERGE` 还不是真合并，只是“另存一份”
- 当前 `KEEP_NEW` 还没有接删除预审
- 远程能力不是没有，而是缺少事务式编排层

#### 二、第一批必须先动的文件

第一批只动这些，不要一下子全仓库散改：

1. `backend/app/core/conflict_resolution_service.py`（新增）
2. `backend/app/api/routes.py`
3. `frontend/src/api/index.js`
4. `frontend/src/views/Conflicts.vue`

第一批目标只有四件事：

- 新增冲突服务层
- 新增 comparison 接口
- 让前端能拉 comparison 数据
- 把 `KEEP_OLD` 从问题列表 UI 去掉

#### 三、服务层第一版必须先做什么

`backend/app/core/conflict_resolution_service.py` 第一版先做这些函数：

- `describe_existing_target(existing_path)`
- `get_comparison(conflict, refresh=False)`
- `apply_resolution(conflict, action, session_id=None, merge_decisions=None)`
- `cleanup_session(conflict_id)`

内部至少先补这些能力：

- 把新压缩包复制到临时 workspace
- 在 workspace 内解压和过滤
- 读取旧目录文件树
  - 本地：直接扫目录
  - 远程：复用 `library_manager.folder_contents()`
- 生成 `comparison_items`
- 生成 `summary`
- 读取删除预审结果
- `KEEP_NEW` 本地安全替换
- `SKIP` 删除新来源

第一版可以先不做完整远程 merge，但必须把接口和数据结构先定住。

#### 四、`routes.py` 第一版怎么改

先改这三个点：

1. `GET /api/conflicts`
   - 增加：
     - `existing_target_kind`
     - `existing_library_id`
     - `existing_library_name`
     - `compare_supported`

2. 新增 `GET /api/conflicts/{id}/comparison`
   - 调服务层 `get_comparison()`

3. 重构 `POST /api/conflicts/{id}/resolve`
   - payload 改成支持：
     - `action`
     - `session_id`
     - `merge_decisions`
   - 不要继续把主逻辑堆在 route 里
   - route 里只做：
     - 查 conflict
     - 调服务
     - 更新 DB 状态
     - 返回结果

#### 五、前端第一版怎么改

`frontend/src/api/index.js` 先补：

- `conflictApi.getComparison(conflictId, options = {})`
- `conflictApi.resolve(conflictId, payload)`

`frontend/src/views/Conflicts.vue` 第一版先做：

- 删除所有 `KEEP_OLD` 按钮和文案
- 保留列表页，不改路由结构
- 增加：
  - `activeConflictId`
  - `comparisonVisible`
  - `comparisonLoading`
  - `comparisonSession`
  - `mergeDecisions`
- 新增“打开合并工作台”动作
- 工作台打开时暂停自动轮询

第一版前端可以先用一个较简单的 `Dialog` 承载合并工作台，不要求一次拆完所有子组件，但不要把所有逻辑继续堆在按钮回调里。

#### 六、第二批再动哪些文件

第一批跑通后，再动：

1. `backend/app/core/classifier.py`
2. `backend/app/core/duplicate_service.py`
3. `frontend/src/components/conflicts/ConflictMergeWorkbench.vue`（新增）
4. `frontend/src/components/conflicts/ConflictFileDiffTable.vue`（新增）
5. `frontend/src/components/conflicts/ConflictResultSummary.vue`（新增）

第二批目标：

- 修远程快照判断
- 收敛推荐动作
- 把合并工作台拆成稳定组件

#### 七、远程场景要怎么落地

后续线程继续做远程时，严格按下面思路，不要偏：

`KEEP_NEW` 远程：

1. 上传到临时目录
2. 旧目录 rename 为备份目录
3. 临时目录 rename 为正式目录
4. 成功后删备份
5. 失败则把备份 rename 回去

`MERGE` 远程：

1. 新文件先上传为临时文件名
2. 被覆盖或要删除的旧文件先 rename 为备份名
3. 新文件 rename 为正式名
4. 成功后删备份
5. 失败时：
   - 删已转正的新文件
   - 旧备份 rename 回正式名
   - 删未转正的临时上传文件

不要做：

- 先删旧目录再上传新目录
- 从群晖把旧目录整包拉回本地再合并

#### 八、这几个坑一定要记住

- `classifier.py` 现在会把远程 snapshot 误判成失效
- `MERGE` 当前实现不符合需求，不能沿用
- 问题列表页的轮询会打断编辑态
- `Set` 原地增删做 loading 标记不稳定，前端最好每次重新赋值
- 合并工作台不要频繁销毁，否则用户选择会丢
- 删除确认文案应尽量复用库存页风格，不要新造一套

#### 九、每次改完最低验证

至少执行：

- `py -3 -m py_compile backend/app/api/routes.py backend/app/core/library_manager.py backend/app/core/classifier.py backend/app/core/duplicate_service.py`
- `npm run build`

至少人工确认：

- 问题列表不再显示 `保留旧版`
- `保留新版` 会先走删除预审
- `跳过` 删除失败时不会假装成功
- `合并` 能看到真实文件对比
- 本地替换失败不会出现“旧内容没了、新内容也没写完”
- 远程替换失败不会留下半完成目录
## 14. 最近补充交接（2026-03-24：分卷解压 / 问题作品 / 库存真实搜索）

这一节用于让后续线程直接接住最近一轮高频修复，避免再重复踩坑。

### 1. 分卷压缩识别与解压链路

最近已补过以下结论：

- 分卷识别不能只识别 `.7z.001`
- 还要兼容：
  - `.zip` + `.z01/.z02`
  - `.rar` + `.r00/.r01`
  - `.part1.rar/.part2.rar`
- 主卷文件先到、分卷后到时，不能过早建任务
- `7z` 子进程不能在高并发下无限放大
- 不能在“读取压缩包内容”阶段因为加密目录头或交互式密码输入卡死

本轮已经做过的关键处理：

- `backend/app/core/file_processor.py`
  - 主卷 `.zip/.rar` 也会纳入分卷等待识别
  - `VolumeSet` 支持 `entry_path`
- `backend/app/core/extract_service.py`
  - `7z` 可用性检查已做缓存
  - `7z` 解压并发已单独限流
  - 临时解压目录改成唯一目录，避免并发冲突
  - `stdin=DEVNULL`，避免 7z 等交互式密码输入
  - 压缩包预读失败时会回退为直接尝试解压
  - 解压成功后，如果密码库条目自带 `rjcode`，会写入：
    - `task.task_metadata['inferred_rjcode']`
    - `task.task_metadata['rjcode']`
    - `task.rjcode`
- `backend/app/core/task_engine.py`
  - 任务会优先复用 `inferred_rjcode`
  - 元数据阶段和重命名前会再次回填有效 RJ
- `backend/app/core/rename_service.py`
  - `metadata.rjcode` 缺失时，会回退到：
    - `metadata.inferred_rjcode`
    - `task.rjcode`

后续必须记住：

- “密码库带 RJ，但路径本身没 RJ” 已经不是异常分支
- 这种情况下最终文件夹命名也应继续使用密码库带出的 RJ
- 不要再把这条 RJ 只停留在解压阶段

### 2. 解压失败与问题作品列表

最近查到的一个关键根因是：

- 某些解压失败任务之前只会 `fail`
- 但不会写入 `conflict_works`
- 导致前端“问题作品”页面看起来像没记录

目前已明确收口为：

- `backend/app/core/task_engine.py`
  - 解压失败会写入一条 `EXTRACT_FAILED`
- `backend/app/core/classifier.py`
  - 去重时对无 RJ 记录会回退用 `new_path`
- `backend/app/core/conflict_resolution_service.py`
  - 会按问题类型动态下发可用动作
  - `EXTRACT_FAILED` 默认只允许 `SKIP`
- `frontend/src/views/Conflicts.vue`
  - 解压失败项不再沿用重复作品界面
  - 会单独显示失败原因和失败提示

后续如果用户反馈“问题作品没显示”，先检查：

1. 解压失败有没有落 `conflict_works`
2. `available_actions` 是否被后端正确下发
3. 前端是不是把 `EXTRACT_FAILED` 误当重复项渲染

### 3. 保留新版 / 跳过 / 合并 重构现状

当前问题作品顶层动作已经收敛为：

- `KEEP_NEW`
- `SKIP`
- `MERGE`

最近相关主要入口：

- `frontend/src/views/Conflicts.vue`
- `frontend/src/components/conflicts/ConflictMergeWorkbench.vue`
- `frontend/src/api/index.js`
- `backend/app/api/routes.py`
- `backend/app/core/conflict_resolution_service.py`
- `backend/app/core/folder_compare_service.py`

最近明确落地过的点：

- `KEEP_OLD` 在新链路里已视为兼容别名，不应继续作为顶层动作暴露
- `KEEP_NEW` 会先走删除预审 / 删除确认
- `MERGE` 不再是“简单并存”，而是进入文件级工作台
- 远程落地已接到 `library_manager.py`
  - 包括阶段目录上传
  - 远程 copy/move
  - 备份切换

### 4. 库存页真实搜索现状

库存页搜索最近已从“当前页过滤”改成“真实搜索”。

当前正确目标：

- 本地库：
  - 用户主动搜索时走真实递归搜索
  - 平时浏览仍走轻量目录列表
- 远程库：
  - 只能走群晖搜索接口
  - 不要再用本地递归全盘扫作为远程搜索兜底

最近已明确做过的点：

- `frontend/src/views/Library.vue`
  - 搜索命中文件名高亮
  - 搜索结果可“定位”到真实目录
  - 搜索结果进入目录后，必须退出搜索态，不能串台
  - “命中路径”列已移除，保留命中文件名即可
- `backend/app/core/library_manager.py`
  - 本地搜索只在搜索时触发
  - RJ 搜索会折叠到最近的 RJ 文件夹
  - 远程搜索现在只走群晖接口
  - 当搜索根是 `/` 时，不应只对 `/` 搜一次
  - 应改为：
    1. `list_share`
    2. 对每个 share 分别调用群晖搜索接口
    3. 再汇总结果

后续必须记住：

- 远程搜索如果再出问题，优先排查：
  - `SYNO.FileStation.Search` 对当前路径是否生效
  - 根目录 `/` 是否需要按 share 拆分搜索
  - 返回字段里到底是 `path`、`real_path` 还是别的字段
- 不要再把远程搜索退回到“我们自己递归扫盘”

### 5. 库存统计口径现状

最近已经确认过一个高频误区：

- 用户在资源管理器看到的目录属性大小
- 不一定等于库存统计显示的“当前库统计”

原因通常是：

- 用户看的只是某个子目录
- 库存统计算的是整个库存根目录 / browse root

后续排查时先确认：

1. 当前库存根路径到底是什么
2. `browse_root_path` 和 `root_path` 是否一致
3. 用户截图看的是否是根目录，还是根目录下的子目录

不要第一时间假设“统计接口算错了”。

### 6. 这轮最低验证记录

本轮最近已执行过：

- `py -3 -m py_compile backend/app/core/extract_service.py backend/app/core/file_processor.py backend/app/core/task_engine.py backend/app/core/rename_service.py backend/app/core/library_manager.py backend/app/api/routes.py`
- `npm.cmd run build`

如果后续继续修改这些链路，至少重复上述两类验证。
