# KikoeruManager 性能瓶颈检查报告

检查日期：2026-06-09  
检查方式：静态代码审计 + 当前 `data/cache.db` 表规模抽样 + 本地日志关键字检索。  
边界：这不是压测报告；没有启动完整业务压测，也没有访问真实 NAS / 下载源做吞吐测试。

## 结论

当前系统已经做过一轮性能治理，不是原始状态：

- 后端有 SQLite WAL / busy timeout / QueuePool，见 `backend/app/models/database.py:1603`、`backend/app/models/database.py:1638`。
- 已有资源预算服务，资源维度包括 `disk_io_local`、`archive_cpu`、`remote_fs`、`network_download`、`sqlite_write`，见 `backend/app/core/resource_budget_service.py:24`。
- 已有慢 API 日志和资源预算快照，阈值默认 0.5s，见 `backend/app/api/routes.py:1700`、`backend/app/api/routes.py:1771`。
- 已有任务阶段指标接口，见 `backend/app/api/routes.py:3176`。
- 前端路由已经懒加载，见 `frontend/src/router/index.js:4`；Vite 已有 manual chunks，见 `frontend/vite.config.js:60`。

真正的瓶颈集中在四处：

1. 任务中心物化表已经有，但 summary 路径默认不启用，请求仍可能回到运行期聚合。
2. 前端把多个巨型工作台 keep-alive 常驻，内存、watcher 和激活/切换成本偏高。
3. 资源预算覆盖面比旧审计好，但默认值仍偏“吞吐优先”，多下载源 + 解压 + 远程库同时跑时会互相抢 IO / 网络。
4. 可观测性入口有了，但当前本地样本太少，缺少持续的 p95 / 任务阶段数据，后续优化容易重新变成猜。

## 当前本地数据

当前数据库：`data/cache.db`，大小约 103.84 MiB。

| 表 | 行数 |
|---|---:|
| `activity_logs` | 3651 |
| `task_center_items` | 373 |
| `activity_log_rollups` | 31 |
| `task_phase_metrics` | 93 |
| `library_index_entries` | 7 |
| `library_index_status` | 1 |
| `conflict_works` | 352 |
| `circle_works` | 4983 |
| `work_metadata` | 8634 |

`task_phase_metrics` 当前样本很少，只有 93 行。最大耗时是一条 `http_download / network_download / partial_failed`，`duration_ms=74216`；百度网盘样本都是 6 字节级测试数据，不能代表真实下载性能。

本地日志没有检索到新的慢 API / 慢 SQL 记录；只能说明当前日志样本没有覆盖高压业务，不代表线上没有慢点。

## P0：任务中心物化路径没有默认启用

### 证据

- `task_center_items` 表已经存在，本地有 373 行。
- 物化列表服务存在，见 `backend/app/core/task_center_materialization_service.py:247`。
- 但 `/api/task-center/list` 的 summary 模式只有在 `KIKOERUMANAGER_TASK_CENTER_MATERIALIZED_SUMMARY=1` 时才走物化，见 `backend/app/core/task_center_service.py:2001`。
- 默认路径仍会 `_build_all_items()`，见 `backend/app/core/task_center_service.py:2017`。

### 影响

任务中心、仪表盘、后台任务卡片都依赖这条链。活跃任务、等待重试、问题作品、pending import 一多，请求期聚合会变成 CPU 峰值，表现为任务页刷新慢、SSE 推送后 UI 更新抖动。

### 建议

- 把物化 summary 从环境变量改成配置项，默认开启。
- 启动时如果 `task_center_items` 为空，触发一次轻量 backfill。
- 保留旧聚合路径作为 fallback，并定期跑 diff。
- detail 模式暂时可以不物化，先稳住列表和 Dashboard。

优先改动文件：

- `backend/app/core/task_center_service.py`
- `backend/app/core/task_center_materialization_service.py`
- `backend/app/api/routes.py`
- `frontend/src/views/Tasks.vue`

## P0：巨型工作台 keep-alive 常驻

### 证据

前端最大文件：

| 文件 | 行数 |
|---|---:|
| `frontend/src/views/Library.vue` | 15446 |
| `frontend/src/views/CircleCompletion.vue` | 6470 |
| `frontend/src/App.vue` | 6342 |
| `frontend/src/views/Conflicts.vue` | 4777 |
| `frontend/src/views/ASMRSync.vue` | 3462 |
| `frontend/src/components/subtitle-import/SubtitleImportWorkbench.vue` | 3015 |

`App.vue` 对 `cachedViews` 使用 `<keep-alive>`，见 `frontend/src/App.vue:185`、`frontend/src/App.vue:266`。路由里大量页面 `cache: true`，见 `frontend/src/router/index.js:29`、`frontend/src/router/index.js:49`、`frontend/src/router/index.js:59`、`frontend/src/router/index.js:69`、`frontend/src/router/index.js:79`、`frontend/src/router/index.js:89`、`frontend/src/router/index.js:99`、`frontend/src/router/index.js:113`、`frontend/src/router/index.js:123`、`frontend/src/router/index.js:143`。

### 影响

库存、社团补全、问题作品、ASMR 同步、设置等页面会在访问后保留组件实例。它们内部的 computed、watch、定时器、弹窗状态和大数组如果没有在 `deactivated` 暂停，就会形成长期内存和 CPU 压力。

### 建议

- 给 `<keep-alive>` 加 `max`，先设 3 或 4。
- 只缓存确实需要保留工作状态的页面；`Settings`、`LibraryBackup` 这类低频页面不建议常驻。
- 所有重型页面补 `onActivated/onDeactivated`，暂停轮询、SSE 以外的定时器、拖拽监听和测量 RAF。
- `Library.vue` 优先拆出文件表、选择框选、右键菜单、路径栏、批量操作、字幕工作台入口，降低单组件响应式图规模。

优先改动文件：

- `frontend/src/App.vue`
- `frontend/src/router/index.js`
- `frontend/src/views/Library.vue`
- `frontend/src/views/CircleCompletion.vue`
- `frontend/src/views/Conflicts.vue`

## P1：资源预算默认值仍偏乐观

### 证据

默认资源预算：`disk_io_local=2`、`archive_cpu=0`、`remote_fs=4`、`network_download=5`、`sqlite_write=1`，见 `backend/app/config/settings.py:508` 到 `backend/app/config/settings.py:515`。

`archive_cpu=0` 在资源预算里等价于不加全局限制；解压仍有自己的 semaphore，但它只管解压链路。网络下载预算默认 5，同时还存在 HTTP、ASMR、百度、PikPak、Google Drive、Transfer.it 等多入口。

已接入预算的关键链路：

- 解压 / 探测：`backend/app/core/extract_service.py:1537`、`backend/app/core/extract_service.py:6330`。
- 群晖远程操作：`backend/app/core/library_manager.py:733`、`backend/app/core/library_manager.py:1519`。
- 库存索引写入 / 远程 rebuild：`backend/app/core/library_index/snapshot_store.py:139`、`backend/app/core/library_index/service.py:273`。
- HTTP 直连下载：`backend/app/core/http_download_service.py:4518`、`backend/app/core/http_download_service.py:4768`。
- 百度 PCS-Go：`backend/app/core/baidu_netdisk_service.py:3957`。
- ASMR 下载：`backend/app/core/asmr_download_service.py:675`。
- activity log 写入：`backend/app/core/activity_log_writer.py:150`。

### 影响

默认配置在 SSD + 本地库上问题不大，但在 HDD、Docker 单盘、NAS 远程库、代理下载混跑时，仍可能出现长尾卡顿：

- 下载占满网络出口时，字幕/元数据/远程库请求会变慢。
- 解压 + 备份 + 本地上传同时跑时，磁盘队列变长。
- 远程索引 rebuild 占用 `remote_fs` 权重 2，配合目录浏览 / 上传 / 问题作品统计，NAS FileStation 仍可能顶满。

### 建议

- Docker / NAS 默认配置更保守：`disk_io_local=1`、`remote_fs=2`、`network_download=3`。
- `archive_cpu` 不建议默认 0；设为当前解压并发上限，避免不同解压子链路绕过全局预算。
- 设置页展示当前 active / waiting 预算，用户能看到“卡在等资源”。
- 慢 API 日志里已经带 `resource_budget`，后续按 slow log 反推默认值。

优先改动文件：

- `backend/config/config.yaml`
- `backend/app/config/settings.py`
- `frontend/src/components/settings/ProcessingSettingsPanel.vue`
- `backend/app/core/resource_budget_service.py`

## P1：远程 FS 熔断只有“短路”，缺少延迟分布

### 证据

群晖客户端已有失败短路：

- 失败记录：`backend/app/core/library_manager.py:671`
- 短路检查：`backend/app/core/library_manager.py:690`
- 健康快照：`backend/app/core/library_manager.py:698`
- 系统接口：`backend/app/api/routes.py:3170`

测试覆盖也存在：`backend/tests/test_synology_remote_health.py:7`。

### 影响

当前能防“连续 timeout 把系统拖死”，但还不能回答：

- 哪个库最慢？
- 是 list 慢、search 慢、upload 慢还是 dir_size 慢？
- p95 是多少？
- 最近 5 分钟是否降级？

所以用户反馈“库存页卡”时，仍然要翻日志或复现。

### 建议

- 按 `profile_id / library_id / api` 记录最近 100 次 latency ring buffer。
- health snapshot 输出 avg / p95 / timeout_count / circuit_remaining。
- `/api/conflicts`、库存全局搜索、RemoteFolderPicker 在 `remote_degraded` 时减少并发和自动重试。

优先改动文件：

- `backend/app/core/library_manager.py`
- `backend/app/api/routes.py`
- `frontend/src/components/common/RemoteFolderPickerDialog.vue`
- `frontend/src/views/Library.vue`

## P1：下载 / 上传进度仍有多套写法

### 证据

统一 `Task.update_progress()` 已有重复进度节流和落库压缩，见 `backend/app/core/task_engine.py:313`、`backend/app/core/task_engine.py:426`。

但仍有不少链路绕开或半绕开：

- 百度上传/下载直接 `task.mark_changed("progress")` 并维护 120 条 `progress_log`，见 `backend/app/core/baidu_netdisk_service.py:4729`、`backend/app/core/baidu_netdisk_service.py:4740`。
- HTTP 下载对 Google Drive / Transfer.it 各自维护 progress callback，见 `backend/app/core/http_download_service.py:4605`、`backend/app/core/http_download_service.py:4963`。
- RJ 字幕、社团补全、ASMR 下载在 `task_engine.py` 内部还有多个本地 `append_progress_log()`。

### 影响

高频下载或批量任务时，任务中心 SSE、materialized item 更新、activity log / task metadata 写入会被进度事件放大。虽然现在已经比旧版本好，但不是统一模型。

### 建议

- 抽一个 `ProgressThrottler`，统一按 `min_interval + min_percent_delta + terminal_force` 控制。
- `append_progress_log()` 不要散落在业务函数里，改成 Task 方法或 task event helper。
- `progress_log` 运行期保留 60 条，落库保留关键 24 条；百度当前 120 条偏高。
- 所有下载平台统一输出 `{downloaded,total,speed,status,row_id}`，Task 层统一合成进度。

优先改动文件：

- `backend/app/core/task_engine.py`
- `backend/app/core/http_download_service.py`
- `backend/app/core/baidu_netdisk_service.py`
- `backend/app/core/asmr_download_service.py`

## P1：库存统计仍有 os.walk 兜底路径

### 证据

已有很多地方改成优先走库存索引，例如库存统计明确“只允许走索引”，见 `backend/app/core/library_manager.py:8058`。

但仍有必须注意的扫描路径：

- 备份 manifest 仍要 `os.walk` 构建文件清单，见 `backend/app/core/backup_zip_service.py:708`。
- 备份大小先尝试库存索引，失败后 `os.walk`，见 `backend/app/core/backup_zip_service.py:939`。
- 操作历史补 size 有 `_safe_path_size()`，虽然有 50000 项保护，但仍会扫盘，见 `backend/app/core/activity_log_service.py:203`。

### 影响

大库存、慢盘、远程映射盘上，备份和历史补录可能造成长时间 IO 抢占。当前已有资源预算包裹备份扫描，但“是否扫盘”本身仍是高成本动作。

### 建议

- 备份 manifest 尽量复用 `library_index_entries`，只对索引缺失或 stale 的路径补扫。
- `_safe_path_size()` 对库存路径优先查索引，不直接 `os.walk`。
- 后台维护任务默认 time budget，避免一次修历史扫完整库。

优先改动文件：

- `backend/app/core/backup_zip_service.py`
- `backend/app/core/activity_log_service.py`
- `backend/app/core/library_index/`

## P2：路由安全状态每次跳转都请求

### 证据

`router.beforeEach` 每次非 gate 路由都调用 `securityGateApi.status()`，见 `frontend/src/router/index.js:188`、`frontend/src/router/index.js:194`。

### 影响

安全网关启用时，页面切换要等一个 API 往返。平时本地很快，但后端卡顿时会放大成“前端路由卡住”。

### 建议

- 给 status 加 5 到 15 秒短 TTL。
- 收到安全网关事件或 401/403 时主动失效。
- gate 页面仍强制实时请求。

优先改动文件：

- `frontend/src/router/index.js`
- `frontend/src/api/index.js`
- `backend/app/core/security_gate_service.py`

## P2：App 全局样式和页面样式混在一起

### 证据

`frontend/src/App.vue` 6342 行，里面包含大量页面暗黑样式，例如 `.library`、`.activity-page`、`.settings-page` 等选择器，见 `frontend/src/App.vue:1464`、`frontend/src/App.vue:4712`。

### 影响

这不一定直接导致运行期慢，但会拖慢 HMR、增加 CSS cascade 匹配和维护成本。每次改一个页面样式都可能影响全局。

### 建议

- 页面专属样式回迁到页面组件或 `dark-mode.css` 对应分区。
- `App.vue` 只保留壳、侧边栏、通用 dialog focus reset。
- 拆样式时不要一次性重构，按页面迁移并浏览器验证。

## 不建议优先做

- 不建议现在把 SQLite 换 PostgreSQL。当前数据量 10 万级以内时，主要问题不是数据库类型，而是请求期聚合、进度事件和 IO 背压。
- 不建议盲目提高并发。这个项目瓶颈大多是磁盘、NAS、下载源和子进程，提高并发通常只会把平均吞吐换成长尾卡顿。
- 不建议先做纯视觉重构。库存页和问题作品交互复杂，视觉重构不能解决任务中心聚合和 IO 背压。

## 推荐执行顺序

### 第一批：低风险、收益直接

1. 默认启用任务中心 summary 物化，并在设置页展示是否命中物化。
2. `<keep-alive>` 加 `max=3`，并取消缓存低频重型页。
3. 安全网关 status 增加短 TTL。
4. 把 resource budget 当前 active / waiting 展示到处理设置页。

### 第二批：核心运行瓶颈

1. `ProgressThrottler` 统一下载、上传、字幕、社团补全进度。
2. 远程 FS health 增加 per-api latency/p95。
3. NAS / Docker 模式下默认降低资源预算。
4. 备份 manifest 复用库存索引。

### 第三批：结构治理

1. 拆 `Library.vue`，先拆表格和框选/拖拽逻辑。
2. 拆 `CircleCompletion.vue` 和 `Conflicts.vue` 的详情/列表/弹窗。
3. 把 `App.vue` 页面专属暗黑样式迁出。
4. activity rollup 从“写入时重算 group”逐步改成增量计数。

## 需要补的压测

这些是下一轮要拿数据确认的指标：

- `/api/task-center/list?mode=summary`：物化开/关，active 任务 10/100/500 的 p95。
- `/api/activity-logs?lite=true`：activity_logs 1 万 / 10 万 / 50 万行的 p95。
- `/api/conflicts?include_stats=true`：本地库 / 群晖正常 / 群晖超时三场景。
- 库存页：打开 1 万文件目录、搜索、框选、右键菜单、移动弹窗的 FPS 和内存。
- 下载：HTTP / Google Drive / Transfer.it / 百度 / ASMR 同时跑时，resource budget active/waiting、任务中心 SSE 频率、SQLite 写入次数。
- 解压：SSD / HDD / NAS 下 `archive_cpu` 不同默认值的吞吐和 API p95。

