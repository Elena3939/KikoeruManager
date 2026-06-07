# KikoeruManager 系统瓶颈与优化优先级审计

审计日期：2026-06-07  
范围：后端 FastAPI/SQLite/任务引擎/库存索引/下载解压链路，前端 Vue 工作台/日志/任务中心/库存页。  
结论基准：只基于当前仓库代码和已有运行经验整理，没有跑压测；优先级按“用户体感收益 + 故障概率 + 改造风险”排序。

## 总结

当前系统不是“完全没做性能优化”的状态，很多一阶问题已经处理过：

- SQLite 已启用 QueuePool、WAL、busy_timeout、内存 temp/cache，见 `backend/app/models/database.py:1417`、`backend/app/models/database.py:1449`。
- 操作历史已经有 FTS5 搜索、lite 快速路径、5000 行合并窗口和查询缓存，见 `backend/app/api/routes.py:498`、`backend/app/api/routes.py:533`、`backend/app/api/routes.py:740`。
- 任务中心已经有 SSE + 30s fallback 轮询，不是粗暴 1s 轮询，见 `backend/app/api/routes.py:2165`、`frontend/src/views/Tasks.vue:124`、`frontend/src/views/Tasks.vue:126`。
- 库存索引已经用本地 `os.scandir`、远程群晖 Search、SQLite 批量 UPSERT，见 `backend/app/core/library_index/local_scanner.py:3`、`backend/app/core/library_index/remote_scanner.py:4`、`backend/app/core/library_index/snapshot_store.py:46`。
- 解压已经按磁盘类型/配置控制 7z 并发，见 `backend/app/core/extract_service.py:1277`、`backend/app/core/extract_service.py:1314`。

真正值得继续投的瓶颈集中在二阶问题：跨链路背压、审计/任务聚合的重算、远程 IO 的峰值控制、大文件任务的进度写入频率、前端大页面组件拆分与按需渲染。

## 优先级矩阵

| 优先级 | 优化项 | 收益 | 风险 | 主要影响面 |
|---|---|---:|---:|---|
| P0 | 给任务/下载/上传/解压/索引建立统一资源背压 | 很高 | 中 | 全局卡顿、NAS 压力、SQLite 锁等待 |
| P0 | 操作历史和任务中心改事件增量物化，减少请求期聚合 | 很高 | 中高 | ActivityHistory、Tasks、Dashboard |
| P0 | 远程库存/群晖操作加全局限流和熔断 | 高 | 中 | 库存页、问题作品、字幕、上传、索引 |
| P1 | 大文件 IO 缓冲和进度写入节流统一 | 高 | 中 | 解压、备份、HTTP/百度下载、上传 |
| P1 | 前端巨型页面拆分和懒加载 | 中高 | 中 | 首屏、HMR/build、页面切换 |
| P1 | 日志/任务流统一增量状态模型 | 中高 | 低中 | Logs、Tasks、Dashboard |
| P1 | SQLite 表增长治理和自动维护策略 | 中 | 低中 | activity_logs、notifications、task metadata |
| P2 | 构建体积和路由级 chunk 优化 | 中 | 低 | 前端发布包、启动速度 |
| P2 | 可观测性：慢查询/慢 IO/任务耗时指标面板 | 中 | 低 | 后续优化准确性 |

## P0-1 统一资源背压

### 现状

目前不同链路各自有局部并发控制：

- 解压 7z 有 `_get_7z_semaphore()`，配置来源在 `backend/app/core/extract_service.py:1277`、`backend/app/core/extract_service.py:1314`。
- 问题作品上下文构建固定 `asyncio.Semaphore(8)`，见 `backend/app/api/routes.py:4264` 附近。
- 远程库存索引每库 rebuild 有锁，但跨库/跨业务没有统一预算，见 `backend/app/core/library_index/service.py:178`。
- 百度 PCS-Go 有自己的 `max_parallel`、`max_download_load`，见 `backend/app/core/baidu_netdisk_service.py:3362`。
- 本地/远程库存操作里还有多个局部 semaphore，例如 `library_manager.py` 中 stat/upload/request 限制。

这些局部限制互相不知道：解压、上传、远程 stat、索引重建、HTTP 下载同时跑时，还是可能把同一块磁盘、NAS、SQLite 写事务或网络出口打满。

### 建议

新增一个后端全局 `ResourceBudgetService`，按资源维度发令牌：

- `disk_io_local`: 本地大文件读写、备份、嵌套解压复制、上传前扫描。
- `archive_cpu`: 7z/unar/lsar 子进程。
- `remote_fs`: 群晖 FileStation list/stat/search/upload/rename/delete。
- `network_download`: HTTP/PikPak/Google Drive/Gofile/百度下载。
- `sqlite_write`: 高频写入型任务 metadata、activity log、索引 bulk upsert。

接入方式不要大改任务引擎，先做小包裹：

```python
async with budget.acquire("remote_fs", weight=1, reason="conflict.describe"):
    return await resolution_service.describe_conflict_async(...)
```

配置层给默认值：

- SSD 本地：`disk_io_local=2~3`。
- HDD/NAS：`disk_io_local=1`。
- 群晖：`remote_fs=4`，Search/rebuild 单独占 2。
- archive：沿用当前解压并发探测结果，但接入全局预算。

### 收益

- 降低“多个工作台同时开工时整个系统卡死”的概率。
- 避免 NAS/FileStation 被并发 stat/search 拖到 60s+。
- SQLite WAL 已经缓解读写互斥，但统一控制写峰值能继续减少 `database is locked` 和响应抖动。

### 风险

- 中等。最大风险是令牌拿太保守导致吞吐下降。
- 需要避免死锁：所有链路只能短持有令牌，不要在持有 `sqlite_write` 时再等 `remote_fs`。

### 验证

- 同时启动 2 个解压、1 个远程索引、1 个百度下载、1 个问题作品页刷新。
- 记录 `/api/task-center/list`、`/api/conflicts`、`/api/activity-logs?lite=true` p95。
- NAS CPU/IO、SQLite busy 计数、任务平均吞吐。

## P0-2 操作历史和任务中心增量物化

### 现状

操作历史已经很努力地优化过：

- lite 路径跳过深度合并，见 `backend/app/api/routes.py:521`。
- 默认合并窗口限制 5000 行，见 `backend/app/api/routes.py:533`、`backend/app/api/routes.py:740`。
- 搜索强制 FTS5，避免 LIKE 全表扫，见 `backend/app/api/routes.py:244`、`backend/app/api/routes.py:612`。

任务中心也有缓存：

- detail TTL 1.2s，summary TTL 2.5s，pending/conflict/waiting retry 子缓存 3~5s，见 `backend/app/core/task_center_service.py:31` 到 `backend/app/core/task_center_service.py:37`。
- `_build_all_items()` 每次冷路径仍会重新序列化 engine tasks、pending、waiting retry、active conflicts，并跑多段 merge/dedupe/sort，见 `backend/app/core/task_center_service.py:1643`。

瓶颈不是单个查询，而是“请求期重新聚合”。记录越多、任务类型越多，聚合逻辑越容易变成 UI 刷新路径上的 CPU 尖刺。

### 建议

把“树形聚合结果”和“任务中心列表项”从请求期计算改成事件期物化：

1. activity log writer 写入时，同步/异步更新 `activity_log_rollups` 表。
2. task engine 状态变更时，写入 `task_center_items` 的当前快照。
3. API 列表只做 SQL 分页、过滤、轻量 join。
4. 老数据通过后台 backfill job 渐进重建。

最小落地切法：

- 先只物化任务中心 active/current items，不碰历史。
- 再物化 activity batch rollup：`batch_id -> child counts/status/latest_activity_at`。
- 最后替换 ActivityHistory 的非 lite 深度合并路径。

### 收益

- 任务中心和操作历史列表 p95 会更稳定。
- 大量历史记录时，性能不再依赖 5000 行窗口和复杂 Python merge。
- 更容易做 Dashboard 复用，避免多个页面重复聚合同一批状态。

### 风险

- 中高。聚合语义是业务核心，错了会出现历史树丢子任务、状态不一致。
- 要保留现有聚合器作为对照，至少一段时间双写 + diff。

### 验证

- 构造 10 万 activity_logs、1000 batch_id、100 active tasks。
- 对比旧聚合器和物化表输出。
- 跑 ActivityHistory、Tasks、Dashboard 三页面真实浏览器验证。

## P0-3 远程库存/群晖操作限流和熔断

### 现状

远程索引已经优先用群晖 Search，避免 SMB `os.scandir` 逐项网络 round trip，见 `backend/app/core/library_index/remote_scanner.py:4`。

但远程操作入口很多：

- 库存浏览/搜索/移动/删除。
- 问题作品 `describe_conflict_async(include_stats)`。
- 字幕远程扫描。
- 本地上传到远程库存。
- 库存索引 rebuild。

这些入口有局部保护，但缺一个“群晖当前健康状态”。如果凭据过期、FileStation 卡住、NAS 正在索引，多个页面会同时重试/轮询。

### 建议

新增 `RemoteFsHealth`：

- 按 `library_id` 记录最近错误码、超时率、p95 latency。
- 连续超时进入短熔断：30~120s 内只允许轻量 health probe。
- UI 收到 `remote_degraded` 后显示“远程库暂慢”，避免页面一直转。
- 所有远程 stat/list/search/upload/delete 都走同一个 client wrapper。

优先改：

1. `/api/conflicts` phase2 远程上下文。
2. 库存全局搜索 fallback，当前单库 fallback timeout 是 5s，见 `backend/app/api/routes.py:6022`、`backend/app/api/routes.py:6190`。
3. LibraryMoveDialog/RemoteFolderPicker 的远程目录浏览。

### 收益

- NAS 异常时系统不会整体被拖慢。
- 用户能知道“远程库慢/不可用”，而不是误以为应用卡死。
- 减少重复请求打爆 FileStation。

### 风险

- 中。熔断太激进会让可恢复请求被挡。
- 需要对手动操作提供“强制重试”。

## P1-1 大文件 IO 和进度写入节流

### 现状

大文件链路已经避免了明显的整文件读：

- 备份服务读 stdout 使用 64KB buffer，见 `backend/app/core/backup_zip_service.py:39`、`backend/app/core/backup_zip_service.py:623`。
- embedded ZIP payload copy 用 `copyfileobj(..., 8MB)`，见 `backend/app/core/extract_service.py:1415`。
- HTTP 下载里有流式写入，但 Google Drive 直连处仍可见 `response.content.read(1024)`，见 `backend/app/core/http_download_service.py:1996`；写盘点见 `backend/app/core/http_download_service.py:4446`。
- `Task.update_progress()` 每次都会追加 `progress_log`，限长 60 条，见 `backend/app/core/task_engine.py:293`。

问题是每条链路的 chunk size、flush 策略、progress 更新频率不统一。大文件下载/上传/解压时，如果每 KB 或每小步骤都写 metadata/log，就会放大 SQLite 写压力和前端事件风暴。

### 建议

统一三个工具：

- `stream_copy(src, dst, chunk_size, progress_interval_bytes, progress_interval_seconds)`。
- `ProgressThrottler(min_interval=0.75s, min_delta_percent=1)`。
- `TaskMetadataBufferedWriter(flush_interval=1s, terminal_flush=True)`。

优先替换：

1. HTTP 直连下载 chunk 从 1KB 提到 256KB~1MB，保留 Range resume 的边界校验。
2. 上传/下载任务 progress_log 通过 throttler 合并。
3. 备份 manifest/dir size 扫描复用库存索引已有 size/file_count，缺失时才扫盘。

### 收益

- 大文件任务吞吐更稳定。
- SQLite 写入和 SSE/UI 更新减少。
- 慢盘/NAS 上体感明显。

### 风险

- 中。下载恢复、校验、进度准确性要测。
- chunk 过大可能影响取消响应速度，建议 256KB~1MB，不要直接上 8MB 到所有网络流。

## P1-2 前端巨型页面拆分和懒加载

### 现状

大文件非常集中：

- `Library.vue`、`CircleCompletion.vue`、`Conflicts.vue`、`ASMRSync.vue`、`SubtitleImportWorkbench.vue` 都是超大工作台。
- `App.vue` 还包含大量全局样式和 3s 状态刷新，见 `frontend/src/App.vue:317`。
- 路由组件目前在 `App.vue` 直接 import 并映射，页面 chunk 不够细。

这些不一定导致运行期卡顿，但会造成：

- Vite build/HMR 慢。
- 首屏 bundle 偏大。
- 页面切换时一次性创建太多 watcher/computed。
- CSS cascade 难维护，样式冲突修复成本高。

### 建议

- 路由级 `defineAsyncComponent` / dynamic import。
- 工作台内部按“页头/工具栏/主列表/详情抽屉/弹窗”拆组件。
- 重型弹窗只在打开时挂载：`v-if="dialogVisible"`。
- 大列表统一虚拟化或分页，不要只在社团补全使用 virtual。
- 把 `App.vue` 内页面专属样式迁回对应 scoped 或页面 class 下，减少全局 cascade。

### 收益

- 启动和页面切换更轻。
- 后续样式 bug 少。
- build/HMR 速度改善。

### 风险

- 中。拆组件容易破坏现有选择/拖拽/右键上下文。
- 必须每拆一块就浏览器验证，尤其库存页。

## P1-3 日志/任务流进一步合并

### 现状

日志页已经用 SSE 增量，见 `backend/app/api/routes.py:3696`、`frontend/src/views/Logs.vue:1029`。

全历史搜索也有扫描预算：

- 跨文件总扫描 96MB，单文件 64MB，单页 1000，见 `backend/app/api/routes.py:3808`。

任务中心有 SSE，但 App 顶层仍每 3s 刷一次状态，见 `frontend/src/App.vue:317`；库存索引 badge 在 syncing 时 1.2s 轮询，见 `frontend/src/components/library/LibraryIndexBadge.vue:164`。

### 建议

- 把 App 顶层 `refreshStatus` 合并到任务中心 SSE 或一个 `/api/app/status-lite` 长轮询/SSE。
- 库存索引重建状态改成后台事件推送，fallback 轮询保留。
- 日志页进度行已经前端 compact，后端可进一步给 task progress 专门事件，普通日志只保留异常/关键节点。

### 收益

- 降低空闲请求数。
- 多页面同时打开时后端更安静。
- 移动端和 NAS Docker 部署更稳。

### 风险

- 低中。主要是断线重连和旧页面兼容。

## P1-4 SQLite 表增长治理

### 现状

已有维护入口：

- activity compact / estimate。
- FTS rebuild。
- database shrink。
- notification cleanup。

但这更像手动维护功能，不是完整策略。随着 `activity_logs.detail`、task metadata、notification outbox 增长，SQLite 文件、FTS、WAL checkpoint 都会影响响应。

### 建议

默认策略：

- activity_logs：90 天前自动压缩 detail，保留摘要和关键字段；失败/问题作品/用户手动动作保留更久。
- progress_log：任务完成后只保留关键节点，完整流写入归档日志文件。
- notification/outbox：按 retain_days + max_items 清理。
- FTS rebuild：检测 tokenizer/碎片状态后提示，不要频繁自动跑。

### 收益

- 长期运行不劣化。
- DB 文件和 FTS 表可控。

### 风险

- 低中。风险是误删诊断信息，策略必须按 category/status 白名单。

## P2-1 构建体积和 chunk 策略

### 建议

- `vite.config` 增加 manual chunks：`vendor-vue`、`vendor-ui`、`vendor-table`、`vendor-editor`、`vendor-lottie`。
- Tiptap/Block Editor、AG Grid/TanStack、Lottie 这类只在对应页面加载。
- 路由组件 dynamic import。

### 收益

- 首屏 JS 下降。
- 冷启动和缓存命中更好。

### 风险

- 低。主要验证构建产物和路由懒加载。

## P2-2 可观测性补齐

### 建议

新增轻量性能记录，不上重型 APM：

- API middleware 记录 >500ms 请求：path、elapsed、query params 白名单、db busy、当前资源预算。
- SQLite slow query wrapper：只记录 >200ms 的业务查询。
- 任务耗时阶段表：task_id、phase、start/end、bytes、items、resource。
- 前端性能 debug panel：最近 API p95、SSE 状态、任务中心列表耗时。

### 收益

- 后续优化不靠猜。
- 用户报“卡”时能直接定位是 NAS、SQLite、下载、前端渲染还是 API 聚合。

### 风险

- 低。注意不要记录 token/password/path 里的敏感片段。

## 建议执行顺序

### 第一阶段：低风险收益

1. 加 API 慢请求日志和任务阶段耗时。
2. HTTP 直连下载 chunk/throttle 调整。
3. App 顶层 3s 状态刷新合并/降频。
4. 库存索引 badge 增加 SSE 或只在 visible/syncing 时轮询。

### 第二阶段：核心瓶颈

1. `ResourceBudgetService` 接解压、远程 FS、下载、索引。
2. 远程 FS health + 熔断。
3. 任务中心 current items 物化表。

### 第三阶段：结构治理

1. activity batch rollup 物化。
2. ActivityHistory 深度聚合替换。
3. 前端大工作台拆分和路由懒加载。

## 不建议优先做的事

- 不建议把 SQLite 立刻换 PostgreSQL。当前瓶颈更多是请求期聚合、远程 IO 和写入节流，换库不能解决 NAS/FileStation 和前端巨型工作台。
- 不建议把所有轮询都改 WebSocket。任务中心和日志已经 SSE，真正要改的是事件粒度和请求合并。
- 不建议盲目提高并发。这个项目大量操作是慢盘/NAS/压缩/下载，提高并发很容易把吞吐换成长尾卡死。
- 不建议先做视觉层面的前端重构。库存页/字幕/问题作品交互复杂，拆组件必须跟业务链路验证一起做。

## 需要压测确认的指标

- `/api/activity-logs?lite=true`：p50/p95、响应体大小、FTS 搜索 p95。
- `/api/task-center/list?mode=summary/detail`：active 任务 10/100/500 时 p95。
- `/api/conflicts?include_stats=false/true`：远程库正常/超时/凭据失效三种场景。
- 库存全局搜索：索引 ready、索引未 ready fallback、远程库 timeout。
- 大文件下载：1GB/10GB、断点续传、取消响应延迟、SQLite 写入次数。
- 解压：SSD/HDD/NAS，不同并发下总耗时和系统响应。
- 前端：Library/Tasks/ActivityHistory 首屏渲染、切换耗时、内存占用。
