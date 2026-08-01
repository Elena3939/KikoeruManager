# 关联字幕补配开发手册

本文档用于后续新线程直接接手实现“关联作品命中特授字幕补配分支”。
时间基线：2026-03-24。

## 1. 功能目标

这个功能不是独立于解压流程的新系统，而是“正常解压队列中的特授分支”。

- 正常解压任务先进入现有预检查重。
- 如果只是同 RJ 直接重复，维持原逻辑。
- 如果命中“关联作品已在库中”，并且库中存在原作品目录，但原作品当前没有字幕，则继续判断：
  - 当前待处理 RJ 是否为翻译作品
  - 当前压缩包内部是否包含字幕
- 若满足条件：
  - 不走普通冲突处理
  - 不解压整包
  - 只提取字幕文件
  - 按现有 RJ 字幕链路的过滤、去重、合并、写入规则，将字幕写入目标原作品的 `subtitles/`
  - 生成一条待人工配对任务
  - 点击任务后直接进入现有字幕工作台下半区，让用户配对字幕和音声
  - 导入成功后原压缩包按“已处理”归档
- 若开关关闭、不满足条件、定位不到目标目录、或执行失败：
  - 回退到原问题队列逻辑

## 2. 用户已确认的最终口径

### 2.1 队列定位

- 这个功能仍属于正常解压队列的一部分
- 它是特殊授权分支，不是旁路流程

### 2.2 导入成功后的压缩包处理

- 如果导入成功，原压缩包按“已处理”归档
- 不要同时残留在问题队列中

### 2.3 新页面命名

- 侧边栏新入口名称：`字幕补配`

### 2.4 远程库存目标定位

远程库使用项目内现有群晖查询能力，流程固定如下：

1. 从 DLsite 获取关联作品链，拿到原作品 RJ
2. 查询 Kikoeru 服务器
3. 如果 Kikoeru 上该原作品 RJ 已有字幕，不走这个特授分支
4. 如果 Kikoeru 上该原作品 RJ 没字幕，则把该原作品 RJ 提取出来
5. 通过项目内群晖查询接口搜索该 RJ 所在目录
6. 若命中 1 个本地目录，则直接作为目标目录
7. 若命中 0 个目录，则回问题队列
8. 若命中多个目录，第一版不要自动猜，转到 字幕补配 页让用户手动选择目标目录(给出两个目录的文件夹树以及文件夹大小的信息方便判断)
9. 定位目标目录后，把提取出的字幕上传到该目录的 `subtitles/`
10. 然后生成待人工匹配任务

### 2.5 本地库存目标定位

本地库存不走群晖接口，流程固定如下：

1. 从 DLsite 获取关联作品链，拿到原作品 RJ
2. 直接使用项目内本地库存查询能力搜索该原作品 RJ
3. 若命中 1 个本地目录，则直接作为目标目录
4. 若命中 0 个目录，则回问题队列
5. 若命中多个目录，第一版不要自动猜，转到 字幕补配 页让用户手动选择目标目录(给出两个目录的文件树以及文件夹大小的信息方便判断)
6. 定位目标目录后，把提取出的字幕写入该目录的 subtitles/
7. 然后生成待人工匹配任务
## 3. 现有代码基础

后续实现必须优先复用以下文件与能力，不要重新造轮子。

### 3.1 后端主链路

- 解压主流程：
  - `backend/app/core/task_engine.py`
- 解压器、压缩包目录读取、密码策略：
  - `backend/app/core/extract_service.py`
- 解压前重复检查：
  - `backend/app/core/classifier.py`
- 关联作品分析：
  - `backend/app/core/duplicate_service.py`
- DLsite 翻译链与原作识别：
  - `backend/app/core/dlsite_service.py`

### 3.2 字幕链路

- RJ 字幕处理主服务：
  - `backend/app/core/rj_subtitle_service.py`
- 本地/远程 `subtitles/` 写入、同名覆盖、等价名迁移、内容去重：
  - 已在 `rj_subtitle_service.py` 内实现

### 3.3 远程库存

- 群晖搜索、最近 RJ 目录折叠、远程上传、远程目录操作：
  - `backend/app/core/library_manager.py`

### 3.4 API

- RJ 字幕相关接口：
  - `backend/app/api/routes.py`

### 3.5 前端工作台

- 库存页 RJ 字幕工作台：
  - `frontend/src/views/Library.vue`
- 工作台下半区组件：
  - `frontend/src/components/library/SubtitleInspectorWorkbench.vue`
- 路由：
  - `frontend/src/router/index.js`
- 侧边栏：
  - `frontend/src/App.vue`

### 3.6 配置

- 配置模型：
  - `backend/app/config/settings.py`
- 默认配置模板：
  - `backend/config/config.yaml`

## 4. 最终行为定义

### 4.1 主流程判断

正常解压任务在预检查重时，除了原有逻辑外，还要支持判断以下特授条件：

- 当前作品属于翻译作品
- 关联链中存在原作品
- 库中存在原作品目录
- 原作品目录当前没有字幕
- 当前压缩包中存在字幕
- 自动特授开关已开启

全部满足时，进入“关联字幕补配导入分支”。

### 4.2 导入分支行为

- 不解压整包
- 只提取字幕文件
- 只允许字幕文件进入后续流程
- 提取出来的字幕仍要继续走现有规则：
  - 字幕过滤规则
  - 内容去重
  - 同名/等价名合并
  - 本地 `subtitles/` 写入规则
  - 远程群晖 `subtitles/` 写入规则

### 4.3 任务行为

- 导入成功后生成待人工匹配任务
- 继续复用 `TaskType.RJ_SUBTITLE_FETCH`
- 通过 `task_metadata.source_mode` 区分来源
- 点击任务后仍进入现有字幕工作台下半区

### 4.4 手动入口

新增侧边栏页面 `字幕补配`，支持：

- 压缩包补配
- 字幕文件夹补配

其中“字幕文件夹补配”用于支持用户手动放入一个以 RJ 命名的文件夹，或其中包含 `subtitles` 文件夹时，直接进行匹配上传。

## 5. 建议新增的数据字段

### 5.1 配置字段

在 `auto_process` 下新增：

- `import_linked_translation_subtitles: false`

在 `rj_subtitle` 下新增：

- `auto_import_use_filter_rules: true`
- `auto_import_filter_rules: []`

说明：

- 自动流程不能依赖前端 `localStorage`
- 自动流程使用的字幕过滤规则必须进入后端配置
- 手动页可以继续保留前端临时编辑，但自动流程必须有后端稳定配置

### 5.2 任务元数据字段

建议在 `task_metadata` 中新增：

- `source_mode`
- `target_rjcode`
- `target_folder_path`
- `target_library_id`
- `source_archive_path`
- `import_reason`
- `awaiting_manual_match`
- `kikoeru_checked_rjcode`
- `kikoeru_has_subtitle`

建议的 `source_mode` 值：

- `remote_fetch`
- `linked_translation_archive_import`
- `subtitle_folder_import`

## 6. 建议新增的服务结构

新增文件：

- `backend/app/core/linked_subtitle_import_service.py`

职责：

- 判断是否命中特授条件
- 从压缩包目录读取字幕候选
- 调用选择性解压，只提字幕
- 调用现有字幕过滤、去重、写入能力
- 返回可以直接转换成 RJ 字幕任务状态的数据结构

不要把完整业务直接堆进 `task_engine.py`。

## 7. 后端修改说明

### 7.1 `backend/app/config/settings.py`

需要修改：

- `AutoProcessConfig`
  - 增加 `import_linked_translation_subtitles: bool = False`
- `RJSubtitleConfig`
  - 增加 `auto_import_use_filter_rules`
  - 增加 `auto_import_filter_rules`
- 配置加载兼容逻辑
  - 补旧配置默认值

要求：

- 兼容旧配置文件
- 不破坏现有字段

### 7.2 `backend/config/config.yaml`

需要修改：

- 增加上述默认模板字段

要求：

- 只改仓库模板
- 不写入用户真实敏感配置

### 7.3 `backend/app/core/extract_service.py`

需要新增能力：

- 从压缩包目录列表中按条目选择性解压

建议新增方法：

- `extract_selected_entries(...)`

要求：

- 不重写现有密码逻辑
- 沿用当前 7z 检测、密码库、RJ 推测密码逻辑
- 只解压字幕扩展名和字幕目录内文件
- 支持保留原有相对路径结构
- 输出到临时目录

备注：

- 现有 `_get_archive_info()` 已支持“先读取压缩包目录，不直接解压”
- 这是做选择性解压的基础

### 7.4 `backend/app/core/classifier.py`

当前问题：

- `check_duplicate_before_extract()` 只返回 `bool`
- 对特授流程来说信息量不够

建议：

- 改为返回结构化结果，而不是单纯 `bool`

建议至少包含：

- `is_duplicate`
- `conflict_type`
- `linked_original_rjcode`
- `linked_original_path`
- `linked_original_library_id`
- `can_try_subtitle_import`

要求：

- 保留原有问题队列兼容逻辑
- 让 `task_engine` 能基于结果做特授分支判断

### 7.5 `backend/app/core/duplicate_service.py`

需要补强：

- 让主流程更直接获得：
  - 当前 RJ 是否翻译作
  - 关联原作 RJ
  - 库中原作路径
  - 语言信息
  - 当前冲突是否满足“原作存在但无字幕”的判断前提

建议：

- 继续复用现有 `LinkedWork`、`DuplicateCheckResult`
- 可以新增更方便 `task_engine` 使用的分析辅助方法

### 7.6 `backend/app/core/library_manager.py`

远程库存第一版继续复用现有搜索能力，不要新造一套群晖搜索。

要求：

- 使用现有群晖搜索接口按原作 RJ 搜目标目录
- 若命中 1 个目录则直接使用
- 若命中多个目录则返回候选列表，由前端人工选
- 若 0 命中则回问题队列

### 7.7 `backend/app/core/rj_subtitle_service.py`

不要重写核心流程。

需要做的是抽出现有可复用能力，支持“本地已提取字幕源 -> 写入目标作品 `subtitles/`”：

- 过滤
- 内容去重
- 本地写入
- 远程写入

优先复用现有内部方法：

- `_write_local_downloaded_subtitles`
- `_write_remote_downloaded_subtitles`
- `_dedupe_downloaded_subtitles_by_content`
- 等价名迁移相关逻辑

必要时新增一个面向“导入型来源”的统一入口方法。

### 7.8 `backend/app/core/task_engine.py`

这是主接入点。

要求：

- 在正常解压的预检查重之后接入特授逻辑
- 分支规则：
  - 开关关闭：维持原逻辑
  - 开关开启但不满足条件：维持原逻辑
  - 开关开启且满足条件：进入 `linked_subtitle_import_service`
- 导入成功：
  - 生成待人工匹配任务
  - 主解压任务按成功处理
  - 原压缩包进入已处理归档
- 导入失败：
  - 记录日志
  - 回问题队列

注意：

- 不要成功导入后又把同一压缩包丢进问题队列

### 7.9 `backend/app/api/routes.py`

需要新增或扩展接口，服务于新页面 `字幕补配`。

建议接口能力：

- 压缩包预检导入
- 字幕文件夹预检导入
- 远程目标目录搜索
- 创建导入型 RJ 字幕任务
- 查询导入任务状态

RJ 字幕状态接口也要扩展输出字段：

- `source_mode`
- `target_rjcode`
- `target_folder_path`
- `target_library_id`
- `source_archive_path`

## 8. 前端修改说明

### 8.1 新页面

新增：

- `frontend/src/views/SubtitleImport.vue`

页面名称：

- `字幕补配`

建议分成两种入口：

- `压缩包补配`
- `字幕文件夹补配`

### 8.2 路由

在：

- `frontend/src/router/index.js`

新增路由：

- `/subtitle-import`

### 8.3 侧边栏

在：

- `frontend/src/App.vue`

新增菜单项：

- `字幕补配`

### 8.4 工作台复用原则

不要复制一整份 `Library.vue` 的字幕工作台状态。

必须先把与字幕检查/匹配相关的状态和动作抽成 composable 或共享逻辑层，再让：

- 库存页
- 新的 `字幕补配` 页

共同复用。

现有可复用目标主要是：

- 字幕树检查
- 批量删除
- 音频/字幕顺序点选配对
- 手动配对应用

### 8.5 页面第一版能力

第一版前端建议只覆盖：

- 输入压缩包路径或选择待处理压缩包
- 展示识别结果：
  - 当前翻译作 RJ
  - 目标原作 RJ
  - 目标库
  - 本地/远程
  - Kikoeru 是否无字幕
- 若远程搜索多命中，展示目标目录候选供用户选择
- 执行导入
- 执行完成后，在当前页面下方直接进入配对工作台

## 9. 远程库存行为规则

### 9.1 单命中

- 群晖搜索命中 1 个目标目录
- 直接作为目标目录

### 9.2 零命中

- 直接回问题队列

### 9.3 多命中

- 第一版不要自动猜目录
- 进入 `字幕补配` 页让用户手动选目标目录

### 9.4 Kikoeru 已有字幕

- 不走这个特授分支
- 维持原重复作品处理逻辑

## 10. 本地库存行为规则

### 10.1 查询方式

- 本地库存不要走群晖接口
- 直接使用项目内已有的本地库存搜索能力按原作 RJ 查找目标目录

### 10.2 单命中

- 本地搜索命中 1 个目标目录
- 直接作为目标目录

### 10.3 零命中

- 直接回问题队列

### 10.4 多命中

- 第一版不要自动猜目录
- 进入 字幕补配 页让用户手动选目标目录

## 11. 必须覆盖的边界条件

- 压缩包内没有字幕
- 目标原作目录不存在
- 目标原作目录已存在字幕
- 目标目录中没有音频
- 群晖搜索零命中
- 群晖搜索多命中
- Kikoeru 查询失败
- 选择性解压失败
- 字幕上传 0 个
- 字幕写入部分成功、部分失败

建议策略：

- 目标目录无音频：不要生成待配对任务
- 写入 0 个：视为失败
- 写入部分成功：允许生成任务，但必须在日志中明确为 partial

## 12. 任务日志建议

自动分支必须打清楚这些日志，避免后续排查困难：

- `命中关联作品冲突`
- `当前作品为翻译作`
- `目标原作 RJ`
- `目标原作当前无字幕`
- `压缩包内检测到字幕数`
- `过滤后保留数`
- `内容去重合并数`
- `写入数`
- `等待人工配对`
- `来源模式 linked_translation_archive_import`

## 13. 推荐实施顺序

1. 配置模型和默认配置补字段
2. 预检查重结果结构化
3. `extract_service` 选择性提字幕能力
4. 新增 `linked_subtitle_import_service`
5. `task_engine` 接入自动分支
6. RJ 字幕状态接口扩展
7. 抽字幕工作台共享逻辑
8. 新增 `字幕补配` 页面和侧边栏入口
9. 补远程多命中人工选择流程
10. 做完整验证

## 14. 最低验证要求

### 13.1 后端

至少执行：

```powershell
py -3 -m py_compile backend/app/api/routes.py backend/app/core/task_engine.py backend/app/core/rj_subtitle_service.py backend/app/core/extract_service.py backend/app/core/linked_subtitle_import_service.py backend/app/config/settings.py
```

### 13.2 前端

至少执行：

```powershell
npm run build
```

### 13.3 手工验证

至少覆盖：

- 本地库：关联原作无字幕，翻译包内含字幕，自动导入成功
- 远程群晖库：Kikoeru 无字幕，群晖搜索命中单目录，上传成功
- 远程群晖库：群晖搜索多目录，转人工选择
- 压缩包无字幕，正确回问题队列
- 目标原作已有字幕，不走特授分支
- 导入成功后点击任务，能直接进入字幕工作台下半区并完成配对

## 15. 对新线程的执行要求

新线程接手时建议先做这件事：

- 先按本手册做详细实现计划，不要直接开改
- 先确认：
  - 文件改动范围
  - 数据结构
  - 回退策略
  - 多命中远程目录时的前后端交互
- 确认后再进入编码

## 16. 明确禁止事项

- 不要把这个功能做成独立于正常解压队列的旁路系统
- 不要成功导入后还把原压缩包留在问题队列
- 不要只依赖前端 `localStorage` 存自动流程过滤规则
- 不要重写一套新的字幕工作台 UI
- 不要绕开现有本地/远程 `subtitles/` 写入规则
- 不要恢复设置页里被移除的 RJ 字幕重复面板


